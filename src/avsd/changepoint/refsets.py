"""Reference event sets for the alignment test, the window sweep, and per change point flags.

Every set is tested with the two nulls of align.py at each w in W_SWEEP:

- the CHANGELOG sets of `align.ENTRY_SETS` (the SPEC primary result is w = config w);
- village goal transitions, and CHANGELOG scaffolding bullets plus goal transitions;
- agent goal changes (documented.py), specific to groups of change points (an agent's own series,
  and the family and all-agent series that include it), over the agent-goal era: the run days
  from the first agent goal on;
- monitor dates with medium or high severity likely-scaffolding-issue or emotional-or-erratic
  findings (monitor.py), over the monitor coverage window, placed only on covered run days; such
  findings occur on most covered days, so the dates with a high severity finding are tested too.

Every set except the monitor sets also gets the week-preserving nulls 1w and 2w (align.py), which
keep the weekday of each entry. Change points enter a test when they lie in the set's window. The
series set "all" is the
module's own series (family, agent, lexical); external series (monitor counts, modules A and B1)
are tested as their own series set. Holm adjusts p-values within one method, change-point set,
series set and w (each null on its own), separately for the CHANGELOG category rows and for the
goal and monitor rows.
The rows "all" and "scaffolding" are summaries and are not adjusted.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context

import numpy as np
import polars as pl

from avsd.changepoint import align as A
from avsd.changepoint.monitor import TEST_CATEGORIES, Monitor, monitor_entries
from avsd.changepoint.series import SeriesSpec

W_SWEEP = (0, 1, 2, 3)
ENTRY_COLS = ["entry_id", "source", "date_start", "date_end", "categories", "rd_start", "rd_end"]
SUMMARY, CATEGORY, DOCUMENTED = "summary", "changelog categories", "goals and monitor"
OWN_LEVELS = ("family", "agent", "lexical")
_FAR = 10 ** 6


@dataclass
class RefSet:
    name: str
    family: str                              # Holm family: SUMMARY, CATEGORY or DOCUMENTED
    entries: pl.DataFrame                    # ENTRY_COLS
    domain: np.ndarray | None = None         # run days entries may occupy (None: all)
    window: tuple[int, int] | None = None    # run days of the change points that enter the test
    groups: list[set[str]] | None = None     # per entry, the change-point groups it concerns
    week_nulls: bool = True                  # also run the week-preserving nulls 1w and 2w


def series_group(spec: SeriesSpec) -> str | None:
    """Group key of a series for group-specific entries (agent goal changes)."""
    if spec.level == "agent":
        return f"agent:{spec.agent_ids[0]}"
    if spec.level in ("family", "lexical"):
        return f"family:{spec.entity}"
    return None


def reference_sets(changelog: pl.DataFrame, goals: pl.DataFrame, agoals: pl.DataFrame,
                   agoal_groups: list[set[str]], mon: Monitor | None, days: pl.DataFrame) -> list[RefSet]:
    """All entry sets of the alignment test, CHANGELOG sets first."""
    sets = [RefSet(name, SUMMARY if name in ("all", "scaffolding") else CATEGORY,
                   changelog.filter(expr()).select(ENTRY_COLS))
            for name, expr in A.ENTRY_SETS.items()]
    g = goals.select(ENTRY_COLS)
    sets.append(RefSet("village goal transitions", DOCUMENTED, g))
    scaffolding = changelog.filter(pl.col("source") == "changelog").select(ENTRY_COLS)
    sets.append(RefSet("scaffolding + goal transitions", DOCUMENTED, pl.concat([scaffolding, g])))
    if agoals.height:
        lo, n = int(agoals["rd_start"].min()), int(days["run_day"].max())
        sets.append(RefSet("agent goal changes", DOCUMENTED, agoals.select(ENTRY_COLS),
                           np.arange(lo, n + 1), (lo, n), agoal_groups))
    if mon is not None:
        for sev, label in ((("medium", "high"), "medium/high"), (("high",), "high")):
            for c in TEST_CATEGORIES:
                sets.append(RefSet(f"monitor {c} ({label})", DOCUMENTED,
                                   monitor_entries(mon, c, days, sev), mon.domain, mon.window,
                                   week_nulls=False))
    return sets


def _nearest(g: np.ndarray, off: np.ndarray) -> np.ndarray:
    """Index of the nearest entry per row: smallest gap, then smallest |offset|."""
    return np.lexsort((np.abs(off), g), axis=1)[:, 0]


def documented_columns(cps: pl.DataFrame, goals: pl.DataFrame, agoals: pl.DataFrame,
                       agoal_groups: list[set[str]], w: int, n_days: int) -> pl.DataFrame:
    """Per change point: nearest village goal transition and relevant agent goal change, aligned at w.

    `cps` has run_day, resolution_run_days and group_key.
    """
    p = cps["run_day"].to_numpy()
    lo, hi = A.cp_interval(p, cps["resolution_run_days"].to_numpy(), n_days)
    out: dict[str, list] = {}
    g = A.gaps(lo, hi, goals["rd_start"].to_numpy(), goals["rd_end"].to_numpy())
    off = goals["rd_start"].to_numpy()[None, :] - p[:, None]
    j = _nearest(g, off)
    rows = np.arange(len(p))
    dates = goals["date_start"].to_list()
    out["goal_transition_gap_run_days"] = g[rows, j].tolist()
    out["goal_transition_offset_run_days"] = off[rows, j].tolist()
    out["nearest_goal_transition_date"] = [dates[k] for k in j]
    out["aligned_goal_transition"] = (g[rows, j] <= w).tolist()
    if agoals.height:
        keys = cps["group_key"].to_list()
        rel = np.array([[k is not None and k in gs for gs in agoal_groups] for k in keys], dtype=bool)
        ga = np.where(rel, A.gaps(lo, hi, agoals["rd_start"].to_numpy(), agoals["rd_end"].to_numpy()), _FAR)
        best = ga.min(axis=1)
        out["agent_goal_gap_run_days"] = [int(b) if b < _FAR else None for b in best]
        out["aligned_agent_goal"] = (best <= w).tolist()
    else:
        out["agent_goal_gap_run_days"] = [None] * len(p)
        out["aligned_agent_goal"] = [False] * len(p)
    return pl.DataFrame(out, schema_overrides={"agent_goal_gap_run_days": pl.Int64})


def _task(args: tuple) -> tuple[tuple, dict]:
    key, lo, hi, grp, e_lo, e_hi, e_groups, domain, dom_dates, n_days, w, reps, seed = args
    entries = pl.DataFrame({"rd_start": e_lo, "rd_end": e_hi})
    return key, A.alignment_test(lo, hi, entries, n_days, w, reps, np.random.default_rng(seed),
                                 domain, grp, e_groups, dom_dates)


P_COLS = ("null1_p", "null2_p", "null1w_p", "null2w_p")


def alignment_table(
    cps: pl.DataFrame, sets: list[RefSet], days: pl.DataFrame, reps: int, seed: int, n_workers: int,
    combos: list[tuple[str, str, Callable[[], pl.Expr]]], series_sets: tuple[str, ...],
    ws: tuple[int, ...] = W_SWEEP,
) -> pl.DataFrame:
    """One row per (method, change-point set), series set, entry set and w (module docstring).

    `combos` lists (method, change-point set name, filter on the change-point rows).
    """
    d = days.sort("run_day")
    n_days = int(d["run_day"].max())
    dates = d["date"].to_numpy()
    tasks = []
    for ci, (method, cp_set, keep) in enumerate(combos):
        mc = cps.filter((pl.col("method") == method) & keep())
        for si, sset in enumerate(series_sets):
            sub = (mc.filter(pl.col("level").is_in(OWN_LEVELS)) if sset == "all"
                   else mc.filter(pl.col("level") == sset))
            for ei, rs in enumerate(sets):
                s2 = sub if rs.window is None else sub.filter(pl.col("run_day").is_between(*rs.window))
                grp = e_groups = None
                if rs.groups is not None:
                    keys = sorted(set().union(*rs.groups))
                    s2 = s2.filter(pl.col("group_key").is_in(keys))
                    kid = {k: i for i, k in enumerate(keys)}
                    grp = np.array([kid[k] for k in s2["group_key"].to_list()], dtype=np.int64)
                    e_groups = [frozenset(kid[k] for k in gs) for gs in rs.groups]
                if s2.is_empty():
                    continue
                lo, hi = A.cp_interval(s2["run_day"].to_numpy(), s2["resolution_run_days"].to_numpy(), n_days)
                e_lo, e_hi = rs.entries["rd_start"].to_numpy(), rs.entries["rd_end"].to_numpy()
                dom = np.arange(1, n_days + 1) if rs.domain is None else rs.domain
                dom_dates = dates[dom - 1] if rs.week_nulls else None
                for wi, w in enumerate(ws):
                    tasks.append(((method, cp_set, sset, rs.name, rs.family, w), lo, hi, grp, e_lo, e_hi,
                                  e_groups, rs.domain, dom_dates, n_days, w, reps, (seed, ci, si, ei, wi)))
    if n_workers > 1:
        with ProcessPoolExecutor(n_workers, mp_context=get_context("fork")) as ex:
            res = list(ex.map(_task, tasks, chunksize=4))
    else:
        res = [_task(t) for t in tasks]
    names = ("method", "cp_set", "series_set", "entry_set", "holm_family", "w")
    df = pl.DataFrame([{**dict(zip(names, k)), **row} for k, row in res], infer_schema_length=None)
    for c in P_COLS:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, pl.Float64).alias(c))
    parts = []
    for (fam,), g in df.group_by(["holm_family"], maintain_order=True):
        if fam == SUMMARY:
            parts.append(g.with_columns(*[pl.lit(None, pl.Float64).alias(f"{c}_holm") for c in P_COLS]))
            continue
        for _, gg in g.group_by(["method", "cp_set", "series_set", "w"], maintain_order=True):
            adj = []
            for c in P_COLS:
                a = np.full(gg.height, np.nan)
                ok = gg[c].is_not_null().to_numpy()
                if ok.any():
                    a[ok] = A.holm(gg[c].to_numpy()[ok])
                adj.append(pl.Series(f"{c}_holm", a).fill_nan(None))
            parts.append(gg.with_columns(*adj))
    order = {s.name: i for i, s in enumerate(sets)}
    return (pl.concat(parts, how="diagonal_relaxed")
            .with_columns(pl.col("entry_set").replace_strict(order, default=99).alias("_o"))
            .sort("method", "cp_set", "series_set", "w", "_o").drop("_o"))
