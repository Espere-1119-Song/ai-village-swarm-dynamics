"""`avsd changepoint` (SPEC 7): series, detection, CHANGELOG alignment, outputs and QA report.

`run_changepoint(cfg)` builds the series (series.py, plus the monitor counts of monitor.py as
external series), runs PELT, the penalty sweep, the l2 block bootstrap and BOCPD on every series in
parallel (detect.py), checks family-level change points for composition effects, flags each change
point against the CHANGELOG, the village goal transitions and the agent goal changes (refsets.py),
annotates it with nearby monitor findings, runs the alignment tests for every entry set and window
w in the sweep (refsets.py, align.py), and writes

- outputs/tables/changepoints.csv: one row per change point and method (pelt_l2, pelt_rbf);
- outputs/tables/changepoint_alignment.csv: S and both nulls per method, change-point set (all, or
  persistent at 4x the penalty), series set and entry set;
- outputs/tables/changepoint_series.csv: one row per candidate series (resolution, points, counts);
- outputs/tables/lexical_words.csv: the family-characteristic words (words and rates only);
- outputs/tables/changepoints_weekday_adjusted.csv: PELT l2 change points of the daily series after
  removing weekday effects (weekday.py), with the nearest original change point;
- outputs/tables/monday_ratio.csv: Monday / Tuesday-Friday ratios of the family-level daily series;
- outputs/tables/changepoint_monitor_findings.parquet: change point and monitor finding pairs
  (ids, categories, severities, run-day offsets) for findings that involve the series' agents;
- data/processed/changepoint_series.parquet: the points of every analysed series;
- outputs/figures/F5_changepoint_timeline.pdf and .png;
- outputs/qa/changepoint.md.

Composition check (SPEC 7.2), for change points of family-level and lexical series: with the change
point at run day tau, the before window runs from max(previous change point, tau - H) to tau - 1 and
the after window from tau to min(next change point - 1, tau + H - 1), H = max(COMP_WINDOW_RUN_DAYS,
4 x resolution). Stayers are the group's agents active on at least half (and at least 2) of the run
days on which the group is active in each window. The series is recomputed for the stayers alone.
We report their shift (after minus before, original units), the ratio of their shift to the full
population's on the detection scale over the same windows, and a Welch t-test of their points
before against after. Verdicts: "shift among stayers" (p < 0.05, the same sign, ratio at least
0.5), "partial shift among stayers" (p < 0.05, the same sign, ratio below 0.5), "no shift among
stayers" (otherwise), "no stayers" and "too few points".

A change point with no CHANGELOG entry within w run days is "cause unidentified" (`cause`, the SPEC
label) and carries four live UI links, at the midpoint of the main run block on run days p - 2 and
p - 1 (before) and p and p + 1 (after). `cause_documented` repeats the label with village goal
transitions and the series' own agent goal changes counted as documented events too.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import os
import time
import warnings
import zlib
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from avsd.changepoint import align as A
from avsd.changepoint import refsets as R
from avsd.changepoint.detect import (
    BETA, BETAS, BOCPD_RUN_DAYS, MIN_SEGMENT_RUN_DAYS, N_BOOT, SeriesDetection, detect_series,
    segment_means,
)
from avsd.changepoint.documented import agent_goal_entries, agent_goal_groups, village_goal_entries
from avsd.changepoint.figure import plot_timeline
from avsd.changepoint.lexical import FOCUS_WORD, MIN_AGENTS, MIN_COUNT, MIN_DAYS, PRIOR_SIZE, TOP_K
from avsd.changepoint.monitor import SEVERE, TEST_CATEGORIES, annotate, load_monitor, monitor_series
from avsd.changepoint.weekday import (
    WEEKDAY_NAMES, detect_all_adjusted, monday_ratios, weekday_name,
)
from avsd.changepoint.series import (
    BIN_RUN_DAYS, METRICS, MIN_DAILY_SUPPORT, MIN_POINTS, Components, SeriesSpec, build_series,
    load_components, load_external, series_points, specs_for, transform,
)
from avsd.config import load_config
from avsd.events.agents import FAMILIES

DEFAULTS = {"align_window_run_days": 3, "null_reps": 10000, "block_len_run_days": 5}
METHODS = {"l2": "pelt_l2", "rbf": "pelt_rbf"}
SERIES_SETS = ("all", "family", "agent", "lexical", "external")
CP_SETS = {"all": lambda: pl.lit(True), "persistent": lambda: pl.col("persists_4x_penalty")}
ADJ = "pelt_l2_weekday_adjusted"
COMBOS = [
    ("pelt_l2", "all", lambda: pl.lit(True)),
    ("pelt_l2", "persistent", lambda: pl.col("persists_4x_penalty")),
    ("pelt_l2", "daily", lambda: pl.col("resolution_run_days") == 1),
    ("pelt_rbf", "all", lambda: pl.lit(True)),
    ("pelt_rbf", "persistent", lambda: pl.col("persists_4x_penalty")),
    (ADJ, "daily", lambda: pl.lit(True)),
]
TEST_FRAME_COLS = ["method", "level", "run_day", "resolution_run_days", "group_key", "persists_4x_penalty"]
COMP_WINDOW_RUN_DAYS = 20
COMP_MIN_SHARE = 0.5
UI_URL = "https://theaidigest.org/village?day={day}&time={ms}"
CITATION = 'Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village'


def _detect_task(args: tuple) -> SeriesDetection:
    return detect_series(*args)


def detect_all(
    specs: list[SeriesSpec], values: pl.DataFrame, block_len: int, seed: int, n_workers: int,
    n_boot: int = N_BOOT,
) -> dict[str, SeriesDetection]:
    """detect_series for every spec, in parallel; seeds derive from `seed` and the series id."""
    parts = values.partition_by("series_id", as_dict=True)
    tasks = []
    for s in sorted(specs, key=lambda s: -s.n_points):
        x = parts[(s.series_id,)]["value_t"].to_numpy()
        tasks.append((s.series_id, x, s.resolution, block_len, (seed, zlib.crc32(s.series_id.encode())),
                      BETA, BETAS, n_boot))
    if n_workers > 1:
        with ProcessPoolExecutor(n_workers, mp_context=get_context("fork")) as ex:
            out = list(ex.map(_detect_task, tasks, chunksize=2))
    else:
        out = [_detect_task(t) for t in tasks]
    return {d.series_id: d for d in out}


def _near(p: int, others: np.ndarray, tol: int) -> bool:
    return bool(others.size and np.min(np.abs(others - p)) <= tol)


def changepoint_rows(spec: SeriesSpec, pts: pl.DataFrame, det: SeriesDetection, days: pl.DataFrame,
                     w: int) -> list[dict]:
    """One row per change point and method of one series (position, magnitude, interval, checks)."""
    rd = pts["run_day"].to_numpy()
    rd_end = pts["run_day_end"].to_numpy()
    v = pts["value"].to_numpy()
    na = pts["n_agents"].cast(pl.Float64).fill_null(float("nan")).to_numpy()
    z = det.z(pts["value_t"].to_numpy())
    n = len(rd)
    tol = max(w, spec.resolution)

    def mean_agents(a: int, b: int) -> float | None:
        x = na[a:b]
        return float(np.nanmean(x)) if np.isfinite(x).any() else None

    dmap = dict(days.select("run_day", "date").iter_rows())
    vmap = dict(days.select("run_day", "village_day").iter_rows())
    boc = rd[det.bocpd] if det.bocpd else np.array([], dtype=int)
    rows = []
    for key, method in METHODS.items():
        cps = det.cps.get(key, [])
        s2 = rd[det.sweep[f"{key}@{2 * BETA:g}"]] if det.sweep[f"{key}@{2 * BETA:g}"] else np.array([])
        s4 = rd[det.sweep[f"{key}@{4 * BETA:g}"]] if det.sweep[f"{key}@{4 * BETA:g}"] else np.array([])
        bounds = [0, *cps, n]
        for j, c in enumerate(cps):
            a, b = bounds[j], bounds[j + 2]
            p = int(rd[c])
            before, after = float(v[a:c].mean()), float(v[c:b].mean())
            dist = int(np.min(np.abs(boc - p))) if boc.size else None
            r = {
                "series_id": spec.series_id, "level": spec.level, "entity": spec.entity,
                "metric": spec.metric.name, "metric_label": spec.metric.label,
                "resolution_run_days": spec.resolution, "method": method, "cp_index": j + 1,
                "n_cp_series": len(cps), "run_day": p, "date": dmap[p], "village_day": vmap[p],
                "segment_before_from": dmap[int(rd[a])], "segment_after_to": dmap[int(rd_end[b - 1])],
                "mean_before": before, "mean_after": after, "magnitude": after - before,
                "rel_change": (after - before) / abs(before) if before else None,
                "magnitude_std": float(z[c:b].mean() - z[a:c].mean()),
                "n_agents_before": mean_agents(a, c), "n_agents_after": mean_agents(c, b),
                "ci_lo_run_day": None, "ci_hi_run_day": None, "ci_lo_date": None, "ci_hi_date": None,
                "boot_detect_rate": None,
                "persists_2x_penalty": _near(p, s2, tol), "persists_4x_penalty": _near(p, s4, tol),
                "bocpd_agree": dist is not None and dist <= tol, "bocpd_distance_run_days": dist,
            }
            if key == "l2" and j < len(det.boot):
                lo, hi, rate = det.boot[j]
                if lo is not None:
                    r.update(ci_lo_run_day=int(rd[lo]), ci_hi_run_day=int(rd[hi]),
                             ci_lo_date=dmap[int(rd[lo])], ci_hi_date=dmap[int(rd[hi])])
                r["boot_detect_rate"] = rate
            rows.append(r)
    return rows


def composition(comp: Components, spec: SeriesSpec, pts: pl.DataFrame, cps: list[int], j: int) -> dict:
    """Family-level change point j recomputed with the agents active on both sides (module doc)."""
    rd = pts["run_day"].to_numpy()
    res = spec.resolution
    tau = int(rd[cps[j]])
    prev = int(rd[cps[j - 1]]) if j else int(rd[0])
    nxt = int(rd[cps[j + 1]]) if j + 1 < len(cps) else int(rd[-1]) + res
    h = max(COMP_WINDOW_RUN_DAYS, 4 * res)
    b_lo, a_hi = max(prev, tau - h), min(nxt - 1, tau + h - 1)
    d = comp.daily.filter(pl.col("agent_id").is_in(list(spec.agent_ids))
                          & pl.col("run_day").is_between(b_lo, a_hi))
    days_b = d.filter(pl.col("run_day") < tau)["run_day"].n_unique()
    days_a = d.filter(pl.col("run_day") >= tau)["run_day"].n_unique()
    act = d.group_by("agent_id").agg((pl.col("run_day") < tau).sum().alias("nb"),
                                     (pl.col("run_day") >= tau).sum().alias("na"))
    stay = act.filter((pl.col("nb") >= max(2.0, COMP_MIN_SHARE * days_b))
                      & (pl.col("na") >= max(2.0, COMP_MIN_SHARE * days_a)))["agent_id"].to_list()
    out = {"comp_n_agents_before": int((act["nb"] > 0).sum()),
           "comp_n_agents_after": int((act["na"] > 0).sum()), "comp_n_stayers": len(stay),
           "comp_mean_before": None, "comp_mean_after": None, "comp_magnitude": None,
           "comp_ratio": None, "comp_p": None, "comp_verdict": "no stayers"}
    if not stay:
        return out
    full = series_points(comp.daily, spec.agent_ids, spec.metric, res, b_lo, a_hi)
    st = series_points(comp.daily, stay, spec.metric, res, b_lo, a_hi)

    def split(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        return (df.filter(pl.col("run_day") < tau)["value"].to_numpy(),
                df.filter(pl.col("run_day") >= tau)["value"].to_numpy())

    fb, fa = split(full)
    sb, sa = split(st)
    if min(len(sb), len(sa), len(fb), len(fa)) < 2:
        out["comp_verdict"] = "too few points"
        return out
    tb, ta = transform(sb, spec.metric), transform(sa, spec.metric)
    full_d = transform(fa, spec.metric).mean() - transform(fb, spec.metric).mean()
    stay_d = ta.mean() - tb.mean()
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # near-constant windows
        p = float(stats.ttest_ind(ta, tb, equal_var=False).pvalue)
    ratio = float(stay_d / full_d) if full_d else None
    shift = (not math.isnan(p)) and p < 0.05 and ratio is not None and ratio > 0
    verdict = ("no shift among stayers" if not shift else
               "shift among stayers" if ratio >= 0.5 else "partial shift among stayers")
    out.update(comp_mean_before=float(sb.mean()), comp_mean_after=float(sa.mean()),
               comp_magnitude=float(sa.mean() - sb.mean()), comp_ratio=ratio,
               comp_p=None if math.isnan(p) else p, comp_verdict=verdict)
    return out


def series_order(active: list[SeriesSpec], comp: Components) -> pl.DataFrame:
    """Figure rows: families then agents (by first active run day) then words, then modules A, B1."""
    first = dict(comp.daily.group_by("agent_id").agg(pl.col("run_day").min()).iter_rows())
    mpos = {m.name: i for i, m in enumerate(METRICS)}
    fam = [*FAMILIES, "All agents"]
    words = comp.lexical.family_words

    def key(s: SeriesSpec) -> tuple:
        if s.level == "family":
            return (0, fam.index(s.entity), mpos[s.metric.name], "")
        if s.level == "agent":
            return (1, first.get(s.agent_ids[0], 0), mpos[s.metric.name], s.entity)
        if s.level == "lexical":
            w = s.metric.name.split(":", 1)[1]
            return (2, fam.index(s.entity), words.get(s.entity, []).index(w), "")
        return (3, 0, 0, s.series_id)

    ordered = sorted(active, key=key)
    return pl.DataFrame({"series_id": [s.series_id for s in ordered], "level": [s.level for s in ordered]})


def entry_table(cps: pl.DataFrame, entries: pl.DataFrame) -> pl.DataFrame:
    """Per CHANGELOG entry: PELT l2 change points and series with a change point within w."""
    m = (cps.filter(pl.col("method") == "pelt_l2")
         .select("series_id", pl.col("entries_within_w").str.split(";").alias("entry_id"))
         .explode("entry_id").filter(pl.col("entry_id") != ""))
    g = m.group_by("entry_id").agg(pl.len().alias("n_changepoints"),
                                   pl.col("series_id").n_unique().alias("n_series"))
    return (entries.select("entry_id", "date_start", "source", pl.col("categories").list.join(";"))
            .join(g, on="entry_id", how="left")
            .with_columns(pl.col("n_changepoints").fill_null(0), pl.col("n_series").fill_null(0))
            .sort(["n_series", "date_start"], descending=[True, False]))


def ui_links(days: pl.DataFrame) -> dict[int, str]:
    """run day -> live UI link at the midpoint of its main run block."""
    out = {}
    for r in days.iter_rows(named=True):
        mid: datetime = r["main_start"] + (r["main_end"] - r["main_start"]) / 2
        out[r["run_day"]] = UI_URL.format(day=r["village_day"], ms=int(mid.timestamp() * 1000))
    return out


def residual_diagnostics(active: list[SeriesSpec], parts: dict, dets: dict[str, SeriesDetection]) -> dict:
    """Lag-1 autocorrelation and variance of the l2 residuals (standardised scale), daily series."""
    rho, var = [], []
    for s in active:
        if s.resolution != 1:
            continue
        det = dets[s.series_id]
        z = det.z(parts[(s.series_id,)]["value_t"].to_numpy())
        r = z - segment_means(z, det.cps["l2"])
        if r.size > 3 and r.std() > 0:
            rho.append(float(np.corrcoef(r[:-1], r[1:])[0, 1]))
            var.append(float(r.var()))
    q = lambda a: [float(np.quantile(a, x)) for x in (0.25, 0.5, 0.75)] if a else [None] * 3  # noqa: E731
    return {"n": len(rho), "rho": q(rho), "var": q(var)}


def _fmt(x, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _md_table(df: pl.DataFrame, nd: int = 3) -> str:
    cols = df.columns
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in df.iter_rows():
        lines.append("| " + " | ".join(_fmt(v, nd).replace("|", "\\|") for v in r) + " |")
    return "\n".join(lines)


HEAD_COLS = ("entry_set", "n_entries", "n_changepoints", "coverage_frac", "aligned", "aligned_frac",
             "null1_mean", "null1_q025", "null1_q975", "null1_p", "null1_p_exact", "null1_p_holm",
             "null2_mean", "null2_q025", "null2_q975", "null2_p", "null2_p_holm")
NEW_SETS = ("scaffolding", "village goal transitions", "scaffolding + goal transitions",
            "agent goal changes", *(f"monitor {c} ({s})" for s in ("medium/high", "high")
                                    for c in TEST_CATEGORIES))
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _sel(al: pl.DataFrame, method: str, cp_set: str, w: int | None = None, series_set: str = "all",
         sets: tuple[str, ...] | None = None, families: tuple[str, ...] | None = None) -> pl.DataFrame:
    m = (pl.col("method") == method) & (pl.col("cp_set") == cp_set) & (pl.col("series_set") == series_set)
    if w is not None:
        m &= pl.col("w") == w
    if sets is not None:
        m &= pl.col("entry_set").is_in(list(sets))
    if families is not None:
        m &= pl.col("holm_family").is_in(list(families))
    return al.filter(m)


def write_qa(path: Path, ctx: dict) -> None:
    """outputs/qa/changepoint.md: aggregates only."""
    s: pl.DataFrame = ctx["series_index"]
    cps: pl.DataFrame = ctx["cps"]
    al: pl.DataFrame = ctx["alignment"]
    l2 = cps.filter((pl.col("method") == "pelt_l2") & pl.col("level").is_in(R.OWN_LEVELS))
    w = ctx["w"]
    analysed = s.filter(pl.col("skipped").is_null())
    cl_fams = (R.SUMMARY, R.CATEGORY)
    new_cols = ("entry_set", "w", "n_entries", "n_domain_days", "n_changepoints", "coverage_frac",
                "aligned", "aligned_frac", "null1_mean", "null1_p", "null1_p_holm", "null2_mean", "null2_p",
                "null2_p_holm", "null1w_mean", "null1w_p", "null1w_p_holm", "null2w_mean", "null2w_p",
                "null2w_p_holm")
    week_cols = ("entry_set", "w", "coverage_frac", "aligned", "null1_p", "null2_p", "null1w_mean",
                 "null1w_p", "null1w_p_holm", "null2w_mean", "null2w_p", "null2w_p_holm")
    headline_ws = tuple(sorted({0, 1, w}))
    adj_sets = ("all", "scaffolding", "roster only", "goal", "village goal transitions",
                "scaffolding + goal transitions", "agent goal changes")
    adj_cols = ("method", "entry_set", "w", "n_changepoints", "coverage_frac", "aligned", "aligned_frac",
                "null1_p", "null2_p", "null1w_p", "null2w_p")
    sweep = _sel(al, "pelt_l2", "all")
    cover = (sweep.select("entry_set", "w", "coverage_frac")
             .pivot(on="w", index="entry_set", values="coverage_frac", sort_columns=True))
    cover = cover.rename({c: f"w={c}" for c in cover.columns if c != "entry_set"})
    pvals = (sweep.select("entry_set", "w", pl.format("{} / {}", pl.col("null1_p").round(3),
                                                      pl.col("null2_p").round(3)).alias("p"))
             .pivot(on="w", index="entry_set", values="p", sort_columns=True))
    pvals = pvals.rename({c: f"w={c}" for c in pvals.columns if c != "entry_set"})
    out = [
        "# QA: module C, change points and CHANGELOG alignment (SPEC 7)", "",
        CITATION, "",
        f"Generated by `avsd changepoint` (`src/avsd/changepoint/`) on {ctx['generated']}. "
        f"Runtime {ctx['runtime_s']:.0f} s on {ctx['n_workers']} processes "
        f"({', '.join(f'{k} {v:.0f} s' for k, v in ctx['timings'].items())}).", "",
        "## 1. Inputs", "",
        f"- Run days: {ctx['n_days']} ({ctx['first_date']} to {ctx['last_date']}).",
        f"- Agent-days with activity: {ctx['comp_stats']['agent_days']:,}; agent chat messages "
        f"{ctx['comp_stats']['messages']:,} (without content: {ctx['comp_stats']['messages_without_content']}); "
        f"agent-days dropped as not present (roster rule): {ctx['comp_stats']['agent_days_dropped']}.",
        f"- CHANGELOG entries: {ctx['n_entries']} ({ctx['n_scaffolding']} scaffolding bullets, "
        f"{ctx['n_roster']} roster joins and leaves), {ctx['n_entries_moved']} of them dated on a day "
        "without a run and moved to the next run day.",
        f"- Documented goal changes: {ctx['n_goals']} village goal transitions on "
        f"{ctx['n_goal_days']} run days, and {ctx['n_agoals']} agent goal changes of "
        f"{ctx['n_agoal_agents']} agents on {ctx['n_agoal_days']} run days from {ctx['agoal_first']}. "
        "A goal start belongs to the first run day whose last block ends at or after it.",
        f"- Monitor: {ctx['external'].get('monitor', 'not available')}.",
        f"- Alignment window w = {w} run days (SPEC default), swept over w = "
        f"{', '.join(str(x) for x in ctx['ws'])}; null reps {ctx['reps']:,}; bootstrap block "
        f"{ctx['block']} run days, {ctx['n_boot']} replicates; seed {ctx['seed']}.", "",
        "## 2. Series", "",
        f"Candidate series {s.height}, analysed {analysed.height}, skipped {s.height - analysed.height} "
        f"({', '.join(f'{k}: {v}' for k, v in ctx['skip_counts'].items()) or 'none'}). "
        f"Acceptance (at least 20 series with completed detection): "
        f"{'met' if analysed.height >= 20 else 'NOT MET'} ({analysed.height}). External series "
        "(monitor counts, modules A and B1) are listed separately and are not part of the series "
        "set \"all\" in the alignment tests.", "",
        f"Sparse series (median daily support below {MIN_DAILY_SUPPORT}) are pooled into "
        f"{BIN_RUN_DAYS}-run-day bins; series need {MIN_POINTS} points.", "",
        _md_table(ctx["series_counts"]), "",
        "Every analysed series with its number of change points (PELT l2, PELT rbf, BOCPD):", "",
        "<details><summary>Series list</summary>", "",
        _md_table(analysed.select("series_id", "resolution_run_days", "n_points", "n_cp_l2",
                                  "n_cp_rbf", "n_cp_bocpd")),
        "", "</details>", "",
        "## 3. Detection settings", "",
        f"PELT (ruptures, custom cumulative-sum costs equal to CostL2 and CostRbf), minimum segment "
        f"{MIN_SEGMENT_RUN_DAYS} run days, jump 1. Penalty beta * log(n) on the series standardised by "
        f"the MAD of first differences (l2), and beta * v * log(n) for rbf; default beta = {BETA:g}. "
        f"BOCPD: Normal-Gamma prior (0, 1, 1, 1) on the same scale, constant hazard of one change per "
        f"{BOCPD_RUN_DAYS:g} run days.", "",
        "## 4. Penalty sensitivity", "",
        _md_table(ctx["sweep"]), "",
        f"Share of default l2 change points that persist (a change point within max(w, resolution) "
        f"run days) at 2x the penalty: {ctx['persist2']:.3f}; at 4x: {ctx['persist4']:.3f}. The "
        "persistent set (4x) is tested separately in section 8.", "",
        f"Residuals around the l2 segment means of the {ctx['resid']['n']} daily series, on the "
        "standardised scale (quartiles): lag-1 autocorrelation "
        + " / ".join(_fmt(v, 2) for v in ctx["resid"]["rho"]) + ", variance "
        + " / ".join(_fmt(v, 2) for v in ctx["resid"]["var"]) + ". The BIC-type penalty assumes "
        "independent noise of unit variance; positive autocorrelation and a variance above 1 mean "
        "that the default penalty splits more readily than that assumption implies, which is why "
        "the sweep and the persistent set are reported.", "",
        "## 5. BOCPD agreement", "",
        _md_table(ctx["bocpd"]), "",
        "Agreement: a BOCPD change point within max(w, resolution) run days. Chance: the mean share "
        "of a series' points that lie that close to one of its BOCPD change points.", "",
        "## 6. Bootstrap location intervals (PELT l2)", "",
        f"Change points with an interval (at least 10 matched replicates): {ctx['boot']['with_ci']} of "
        f"{ctx['boot']['n']}. Median interval width {ctx['boot']['median_width']} run days; median "
        f"detection rate {ctx['boot']['median_rate']:.2f}.", "",
        "## 7. Composition check (family-level and lexical series)", "",
        _md_table(ctx["composition"]), "",
        f"## 8. Alignment with the CHANGELOG (SPEC primary result, w = {w})", "",
        "S is the number of change points with an entry within w run days (a change point found in "
        "bins covers half a bin on each side). Null 1 shifts all entries together on the circle of "
        "domain run days, by more than 2w; null 2 places each distinct entry interval at its own "
        "uniformly drawn start. Means and 2.5 to 97.5% ranges are over the null draws; p is "
        "one-sided. Holm adjusts within one method, change-point set, series set and w, across the "
        "CHANGELOG category rows, and separately across the goal and monitor rows (\"all\" and "
        "\"scaffolding\" are summaries). Coverage is the share of domain run days within w of an "
        "entry. The roster category holds exactly the roster joins and leaves, so its row is "
        "\"roster only\". Every goal entry also carries prompt, so the prompt category is \"prompt "
        "(goal pooled)\", and \"goal\" with \"prompt without goal\" is the variant with goal changes "
        "as their own category. The series set \"all\" is the module's own series (family, agent, "
        "lexical).", "",
        "PELT l2, all change points, all series:", "",
        _md_table(_sel(al, "pelt_l2", "all", w, families=cl_fams).select(HEAD_COLS)), "",
        "PELT l2, persistent change points (4x penalty), all series:", "",
        _md_table(_sel(al, "pelt_l2", "persistent", w, families=cl_fams).select(HEAD_COLS)), "",
        "All CHANGELOG entries, by method, change-point set and series set:", "",
        _md_table(al.filter((pl.col("entry_set") == "all") & (pl.col("w") == w)).select(
            "method", "cp_set", "series_set", "n_changepoints", "coverage_frac", "aligned",
            "aligned_frac", "null1_mean", "null1_sd", "null1_p", "null2_mean", "null2_sd", "null2_p")), "",
        "Full table (every w): `outputs/tables/changepoint_alignment.csv`.", "",
        "Week-preserving nulls for the CHANGELOG sets (PELT l2, all change points, all series): null "
        "1w shifts all entries by whole calendar weeks (exact over the allowed shifts), null 2w places "
        "each entry among the run days of its own weekday. Holm as above, for each null. "
        f"{ctx['week_note']}", "",
        _md_table(_sel(al, "pelt_l2", "all", families=cl_fams).filter(pl.col("w").is_in(list(headline_ws)))
                  .sort("w").select(week_cols)), "",
        "CHANGELOG entries with the most series that change within w run days (PELT l2):", "",
        _md_table(ctx["entry_table"].head(20)), "",
        f"Entries with no l2 change point within w: {ctx['entry_table'].filter(pl.col('n_changepoints') == 0).height} "
        f"of {ctx['entry_table'].height}.", "",
        "## 9. Goal transitions and monitor findings next to the CHANGELOG", "",
        "Village goal transitions and agent goal changes are documented changes that the CHANGELOG "
        "does not list. Agent goal changes count only for the agent's own series and for the family "
        "and all-agent series that include it, over the run days from the first agent goal on. The "
        "monitor sets use the run days with a medium or high severity finding of the category, over "
        "the monitor coverage window, and both nulls place them on covered run days only. These are "
        f"annotations; they do not state causes. Headline at w = 1, with w = 0 and the SPEC default "
        f"w = {w}; nulls 1w and 2w keep the weekday of each entry (not run for the monitor sets):", "",
        "PELT l2, all change points, all series:", "",
        _md_table(_sel(al, "pelt_l2", "all", sets=NEW_SETS).filter(pl.col("w").is_in(list(headline_ws)))
                  .sort("w", "entry_set").select(new_cols)), "",
        "PELT l2, persistent change points, all series:", "",
        _md_table(_sel(al, "pelt_l2", "persistent", sets=NEW_SETS).filter(pl.col("w").is_in(list(headline_ws)))
                  .sort("w", "entry_set").select(new_cols)), "",
        "PELT rbf, all change points, all series:", "",
        _md_table(_sel(al, "pelt_rbf", "all", sets=NEW_SETS).filter(pl.col("w").is_in(list(headline_ws)))
                  .sort("w", "entry_set").select(new_cols)), "",
        "Weekdays of the run days, of the PELT l2 change points of daily series (own series; binned "
        "series are left out because their positions are bin starts), and of the village goal "
        "transitions. The circular shift keeps the spacing of the entries, so shifts by whole weeks "
        "keep their weekdays; the uniform placement does not.", "",
        _md_table(ctx["weekdays"]), "",
        "## 10. Window sensitivity (PELT l2, all change points, all series)", "",
        "Coverage, the share of domain run days within w of an entry (for agent goal changes, "
        "averaged over the change points' groups):", "",
        _md_table(cover), "",
        "p-values, null 1 / null 2:", "",
        _md_table(pvals), "",
        "## 11. Weekday-adjusted detection (robustness check)", "",
        *ctx["weekday_lines"], "",
        "Alignment of the change points of the same daily series, before (pelt_l2, cp_set daily) and "
        "after weekday adjustment (pelt_l2_weekday_adjusted), all series:", "",
        _md_table(al.filter(pl.col("cp_set").eq("daily") & (pl.col("series_set") == "all")
                            & pl.col("entry_set").is_in(list(adj_sets)) & pl.col("w").is_in(list(headline_ws)))
                  .sort("entry_set", "w", "method").select(adj_cols)), "",
        "## 12. Monday pattern of the family-level daily series", "",
        "For each calendar week with all five weekdays, the value on Monday divided by the mean of "
        "Tuesday to Friday (original units). Mean and median over weeks; perma-computer-use regimes "
        "split at 2026-03-24 (the week of the rollout left out, Mann-Whitney U); schedule regimes "
        "from the observed run blocks (weeks inside one regime, Kruskal-Wallis over regimes with at "
        "least 3 weeks). A description of the data, not a cause:", "",
        _md_table(ctx["monday"]), "",
        *ctx["monday_lines"], "",
        "## 13. Cause unidentified (PELT l2, own series)", "",
        f"Unaligned to the CHANGELOG (no entry within w = {w}): {ctx['n_unidentified']} of {l2.height} "
        f"change points ({ctx['n_unidentified_persistent']} persist at 4x the penalty), on "
        f"{ctx['unidentified_days'].height} run days. Unaligned to any documented event (CHANGELOG, "
        f"village goal transition, or the series' own agent goal change): {ctx['n_undocumented']} "
        f"({ctx['n_undocumented_persistent']} persistent), on {ctx['undocumented_days'].height} run "
        "days. By level:", "",
        _md_table(ctx["unidentified_levels"]), "",
        "Run days with change points unaligned to any documented event (links: main run block on "
        "p - 2, p - 1, p, p + 1):", "",
        _md_table(ctx["undocumented_days"]), "",
        "## 14. Monitor annotations", "",
        *ctx["monitor_lines"], "",
        "## 15. Lexical words", "",
        f"Top {TOP_K} words per family by z-scored log-odds with an informative Dirichlet prior "
        f"(a_0 = {PRIOR_SIZE:g}), each family against the others; candidates need {MIN_COUNT} uses in "
        f"the family on {MIN_DAYS} run days by {MIN_AGENTS} agents. '{FOCUS_WORD}' has a series in "
        "every family. Candidates removed before the top words were taken: "
        + ", ".join(f"{k} {v}" for k, v in ctx["lex_filters"].items())
        + "; filter lists held " + ", ".join(f"{v} {k}" for k, v in ctx["lex_lists"].items())
        + " (never written out).", "",
        _md_table(ctx["words"]), "",
        "## 16. External series and hooks", "",
        *[f"- {k}: {v}" for k, v in ctx["external"].items()], "",
        "## 17. Privacy", "",
        "All outputs are aggregates per run day or per change point. Humans never appear: series "
        "are built from agent rows only, lexical outputs list words and rates, and words that look "
        "like personal names, handles, e-mail addresses, URLs or keys are filtered (section 15). "
        "CHANGELOG entries are referenced by id, date and category, never by text. Monitor findings "
        "appear only as ids, categories, severities, confidences and counts; their text and the "
        "names of the participants stay in data/.", "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")


def label_changepoints(df: pl.DataFrame, entries: pl.DataFrame, goals: pl.DataFrame, agoals: pl.DataFrame,
                       agoal_groups: list[set[str]], w: int, n_days: int, links: dict[int, str]) -> pl.DataFrame:
    """CHANGELOG match, goal flags, both cause labels and the UI links of unaligned change points.

    `df` has run_day, resolution_run_days and group_key.
    """
    lo, hi = A.cp_interval(df["run_day"].to_numpy(), df["resolution_run_days"].to_numpy(), n_days)
    df = pl.concat([df, A.match_entries(df["run_day"].to_numpy(), lo, hi, entries, w),
                    R.documented_columns(df, goals, agoals, agoal_groups, w, n_days)], how="horizontal")

    def four_links(p: int) -> str:
        return " ".join(links[d] for d in (p - 2, p - 1, p, p + 1) if 1 <= d <= n_days)

    documented = pl.col("aligned") | pl.col("aligned_goal_transition") | pl.col("aligned_agent_goal")
    return df.with_columns(
        pl.when(pl.col("aligned")).then(pl.lit("aligned with CHANGELOG"))
        .otherwise(pl.lit("cause unidentified")).alias("cause"),
        documented.alias("aligned_documented"),
        (~pl.col("aligned")).alias("unaligned_changelog"),
        (~documented).alias("unaligned_documented"),
        pl.when(documented).then(pl.lit("aligned with a documented event"))
        .otherwise(pl.lit("cause unidentified")).alias("cause_documented"),
        pl.when(~pl.col("aligned"))
        .then(pl.col("run_day").map_elements(four_links, return_dtype=pl.String))
        .alias("ui_links"),
    )


def adjusted_rows(daily: list[SeriesSpec], parts: dict, dets: dict[str, SeriesDetection],
                  adj: dict[str, list[int]], days: pl.DataFrame) -> pl.DataFrame:
    """One row per weekday-adjusted PELT l2 change point, with its nearest original l2 change point."""
    dmap = dict(days.select("run_day", "date").iter_rows())
    vmap = dict(days.select("run_day", "village_day").iter_rows())
    rows = []
    for s in daily:
        pts = parts[(s.series_id,)]
        rd, v = pts["run_day"].to_numpy(), pts["value"].to_numpy()
        orig = rd[dets[s.series_id].cps["l2"]] if dets[s.series_id].cps["l2"] else np.array([], dtype=int)
        cps = adj.get(s.series_id, [])
        bounds = [0, *cps, len(rd)]
        for j, c in enumerate(cps):
            a, b, p = bounds[j], bounds[j + 2], int(rd[c])
            dist = int(np.min(np.abs(orig - p))) if orig.size else None
            before, after = float(v[a:c].mean()), float(v[c:b].mean())
            rows.append({
                "series_id": s.series_id, "level": s.level, "entity": s.entity, "metric": s.metric.name,
                "metric_label": s.metric.label, "resolution_run_days": 1, "method": ADJ,
                "cp_index": j + 1, "n_cp_series": len(cps), "run_day": p, "date": dmap[p],
                "village_day": vmap[p], "mean_before": before, "mean_after": after,
                "magnitude": after - before, "nearest_original_distance_run_days": dist,
                "matches_original_within_1": dist is not None and dist <= 1,
            })
    schema = {"cp_index": pl.Int64, "n_cp_series": pl.Int64, "run_day": pl.Int64,
              "resolution_run_days": pl.Int64, "nearest_original_distance_run_days": pl.Int64}
    return pl.DataFrame(rows, schema_overrides=schema, infer_schema_length=None)


def run_changepoint(cfg: dict | None = None, n_workers: int | None = None,
                    n_boot: int = N_BOOT) -> dict:
    """Run module C end to end and write its outputs; returns a summary dict."""
    t0 = time.perf_counter()
    clock = t0
    timings: dict[str, float] = {}

    def lap(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[name] = now - clock
        clock = now

    cfg = cfg or load_config()
    cc = {**DEFAULTS, **(cfg.get("changepoint") or {})}
    w, reps, block = int(cc["align_window_run_days"]), int(cc["null_reps"]), int(cc["block_len_run_days"])
    seed = int(cfg["seed"])
    n_workers = n_workers or int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1))
    outputs, processed = Path(cfg["paths"]["outputs"]), Path(cfg["paths"]["processed"])

    comp = load_components(cfg)
    days, n_days = comp.days, comp.n_days
    specs = specs_for(comp)
    values = build_series(comp, specs)
    ext_specs, ext_values, ext_status = load_external(cfg, days)
    mon = load_monitor(processed, days)
    if mon is not None:
        m_specs, m_values = monitor_series(mon, comp.agents, n_days)
        ext_specs += m_specs
        ext_values = pl.concat([v for v in (ext_values, m_values) if v.height], how="vertical_relaxed")
        ext_status["monitor"] = (
            f"{len(m_specs)} series ({sum(s.skipped is None for s in m_specs)} analysed) from "
            f"data/processed/monitor_findings.parquet: {mon.findings.height:,} findings of the export "
            f"on {len(mon.covered)} run days; coverage window run days {mon.window[0]} to {mon.window[1]} "
            f"({len(mon.domain)} covered run days)")
    else:
        ext_status["monitor"] = "not available (data/processed/monitor_findings.parquet)"
    specs += ext_specs
    if ext_values.height:
        values = pl.concat([values, ext_values], how="vertical_relaxed")
    active = [s for s in specs if s.skipped is None]
    lap("series")

    dets = detect_all(active, values, block, seed, n_workers, n_boot)
    for s in active:
        if dets[s.series_id].skipped:
            s.skipped = dets[s.series_id].skipped
    active = [s for s in active if s.skipped is None]
    lap("detection")

    parts = values.partition_by("series_id", as_dict=True)
    rows, comp_rows = [], []
    for s in active:
        pts, det = parts[(s.series_id,)], dets[s.series_id]
        r = changepoint_rows(s, pts, det, days, w)
        rows += r
        if s.level in ("family", "lexical"):
            for key, method in METHODS.items():
                for j in range(len(det.cps[key])):
                    comp_rows.append({"series_id": s.series_id, "method": method, "cp_index": j + 1,
                                      **composition(comp, s, pts, det.cps[key], j)})
    cps = pl.DataFrame(rows, infer_schema_length=None)
    if comp_rows:
        cps = cps.join(pl.DataFrame(comp_rows, infer_schema_length=None),
                       on=["series_id", "method", "cp_index"], how="left")
    lap("changepoints")

    cl = pl.read_parquet(processed / "changelog.parquet")
    entries = A.map_entries(cl, days)
    tables_dir = Path(cfg["paths"]["tables"])
    goals = village_goal_entries(tables_dir, days)
    agoals = agent_goal_entries(tables_dir, days, comp.agents)
    family_of = dict(comp.agents.select("agent_id", "model_family").iter_rows())
    agoal_groups = agent_goal_groups(agoals, family_of)
    group_of = {s.series_id: R.series_group(s) for s in active}
    cps = cps.with_columns(pl.col("series_id").replace_strict(group_of, default=None, return_dtype=pl.String)
                           .alias("group_key"))
    links = ui_links(days)
    cps = label_changepoints(cps, entries, goals, agoals, agoal_groups, w, n_days, links).sort(
        "method", "level", "series_id", "cp_index")

    # Weekday-adjusted PELT l2 on the daily own series (robustness check).
    wd_of = dict(zip(days["run_day"].to_list(), A.weekdays(days["date"].to_numpy()).tolist()))
    daily = [s for s in active if s.level in R.OWN_LEVELS and s.resolution == 1]
    adj = detect_all_adjusted(
        {s.series_id: (parts[(s.series_id,)]["value_t"].to_numpy(),
                       np.array([wd_of[r] for r in parts[(s.series_id,)]["run_day"].to_list()]))
         for s in daily}, n_workers)
    adjdf = adjusted_rows(daily, parts, dets, adj, days).with_columns(
        pl.col("series_id").replace_strict(group_of, default=None, return_dtype=pl.String).alias("group_key"))
    adjdf = label_changepoints(adjdf, entries, goals, agoals, agoal_groups, w, n_days, links)
    adj_rd = dict(adjdf.group_by("series_id").agg(pl.col("run_day")).iter_rows()) if adjdf.height else {}
    near = []
    for sid, r, m, res, lv in zip(cps["series_id"].to_list(), cps["run_day"].to_list(), cps["method"].to_list(),
                                  cps["resolution_run_days"].to_list(), cps["level"].to_list()):
        if m != "pelt_l2" or res != 1 or lv not in R.OWN_LEVELS:
            near.append(None)
        else:
            a = adj_rd.get(sid) or []
            near.append(bool(a) and min(abs(x - r) for x in a) <= 1)
    cps = cps.with_columns(pl.Series("weekday", weekday_name(cps["date"].to_list())),
                           pl.Series("weekday_adjusted_match_within_1", near, dtype=pl.Boolean))
    adjdf = adjdf.with_columns(pl.Series("weekday", weekday_name(adjdf["date"].to_list())))
    lap("weekday")
    monitor_links = pl.DataFrame()
    if mon is not None:
        agents_of = {s.series_id: (None if s.entity in ("All agents", "Monitor All agents")
                                   else set(s.agent_ids) if s.level != "external"
                                   else {a for a, f in family_of.items() if f"Monitor {f}" == s.entity})
                     for s in active}
        mcols, monitor_links = annotate(cps, mon, agents_of, w)
        cps = pl.concat([cps, mcols], how="horizontal")
    lap("annotation")
    sets = R.reference_sets(entries, goals, agoal_groups=agoal_groups, agoals=agoals, mon=mon, days=days)
    test_frame = pl.concat([cps.select(TEST_FRAME_COLS),
                            adjdf.with_columns(pl.lit(None, pl.Boolean).alias("persists_4x_penalty"))
                            .select(TEST_FRAME_COLS)], how="vertical_relaxed")
    alignment = R.alignment_table(test_frame, sets, days, reps, seed, n_workers, COMBOS, SERIES_SETS,
                                  tuple(sorted({*R.W_SWEEP, w})))
    lap("alignment")

    # Series index and outputs.
    cnt = cps.group_by("series_id", "method").len()
    idx = pl.DataFrame([{
        "series_id": s.series_id, "level": s.level, "entity": s.entity, "metric": s.metric.name,
        "metric_label": s.metric.label, "resolution_run_days": s.resolution, "n_points": s.n_points,
        "skipped": s.skipped,
        "n_cp_bocpd": len(dets[s.series_id].bocpd) if s.skipped is None else None,
    } for s in specs], infer_schema_length=None)
    for key, method in METHODS.items():
        c = cnt.filter(pl.col("method") == method).select("series_id", pl.col("len").alias(f"n_cp_{key}"))
        idx = idx.join(c, on="series_id", how="left").with_columns(
            pl.when(pl.col("skipped").is_null()).then(pl.col(f"n_cp_{key}").fill_null(0))
            .alias(f"n_cp_{key}"))
    tables = outputs / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    cps.drop("group_key").write_csv(tables / "changepoints.csv")
    alignment.write_csv(tables / "changepoint_alignment.csv")
    if monitor_links.height:
        monitor_links.write_parquet(tables / "changepoint_monitor_findings.parquet")
    adjdf.drop("group_key").write_csv(tables / "changepoints_weekday_adjusted.csv")
    fam_daily = [s.series_id for s in daily if s.level == "family"]
    mratio = monday_ratios(values.filter(pl.col("series_id").is_in(fam_daily))
                           .select("series_id", "run_day", "value"), days)
    mratio.write_csv(tables / "monday_ratio.csv")
    idx.write_csv(tables / "changepoint_series.csv")
    comp.lexical.words.write_csv(tables / "lexical_words.csv")
    values.join(idx.select("series_id", "level", "entity", "metric", "resolution_run_days"),
                on="series_id", how="left").write_parquet(processed / "changepoint_series.parquet")
    l2 = cps.filter(pl.col("method") == "pelt_l2")
    fig_paths = plot_timeline(l2.select("series_id", "date", "aligned"), entries,
                              series_order(active, comp), outputs / "figures" / "F5_changepoint_timeline",
                              goals=goals)
    lap("outputs")

    # QA context (own series: family, agent, lexical).
    own_active = [s for s in active if s.level in R.OWN_LEVELS]
    sweep_rows = []
    for b in sorted({*BETAS, BETA, 2 * BETA, 4 * BETA}):
        row = {"beta": b}
        for key in METHODS:
            counts = [len(dets[s.series_id].sweep[f"{key}@{b:g}"]) for s in own_active]
            row[f"{key}_changepoints"] = int(sum(counts))
            row[f"{key}_series_with_cp"] = int(sum(c > 0 for c in counts))
        sweep_rows.append(row)
    boc_rows = []
    for key, method in METHODS.items():
        m = cps.filter((pl.col("method") == method) & pl.col("level").is_in(R.OWN_LEVELS))
        chance = []
        for s in own_active:
            det = dets[s.series_id]
            ncp = len(det.cps[key])
            if not ncp:
                continue
            rd = parts[(s.series_id,)]["run_day"].to_numpy()
            tol = max(w, s.resolution)
            boc = rd[det.bocpd] if det.bocpd else np.array([])
            cover = np.mean([_near(int(p), boc, tol) for p in rd]) if boc.size else 0.0
            chance += [cover] * ncp
        boc_rows.append({"method": method, "changepoints": m.height,
                         "with_bocpd_within_tol": int(m["bocpd_agree"].sum()),
                         "agreement": float(m["bocpd_agree"].mean()) if m.height else None,
                         "chance": float(np.mean(chance)) if chance else None,
                         "bocpd_changepoints_total": int(sum(len(dets[s.series_id].bocpd) for s in own_active))})
    own = l2.filter(pl.col("level").is_in(R.OWN_LEVELS))
    widths = (own["ci_hi_run_day"] - own["ci_lo_run_day"]).drop_nulls()
    resid = residual_diagnostics(active, parts, dets)
    ent_tab = entry_table(own, entries)
    comp_tab = (cps.filter(pl.col("level").is_in(["family", "lexical"]))
                .group_by("method", "comp_verdict").len().sort("method", "comp_verdict"))

    def by_day(df: pl.DataFrame) -> pl.DataFrame:
        return (df.group_by("run_day", "date").agg(
            pl.len().alias("n_changepoints"), pl.col("series_id").n_unique().alias("n_series"),
            pl.col("persists_4x_penalty").sum().alias("n_persistent"),
            pl.col("level").unique().sort().str.join(", ").alias("levels"),
            pl.col("ui_links").first().alias("ui_links"))
            .sort(["n_changepoints", "run_day"], descending=[True, False]))

    un = own.filter(pl.col("unaligned_changelog"))
    und = own.filter(pl.col("unaligned_documented"))
    levels = (own.group_by("level").agg(pl.len().alias("changepoints"),
                                        pl.col("unaligned_changelog").sum().alias("unaligned_changelog"),
                                        pl.col("aligned_goal_transition").sum().alias("goal_transition_within_w"),
                                        pl.col("unaligned_documented").sum().alias("unaligned_documented"))
              .sort("level"))
    monitor_lines = ["Monitor data not available."]
    if mon is not None:
        inside = own.filter(pl.col("monitor_covered_days") > 0)
        q = lambda c: " / ".join(_fmt(float(inside[c].quantile(x)), 0) for x in (0.25, 0.5, 0.75))  # noqa: E731
        sev = (monitor_links.filter((pl.col("method") == "pelt_l2") & pl.col("severity").is_in(SEVERE)
                                    & pl.col("series_id").is_in(inside["series_id"].unique().to_list()))
               if monitor_links.height else pl.DataFrame({"category": [], "series_id": [], "cp_index": []}))
        cat_lines = []
        for c in TEST_CATEGORIES:
            n_c = sev.filter(pl.col("category") == c).select("series_id", "cp_index").unique().height
            cat_lines.append(f"{c} {n_c} ({n_c / max(1, inside.height):.1%})")
        m_cp = cps.filter((pl.col("method") == "pelt_l2") & pl.col("series_id").str.starts_with("monitor:"))
        monitor_lines = [
            f"Own-series PELT l2 change points with a covered run day within w = {w} run days (plus "
            f"half a bin): {inside.height} of {own.height}. Findings in that window per change point "
            f"(quartiles): {q('monitor_n_findings')}; findings that involve the series' agents: "
            f"{q('monitor_n_series_agents')}.",
            "",
            "Change points with at least one medium or high severity finding involving the series' "
            "agents in the window: " + "; ".join(cat_lines) + ". The alignment tests in sections 9 "
            "and 10 compare the monitor dates with chance placements on covered run days.",
            "",
            f"Monitor series: {sum(1 for x in active if x.series_id.startswith('monitor:'))} analysed, "
            f"with {m_cp.height} PELT l2 change points ({int(m_cp['aligned'].sum()) if m_cp.height else 0} "
            "within w of a CHANGELOG entry). Per change point, `changepoints.csv` holds the counts by "
            "category and severity and the ids of the medium or high severity findings that involve "
            "the series' agents; `outputs/tables/changepoint_monitor_findings.parquet` lists every change "
            f"point and finding pair that involves the series' agents ({monitor_links.height:,} rows: "
            "ids, categories, severities, confidences and run-day offsets only).",
        ]
    series_counts = (idx.group_by("level", "metric").agg(
        pl.len().alias("candidates"), pl.col("skipped").is_null().sum().alias("analysed"),
        (pl.col("skipped").is_null() & (pl.col("resolution_run_days") > 1)).sum().alias("binned"),
        pl.col("n_cp_l2").sum().alias("cp_l2"), pl.col("n_cp_rbf").sum().alias("cp_rbf"))
        .sort("level", "metric"))
    for lv, label in (("lexical", "words"), ("external", "monitor and modules A, B1")):
        sub = series_counts.filter(pl.col("level") == lv)
        if sub.height:
            series_counts = pl.concat([
                series_counts.filter(pl.col("level") != lv),
                sub.group_by("level").agg(pl.lit(label).alias("metric"),
                                          *[pl.col(c).sum() for c in sub.columns[2:]]),
            ], how="diagonal_relaxed")
    skip_counts = dict(idx.filter(pl.col("skipped").is_not_null()).group_by("skipped").len().iter_rows())
    ws = tuple(sorted({*R.W_SWEEP, w}))
    od = own.filter(pl.col("resolution_run_days") == 1)
    share_mon_days = float((A.weekdays(days["date"].to_numpy()) == 0).mean())

    def mon_share(df: pl.DataFrame) -> float:
        return float((df["weekday"] == "Monday").mean()) if df.height else 0.0

    od_mon = od.filter(pl.col("weekday") == "Monday")
    by_level = (pl.DataFrame({"level": list(R.OWN_LEVELS)})
                .join(od.group_by("level").agg(pl.len().alias("original"),
                                               (pl.col("weekday") == "Monday").mean().alias("original_monday_share"),
                                               pl.col("weekday_adjusted_match_within_1").sum().alias("original_kept")),
                      on="level", how="left")
                .join(adjdf.group_by("level").agg(pl.len().alias("adjusted"),
                                                  (pl.col("weekday") == "Monday").mean().alias("adjusted_monday_share"),
                                                  pl.col("matches_original_within_1").sum().alias("adjusted_matched")),
                      on="level", how="left"))
    weekday_lines = [
        f"Daily own series: {len(daily)}. Before adjustment they have {od.height} PELT l2 change points, "
        f"{mon_share(od):.1%} of them on Mondays (Mondays are {share_mon_days:.1%} of run days). After "
        f"weekday adjustment: {adjdf.height} change points, {mon_share(adjdf):.1%} on Mondays.",
        "",
        f"{int(adjdf['matches_original_within_1'].sum())} of {adjdf.height} adjusted change points lie "
        f"within 1 run day of an original change point of the same series, and "
        f"{int(od['weekday_adjusted_match_within_1'].sum())} of {od.height} original change points keep an "
        f"adjusted one within 1 run day ({int(od_mon['weekday_adjusted_match_within_1'].sum())} of the "
        f"{od_mon.height} on Mondays). By level:",
        "",
        _md_table(by_level),
        "",
        "Weekday adjustment: the median, over each series, of the deviation from a centred 5-point "
        "rolling median on each weekday is subtracted on the detection scale; PELT l2 then runs with "
        "the default penalty. Rows: `outputs/tables/changepoints_weekday_adjusted.csv`; in "
        "`changepoints.csv` the column `weekday_adjusted_match_within_1` marks original daily-series "
        "l2 change points with an adjusted one within 1 run day.",
    ]
    ks_all = _sel(alignment, "pelt_l2", "all").filter(pl.col("n_week_shifts").is_not_null())
    k_full = ks_all.filter(pl.col("entry_set") == "all")["n_week_shifts"].max()
    k_era = ks_all.filter(pl.col("entry_set") == "agent goal changes")["n_week_shifts"].max()
    week_note = (
        f"With at most {k_full} allowed week shifts the smallest null 1w p-value is 1/{(k_full or 0) + 1} "
        f"(1/{(k_era or 0) + 1} over the agent-goal era), so its Holm-adjusted values over "
        "the nine category rows cannot fall below about nine times that.") if k_full else ""
    mcols = [c for c in ("series_id", "n_weeks", "mean_ratio", "median_ratio", "share_weeks_monday_higher",
                         "mean_pre_cu", "mean_post_cu", "p_pre_vs_post_cu", "mean_2h", "mean_3h", "mean_4h",
                         "mean_8h_event", "mean_8h", "p_schedule_regimes") if c in mratio.columns]
    monday = mratio.select(mcols) if mratio.height else pl.DataFrame()
    monday_lines = []
    if mratio.height:
        monday_lines = [
            f"{int((mratio['mean_ratio'] > 1).sum())} of {mratio.height} family-level daily series have a "
            f"mean Monday / Tuesday-Friday ratio above 1 (median of the means "
            f"{float(mratio['mean_ratio'].median()):.2f}). The ratio differs between the perma-computer-use "
            f"regimes (p < 0.05) for {int((mratio['p_pre_vs_post_cu'] < 0.05).sum())} series and between "
            f"schedule regimes for {int((mratio['p_schedule_regimes'] < 0.05).sum())} (unadjusted p). "
            "Table: `outputs/tables/monday_ratio.csv`.",
        ]
    wd = lambda col: pl.col(col).dt.weekday()  # noqa: E731
    weekdays = (
        pl.DataFrame({"wd": range(1, 8), "weekday": WEEKDAYS})
        .join(days.group_by(wd("date").alias("wd")).len().rename({"len": "run_days"}), on="wd", how="left")
        .join(own.filter(pl.col("resolution_run_days") == 1).group_by(wd("date").alias("wd")).len()
              .rename({"len": "daily_series_changepoints"}), on="wd", how="left")
        .join(goals.group_by(wd("date_start").alias("wd")).len().rename({"len": "goal_transitions"}),
              on="wd", how="left")
        .with_columns(pl.exclude("weekday", "wd").fill_null(0)).drop("wd")
    )
    runtime = time.perf_counter() - t0
    ctx = {
        "generated": date.today().isoformat(), "runtime_s": runtime, "n_workers": n_workers,
        "timings": timings, "n_days": n_days, "first_date": days["date"].min(),
        "last_date": days["date"].max(), "comp_stats": comp.stats, "n_entries": entries.height,
        "n_scaffolding": entries.filter(pl.col("source") == "changelog").height,
        "n_roster": entries.filter(pl.col("source") == "roster").height,
        "n_entries_moved": int((~entries["date_start"].is_in(days["date"].to_list())).sum()),
        "n_goals": goals.height, "n_goal_days": goals["rd_start"].n_unique(),
        "n_agoals": agoals.height, "n_agoal_agents": agoals["agent_id"].n_unique() if agoals.height else 0,
        "n_agoal_days": agoals["rd_start"].n_unique() if agoals.height else 0,
        "agoal_first": agoals["date_start"].min() if agoals.height else None,
        "w": w, "ws": ws, "reps": reps, "block": block, "seed": seed, "n_boot": n_boot,
        "series_index": idx, "cps": cps,
        "alignment": alignment, "skip_counts": skip_counts, "series_counts": series_counts,
        "sweep": pl.DataFrame(sweep_rows), "persist2": float(own["persists_2x_penalty"].mean()),
        "persist4": float(own["persists_4x_penalty"].mean()), "bocpd": pl.DataFrame(boc_rows),
        "boot": {"n": own.height, "with_ci": int(own["ci_lo_run_day"].is_not_null().sum()),
                 "median_width": int(widths.median()) if widths.len() else None,
                 "median_rate": float(own["boot_detect_rate"].median() or 0.0)},
        "composition": comp_tab, "n_unidentified": un.height, "unidentified_days": by_day(un),
        "n_unidentified_persistent": int(un["persists_4x_penalty"].sum()),
        "n_undocumented": und.height, "n_undocumented_persistent": int(und["persists_4x_penalty"].sum()),
        "undocumented_days": by_day(und), "unidentified_levels": levels, "monitor_lines": monitor_lines,
        "week_note": week_note,
        "weekdays": weekdays, "weekday_lines": weekday_lines, "monday": monday,
        "monday_lines": monday_lines,
        "words": comp.lexical.words.select("family", "rank", "word", "z", "rate_family_per_1000_msgs",
                                           "rate_rest_per_1000_msgs"),
        "lex_filters": comp.lexical.filter_counts, "lex_lists": comp.lexical.list_sizes,
        "external": ext_status, "resid": resid,
        "entry_table": ent_tab,
    }
    qa = outputs / "qa" / "changepoint.md"
    write_qa(qa, ctx)
    head = _sel(alignment, "pelt_l2", "all").filter(pl.col("w").is_in([0, 1, w]))
    return {
        "n_series_candidates": len(specs), "n_series_analysed": len(active),
        "n_changepoints": dict(cps.group_by("method").len().iter_rows()),
        "n_unaligned_changelog": un.height, "n_unaligned_documented": und.height,
        "weekday_adjusted": {"daily_series": len(daily), "original_cps": od.height,
                             "original_monday_share": mon_share(od), "adjusted_cps": adjdf.height,
                             "adjusted_monday_share": mon_share(adjdf),
                             "adjusted_matching_original_within_1": int(adjdf["matches_original_within_1"].sum()),
                             "original_kept_within_1": int(od["weekday_adjusted_match_within_1"].sum())},
        "alignment_l2_all": head.select("entry_set", "w", "coverage_frac", "n_changepoints", "aligned",
                                        "null1_p", "null2_p", "null1w_p", "null2w_p").to_dicts(),
        "runtime_s": runtime, "timings": timings,
        "outputs": [str(p) for p in (tables / "changepoints.csv", tables / "changepoint_alignment.csv",
                                     tables / "changepoint_series.csv", tables / "lexical_words.csv",
                                     tables / "changepoint_monitor_findings.parquet",
                                     tables / "changepoints_weekday_adjusted.csv", tables / "monday_ratio.csv",
                                     *fig_paths, qa)],
    }
