"""Exact cluster (branching) simulation of the Hawkes model given exogenous events (SPEC 5.6-1).

Immigrants come from the piecewise-constant baseline. Every event of source j
(exogenous or agent) has Poisson(n_ij) children in each agent dimension i,
with delays drawn from the truncated kernel g_ij on (0, L]; children after T
are dropped. An agent absent on a day (present[i] False) has no immigrants
and no children that day. The true parent source of each agent event is
returned so that recovery can be scored against the realized decomposition.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from avsd.hawkes.model import Day, HawkesSpec, default_exo_names, share_names


def _sources(x, H: int) -> tuple[np.ndarray, ...]:
    """One day's exogenous events: an array of times when H == 1, else H arrays."""
    if H == 1 and not (isinstance(x, (list, tuple)) and len(x) and np.ndim(x[0]) == 1):
        return (np.sort(np.asarray(x, dtype=np.float64)),)
    if len(x) != H:
        raise ValueError(f"expected {H} exogenous event arrays, got {len(x)}")
    return tuple(np.sort(np.asarray(s, dtype=np.float64)) for s in x)


def simulate_day(mu: np.ndarray, alpha: np.ndarray, T: float, exo_times, rng: np.random.Generator,
                 spec: HawkesSpec | None = None, max_events: int = 1_000_000,
                 present: np.ndarray | None = None) -> tuple[Day, np.ndarray]:
    """alpha is (K, K + H, M); exo_times is one array (H = 1) or H arrays;
    present (K,) the agents present that day (None: all; the Day keeps it).
    Returns the day and, per agent event, its parent source (-1 background,
    0..K-1 agent, K + h exogenous source h)."""
    spec = spec or HawkesSpec()
    K, M = mu.shape[0], spec.M
    H = alpha.shape[1] - K
    beta, trunc = spec.beta, spec.trunc
    n = spec.branching(alpha)
    with np.errstate(invalid="ignore", divide="ignore"):
        cum = np.cumsum(alpha * trunc, axis=-1) / n[..., None]  # (K, K + H, M) mixture CDF
    if present is not None:
        present = np.asarray(present, dtype=bool)
        mu, n = mu * present[:, None], n * present[:, None]

    edges = np.arange(spec.n_bins + 1) * spec.bin_width
    edges[-1] = np.inf
    seg = np.clip(np.minimum(T, edges[1:]) - edges[:-1], 0, None)
    cnt = rng.poisson(mu * seg)                                    # (K, n_bins)
    dims = np.repeat(np.tile(np.arange(K), spec.n_bins), cnt.T.ravel())
    lo = np.repeat(np.repeat(edges[:-1], K), cnt.T.ravel())
    width = np.repeat(np.repeat(seg, K), cnt.T.ravel())
    times = lo + width * rng.random(dims.size)
    out_t, out_d, out_p = [times], [dims], [np.full(dims.size, -1)]

    ex = _sources(exo_times, H)
    par_t = np.concatenate([*ex, times])
    par_s = np.concatenate([*(np.full(x.size, K + h) for h, x in enumerate(ex)), dims]).astype(np.int64)
    total = dims.size
    while par_t.size:
        nk = rng.poisson(n[:, par_s])                              # (K, n_parents)
        c_dim = np.repeat(np.tile(np.arange(K), par_t.size), nk.T.ravel())
        c_src = np.repeat(par_s, nk.sum(0))
        c_par = np.repeat(par_t, nk.sum(0))
        m = (rng.random(c_dim.size)[:, None] > cum[c_dim, c_src]).sum(1)
        m = np.minimum(m, M - 1)
        v = 1.0 - rng.random(c_dim.size)                           # (0, 1]
        tau = -np.log1p(-v * trunc[m]) / beta[m]
        c_t = c_par + tau
        keep = c_t <= T
        par_t, par_s = c_t[keep], c_dim[keep]
        out_t.append(par_t), out_d.append(par_s), out_p.append(c_src[keep])
        total += par_t.size
        if total > max_events:
            raise RuntimeError("simulation exceeded max_events; the process may be supercritical")

    t, d, p = np.concatenate(out_t), np.concatenate(out_d), np.concatenate(out_p)
    order = np.argsort(t, kind="stable")
    kw = {"human_times": ex[0]} if H == 1 else {"exo_times": ex}
    return Day(T=float(T), agent_times=t[order], agent_dims=d[order].astype(np.int64), present=present, **kw), \
        p[order].astype(np.int64)


def simulate(mu: np.ndarray, alpha: np.ndarray, Ts: Sequence[float], exo_times: Sequence,
             rng: np.random.Generator, spec: HawkesSpec | None = None,
             present: Sequence[np.ndarray] | np.ndarray | None = None,
             max_events: int | None = None) -> tuple[list[Day], list[np.ndarray]]:
    """exo_times: per day, one array (H = 1) or H arrays; present: per day, the (K,) presence mask
    (None: everyone present every day). max_events caps the agent events of all days together
    (RuntimeError above it; default 1,000,000 per day)."""
    pres = [None] * len(Ts) if present is None else list(present)
    if len(pres) != len(Ts):
        raise ValueError("present needs one mask per day")
    out, total = [], 0
    for T, x, p in zip(Ts, exo_times, pres):
        cap = 1_000_000 if max_events is None else max_events - total
        day, par = simulate_day(mu, alpha, T, x, rng, spec, max_events=cap, present=p)
        total += day.agent_times.size
        out.append((day, par))
    return [d for d, _ in out], [p for _, p in out]


def label_shares(days: list[Day], parent_src: list[np.ndarray], K: int,
                 exo_names: tuple[str, ...] | None = None) -> dict[str, float]:
    """Realized decomposition from true parent sources, in share_names order."""
    H = days[0].H if days else 1
    names = share_names(tuple(exo_names) if exo_names is not None else default_exo_names(H))
    if len(names) != H + 3:
        raise ValueError(f"exo_names must name the {H} exogenous sources")
    dims = np.concatenate([np.asarray(d.agent_dims) for d in days]) if days else np.empty(0, np.int64)
    p = np.concatenate(parent_src) if parent_src else np.empty(0, np.int64)
    cls = np.where(p < 0, 0, np.where(p >= K, 1 + p - K, np.where(p == dims, H + 2, H + 1)))
    frac = np.bincount(cls, minlength=H + 3) / max(cls.size, 1)
    return dict(zip(names, frac.tolist()))
