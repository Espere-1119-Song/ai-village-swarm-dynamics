"""Time-rescaling goodness of fit (SPEC 5.6-2).

For each agent dimension, the compensator increments between consecutive
events are iid Exp(1) under the model. The compensator includes the truncated
kernel integral exactly: a source event (agent or exogenous) at t_l adds
sum_m alpha^(m) (1 - exp(-beta_m min(L, t - t_l))).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from avsd.hawkes.model import Day, HawkesFit, Packed, _check_fit, _packed


@dataclass
class Rescaling:
    ks_stat: np.ndarray            # (K,)
    ks_pvalue: np.ndarray          # (K,)
    n: np.ndarray                  # (K,) number of increments
    increments: list[np.ndarray]   # per dimension

    @property
    def pooled(self) -> np.ndarray:
        """All increments. At an EM fixed point sum_d Lambda_i(T_d) = N_i, so with
        pool="concat" their mean is 1 up to the censored tails for any fitted
        model; the mean is informative only at fixed (e.g. true) parameters."""
        return np.concatenate(self.increments) if self.increments else np.empty(0)


def compensator_at_events(pk: Packed, fit: HawkesFit) -> np.ndarray:
    """Lambda_i(t_k) for each target k, i its own dimension, from its day's start."""
    _check_fit(pk, fit)
    spec, K = fit.spec, fit.K
    t = pk.ev_t[pk.tgt_ev]
    i = pk.tgt_dim
    lo = np.arange(spec.n_bins) * spec.bin_width
    width = np.full(spec.n_bins, spec.bin_width)
    width[-1] = np.inf
    base = (fit.mu[i] * np.clip(t[:, None] - lo, 0.0, width)).sum(1)
    # Source events older than L contribute their full n_ij.
    n = fit.n
    cum = np.zeros((K, pk.ev_t.size + 1))
    np.cumsum(n[:, pk.ev_src], axis=1, out=cum[:, 1:])
    full = cum[i, pk.tgt_lo] - cum[i, pk.ev_off[pk.tgt_day]]
    pair_dim = np.repeat(i, np.diff(pk.ptr))
    part = (fit.alpha[pair_dim, pk.par_src] * -np.expm1(-np.multiply.outer(pk.dt, spec.beta))).sum(1)
    partial = np.bincount(np.repeat(np.arange(t.size), np.diff(pk.ptr)), weights=part, minlength=t.size)
    return base + full + partial


def time_rescaling(days: list[Day] | Packed, fit: HawkesFit, pool: str = "concat") -> Rescaling:
    """KS test of compensator increments against Exp(1), per agent dimension.

    pool="concat" joins the days' rescaled time axes end to end, so the gap
    spanning a day boundary is the censored tail of one day plus the head of
    the next; the pooled gaps are then exactly iid Exp(1) under the model.
    Days on which an agent is absent (Packed.present) add nothing to its axis.
    pool="day" restarts at each day start and drops each day's censored tail,
    which biases the gaps low by about 1/(events per day and dimension).
    """
    if pool not in ("concat", "day"):
        raise ValueError("pool must be 'concat' or 'day'")
    pk = _packed(days, fit.K, fit.spec, fit.exo_names)
    lam = compensator_at_events(pk, fit)
    if pool == "concat":
        total = fit.mu @ pk.E.T + np.einsum("ijm,djm->id", fit.alpha, pk.W)  # (K, D) Lambda_i(T_d)
        total = total * pk.present.T
        offset = np.cumsum(total, axis=1) - total
        lam = lam + offset[pk.tgt_dim, pk.tgt_day]
    order = np.lexsort((np.arange(lam.size), pk.tgt_day, pk.tgt_dim))
    lam, day, dim = lam[order], pk.tgt_day[order], pk.tgt_dim[order]
    inc = np.diff(lam, prepend=0.0)
    first = np.ones(lam.size, bool)
    first[1:] = dim[1:] != dim[:-1]
    if pool == "day":
        first[1:] |= day[1:] != day[:-1]
    inc[first] = lam[first]
    incs = [inc[dim == k] for k in range(fit.K)]
    ks = [stats.kstest(x, "expon") if x.size else (np.nan, np.nan) for x in incs]
    return Rescaling(np.array([s[0] for s in ks]), np.array([s[1] for s in ks]),
                     np.array([x.size for x in incs]), incs)
