"""Weekday structure of the daily series: weekday-adjusted detection and the Monday ratio.

Weekday adjustment (a robustness check of the PELT l2 change points): for a daily (unbinned)
series on its detection scale, the local level is a centred rolling median over ROLL_POINTS points
(one working week), the weekday effect is the median over the whole series of the deviations from
that level on each weekday, and the adjusted series is the series minus the effect of each point's
weekday. Estimating the effects from deviations around a local level keeps level shifts out of
them. PELT l2 then runs on the adjusted series with the settings of detect.py (scaling by the MAD
of first differences, penalty beta * log(n), minimum segment MIN_SEGMENT_RUN_DAYS).

Monday ratio (a description, not a cause): for each family-level daily series and each calendar
week with all five weekdays observed, the value on Monday divided by the mean of Tuesday to Friday
(original units; weeks with a zero denominator are skipped). We report the mean and median over
weeks, split by the perma-computer-use regime (weeks ending before PERMA_CU_START against weeks
starting on or after it; the week of the rollout is left out) and by schedule regime (weeks whose
five days share one regime). Differences are tested with Mann-Whitney U (two regimes) and
Kruskal-Wallis (schedule regimes with at least MIN_WEEKS weeks).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from multiprocessing import get_context

import numpy as np
import pandas as pd
import polars as pl
from scipy import stats

from avsd.changepoint.align import weekdays
from avsd.changepoint.detect import BETA, MIN_SEGMENT_RUN_DAYS, noise_scale, pelt
from avsd.events.runs import schedule_regime

ROLL_POINTS = 5
PERMA_CU_START = date(2026, 3, 24)   # first CONSOLIDATE (schema_notes section 5)
MIN_WEEKS = 3
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def weekday_effects(x: np.ndarray, wd: np.ndarray, window: int = ROLL_POINTS) -> np.ndarray:
    """Per point, the weekday effect: median deviation from a centred rolling median, by weekday."""
    x = np.asarray(x, dtype=float)
    level = pd.Series(x).rolling(window, center=True, min_periods=max(2, window // 2 + 1)).median()
    dev = x - level.to_numpy()
    eff = {d: float(np.nanmedian(dev[wd == d])) if np.isfinite(dev[wd == d]).any() else 0.0
           for d in np.unique(wd)}
    return np.array([eff[d] for d in wd])


def adjust(x: np.ndarray, wd: np.ndarray) -> np.ndarray:
    """Series minus the weekday effect of each point."""
    return np.asarray(x, dtype=float) - weekday_effects(x, wd)


def detect_adjusted(series_id: str, x: np.ndarray, wd: np.ndarray, beta: float = BETA) -> tuple[str, list[int]]:
    """PELT l2 change points of the weekday-adjusted series (indices of new segments)."""
    xa = adjust(x, wd)
    scale = noise_scale(xa)
    if not scale > 0 or len(xa) < 2 * MIN_SEGMENT_RUN_DAYS + 1:
        return series_id, []
    z = (xa - np.median(xa)) / scale
    return series_id, pelt(z, "l2", beta * math.log(len(z)), MIN_SEGMENT_RUN_DAYS)


def _task(args: tuple) -> tuple[str, list[int]]:
    return detect_adjusted(*args)


def detect_all_adjusted(series: dict[str, tuple[np.ndarray, np.ndarray]], n_workers: int) -> dict[str, list[int]]:
    """series_id -> (values on the detection scale, weekdays) for daily series; returns change points."""
    tasks = [(sid, x, wd) for sid, (x, wd) in series.items()]
    if n_workers > 1:
        with ProcessPoolExecutor(n_workers, mp_context=get_context("fork")) as ex:
            return dict(ex.map(_task, tasks, chunksize=4))
    return dict(_task(t) for t in tasks)


def _test(groups: list[np.ndarray]) -> float | None:
    groups = [g for g in groups if len(g) >= MIN_WEEKS]
    if len(groups) < 2:
        return None
    try:
        if len(groups) == 2:
            return float(stats.mannwhitneyu(groups[0], groups[1], alternative="two-sided").pvalue)
        return float(stats.kruskal(*groups).pvalue)
    except ValueError:  # all values identical
        return None


def monday_ratios(values: pl.DataFrame, days: pl.DataFrame) -> pl.DataFrame:
    """Monday / mean(Tuesday..Friday) per week for each series in `values` (series_id, run_day, value)."""
    d = days.select("run_day", "date")
    v = (values.join(d, on="run_day", how="inner")
         .with_columns(pl.col("date").dt.weekday().alias("wd"),
                       pl.col("date").dt.truncate("1w").alias("week"),
                       schedule_regime(pl.col("date")).cast(pl.String).alias("regime")))
    rows = []
    for (sid,), g in v.group_by(["series_id"], maintain_order=True):
        wk = (g.filter(pl.col("wd") <= 5).group_by("week").agg(
            pl.col("value").filter(pl.col("wd") == 1).first().alias("mon"),
            pl.col("value").filter(pl.col("wd").is_between(2, 5)).mean().alias("rest"),
            pl.col("wd").n_unique().alias("n_wd"),
            pl.col("regime").n_unique().alias("n_regime"),
            pl.col("regime").first().alias("regime"),
            pl.col("date").max().alias("last"))
            .filter((pl.col("n_wd") == 5) & (pl.col("rest") > 0))
            .with_columns((pl.col("mon") / pl.col("rest")).alias("ratio")))
        if wk.is_empty():
            continue
        r = wk["ratio"].to_numpy()
        pre = wk.filter(pl.col("last") < pl.lit(PERMA_CU_START))["ratio"].to_numpy()
        post = wk.filter(pl.col("week") >= pl.lit(PERMA_CU_START))["ratio"].to_numpy()
        reg = wk.filter(pl.col("n_regime") == 1)
        by_reg = {k: reg.filter(pl.col("regime") == k)["ratio"].to_numpy() for k in sorted(set(reg["regime"]))}
        row = {"series_id": sid, "n_weeks": len(r), "mean_ratio": float(r.mean()),
               "median_ratio": float(np.median(r)), "share_weeks_monday_higher": float(np.mean(r > 1)),
               "n_pre_cu": len(pre), "mean_pre_cu": float(pre.mean()) if len(pre) else None,
               "n_post_cu": len(post), "mean_post_cu": float(post.mean()) if len(post) else None,
               "p_pre_vs_post_cu": _test([pre, post])}
        for k, x in by_reg.items():
            row[f"mean_{k}"] = float(x.mean()) if len(x) else None
            row[f"n_{k}"] = len(x)
        row["p_schedule_regimes"] = _test(list(by_reg.values()))
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


def weekday_name(dates: list[date]) -> list[str]:
    """Weekday names of dates."""
    return [WEEKDAY_NAMES[int(i)] for i in weekdays(np.array(dates, dtype="datetime64[D]"))]
