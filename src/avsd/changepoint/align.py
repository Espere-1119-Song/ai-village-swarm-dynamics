"""Alignment of change points with CHANGELOG entries (SPEC 7.3).

Entries (`changelog.parquet`, scaffolding bullets and roster joins and leaves) map to run days: the
start is the first run day on or after `date_start` (a change made on a weekend takes effect at the
next run), the end the last run day on or before `date_end`, and never before the start. A change
point at run day p covers [p - h, p + h], with h = (resolution - 1) // 2, so the position of a
change found in 5-run-day bins (the bin start) gets the half-width of a bin. A change point is
aligned with an entry when the run-day gap between the two intervals is at most w.

The statistic S is the number of change points aligned with at least one entry of the set. Both
nulls keep the change points fixed and move the entries within a domain of run days (every run day
for the CHANGELOG and the goal transitions; the run days with monitor data for monitor findings):

- null 1, circular shift: every entry moves by the same offset k on the circle of domain days,
  keeping their spacing and durations. k is drawn uniformly (`null_reps` draws) from the offsets
  more than 2w steps from 0 both ways round the circle, since a smaller shift leaves the windows
  of the shifted entries overlapping their observed windows (the p-value could then never fall
  below about (4w + 1) / N). The exact p-value over all those offsets is reported too;
- null 2, uniform placement: every distinct entry interval starts at its own uniformly drawn
  domain day (distinct starts), keeping its duration. Entries with the same run-day interval (for
  example several roster joins on one day) move together, so that the null does not spread one
  dated event over several places.

Two week-preserving nulls keep the weekday of every entry: null 1w shifts all entries together by
whole calendar weeks (dates on a circle of whole weeks, mapped back with the next-run-day rule;
shifts within 2w run days of zero, about 5 run days per week, are left out), and null 2w places
each distinct entry interval at a distinct uniform start among the domain days of its weekday.

An entry set can be specific to groups of change points: an agent's goal changes concern only that
agent's series and the series of its family and of all agents. A change point then counts as
aligned only with the entries of its group, while the entries still move together.

p = (1 + #{S* >= S}) / (1 + reps), one-sided. Entry sets: all entries, scaffolding bullets only,
roster joins and leaves only, and each category. Every goal entry also carries `prompt` (owner
decision of 2026-09-30), so "prompt" pools goal entries with prompt entries, and "prompt without
goal" plus "goal" keep them apart.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import polars as pl

from avsd.events.changelog import CATEGORIES


def _has(cat: str) -> pl.Expr:
    return pl.col("categories").list.contains(cat)


ENTRY_SETS: dict[str, Callable[[], pl.Expr]] = {
    "all": lambda: pl.lit(True),
    "scaffolding": lambda: pl.col("source") == "changelog",
    "roster only": lambda: pl.col("source") == "roster",
    "prompt (goal pooled)": lambda: _has("prompt") | _has("goal"),
    "prompt without goal": lambda: _has("prompt") & ~_has("goal"),
    **{c: (lambda c=c: _has(c)) for c in CATEGORIES if c not in ("prompt", "roster")},
}


def map_entries(changelog: pl.DataFrame, days: pl.DataFrame) -> pl.DataFrame:
    """CHANGELOG rows with run-day intervals `rd_start`, `rd_end` (entries after the data dropped)."""
    d = days.sort("run_day")
    dates = d["date"].to_numpy()
    rds = d["run_day"].to_numpy()
    start = np.searchsorted(dates, changelog["date_start"].to_numpy(), side="left")
    end = np.searchsorted(dates, changelog["date_end"].to_numpy(), side="right") - 1
    keep = start < len(dates)
    start_rd = np.where(keep, rds[np.minimum(start, len(rds) - 1)], -1)
    end_rd = np.maximum(np.where(end >= 0, rds[np.maximum(end, 0)], -1), start_rd)
    return changelog.with_columns(
        pl.Series("rd_start", start_rd, dtype=pl.Int32), pl.Series("rd_end", end_rd, dtype=pl.Int32)
    ).filter(pl.Series(keep))


def cp_interval(run_day: np.ndarray, resolution: np.ndarray, n_days: int) -> tuple[np.ndarray, np.ndarray]:
    """[lo, hi] run days covered by change points at `run_day` found at `resolution`."""
    h = (np.asarray(resolution) - 1) // 2
    p = np.asarray(run_day)
    return np.clip(p - h, 1, n_days), np.clip(p + h, 1, n_days)


def gaps(cp_lo: np.ndarray, cp_hi: np.ndarray, e_lo: np.ndarray, e_hi: np.ndarray) -> np.ndarray:
    """Run-day gap between every change point and every entry interval (0 when they overlap)."""
    a = e_lo[None, :] - cp_hi[:, None]
    b = cp_lo[:, None] - e_hi[None, :]
    return np.maximum(0, np.maximum(a, b))


def match_entries(
    cp_run_day: np.ndarray, cp_lo: np.ndarray, cp_hi: np.ndarray, entries: pl.DataFrame, w: int
) -> pl.DataFrame:
    """Per change point: the nearest entry (gap, then distance to its start) and all entries within w."""
    e_lo, e_hi = entries["rd_start"].to_numpy(), entries["rd_end"].to_numpy()
    ids = entries["entry_id"].to_list()
    cats = entries["categories"].to_list()
    src = entries["source"].to_list()
    dstart = entries["date_start"].to_list()
    g = gaps(cp_lo, cp_hi, e_lo, e_hi)
    off = e_lo[None, :] - np.asarray(cp_run_day)[:, None]
    order = np.lexsort((np.abs(off), g), axis=1) if g.size else np.zeros_like(g)
    rows = []
    for i in range(len(cp_run_day)):
        j = int(order[i, 0])
        within = np.flatnonzero(g[i] <= w)
        wc = sorted({c for k in within for c in cats[k]}, key=CATEGORIES.index)
        rows.append({
            "nearest_entry_id": ids[j],
            "nearest_entry_date": dstart[j],
            "nearest_entry_source": src[j],
            "nearest_entry_categories": ";".join(cats[j]),
            "nearest_entry_gap_run_days": int(g[i, j]),
            "nearest_entry_offset_run_days": int(off[i, j]),
            "n_entries_within_w": int(within.size),
            "entries_within_w": ";".join(ids[k] for k in within),
            "categories_within_w": ";".join(wc),
            "aligned": bool(within.size),
        })
    return pl.DataFrame(rows)


def _intervals_to_unique(cp_lo: np.ndarray, cp_hi: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unique (lo, hi) pairs, 0-indexed, with their multiplicities."""
    pairs, counts = np.unique(np.stack([cp_lo - 1, cp_hi - 1], axis=1), axis=0, return_counts=True)
    return pairs[:, 0], pairs[:, 1], counts.astype(np.int64)


def _aligned_counts(cov: np.ndarray, lo: np.ndarray, hi: np.ndarray, wts: np.ndarray) -> np.ndarray:
    """Weighted number of change-point intervals touching a covered day, per row of `cov`."""
    cc = np.zeros((cov.shape[0], cov.shape[1] + 1), dtype=np.int32)
    np.cumsum(cov, axis=1, out=cc[:, 1:])
    return ((cc[:, hi + 1] - cc[:, lo]) > 0).astype(np.int64) @ wts


def _dilate(ind: np.ndarray, w: int) -> np.ndarray:
    """covered[r, d] = any ind[r, d-w..d+w] (no wrap)."""
    n = ind.shape[1]
    c = np.zeros((ind.shape[0], n + 1), dtype=np.int32)
    np.cumsum(ind, axis=1, out=c[:, 1:])
    d = np.arange(n)
    return (c[:, np.minimum(d + w + 1, n)] - c[:, np.maximum(d - w, 0)]) > 0


def entry_indicator(e_lo: np.ndarray, e_hi: np.ndarray, n_days: int) -> np.ndarray:
    """1 on run days (0-indexed) inside any entry interval."""
    diff = np.zeros(n_days + 1, dtype=np.int32)
    np.add.at(diff, e_lo - 1, 1)
    np.add.at(diff, e_hi, -1)
    return (np.cumsum(diff[:n_days]) > 0).astype(np.int8)


@dataclass
class EntryLayout:
    """Entries on a domain of run days, one row per distinct interval, with the groups it concerns."""

    dom: np.ndarray                 # sorted run days the entries may occupy
    i_lo: np.ndarray                # domain-index range of each distinct interval
    i_hi: np.ndarray
    masks: dict[int, np.ndarray]    # group -> distinct intervals that concern it
    n_entries: int                  # entries inside the domain, before deduplication

    @property
    def length(self) -> np.ndarray:
        return self.i_hi - self.i_lo + 1

    def indicator(self, g: int) -> np.ndarray | None:
        """Domain-index indicator of the observed entries of group g."""
        m = self.masks.get(g)
        if m is None or not m.any():
            return None
        diff = np.zeros(len(self.dom) + 1, dtype=np.int32)
        np.add.at(diff, self.i_lo[m], 1)
        np.add.at(diff, self.i_hi[m] + 1, -1)
        return (np.cumsum(diff[:-1]) > 0).astype(np.int8)


def layout_entries(e_lo: np.ndarray, e_hi: np.ndarray, domain: np.ndarray,
                   entry_groups: list[frozenset[int]] | None = None) -> EntryLayout:
    """Map entry intervals (run days) onto domain indices; identical intervals merge (union of groups)."""
    dom = np.asarray(domain, dtype=np.int64)
    i_lo = np.searchsorted(dom, e_lo, side="left")
    i_hi = np.searchsorted(dom, e_hi, side="right") - 1
    groups = entry_groups if entry_groups is not None else [frozenset({0})] * len(i_lo)
    merged: dict[tuple[int, int], set[int]] = {}
    for a, b, g in zip(i_lo, i_hi, groups):
        if a <= b:
            merged.setdefault((int(a), int(b)), set()).update(g)
    keys = sorted(merged)
    lo = np.array([k[0] for k in keys], dtype=np.int64)
    hi = np.array([k[1] for k in keys], dtype=np.int64)
    all_groups = sorted({g for v in merged.values() for g in v})
    masks = {g: np.array([g in merged[k] for k in keys], dtype=bool) for g in all_groups}
    return EntryLayout(dom, lo, hi, masks, int(np.sum(i_lo <= i_hi)))


def cp_groups(cp_lo: np.ndarray, cp_hi: np.ndarray, cp_group: np.ndarray | None = None
              ) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Unique change-point intervals with weights, per group (group 0 when ungrouped)."""
    cp_lo, cp_hi = np.asarray(cp_lo, dtype=np.int64), np.asarray(cp_hi, dtype=np.int64)
    grp = np.zeros(len(cp_lo), dtype=np.int64) if cp_group is None else np.asarray(cp_group)
    return {int(g): _intervals_to_unique(cp_lo[grp == g], cp_hi[grp == g]) for g in np.unique(grp)}


def _run_cover(ind_dom: np.ndarray, dom: np.ndarray, n_days: int, w: int) -> np.ndarray:
    """Domain-index indicators (R, D) to covered run days (R, n_days)."""
    run = np.zeros((ind_dom.shape[0], n_days), dtype=np.int8)
    run[:, dom - 1] = ind_dom
    return _dilate(run, w)


def shift_null(cps: dict, lay: EntryLayout, n_days: int, w: int, shifts: np.ndarray,
               chunk: int = 2000) -> np.ndarray:
    """S for every circular shift of all entries together, in domain-index units (0 = observed)."""
    nd = len(lay.dom)
    idx = np.arange(nd)
    base = {g: ind for g in cps if (ind := lay.indicator(g)) is not None}
    shifts = np.asarray(shifts)
    out = []
    for k in np.array_split(shifts, max(1, len(shifts) // chunk)):
        tot = np.zeros(len(k), dtype=np.int64)
        for g, ind in base.items():
            cov = _run_cover(ind[(idx[None, :] - k[:, None]) % nd], lay.dom, n_days, w)
            tot += _aligned_counts(cov, *cps[g])
        out.append(tot)
    return np.concatenate(out)


def distinct_starts(rng: np.random.Generator, m: int, nd: int, k: int) -> np.ndarray:
    """(m, k) start indices in 0..nd-1, distinct within a row, in random order."""
    if k > nd:
        return rng.integers(0, nd, size=(m, k))
    keys = rng.random((m, nd))
    sel = np.argpartition(keys, k - 1, axis=1)[:, :k]
    return np.take_along_axis(sel, np.argsort(np.take_along_axis(keys, sel, axis=1), axis=1), axis=1)


def _stats_from_starts(cps: dict, lay: EntryLayout, n_days: int, w: int, starts: np.ndarray) -> np.ndarray:
    """S for each row of `starts` (m, k): entry j occupies domain indices starts[:, j] onward."""
    nd = len(lay.dom)
    m = starts.shape[0]
    ends = np.minimum(starts + lay.length - 1, nd - 1)
    tot = np.zeros(m, dtype=np.int64)
    for g in cps:
        mk = lay.masks.get(g)
        if mk is None or not mk.any():
            continue
        diff = np.zeros((m, nd + 1), dtype=np.int32)
        rows = np.repeat(np.arange(m), int(mk.sum()))
        np.add.at(diff, (rows, starts[:, mk].ravel()), 1)
        np.add.at(diff, (rows, ends[:, mk].ravel() + 1), -1)
        ind = (np.cumsum(diff[:, :nd], axis=1) > 0).astype(np.int8)
        tot += _aligned_counts(_run_cover(ind, lay.dom, n_days, w), *cps[g])
    return tot


def uniform_null(cps: dict, lay: EntryLayout, n_days: int, w: int, reps: int,
                 rng: np.random.Generator, chunk: int = 2000) -> np.ndarray:
    """S with each distinct entry interval placed at a distinct uniform start in the domain."""
    nd, k = len(lay.dom), len(lay.i_lo)
    return np.concatenate([
        _stats_from_starts(cps, lay, n_days, w, distinct_starts(rng, len(r), nd, k))
        for r in np.array_split(np.arange(reps), max(1, reps // chunk))])


def weekdays(dates: np.ndarray) -> np.ndarray:
    """Weekday of each date, Monday = 0."""
    return (np.asarray(dates).astype("datetime64[D]").astype(np.int64) + 3) % 7


def week_shift_ks(dom_dates: np.ndarray, w: int) -> tuple[np.ndarray, int]:
    """Allowed shifts in whole weeks and the circle length in days (whole weeks covering the domain).

    A week moves an entry by about 5 run days, so shifts with 5 * min(k, W - k) <= 2w are left out.
    """
    d = np.asarray(dom_dates).astype("datetime64[D]").astype(np.int64)
    period = 7 * int(np.ceil((d[-1] - d[0] + 1) / 7))
    n_weeks = period // 7
    k = np.arange(1, n_weeks)
    keep = 5 * np.minimum(k, n_weeks - k) > 2 * w
    return (k[keep] if keep.any() else k), period


def week_shift_maps(dom_dates: np.ndarray, ks: np.ndarray, period: int) -> np.ndarray:
    """(K, D): domain index that each domain day moves to when its date shifts by 7k days.

    Dates move on a circle of `period` days (whole weeks, so weekdays are kept) and land on the
    first domain day on or after the shifted date (the next-run-day rule), wrapping to the first.
    """
    d = np.asarray(dom_dates).astype("datetime64[D]").astype(np.int64)
    out = np.empty((len(ks), len(d)), dtype=np.int64)
    for r, k in enumerate(ks):
        idx = np.searchsorted(d, d[0] + (d - d[0] + 7 * int(k)) % period, side="left")
        idx[idx >= len(d)] = 0
        out[r] = idx
    return out


def week_shift_null(cps: dict, lay: EntryLayout, n_days: int, w: int, maps: np.ndarray) -> np.ndarray:
    """S for every whole-week shift of all entries together (rows of `maps`)."""
    return _stats_from_starts(cps, lay, n_days, w, maps[:, lay.i_lo])


def weekday_null(cps: dict, lay: EntryLayout, n_days: int, w: int, reps: int, rng: np.random.Generator,
                 dom_weekday: np.ndarray, chunk: int = 2000) -> np.ndarray:
    """S with each distinct entry interval placed at a distinct uniform start among domain days of
    the weekday it starts on."""
    cls = dom_weekday[lay.i_lo]
    pools = {int(c): np.flatnonzero(dom_weekday == c) for c in np.unique(cls)}
    members = {c: np.flatnonzero(cls == c) for c in pools}
    out = []
    for r in np.array_split(np.arange(reps), max(1, reps // chunk)):
        starts = np.empty((len(r), len(cls)), dtype=np.int64)
        for c, pool in pools.items():
            starts[:, members[c]] = pool[distinct_starts(rng, len(r), len(pool), len(members[c]))]
        out.append(_stats_from_starts(cps, lay, n_days, w, starts))
    return np.concatenate(out)


def shift_offsets(n_days: int, w: int) -> np.ndarray:
    """Circular offsets more than 2w steps from 0 in both directions (all if too few days)."""
    k = np.arange(2 * w + 1, n_days - 2 * w)
    return k if k.size else np.arange(n_days)


def holm(p: np.ndarray) -> np.ndarray:
    """Holm-adjusted p-values."""
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * p[i])
        adj[i] = min(1.0, run)
    return adj


def _summary(prefix: str, null: np.ndarray, s_obs: int) -> dict[str, float]:
    return {
        f"{prefix}_mean": float(null.mean()),
        f"{prefix}_sd": float(null.std(ddof=1)) if null.size > 1 else 0.0,
        f"{prefix}_q025": float(np.quantile(null, 0.025)),
        f"{prefix}_q975": float(np.quantile(null, 0.975)),
        f"{prefix}_p": float((1 + np.sum(null >= s_obs)) / (1 + null.size)),
    }


def alignment_test(
    cp_lo: np.ndarray, cp_hi: np.ndarray, entries: pl.DataFrame, n_days: int, w: int, reps: int,
    rng: np.random.Generator, domain: np.ndarray | None = None, cp_group: np.ndarray | None = None,
    entry_groups: list[frozenset[int]] | None = None, dom_dates: np.ndarray | None = None,
) -> dict[str, float]:
    """S, both nulls and the coverage of one change-point set against one entry set.

    `entries` has rd_start and rd_end. `domain` (default: every run day) holds the run days that
    entries may occupy under the nulls; entries outside it are dropped, and shifts run on the circle
    of domain days. With `cp_group` and `entry_groups`, a change point counts as aligned only with
    the entries that concern its group (for example an agent's own goal changes). All entries
    still move together under null 1, and each distinct interval is placed once under null 2.
    Coverage is the share of domain days within w of an entry, averaged over the change points'
    groups. With `dom_dates` (the dates of the domain days) two week-preserving nulls are added:
    null 1w shifts all entries together by whole calendar weeks (exact over the allowed shifts,
    p = (1 + #{S* >= S}) / (1 + K)), and null 2w places each distinct interval at a distinct
    uniform start among domain days of its own weekday.
    """
    e_lo = entries["rd_start"].to_numpy().astype(np.int64)
    e_hi = entries["rd_end"].to_numpy().astype(np.int64)
    dom = np.arange(1, n_days + 1) if domain is None else np.asarray(domain, dtype=np.int64)
    lay = layout_entries(e_lo, e_hi, dom, entry_groups)
    m = len(cp_lo)
    cps = cp_groups(cp_lo, cp_hi, cp_group) if m else {}
    weights = {g: int(v[2].sum()) for g, v in cps.items()} if m else {0: 1}
    cover = {}
    for g in weights:
        ind = lay.indicator(g)
        cover[g] = 0.0 if ind is None else float(_run_cover(ind[None, :], dom, n_days, w)[0][dom - 1].mean())
    row: dict[str, float] = {
        "n_entries": lay.n_entries, "n_entry_intervals": len(lay.i_lo), "n_domain_days": len(dom),
        "n_changepoints": m,
        "coverage_frac": sum(cover[g] * weights[g] for g in weights) / max(1, sum(weights.values())),
    }
    if m == 0 or len(lay.i_lo) == 0:
        return row
    s_obs = int(shift_null(cps, lay, n_days, w, np.array([0]))[0])
    offsets = shift_offsets(len(dom), w)
    exact = shift_null(cps, lay, n_days, w, offsets)
    shift = shift_null(cps, lay, n_days, w, rng.choice(offsets, size=reps))
    unif = uniform_null(cps, lay, n_days, w, reps, rng)
    row.update({"aligned": s_obs, "aligned_frac": s_obs / m})
    row.update(_summary("null1", shift, s_obs))
    row["null1_p_exact"] = float(np.mean(exact >= s_obs))
    row.update(_summary("null2", unif, s_obs))
    if dom_dates is not None:
        ks, period = week_shift_ks(dom_dates, w)
        wk = week_shift_null(cps, lay, n_days, w, week_shift_maps(dom_dates, ks, period))
        summ = _summary("null1w", wk, s_obs)
        summ["null1w_p"] = float((1 + np.sum(wk >= s_obs)) / (1 + wk.size))
        row.update(summ)
        row["n_week_shifts"] = int(wk.size)
        row.update(_summary("null2w", weekday_null(cps, lay, n_days, w, reps, rng, weekdays(dom_dates)), s_obs))
    return row
