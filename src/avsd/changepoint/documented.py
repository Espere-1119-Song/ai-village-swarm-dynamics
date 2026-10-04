"""Documented changes besides the CHANGELOG: village goal transitions and agent goal changes.

Village goals (`village_goals`, 51 contiguous goals) and per-agent goals (`agent_goals`, from
2026-07-06) are documented changes of the agents' environment that the CHANGELOG does not list.
Every goal start becomes an entry on the first run day whose last run block ends at or after it: a
goal set overnight or on a weekend takes effect at the next run, one set during a run on that day.
The first village goal starts with the village (2025-04-02). An agent goal change concerns that
agent's own series and the series of its family and of all agents (`agent_goal_groups`). Agents
that joined after 2026-07-06 received their first goal when they joined.

The entry tables have the columns of `align.map_entries` (entry_id, source, date_start, date_end,
categories, rd_start, rd_end); `date_start` is the run date of the entry.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl

GOAL_SOURCE, AGENT_GOAL_SOURCE = "village_goal", "agent_goal"


def run_day_of(ts_utc: pl.Series, days: pl.DataFrame) -> np.ndarray:
    """First run day whose last block ends at or after each timestamp (-1 after the data)."""
    d = days.sort("run_day")
    ends = d["last_end"].dt.replace_time_zone(None).to_numpy()
    rd = d["run_day"].to_numpy()
    i = np.searchsorted(ends, ts_utc.dt.convert_time_zone("UTC").dt.replace_time_zone(None).to_numpy(),
                        side="left")
    return np.where(i < len(rd), rd[np.minimum(i, len(rd) - 1)], -1)


def _entries(ids: list[str], source: str, rd: np.ndarray, days: pl.DataFrame, label: str,
             extra: dict | None = None) -> pl.DataFrame:
    date_of = dict(days.select("run_day", "date").iter_rows())
    keep = rd > 0
    rd = rd[keep]
    df = pl.DataFrame({
        "entry_id": [i for i, k in zip(ids, keep) if k],
        "source": [source] * len(rd),
        "date_start": [date_of[int(r)] for r in rd],
        "date_end": [date_of[int(r)] for r in rd],
        "categories": [[label]] * len(rd),
        "rd_start": rd.astype(np.int32),
        "rd_end": rd.astype(np.int32),
        **{k: [v for v, kk in zip(vals, keep) if kk] for k, vals in (extra or {}).items()},
    }, schema_overrides={"categories": pl.List(pl.String)})
    return df.sort("rd_start", maintain_order=True)


def _unique_ids(base: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for b in base:
        seen[b] = seen.get(b, 0) + 1
        out.append(b if seen[b] == 1 else f"{b}-{seen[b]}")
    return out


def village_goal_entries(tables: Path, days: pl.DataFrame) -> pl.DataFrame:
    """One entry per village goal start."""
    g = pl.read_parquet(Path(tables) / "village_goals.parquet", columns=["start_time"]).sort("start_time")
    rd = run_day_of(g["start_time"], days)
    date_of = dict(days.select("run_day", "date").iter_rows())
    ids = _unique_ids([f"goal-{date_of.get(int(r), 'after')}" for r in rd])
    return _entries(ids, GOAL_SOURCE, rd, days, "goal transition")


def agent_goal_entries(tables: Path, days: pl.DataFrame, agents: pl.DataFrame) -> pl.DataFrame:
    """One entry per agent goal start, with agent_id and agent name (public)."""
    g = (pl.read_parquet(Path(tables) / "agent_goals.parquet", columns=["agent_id", "start_time"])
         .join(agents.select("agent_id", "name"), on="agent_id", how="left").sort("start_time"))
    rd = run_day_of(g["start_time"], days)
    date_of = dict(days.select("run_day", "date").iter_rows())
    slug = [re.sub(r"[^a-z0-9]+", "-", (n or a).lower()).strip("-")
            for n, a in zip(g["name"].to_list(), g["agent_id"].to_list())]
    ids = _unique_ids([f"agent-goal-{s}-{date_of.get(int(r), 'after')}" for s, r in zip(slug, rd)])
    return _entries(ids, AGENT_GOAL_SOURCE, rd, days, "agent goal change",
                    {"agent_id": g["agent_id"].to_list(), "agent": g["name"].to_list()})


def agent_goal_groups(entries: pl.DataFrame, family_of: dict[str, str]) -> list[set[str]]:
    """Group keys each agent goal change concerns: the agent, its family and all agents."""
    return [{f"agent:{a}", f"family:{family_of.get(a, '')}", "family:All agents"}
            for a in entries["agent_id"].to_list()]
