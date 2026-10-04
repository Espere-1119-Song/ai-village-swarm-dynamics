"""build-events on a tiny synthetic village: linking, actors, days, runs, rooms."""

import dataclasses
import json
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

from avsd.events.build import ORDER, assemble, build_events
from avsd.events.events_qa import reconciliation
from avsd.events.links import greedy_match, window_candidates
from avsd.events.refs import set_owner_salt
from avsd.events.runs import assign_run_columns, find_blocks
from avsd.events.unified import (
    TEXT_MAX,
    agent_room_intervals,
    assign_agent_rooms,
    list_minus,
    mention_target,
    room_at,
)

UTC = timezone.utc
A = "aaaaaaaa-0000-4000-8000-00000000000a"  # Claude Opus 4.5
B = "bbbbbbbb-0000-4000-8000-00000000000b"  # GPT-5
C = "cccccccc-0000-4000-8000-00000000000c"  # Opus 4.5 (Claude Code), no activity
S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"
GEN, BEST = "room-general", "room-best"
BOT = "445ab51c-3bb1-4475-a536-67f1924b06cf"
U1, U2 = "user-1", "user-2"
LONG = "hello world " + "x" * 2100  # longer than TEXT_MAX: cut inline, linked on full text
NUDGE = "@Claude Opus 4.5 — it looks like you are stuck"
QUERY = "what happened at https://example.com/q"


@pytest.fixture(autouse=True, scope="module")
def _fixed_salt():
    """Owner pseudonyms in the QA report use a test secret, not the project file."""
    set_owner_salt(b"unit-test-salt-0123456789abcdef")
    yield
    set_owner_salt(None)


def t(day: int, hh: int, mm: int, ss: float = 0.0) -> datetime:
    """UTC time on 2026-04-<day>."""
    return datetime(2026, 4, day, hh, mm, tzinfo=UTC) + timedelta(seconds=ss)


TS = pl.Datetime("us", "UTC")
EV_COLS = {
    "id": pl.String, "event_index": pl.Int64, "action_type": pl.String, "data_keys": pl.String,
    "speaker_id": pl.String, "speaker_type": pl.String, "agent_id": pl.String,
    "room_id": pl.String, "previous_room_id": pl.String, "message_id": pl.String,
    "cu_session_id": pl.String, "start_day": pl.String, "end_day": pl.String,
    "start_date": pl.String, "end_date": pl.String, "cost": pl.Float64,
    "input_tokens": pl.Float64, "output_tokens": pl.Float64, "created_at": TS,
}
EVT_COLS = {c: pl.String for c in ("id", "query", "session_goal", "summary", "next_session_goal",
                                   "content", "answer", "data_json")}
K_OUT = "actionType,agentId,cost,output,outputTokens,roomId"
K_NOOUT = "actionType,agentId,cost,outputTokens,roomId"


def _events() -> tuple[list[dict], list[dict]]:
    rows, text = [], []

    def ev(i, at, ts, **kw):
        eid = f"e{i}"
        rows.append({"id": eid, "event_index": i, "action_type": at, "created_at": ts,
                     "data_keys": kw.pop("keys", K_OUT), "cost": kw.pop("cost", 0.01), **{
                         k: v for k, v in kw.items() if k in EV_COLS}})
        text.append({"id": eid, **{k: v for k, v in kw.items() if k in EVT_COLS}})

    ev(1, "START_USING_COMPUTER", t(1, 17, 0, 0.05), agent_id=A, cu_session_id=S1, room_id=GEN,
       session_goal="Work on https://example.com/plan")
    ev(2, "AGENT_TALK", t(1, 17, 1, 0.07), speaker_id=A, speaker_type="agent", room_id=GEN,
       message_id="c1", content=LONG)
    ev(3, "USER_TALK", t(1, 17, 2, 0.04), speaker_id=U1, speaker_type="HUMAN", room_id=GEN,
       message_id="c2", content="hi agents")
    ev(4, "USER_TALK", t(1, 17, 3, 0.04), speaker_id=BOT, speaker_type="HUMAN", room_id=GEN,
       message_id="c3", content=NUDGE)
    ev(5, "SEARCH_HISTORY", t(1, 17, 4, 0.05), agent_id=A, room_id=GEN, query=QUERY,
       answer="see https://example.com/q and "
              "https://docs.google.com/document/d/abcdefghijklmnopqrstuvwxyz/edit",
       start_day="360", end_day="364")
    ev(6, "PAUSE", t(1, 17, 5, 0.02), agent_id=A, room_id=GEN)
    ev(7, "ENTER_ROOM", t(1, 17, 6), agent_id=A, room_id=BEST, previous_room_id=GEN)
    ev(8, "AGENT_TALK", t(1, 17, 7, 0.07), speaker_id=A, speaker_type="agent", room_id=BEST,
       message_id="c4", content="in best now")
    ev(9, "AGENT_TALK", t(1, 17, 10, 0.07), speaker_id=B, speaker_type="agent", room_id=GEN,
       message_id="c5", content="B here")
    ev(10, "STOP_USING_COMPUTER", t(1, 18, 59), agent_id=A, summary="Did things",
       keys="actionType,agentId,cost,outputTokens,summary")
    ev(11, "CONSOLIDATE", t(1, 18, 50), agent_id=B, cu_session_id=S2, room_id=BEST,
       next_session_goal="Next: write docs")
    ev(12, "WAIT", t(1, 17, 30), agent_id=B)
    ev(13, "RESTARTING_AFTER_GOOGLE_SIGN_IN", t(1, 17, 40), agent_id=B, room_id=GEN)
    ev(14, "OUTREACH_APPROVAL_RESPONSE", t(1, 17, 45), agent_id=A, room_id=BEST,
       data_json='{"messageContent": "Dear someone", "approval": true}', cost=0.0)
    ev(15, "ENTER_ROOM", t(1, 17, 50), agent_id=B, room_id=BEST, previous_room_id=GEN,
       keys=K_NOOUT, cost=0.0)
    ev(16, "STOP_HUMAN_USE_SESSION", t(1, 17, 55), agent_id=A,
       data_json='{"endReason": "user_timeout"}', summary="timed out")
    ev(17, "USER_NAME_CHANGE", t(1, 18, 0), keys="actionType,newName,oldName,userId")
    ev(18, "USER_TALK", t(1, 18, 5), speaker_id=U2, speaker_type="HUMAN", room_id=GEN,
       message_id="gone", content="orphan msg")
    ev(19, "WAIT", t(2, 1, 0), agent_id=A)  # 18:00 PT on 04-01: an extra block
    ev(20, "AGENT_TALK", t(2, 1, 10, 0.04), speaker_id=A, speaker_type="agent", room_id=BEST,
       message_id="c6", content="late note")
    ev(21, "AGENT_TALK", t(2, 17, 0, 0.04), speaker_id=A, speaker_type="agent", room_id=BEST,
       message_id="c8", content="day two")
    ev(22, "USER_TALK", t(2, 17, 30, 0.04), speaker_id=BOT, speaker_type="HUMAN", room_id=GEN,
       message_id="c9", content="Pausing the village for today")
    ev(23, "AGENT_TALK", t(2, 17, 20, 0.04), speaker_id=B, speaker_type="agent", room_id=BEST,
       message_id="c10", content="B day two")
    ev(24, "USER_TALK", t(4, 18, 0, 0.04), speaker_id=U1, speaker_type="HUMAN", room_id=GEN,
       message_id="c11", content="weekend hello")
    ev(25, "AGENT_TALK", t(1, 20, 0, 0.04), speaker_id=U1, speaker_type="HUMAN", room_id=GEN,
       message_id="c7", content="human after hours")
    rows[-1]["action_type"] = "USER_TALK"
    rows.sort(key=lambda r: r["created_at"])  # event_index follows time, as in the data
    for i, r in enumerate(rows, start=1):
        r["event_index"] = i
    return rows, text


CHAT = [  # id, speaker_type, agent, user, content, room, ts
    ("c1", "agent", A, None, LONG, GEN, t(1, 17, 1, 0.03)),
    ("c2", "user", None, U1, "hi agents", GEN, t(1, 17, 2)),
    ("c3", "user", None, BOT, NUDGE, GEN, t(1, 17, 3)),
    ("c4", "agent", A, None, "in best now", BEST, t(1, 17, 7, 0.03)),
    ("c5", "agent", B, None, "B here", GEN, t(1, 17, 10)),
    ("c6", "agent", A, None, "late note", BEST, t(2, 1, 10)),
    ("c7", "user", None, U1, "human after hours", GEN, t(1, 20, 0)),
    ("c8", "agent", A, None, "day two", BEST, t(2, 17, 0)),
    ("c9", "user", None, BOT, "Pausing the village for today", GEN, t(2, 17, 30)),
    ("c10", "agent", B, None, "B day two", BEST, t(2, 17, 20)),
    ("c11", "user", None, U1, "weekend hello", GEN, t(4, 18, 0)),
]

TURNS = [  # id, session, action_name, keys, agent_action, error_len, ts, output, error, msgs
    ("T1", S1, "bash", "command",
     '{"command": "cat /tmp/x.txt && curl https://example.com/a?utm_source=x"}', None,
     t(1, 17, 0, 10), "see https://github.com/ai-village-agents/repo", None, None),
    ("T2", S1, "send_message_back_to_chat", "content", json.dumps({"content": LONG}), None,
     t(1, 17, 1), None, None, None),
    ("T3", S1, "search_history", "endDay,query,startDay", json.dumps({"query": QUERY}), None,
     t(1, 17, 4), "answer", None, None),
    ("T4", S1, "pause", "seconds", '{"seconds": 60}', None, t(1, 17, 5), None, None, None),
    ("T5", S1, "move_to_room", "roomName", '{"roomName": "best"}', None, t(1, 17, 5, 59.99),
     None, None, None),
    ("T6", S2, "left_click", "action,coordinate,text",
     '{"action": "left_click", "coordinate": [1, 2], "text": null}', None, t(1, 17, 0, 40),
     None, None, None),
    ("T7", S2, None, None, None, None, t(1, 17, 20), None, None, '[{"type": "text"}]'),
    ("T8", S2, None, None, None, None, t(1, 17, 21), None, None,
     '[{"type": "tool_use", "name": "bogus"}]'),
    ("T9", S2, None, "restart", '{"restart": true}', None, t(1, 17, 22), None, None, None),
    ("T10", S1, "search_history", "query", json.dumps({"query": QUERY}), 30, t(1, 17, 4, 1),
     None, "bad range", None),
    # B keeps acting so that 04-01 has no gap > G inside its main block.
    *[(f"T{11 + i}", S2, "screenshot", "action", '{"action": "screenshot"}', None, ts, None,
       None, None) for i, ts in enumerate([t(1, 17, 50), t(1, 18, 10), t(1, 18, 30)])],
    ("T14", S2, "get_pixel_coords_of_element", "action,description",
     '{"action": "get_pixel_coords_of_element", "description": "Submit on https://example.com/form"}',
     None, t(1, 17, 0, 50), "see https://example.com/form and https://example.com/next", None,
     None),
]


def _memories() -> tuple[list[dict], list[dict]]:
    m1 = "notes\n"
    m3 = m1 + f"\n\nPREVIOUS (NOW ENDED) COMPUTER USE SESSION ({S1})\nsummary"
    rows = [("M1", A, t(1, 17, 30), m1), ("M3", A, t(1, 18, 59) - timedelta(milliseconds=16), m3),
            ("M4", B, t(1, 16, 0), "early\n"),  # off-schedule write: no block of its own
            ("M2", B, t(1, 18, 50) - timedelta(milliseconds=16), "consolidated\n")]
    meta = [{"id": i, "agent_id": a, "created_at": ts, "updated_at": ts, "content_len": len(c)}
            for i, a, ts, c in rows]
    return meta, [{"id": i, "content": c} for i, _, _, c in rows]


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    d = tmp_path_factory.mktemp("tables")
    pl.DataFrame({
        "id": [A, B, C], "name": ["Claude Opus 4.5", "GPT-5", "Opus 4.5 (Claude Code)"],
        "model_string": ["claude-opus-4-5-20251101", "gpt-5-2025-08-07",
                         "claude-code::claude-opus-4-5-20251101"],
        "created_at": [t(1, 0, 0)] * 3,
    }, schema_overrides={"created_at": TS}).write_parquet(d / "agents.parquet")
    pl.DataFrame({"id": [GEN, BEST], "name": ["general", "best"]}).write_parquet(
        d / "chat_rooms.parquet")
    pl.DataFrame(
        [dict(zip(["id", "speaker_type", "agent_speaker_id", "user_speaker_id", "content",
                   "room_id", "created_at"], r)) for r in CHAT],
        schema={"id": pl.String, "speaker_type": pl.String, "agent_speaker_id": pl.String,
                "user_speaker_id": pl.String, "content": pl.String, "room_id": pl.String,
                "created_at": TS},
    ).write_parquet(d / "chat_messages.parquet")
    rows, text = _events()
    pl.DataFrame(rows, schema=EV_COLS).write_parquet(d / "events.parquet")
    pl.DataFrame(text, schema=EVT_COLS).write_parquet(d / "events_text.parquet")
    pl.DataFrame({
        "id": [S1, S2], "agent_id": [A, B], "session_goal": ["Work on https://example.com/plan",
                                                             "Start up"],
        "created_at": [t(1, 17, 0), t(1, 17, 0, 30)],
    }, schema_overrides={"created_at": TS}).write_parquet(d / "computer_use_sessions.parquet")
    cols = ["id", "session_id", "action_name", "action_keys", "agent_action", "error_len",
            "created_at"]
    pl.DataFrame([dict(zip(cols, r[:7])) for r in TURNS],
                 schema={**{c: pl.String for c in cols[:5]}, "error_len": pl.Int64,
                         "created_at": TS}).write_parquet(d / "computer_use_turns.parquet")
    pl.DataFrame([{"id": r[0], "output": r[7], "error": r[8], "agent_messages": r[9]}
                  for r in TURNS], schema={c: pl.String for c in
                                           ("id", "output", "error", "agent_messages")}
                 ).write_parquet(d / "computer_use_turns_text.parquet")
    meta, mtext = _memories()
    pl.DataFrame(meta, schema={"id": pl.String, "agent_id": pl.String, "created_at": TS,
                               "updated_at": TS, "content_len": pl.Int64}
                 ).write_parquet(d / "agent_memories.parquet")
    pl.DataFrame(mtext).write_parquet(d / "agent_memories_text.parquet")
    pl.DataFrame({"id": ["cc1"], "agent_id": [C], "created_at": [t(1, 0, 0)]},
                 schema_overrides={"created_at": TS}
                 ).write_parquet(d / "claude_code_sessions.parquet")
    pl.DataFrame({
        "id": ["s1", "s2"], "type": ["daily", "agent"], "summary_target": ["365", "GPT-5"],
        "summary_date": ["2026-04-01", None], "content": ["day summary", "agent summary"],
        "created_at": [t(2, 17, 0), t(2, 17, 0)], "updated_at": [t(2, 17, 0), t(4, 17, 0)],
    }, schema_overrides={"created_at": TS, "updated_at": TS}).write_parquet(d / "summaries.parquet")
    pl.DataFrame({"id": ["G1", "G2"], "start_time": [t(1, 0, 0) - timedelta(days=2), t(2, 0, 0)],
                  "end_time": [t(2, 0, 0), None]},
                 schema_overrides={"start_time": TS, "end_time": TS}
                 ).write_parquet(d / "village_goals.parquet")
    pl.DataFrame({"id": ["AG1"], "agent_id": [A], "start_time": [t(2, 12, 0)], "end_time": [None]},
                 schema_overrides={"start_time": TS, "end_time": TS}
                 ).write_parquet(d / "agent_goals.parquet")
    return d


@pytest.fixture(scope="module")
def res(tables):
    return assemble(tables, "America/Los_Angeles", 1800.0, n_workers=1)


def row(res, uid: str) -> dict:
    out = res.unified.filter(pl.col("event_uid") == uid)
    assert out.height == 1, uid
    return out.row(0, named=True)


def test_row_accounting(res, tables):
    df = res.unified
    n = dict(df.group_by("source").len().with_columns(pl.col("source").cast(pl.String)).iter_rows())
    # 25 events - 11 linked talk - 1 START - 1 USER_NAME_CHANGE = 12 (incl. the orphan).
    assert n == {"chat": 11, "event": 12, "session": 2, "turn": 14, "memory": 4, "summary": 2}
    assert df["event_uid"].is_unique().all()
    assert df.filter(pl.col("event_uid").is_in(["event:e2", "event:e1", "event:e17"])).is_empty()
    assert df["ts_utc"].is_sorted()
    assert df["ts_utc"].null_count() == 0 and df["actor_type"].null_count() == 0
    # File order (ts_utc, source as text, event_index, event_uid).
    txt = df.with_columns(pl.col("source").cast(pl.String))
    assert txt.equals(txt.sort(ORDER, nulls_last=True, maintain_order=True))
    rows, ok, links = reconciliation(res, tables)
    assert ok and all(r[6] == 0 and r[7] == 0 for r in rows)
    ev_row = next(r for r in rows if r[1] == "event")
    # events: 25 = 12 emitted + 12 linked (11 talk events on chat rows, 1 START) + 1 rename.
    assert ev_row[2:6] == [25, 12, 12, 1]
    assert (links["chat_carrying"], links["session_carrying"]) == (11, 1)


def test_reconciliation_measures_output(res, tables):
    """Linked counts come from the rows that carry the ids, so lost links show."""
    df = res.unified
    lost_start = df.with_columns(
        pl.when(pl.col("source") == "session").then(None).otherwise(pl.col("src_event_id"))
        .alias("src_event_id"))
    rows, ok, links = reconciliation(dataclasses.replace(res, unified=lost_start), tables)
    ev_row = next(r for r in rows if r[1] == "event")
    assert not ok and ev_row[6] == 1 and links["session_unmatched"] == 1
    # A chat row carrying the wrong event: counts still add up, the ids do not.
    swapped = df.with_columns(
        pl.when(pl.col("event_uid") == "chat:c2").then(pl.lit("e3x"))
        .otherwise(pl.col("src_event_id")).alias("src_event_id"))
    rows, ok, links = reconciliation(dataclasses.replace(res, unified=swapped), tables)
    ev_row = next(r for r in rows if r[1] == "event")
    assert not ok and ev_row[6] == 0 and ev_row[7] == 2 and links["chat_unmatched"] == 2


def test_dedup_and_links(res):
    c1 = row(res, "chat:c1")
    assert (c1["src_event_id"], c1["event_index"], c1["linked_uid"]) == ("e2", 2, "turn:T2")
    assert c1["session_id"] == S1  # from the linked send_message turn
    assert row(res, "turn:T2")["dup_of_uid"] == "chat:c1"
    assert row(res, "turn:T3")["dup_of_uid"] == "event:e5"
    assert row(res, "turn:T10")["dup_of_uid"] is None  # errored search turn
    assert row(res, "turn:T4")["dup_of_uid"] == "event:e6"
    assert row(res, "turn:T5")["dup_of_uid"] == "event:e7"
    e5 = row(res, "event:e5")
    assert (e5["linked_uid"], e5["session_id"]) == ("turn:T3", S1)
    assert (e5["search_start_day"], e5["search_end_day"]) == (360, 364)
    orphan = row(res, "event:e18")
    assert orphan["chat_row_missing"] and orphan["kind"] == "human_msg"
    assert orphan["actor_id"] == "human"
    s1 = row(res, f"session:{S1}")
    assert (s1["src_event_id"], s1["subkind"], s1["actor_type"]) == ("e1", "start_only", "agent")
    m3 = row(res, "memory:M3")
    assert (m3["linked_uid"], m3["session_id"], m3["rel"]) == ("event:e10", S1, "append_session")
    assert row(res, "event:e10")["session_id"] == S1  # STOP: latest session at or before
    assert row(res, "event:e11")["session_id"] == S2  # CONSOLIDATE: cu_session_id
    assert row(res, "chat:c5")["session_id"] == S2  # open session of B


def test_text_refs_and_cut(res):
    df = res.unified
    assert df["text_ref"].null_count() == 0
    assert (df["text"].str.len_chars().fill_null(0) <= TEXT_MAX).all()
    c1, t2 = row(res, "chat:c1"), row(res, "turn:T2")
    assert t2["dup_of_uid"] == "chat:c1"  # linked on the full text
    for r in (c1, t2):
        assert r["text"] == LONG[:TEXT_MAX] and r["text_len"] == len(LONG)
    refs = {uid: row(res, uid)["text_ref"] for uid in (
        "chat:c1", "event:e5", f"session:{S1}", "turn:T2", "memory:M1", "summary:s1")}
    assert refs == {"chat:c1": "chat_messages:c1", "event:e5": "events_text:e5",
                    f"session:{S1}": f"computer_use_sessions:{S1}",
                    "turn:T2": "computer_use_turns:T2", "memory:M1": "agent_memories_text:M1",
                    "summary:s1": "summaries:s1"}
    # refs_obs never repeats refs (events and turns); other agent_action text keys count.
    e5 = row(res, "event:e5")
    assert e5["text"] == QUERY and e5["refs"] == ["https://example.com/q"]
    assert e5["refs_obs"] == ["gdoc:document:abcdefghijklmnopqrstuvwxyz"]
    t14 = row(res, "turn:T14")
    assert t14["text"] == "Submit on https://example.com/form"
    assert (t14["refs"], t14["refs_obs"]) == (["https://example.com/form"], ["https://example.com/next"])
    t1 = row(res, "turn:T1")
    assert t1["refs_obs"] == ["github:ai-village-agents/repo"]


def test_list_minus_keeps_order():
    df = pl.DataFrame({"a": [["x", "b", "a", "c", "z"], None, ["p", "p2"], []],
                       "b": [["b", "q"], ["x"], None, ["y"]]})
    assert list_minus(df, "a", "b").to_list() == [["x", "a", "c", "z"], [], ["p", "p2"], []]


def test_mention_target():
    names = {"g5": "GPT-5", "g51": "GPT-5.1", "o45": "Claude Opus 4.5",
             "cc": "Opus 4.5 (Claude Code)"}
    texts = pl.Series(["@GPT-5.1 — it looks like", "@GPT-5 — stuck", "  @claude opus 4.5, hi",
                       "@Opus 4.5 (Claude Code) — x", "hi @GPT-5", "@GPT-5x", "@GPT-5. Next", None])
    assert mention_target(texts, names).to_list() == ["g51", "g5", "o45", "cc", None, None, "g5",
                                                     None]


def test_actor_types(res):
    expect = {
        "chat:c2": ("human", "human", "human_msg"),
        "chat:c3": ("system", "system:nudger", "system_msg"),
        "event:e13": ("system", "system:scaffold", "other"),
        "event:e14": ("human", "human", "other"),
        "event:e15": ("system", "system:scaffold", "other"),
        "event:e16": ("system", "system:scaffold", "other"),
        "event:e7": ("agent", A, "other"),
        "summary:s1": ("system", "system:summarizer", "other"),
        "turn:T6": ("agent", B, "turn"),
    }
    for uid, (atype, actor, kind) in expect.items():
        r = row(res, uid)
        assert (r["actor_type"], r["actor_id"], r["kind"]) == (atype, actor, kind), uid
    assert row(res, "event:e14")["target_agent_id"] == A
    assert row(res, "summary:s2")["target_agent_id"] == B
    c9 = row(res, "chat:c9")
    assert c9["is_run_marker"] and c9["subkind"] == "run_marker"
    assert c9["target_agent_id"] is None
    c3 = row(res, "chat:c3")
    assert (c3["subkind"], c3["target_agent_id"]) == ("nudge", A)
    assert res.stats["nudge_targets"] == {"nudges": 1, "with_target": 1}
    kinds = {r["event_uid"]: r["turn_kind"] for r in res.unified.filter(
        pl.col("source") == "turn").iter_rows(named=True)}
    assert kinds["turn:T7"] == "talk_only" and kinds["turn:T8"] == "malformed_call"
    assert kinds["turn:T9"] == "bash_restart" and kinds["turn:T1"] == "tool_action"
    agent = res.unified.filter(pl.col("actor_type") == "agent")
    assert agent["model_family"].null_count() == 0
    assert set(agent["model_family"]) == {"Anthropic", "OpenAI"}
    humans = res.humans
    assert set(humans["user_id"]) == {U1, U2, BOT}
    assert not res.unified["actor_id"].is_in([U1, U2, BOT]).any()


def test_village_day_and_goals(res):
    assert row(res, "chat:c1")["village_day"] == 365
    assert row(res, "chat:c6")["village_day"] == 365  # 18:10 PT on 04-01, 01:10 UTC on 04-02
    assert row(res, "chat:c8")["village_day"] == 366
    assert row(res, "chat:c1")["goal_id"] == "G1"
    c8 = row(res, "chat:c8")
    assert (c8["goal_id"], c8["agent_goal_id"]) == ("G2", "AG1")
    assert row(res, "chat:c1")["agent_goal_id"] is None


def test_rooms(res):
    assert row(res, "chat:c1")["agent_room_id"] == GEN
    assert row(res, "chat:c4")["agent_room_id"] == BEST  # after ENTER_ROOM e7
    e7 = row(res, "event:e7")
    assert (e7["room_id"], e7["previous_room_id"], e7["agent_room_id"]) == (BEST, GEN, GEN)
    assert row(res, "turn:T6")["agent_room_id"] == GEN  # no earlier event: look-ahead
    assert row(res, "event:e11")["agent_room_id"] == BEST  # after the operator move e15
    assert res.stats["rooms"] == {"agent_msgs": 6, "strict_correct": 6, "lookahead_correct": 6,
                                  "agent_rows_without_room": 0}


def test_room_intervals(res):
    iv = res.room_intervals
    got = {(r["agent_id"], r["spell"]): (r["room_id"], r["start"], r["end"], r["opened_by"])
           for r in iv.iter_rows(named=True)}
    assert got == {
        (A, 0): (GEN, None, t(1, 17, 0, 0.05), "rule"),
        (A, 1): (GEN, t(1, 17, 0, 0.05), t(1, 17, 6), "event"),  # START e1
        (A, 2): (BEST, t(1, 17, 6), None, "event"),  # ENTER_ROOM e7
        (B, 0): (GEN, None, t(1, 17, 10, 0.07), "rule"),
        (B, 1): (GEN, t(1, 17, 10, 0.07), t(1, 17, 50), "event"),
        (B, 2): (BEST, t(1, 17, 50), None, "event"),  # operator move e15
    }
    ri = res.stats["room_intervals"]
    assert (ri["by_event"], ri["by_rule"], ri["end_before_start"]) == (4, 2, 0)
    assert ri["agent_rows_agree"] == ri["agent_rows"] > 0


def test_first_enter_room_row_gets_the_room_it_left():
    """Like every other ENTER_ROOM row, an agent's first one is in the room it left."""
    ts = datetime(2026, 3, 10, 19, tzinfo=UTC)
    ev = pl.DataFrame([
        {"id": "x1", "akey": "r", "event_index": 1, "created_at": ts, "room_id": BEST,
         "action_type": "ENTER_ROOM", "previous_room_id": "room-rest"},
        {"id": "x2", "akey": "r", "event_index": 2, "created_at": ts + timedelta(minutes=1),
         "room_id": BEST, "action_type": "AGENT_TALK", "previous_room_id": None},
    ], schema_overrides={"created_at": TS})
    df = pl.DataFrame({
        "event_uid": ["event:x1", "turn:t0", "event:x3"], "actor_id": ["r"] * 3,
        "actor_type": ["agent"] * 3, "event_index": [1, None, 3],
        "ts_utc": [ts, ts - timedelta(minutes=1), ts + timedelta(minutes=2)],
        "source": ["event", "turn", "event"], "subkind": ["enter_room", "bash", "wait"],
        "previous_room_id": ["room-rest", None, None],
    }, schema_overrides={"ts_utc": TS}).with_columns(
        pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("date"))
    out = assign_agent_rooms(df, ev, GEN)
    assert dict(zip(out["event_uid"], out["agent_room_id"])) == {
        "event:x1": "room-rest", "turn:t0": "room-rest", "event:x3": BEST}


def test_room_intervals_rules():
    """General before 2026-03-05 PT, then the first event's room (or the room an ENTER_ROOM left)."""
    P, Q, R_ = "agent-p", "agent-q", "agent-r"

    def e(i, akey, ts, room, at="AGENT_TALK", prev=None):
        return {"id": f"x{i}", "akey": akey, "event_index": i, "created_at": ts, "room_id": room,
                "action_type": at, "previous_room_id": prev}

    ev = pl.DataFrame([
        e(1, P, datetime(2026, 3, 1, 18, tzinfo=UTC), GEN),
        e(2, Q, datetime(2026, 3, 10, 18, tzinfo=UTC), BEST),
        e(3, R_, datetime(2026, 3, 10, 19, tzinfo=UTC), BEST, "ENTER_ROOM", "room-rest"),
        e(4, R_, datetime(2026, 3, 10, 20, tzinfo=UTC), BEST),
    ], schema_overrides={"created_at": TS})
    first = pl.DataFrame({"agent_id": [P, Q, R_, "agent-s"],
                          "first_ts": [datetime(2026, 2, 1, tzinfo=UTC),
                                       datetime(2026, 3, 2, tzinfo=UTC),
                                       datetime(2026, 3, 10, 18, tzinfo=UTC),
                                       datetime(2026, 4, 1, tzinfo=UTC)]},
                         schema_overrides={"first_ts": TS})
    iv = agent_room_intervals(ev, first, GEN)
    rs = datetime(2026, 3, 5, 8, tzinfo=UTC)  # 2026-03-05 00:00 PT
    spells = {a: [(r["room_id"], r["start"], r["opened_by"]) for r in
                  iv.filter(pl.col("agent_id") == a).sort("spell").iter_rows(named=True)]
              for a in (P, Q, R_, "agent-s")}
    assert spells[P] == [(GEN, None, "rule"), (GEN, datetime(2026, 3, 1, 18, tzinfo=UTC), "event")]
    assert spells[Q] == [(GEN, None, "rule"), (BEST, rs, "rule"),
                         (BEST, datetime(2026, 3, 10, 18, tzinfo=UTC), "event")]
    assert spells[R_] == [("room-rest", None, "rule"),
                          (BEST, datetime(2026, 3, 10, 19, tzinfo=UTC), "event")]
    assert spells["agent-s"] == [(GEN, None, "rule")]
    q = pl.DataFrame({"actor_id": [Q, Q, Q, R_, R_, "nobody"],
                      "ts_utc": [datetime(2026, 3, 3, tzinfo=UTC), datetime(2026, 3, 6, tzinfo=UTC),
                                 datetime(2026, 3, 11, tzinfo=UTC),
                                 datetime(2026, 3, 10, 19, tzinfo=UTC),
                                 datetime(2026, 3, 10, 19, 0, 1, tzinfo=UTC),
                                 datetime(2026, 3, 11, tzinfo=UTC)]},
                     schema_overrides={"ts_utc": TS})
    assert room_at(iv, q).to_list() == [GEN, BEST, BEST, "room-rest", BEST, None]


def test_run_periods_and_active_time(res):
    b = res.blocks.sort("realization_id")
    assert b["run_day"].to_list() == [1, 1, 2]
    assert b["block"].to_list() == [0, 1, 0]
    assert b["active_seconds"].to_list() == pytest.approx([7140.0, 600.0, 1200.0])
    assert b["n_pauses"].to_list() == [1, 1, 0]
    assert res.pauses.height == 1
    assert res.pauses["seconds"][0] == pytest.approx(6 * 3600 + 60)
    c6 = row(res, "chat:c6")
    assert (c6["realization_id"], c6["block"], c6["t_in_day"]) == (1, 1, pytest.approx(600.0))
    assert c6["t_active"] == pytest.approx(7740.0)
    c8 = row(res, "chat:c8")
    assert (c8["run_day"], c8["t_in_day"], c8["t_active"]) == (2, 0.0, pytest.approx(7740.0))
    c7 = row(res, "chat:c7")  # human row after the main block: frozen t_active
    assert not c7["in_run"] and c7["realization_id"] == 0
    assert c7["t_in_day"] == pytest.approx(3 * 3600.0)
    assert c7["t_active"] == pytest.approx(7140.0)
    c11 = row(res, "chat:c11")  # human-only date
    assert c11["run_day"] is None and c11["t_in_day"] is None
    assert c11["t_active"] == pytest.approx(8940.0)
    m4 = row(res, "memory:M4")  # memory rows do not define run intervals
    assert (m4["in_run"], m4["realization_id"], m4["t_active"]) == (False, 0, 0.0)
    assert m4["t_in_day"] == pytest.approx(-3600.0)
    acts = res.unified.filter((pl.col("actor_type") == "agent") & (pl.col("source") != "memory"))
    assert acts["in_run"].all()
    ta = res.unified["t_active"]
    assert ta.is_sorted()


def test_roster_and_agents(res):
    r = res.roster
    assert r.height == 2 * 3
    act = {(x["run_day"], x["agent_id"]): x["active"] for x in r.iter_rows(named=True)}
    assert act[(1, A)] and act[(2, A)] and act[(1, B)] and not act[(1, C)]
    a = res.agents.filter(pl.col("agent_id") == A).row(0, named=True)
    assert a["first_active_ts"] == t(1, 17, 0)
    assert a["model_group"] == "Claude Opus 4.5"


def test_build_writes_outputs(tables, tmp_path):
    cfg = {
        "seed": 20261003,
        "paths": {"tables": tables, "processed": tmp_path / "processed",
                  "outputs": tmp_path / "outputs", "raw": tmp_path / "raw"},
        "time": {"village_tz": "America/Los_Angeles", "pause_gap_minutes": 30,
                 "village_day1": "2025-04-02"},
        "dataset": {"revision": "test"},
    }
    (tmp_path / "raw").mkdir()
    shutil.copy(Path(__file__).parent / "fixtures" / "CHANGELOG.md", tmp_path / "raw")
    build_events(cfg, n_workers=1)
    for f in ("events_unified", "run_periods", "pause_segments", "agents", "roster_daily",
              "human_ids", "agent_room_intervals", "changelog"):
        assert (tmp_path / "processed" / f"{f}.parquet").exists(), f
    report = (tmp_path / "outputs" / "qa" / "build_events.md").read_text()
    assert "Reconciles exactly: **True**" in report
    assert "Time range per source" in report and "## 13. CHANGELOG" in report
    assert "Opened by a room-carrying event: 4" in report
    for s in ("hello world", U1, BOT, "Dear someone", "it looks like", "Submit on"):
        assert s not in report


def test_find_blocks_gap_threshold():
    ts = [t(1, 17, 0), t(1, 17, 20), t(1, 18, 0), t(1, 18, 10)]
    df = pl.DataFrame({"date": [datetime(2026, 4, 1).date()] * 4, "ts_utc": ts},
                      schema_overrides={"ts_utc": TS})
    b15, p15 = find_blocks(df, 15 * 60)
    b30, p30 = find_blocks(df, 30 * 60)
    assert (b15.height, p15.height, b30.height, p30.height) == (3, 2, 2, 1)
    assert b30.filter(pl.col("block") == 0)["start"][0] == t(1, 17, 0)  # 20 min vs 10 min
    assert b15["active_seconds"].sum() == pytest.approx(600.0)


def test_t_active_monotone_over_many_blocks():
    rng = random.Random(3)
    t0 = datetime(2026, 1, 5, 17, tzinfo=UTC)
    ts = sorted(t0 + timedelta(days=d, seconds=rng.random() * 9000)
                for d in range(200) for _ in range(30))
    df = pl.DataFrame({"ts_utc": ts}, schema_overrides={"ts_utc": TS}).with_columns(
        pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("date"))
    blocks, _ = find_blocks(df, 1800.0)
    out = assign_run_columns(df.lazy(), blocks).collect()
    assert out["t_active"].is_sorted() and out["in_run"].all()
    assert out["t_active"][-1] == pytest.approx(blocks["active_seconds"].sum())


def test_greedy_match_equals_sequential():
    rng = random.Random(7)
    cand = pl.DataFrame({
        "lid": [f"l{rng.randrange(30)}" for _ in range(300)],
        "rid": [f"r{rng.randrange(30)}" for _ in range(300)],
        "dt": [rng.random() for _ in range(300)],
    }).unique(["lid", "rid"])
    got = {(a, b) for a, b in greedy_match(cand, pl.col("dt")).select("lid", "rid").iter_rows()}
    used_l, used_r, want = set(), set(), set()
    for a, b, _ in cand.sort("dt", "lid", "rid").iter_rows():
        if a not in used_l and b not in used_r:
            used_l.add(a), used_r.add(b), want.add((a, b))
    assert got == want


def test_window_candidates_bounds():
    left = pl.DataFrame({"k": ["x", "x"], "lid": ["a", "b"], "lts": [t(1, 0, 0), t(1, 0, 0, 10)]},
                        schema_overrides={"lts": TS})
    right = pl.DataFrame({"k": ["x", "x", "x", "x", "y"], "rid": ["r0", "r1", "r2", "r9", "r3"],
                          "rts": [t(1, 0, 0, 5), t(1, 0, 0, 30), t(1, 0, 1), t(1, 0, 15),
                                  t(1, 0, 0, 1)]},
                         schema_overrides={"rts": TS})
    c = window_candidates(left, right, ["k"], 0.0, 120.0)
    assert sorted(c.select("lid", "rid").iter_rows()) == [
        ("a", "r0"), ("a", "r1"), ("a", "r2"), ("b", "r1"), ("b", "r2")]
    c = window_candidates(left, right, ["k"], -10.0, 10.0)
    assert sorted(c.select("lid", "rid").iter_rows()) == [("a", "r0"), ("b", "r0")]
