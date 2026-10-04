"""Run-day bootstrap for the Hawkes decomposition and branching matrix (SPEC 5.5).

Resampling run days with replacement is done by weighting each day by its draw
count, which is equivalent to refitting on the concatenated sample. The unit
drawn is a cluster of realizations (`clusters`, default one per realization):
the pipeline passes the run date, so the two blocks of a date with an
off-schedule extra block are drawn together. Rep r draws from
default_rng([seed, r]), so reps are independent of how they are chunked.

Each rep is fitted with the point estimator: fit()'s starts (`starts`, by
default the full-data fit's) plus a warm start from the full-data fit, keeping
the highest objective. The shared-kernel likelihood has several local maxima,
and a resample can move the best one: in the first real-data run a warm start
alone ended more than 0.1 nats below the multi-start optimum in 34 of 44
windows (24 reps each, up to 52 nats) and moved interval bounds by up to 0.22,
while the starts alone are also beaten by the warm start in some reps
(docs/decisions.md). BootstrapResult keeps both objectives of every rep.
`multistart=False` keeps only the warm start (about ten times faster; for
checks).

The refit must actually converge: from a warm start, a loose tolerance stops
after a few EM steps near the full-data fit and the intervals come out too
narrow (tol=1e-4 gave share SDs about 1/4 of the converged ones; an objective
test of 1e-8 alone gave SDs 2-6% low). The refits therefore use the same
stopping rule as fit(), including the parameter-step test and, for shared
kernels, the Newton certificate, and the full-data fit passed in should have
converged under it too, or the point estimate and the interval are centred on
different estimators.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, fields

import numpy as np

from avsd.hawkes.model import (
    MAX_ITER, SHARES, TOL, XTOL, Day, HawkesFit, Packed, _check_fit, _fit_pack, _packed, _shares,
)


@dataclass
class BootstrapResult:
    reps: np.ndarray        # (R,) rep indices
    shares: np.ndarray      # (R, 3 + H) in `names` order
    n: np.ndarray           # (R, K, K + H)
    rho: np.ndarray         # (R,)
    n_iter: np.ndarray      # (R,) of the kept refit
    converged: np.ndarray   # (R,) the kept refit is certified
    obj_warm: np.ndarray    # (R,) objective of the warm-started refit
    obj_starts: np.ndarray  # (R,) best objective over fit()'s starts (nan when multistart=False)
    n_violations: np.ndarray  # (R,) objective decreases over all refits of the rep
    events: np.ndarray      # (R,) weighted number of agent events of the rep
    n_clusters: np.ndarray  # (R,) distinct clusters (run dates) drawn
    names: tuple[str, ...] = SHARES

    @classmethod
    def concat(cls, parts: list[BootstrapResult]) -> BootstrapResult:
        parts = sorted(parts, key=lambda p: p.reps[0] if p.reps.size else -1)
        if len({p.names for p in parts}) > 1:
            raise ValueError("bootstrap parts have different share names")
        arrays = [f.name for f in fields(cls) if f.name != "names"]
        return cls(**{a: np.concatenate([getattr(p, a) for p in parts]) for a in arrays},
                   names=parts[0].names if parts else SHARES)

    @property
    def warm_won(self) -> np.ndarray:
        """(R,) the warm start gave the kept refit (ties count for the warm start)."""
        return ~(self.obj_starts > self.obj_warm)

    def ci(self, level: float = 0.95) -> dict[str, np.ndarray]:
        """Percentile intervals over all reps; last axis is (lower, upper). Warns
        when some refits hit max_iter without converging."""
        bad = int((~self.converged.astype(bool)).sum())
        if bad:
            warnings.warn(f"{bad} of {self.converged.size} bootstrap refits did not converge",
                          RuntimeWarning, stacklevel=2)
        q = [(1 - level) / 2, (1 + level) / 2]
        return {
            "shares": np.moveaxis(np.nanquantile(self.shares, q, axis=0), 0, -1),
            "n": np.moveaxis(np.quantile(self.n, q, axis=0), 0, -1),
            "rho": np.quantile(self.rho, q),
        }

    def shares_ci(self, level: float = 0.95) -> dict[str, tuple[float, float]]:
        return {s: tuple(v) for s, v in zip(self.names, self.ci(level)["shares"].tolist())}


def day_weights(rng: np.random.Generator, clusters: np.ndarray) -> np.ndarray:
    """One rep's weight of each day: the draw count of its cluster, clusters drawn with replacement
    as often as there are clusters."""
    C = int(clusters.max()) + 1 if clusters.size else 0
    return np.bincount(rng.integers(0, C, C), minlength=C)[clusters].astype(np.float64)


def bootstrap_reps(days: list[Day] | Packed, fit: HawkesFit, start: int, stop: int, seed: int,
                   *, tol: float = TOL, xtol: float = XTOL, max_iter: int = MAX_ITER,
                   accelerate: bool = True, clusters: np.ndarray | None = None, multistart: bool = True,
                   starts: tuple[str, ...] | None = None) -> BootstrapResult:
    """Run reps [start, stop). clusters (D,) maps each day to its resampling unit, numbered from 0
    (default: every day its own unit). starts: fit()'s starts for the multistart refit (default:
    the full-data fit's, or STARTS[kernel_sharing] when it was warm-started)."""
    pk = _packed(days, fit.K, fit.spec, fit.exo_names)
    _check_fit(pk, fit)
    if not fit.converged:
        warnings.warn("bootstrapping a fit that did not converge", RuntimeWarning, stacklevel=2)
    D = pk.n_days
    clusters = np.arange(D) if clusters is None else np.asarray(clusters, dtype=np.int64)
    if clusters.shape != (D,) or (D and (clusters.min() < 0 or np.unique(clusters).size != clusters.max() + 1)):
        raise ValueError("clusters must number every day's unit 0..C-1, all units used")
    if starts is None and fit.start != "init":
        starts = fit.starts
    R = max(stop - start, 0)
    K, H = fit.K, fit.H
    out = BootstrapResult(
        reps=np.arange(start, start + R), shares=np.empty((R, 3 + H)), n=np.empty((R, K, K + H)), rho=np.empty(R),
        n_iter=np.empty(R, np.int64), converged=np.empty(R, bool), obj_warm=np.empty(R),
        obj_starts=np.full(R, np.nan), n_violations=np.empty(R, np.int64), events=np.empty(R),
        n_clusters=np.empty(R, np.int64), names=fit.share_names)
    ev = np.bincount(pk.tgt_day, minlength=D).astype(np.float64)
    kw = {"l1": fit.l1, "tol": tol, "xtol": xtol, "max_iter": max_iter, "accelerate": accelerate,
          "kernel_sharing": fit.kernel_sharing, "l1_scope": fit.l1_scope, "tie_exo": fit.tie_exo}
    for k, r in enumerate(range(start, stop)):
        w_day = day_weights(np.random.default_rng([seed, r]), clusters)
        f = _fit_pack(pk, w_day, init=(fit.mu, fit.alpha), **kw)
        out.obj_warm[k], viol = f.objective[-1], f.n_violations
        if multistart:
            g = _fit_pack(pk, w_day, starts=starts, **kw)
            out.obj_starts[k], viol = g.objective[-1], viol + g.n_violations
            if g.objective[-1] > f.objective[-1]:
                f = g
        out.shares[k] = _shares(pk, f.mu, f.alpha, w_day)
        out.n[k] = f.n
        out.rho[k] = f.rho
        out.n_iter[k], out.converged[k], out.n_violations[k] = f.n_iter, f.converged, viol
        out.events[k] = float(ev @ w_day)
        out.n_clusters[k] = np.unique(clusters[w_day > 0]).size
    return out


def bootstrap(days: list[Day] | Packed, fit: HawkesFit, n_boot: int = 1000, seed: int = 20261003,
              *, tol: float = TOL, xtol: float = XTOL, max_iter: int = MAX_ITER,
              accelerate: bool = True, clusters: np.ndarray | None = None,
              multistart: bool = True) -> BootstrapResult:
    return bootstrap_reps(days, fit, 0, n_boot, seed, tol=tol, xtol=xtol, max_iter=max_iter,
                          accelerate=accelerate, clusters=clusters, multistart=multistart)
