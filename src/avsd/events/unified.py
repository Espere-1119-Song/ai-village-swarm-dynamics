"""Unified event table (SPEC 4.1 step 3, docs/decisions.md "Unified event table conventions").

One row per chat message, emitted event, computer-use session, turn, memory
snapshot and summary, with a common schema (`UNIFIED_SCHEMA`):

- **chat**: every `chat_messages` row. Its AGENT_TALK/USER_TALK event is linked
  (`src_event_id`, `event_index`, cost and tokens), not emitted.
- **event**: all events except linked talk events, START_USING_COMPUTER
  (carried by the session row) and USER_NAME_CHANGE (viewer renames, counted
  in QA only). The 57 USER_TALK events without a chat row are emitted with
  `chat_row_missing`.
- **session**: one `session_start` per `computer_use_sessions` row; its START
  event (if any) gives `src_event_id`, cost and tokens.
- **turn**: every turn. Turns that mirror a chat row or an event keep
  `dup_of_uid`; the mirrored row has `linked_uid` pointing back at the turn.
- **memory**: every snapshot, with the module B1 versions
  (`memory_versions.classify_memory_rows`) and `linked_uid` to the STOP or
  CONSOLIDATE event written 0-1 s after it.
- **summary**: every summary, timed by `updated_at`.

Actors: agents by id (events keyed by `coalesce(agent_id, speaker_id)`, never
`speaker_type`); every human is `human`; scaffolding rows are
`system:nudger` (bot chat account), `system:scaffold` and
`system:summarizer`. Raw user ids go only to `data/processed/human_ids.parquet`.
Human and system rows that concern one agent keep it in `target_agent_id`;
for an auto-nudge that is the agent of its leading `@<agent name>`.

Text, one rule for every source: `text` holds at most TEXT_MAX chars of the
row's own text (chat content; search query, CONSOLIDATE next goal, STOP
summary, helper-request goal and orphan human message for events; session
goal; the turn's agent_action command, text, content, query, element
description or helper-request goal), `text_len` is the full length (so on a
row with inline text, `text_len > TEXT_MAX` marks a cut), and `text_ref`
(`<table>:<id>`, set on every row) names the record that holds the full text:
`chat_messages`, `events_text` (also the full payload), `computer_use_sessions`,
`computer_use_turns` (agent_action; the turn's output, error and provider
response are in `computer_use_turns_text` under the same id),
`agent_memories_text` and `summaries`. Memory snapshots and summaries have no
inline text. Outreach payloads name third parties and are by reference only.
`refs` come from the full text the actor produced, `refs_obs` from tool
output, errors and search answers, minus refs already in `refs` (both in
order of first appearance). Memory snapshots and summaries get no refs.

`linked_uid`: for a chat or event row, the turn that issued it (that turn has
`dup_of_uid`); for a memory row, the STOP/CONSOLIDATE event 0-1 s after it.

`session_id`: turns their session; session rows their own id; CONSOLIDATE its
`cu_session_id`; STOP the agent's latest session at or before it; rows a turn
mirrors the turn's session; memory the label's session UUID (if it is a
session of the agent), else its linked end event's session, else the latest
session; other agent chat and event rows the agent's session open at that
time (created before, not yet closed; a session without STOP or CONSOLIDATE
closes at its last turn).

Rooms: `agent_room_id` on agent rows (`assign_agent_rooms`) and the same rule
as spells per agent in `agent_room_intervals` (exposure lookups, module B2;
retired agents stay in their last room, so combine with roster activity).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pyarrow.parquet as pq

from avsd.events.links import greedy_match, window_candidates
from avsd.events.memory_versions import REGIME_TOLERANCE_S, RELS, classify_memory_rows
from avsd.events.refs import extract_refs_batch
from avsd.events.runs import SCHEDULE_LABELS

SOURCES = ("chat", "event", "session", "turn", "memory", "summary")
KINDS = (
    "agent_msg", "human_msg", "system_msg", "session_start", "session_end", "turn",
    "memory_write", "search_history", "wait", "pause", "other",
)
ACTOR_TYPES = ("agent", "human", "system")
TURN_KINDS = ("tool_action", "talk_only", "malformed_call", "bash_restart")
ROOMS_ERAS = ("R0", "R1", "R2", "R3")
REGIMES_CU = ("pre", "post")

BOT_USER_ID = "445ab51c-3bb1-4475-a536-67f1924b06cf"  # auto-nudger and run markers
HUMAN, NUDGER = "human", "system:nudger"
SCAFFOLD, SUMMARIZER = "system:scaffold", "system:summarizer"

VILLAGE_DAY1 = date(2025, 4, 2)
ROOMS_START = date(2026, 3, 5)  # every agent is in `general` before this PT date
ROOMS_ERA_STARTS = ((date(2026, 2, 25), "R1"), (date(2026, 3, 16), "R2"), (date(2026, 7, 6), "R3"))
TEXT_MAX = 2000  # chars of text kept inline on any row
# agent_action keys whose value the agent wrote (first non-null wins): bash,
# typed text, chat, search query, UI element description, helper-request goal.
TURN_TEXT_KEYS = ("command", "text", "content", "query", "description", "sessionGoal")
EXPECTED_ROOM_SPELLS = 466  # from room-carrying events: 46 first rooms + 420 changes (verification)
ROOM_INTERVAL_SCHEMA: dict[str, pl.DataType] = {
    "agent_id": pl.String,
    "spell": pl.Int32,
    "room_id": pl.String,
    "start": pl.Datetime("us", "UTC"),
    "end": pl.Datetime("us", "UTC"),
    "opened_by": pl.String,
    "start_event_uid": pl.String,
}

SEND_WINDOW_S = (0.0, 300.0)  # send_message turn -> chat row
SEARCH_WINDOW_S = 120.0  # |turn - SEARCH_HISTORY event|
EVENT_WINDOW_S = (0.0, 120.0)  # other tool turns -> their event
MEMORY_WINDOW_S = 1.0  # memory row -> STOP/CONSOLIDATE after it
# Turn action -> the event type it duplicates (send_message and search_history aside).
TURN_EVENT_LINKS = {
    "pause": "PAUSE",
    "move_to_room": "ENTER_ROOM",
    "request_Google_sign_in": "REQUEST_GOOGLE_SIGN_IN",
    "request_approval_for_unsolicited_outreach": "OUTREACH_APPROVAL_REQUEST",
    "request_human_helper": "REQUEST_HUMAN_HELPER",
    "cancel_request_for_human_helper": "CANCEL_REQUEST_FOR_HUMAN_HELPER",
}
# Daily pause/resume markers (bot and staff), schema_notes 4.6.
RUN_MARKER_RE = (
    r"(?i)^\s*(?:pausing the village for today|resum(?:e|ing) (?:the village )?for today)"
    r"|(?i)\b(?:pausing|resuming) (?:the )?village\b"
)
# A tool call in a raw provider response (null agent_action = malformed call).
TOOL_CALL_RE = (
    r'"type"\s*:\s*"(?:tool_use|function_call|computer_call)"'
    r'|"tool_calls"\s*:\s*\[\s*\{|"functionCall"'
)
OUTPUT_KEY_RE = r"(?:^|,)output(?:,|$)"

UNIFIED_SCHEMA: dict[str, pl.DataType] = {
    "event_uid": pl.String,
    "source": pl.Enum(SOURCES),
    "kind": pl.Enum(KINDS),
    "subkind": pl.String,
    "ts_utc": pl.Datetime("us", "UTC"),
    "ts_pt": pl.Datetime("us", "America/Los_Angeles"),
    "village_day": pl.Int32,
    "run_day": pl.Int32,
    "realization_id": pl.Int32,
    "block": pl.Int16,
    "in_run": pl.Boolean,
    "t_in_day": pl.Float64,
    "t_active": pl.Float64,
    "actor_id": pl.String,
    "actor_type": pl.Enum(ACTOR_TYPES),
    "model": pl.String,
    "model_family": pl.String,
    "provider": pl.String,
    "scaffold": pl.String,
    "room_id": pl.String,
    "agent_room_id": pl.String,
    "previous_room_id": pl.String,
    "session_id": pl.String,
    "goal_id": pl.String,
    "agent_goal_id": pl.String,
    "target_agent_id": pl.String,
    "text": pl.String,
    "text_ref": pl.String,
    "text_len": pl.Int64,
    "refs": pl.List(pl.String),
    "refs_obs": pl.List(pl.String),
    "src_event_id": pl.String,
    "event_index": pl.Int64,
    "cost": pl.Float64,
    "input_tokens": pl.Float64,
    "output_tokens": pl.Float64,
    "dup_of_uid": pl.String,
    "linked_uid": pl.String,
    "chat_row_missing": pl.Boolean,
    "is_run_marker": pl.Boolean,
    "turn_kind": pl.Enum(TURN_KINDS),
    "regime_cu": pl.Enum(REGIMES_CU),
    "rooms_era": pl.Enum(ROOMS_ERAS),
    "schedule_regime": pl.Enum(SCHEDULE_LABELS),
    "version_idx": pl.Int32,
    "parent_uid": pl.String,
    "input_row_uid": pl.String,
    "is_generation": pl.Boolean,
    "rel": pl.Enum(RELS),
    "drop_version": pl.Boolean,
    "summary_regenerated": pl.Boolean,
    "summary_is_latest": pl.Boolean,
    "search_start_day": pl.Int32,
    "search_end_day": pl.Int32,
}


def _secs(expr: pl.Expr) -> pl.Expr:
    return expr.dt.total_microseconds() / 1e6


def _uid(prefix: str, col: str = "id") -> pl.Expr:
    return (pl.lit(prefix + ":") + pl.col(col)).alias("event_uid")


def _refs(df: pl.DataFrame, text: pl.Expr, name: str = "refs") -> pl.DataFrame:
    """Add a refs column extracted from `text` (vectorised, see refs.py)."""
    s = df.select(text.alias("_t"))["_t"]
    return df.with_columns(extract_refs_batch(s).alias(name))


def list_minus(df: pl.DataFrame, col: str, other: str) -> pl.Series:
    """`col` without the elements of `other`, row by row, in the order of `col`.

    Null lists count as empty. Unlike `list.set_difference`, the order of
    first appearance survives.
    """
    x = df.select(pl.col(col).alias("_v"), pl.col(other).alias("_o")).with_row_index("_r")
    a = (x.select("_r", "_v").explode("_v", empty_as_null=True).drop_nulls("_v")
         .with_row_index("_p"))
    b = (x.select("_r", pl.col("_o").alias("_v")).explode("_v", empty_as_null=True)
         .drop_nulls("_v").unique())
    kept = (a.join(b, on=["_r", "_v"], how="anti").sort("_p")
            .group_by("_r", maintain_order=True).agg("_v"))
    out = x.select("_r").join(kept, on="_r", how="left", maintain_order="left")
    return out["_v"].fill_null(pl.lit([], dtype=pl.List(pl.String))).alias(col)


def mention_target(texts: pl.Series, agent_names: dict[str, str]) -> pl.Series:
    """Agent id named by a leading `@<agent name>` (longest name first, any case), else null."""
    names = sorted(((n.lower(), a) for a, n in agent_names.items()), key=lambda x: -len(x[0]))

    def one(s: str | None) -> str | None:
        s = (s or "").lstrip()
        if not s.startswith("@"):
            return None
        rest = s[1:].lower()
        for name, agent in names:
            tail = rest[len(name):] if rest.startswith(name) else None
            # The name must end there: not "@GPT-5" inside "@GPT-5.1".
            if tail is not None and not (tail[:1].isalnum() or tail[:1] in ("-", "_")
                                         or (tail[:1] == "." and tail[1:2].isalnum())):
                return agent
        return None

    return pl.Series([one(s) for s in texts.to_list()], dtype=pl.String)


def _actor_type(expr: pl.Expr) -> pl.Expr:
    return expr.cast(pl.Enum(ACTOR_TYPES))


# --- inputs -------------------------------------------------------------------

def load_events(tables: Path) -> pl.DataFrame:
    """All events with the agent key used for rooms and links."""
    ev = pl.read_parquet(
        tables / "events.parquet",
        columns=[
            "id", "event_index", "action_type", "data_keys", "speaker_id", "agent_id",
            "room_id", "previous_room_id", "message_id", "cu_session_id", "start_day",
            "end_day", "start_date", "end_date", "cost", "input_tokens", "output_tokens",
            "created_at",
        ],
    )
    return ev.with_columns(
        pl.coalesce(
            "agent_id", pl.when(pl.col("action_type") == "AGENT_TALK").then(pl.col("speaker_id"))
        ).alias("akey")
    )


def load_sessions(tables: Path, ev: pl.DataFrame, turns_last: pl.DataFrame) -> pl.DataFrame:
    """Sessions with their START, CONSOLIDATE and STOP events and end time.

    CONSOLIDATE closes the session named by `cu_session_id`; STOP has no
    session key and closes the agent's latest session created at or before
    it. `end_ts` is the earliest closing event, else the last turn.
    """
    s = pl.read_parquet(
        tables / "computer_use_sessions.parquet",
        columns=["id", "agent_id", "session_goal", "created_at"],
    )
    start = (
        ev.filter(pl.col("action_type") == "START_USING_COMPUTER")
        .sort("event_index")
        .group_by("cu_session_id", maintain_order=True)
        .first()
        .select(
            pl.col("cu_session_id").alias("id"), pl.col("id").alias("start_event_id"),
            pl.col("event_index").alias("start_event_index"),
            pl.col("room_id").alias("start_room_id"),
            pl.col("cost").alias("start_cost"), pl.col("input_tokens").alias("start_input_tokens"),
            pl.col("output_tokens").alias("start_output_tokens"),
            pl.col("data_keys").str.contains(OUTPUT_KEY_RE).alias("start_has_output"),
        )
    )
    cons = (
        ev.filter(pl.col("action_type") == "CONSOLIDATE")
        .group_by("cu_session_id")
        .agg(pl.col("created_at").min().alias("cons_ts"), pl.len().alias("n_cons"))
        .rename({"cu_session_id": "id"})
    )
    stops = stop_sessions(ev, s)
    stop_agg = stops.group_by("session_id").agg(
        pl.col("stop_ts").min(), pl.len().alias("n_stop")
    ).rename({"session_id": "id"})
    out = (
        s.join(start, on="id", how="left")
        .join(cons, on="id", how="left")
        .join(stop_agg, on="id", how="left")
        .join(turns_last.rename({"session_id": "id"}), on="id", how="left")
        .with_columns(
            pl.min_horizontal("cons_ts", "stop_ts").alias("close_ts"),
        )
        .with_columns(pl.coalesce("close_ts", "last_turn_ts").alias("end_ts"))
        .with_columns(
            pl.when(pl.col("start_event_id").is_not_null() & pl.col("cons_ts").is_not_null())
            .then(pl.lit("both"))
            .when(pl.col("start_event_id").is_not_null()).then(pl.lit("start_only"))
            .when(pl.col("cons_ts").is_not_null()).then(pl.lit("consolidate_only"))
            .otherwise(pl.lit("neither"))
            .alias("category")
        )
    )
    return out


def stop_sessions(ev: pl.DataFrame, sessions: pl.DataFrame) -> pl.DataFrame:
    """STOP_USING_COMPUTER event id -> the agent's latest session created at or before it."""
    stops = (
        ev.filter(pl.col("action_type") == "STOP_USING_COMPUTER")
        .select(pl.col("id").alias("stop_id"), pl.col("akey").alias("agent_id"),
                pl.col("created_at").alias("stop_ts"))
        .sort("stop_ts")
    )
    sa = sessions.select(pl.col("id").alias("session_id"), "agent_id",
                         pl.col("created_at").alias("s_ts")).sort("s_ts")
    return stops.join_asof(sa, left_on="stop_ts", right_on="s_ts", by="agent_id",
                           strategy="backward", check_sortedness=False)


# --- sources ------------------------------------------------------------------

def build_chat(
    tables: Path, ev: pl.DataFrame, agent_names: dict[str, str], stats: dict
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Chat rows and the raw-user-id side table.

    Auto-nudges get the agent of their leading `@<agent name>` as
    `target_agent_id` (`agent_names`: agent id -> name).
    """
    cm = pl.read_parquet(
        tables / "chat_messages.parquet",
        columns=["id", "speaker_type", "agent_speaker_id", "user_speaker_id", "content",
                 "room_id", "created_at"],
    )
    talk = ev.filter(pl.col("action_type").is_in(["AGENT_TALK", "USER_TALK"]))
    linked = talk.filter(pl.col("message_id").is_in(cm["id"].implode()))
    stats["chat_talk"] = {
        "talk_events": talk.height,
        "linked": linked.height,
        "linked_distinct_chat": linked["message_id"].n_unique(),
        "orphans": talk.height - linked.height,
        "chat_without_talk": cm.height - linked["message_id"].n_unique(),
        "room_mismatch": int(
            linked.join(cm.select("id", pl.col("room_id").alias("cm_room")),
                        left_on="message_id", right_on="id")
            .filter(pl.col("room_id") != pl.col("cm_room")).height
        ),
    }
    if linked.height != linked["message_id"].n_unique():
        raise ValueError("a chat message has more than one talk event")
    link = linked.select(
        pl.col("message_id").alias("id"), pl.col("id").alias("src_event_id"), "event_index",
        "cost", "input_tokens", "output_tokens",
    )
    is_agent = pl.col("speaker_type") == "agent"
    is_bot = pl.col("user_speaker_id") == BOT_USER_ID
    marker = ~is_agent & pl.col("content").fill_null("").str.contains(RUN_MARKER_RE)
    df = (
        cm.join(link, on="id", how="left")
        .with_columns(
            _uid("chat"),
            pl.lit("chat").alias("source"),
            pl.when(is_agent).then(pl.lit("agent_msg")).when(is_bot).then(pl.lit("system_msg"))
            .otherwise(pl.lit("human_msg")).alias("kind"),
            pl.when(is_agent).then(pl.lit(None, pl.String))
            .when(marker).then(pl.lit("run_marker"))
            .when(is_bot).then(pl.lit("nudge")).alias("subkind"),
            pl.col("created_at").alias("ts_utc"),
            pl.when(is_agent).then(pl.col("agent_speaker_id")).when(is_bot).then(pl.lit(NUDGER))
            .otherwise(pl.lit(HUMAN)).alias("actor_id"),
            _actor_type(pl.when(is_agent).then(pl.lit("agent")).when(is_bot).then(pl.lit("system"))
                        .otherwise(pl.lit("human"))).alias("actor_type"),
            pl.col("content").alias("text"),
            (pl.lit("chat_messages:") + pl.col("id")).alias("text_ref"),
            pl.col("content").str.len_chars().fill_null(0).cast(pl.Int64).alias("text_len"),
            marker.alias("is_run_marker"),
            pl.lit(False).alias("chat_row_missing"),
        )
    )
    df = df.with_columns(
        pl.when(pl.col("subkind") == "nudge")
        .then(mention_target(df["content"], agent_names)).alias("target_agent_id")
    )
    nudges = df.filter(pl.col("subkind") == "nudge")
    stats["nudge_targets"] = {"nudges": nudges.height,
                              "with_target": int(nudges["target_agent_id"].is_not_null().sum())}
    df = _refs(df, pl.col("content"))
    humans = df.filter(~is_agent).select(
        "event_uid", pl.col("user_speaker_id").alias("user_id"), is_bot.alias("is_bot")
    )
    return df.drop("speaker_type", "agent_speaker_id", "user_speaker_id", "content",
                   "created_at", "id"), humans


def _event_text(tables: Path, ids: pl.Series) -> pl.DataFrame:
    return (
        pl.scan_parquet(tables / "events_text.parquet")
        .filter(pl.col("id").is_in(ids.implode()))
        .select("id", "query", "session_goal", "summary", "next_session_goal", "content", "answer")
        .collect()
    )


def _event_payload(tables: Path, ids: pl.Series) -> pl.DataFrame:
    return (
        pl.scan_parquet(tables / "events_text.parquet")
        .filter(pl.col("id").is_in(ids.implode()))
        .select(
            "id",
            pl.col("data_json").str.json_path_match("$.endReason").alias("end_reason"),
            pl.col("data_json").str.json_path_match("$.messageContent").alias("message_content"),
        )
        .collect()
    )


def _day_number(day: pl.Expr, iso: pl.Expr) -> pl.Expr:
    """SEARCH_HISTORY range bound as a village day (integer day or ISO date)."""
    from_iso = (
        iso.str.slice(0, 10).str.to_date("%Y-%m-%d", strict=False) - pl.lit(VILLAGE_DAY1)
    ).dt.total_days() + 1
    return pl.coalesce(day.cast(pl.Int64, strict=False), from_iso).cast(pl.Int32)


def build_events_rows(tables: Path, ev: pl.DataFrame, chat_event_ids: pl.Series,
                      stats: dict) -> pl.DataFrame:
    """Event rows: all events minus linked talk, START and USER_NAME_CHANGE."""
    at = pl.col("action_type")
    stats["event_types"] = dict(ev.group_by("action_type").len().iter_rows())
    e = ev.filter(
        ~pl.col("id").is_in(chat_event_ids.implode())
        & ~at.is_in(["START_USING_COMPUTER", "USER_NAME_CHANGE"])
    )
    txt = _event_text(tables, e["id"])
    special = e.filter(at.is_in(["STOP_HUMAN_USE_SESSION", "OUTREACH_APPROVAL_REQUEST",
                                 "OUTREACH_APPROVAL_RESPONSE"]))["id"]
    pay = _event_payload(tables, special)
    e = e.join(txt, on="id", how="left").join(pay, on="id", how="left")

    no_output = ~pl.col("data_keys").fill_null("").str.contains(OUTPUT_KEY_RE)
    operator_move = (at == "ENTER_ROOM") & (pl.col("cost").fill_null(0) == 0) & no_output
    user_talk = at == "USER_TALK"
    actor_type = (
        pl.when(user_talk & (pl.col("speaker_id") == BOT_USER_ID)).then(pl.lit("system"))
        .when(user_talk).then(pl.lit("human"))
        .when(at == "OUTREACH_APPROVAL_RESPONSE").then(pl.lit("human"))
        .when(at == "RESTARTING_AFTER_GOOGLE_SIGN_IN").then(pl.lit("system"))
        .when(at == "STOP_HUMAN_USE_SESSION")
        .then(pl.when(pl.col("end_reason") == "user_ended").then(pl.lit("human"))
              .when(pl.col("end_reason") == "user_timeout").then(pl.lit("system"))
              .otherwise(pl.lit("agent")))
        .when(operator_move).then(pl.lit("system"))
        .otherwise(pl.lit("agent"))
    )
    kind = (
        pl.when(at.is_in(["STOP_USING_COMPUTER", "CONSOLIDATE"])).then(pl.lit("session_end"))
        .when(at == "SEARCH_HISTORY").then(pl.lit("search_history"))
        .when(at == "WAIT").then(pl.lit("wait"))
        .when(at == "PAUSE").then(pl.lit("pause"))
        .when(user_talk & (pl.col("speaker_id") == BOT_USER_ID)).then(pl.lit("system_msg"))
        .when(user_talk).then(pl.lit("human_msg"))
        .otherwise(pl.lit("other"))
    )
    subkind = (
        pl.when(at == "STOP_USING_COMPUTER").then(pl.lit("stop"))
        .when(at == "CONSOLIDATE").then(pl.lit("consolidate"))
        .otherwise(at.str.to_lowercase())
    )
    text = (
        pl.when(at == "SEARCH_HISTORY").then(pl.col("query"))
        .when(at == "CONSOLIDATE").then(pl.col("next_session_goal"))
        .when(at.is_in(["STOP_USING_COMPUTER", "STOP_HUMAN_USE_SESSION"])).then(pl.col("summary"))
        .when(at == "REQUEST_HUMAN_HELPER").then(pl.col("session_goal"))
        .when(user_talk).then(pl.col("content"))
    )
    # Outreach payloads name third parties: text by reference only.
    text_len = pl.coalesce(text.str.len_chars(), pl.col("message_content").str.len_chars(),
                           pl.lit(0))
    e = e.with_columns(
        _uid("event"),
        pl.lit("event").alias("source"),
        kind.alias("kind"),
        subkind.alias("subkind"),
        pl.col("created_at").alias("ts_utc"),
        _actor_type(actor_type).alias("actor_type"),
        text.alias("text"),
        (pl.lit("events_text:") + pl.col("id")).alias("text_ref"),
        text_len.cast(pl.Int64).alias("text_len"),
        pl.col("id").alias("src_event_id"),
        user_talk.alias("chat_row_missing"),
        (user_talk & pl.col("content").fill_null("").str.contains(RUN_MARKER_RE))
        .alias("is_run_marker"),
        _day_number(pl.col("start_day"), pl.col("start_date")).alias("search_start_day"),
        _day_number(pl.col("end_day"), pl.col("end_date")).alias("search_end_day"),
    ).with_columns(
        pl.when(pl.col("actor_type") == "agent").then(pl.col("akey"))
        .when(pl.col("actor_type") == "human").then(pl.lit(HUMAN))
        .when(user_talk).then(pl.lit(NUDGER))
        .otherwise(pl.lit(SCAFFOLD)).alias("actor_id"),
        pl.when(pl.col("actor_type") != "agent").then(pl.col("agent_id")).alias("target_agent_id"),
    )
    actor_text = pl.when(at == "OUTREACH_APPROVAL_REQUEST").then(pl.col("message_content")) \
        .when(at != "OUTREACH_APPROVAL_RESPONSE").then(pl.col("text"))
    e = _refs(e, actor_text)
    e = _refs(e, pl.col("answer"), "refs_obs")
    e = e.with_columns(list_minus(e, "refs_obs", "refs"))
    stats["event_actor_rules"] = dict(
        e.filter(pl.col("actor_type") != "agent").group_by("action_type").len().iter_rows()
    )
    return e.select(
        "event_uid", "source", "kind", "subkind", "ts_utc", "actor_id", "actor_type", "room_id",
        "previous_room_id", "target_agent_id", "text", "text_ref", "text_len", "refs", "refs_obs",
        "src_event_id", "event_index", "cost", "input_tokens", "output_tokens",
        "chat_row_missing", "is_run_marker", "search_start_day", "search_end_day",
        pl.col("id").alias("_id"), pl.col("action_type").alias("_action_type"),
        pl.col("cu_session_id").alias("_cu_session_id"),
        pl.col("speaker_id").alias("_speaker_id"),
    )


def build_session_rows(sessions: pl.DataFrame) -> pl.DataFrame:
    """One session_start per session; "Start up" starts with cost 0 and no output are system."""
    startup = (
        (pl.col("session_goal") == "Start up")
        & (pl.col("start_cost").fill_null(-1) == 0)
        & ~pl.col("start_has_output").fill_null(True)
    )
    df = sessions.with_columns(
        _uid("session"),
        pl.lit("session").alias("source"),
        pl.lit("session_start").alias("kind"),
        pl.col("category").alias("subkind"),
        pl.col("created_at").alias("ts_utc"),
        pl.when(startup).then(pl.lit(SCAFFOLD)).otherwise(pl.col("agent_id")).alias("actor_id"),
        _actor_type(pl.when(startup).then(pl.lit("system")).otherwise(pl.lit("agent")))
        .alias("actor_type"),
        pl.when(startup).then(pl.col("agent_id")).alias("target_agent_id"),
        pl.col("start_room_id").alias("room_id"),
        pl.col("id").alias("session_id"),
        pl.col("session_goal").alias("text"),
        (pl.lit("computer_use_sessions:") + pl.col("id")).alias("text_ref"),
        pl.col("session_goal").str.len_chars().fill_null(0).cast(pl.Int64).alias("text_len"),
        pl.col("start_event_id").alias("src_event_id"),
        pl.col("start_event_index").alias("event_index"),
        pl.col("start_cost").alias("cost"),
        pl.col("start_input_tokens").alias("input_tokens"),
        pl.col("start_output_tokens").alias("output_tokens"),
    )
    df = _refs(df, pl.col("session_goal"))
    return df.select(
        "event_uid", "source", "kind", "subkind", "ts_utc", "actor_id", "actor_type",
        "target_agent_id", "room_id", "session_id", "text", "text_ref", "text_len", "refs",
        "src_event_id", "event_index", "cost", "input_tokens", "output_tokens",
    )


def _turn_obs_refs(tables: Path, batch_rows: int = 250_000) -> pl.DataFrame:
    """refs from tool output and error text, one row group batch at a time."""
    pf = pq.ParquetFile(tables / "computer_use_turns_text.parquet")
    parts = []
    for batch in pf.iter_batches(batch_size=batch_rows, columns=["id", "output", "error"]):
        b = pl.from_arrow(batch)
        text = b.select(
            pl.concat_str([pl.col("output"), pl.col("error")], separator="\n", ignore_nulls=True)
        ).to_series()
        refs = extract_refs_batch(text)
        parts.append(b.select("id").with_columns(refs.alias("refs_obs_raw"))
                     .filter(pl.col("refs_obs_raw").list.len() > 0))
    return pl.concat(parts) if parts else pl.DataFrame(
        schema={"id": pl.String, "refs_obs_raw": pl.List(pl.String)})


def _malformed_null_turns(tables: Path, ids: pl.Series) -> pl.DataFrame:
    """Null-action turns whose provider response holds a tool call."""
    return (
        pl.scan_parquet(tables / "computer_use_turns_text.parquet")
        .filter(pl.col("id").is_in(ids.implode()))
        .select("id", pl.col("agent_messages").fill_null("").str.contains(TOOL_CALL_RE)
                .alias("has_call"))
        .collect()
    )


def build_turn_rows(
    tables: Path, sessions: pl.DataFrame, ev: pl.DataFrame, chat: pl.DataFrame, stats: dict
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Turn rows with dup_of_uid, and the reverse links (uid -> turn uid)."""
    t = (
        pl.scan_parquet(tables / "computer_use_turns.parquet")
        .select("id", "session_id", "action_name", "action_keys", "agent_action", "error_len",
                "created_at")
        .collect()
        .join(sessions.select(pl.col("id").alias("session_id"), "agent_id"), on="session_id",
              how="left")
    )
    aa = pl.col("agent_action")
    # Agent-written text keys; outreach keys (recipient, messageContent) stay out.
    full = pl.coalesce(*[aa.str.json_path_match(f"$.{k}") for k in TURN_TEXT_KEYS])
    t = t.with_columns(full.alias("_full"))
    null_ids = t.filter(aa.is_null())["id"]
    mal = _malformed_null_turns(tables, null_ids)
    t = t.join(mal, on="id", how="left")
    turn_kind = (
        pl.when(aa.is_null() & pl.col("has_call").fill_null(False)).then(pl.lit("malformed_call"))
        .when(aa.is_null()).then(pl.lit("talk_only"))
        .when(pl.col("action_name").is_null() & (pl.col("action_keys") == "restart"))
        .then(pl.lit("bash_restart"))
        .when(pl.col("action_name").is_null()).then(pl.lit("malformed_call"))
        .otherwise(pl.lit("tool_action"))
    )

    # --- duplicate links ---------------------------------------------------
    links: list[pl.DataFrame] = []
    # send_message -> chat row: same agent, exact content, chat 0-300 s later.
    sm = t.filter(pl.col("action_name") == "send_message_back_to_chat").select(
        "agent_id", pl.col("id").alias("lid"), pl.col("created_at").alias("lts"),
        aa.str.json_path_match("$.content").alias("txt"),
    ).filter(pl.col("txt").is_not_null()).with_columns(pl.col("txt").hash().alias("h"))
    ca = chat.filter(pl.col("kind") == "agent_msg").select(
        pl.col("actor_id").alias("agent_id"), pl.col("event_uid").alias("rid"),
        pl.col("ts_utc").alias("rts"), pl.col("text").alias("txt_r"),
    ).with_columns(pl.col("txt_r").hash().alias("h"))
    cand = window_candidates(sm, ca, ["agent_id", "h"], *SEND_WINDOW_S)
    cand = (cand.join(sm.select("lid", "txt"), on="lid").join(ca.select("rid", "txt_r"), on="rid")
            .filter(pl.col("txt") == pl.col("txt_r")))
    m = greedy_match(cand, pl.col("dt"))
    links.append(m.select("lid", "rid", pl.lit("send_message_back_to_chat").alias("link")))
    stats_links = {"send_message_back_to_chat": (sm.height, m.height)}

    # search_history -> SEARCH_HISTORY: same agent, exact query, |dt| <= 120 s, no error.
    sh = t.filter((pl.col("action_name") == "search_history")
                  & (pl.col("error_len").fill_null(0) == 0)).select(
        "agent_id", pl.col("id").alias("lid"), pl.col("created_at").alias("lts"),
        aa.str.json_path_match("$.query").alias("q"),
    ).filter(pl.col("q").is_not_null())
    se = (ev.filter(pl.col("action_type") == "SEARCH_HISTORY")
          .select(pl.col("akey").alias("agent_id"), pl.col("id").alias("eid"),
                  pl.col("created_at").alias("rts")))
    se = se.join(_event_text(tables, se["eid"]).select(pl.col("id").alias("eid"), "query"),
                 on="eid").select("agent_id", (pl.lit("event:") + pl.col("eid")).alias("rid"),
                                  "rts", pl.col("query").alias("q"))
    cand = window_candidates(sh, se, ["agent_id", "q"], -SEARCH_WINDOW_S, SEARCH_WINDOW_S)
    m = greedy_match(cand, pl.col("dt").abs())
    links.append(m.select("lid", "rid", pl.lit("search_history").alias("link")))
    n_search_turns = t.filter(pl.col("action_name") == "search_history").height
    stats_links["search_history"] = (n_search_turns, m.height)

    # Other tool turns -> the first event of their type 0-120 s later.
    for action, etype in TURN_EVENT_LINKS.items():
        lt = t.filter(pl.col("action_name") == action).select(
            "agent_id", pl.col("id").alias("lid"), pl.col("created_at").alias("lts"))
        re_ = ev.filter(pl.col("action_type") == etype).select(
            pl.col("akey").alias("agent_id"), (pl.lit("event:") + pl.col("id")).alias("rid"),
            pl.col("created_at").alias("rts"))
        cand = window_candidates(lt, re_, ["agent_id"], *EVENT_WINDOW_S)
        m = greedy_match(cand, pl.col("dt"))
        links.append(m.select("lid", "rid", pl.lit(action).alias("link")))
        stats_links[action] = (lt.height, m.height)
    stats["turn_links"] = stats_links
    link = pl.concat(links)
    if link["lid"].n_unique() != link.height or link["rid"].n_unique() != link.height:
        raise ValueError("turn links are not one-to-one")

    t = t.join(link.select(pl.col("lid").alias("id"), pl.col("rid").alias("dup_of_uid")),
               on="id", how="left")
    t = t.with_columns(
        _uid("turn"),
        pl.lit("turn").alias("source"),
        pl.lit("turn").alias("kind"),
        pl.col("action_name").alias("subkind"),
        pl.col("created_at").alias("ts_utc"),
        pl.col("agent_id").alias("actor_id"),
        _actor_type(pl.lit("agent")).alias("actor_type"),
        # Cut here already to save memory; assemble cuts every source the same way.
        pl.col("_full").str.slice(0, TEXT_MAX).alias("text"),
        (pl.lit("computer_use_turns:") + pl.col("id")).alias("text_ref"),
        pl.col("_full").str.len_chars().fill_null(0).cast(pl.Int64).alias("text_len"),
        turn_kind.cast(pl.Enum(TURN_KINDS)).alias("turn_kind"),
    )
    t = _refs(t, pl.col("_full"))
    obs = _turn_obs_refs(tables)
    t = t.join(obs, on="id", how="left")
    t = t.with_columns(list_minus(t, "refs_obs_raw", "refs").alias("refs_obs"))
    back = link.select(pl.col("rid").alias("event_uid"),
                       (pl.lit("turn:") + pl.col("lid")).alias("linked_uid"),
                       pl.col("link"))
    rows = t.select(
        "event_uid", "source", "kind", "subkind", "ts_utc", "actor_id", "actor_type",
        "session_id", "text", "text_ref", "text_len", "refs", "refs_obs", "dup_of_uid",
        "turn_kind",
    )
    return rows, back


def build_memory_rows(tables: Path, ev: pl.DataFrame, sessions: pl.DataFrame,
                      n_workers: int | None, stats: dict) -> pl.DataFrame:
    """Memory snapshots with versions, linked session_end and session."""
    mv = classify_memory_rows(tables, n_workers)
    stats["memory_rel"] = dict(mv.group_by("rel").len().with_columns(
        pl.col("rel").cast(pl.String)).iter_rows())
    ends = (
        ev.filter(pl.col("action_type").is_in(["STOP_USING_COMPUTER", "CONSOLIDATE"]))
        .select(pl.col("akey").alias("agent_id"), pl.col("created_at").alias("e_ts"),
                (pl.lit("event:") + pl.col("id")).alias("linked_uid"),
                pl.col("action_type").alias("e_type"), pl.col("id").alias("e_id"),
                pl.col("cu_session_id").alias("e_cu"))
    )
    stop_sid = stop_sessions(ev, sessions).select(pl.col("stop_id").alias("e_id"),
                                                  pl.col("session_id").alias("e_stop_sid"))
    # The asof joins below cannot check sortedness within `by` groups, so both
    # sides are sorted right before each of them.
    ends = ends.join(stop_sid, on="e_id", how="left").with_columns(
        pl.coalesce("e_cu", "e_stop_sid").alias("end_session_id")
    ).sort("e_ts")
    m = (
        mv.sort("created_at")
        .join_asof(ends.select("agent_id", "e_ts", "linked_uid", "end_session_id"),
                   left_on="created_at", right_on="e_ts", by="agent_id", strategy="forward",
                   tolerance=f"{int(MEMORY_WINDOW_S * 1e6)}us", check_sortedness=False)
    )
    # Session: the label's UUID (only if it is a session of this agent), else the
    # linked end event's session, else the latest session started at or before.
    own = sessions.select(pl.col("id").alias("session_id"), "agent_id",
                          pl.lit(True).alias("_own"))
    sa = sessions.select(pl.col("id").alias("asof_sid"), "agent_id",
                         pl.col("created_at").alias("s_ts")).sort("s_ts")
    m = (
        m.join(own, on=["session_id", "agent_id"], how="left", maintain_order="left")
        .sort("created_at")
        .join_asof(sa, left_on="created_at", right_on="s_ts", by="agent_id", strategy="backward",
                   check_sortedness=False)
    )
    label = pl.when(pl.col("_own")).then(pl.col("session_id"))
    stats["memory_links"] = {
        "rows": m.height,
        "linked_end": int(m["linked_uid"].is_not_null().sum()),
        "linked_end_distinct": int(m["linked_uid"].drop_nulls().n_unique()),
        "label_uuid": int(m["session_id"].is_not_null().sum()),
        "label_uuid_own_session": int(m["_own"].fill_null(False).sum()),
        "session_from_label": int(m.select(label.is_not_null().sum()).item()),
        "session_from_end_event": int(
            m.select((label.is_null() & pl.col("end_session_id").is_not_null()).sum()).item()),
        "session_from_asof": int(
            m.select((label.is_null() & pl.col("end_session_id").is_null()
                      & pl.col("asof_sid").is_not_null()).sum()).item()),
    }
    m = m.with_columns(pl.coalesce(label, "end_session_id", "asof_sid").alias("session_id"))
    return m.select(
        _uid("memory"),
        pl.lit("memory").alias("source"),
        pl.lit("memory_write").alias("kind"),
        pl.col("rel").cast(pl.String).alias("subkind"),
        pl.col("created_at").alias("ts_utc"),
        pl.col("agent_id").alias("actor_id"),
        _actor_type(pl.lit("agent")).alias("actor_type"),
        "session_id",
        (pl.lit("agent_memories_text:") + pl.col("id")).alias("text_ref"),
        pl.col("content_len").fill_null(0).cast(pl.Int64).alias("text_len"),
        "linked_uid",
        pl.col("regime_cu").cast(pl.String).alias("_regime_cu"),
        "version_idx",
        (pl.lit("memory:") + pl.col("parent_gen_id")).alias("parent_uid"),
        (pl.lit("memory:") + pl.col("input_row_id")).alias("input_row_uid"),
        "is_generation",
        "rel",
        (pl.col("rel") == "ident").alias("drop_version"),
    )


def build_summary_rows(tables: Path, agent_names: dict[str, str]) -> pl.DataFrame:
    """Summaries, timed by updated_at; regenerated and latest flags."""
    s = pl.read_parquet(tables / "summaries.parquet")
    name_to_id = {v: k for k, v in agent_names.items()}
    target_name = pl.col("summary_target").str.replace(r":\d+$", "")
    return (
        s.with_columns(
            ((pl.col("updated_at") - pl.col("created_at")) > pl.duration(hours=24))
            .alias("summary_regenerated"),
            (pl.col("updated_at") == pl.col("updated_at").max()
             .over("type", "summary_target", "summary_date")).alias("summary_is_latest"),
        )
        .select(
            _uid("summary"),
            pl.lit("summary").alias("source"),
            pl.lit("other").alias("kind"),
            pl.col("type").alias("subkind"),
            pl.col("updated_at").alias("ts_utc"),
            pl.lit(SUMMARIZER).alias("actor_id"),
            _actor_type(pl.lit("system")).alias("actor_type"),
            target_name.replace_strict(name_to_id, default=None).alias("target_agent_id"),
            (pl.lit("summaries:") + pl.col("id")).alias("text_ref"),
            pl.col("content").str.len_chars().fill_null(0).cast(pl.Int64).alias("text_len"),
            "summary_regenerated",
            "summary_is_latest",
        )
    )


# --- assembly -----------------------------------------------------------------

def rooms_era(pt_date: pl.Expr) -> pl.Expr:
    expr = pl.lit("R0")
    for start, label in ROOMS_ERA_STARTS:
        expr = pl.when(pt_date >= pl.lit(start)).then(pl.lit(label)).otherwise(expr)
    return expr.cast(pl.Enum(ROOMS_ERAS))


def assign_agent_rooms(df: pl.DataFrame, ev: pl.DataFrame, general_id: str) -> pl.DataFrame:
    """agent_room_id for agent rows, plus `_room_strict` (earlier events only).

    The room of the agent's latest earlier room-carrying event, in
    event_index order for rows that have one and in time order otherwise;
    `general` before ROOMS_START; else, for an ENTER_ROOM row, the room it
    left, and for other rows the next event's room (an ENTER_ROOM's previous
    room); else `general`.
    """
    rb = ev.filter(pl.col("akey").is_not_null() & pl.col("room_id").is_not_null()).select(
        pl.col("akey").alias("actor_id"), "event_index", pl.col("created_at").alias("rts"),
        pl.col("room_id").alias("prior_room"),
        pl.when(pl.col("action_type") == "ENTER_ROOM").then(pl.col("previous_room_id"))
        .otherwise(pl.col("room_id")).alias("next_room"),
    )
    ag = df.filter(pl.col("actor_type") == "agent").select(
        "event_uid", "actor_id", "event_index", "ts_utc", "date",
        pl.when((pl.col("source") == "event") & (pl.col("subkind") == "enter_room"))
        .then(pl.col("previous_room_id")).alias("left_room"),
    )
    by_idx = ag.filter(pl.col("event_index").is_not_null()).sort("event_index")
    rbi = rb.sort("event_index")
    by_idx = (
        by_idx.join_asof(rbi.select("actor_id", "event_index", "prior_room"), on="event_index",
                         by="actor_id", strategy="backward", allow_exact_matches=False,
                         check_sortedness=False)
        .join_asof(rbi.select("actor_id", "event_index", "next_room"), on="event_index",
                   by="actor_id", strategy="forward", allow_exact_matches=False,
                   check_sortedness=False)
    )
    by_ts = ag.filter(pl.col("event_index").is_null()).sort("ts_utc")
    rbt = rb.sort("rts")
    by_ts = (
        by_ts.join_asof(rbt.select("actor_id", "rts", "prior_room"), left_on="ts_utc",
                        right_on="rts", by="actor_id", strategy="backward",
                        allow_exact_matches=False, check_sortedness=False).drop("rts")
        .join_asof(rbt.select("actor_id", "rts", "next_room"), left_on="ts_utc", right_on="rts",
                   by="actor_id", strategy="forward", allow_exact_matches=False,
                   check_sortedness=False).drop("rts")
    )
    gen = pl.lit(general_id)
    rooms = pl.concat([by_idx, by_ts]).select(
        "event_uid",
        pl.coalesce("prior_room", gen).alias("_room_strict"),
        pl.coalesce(
            "prior_room",
            pl.when(pl.col("date") < pl.lit(ROOMS_START)).then(gen),
            "left_room",
            "next_room",
            gen,
        ).alias("agent_room_id"),
    )
    return df.join(rooms, on="event_uid", how="left", maintain_order="left")


def _room_events(ev: pl.DataFrame) -> pl.DataFrame:
    """The agents' room-carrying events in event_index order (the input of the room rule)."""
    return (
        ev.filter(pl.col("akey").is_not_null() & pl.col("room_id").is_not_null())
        .select(
            pl.col("akey").alias("agent_id"), "event_index", pl.col("created_at").alias("ts"),
            "room_id",
            pl.when(pl.col("action_type") == "ENTER_ROOM").then(pl.col("previous_room_id"))
            .otherwise(pl.col("room_id")).alias("next_room"),
            (pl.lit("event:") + pl.col("id")).alias("uid"),
        )
        .sort("agent_id", "event_index")
    )


def agent_room_intervals(ev: pl.DataFrame, first_seen: pl.DataFrame, general_id: str,
                         tz: str = "America/Los_Angeles") -> pl.DataFrame:
    """Room spells per agent: the `agent_room_id` rule as a function of time.

    `first_seen` has agent_id and first_ts (the agent's first agent row).
    Spells opened by an event: in event_index order, each room-carrying event
    whose room differs from the agent's previous one opens a spell at its time
    (`start_event_uid`), so the agent's rows after it are in that room. Spells
    opened by the rule cover the time before the agent's first room-carrying
    event: `general` before ROOMS_START (PT), from ROOMS_START that event's
    room (for an ENTER_ROOM, the room it left). The first spell of each agent
    has a null `start`; a spell ends where the next one starts (`end` null for
    the last). Look up a time with `room_at` (latest start strictly before it).
    Agents without room-carrying events get one `general` spell.
    """
    rooms_start = datetime.combine(ROOMS_START, datetime.min.time(), ZoneInfo(tz)).astimezone(
        timezone.utc)
    rb = _room_events(ev).with_columns(
        (pl.col("room_id") != pl.col("room_id").shift(1).over("agent_id")).fill_null(True)
        .alias("_new")
    )
    by_event = rb.filter(pl.col("_new")).select(
        "agent_id", "room_id", pl.col("ts").alias("start"), pl.lit("event").alias("opened_by"),
        pl.col("uid").alias("start_event_uid"),
    )
    first = rb.group_by("agent_id", maintain_order=True).first()
    info = (
        first_seen.select("agent_id", "first_ts")
        .join(first.select("agent_id", pl.col("ts").alias("t1"), "next_room"), on="agent_id",
              how="full", coalesce=True)
    )
    rule = []
    for agent, first_ts, t1, next_room in info.select(
            "agent_id", "first_ts", "t1", "next_room").iter_rows():
        if t1 is None:  # no room-carrying event: `general` throughout
            rule.append((agent, general_id, None))
        elif t1 <= rooms_start:
            rule.append((agent, general_id, None))
        elif first_ts is not None and first_ts < rooms_start:
            rule += [(agent, general_id, None), (agent, next_room or general_id, rooms_start)]
        else:
            rule.append((agent, next_room or general_id, None))
    by_rule = pl.DataFrame(
        rule, schema={"agent_id": pl.String, "room_id": pl.String,
                      "start": pl.Datetime("us", "UTC")}, orient="row",
    ).with_columns(pl.lit("rule").alias("opened_by"),
                   pl.lit(None, pl.String).alias("start_event_uid"))
    spells = (
        pl.concat([by_rule.with_columns(pl.lit(0).alias("_o")),
                   by_event.with_columns(pl.lit(1).alias("_o"))], how="vertical_relaxed")
        .with_row_index("_i")
        .sort("agent_id", "_o", "_i")  # rule spells first, then events in event_index order
        .with_columns(
            pl.int_range(pl.len()).over("agent_id").cast(pl.Int32).alias("spell"),
            pl.col("start").shift(-1).over("agent_id").alias("end"),
        )
    )
    return spells.select([pl.col(c).cast(t) for c, t in ROOM_INTERVAL_SCHEMA.items()])


def room_at(intervals: pl.DataFrame, rows: pl.DataFrame, agent: str = "actor_id",
            ts: str = "ts_utc") -> pl.Series:
    """Room of each row's agent at its time from `agent_room_intervals` (null if unknown).

    Takes the spell with the latest start strictly before the time (a null
    start counts as the beginning of time), like the strictly-earlier rule of
    `assign_agent_rooms`. Returns one value per row of `rows`, in its order.
    """
    lo = datetime(1970, 1, 1, tzinfo=timezone.utc)
    iv = (intervals.select(pl.col("agent_id").alias("_a"), pl.col("start").fill_null(lo)
                           .alias("_s"), pl.col("room_id").alias("_room"))
          .sort("_s"))
    q = (rows.select(pl.col(agent).alias("_a"), pl.col(ts).alias("_t")).with_row_index("_r")
         .sort("_t"))
    out = q.join_asof(iv, left_on="_t", right_on="_s", by="_a", strategy="backward",
                      allow_exact_matches=False, check_sortedness=False).sort("_r")
    return out["_room"]


def assign_open_sessions(df: pl.DataFrame, sessions: pl.DataFrame) -> pl.DataFrame:
    """Session for agent rows without one: the agent's session open at ts.

    Open means created at or before ts and not ended before it (`end_ts`).
    """
    need = df.filter((pl.col("actor_type") == "agent") & pl.col("session_id").is_null()
                     & pl.col("source").is_in(["chat", "event"]))
    sa = sessions.select(pl.col("id").alias("_sid"), pl.col("agent_id").alias("actor_id"),
                         pl.col("created_at").alias("s_ts"), "end_ts").sort("s_ts")
    got = (
        need.select("event_uid", "actor_id", "ts_utc").sort("ts_utc")
        .join_asof(sa, left_on="ts_utc", right_on="s_ts", by="actor_id", strategy="backward",
                   check_sortedness=False)
        .filter(pl.col("end_ts").is_not_null() & (pl.col("ts_utc") <= pl.col("end_ts")))
        .select("event_uid", "_sid")
    )
    return (df.join(got, on="event_uid", how="left", maintain_order="left")
            .with_columns(pl.coalesce("session_id", "_sid").alias("session_id")).drop("_sid"))


def assign_goals(df: pl.DataFrame, tables: Path) -> pl.DataFrame:
    """goal_id (village goal in force) and agent_goal_id (the actor's own goal)."""
    vg = (pl.read_parquet(tables / "village_goals.parquet",
                          columns=["id", "start_time", "end_time"])
          .rename({"id": "_gid", "end_time": "_gend"}).sort("start_time"))
    ag = (pl.read_parquet(tables / "agent_goals.parquet",
                          columns=["id", "agent_id", "start_time", "end_time"])
          .rename({"id": "_agid", "agent_id": "actor_id", "start_time": "_ag_start",
                   "end_time": "_agend"}).sort("_ag_start"))
    out = (
        df.join_asof(vg, left_on="ts_utc", right_on="start_time", strategy="backward")
        .join_asof(ag, left_on="ts_utc", right_on="_ag_start", by="actor_id", strategy="backward",
                   check_sortedness=False)
        .with_columns(
            pl.when(pl.col("_gend").is_null() | (pl.col("ts_utc") < pl.col("_gend")))
            .then(pl.col("_gid")).alias("goal_id"),
            pl.when(pl.col("_agend").is_null() | (pl.col("ts_utc") < pl.col("_agend")))
            .then(pl.col("_agid")).alias("agent_goal_id"),
        )
        .drop("_gid", "start_time", "_gend", "_agid", "_ag_start", "_agend")
    )
    return out


def assign_regime_cu(df: pl.DataFrame, ev: pl.DataFrame, meta: pl.DataFrame) -> pl.DataFrame:
    """`post` from the agent's first CONSOLIDATE (less REGIME_TOLERANCE_S).

    The Claude Code agent stays `pre`. Memory rows keep the module B1 value.
    """
    first = (
        ev.filter(pl.col("action_type") == "CONSOLIDATE")
        .group_by(pl.col("akey").alias("actor_id"))
        .agg(pl.col("created_at").min().alias("_first_cons"))
    )
    cc = meta.filter(pl.col("scaffold") == "claude_code")["agent_id"]
    tol = pl.duration(milliseconds=int(REGIME_TOLERANCE_S * 1000))
    return (
        df.join(first, on="actor_id", how="left", maintain_order="left")
        .with_columns(
            pl.when(pl.col("actor_type") != "agent").then(pl.lit(None, pl.String))
            .when(pl.col("_regime_cu").is_not_null()).then(pl.col("_regime_cu"))
            .when(~pl.col("actor_id").is_in(cc.implode())
                  & (pl.col("ts_utc") >= pl.col("_first_cons") - tol)).then(pl.lit("post"))
            .otherwise(pl.lit("pre"))
            .cast(pl.Enum(REGIMES_CU)).alias("regime_cu")
        )
        .drop("_first_cons", "_regime_cu")
    )


def default_workers() -> int:
    return int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
