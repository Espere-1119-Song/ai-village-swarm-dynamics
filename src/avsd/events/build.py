"""`avsd build-events` (SPEC 4.1 steps 3-6 and 8, 4.2).

Writes to `data/processed/`:

- `events_unified.parquet` (unified.UNIFIED_SCHEMA), sorted by
  (ts_utc, source, event_index, event_uid) with `source` compared as text,
- `run_periods.parquet` and `pause_segments.parquet` (runs.py),
- `agents.parquet` (agents.py) and `roster_daily.parquet` (roster.py),
- `agent_room_intervals.parquet` (unified.agent_room_intervals),
- `human_ids.parquet`: raw user ids of human and bot rows (never leaves data/),
- `changelog.parquet` from `<paths.raw>/CHANGELOG.md` (changelog.py, SPEC 4.1 step 7),

and the QA report `outputs/qa/build_events.md` (aggregates only).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import resource
import time
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from avsd.config import load_config
from avsd.events import unified as U
from avsd.events.agents import build_agents, load_agent_meta
from avsd.events.roster import build_roster
from avsd.events.runs import assign_run_columns, find_blocks, schedule_regime


ORDER = ["ts_utc", "source", "event_index", "event_uid"]  # file order of events_unified


@dataclass
class BuildResult:
    unified: pl.DataFrame
    blocks: pl.DataFrame
    pauses: pl.DataFrame
    agents: pl.DataFrame
    roster: pl.DataFrame
    humans: pl.DataFrame
    sessions: pl.DataFrame
    room_intervals: pl.DataFrame
    stats: dict = field(default_factory=dict)


def _event_sessions(events: pl.DataFrame, ev: pl.DataFrame, sessions: pl.DataFrame) -> pl.DataFrame:
    """CONSOLIDATE: its cu_session_id. STOP: the agent's latest session at or before it."""
    stop = U.stop_sessions(ev, sessions).select(pl.col("stop_id").alias("_id"),
                                                pl.col("session_id").alias("_stop_sid"))
    return (
        events.join(stop, on="_id", how="left")
        .with_columns(
            pl.when(pl.col("_action_type") == "CONSOLIDATE").then(pl.col("_cu_session_id"))
            .when(pl.col("_action_type") == "STOP_USING_COMPUTER").then(pl.col("_stop_sid"))
            .alias("session_id")
        )
        .drop("_stop_sid")
    )


def assemble(tables: Path, tz: str, gap_s: float, n_workers: int | None = None) -> BuildResult:
    """Build every output in memory from the parquet tables in `tables`."""
    tables = Path(tables)
    stats: dict = {"timings": {}}
    clock = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        stats["timings"][name] = now - clock
        clock = now

    meta = load_agent_meta(tables)
    names = dict(meta.select("agent_id", "name").iter_rows())
    ev = U.load_events(tables)
    turns_last = (
        pl.scan_parquet(tables / "computer_use_turns.parquet")
        .group_by("session_id").agg(pl.col("created_at").max().alias("last_turn_ts"),
                                    pl.len().alias("n_turns"))
        .collect()
    )
    sessions = U.load_sessions(tables, ev, turns_last)
    stops = U.stop_sessions(ev, sessions)
    stats["stop_map"] = {
        "stops": stops.height,
        "mapped": int(stops["session_id"].is_not_null().sum()),
        "distinct_sessions": int(stops["session_id"].drop_nulls().n_unique()),
    }
    lap("inputs")

    chat, humans = U.build_chat(tables, ev, names, stats)
    lap("chat")
    events = U.build_events_rows(tables, ev, chat["src_event_id"].drop_nulls(), stats)
    events = _event_sessions(events, ev, sessions)
    humans = pl.concat([
        humans,
        events.filter(pl.col("_action_type") == "USER_TALK").select(
            "event_uid", pl.col("_speaker_id").alias("user_id"),
            (pl.col("_speaker_id") == U.BOT_USER_ID).alias("is_bot")),
    ])
    lap("events")
    sess_rows = U.build_session_rows(sessions)
    lap("sessions")
    turn_rows, back = U.build_turn_rows(tables, sessions, ev, chat, stats)
    lap("turns")
    mem_rows = U.build_memory_rows(tables, ev, sessions, n_workers, stats)
    lap("memory")
    summ_rows = U.build_summary_rows(tables, names)

    # Chat and event rows that a turn mirrors: linked_uid and the turn's session.
    turn_sid = turn_rows.select(pl.col("event_uid").alias("linked_uid"),
                                pl.col("session_id").alias("_turn_sid"))
    back = back.join(turn_sid, on="linked_uid", how="left")

    df = pl.concat(
        [chat, events.drop("_id", "_action_type", "_cu_session_id", "_speaker_id"), sess_rows,
         turn_rows, mem_rows, summ_rows],
        how="diagonal_relaxed",
    )
    df = (
        df.join(back.select("event_uid", pl.col("linked_uid").alias("_back"), "_turn_sid"),
                on="event_uid", how="left")
        .with_columns(
            pl.coalesce("linked_uid", "_back").alias("linked_uid"),
            pl.when(pl.col("actor_type") == "agent")
            .then(pl.coalesce("session_id", "_turn_sid")).otherwise(pl.col("session_id"))
            .alias("session_id"),
        )
        .drop("_back", "_turn_sid")
    )
    if df["event_uid"].n_unique() != df.height:
        raise ValueError("duplicate event_uid")
    # Time order: the joins below keep the left order (maintain_order="left"),
    # and their asof joins need ts_utc sorted. The file order is re-imposed at the end.
    df = df.sort(ORDER, nulls_last=True, maintain_order=True)
    lap("concat")

    # Time, eras and agent attributes.
    df = df.with_columns(pl.col("ts_utc").dt.convert_time_zone(tz).alias("ts_pt")).with_columns(
        pl.col("ts_pt").dt.date().alias("date")
    ).with_columns(
        ((pl.col("date") - pl.lit(U.VILLAGE_DAY1)).dt.total_days() + 1).cast(pl.Int32)
        .alias("village_day"),
        U.rooms_era(pl.col("date")).alias("rooms_era"),
        schedule_regime(pl.col("date")).alias("schedule_regime"),
    )
    agent_cols = meta.select(
        pl.col("agent_id").alias("actor_id"), pl.col("model_string").alias("_model"),
        pl.col("model_family").alias("_family"), pl.col("provider").alias("_provider"),
        pl.col("scaffold").cast(pl.String).alias("_scaffold"),
    )
    is_agent = pl.col("actor_type") == "agent"
    df = df.join(agent_cols, on="actor_id", how="left", maintain_order="left").with_columns(
        pl.when(is_agent).then(pl.col("_model")).alias("model"),
        pl.when(is_agent).then(pl.col("_family")).alias("model_family"),
        pl.when(is_agent).then(pl.col("_provider")).alias("provider"),
        pl.when(is_agent).then(pl.col("_scaffold")).alias("scaffold"),
    ).drop("_model", "_family", "_provider", "_scaffold")

    rooms = pl.read_parquet(tables / "chat_rooms.parquet", columns=["id", "name"])
    general = rooms.filter(pl.col("name") == "general")["id"]
    if general.len() != 1:
        raise ValueError("expected exactly one `general` room")
    df = U.assign_agent_rooms(df, ev, general[0])
    msg = df.filter(pl.col("kind") == "agent_msg")
    stats["rooms"] = {
        "agent_msgs": msg.height,
        "strict_correct": int((msg["_room_strict"] == msg["room_id"]).sum()),
        "lookahead_correct": int((msg["agent_room_id"] == msg["room_id"]).sum()),
        "agent_rows_without_room": int(
            df.filter(is_agent & pl.col("agent_room_id").is_null()).height),
    }
    df = df.drop("_room_strict")
    # Room spells per agent, checked against agent_room_id on every agent row.
    ag_rooms = df.filter(is_agent).select("actor_id", "ts_utc", "agent_room_id")
    first_seen = ag_rooms.group_by(pl.col("actor_id").alias("agent_id")).agg(
        pl.col("ts_utc").min().alias("first_ts"))
    intervals = U.agent_room_intervals(ev, first_seen, general[0], tz)
    looked_up = U.room_at(intervals, ag_rooms)
    stats["room_intervals"] = {
        "spells": intervals.height,
        "agents": intervals["agent_id"].n_unique(),
        "by_event": int((intervals["opened_by"] == "event").sum()),
        "by_rule": int((intervals["opened_by"] == "rule").sum()),
        "end_before_start": int((intervals["end"] < intervals["start"]).sum()),
        "agent_rows": ag_rooms.height,
        "agent_rows_agree": int((looked_up == ag_rooms["agent_room_id"]).sum()),
    }
    df = U.assign_open_sessions(df, sessions)
    df = U.assign_goals(df, tables)
    if "_regime_cu" not in df.columns:
        df = df.with_columns(pl.lit(None, pl.String).alias("_regime_cu"))
    df = U.assign_regime_cu(df, ev, meta)
    lap("attributes")

    # Run periods and run columns.
    if not df["ts_utc"].is_sorted():
        raise ValueError("rows lost their time order")
    # Agent actions define the run intervals; memory snapshots are scaffold writes.
    agent_rows = df.filter(is_agent & (pl.col("source") != "memory")).select("date", "ts_utc")
    blocks, pauses = find_blocks(agent_rows, gap_s, tz)
    stats["g_sensitivity"] = {
        g: float(find_blocks(agent_rows, g * 60.0, tz)[0]["active_seconds"].sum())
        for g in (15, 30, 60)
    }
    df = assign_run_columns(df.lazy(), blocks).collect()
    # File order, independent of how the joins above ordered their output.
    # `source` is still text here, so ties sort chat < event < memory < ...
    df = df.sort(ORDER, nulls_last=True, maintain_order=True)
    lap("runs")

    fills = {
        "text": pl.col("text").str.slice(0, U.TEXT_MAX),  # one rule for every source
        "refs": pl.col("refs").fill_null(pl.lit([], dtype=pl.List(pl.String))),
        "refs_obs": pl.col("refs_obs").fill_null(pl.lit([], dtype=pl.List(pl.String))),
        "chat_row_missing": pl.col("chat_row_missing").fill_null(False),
        "is_run_marker": pl.col("is_run_marker").fill_null(False),
    }
    for c in U.UNIFIED_SCHEMA:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None).alias(c))
    df = df.select(
        [fills.get(c, pl.col(c)).cast(t).alias(c) for c, t in U.UNIFIED_SCHEMA.items()]
    )
    agents = build_agents(meta, df.lazy())
    roster = build_roster(df.lazy(), blocks, agents)
    lap("agents_roster")
    return BuildResult(df, blocks, pauses, agents, roster, humans, sessions, intervals, stats)


def peak_rss_gb() -> float:
    """Peak resident memory of this process and its children (Linux KB units)."""
    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return max(own, kids) / 1024 ** 2


def build_events(cfg: dict | None = None, n_workers: int | None = None) -> BuildResult:
    """Run the build on the configured tables and write all outputs and the QA report."""
    from avsd.events.changelog import write_changelog
    from avsd.events.events_qa import write_report

    cfg = cfg or load_config()
    t0 = time.perf_counter()
    tables = cfg["paths"]["tables"]
    out = Path(cfg["paths"]["processed"])
    gap_s = float(cfg["time"]["pause_gap_minutes"]) * 60.0
    res = assemble(tables, cfg["time"]["village_tz"], gap_s, n_workers or U.default_workers())
    t_write = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    res.unified.write_parquet(out / "events_unified.parquet", compression="zstd",
                              row_group_size=250_000)
    res.blocks.write_parquet(out / "run_periods.parquet")
    res.pauses.write_parquet(out / "pause_segments.parquet")
    res.agents.write_parquet(out / "agents.parquet")
    res.roster.write_parquet(out / "roster_daily.parquet")
    res.room_intervals.write_parquet(out / "agent_room_intervals.parquet")
    res.humans.write_parquet(out / "human_ids.parquet")
    cl = write_changelog(out, Path(cfg["paths"]["raw"]) / "CHANGELOG.md")
    res.stats["changelog"] = dict(cl.group_by("source").len().iter_rows())
    res.stats["timings"]["write"] = time.perf_counter() - t_write
    res.stats["runtime_s"] = time.perf_counter() - t0
    res.stats["peak_rss_gb"] = peak_rss_gb()
    report = cfg["paths"]["outputs"] / "qa" / "build_events.md"
    write_report(res, cfg, report)
    return res

