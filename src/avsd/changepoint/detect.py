"""PELT change points, penalties and block-bootstrap location intervals (SPEC 7.2).

Each series is analysed on its detection scale (series.Metric.transform), centred at its median and
divided by a robust noise scale, sigma = MAD(first differences) / (0.6745 sqrt 2), which mean
shifts barely affect. On that standardised scale PELT (ruptures) runs with two costs:

- l2 (mean shifts) with the BIC-type penalty beta * log(n). A change point adds a level and a
  location, so beta = 2 is the BIC penalty for Gaussian noise of unit variance.
- rbf (changes in distribution; Gaussian kernel with the median-heuristic bandwidth, as in
  ruptures) with beta * v * log(n), where v = E[1 - k(x, x')] is the within-segment variance in
  the kernel feature space. v is estimated from neighbouring points (10% trimmed mean, so that
  jumps do not inflate it), as sigma is for l2.

Both costs are re-implemented with cumulative sums (`CostL2Cum`, `CostRbfCum`), so a segment cost
takes O(1) time. They equal ruptures' CostL2 and CostRbf (tests) and are passed to `ruptures.Pelt`
as custom costs. Segments are at least MIN_SEGMENT_RUN_DAYS run days long. The penalty sweep re-runs
both costs at every beta in BETAS.

Location intervals come from a residual moving-block bootstrap: the residuals around the fitted
segment means are resampled in blocks of `block_len_run_days`, added back to the means, and PELT
re-runs with the same penalty. Each original change point takes the nearest bootstrap change point
inside its basin (half-way to its neighbours); the 2.5 and 97.5 percentiles of these positions are
the interval, and the share of replicates with a match is the detection rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import accumulate

import numpy as np
import ruptures as rpt
from ruptures.base import BaseCost
from ruptures.exceptions import NotEnoughPoints
from scipy.spatial.distance import pdist, squareform

from avsd.changepoint.bocpd import bocpd_changepoints

BETA = 2.0
BETAS = (0.5, 1.0, 2.0, 4.0, 8.0)
MIN_SEGMENT_RUN_DAYS = 10
N_BOOT = 200
MIN_BOOT_HITS = 10            # replicates with a match needed for an interval
RBF_TRIM = 0.10
BOCPD_RUN_DAYS = 100.0        # expected segment length of the BOCPD hazard, in run days
_MAD_NORMAL = 0.6744897501960817


class CostL2Cum(BaseCost):
    """Squared deviation from the segment mean (ruptures' CostL2), from cumulative sums."""

    model = "l2_cum"

    def __init__(self) -> None:
        self.min_size = 1
        self._s1: list[float] = []
        self._s2: list[float] = []

    def fit(self, signal: np.ndarray) -> "CostL2Cum":
        x = np.asarray(signal, dtype=float)
        if x.ndim != 1:
            raise ValueError("CostL2Cum takes a 1-D signal")
        self.signal = x
        self._s1 = [0.0, *accumulate(x.tolist())]
        self._s2 = [0.0, *accumulate((x * x).tolist())]
        return self

    def error(self, start: int, end: int) -> float:
        n = end - start
        if n < self.min_size:
            raise NotEnoughPoints
        s1 = self._s1[end] - self._s1[start]
        return self._s2[end] - self._s2[start] - s1 * s1 / n


def rbf_gram(x: np.ndarray, gamma: float | None = None) -> tuple[np.ndarray, float]:
    """Gaussian Gram matrix and bandwidth exactly as ruptures' CostRbf builds them."""
    x = np.asarray(x, dtype=float).reshape(len(x), -1)
    k = pdist(x, metric="sqeuclidean")
    if gamma is None:
        gamma = 1.0
        med = float(np.median(k)) if k.size else 0.0
        if med != 0:
            gamma = 1.0 / med
    k = np.clip(k * gamma, 1e-2, 1e2)
    return np.exp(squareform(-k)), float(gamma)


class CostRbfCum(BaseCost):
    """Kernel cost (ruptures' CostRbf), from a 2-D cumulative sum of the Gram matrix."""

    model = "rbf_cum"

    def __init__(self, gamma: float | None = None) -> None:
        self.min_size = 1
        self.gamma = gamma
        self._c: list[list[float]] = []

    def fit(self, signal: np.ndarray) -> "CostRbfCum":
        x = np.asarray(signal, dtype=float)
        self.signal = x.reshape(len(x), -1)
        gram, self.gamma = rbf_gram(self.signal, self.gamma)
        c = np.zeros((len(x) + 1, len(x) + 1))
        c[1:, 1:] = gram.cumsum(0).cumsum(1)
        self._c = c.tolist()
        return self

    def error(self, start: int, end: int) -> float:
        n = end - start
        if n < self.min_size:
            raise NotEnoughPoints
        c = self._c
        block = c[end][end] - c[start][end] - c[end][start] + c[start][start]
        return n - block / n  # the Gram diagonal is 1


def pelt(z: np.ndarray, cost: str, pen: float, min_size: int, gamma: float | None = None) -> list[int]:
    """PELT change points of `z`: indices of the first point of each new segment."""
    if len(z) < 2 * min_size:
        return []
    c = CostL2Cum() if cost == "l2" else CostRbfCum(gamma)
    return rpt.Pelt(custom_cost=c, min_size=min_size, jump=1).fit(np.asarray(z, float)).predict(pen=pen)[:-1]


def noise_scale(x: np.ndarray) -> float:
    """Noise SD from first differences: MAD / (0.6745 sqrt 2), or their SD / sqrt 2 if the MAD is 0."""
    d = np.diff(np.asarray(x, dtype=float))
    if d.size == 0:
        return 0.0
    s = float(np.median(np.abs(d - np.median(d)))) / _MAD_NORMAL / math.sqrt(2)
    if s <= 1e-12:
        s = float(np.std(d)) / math.sqrt(2)
    return s


def rbf_scale(z: np.ndarray, gamma: float) -> float:
    """Feature-space variance v = E[1 - k(x, x')] from neighbouring points (trimmed mean)."""
    d2 = np.diff(np.asarray(z, dtype=float)) ** 2
    v = np.sort(1.0 - np.exp(-np.clip(gamma * d2, 1e-2, 1e2)))
    keep = max(1, int(math.ceil(v.size * (1.0 - RBF_TRIM))))
    return float(v[:keep].mean())


def segment_means(z: np.ndarray, cps: list[int]) -> np.ndarray:
    """Each point replaced by the mean of its segment."""
    out = np.empty(len(z))
    bounds = [0, *cps, len(z)]
    for a, b in zip(bounds[:-1], bounds[1:]):
        out[a:b] = z[a:b].mean()
    return out


def bootstrap_locations(
    z: np.ndarray, cps: list[int], pen: float, min_size: int, block: int, n_boot: int,
    rng: np.random.Generator,
) -> list[tuple[int | None, int | None, float]]:
    """(lo, hi, detection rate) per change point from a residual moving-block bootstrap (l2)."""
    if not cps:
        return []
    n = len(z)
    fitted = segment_means(z, cps)
    resid = z - fitted
    block = max(1, min(block, n))
    n_blocks = math.ceil(n / block)
    bounds = [0, *cps, n]
    basins = [((bounds[j] + cps[j]) / 2.0, (cps[j] + bounds[j + 2]) / 2.0) for j in range(len(cps))]
    hits: list[list[int]] = [[] for _ in cps]
    offsets = np.arange(block)
    for _ in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        e = resid[(starts[:, None] + offsets).ravel()[:n]]
        bk = np.asarray(pelt(fitted + e, "l2", pen, min_size), dtype=int)
        if bk.size == 0:
            continue
        for j, c in enumerate(cps):
            lo, hi = basins[j]
            cand = bk[(bk >= lo) & (bk < hi)]
            if cand.size:
                hits[j].append(int(cand[np.argmin(np.abs(cand - c))]))
    out = []
    for h in hits:
        if len(h) >= MIN_BOOT_HITS:
            lo, hi = np.percentile(h, [2.5, 97.5])
            out.append((int(math.floor(lo)), int(math.ceil(hi)), len(h) / n_boot))
        else:
            out.append((None, None, len(h) / n_boot))
    return out


@dataclass
class SeriesDetection:
    """Detection output for one series. Change points are indices into the series' points."""

    series_id: str
    n: int
    center: float = 0.0
    scale: float = 0.0
    gamma: float = 0.0
    rbf_v: float = 0.0
    pen: dict[str, float] = field(default_factory=dict)
    cps: dict[str, list[int]] = field(default_factory=dict)         # method -> change points
    sweep: dict[str, list[int]] = field(default_factory=dict)       # f"{cost}@{beta}" -> change points
    boot: list[tuple[int | None, int | None, float]] = field(default_factory=list)  # per l2 change point
    bocpd: list[int] = field(default_factory=list)
    bocpd_support: list[float] = field(default_factory=list)
    skipped: str | None = None

    def z(self, x: np.ndarray) -> np.ndarray:
        return (np.asarray(x, dtype=float) - self.center) / self.scale


def detect_series(
    series_id: str, x: np.ndarray, resolution: int, block_len_run_days: int, seed: int | tuple[int, ...],
    beta: float = BETA, betas: tuple[float, ...] = BETAS, n_boot: int = N_BOOT,
) -> SeriesDetection:
    """PELT (l2, rbf) with the penalty sweep, the l2 bootstrap intervals and BOCPD for one series.

    `x` is the series on its detection scale, one value per point; `resolution` is the number of
    run days per point (1 or the bin width).
    """
    x = np.asarray(x, dtype=float)
    det = SeriesDetection(series_id, len(x))
    min_size = max(2, math.ceil(MIN_SEGMENT_RUN_DAYS / resolution))
    if len(x) < 2 * min_size + 1:
        det.skipped = "too short"
        return det
    det.center, det.scale = float(np.median(x)), noise_scale(x)
    if not det.scale > 0:
        det.skipped = "constant"
        return det
    z = det.z(x)
    n = len(z)
    _, det.gamma = rbf_gram(z)
    det.rbf_v = rbf_scale(z, det.gamma)
    unit = {"l2": 1.0, "rbf": det.rbf_v}
    for cost in ("l2", "rbf"):
        for b in sorted({*betas, beta, 2 * beta, 4 * beta}):
            det.sweep[f"{cost}@{b:g}"] = pelt(z, cost, b * unit[cost] * math.log(n), min_size, det.gamma)
        det.pen[cost] = beta * unit[cost] * math.log(n)
        det.cps[cost] = det.sweep[f"{cost}@{beta:g}"]
    rng = np.random.default_rng(seed)
    block = max(1, math.ceil(block_len_run_days / resolution))
    det.boot = bootstrap_locations(z, det.cps["l2"], det.pen["l2"], min_size, block, n_boot, rng)
    hazard = min(0.5, resolution / BOCPD_RUN_DAYS)
    det.bocpd, det.bocpd_support = bocpd_changepoints(z, hazard, min_size=min_size)
    return det
