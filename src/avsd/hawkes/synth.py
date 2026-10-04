"""Simulated goal windows for the recovery experiments (scripts/hawkes_*.py) and tests.

A window has K agents, 5-10 run days of about 3.5 h, 2k-6k agent messages, a
human source and targeted system nudges. A nudge excites only the agent it
targets, so the truth has one system source per agent; the fitted model pools
them into one "system" column (as the real data must be fitted), a mild
misspecification shared by all fit variants.

The truths are a regime, not an estimate of the real windows: class kernel
shapes are drawn around W_CLASS, self shares come out at 0.23-0.39, rho_true at
0.65-0.85, and days are 3.2-3.8 h. Real fits differ on all of these (more self
excitation, other-agent kernels concentrated on the 1-min component, 8-h days
from 2026-06-29), so error levels measured on these truths do not transfer to
real windows; scripts/hawkes_matched_recovery.py calibrates per real window.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from avsd.hawkes.model import Day, HawkesSpec
from avsd.hawkes.simulate import simulate

SPEC = HawkesSpec()
H = 3600.0
EXO = ("human", "system")
# Class kernel weights over the 1 min, 10 min, 1 h components.
W_CLASS = {"self": (0.25, 0.45, 0.30), "other": (0.55, 0.35, 0.10),
           "human": (0.45, 0.40, 0.15), "system": (0.35, 0.45, 0.20)}


@dataclass
class Truth:
    K: int
    mu: np.ndarray        # (K, n_bins)
    alpha: np.ndarray     # (K, K + 1 + K, M): agents, human, one targeted system source per agent
    n_fit: np.ndarray     # (K, K + 2) branching matrix in the fitted (pooled) parametrization
    w_class: np.ndarray   # (4, M) class means: self, other, human, system
    rates: tuple[float, float]  # human events per hour, nudges per hour
    meta: dict = field(default_factory=dict)


def _scale_offdiag(diag: np.ndarray, off: np.ndarray, rho: float) -> np.ndarray:
    """D + c O with spectral radius rho (bisection on c >= 0)."""
    def r(c):
        return np.abs(np.linalg.eigvals(np.diag(diag) + c * off)).max()
    if r(0.0) >= rho or not off.any():
        return np.diag(diag) + 0.0 * off
    lo, hi = 0.0, 1.0
    while r(hi) < rho:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if r(mid) < rho else (lo, mid)
    return np.diag(diag) + lo * off


def make_truth(K: int, variant: str, rng: np.random.Generator, n_events: float, T_total: float,
               kappa: float | None = None, tilt: float | None = None,
               w_class_means: dict[str, tuple[float, float, float]] | None = None) -> Truth:
    """variant "sparse" (2 strong sources per agent) or "dense" (about half of all
    pairs, gamma weights). kappa=None shares kernel shapes by class; a finite
    kappa draws each cell's shape from Dirichlet(kappa * class mean). tilt=s
    gives every agent its own latency: all kernels into agent i are tilted by
    exp(g_i (m - 1)) over the components m = 0, 1, 2, g_i ~ N(0, s^2) (a
    row-structured misspecification). kappa and tilt draw from separate streams,
    so all other parts of the window are the same with and without them; the
    realized events still differ, because delays change. w_class_means replaces
    W_CLASS."""
    M = SPEC.M
    means = W_CLASS if w_class_means is None else w_class_means
    diag = rng.uniform(0.2, 0.5, K)
    off = np.zeros((K, K))
    if variant == "sparse":
        for i in range(K):
            js = rng.choice([j for j in range(K) if j != i], 2, replace=False)
            off[i, js] = rng.uniform(0.5, 1.0, 2)
    elif variant == "dense":
        off = rng.gamma(0.5, 1.0, (K, K)) * (rng.uniform(size=(K, K)) < 0.5)
        np.fill_diagonal(off, 0.0)
    else:
        raise ValueError(variant)
    rho = rng.uniform(0.65, 0.85)
    n_aa = _scale_offdiag(diag, off, rho)
    n_h = rng.uniform(0.1, 0.4, K)
    n_s = rng.uniform(0.5, 1.0, K)                       # response of the targeted agent
    rate_h = rng.uniform(0.5, 3.0) / H                    # human messages per second
    rate_s = rng.uniform(3, 10) / (3.5 * H)               # a few nudges per run day
    w_class = np.array([rng.dirichlet(30 * np.array(means[c]))
                        for c in ("self", "other", "human", "system")])
    # Separate streams for the per-cell shapes and the latency tilt.
    words = rng.integers(0, 2**32, 4)
    rng_shape = np.random.default_rng(words)
    rng_tilt = np.random.default_rng([*words, 1])

    # Full simulation parametrization: agents, human, K targeted system sources.
    n_full = np.hstack([n_aa, n_h[:, None], np.diag(n_s)])
    cls = np.ones((K, 2 * K + 1), np.int64)
    cls[np.arange(K), np.arange(K)] = 0
    cls[:, K] = 2
    cls[:, K + 1:] = 3
    w_cell = w_class[cls]
    if kappa is not None:
        w_cell = np.apply_along_axis(lambda w: rng_shape.dirichlet(kappa * w), -1, w_cell)
    if tilt is not None:
        g = rng_tilt.normal(0.0, tilt, K)
        w_cell = w_cell * np.exp(g[:, None, None] * (np.arange(M) - 1.0))
        w_cell /= w_cell.sum(-1, keepdims=True)
    alpha = SPEC.alpha_from(n_full, w_cell)

    # Baseline: activity heterogeneity and a start-of-day burst, scaled to n_events.
    act = rng.lognormal(0.0, 0.5, K)
    profile = np.ones(SPEC.n_bins)
    profile[0] = 1.5
    exo_drive = n_h * rate_h + n_s * rate_s / K
    inv = np.linalg.inv(np.eye(K) - n_aa)
    target = n_events / T_total                          # agent events per second
    exo_part = (inv @ exo_drive).sum()
    base = max(target - exo_part, 0.2 * target) / (inv @ act).sum()
    mu = (base * act)[:, None] * profile[None, :] / profile[:4].mean()
    n_fit = np.hstack([n_aa, n_h[:, None], (n_s / K)[:, None]])
    return Truth(K, mu, alpha, n_fit, w_class, (rate_h * H, rate_s * H),
                 {"variant": variant, "rho": float(rho), "kappa": kappa, "tilt": tilt})


def draw_exogenous(truth: Truth, D: int, rng: np.random.Generator) -> tuple[np.ndarray, list[tuple]]:
    """Day lengths and, per day, the human events and one nudge array per agent."""
    K = truth.K
    Ts = rng.uniform(3.2 * H, 3.8 * H, D)
    exo = []
    for T in Ts:
        hum = np.sort(rng.uniform(0, T, rng.poisson(truth.rates[0] / H * T)))
        nud = np.sort(rng.uniform(0, T, rng.poisson(truth.rates[1] / H * T)))
        tgt = rng.integers(0, K, nud.size)
        exo.append((hum, *(nud[tgt == i] for i in range(K))))
    return Ts, exo


def pool_window(K: int, days: list[Day], labels: list[np.ndarray]) -> tuple[list[Day], list[np.ndarray]]:
    """Days simulated with K targeted system sources -> the fitted parametrization
    (human, all nudges pooled) and pooled parent labels."""
    out_days, out_lab = [], []
    for d, lab in zip(days, labels):
        nudges = np.sort(np.concatenate(d.exo_times[1:]))
        out_days.append(Day(d.T, d.agent_times, d.agent_dims, exo_times=(d.exo_times[0], nudges)))
        out_lab.append(np.where(lab > K, K + 1, lab))    # all system sources -> K + 1
    return out_days, out_lab


def simulate_window(truth: Truth, D: int, rng: np.random.Generator) -> tuple[list[Day], list[np.ndarray]]:
    """Days in the fitted parametrization (human, system) and pooled parent labels."""
    Ts, exo = draw_exogenous(truth, D, rng)
    days, labels = simulate(truth.mu, truth.alpha, list(Ts), exo, rng, SPEC)
    return pool_window(truth.K, days, labels)


def _window_start(K: int, variant: str, seed, kappa, tilt, w_class_means):
    rng = np.random.default_rng(seed)
    D = int(rng.integers(5, 11))
    n_target = float(rng.uniform(2000, 6000))
    # Days start without history, so realized counts are about 80% of the stationary rate.
    truth = make_truth(K, variant, rng, n_target / 0.8, D * 3.5 * H, kappa, tilt, w_class_means)
    return rng, truth, D, n_target


def realistic_window(K: int, variant: str, seed, kappa: float | None = None, tilt: float | None = None,
                     w_class_means: dict[str, tuple[float, float, float]] | None = None):
    """One simulated window: (truth, days, labels, D, n_target)."""
    rng, truth, D, n_target = _window_start(K, variant, seed, kappa, tilt, w_class_means)
    days, labels = simulate_window(truth, D, rng)
    return truth, days, labels, D, n_target


def window_exogenous(K: int, variant: str, seed, kappa: float | None = None, tilt: float | None = None,
                     w_class_means: dict[str, tuple[float, float, float]] | None = None):
    """(truth, day lengths, per-day exogenous events with one nudge array per agent) of
    realistic_window(K, variant, seed, ...): the inputs to simulate the window again at
    its true parameters."""
    rng, truth, D, _ = _window_start(K, variant, seed, kappa, tilt, w_class_means)
    Ts, exo = draw_exogenous(truth, D, rng)
    return truth, Ts, exo
