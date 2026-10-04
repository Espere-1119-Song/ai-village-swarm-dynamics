"""QA report for `avsd build-events` (SPEC 4.1 step 8, 4.2, 4.3).

Aggregates only: counts, distributions, agent (model) names and live UI links
without text. Expected values come from the verification in
docs/schema_notes.md section 4 and docs/decisions.md.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from avsd.events.refs import ref_type
from avsd.events.unified import EXPECTED_ROOM_SPELLS, SOURCES, TEXT_MAX

if TYPE_CHECKING:
    from avsd.events.build import BuildResult

# Expected values on the pinned export (schema_notes 4, decisions.md).
EXPECTED_LINKS = {
    "send_message_back_to_chat": 100_353,
    "search_history": 9_945,
    "pause": 39_277,
    "move_to_room": 392,
    "request_Google_sign_in": 619,
    "request_approval_for_unsolicited_outreach": 352,
    "request_human_helper": 130,
    "cancel_request_for_human_helper": 33,
}
EXPECTED_SESSION_CATEGORIES = {"start_only": 25_969, "consolidate_only": 52_319, "both": 6,
                               "neither": 70}
EXPECTED_CHAT_ACTORS = {"agent": 173_493, "human": 7_762, "system": 2_230}
EXPECTED_RUN_DAYS, EXPECTED_HUMAN_ONLY_DATES = 389, 10
EXPECTED_ROOMS = {"strict": 173_486, "lookahead": 173_492, "of": 173_493}
EXPECTED_VILLAGE_DAY = 789
LIVE_URL = "https://theaidigest.org/village?day={day}&time={ms}"


def _fmt(v) -> str:
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_fmt(v) for v in r) + " |" for r in rows]
    return out + [""]


def _ok(got, exp) -> str:
    return "ok" if got == exp else f"differs by {got - exp:+,}"


def _ref_type(ref: str) -> str:
    """refs.ref_type, with a catch-all for keys it does not parse (e.g. `path:.`)."""
    try:
        return ref_type(ref)
    except (IndexError, ValueError):
        return ref.split(":", 1)[0] + ":other"


TABLES = {"chat": "chat_messages", "event": "events", "session": "computer_use_sessions",
          "turn": "computer_use_turns", "memory": "agent_memories", "summary": "summaries"}


def _quantiles(s: pl.Series, qs=(0.0, 0.1, 0.5, 0.9, 1.0)) -> list[float]:
    return [float(s.quantile(q)) if s.len() else float("nan") for q in qs]


def _unmatched(expected: pl.Series, got: pl.Series) -> int:
    """Ids not accounted for exactly once: expected ids missing from `got`,
    plus rows of `got` that repeat an id or carry an id not expected."""
    e = pl.DataFrame({"id": expected.unique()}).with_columns(pl.lit(True).alias("_exp"))
    g = pl.DataFrame({"id": got.drop_nulls()}).group_by("id").len()
    j = e.join(g, on="id", how="full", coalesce=True).with_columns(
        pl.col("len").fill_null(0).cast(pl.Int64))
    return int(j.select(pl.when(pl.col("_exp")).then((pl.col("len") - 1).abs())
                        .otherwise(pl.col("len")).sum()).item())


def reconciliation(res: BuildResult, tables: Path) -> tuple[list[list], bool, dict]:
    """Per source table, measured on the output: table rows = emitted + linked + not emitted.

    `linked` counts the chat and session rows that carry an event id
    (`src_event_id`). `ids not matched` checks the ids themselves: every row
    of the table must appear exactly once among the emitted rows; for events,
    the event rows must be all events but the talk events with a chat row,
    START_USING_COMPUTER and USER_NAME_CHANGE, chat rows must carry exactly
    those talk events and session rows exactly the START events.
    """
    df = res.unified
    u = df.select(pl.col("source").cast(pl.String),
                  pl.col("event_uid").str.splitn(":", 2).struct.field("field_1").alias("rid"),
                  "src_event_id")
    by = {s: u.filter(pl.col("source") == s) for s in SOURCES}
    ev = pl.read_parquet(tables / "events.parquet", columns=["id", "action_type", "message_id"])
    chat_ids = pl.read_parquet(tables / "chat_messages.parquet", columns=["id"])["id"]
    at = pl.col("action_type")
    talk = ev.filter(at.is_in(["AGENT_TALK", "USER_TALK"])
                     & pl.col("message_id").is_in(chat_ids.implode()))["id"]
    start = ev.filter(at == "START_USING_COMPUTER")["id"]
    rename = ev.filter(at == "USER_NAME_CHANGE")["id"]
    emit = ev.filter(~pl.col("id").is_in(talk.implode())
                     & ~at.is_in(["START_USING_COMPUTER", "USER_NAME_CHANGE"]))["id"]
    chat_src = by["chat"]["src_event_id"].drop_nulls()
    sess_src = by["session"]["src_event_id"].drop_nulls()
    links = {
        "chat_carrying": chat_src.len(), "talk_with_chat_row": talk.len(),
        "chat_unmatched": _unmatched(talk, chat_src),
        "session_carrying": sess_src.len(), "start_events": start.len(),
        "session_unmatched": _unmatched(start, sess_src),
    }
    rows = []
    for src, table in TABLES.items():
        if src == "event":
            n, linked, not_emitted = ev.height, chat_src.len() + sess_src.len(), rename.len()
            bad = (_unmatched(emit, by[src]["rid"]) + links["chat_unmatched"]
                   + links["session_unmatched"])
        else:
            ids = pl.read_parquet(tables / f"{table}.parquet", columns=["id"])["id"]
            n, linked, not_emitted = ids.len(), 0, 0
            bad = _unmatched(ids, by[src]["rid"])
        emitted = by[src].height
        rows.append([table, src, n, emitted, linked, not_emitted,
                     n - (emitted + linked + not_emitted), bad])
    ok = all(r[6] == 0 and r[7] == 0 for r in rows)
    return rows, ok, links


def time_ranges(df: pl.DataFrame, tables: Path) -> list[list]:
    """Per source: rows, the range of ts_utc and PT dates, and the raw table's created_at range."""
    rng = (df.group_by(pl.col("source").cast(pl.String))
           .agg(pl.len(), pl.col("ts_utc").min().alias("t0"), pl.col("ts_utc").max().alias("t1"),
                pl.col("ts_pt").dt.date().min().alias("d0"),
                pl.col("ts_pt").dt.date().max().alias("d1")))
    by = {r["source"]: r for r in rng.iter_rows(named=True)}
    out = []
    for src, table in TABLES.items():
        r = by.get(src)
        if r is None:
            continue
        raw = pl.scan_parquet(tables / f"{table}.parquet").select(
            pl.col("created_at").min().alias("c0"), pl.col("created_at").max().alias("c1")
        ).collect().row(0)
        out.append([src, "updated_at" if src == "summary" else "created_at", r["len"],
                    _ts(r["t0"], sec=True), _ts(r["t1"], sec=True), r["d0"], r["d1"],
                    f"{table}: {_ts(raw[0], sec=True)} to {_ts(raw[1], sec=True)}"])
    return out


def write_report(res: BuildResult, cfg: dict, path: Path) -> None:
    df, st = res.unified, res.stats
    tables = Path(cfg["paths"]["tables"])
    agents = res.agents
    names = dict(agents.select("agent_id", "name").iter_rows())
    L: list[str] = [
        "# QA report: build-events",
        "",
        "Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village",
        "",
        f"Dataset revision `{cfg['dataset']['revision']}`. Pause gap G = "
        f"{cfg['time']['pause_gap_minutes']} min. Runtime {st.get('runtime_s', 0):.0f} s, "
        f"peak RSS {st.get('peak_rss_gb', 0):.1f} GB.",
        "",
        "Step timings (s): " + ", ".join(f"{k} {v:.0f}" for k, v in st["timings"].items()) + ".",
        "",
    ]

    # 1. Row accounting.
    rec, ok, lk = reconciliation(res, tables)
    manifest = Path(cfg["paths"]["raw"]) / "manifest.json"
    man = json.loads(manifest.read_text()).get("rowCounts", {}) if manifest.exists() else {}
    L += ["## 1. Row accounting (SPEC 4.3)", "",
          "Each source table must equal emitted + linked (carried by another row) + not "
          "emitted, all measured on the output. Events linked: chat rows that carry their "
          "talk event and session rows that carry their START_USING_COMPUTER event "
          "(`src_event_id`). Not emitted: USER_NAME_CHANGE. `ids not matched` counts table ids "
          "that are not accounted for exactly once (missing, repeated or unexpected; for events "
          "also a chat or session row carrying the wrong event).", ""]
    L += _table(
        ["table", "source", "table rows", "manifest", "emitted", "linked", "not emitted",
         "difference", "ids not matched"],
        [[r[0], r[1], r[2], man.get(r[0], "n/a"), r[3], r[4], r[5], r[6], r[7]] for r in rec],
    )
    L += [f"- Reconciles exactly: **{ok}**. Unified rows: {df.height:,}.",
          f"- Chat rows carrying a talk event: {lk['chat_carrying']:,}; talk events with a chat "
          f"row: {lk['talk_with_chat_row']:,}; not matched one-to-one: {lk['chat_unmatched']:,}.",
          f"- Session rows carrying a START event: {lk['session_carrying']:,}; START events: "
          f"{lk['start_events']:,}; not matched one-to-one: {lk['session_unmatched']:,}.", ""]
    L += ["Time range per source (`ts_utc`; summaries are timed by `updated_at`) and the raw "
          "table's `created_at` range:", ""]
    L += _table(["source", "timed by", "rows", "first ts_utc", "last ts_utc", "first PT date",
                 "last PT date", "raw table created_at"], time_ranges(df, tables))
    ct = st["chat_talk"]
    L += ["Chat and talk events:", ""]
    L += _table(["check", "value", "expected"], [
        ["talk events (AGENT_TALK + USER_TALK)", ct["talk_events"], 183_542],
        ["linked to a chat row", ct["linked"], 183_485],
        ["distinct chat rows linked", ct["linked_distinct_chat"], 183_485],
        ["chat rows without a talk event", ct["chat_without_talk"], 0],
        ["talk events without a chat row (emitted, chat_row_missing)", ct["orphans"], 57],
        ["linked pairs whose room differs", ct["room_mismatch"], 0],
        ["USER_NAME_CHANGE (not emitted)", st["event_types"].get("USER_NAME_CHANGE", 0), 3_711],
    ])

    # 2. Actors.
    L += ["## 2. Actors", ""]
    at = (df.group_by("source", "actor_type").len()
          .with_columns(pl.col("source").cast(pl.String), pl.col("actor_type").cast(pl.String)))
    piv = {(s, a): n for s, a, n in at.iter_rows()}
    L += _table(["source", "agent", "human", "system", "null"], [
        [s, piv.get((s, "agent"), 0), piv.get((s, "human"), 0), piv.get((s, "system"), 0),
         piv.get((s, None), 0)] for s in SOURCES
    ])
    chat_at = {a: piv.get(("chat", a), 0) for a in EXPECTED_CHAT_ACTORS}
    L += ["Chat rows by actor_type vs schema_notes 4.6: " + ", ".join(
        f"{a} {chat_at[a]:,} (expected {e:,}, {_ok(chat_at[a], e)})"
        for a, e in EXPECTED_CHAT_ACTORS.items()) + ".", ""]
    era = (df.group_by("source", "rooms_era", "actor_type").len()
           .with_columns(pl.all().exclude("len").cast(pl.String)))
    eras = ["R0", "R1", "R2", "R3"]
    epiv = {(s, e, a): n for s, e, a, n in era.iter_rows()}
    L += ["By rooms era (R0 < 2026-02-25, R1 to 03-15, R2 to 07-05, R3 from 07-06), rows as "
          "agent / human / system:", ""]
    L += _table(["source", *eras], [
        [s, *[" / ".join(f"{epiv.get((s, e, a), 0):,}" for a in ("agent", "human", "system"))
              for e in eras]] for s in SOURCES
    ])
    L += ["Event rows that are not agent rows, by raw action type: " + ", ".join(
        f"{k} {v:,}" for k, v in sorted(st["event_actor_rules"].items())) + ".", ""]
    nonag = (df.filter(pl.col("actor_type") != "agent").group_by("actor_id").len()
             .sort("len", "actor_id", descending=[True, False]))
    L += ["Non-agent actor ids: " + ", ".join(f"`{a}` {n:,}" for a, n in nonag.iter_rows())
          + ".", ""]
    nt = st["nudge_targets"]
    tgt = (df.filter(pl.col("actor_type") != "agent").group_by("actor_id")
           .agg(pl.len(), pl.col("target_agent_id").is_not_null().sum().alias("t"))
           .sort("actor_id"))
    L += [f"Auto-nudges with a leading `@<agent name>` of a known agent (`target_agent_id`): "
          f"{nt['with_target']:,} of {nt['nudges']:,} (schema_notes 4.6: 1,567 of 1,568 name a "
          "known agent). Non-agent rows with `target_agent_id` by actor: " + ", ".join(
              f"`{a}` {t:,} of {n:,}" for a, n, t in tgt.iter_rows()) + ".", ""]

    # 3. Kinds.
    L += ["## 3. kind and subkind", ""]
    # Ties broken by subkind, so the report is the same on every run.
    ks = (df.group_by("kind", "subkind").len()
          .with_columns(pl.col("kind").cast(pl.String))
          .sort("kind", "len", "subkind", descending=[False, True, False], nulls_last=True))
    L += _table(["kind", "subkind", "rows"], [list(r) for r in ks.iter_rows()])
    tk = (df.filter(pl.col("source") == "turn").group_by(pl.col("turn_kind").cast(pl.String))
          .len().sort("len", "turn_kind", descending=[True, False]))
    L += ["turn_kind: " + ", ".join(f"{k} {n:,}" for k, n in tk.iter_rows()) + ".", ""]
    L += [f"Run markers flagged (`is_run_marker`): "
          f"{int(df['is_run_marker'].sum()):,}, of which bot rows "
          f"{int(df.filter(pl.col('is_run_marker') & (pl.col('actor_type') == 'system')).height):,}"
          ".", ""]

    # 4. Nulls.
    agent = pl.col("actor_type") == "agent"
    checks = [
        ["ts_utc null", df["ts_utc"].null_count(), 0],
        ["actor_type null", df["actor_type"].null_count(), 0],
        ["actor_id null", df["actor_id"].null_count(), 0],
        ["agent rows without model_family", df.filter(agent & pl.col("model_family").is_null())
         .height, 0],
        ["agent rows whose actor is not in agents", df.filter(agent & pl.col("model").is_null())
         .height, 0],
        ["agent rows without agent_room_id", df.filter(agent & pl.col("agent_room_id").is_null())
         .height, 0],
        ["village_day null", df["village_day"].null_count(), 0],
        ["rows without goal_id (before the first goal)", df["goal_id"].null_count(), "n/a"],
        ["duplicate event_uid", df.height - df["event_uid"].n_unique(), 0],
        ["text_ref null", df["text_ref"].null_count(), 0],
        [f"inline text longer than {TEXT_MAX:,} chars", int(
            (df["text"].str.len_chars() > TEXT_MAX).sum()), 0],
    ]
    fam = (df.filter(agent)["model_family"].value_counts()
           .sort("count", "model_family", descending=[True, False]))
    L += ["## 4. Null checks (SPEC 4.3)", ""]
    L += _table(["check", "rows", "expected"], checks)
    cut = (df.filter(pl.col("text").is_not_null() & (pl.col("text_len") > TEXT_MAX))
           .group_by(pl.col("source").cast(pl.String)).len().sort("source"))
    L += [f"Rows whose inline text is cut to {TEXT_MAX:,} chars (full text by `text_ref`; memory "
          "snapshots, summaries and outreach payloads have no inline text): " + ", ".join(
              f"{s} {n:,}" for s, n in cut.iter_rows()) + ".", ""]
    L += ["Agent rows by model_family: " + ", ".join(f"{f} {n:,}" for f, n in fam.iter_rows())
          + f". Agents with rows: {df.filter(agent)['actor_id'].n_unique()} of {agents.height}.",
          ""]
    sess_cov = (df.filter(agent).group_by("source", "kind")
                .agg(pl.len(), pl.col("session_id").is_not_null().sum().alias("with_session"))
                .with_columns(pl.col("source").cast(pl.String), pl.col("kind").cast(pl.String))
                .sort("source", "kind"))
    L += ["session_id coverage of agent rows:", ""]
    L += _table(["source", "kind", "rows", "with session_id"], [list(r) for r in
                                                              sess_cov.iter_rows()])

    # 5. village_day.
    sm = pl.read_parquet(tables / "summaries.parquet",
                         columns=["type", "summary_target", "summary_date"])
    # village_day of the table's own rows on each PT date vs the summary's day number.
    day_map = df.select(pl.col("ts_pt").dt.date().alias("d"), "village_day").unique()
    if day_map["d"].n_unique() != day_map.height:
        raise ValueError("a PT date maps to more than one village_day")
    daily = (
        sm.filter(pl.col("type") == "daily")
        .with_columns(
            pl.col("summary_target").cast(pl.Int64, strict=False).alias("target"),
            pl.col("summary_date").str.to_date(strict=False).alias("d"),
        )
        .with_columns(((pl.col("d") - pl.lit(_day1(cfg))).dt.total_days() + 1).alias("formula"))
        .join(day_map, on="d", how="left")
    )
    num = daily.filter(pl.col("target").is_not_null())
    on_rows = num.filter(pl.col("village_day").is_not_null())
    L += ["## 5. village_day vs daily summaries", "",
          f"- Daily summary rows {daily.height:,}, with a numeric day target {num.height:,} "
          f"(the other {daily.height - num.height} have no target).",
          f"- Target equals `(summary_date - {cfg['time']['village_day1']}) + 1`: "
          f"{int((num['target'] == num['formula']).sum()):,} of {num.height:,} (expected "
          f"{EXPECTED_VILLAGE_DAY}/{EXPECTED_VILLAGE_DAY}).",
          f"- Target equals the village_day of this table's rows on the summary's PT date: "
          f"{int((on_rows['target'] == on_rows['village_day']).sum()):,} of {on_rows.height:,} "
          f"(summary dates with rows). Each PT date has one village_day; range "
          f"{df['village_day'].min()} to {df['village_day'].max()}.", ""]

    # 6. Rooms.
    r = st["rooms"]
    L += ["## 6. Room reconstruction (agent messages)", "",
          "The agent's room is the room of its latest earlier room-carrying event "
          "(event_index order). Strict uses only earlier events (`general` if none); "
          "`agent_room_id` adds `general` before 2026-03-05 and a look-ahead to the next event "
          "for an agent's first appearance (an ENTER_ROOM row itself is in the room it left).",
          ""]
    L += _table(["rule", "correct", "of", "expected"], [
        ["strict", r["strict_correct"], r["agent_msgs"], EXPECTED_ROOMS["strict"]],
        ["agent_room_id (look-ahead)", r["lookahead_correct"], r["agent_msgs"],
         EXPECTED_ROOMS["lookahead"]],
    ])
    ri = st["room_intervals"]
    L += [f"`agent_room_intervals.parquet`: {ri['spells']:,} room spells for {ri['agents']} "
          f"agents. Opened by a room-carrying event: {ri['by_event']:,} (expected "
          f"{EXPECTED_ROOM_SPELLS}: each agent's first room plus 420 changes; "
          f"{_ok(ri['by_event'], EXPECTED_ROOM_SPELLS)}). Opened by the rule before an agent's "
          f"first room-carrying event (`general` before 2026-03-05 PT, then that event's room, "
          f"or the room an ENTER_ROOM left): {ri['by_rule']:,}. Spells ending before they start "
          f"(event_index and time disagree): {ri['end_before_start']:,}.",
          f"- Agent rows whose `agent_room_id` equals the spell room at their time (latest spell "
          f"start strictly before the row): {ri['agent_rows_agree']:,} of {ri['agent_rows']:,}. "
          f"The rules are the same; the lookup goes by time, `agent_room_id` by event_index "
          f"where a row has one, so a difference means the two orders disagree near a room event.",
          "- Retired agents stay in their last room; exposure lookups also need "
          "`roster_daily.active`.", ""]

    # 7. Links.
    tl = st["turn_links"]
    L += ["## 7. Duplicate turns and links", "",
          "Turns that mirror a chat row or an event keep `dup_of_uid`; greedy one-to-one "
          "matching by time difference (send_message: same agent and exact content, chat row "
          "0-300 s later; search_history: same agent, exact query, |dt| <= 120 s, errored turns "
          "dropped; others: same agent, first event of the type 0-120 s later).", ""]
    L += _table(["turn action", "turns", "linked", "expected", "check"], [
        [k, n, m, EXPECTED_LINKS.get(k, "n/a"),
         _ok(m, EXPECTED_LINKS[k]) if k in EXPECTED_LINKS else ""]
        for k, (n, m) in tl.items()
    ])
    ndup = int(df.filter(pl.col("dup_of_uid").is_not_null()).height)
    L += ["- The documented pause count (39,277) is a many-to-one forward join (39,180 distinct "
          "PAUSE events); the one-to-one match pairs each event with at most one turn.",
          f"- Turns with dup_of_uid: {ndup:,}. Rows with linked_uid by source: " + ", ".join(
        f"{s} {n:,}" for s, n in df.filter(pl.col("linked_uid").is_not_null())
        .group_by("source").len().with_columns(pl.col("source").cast(pl.String))
        .sort("source").iter_rows()) + ".", ""]
    ml = st["memory_links"]
    L += [f"- Memory rows with a STOP/CONSOLIDATE event 0-1 s later: {ml['linked_end']:,} of "
          f"{ml['rows']:,} ({ml['linked_end_distinct']:,} distinct events). Memory session_id "
          f"from the label UUID {ml['session_from_label']:,} (label UUIDs {ml['label_uuid']:,}, "
          f"of which a session of the same agent {ml['label_uuid_own_session']:,}), from the "
          f"linked end event {ml['session_from_end_event']:,}, from the latest session "
          f"{ml['session_from_asof']:,}.", ""]
    rel = st["memory_rel"]
    L += ["- Memory relations: " + ", ".join(f"{k} {rel.get(k, 0):,}" for k in sorted(rel))
          + ".", ""]

    # 8. Sessions.
    cat = dict(res.sessions.group_by("category").len().iter_rows())
    sm_ = st["stop_map"]
    L += ["## 8. Sessions", ""]
    L += _table(["category", "sessions", "expected", "check"], [
        [k, cat.get(k, 0), e, _ok(cat.get(k, 0), e)]
        for k, e in EXPECTED_SESSION_CATEGORIES.items()
    ])
    n_two = int(res.sessions.filter(pl.col("n_cons") > 1).height)
    L += [f"- The documented categories sum to {sum(EXPECTED_SESSION_CATEGORIES.values()):,}, "
          f"not {res.sessions.height:,}: {n_two} sessions have two CONSOLIDATE events and were "
          f"counted twice there. Here each session counts once.", ""]
    noend = res.sessions.filter(pl.col("close_ts").is_null()).height
    L += [f"- STOP_USING_COMPUTER mapped to the agent's latest session: {sm_['mapped']:,} of "
          f"{sm_['stops']:,}, distinct sessions {sm_['distinct_sessions']:,} "
          f"(expected 25,939 one-to-one).",
          f"- Sessions without a STOP or CONSOLIDATE: {noend:,} (end = last turn); without "
          f"turns: {res.sessions['n_turns'].null_count():,}.", ""]

    # 9. Run periods.
    b, p = res.blocks, res.pauses
    run_dates = b["date"].n_unique()
    all_dates = df["ts_pt"].dt.date().n_unique()
    no_run = (df.filter(pl.col("run_day").is_null())
              .select(pl.col("ts_pt").dt.date().alias("d"), "actor_type", "source"))
    no_run_by_src = no_run.group_by("source", "actor_type").agg(
        pl.len(), pl.col("d").n_unique().alias("dates")).with_columns(
        pl.col("source").cast(pl.String), pl.col("actor_type").cast(pl.String))
    day = b.group_by("date", "schedule_regime").agg(
        pl.col("start").min(), pl.col("end").max(), pl.col("active_seconds").sum(),
        pl.len().alias("blocks"),
    ).with_columns(((pl.col("end") - pl.col("start")).dt.total_seconds() / 3600).alias("span_h"),
                   (pl.col("active_seconds") / 3600).alias("active_h"))
    L += ["## 9. Run periods and active time (SPEC 4.2)", "",
          f"- Run days (PT dates with agent rows): {run_dates} (expected {EXPECTED_RUN_DAYS}). "
          f"Dates with rows but no agent row (null run_day): {no_run['d'].n_unique()}, "
          f"{no_run.height:,} rows: " + ", ".join(
              f"{s} / {a} {n:,} rows on {k} dates" for s, a, n, k in no_run_by_src.iter_rows())
          + f". All dates with rows: {all_dates}. schema_notes 4.8 counts "
          f"{EXPECTED_HUMAN_ONLY_DATES} weekend dates with only human rows; those were viewer "
          f"renames (USER_NAME_CHANGE), which this table does not emit, so no date here has "
          f"human rows without agent rows.",
          "- Interval rows: agent rows except memory snapshots (scaffold writes).",
          f"- Realizations (blocks): {b.height}. Pause segments (gaps > G within a date): "
          f"{p.height}, total {p['seconds'].sum() / 3600:.1f} h. Main block (block 0) of a date: "
          f"most overlap with the scheduled window, else the longest.",
          f"- Rows outside their block (`in_run` false): "
          f"{int((~df['in_run']).sum()):,}, by actor_type " + ", ".join(
              f"{a} {n:,}" for a, n in df.filter(~pl.col("in_run")).group_by("actor_type").len()
              .with_columns(pl.col("actor_type").cast(pl.String)).sort("actor_type").iter_rows())
          + ".",
          f"- Total active time {b['active_seconds'].sum() / 3600:,.1f} h; max t_active "
          f"{df['t_active'].max() / 3600:,.1f} h; t_active non-decreasing in row order: "
          f"{df['t_active'].is_sorted()}.", ""]
    q = (0.0, 0.1, 0.5, 0.9, 1.0)
    L += ["Daily run length (hours, first to last agent row of the date) by schedule regime:",
          ""]
    rows_ = []
    for reg in ["2h", "3h", "4h", "8h_event", "8h"]:
        d = day.filter(pl.col("schedule_regime") == reg)
        rows_.append([reg, d.height, *[round(x, 2) for x in _quantiles(d["span_h"], q)],
                      round(float(d["active_h"].sum()), 1)])
    L += _table(["regime", "days", "min", "p10", "median", "p90", "max", "active h"], rows_)
    multi = b.filter(pl.col("date").is_in(b.filter(pl.col("block") > 0)["date"].implode()))
    L += ["Dates with more than one block (block 0 = main):", ""]
    L += _table(["date", "block", "realization_id", "start PT", "end PT", "minutes",
                 "agent rows"], [
        [r_["date"], r_["block"], r_["realization_id"],
         r_["start"].astimezone(_tz(cfg)).strftime("%H:%M"),
         r_["end"].astimezone(_tz(cfg)).strftime("%H:%M"),
         round(r_["active_seconds"] / 60, 1), r_["n_agent_rows"]]
        for r_ in multi.sort("date", "start").iter_rows(named=True)
    ])
    L += ["Pause segments:", ""]
    L += _table(["date", "from PT", "to PT", "minutes"], [
        [r_["date"], r_["start"].astimezone(_tz(cfg)).strftime("%H:%M"),
         r_["end"].astimezone(_tz(cfg)).strftime("%H:%M"), round(r_["seconds"] / 60, 1)]
        for r_ in p.iter_rows(named=True)
    ])
    gs = st["g_sensitivity"]
    L += ["Total active time by G: " + ", ".join(
        f"G={g} min {v / 3600:,.1f} h" for g, v in gs.items()) + " (schema_notes 4.8: "
        "1,596-1,600 h for G between 15 and 60 min).", ""]

    # 10. refs.
    rs = (df.group_by("source").agg(
        pl.len(), (pl.col("refs").list.len() > 0).sum().alias("with_refs"),
        pl.col("refs").list.len().sum().alias("refs"),
        (pl.col("refs_obs").list.len() > 0).sum().alias("with_refs_obs"),
        pl.col("refs_obs").list.len().sum().alias("refs_obs"))
        .with_columns(pl.col("source").cast(pl.String)).sort("source"))
    L += ["## 10. refs", "",
          "`refs`: references in text the actor produced; `refs_obs`: references seen only in "
          "tool output, errors and search answers (minus those already in `refs`).", ""]
    L += _table(["source", "rows", "rows with refs", "refs", "rows with refs_obs", "refs_obs"],
                [list(r_) for r_ in rs.iter_rows()])
    for col in ("refs", "refs_obs"):
        vc = df.select(pl.col(col).explode(empty_as_null=True).drop_nulls()
                       .value_counts(sort=True)).unnest(col)
        typ = vc.with_columns(
            pl.col(col).map_elements(_ref_type, return_dtype=pl.String).alias("type")
        ).group_by("type").agg(pl.col("count").sum()).sort(
            "count", "type", descending=[True, False]).head(15)
        L += [f"Top `{col}` types (owners hashed): " + ", ".join(
            f"{t} {n:,}" for t, n in typ.iter_rows()) + ".", ""]

    # 11. Agents.
    act_days = res.roster.group_by("agent_id").agg(pl.col("active").sum().alias("days"))
    ag = agents.join(act_days, on="agent_id", how="left")
    L += ["## 11. Agents", ""]
    L += _table(["agent", "provider", "family", "scaffold", "model group", "first active (UTC)",
                 "last active (UTC)", "active run days"], [
        [r_["name"], r_["provider"], r_["model_family"], r_["scaffold"], r_["model_group"],
         _ts(r_["first_active_ts"]), _ts(r_["last_active_ts"]), r_["days"]]
        for r_ in ag.iter_rows(named=True)
    ])
    fams = agents.group_by("model_family").len().sort("model_family")
    L += ["Agents by family: " + ", ".join(f"{f} {n}" for f, n in fams.iter_rows())
          + " (expected Anthropic 16, Google 5, OpenAI 14, Other 11).", ""]

    # 12. Spot check.
    pool = df.filter(agent & pl.col("source").is_in(["chat", "event", "session", "turn"]))
    spot = pool.sample(min(20, pool.height), seed=int(cfg["seed"])).sort("ts_utc")
    L += ["## 12. Spot check: 20 random agent rows with live UI links", "",
          f"Seed {cfg['seed']}. Agent rows only, no text.", ""]
    L += _table(["ts_pt", "village_day", "agent", "kind", "live UI"], [
        [r_["ts_pt"].strftime("%Y-%m-%d %H:%M:%S %Z"), r_["village_day"],
         names.get(r_["actor_id"], "?"), r_["kind"],
         LIVE_URL.format(day=r_["village_day"], ms=int(r_["ts_utc"].timestamp() * 1000))]
        for r_ in spot.iter_rows(named=True)
    ])

    # 13. CHANGELOG.
    cl = st.get("changelog")
    if cl is not None:
        L += ["## 13. CHANGELOG table (SPEC 4.1 step 7)", "",
              f"`changelog.parquet`: {sum(cl.values()):,} rows, " + ", ".join(
                  f"{s} {n:,}" for s, n in sorted(cl.items()))
              + " (categories from the changelog.py rules and CATEGORY_OVERRIDES).", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def _day1(cfg: dict):
    from datetime import date
    return date.fromisoformat(str(cfg["time"]["village_day1"]))


def _tz(cfg: dict):
    from zoneinfo import ZoneInfo
    return ZoneInfo(cfg["time"]["village_tz"])


def _ts(v, sec: bool = False) -> str:
    return v.strftime("%Y-%m-%d %H:%M" + (":%S" if sec else "")) if v is not None else "n/a"

