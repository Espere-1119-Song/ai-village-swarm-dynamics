"""L1 selection by held-out run days, and the SPEC 5.6-1 recovery check.

Fits of small windows (K of 7-25 agents over 5 run days of 3-8 h, 2k-6k
messages) spread mass over the K(K+H) non-negative n_ij and credit part of
each agent's self-excitation to other agents. Errors are reported on the
SPEC 5.5 four-way decomposition (Recovery.mae4: baseline, exogenous sources
pooled, other agents, self), which the 0.05 bar of SPEC 5.6-1 was set for,
next to the self and other errors. The five-share mae is about 4/5 of mae4
because it averages in the near-empty system share, estimated almost exactly.

How large the error is depends on the regime; no single number applies:
- Simulated grid (avsd.hawkes.synth: class kernel means W_CLASS, self shares
  0.23-0.39, K = 7-20, 3.5-h days; scripts/hawkes_recovery_grid.py, 160
  windows): kernel_sharing="class" gives mae4 0.054 / 0.056 / 0.059 / 0.069 at
  K = 7 / 10 / 13 / 20 (mae 0.044-0.057), about half the per-cell model's
  (SPEC 5.2) and lower in every window, but above 0.05 at every K, with self
  shares 0.08-0.09 low and other-agent shares 0.07-0.12 high.
- Truths matched to the real windows (scripts/hawkes_matched_recovery.py:
  each window's own fit, events, days and K): mae4 0.029 / 0.033 / 0.036 for
  R0 / R2 / R3 (K = 7 / 13 / 25) at the fitted truth, at most 0.044 with 0.05
  or 0.10 more self excitation, but 0.041-0.061 when the self and other
  kernels are slower than fitted and up to 0.053 with the grid's shapes; self
  shares are 0.03-0.11 low. K = 25 is not worse than K = 7 there.

select_l1 picks the L1 strength (SPEC 5.3) by the log-likelihood of held-out
run days. Over all cells it does not improve class fits; over cross-agent
cells only (l1_scope="cross") it removes the self-to-other shift but moves
shares to the baseline and lowers rho, so it is not better on average either.

recovery_check runs the SPEC 5.6-1 protocol for one window: simulate from the
window's fit with its real exogenous events and day lengths, refit each
replicate the same way, and compare the shares with the realized ones. It is
calibrated only where the fit is close to the truth. On the grid it simulates
from fits whose self excitation is too low, so its mae4 (0.035-0.044) is
0.010-0.034 below the actual error, and a pass carries no information: it
flagged 13 of the 100 windows above the bar and 16 of the 60 below it (the
same protocol run at the true parameters is calibrated). On matched truths it
is within 0.02 of the actual error. A pass is therefore not an acceptance
gate by itself: report mae4, the biases and n_bias, together with the
window's matched-truth arms.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from avsd.hawkes.model import (
    SHARES, Day, HawkesFit, HawkesSpec, Packed, _check_fit, _fit_pack, _loglik, _packed, _shares,
    fit as fit_hawkes, pack,
)
from avsd.hawkes.simulate import label_shares, simulate

L1_GRID = (0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)


@dataclass
class L1Selection:
    l1: float
    grid: np.ndarray    # (G,)
    score: np.ndarray   # (G,) held-out log-likelihood summed over folds
    folds: np.ndarray   # (D,) fold of each day


def select_l1(days: list[Day] | Packed, K: int, spec: HawkesSpec | None = None,
              grid: tuple[float, ...] = L1_GRID, n_folds: int = 5, *,
              exo_names: tuple[str, ...] | None = None, **fit_kw) -> L1Selection:
    """Choose l1 from `grid` by K-fold cross-validation over run days. fit_kw
    goes to the fits (e.g. kernel_sharing, l1_scope, starts).

    Day d is in fold d % n_folds (at most one fold per day). Each fold's
    training fit is scored by the log-likelihood of its held-out days; the
    baseline is floored at 1e-3 of the training mean rate so that an event in a
    bin or dimension unseen in training does not score -inf. The fit at the
    smallest l1 runs from fit()'s starts; fits along the rest of the grid are
    warm-started from the previous l1."""
    pk = _packed(days, K, spec, exo_names)
    starts = fit_kw.pop("starts", None)
    D = pk.n_days
    if D < 2:
        raise ValueError("cross-validation needs at least 2 run days")
    folds = np.arange(D) % min(n_folds, D)
    grid = np.asarray(sorted(grid), dtype=np.float64)
    score = np.zeros(grid.size)
    for k in np.unique(folds):
        train = (folds != k).astype(np.float64)
        test = 1.0 - train
        present_time = float((train[:, None] * pk.present * pk.day_T[:, None]).sum())
        floor = 1e-3 * pk.counts(train).sum() / max(present_time, 1e-300)
        init = None
        for g, l1 in enumerate(grid):
            f = _fit_pack(pk, train, l1=l1, init=init, starts=starts if init is None else None, **fit_kw)
            init = (f.mu, f.alpha)
            score[g] += _loglik(pk, np.maximum(f.mu, floor), f.alpha, test)
    return L1Selection(float(grid[np.argmax(score)]), grid, score, folds)


SHARES4 = ("baseline", "exogenous", "other_agents", "self")
# A simulated replicate counts as exploded (a supercritical cascade, unlike the data) when it has more than
# EXPLODE times the window's agent events or EXPLODE_PAIRS times its candidate parent pairs.
EXPLODE = 10
EXPLODE_PAIRS = 50


def n_pairs(days: list[Day], max_lag: float) -> int:
    """Candidate parent pairs of the days' agent events (pack's rule, 0 < dt <= L), without packing."""
    tot = 0
    for d in days:
        s = np.sort(np.concatenate([np.asarray(d.agent_times, dtype=np.float64), *d.exo_times]))
        t = np.asarray(d.agent_times, dtype=np.float64)
        tot += int((np.searchsorted(s, t, "left") - np.searchsorted(s, t - max_lag, "left")).sum())
    return tot


def explosion_caps(pk: Packed) -> tuple[int, int]:
    """(events, pairs) above which a replicate simulated for this window counts as exploded."""
    return max(EXPLODE * pk.tgt_ev.size, 1000), max(EXPLODE_PAIRS * pk.par_ev.size, 100_000)


def pool_exogenous(x: np.ndarray) -> np.ndarray:
    """(..., 3 + H) shares or share errors in share_names order -> (..., 4) SPEC 5.5
    four-way decomposition (SHARES4): baseline, all exogenous sources pooled,
    other agents, self."""
    x = np.asarray(x, dtype=np.float64)
    return np.concatenate([x[..., :1], x[..., 1:-2].sum(-1, keepdims=True), x[..., -2:]], -1)


@dataclass
class Recovery:
    true_shares: np.ndarray  # (R, 3 + H) realized shares from the simulated parent labels
    shares: np.ndarray       # (R, 3 + H) shares of the refit
    rho: np.ndarray          # (R,)
    n: np.ndarray            # (R, K, K + H)
    converged: np.ndarray    # (R,)
    n_events: np.ndarray     # (R,)
    names: tuple[str, ...] = SHARES
    n_true: np.ndarray | None = None  # (K, K + H) branching matrix the replicates were simulated from
    n_violations: np.ndarray | None = None  # (R,) objective decreases of each refit

    @property
    def exploded(self) -> np.ndarray:
        """(R,) replicates whose simulation exceeded the explosion caps (explosion_caps: events or candidate
        pairs; no refit, their shares, n and rho are nan)."""
        return self.n_events < 0

    @property
    def mae(self) -> np.ndarray:
        """(R,) mean absolute error over the 3 + H shares of each replicate (nan if exploded)."""
        return np.abs(self.shares - self.true_shares).mean(1)

    @property
    def mae4(self) -> np.ndarray:
        """(R,) mean absolute error of the SPEC 5.5 four-way decomposition (exogenous
        sources pooled), the decomposition the SPEC 5.6-1 bar of 0.05 was set for.
        With H = 2 the 5-share mae averages in a near-empty, well-estimated system
        share, which makes it about 4/5 of mae4. nan for exploded replicates."""
        return np.abs(pool_exogenous(self.shares - self.true_shares)).mean(1)

    @property
    def mae4_mean(self) -> float:
        """Mean mae4 over the replicates that did not explode."""
        x = self.mae4[~self.exploded]
        return float(x.mean()) if x.size else float("nan")

    @property
    def mae4_se(self) -> float:
        """Monte Carlo standard error of mae4_mean."""
        x = self.mae4[~self.exploded]
        return float(x.std(ddof=1) / np.sqrt(x.size)) if x.size > 1 else float("nan")

    def failed(self, bar: float) -> bool:
        """The SPEC 5.6-1 check fails: a replicate exploded (the fit does not generate data of the window's
        size), or the mean mae4 reaches the bar."""
        return bool(self.exploded.any()) or not self.mae4_mean < bar

    @property
    def bias(self) -> dict[str, float]:
        """Mean refit share minus realized share, per share (SPEC 5.6-1), over replicates that did not explode."""
        ok = ~self.exploded
        if not ok.any():
            return dict.fromkeys(self.names, float("nan"))
        return dict(zip(self.names, (self.shares[ok] - self.true_shares[ok]).mean(0).tolist()))

    @property
    def n_bias(self) -> np.ndarray:
        """(K, K + H) mean refit n minus the simulating n (SPEC 5.6-1)."""
        if self.n_true is None:
            raise ValueError("n_true was not recorded")
        ok = ~self.exploded
        return self.n[ok].mean(0) - self.n_true if ok.any() else np.full(self.n_true.shape, np.nan)

    @classmethod
    def concat(cls, parts: list[Recovery]) -> Recovery:
        """Join replicate chunks (recovery_check with start = 0, R1, ...) in the given order."""
        if not parts or len({p.names for p in parts}) > 1:
            raise ValueError("need at least one part, all with the same share names")
        arrays = ("true_shares", "shares", "rho", "n", "converged", "n_events")
        viol = None if any(p.n_violations is None for p in parts) else np.concatenate([p.n_violations for p in parts])
        return cls(*(np.concatenate([getattr(p, a) for p in parts]) for a in arrays), names=parts[0].names,
                   n_true=parts[0].n_true, n_violations=viol)

    def n_bias_summary(self) -> dict[str, float]:
        """Mean bias and mean absolute bias of n by cell type: self (diagonal), other
        (agent j != i) and exogenous columns."""
        b = self.n_bias
        K = b.shape[0]
        diag = np.eye(K, dtype=bool)
        parts = {"self": b[:, :K][diag], "other": b[:, :K][~diag], "exogenous": b[:, K:].ravel()}
        return {f"n_{k}_{s}": float(f(v)) if v.size else float("nan") for k, v in parts.items()
                for s, f in (("bias", np.mean), ("abs_bias", lambda z: np.abs(z).mean()))}


def recovery_check(days: list[Day] | Packed, fit: HawkesFit, n_rep: int = 20, seed: int = 20261003,
                   refit: Callable[[Packed], HawkesFit] | None = None, start: int = 0) -> Recovery:
    """SPEC 5.6-1 for one window. Replicate r = start, ..., start + n_rep - 1
    simulates from `fit` with the window's exogenous events, day lengths and
    presence masks (rng = default_rng([seed, r]), so chunks can run in parallel
    and be joined with Recovery.concat). A replicate with more than EXPLODE times
    the window's agent events, or EXPLODE_PAIRS times its candidate parent pairs,
    is recorded as exploded without a refit (n_events -1, shares nan): a
    supercritical fit can generate cascades far beyond the data.
    Others are refit with `refit`, by default fit() at the
    same l1, l1_scope, kernel_sharing, tie_exo and starts. Pass a refit that reruns
    select_l1 to check the whole procedure. Report mae4 (the SPEC
    decomposition), the self and other biases and n_bias next to mae; see the
    module docstring for what a pass does and does not show."""
    pk = _packed(days, fit.K, fit.spec, fit.exo_names)
    _check_fit(pk, fit)
    K, H, spec = fit.K, fit.H, fit.spec
    starts = None if fit.start == "init" else fit.starts
    refit = refit or (lambda p: fit_hawkes(p, K, l1=fit.l1, kernel_sharing=fit.kernel_sharing,
                                           l1_scope=fit.l1_scope, starts=starts, tie_exo=fit.tie_exo))
    T, exo = pk.day_T.tolist(), pk.exo_times()
    S = 3 + H
    out = Recovery(np.empty((n_rep, S)), np.empty((n_rep, S)), np.empty(n_rep), np.empty((n_rep, K, K + H)),
                   np.empty(n_rep, bool), np.empty(n_rep, np.int64), fit.share_names, fit.n,
                   np.zeros(n_rep, np.int64))
    cap, pair_cap = explosion_caps(pk)
    for k in range(n_rep):
        try:
            sim_days, labels = simulate(fit.mu, fit.alpha, T, exo, np.random.default_rng([seed, start + k]), spec,
                                        present=pk.present, max_events=cap)
            if n_pairs(sim_days, spec.max_lag) > pair_cap:
                raise RuntimeError("exploded")
        except RuntimeError:
            out.true_shares[k] = out.shares[k] = np.nan
            out.rho[k], out.n[k], out.converged[k], out.n_events[k], out.n_violations[k] = np.nan, np.nan, False, -1, 0
            continue
        p = pack(sim_days, K, spec, exo_names=fit.exo_names)
        f = refit(p)
        out.true_shares[k] = list(label_shares(sim_days, labels, K, fit.exo_names).values())
        out.shares[k] = _shares(p, f.mu, f.alpha, np.ones(p.n_days))
        out.rho[k], out.n[k], out.converged[k] = f.rho, f.n, f.converged
        out.n_events[k], out.n_violations[k] = p.tgt_ev.size, f.n_violations
    return out
