"""Scores over time and the blog's speedup and scaling exponent (SPEC 8.2 D1).

Coverage is the share of steps finished. The best score is the highest finished value on the
task's scale. Both are averaged over runs as step functions: run r rises by w at each of its event
times, and the average rises by w / R. A swarm's speedup at level x is g_x = t_x(one agent) /
t_x(swarm), where t_x is the first time the averaged score reaches x, and the scaling exponent is
lambda = ln g_50 / ln N.

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Curve = tuple[np.ndarray, np.ndarray]   # sorted event times, running average after each event


def mean_curve(times: Sequence[np.ndarray], weights: Sequence[np.ndarray]) -> Curve:
    """Average of R step functions; run r rises by weights[r][k] at times[r][k]."""
    t = np.concatenate([np.asarray(x, dtype=float) for x in times])
    w = np.concatenate([np.asarray(x, dtype=float) for x in weights]) / len(times)
    order = np.argsort(t, kind="stable")
    return t[order], np.cumsum(w[order])


def coverage_curve(finish_times: Sequence[np.ndarray]) -> Curve:
    """Average coverage of runs given each run's step finish times."""
    return mean_curve(finish_times, [np.full(len(f), 1.0 / len(f)) for f in finish_times])


def first_reach(curve: Curve, level: float, t_max: float = 1.0) -> float:
    """First time the averaged score reaches `level` (NaN if not by `t_max`)."""
    t, cum = curve
    k = int(np.searchsorted(cum, level - 1e-9, side="left"))
    if k >= len(t) or t[k] > t_max * (1 + 1e-12):
        return math.nan
    return float(t[k])


def on_grid(curve: Curve, grid: np.ndarray) -> np.ndarray:
    """The averaged score at each grid time (right-continuous)."""
    t, cum = curve
    k = np.searchsorted(t, grid, side="right")
    return np.where(k > 0, cum[np.maximum(k - 1, 0)], 0.0)


def speedup(t_ref: float, t: float) -> float:
    return t_ref / t if t > 0 else math.nan


def scaling_exponent(g: float, n: int) -> float:
    """lambda = ln g / ln N."""
    return math.log(g) / math.log(n) if n > 1 and g > 0 else math.nan
