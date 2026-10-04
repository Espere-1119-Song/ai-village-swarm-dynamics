"""Stream the gzipped JSONL tables into parquet (SPEC 2.5, 4.1 step 2).

Each table becomes `data/processed/tables/<name>.parquet` with a fixed schema.
Long free text (raw model output, memory text, tool output) goes to a side
table `<name>_text.parquet` keyed by `id`, so the main tables stay narrow.
Nested JSON values that are kept are stored as JSON strings.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import gzip
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import orjson
import polars as pl
import pyarrow.parquet as pq

S, B, I, F, TS = pl.String, pl.Boolean, pl.Int64, pl.Float64, "ts"
TS_FORMAT = "%Y-%m-%d %H:%M:%S%.f"


def _json(v):
    if v is None or isinstance(v, str):
        return v
    return orjson.dumps(v).decode()


@dataclass
class TableSpec:
    name: str
    columns: dict[str, object]
    text_columns: dict[str, object] = field(default_factory=dict)
    derive: Callable[[dict], tuple[dict, dict]] | None = None
    chunk_rows: int = 50_000

    @property
    def file(self) -> str:
        return f"{self.name}.jsonl.gz"


# --- per-table row transforms ---------------------------------------------
# Each returns (main_row, text_row). Keys absent from the spec are ignored
# by the writer but counted as unknown keys in the QA report.

_EVENT_FIELDS = {
    "speakerId": "speaker_id",
    "speakerType": "speaker_type",
    "chatMessageId": "chat_message_id",
    "previousRoomId": "previous_room_id",
    "agentId": "agent_id",
    "roomId": "room_id",
    "messageId": "message_id",
    "computerUseSessionId": "cu_session_id",
    "startDay": "start_day",
    "endDay": "end_day",
    # SEARCH_HISTORY switched to ISO dates on 2026-07-29.
    "startDate": "start_date",
    "endDate": "end_date",
    "seconds": "seconds",
    "cost": "cost",
    "inputTokens": "input_tokens",
    "outputTokens": "output_tokens",
}
_EVENT_TEXT = {
    "content": "content",
    "query": "query",
    "answerToQuery": "answer",
    "sessionGoal": "session_goal",
    "summary": "summary",
    "nextSessionGoal": "next_session_goal",
    "output": "output",
    # Viewer display names. Kept only under data/ to identify scaffolding
    # accounts such as the auto-nudger. Never written to outputs.
    "speakerName": "speaker_name",
}
# Dropped from the full payload copy: raw model output (stored above) and
# viewer names from USER_NAME_CHANGE.
_EVENT_DROP = {"output", "speakerName", "oldName", "newName"}


def _derive_event(r: dict) -> tuple[dict, dict]:
    d = r.get("data") or {}
    main = {k: r.get(k) for k in ("id", "event_index", "village_id", "created_at", "updated_at")}
    main["action_type"] = d.get("actionType")
    main["data_keys"] = ",".join(sorted(d.keys()))
    for src, dst in _EVENT_FIELDS.items():
        main[dst] = d.get(src)
    text = {"id": r.get("id")}
    for src, dst in _EVENT_TEXT.items():
        text[dst] = _json(d.get(src))
    text["data_json"] = _json({k: v for k, v in d.items() if k not in _EVENT_DROP})
    main["content_len"] = len(text["content"]) if text["content"] else None
    return main, text


def _derive_turn(r: dict) -> tuple[dict, dict]:
    a = r.get("agent_action")
    if isinstance(a, dict):
        name = a.get("action") or a.get("type") or ("bash" if "command" in a else None)
    else:
        name = None
    main = {
        k: r.get(k)
        for k in (
            "id", "session_id", "system", "screenshot_is_redacted",
            "has_redaction_been_overruled", "created_at", "updated_at",
        )
    }
    main["action_name"] = name
    main["action_keys"] = ",".join(sorted(a.keys())) if isinstance(a, dict) else None
    main["agent_action"] = _json(a)
    out, err = r.get("output"), r.get("error")
    main["output_len"] = len(out) if isinstance(out, str) else None
    main["error_len"] = len(err) if isinstance(err, str) else None
    text = {
        "id": r.get("id"),
        "output": _json(out),
        "error": _json(err),
        "agent_messages": _json(r.get("agent_messages")),
    }
    return main, text


def _derive_memory(r: dict) -> tuple[dict, dict]:
    c = r.get("content")
    main = {k: r.get(k) for k in ("id", "agent_id", "created_at", "updated_at")}
    main["content_len"] = len(c) if isinstance(c, str) else None
    return main, {"id": r.get("id"), "content": c}


def _derive_cc_message(r: dict) -> tuple[dict, dict]:
    main = {
        k: r.get(k)
        for k in (
            "id", "agent_id", "sdk_session_id", "message_type", "message_subtype",
            "message_uuid", "created_at",
        )
    }
    return main, {"id": r.get("id"), "content": _json(r.get("content"))}


_STAMPS = {"created_at": TS, "updated_at": TS}

SPECS: dict[str, TableSpec] = {
    s.name: s
    for s in [
        TableSpec("agents", {
            "id": S, "name": S, "model_string": S, "goal": S, "status_message": S,
            "is_participating": B, "is_pending": B, "is_updating_memory": B,
            "is_paused_for_google_sign_in": B, "input_tokens_used": I,
            "output_tokens_used": I, "last_seen_event_index": I, "paused_until": S,
            "paused_until_task_id": S, "current_computer_use_session_id": S,
            "current_human_use_session_request_id": S, "current_room_id": S,
            "money": S, "emoji": S, "village_id": S, **_STAMPS,
        }),
        TableSpec("villages", {
            "id": S, "name": S, "slug": S, "village_goal": S, "active_agent_id": S,
            "turn_id": S, "schedule": S, "is_chat_open": B, **_STAMPS,
        }),
        TableSpec("village_goals", {
            "id": S, "goal": S, "start_time": TS, "end_time": TS, "village_id": S, **_STAMPS,
        }),
        TableSpec("agent_goals", {
            "id": S, "agent_id": S, "name": S, "short_name": S, "description": S,
            "start_time": TS, "end_time": TS, **_STAMPS,
        }),
        TableSpec("chat_rooms", {
            "id": S, "name": S, "deleted_at": TS, "village_id": S,
            "whitelisted_agent_names": S, "blacklisted_agent_names": S,
            "last_nudger_run_at": TS, "last_nudger_run_chat_message_id": S, **_STAMPS,
        }),
        TableSpec("chat_messages", {
            "id": S, "speaker_type": S, "agent_speaker_id": S, "user_speaker_id": S,
            "content": S, "room_id": S, "has_been_approved": B, **_STAMPS,
        }),
        TableSpec("computer_use_sessions", {
            "id": S, "agent_id": S, "session_goal": S, "short_displayed_session_goal": S,
            "has_been_asked_to_stop": B, "village_id": S, **_STAMPS,
        }),
        TableSpec("summaries", {
            "id": S, "type": S, "summary_target": S, "summary_date": S, "content": S,
            "generated_by": S, "village_id": S, **_STAMPS,
        }),
        TableSpec("claude_code_sessions", {
            "id": S, "agent_id": S, "sdk_session_id": S, **_STAMPS,
        }),
        TableSpec(
            "events",
            {
                "id": S, "event_index": I, "village_id": S, "action_type": S, "data_keys": S,
                **{v: S for v in (
                    "speaker_id", "speaker_type", "chat_message_id", "previous_room_id",
                    "agent_id", "room_id", "message_id", "cu_session_id",
                )},
                "start_day": S, "end_day": S, "start_date": S, "end_date": S, "seconds": F, "cost": F,
                "input_tokens": F, "output_tokens": F, "content_len": I, **_STAMPS,
            },
            text_columns={"id": S, **{v: S for v in _EVENT_TEXT.values()}, "data_json": S},
            derive=_derive_event,
        ),
        TableSpec(
            "computer_use_turns",
            {
                "id": S, "session_id": S, "action_name": S, "action_keys": S,
                "agent_action": S, "output_len": I, "error_len": I, "system": S,
                "screenshot_is_redacted": B, "has_redaction_been_overruled": B, **_STAMPS,
            },
            text_columns={"id": S, "output": S, "error": S, "agent_messages": S},
            derive=_derive_turn,
            chunk_rows=20_000,
        ),
        TableSpec(
            "agent_memories",
            {"id": S, "agent_id": S, "content_len": I, **_STAMPS},
            text_columns={"id": S, "content": S},
            derive=_derive_memory,
            chunk_rows=10_000,
        ),
        TableSpec(
            "claude_code_messages",
            {
                "id": S, "agent_id": S, "sdk_session_id": S, "message_type": S,
                "message_subtype": S, "message_uuid": S, "created_at": TS,
            },
            text_columns={"id": S, "content": S},
            derive=_derive_cc_message,
        ),
    ]
}


def _frame(rows: list[dict], columns: dict[str, object]) -> pl.DataFrame:
    schema = {k: (S if v == TS else v) for k, v in columns.items()}
    clean = []
    for r in rows:
        row = {}
        for k, t in schema.items():
            v = r.get(k)
            if t == S and v is not None and not isinstance(v, str):
                v = _json(v)
            elif t in (I, F) and isinstance(v, str):
                try:
                    v = float(v) if t == F else int(v)
                except ValueError:
                    v = None
            row[k] = v
        clean.append(row)
    df = pl.DataFrame(clean, schema=schema, strict=False, orient="row")
    ts_cols = [k for k, v in columns.items() if v == TS]
    return df.with_columns(
        pl.col(c).str.to_datetime(TS_FORMAT, time_unit="us", time_zone="UTC", strict=False)
        for c in ts_cols
    )


@dataclass
class IngestStats:
    rows: int = 0
    unknown_keys: Counter = field(default_factory=Counter)
    bad_json: int = 0
    raw_ts_nonnull: Counter = field(default_factory=Counter)
    keys_by_type: dict = field(default_factory=lambda: defaultdict(Counter))


def convert_table(spec: TableSpec, raw_dir: Path, out_dir: Path) -> IngestStats:
    out_dir.mkdir(parents=True, exist_ok=True)
    src = raw_dir / spec.file
    main_path = out_dir / f"{spec.name}.parquet"
    text_path = out_dir / f"{spec.name}_text.parquet"
    known_raw = set(spec.columns) | {"data", "agent_messages", "output", "error", "content"}
    ts_cols = [k for k, v in spec.columns.items() if v == TS]
    stats = IngestStats()
    writers: dict[str, pq.ParquetWriter] = {}

    def flush(main_rows, text_rows):
        for path, rows, cols in (
            (main_path, main_rows, spec.columns),
            (text_path, text_rows, spec.text_columns),
        ):
            if not rows or not cols:
                continue
            table = _frame(rows, cols).to_arrow()
            if str(path) not in writers:
                writers[str(path)] = pq.ParquetWriter(path, table.schema, compression="zstd")
            writers[str(path)].write_table(table)

    main_rows, text_rows = [], []
    with gzip.open(src, "rb") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = orjson.loads(line)
            except orjson.JSONDecodeError:
                stats.bad_json += 1
                continue
            stats.rows += 1
            for k in r.keys() - known_raw:
                stats.unknown_keys[k] += 1
            for c in ts_cols:
                if r.get(c) is not None:
                    stats.raw_ts_nonnull[c] += 1
            if spec.derive:
                m, t = spec.derive(r)
                if spec.name == "events":
                    stats.keys_by_type[m["action_type"]][m["data_keys"]] += 1
                elif spec.name == "computer_use_turns":
                    stats.keys_by_type[m["action_name"]][m["action_keys"]] += 1
            else:
                m, t = r, None
            main_rows.append(m)
            if t is not None:
                text_rows.append(t)
            if len(main_rows) >= spec.chunk_rows:
                flush(main_rows, text_rows)
                main_rows, text_rows = [], []
    flush(main_rows, text_rows)
    for w in writers.values():
        w.close()
    return stats
