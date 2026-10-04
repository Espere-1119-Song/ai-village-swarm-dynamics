"""Daily roster (SPEC 4.1 step 6): run day x agent activity and row counts.

One row per run day and agent (the full grid). An agent is `active` on a run
day when it has any `actor_type == "agent"` row that PT date, except rows in
`agents.PRESENCE_EXCLUDE`. Counts are rows by `kind`, so duplicate turns are
counted as turns (`n_turn_dup` gives how many of them mirror a message or
event). `in_window` marks dates between the agent's first and last active day.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import polars as pl

from avsd.events.agents import presence_excluded
from avsd.events.unified import KINDS


def build_roster(unified: pl.LazyFrame, blocks: pl.DataFrame, agents: pl.DataFrame) -> pl.DataFrame:
    """roster_daily: date, run_day, agent_id, active, in_window, n_rows, n_<kind>, n_turn_dup."""
    days = blocks.group_by("date").agg(pl.col("run_day").first()).sort("date")
    rows = (
        unified.filter((pl.col("actor_type") == "agent") & pl.col("run_day").is_not_null())
        .select("actor_id", "kind", "dup_of_uid", "ts_utc",
                pl.col("ts_pt").dt.date().alias("date"))
        .filter(~presence_excluded(pl.col("actor_id"), pl.col("date"), agents))
        .group_by("date", pl.col("actor_id").alias("agent_id"))
        .agg(
            pl.len().alias("n_rows"),
            *[(pl.col("kind") == k).sum().alias(f"n_{k}") for k in KINDS],
            ((pl.col("kind") == "turn") & pl.col("dup_of_uid").is_not_null()).sum()
            .alias("n_turn_dup"),
            pl.col("ts_utc").min().alias("first_ts"),
            pl.col("ts_utc").max().alias("last_ts"),
        )
        .collect()
    )
    window = agents.select(
        "agent_id",
        pl.col("first_active_ts").dt.convert_time_zone("America/Los_Angeles").dt.date()
        .alias("_first"),
        pl.col("last_active_ts").dt.convert_time_zone("America/Los_Angeles").dt.date()
        .alias("_last"),
    )
    count_cols = ["n_rows", *[f"n_{k}" for k in KINDS], "n_turn_dup"]
    grid = (
        days.join(agents.select("agent_id"), how="cross")
        .join(rows, on=["date", "agent_id"], how="left")
        .join(window, on="agent_id", how="left")
        .with_columns(
            *[pl.col(c).fill_null(0).cast(pl.Int32) for c in count_cols],
            (pl.col("date") >= pl.col("_first")).fill_null(False)
            .and_(pl.col("date") <= pl.col("_last")).fill_null(False).alias("in_window"),
        )
        .with_columns((pl.col("n_rows") > 0).alias("active"))
        .drop("_first", "_last")
    )
    return grid.select("date", "run_day", "agent_id", "active", "in_window", *count_cols,
                       "first_ts", "last_ts").sort("run_day", "agent_id")
