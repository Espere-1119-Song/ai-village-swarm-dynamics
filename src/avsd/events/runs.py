"""Run periods, pause segments and active time (SPEC 4.2, docs/decisions.md).

Run intervals come from agent actions: `actor_type == "agent"` rows other
than memory snapshots (scaffold writes, which follow their STOP/CONSOLIDATE
anyway; build.py selects the rows). On each Pacific (PT) date these rows are
cut into blocks wherever two consecutive rows are more than G apart; the gaps
between blocks are the pause segments. Every block is one realization for
module A:

- `realization_id`: global index of the block in time order (0, 1, ...).
- `block`: index of the block within its date. The main block is 0: the block
  that overlaps the date's scheduled window (SCHEDULE_WINDOWS) most, or the
  longest block if none overlaps it. Extra blocks (off-schedule sessions such
  as 2026-06-29 04:41 PT) are 1, 2, ... in time order.
- `t_in_day`: seconds since the start of the row's block. A row on a run date
  outside every block belongs to the latest block of that date that started
  at or before it, or to the date's first block if it comes before all of
  them, so `t_in_day` can be negative or exceed the block length; `in_run`
  says whether the row lies inside its block.
- `t_active`: active seconds since the first block, counting only time inside
  blocks. Rows in a pause segment, outside the day's interval or on a date
  without agent activity keep the value at the end of the preceding block.
- `run_day`: dense rank (from 1) of PT dates with at least one block. Dates
  with only human or system rows get null `run_day`, `realization_id` and
  `t_in_day`.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from datetime import date

import polars as pl

# Observed schedule blocks (schema_notes 4.8): first PT date of each regime.
SCHEDULE_REGIMES: tuple[tuple[date, str], ...] = (
    (date(2025, 4, 2), "2h"),
    (date(2025, 7, 18), "3h"),
    (date(2025, 10, 22), "4h"),  # includes the fixed-UTC days 2025-11-03/04
    (date(2026, 6, 8), "8h_event"),
    (date(2026, 6, 15), "4h"),
    (date(2026, 6, 29), "8h"),
)
SCHEDULE_LABELS = ("2h", "3h", "4h", "8h_event", "8h")
# Scheduled run window (PT hours) of each regime; picks the main block of a date.
SCHEDULE_WINDOWS = {"2h": (11, 13), "3h": (10, 13), "4h": (10, 14), "8h_event": (9, 17),
                    "8h": (9, 17)}
VILLAGE_TZ = "America/Los_Angeles"


def schedule_regime(pt_date: pl.Expr) -> pl.Expr:
    """Schedule regime of a PT date; dates between regimes take the earlier one."""
    expr = pl.lit(None, dtype=pl.String)
    for start, label in SCHEDULE_REGIMES:
        expr = pl.when(pt_date >= pl.lit(start)).then(pl.lit(label)).otherwise(expr)
    return expr.cast(pl.Enum(SCHEDULE_LABELS))


def _secs(expr: pl.Expr) -> pl.Expr:
    return expr.dt.total_microseconds() / 1e6


def find_blocks(
    agent_rows: pl.DataFrame, gap_s: float, tz: str = VILLAGE_TZ
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Blocks and pause segments from agent-row timestamps.

    `agent_rows` has `date` (PT date) and `ts_utc`. Returns (blocks, pauses).
    blocks: date, run_day, realization_id, block, is_main, start, end,
    active_seconds, n_agent_rows, n_pauses, pause_seconds, schedule_regime.
    pauses: date, run_day, start, end, seconds, realization_before, realization_after.
    """
    a = (
        agent_rows.select("date", "ts_utc")
        .sort("ts_utc")
        .with_columns(pl.col("ts_utc").shift(1).over("date").alias("prev_ts"))
        .with_columns(_secs(pl.col("ts_utc") - pl.col("prev_ts")).alias("gap"))
        .with_columns((pl.col("gap").is_null() | (pl.col("gap") > gap_s)).alias("new"))
        .with_columns((pl.col("new").cum_sum().over("date") - 1).alias("k_time"))
    )
    blocks = (
        a.group_by("date", "k_time")
        .agg(
            pl.col("ts_utc").min().alias("start"),
            pl.col("ts_utc").max().alias("end"),
            pl.len().alias("n_agent_rows"),
        )
        .with_columns(_secs(pl.col("end") - pl.col("start")).alias("active_seconds"))
        .sort("start")
        .with_columns(
            pl.int_range(pl.len(), dtype=pl.Int32).alias("realization_id"),
            pl.col("date").rank("dense").cast(pl.Int32).alias("run_day"),
        )
    )
    # Main block: most overlap with the scheduled window, then longest, then earliest.
    reg = schedule_regime(pl.col("date")).cast(pl.String)
    w0 = reg.replace_strict({k: v[0] for k, v in SCHEDULE_WINDOWS.items()}, default=None)
    w1 = reg.replace_strict({k: v[1] for k, v in SCHEDULE_WINDOWS.items()}, default=None)
    day0 = pl.col("date").cast(pl.Datetime("us"))
    win_start = (day0 + pl.duration(hours=w0)).dt.replace_time_zone(tz).dt.convert_time_zone("UTC")
    win_end = (day0 + pl.duration(hours=w1)).dt.replace_time_zone(tz).dt.convert_time_zone("UTC")
    overlap = _secs(pl.min_horizontal("end", win_end) - pl.max_horizontal("start", win_start))
    blocks = blocks.with_columns(pl.max_horizontal(overlap, pl.lit(0.0)).alias("_overlap"))
    main_k = (
        blocks.sort("date", "_overlap", "active_seconds", "start",
                    descending=[False, True, True, False])
        .group_by("date", maintain_order=True)
        .first()
        .select("date", pl.col("k_time").alias("main_k"))
    )
    blocks = (
        blocks.join(main_k, on="date")
        .with_columns(
            pl.when(pl.col("k_time") == pl.col("main_k")).then(0)
            .when(pl.col("k_time") < pl.col("main_k")).then(pl.col("k_time") + 1)
            .otherwise(pl.col("k_time"))
            .cast(pl.Int16)
            .alias("block")
        )
        .with_columns((pl.col("block") == 0).alias("is_main"))
    )
    pauses = (
        a.filter(pl.col("gap") > gap_s)
        .select(
            "date",
            pl.col("prev_ts").alias("start"),
            pl.col("ts_utc").alias("end"),
            pl.col("gap").alias("seconds"),
            pl.col("k_time").alias("k_after"),
        )
    )
    rid = blocks.select("date", "k_time", "realization_id", "run_day")
    pauses = (
        pauses.join(rid.rename({"k_time": "k_after", "realization_id": "realization_after"}),
                    on=["date", "k_after"])
        .with_columns((pl.col("realization_after") - 1).alias("realization_before"))
        .select("date", "run_day", "start", "end", "seconds", "realization_before",
                "realization_after")
        .sort("start")
    )
    day_p = pauses.group_by("date").agg(
        pl.len().cast(pl.Int32).alias("n_pauses"), pl.col("seconds").sum().alias("pause_seconds")
    )
    blocks = (
        blocks.join(day_p, on="date", how="left")
        .with_columns(
            pl.col("n_pauses").fill_null(0),
            pl.col("pause_seconds").fill_null(0.0),
            schedule_regime(pl.col("date")).alias("schedule_regime"),
        )
        .select(
            "date", "run_day", "realization_id", "block", "is_main", "start", "end",
            "active_seconds", "n_agent_rows", "n_pauses", "pause_seconds", "schedule_regime",
        )
        .sort("realization_id")
    )
    return blocks, pauses


def total_active_seconds(agent_rows: pl.DataFrame, gap_s: float) -> float:
    """Sum of block lengths for gap threshold `gap_s` (QA of G)."""
    blocks, _ = find_blocks(agent_rows, gap_s)
    return float(blocks["active_seconds"].sum())


def assign_run_columns(rows: pl.LazyFrame, blocks: pl.DataFrame) -> pl.LazyFrame:
    """Add run_day, realization_id, block, in_run, t_in_day and t_active.

    `rows` needs `ts_utc` and `date` (PT date of ts_utc) and must be sorted by
    `ts_utc`. The output keeps the row order of `rows`.
    """
    b = blocks.sort("start").with_columns(
        # Shifted cumulative sum, so that the frozen value after block i
        # (cum_before + active) equals block i+1's start exactly in floating point.
        pl.col("active_seconds").cum_sum().shift(1, fill_value=0.0).alias("cum_before")
    )
    # t_active: latest block that started at or before the row (any date).
    glob = b.select(
        pl.col("start").alias("g_start"), pl.col("end").alias("g_end"),
        "cum_before", pl.col("active_seconds").alias("g_active"),
    ).lazy()
    # Realization: block of the same date, latest started at or before the row,
    # else the first block of the date.
    by_date = b.select(
        "date", pl.col("start").alias("d_start"), pl.col("end").alias("d_end"),
        "run_day", "realization_id", "block",
    ).lazy()
    first = (
        b.sort("start").group_by("date", maintain_order=True).first()
        .select("date", pl.col("start").alias("f_start"), pl.col("end").alias("f_end"),
                pl.col("run_day").alias("f_run_day"),
                pl.col("realization_id").alias("f_rid"), pl.col("block").alias("f_block"))
        .lazy()
    )
    out = (
        rows.join_asof(glob, left_on="ts_utc", right_on="g_start", strategy="backward")
        .join_asof(by_date, left_on="ts_utc", right_on="d_start", by="date",
                   strategy="backward", check_sortedness=False)
        .join(first, on="date", how="left", maintain_order="left")
        .with_columns(
            pl.coalesce("d_start", "f_start").alias("_bs"),
            pl.coalesce("d_end", "f_end").alias("_be"),
        )
        .with_columns(
            pl.coalesce("run_day", "f_run_day").alias("run_day"),
            pl.coalesce("realization_id", "f_rid").alias("realization_id"),
            pl.coalesce("block", "f_block").alias("block"),
            ((pl.col("ts_utc") >= pl.col("_bs")) & (pl.col("ts_utc") <= pl.col("_be")))
            .fill_null(False).alias("in_run"),
            _secs(pl.col("ts_utc") - pl.col("_bs")).alias("t_in_day"),
            pl.when(pl.col("g_start").is_null()).then(0.0)
            .when(pl.col("ts_utc") <= pl.col("g_end"))
            .then(pl.col("cum_before") + _secs(pl.col("ts_utc") - pl.col("g_start")))
            .otherwise(pl.col("cum_before") + pl.col("g_active"))
            .alias("t_active"),
        )
        .drop("g_start", "g_end", "cum_before", "g_active", "d_start", "d_end", "f_start",
              "f_end", "f_run_day", "f_rid", "f_block", "_bs", "_be")
    )
    return out
