"""Matched-truth recovery arms for a real window (docs/decisions.md, "Hawkes recovery metric and window
acceptance").

The truth is the window's own class fit (l1 = 0): its K, day lengths, exogenous events, per-agent
baselines, n and class kernel shapes. Arms change what the fit may get wrong:

    fit      the fit itself (the truth recovery_check uses)
    slow     self and other kernels: half of the 10-min weight moved to the 1-h component
    fast     self and other kernels: half of the 1-h weight moved to the 10-min component
    self05   excitation moved from other agents to self so that the expected self share rises by
             0.05 at an unchanged expected event count (fits are biased away from self)
    self10   the same with 0.10
    wclass   self and other kernel shapes set to the simulated grid's class means (synth.W_CLASS)

Each replicate simulates the arm with the window's exogenous events, day lengths and presence masks
(an absent agent has no events that day), refits it with fit() (class, l1 = 0, default starts) and
scores the shares against the realized parent labels: mae (all shares) and mae4 (SPEC four-way,
exogenous pooled). scripts/hawkes_matched_recovery.py runs
the arms with a nested recovery_check; avsd.hawkes.pipeline runs them for every final goal window.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import time

import numpy as np
from numba import njit

from avsd.hawkes.model import HawkesFit, HawkesSpec, Packed, _shares, fit, pack
from avsd.hawkes.simulate import label_shares, simulate
from avsd.hawkes.synth import W_CLASS
from avsd.hawkes.validate import n_pairs, pool_exogenous

ARMS = ("fit", "slow", "fast", "self05", "self10", "wclass")
CLASSES = ("self", "other", "human", "system")


@njit(cache=True)
def _expected_day(base, coef, dec, declag, lag, exo):
    """(baseline, exogenous, other, self) expected agent events of one day on a grid: base (steps, K)
    baseline events per step, coef (K, K + H, M) the kernel mass per step, exo (steps, H) counts."""
    steps, K = base.shape
    KH, M = coef.shape[1], coef.shape[2]
    hist = np.zeros((steps, KH))
    hist[:, K:] = exo
    R = np.zeros((KH, M))
    out = np.zeros(4)
    for k in range(steps):
        for i in range(K):
            row = base[k, i]
            out[0] += base[k, i]
            for j in range(KH):
                e = 0.0
                for m in range(M):
                    e += coef[i, j, m] * R[j, m]
                row += e
                if j >= K:
                    out[1] += e
                elif j == i:
                    out[3] += e
                else:
                    out[2] += e
            hist[k, i] = row
        for j in range(KH):
            for m in range(M):
                R[j, m] = dec[m] * R[j, m] + hist[k, j]
                if k >= lag:
                    R[j, m] -= declag[m] * hist[k - lag, j]
    return out


def expected_counts(mu: np.ndarray, alpha: np.ndarray, Ts, exo, spec: HawkesSpec, step: float = 30.0,
                    present=None) -> np.ndarray:
    """Expected (baseline, exogenous, other, self) agent events summed over agents and days, from the
    mean-intensity equation on a grid of `step` seconds. The kernel is discretized so that every
    parent still has n_ij expected children in (0, L]; exact up to the grid, with day edges, the real
    exogenous events, and rho >= 1 handled. present: per day, the (K,) presence mask (an absent
    agent has no baseline and no children that day); None means all present."""
    K, H = mu.shape[0], alpha.shape[1] - mu.shape[0]
    beta = spec.beta
    dec = np.exp(-beta * step)
    lag = round(spec.max_lag / step)
    coef = alpha * -np.expm1(-beta * step)
    pres = [None] * len(Ts) if present is None else list(present)
    out = np.zeros(4)
    for T, x, p in zip(Ts, exo, pres):
        steps = math.ceil(T / step)
        ex = np.zeros((steps, H))
        for h, t in enumerate(x):
            np.add.at(ex[:, h], np.minimum((np.asarray(t) / step).astype(int), steps - 1), 1.0)
        grid = np.arange(steps) * step
        b = spec.bins(np.minimum(grid, T), T)
        on = np.ones(K) if p is None else np.asarray(p, dtype=np.float64)
        base = np.ascontiguousarray((mu[:, b] * on[:, None] * np.minimum(step, T - grid)).T)
        out += _expected_day(base, np.ascontiguousarray(coef * on[:, None, None]), dec, dec ** lag, lag, ex)
    return out


def _bisect(f, lo: float, hi: float, iters: int = 30) -> float:
    """x in [lo, hi] with f(x) = 0 for f increasing, f(lo) <= 0 <= f(hi)."""
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def boost_self(mu, n, w_cell, Ts, exo, delta: float, spec: HawkesSpec, iters: int = 30,
               present=None) -> tuple[np.ndarray, float]:
    """n with the agent diagonal scaled by c >= 1 and the other agent cells by d <= 1, so that the
    expected self share rises by delta at an unchanged expected event count. Returns the new n and
    the rise achieved (less than delta when even d = 0 cannot absorb it)."""
    K = n.shape[0]
    diag = np.eye(K, dtype=bool)

    def counts(c, d):
        m = n.copy()
        m[:, :K] = np.where(diag, n[:, :K] * c, n[:, :K] * d)
        return expected_counts(mu, spec.alpha_from(m, w_cell), Ts, exo, spec, present=present), m

    e0 = counts(1.0, 1.0)[0]
    total0, share0 = e0.sum(), e0[3] / e0.sum()

    def d_for(c):
        return _bisect(lambda d: counts(c, d)[0].sum() - total0, 0.0, 1.0, iters)

    def share(c):
        e = counts(c, d_for(c))[0]
        return e[3] / e.sum()

    hi = 1.0
    while counts(hi, 0.0)[0].sum() < total0:
        hi *= 1.5
    c_max = _bisect(lambda c: counts(c, 0.0)[0].sum() - total0, 1.0, hi, iters)
    if share(c_max) < share0 + delta:
        c = c_max
    else:
        c = _bisect(lambda c: share(c) - share0 - delta, 1.0, c_max, iters)
    e, m = counts(c, d_for(c))
    return m, float(e[3] / e.sum() - share0)


def arm_truth(arm: str, f: HawkesFit, pk: Packed, iters: int = 30) -> tuple[np.ndarray, np.ndarray, float]:
    """(mu, alpha, achieved self-share rise) of an arm, from the class fit f of the window. The
    kernel-shape arms rescale mu so that the expected event count stays that of the fit."""
    if f.kernel_sharing != "class" or f.tie_exo or tuple(f.class_names) != CLASSES:
        raise ValueError("arms need an untied class fit with sources human and system")
    spec = f.spec
    n, w, mu = f.n.copy(), f.w.copy(), f.mu
    s, o = CLASSES.index("self"), CLASSES.index("other")
    Ts, exo, pres = pk.day_T.tolist(), pk.exo_times(), pk.present
    rise = 0.0
    if arm in ("slow", "fast", "wclass"):
        if arm == "wclass":
            for c in (s, o):
                w[c] = W_CLASS[CLASSES[c]]
        else:
            a, b = (1, 2) if arm == "slow" else (2, 1)      # move half of component a to b
            for c in (s, o):
                w[c, b] += 0.5 * w[c, a]
                w[c, a] *= 0.5
        alpha = spec.alpha_from(n, w[f.classes])
        target = expected_counts(mu, f.alpha, Ts, exo, spec, present=pres).sum()
        exo_only = expected_counts(0.0 * mu, alpha, Ts, exo, spec, present=pres).sum()   # linear in mu
        mu = mu * max((target - exo_only) / (expected_counts(mu, alpha, Ts, exo, spec, present=pres).sum()
                                             - exo_only), 0.05)
    elif arm in ("self05", "self10"):
        n, rise = boost_self(mu, n, w[f.classes], Ts, exo, 0.05 if arm == "self05" else 0.10, spec, iters,
                             present=pres)
    elif arm != "fit":
        raise ValueError(arm)
    return mu, spec.alpha_from(n, w[f.classes]), rise


def run_replicate(mu: np.ndarray, alpha: np.ndarray, Ts, exo, K: int, exo_names: tuple[str, ...],
                  spec: HawkesSpec, seed, present=None, caps: tuple[int, int] | None = None) -> dict:
    """Simulate one replicate of an arm (present: per day, the presence mask), refit it (class,
    l1 = 0, default starts) and score the shares. caps = (events, candidate pairs), from
    validate.explosion_caps: a replicate above either raises RuntimeError (an exploding arm)."""
    rng = np.random.default_rng(seed)
    days, labels = simulate(mu, alpha, Ts, exo, rng, spec, present=present,
                            max_events=None if caps is None else caps[0])
    if caps is not None and n_pairs(days, spec.max_lag) > caps[1]:
        raise RuntimeError("simulated replicate exceeds the candidate-pair cap; the arm explodes")
    pk = pack(days, K, spec, exo_names=exo_names)
    t0 = time.time()
    g = fit(pk, K, spec, kernel_sharing="class")
    true = np.array(list(label_shares(days, labels, K, exo_names).values()))
    got = _shares(pk, g.mu, g.alpha, np.ones(pk.n_days))
    err = got - true
    nb = g.n - spec.branching(alpha)
    diag = np.eye(K, dtype=bool)
    return {"mae": float(np.abs(err).mean()), "mae4": float(np.abs(pool_exogenous(err)).mean()),
            **{f"err_{s}": float(e) for s, e in zip(g.share_names, err)},
            **{f"true_{s}": float(v) for s, v in zip(g.share_names, true)},
            "n_self_bias": float(nb[:, :K][diag].mean()),
            "n_other_bias": float(nb[:, :K][~diag].mean()) if K > 1 else float("nan"),
            "rho": g.rho, "rho_truth": float(np.abs(np.linalg.eigvals(spec.branching(alpha)[:, :K])).max()),
            "converged": bool(g.converged), "n_violations": int(g.n_violations), "n_events": int(pk.tgt_ev.size),
            "secs": time.time() - t0}
