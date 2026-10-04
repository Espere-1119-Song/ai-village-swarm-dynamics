"""Discrete-time survival tools for module B1 (SPEC 6.2 H2, 6.3.3).

Units are observed over consolidation trials g = 1..L. A unit lost at trial g
has L = g and an event; a censored unit has L trials and no event. Trial g of a
unit that entered after consolidation e is consolidation e + g of its agent,
which carries calendar strata (regime, CHANGELOG window). Counts are kept per
agent so that confidence intervals can resample agents (cluster bootstrap).

- `risk_counts`: at-risk and event counts n[s, a, g], d[s, a, g] for g = 1..G,
  with trial-level strata (left truncation is handled by risk sets) and one
  overflow bin for g > G.
- Kaplan-Meier (discrete): S(g) = prod_{j <= g} (1 - h_j), h_j = d_j / n_j.
- Geometric model (H2): constant hazard h = sum d / sum n.
- Piecewise-constant alternative over generation bins; likelihood-ratio test
  (naive, units independent) and a Wald test with the cluster-bootstrap
  covariance of the bin hazards (robust to dependence within agents).
- Beta-geometric model: per-unit constant hazards drawn from a Beta(a, b), so
  the population hazard is a / (a + b + g - 1), decreasing in g. It separates
  unit heterogeneity from a true change of the per-unit hazard with g.
- Beta-discrete-Weibull (BdW; Fader, Hardie, Liu, Davin and Steenburgh 2018,
  Journal of Interactive Marketing): theta ~ Beta(a, b) per unit and
  S(g | theta) = (1 - theta)^(g^c), so the population survival is
  S(g) = B(a, b + g^c) / B(a, b). c = 1 is the beta-geometric; c < 1 means a
  unit's own hazard falls with the number of trials survived (duration
  dependence beyond heterogeneity), c > 1 that it rises. With no left
  truncation the likelihood of right-censored units factorises into the
  population hazards, so it is evaluated exactly on the risk sets n_g, d_g.
  Fits are Nelder-Mead in the log-parameters; a fit counts as converged when
  the analytic score and its difference Hessian predict at most 1e-3 nats and
  a change of c of at most 1e-3 from one more Newton step.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import optimize, special, stats

PIECEWISE_BINS: tuple[tuple[int, int | None], ...] = ((1, 1), (2, 2), (3, 4), (5, 8), (9, None))


@dataclass
class RiskCounts:
    """n, d, dmod with shape (strata, agents, G + 2): index 0 unused, G + 1 = overflow."""

    n: np.ndarray
    d: np.ndarray
    dmod: np.ndarray
    g_max: int

    def pooled(self, s: int, agents: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        sel = slice(None) if agents is None else agents
        return (self.n[s, sel].sum(0), self.d[s, sel].sum(0), self.dmod[s, sel].sum(0))


def risk_counts(
    e: np.ndarray,
    L: np.ndarray,
    event: np.ndarray,
    agent: np.ndarray,
    n_agents: int,
    g_max: int,
    strata: list[np.ndarray] | None = None,
    n_strata: int = 1,
    modified: np.ndarray | None = None,
) -> RiskCounts:
    """Counts by stratum, agent and trial g.

    e, L, event, agent: per unit (event > 0 marks a loss at trial L). strata:
    per agent an int array over consolidations c = 1..K (index c - 1), the
    stratum of that trial (-1 = excluded); None puts every trial in stratum 0.
    modified: per unit bool, the loss was a modification.
    """
    G = g_max
    n = np.zeros((n_strata, n_agents, G + 2), dtype=np.float64)
    d = np.zeros_like(n)
    dm = np.zeros_like(n)
    if modified is None:
        modified = np.zeros(len(L), dtype=bool)
    keep = L > 0
    e, L, event, agent, modified = e[keep], L[keep], event[keep], agent[keep], modified[keep]
    order = np.argsort(agent, kind="stable")
    e, L, event, agent, modified = e[order], L[order], event[order], agent[order], modified[order]
    bounds = np.searchsorted(agent, np.arange(n_agents + 1))
    for a in range(n_agents):
        lo_i, hi_i = bounds[a], bounds[a + 1]
        if lo_i == hi_i:
            continue
        ea, La, eva, ma = e[lo_i:hi_i], L[lo_i:hi_i], event[lo_i:hi_i], modified[lo_i:hi_i]
        if strata is None:
            runs = [(1, int((ea + La).max()), 0)]
        else:
            st = strata[a]
            runs = []
            if len(st):
                cut = np.flatnonzero(np.diff(st)) + 1
                starts = np.concatenate([[0], cut])
                ends = np.concatenate([cut, [len(st)]])
                runs = [(int(s0) + 1, int(s1), int(st[s0])) for s0, s1 in zip(starts, ends) if st[s0] >= 0]
        for c_lo, c_hi, s in runs:
            g_lo = np.maximum(1, c_lo - ea)
            g_hi = np.minimum(La, c_hi - ea)
            ok = g_lo <= g_hi
            if not ok.any():
                continue
            gl, gh = g_lo[ok], g_hi[ok]
            # Trials inside 1..G via a difference array; beyond G into the overflow bin.
            in_hi = np.minimum(gh, G)
            m = gl <= in_hi
            diff = (np.bincount(gl[m], minlength=G + 2)[: G + 2]
                    - np.bincount(in_hi[m] + 1, minlength=G + 2)[: G + 2]).astype(np.float64)
            n[s, a, : G + 1] += np.cumsum(diff)[: G + 1]
            n[s, a, G + 1] += np.maximum(0, gh - np.maximum(gl, G + 1) + 1).sum()
        # Events at trial L, in the stratum of consolidation e + L.
        ev = eva > 0
        if ev.any():
            gl = La[ev]
            c_ev = ea[ev] + gl
            s_ev = np.zeros(len(gl), dtype=np.int64) if strata is None else strata[a][c_ev - 1]
            okk = s_ev >= 0
            gi = np.minimum(gl[okk], G + 1)
            np.add.at(d, (s_ev[okk], a, gi), 1.0)
            np.add.at(dm, (s_ev[okk], a, gi), ma[ev][okk].astype(float))
    n[:, :, 0] = 0
    return RiskCounts(n, d, dm, G)


def hazard(n: np.ndarray, d: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n > 0, d / n, np.nan)


def km(h: np.ndarray) -> np.ndarray:
    """S(g) for g = 1..len(h) from discrete hazards (NaN hazards end the curve)."""
    return np.cumprod(1.0 - h)


def bootstrap_weights(agents: np.ndarray, n_total: int, reps: int, rng: np.random.Generator) -> np.ndarray:
    """(reps, n_total) multinomial agent weights, resampling only among `agents`."""
    w = np.zeros((reps, n_total))
    if len(agents) == 0:
        return w
    draws = rng.integers(0, len(agents), size=(reps, len(agents)))
    for r in range(reps):
        np.add.at(w[r], agents[draws[r]], 1.0)
    return w


def bin_sums(x: np.ndarray, bins: tuple[tuple[int, int | None], ...], g_max: int) -> np.ndarray:
    """Sum x[..., g] over generation bins (the last axis indexes g; G + 1 = overflow)."""
    out = []
    for lo, hi in bins:
        h = g_max + 1 if hi is None else min(hi, g_max)
        out.append(x[..., lo: h + 1].sum(-1))
    return np.stack(out, -1)


def _ll(n: np.ndarray, d: np.ndarray, h: np.ndarray) -> float:
    h = np.clip(h, 1e-12, 1 - 1e-12)
    return float(np.sum(d * np.log(h) + (n - d) * np.log1p(-h)))


def piecewise_loglik(n: np.ndarray, d: np.ndarray, g_max: int,
                     bins: tuple[tuple[int, int | None], ...] = PIECEWISE_BINS) -> tuple[float, int]:
    """Maximised log-likelihood of a piecewise-constant hazard and its number of parameters."""
    nb, db = bin_sums(n, bins, g_max), bin_sums(d, bins, g_max)
    ok = nb > 0
    return _ll(nb[ok], db[ok], hazard(nb, db)[ok]), int(ok.sum())


def geometric_loglik(n: np.ndarray, d: np.ndarray) -> float:
    """Maximised log-likelihood of a constant hazard."""
    N, D = n[1:].sum(), d[1:].sum()
    return _ll(n[1:], d[1:], np.full(len(n) - 1, D / N)) if N > 0 else float("nan")


@dataclass
class H2Test:
    n_trials: float
    n_events: float
    h_geom: float
    ll_geom: float
    ll_piecewise: float
    lr: float
    df: int
    p_lr: float
    wald: float
    df_wald: int
    p_wald: float
    bin_h: np.ndarray
    bin_lo: np.ndarray
    bin_hi: np.ndarray
    bg_alpha: float
    bg_beta: float
    ll_betageom: float
    aic_geom: float
    aic_betageom: float
    aic_piecewise: float


def fit_beta_geometric(n: np.ndarray, d: np.ndarray, g: np.ndarray) -> tuple[float, float, float]:
    """MLE of (a, b) for the hazard a / (a + b + g - 1) given counts per g."""
    keep = n > 0
    n, d, g = n[keep], d[keep], g[keep]
    if d.sum() <= 0 or d.sum() >= n.sum():
        return float("nan"), float("nan"), float("nan")

    def nll(p: np.ndarray) -> float:
        a, b = np.exp(p)
        return -_ll(n, d, a / (a + b + g - 1.0))

    h0 = d.sum() / n.sum()
    best = None
    for scale in (0.1, 1.0, 10.0):
        x0 = np.log([h0 * scale, (1 - h0) * scale])
        r = optimize.minimize(nll, x0, method="Nelder-Mead", options={"xatol": 1e-8, "fatol": 1e-8,
                                                                       "maxiter": 4000})
        if best is None or r.fun < best.fun:
            best = r
    a, b = np.exp(best.x)
    return float(a), float(b), float(-best.fun)


def h2_test(
    n_ag: np.ndarray,
    d_ag: np.ndarray,
    g_max: int,
    w: np.ndarray,
    bins: tuple[tuple[int, int | None], ...] = PIECEWISE_BINS,
    min_clusters: int = 5,
    fit_betageom: bool = True,
) -> H2Test:
    """Geometric vs piecewise-constant hazard for agent-level counts n_ag, d_ag (A, G + 2).

    The cluster Wald test needs at least `min_clusters` agents with trials in
    the scope; otherwise it is NaN. The beta-geometric fit assumes no left
    truncation, so callers turn it off for calendar (trial-level) strata.
    """
    n = n_ag.sum(0)
    d = d_ag.sum(0)
    N, D = n[1:].sum(), d[1:].sum()
    h0 = D / N if N > 0 else float("nan")
    ll0 = _ll(n[1:], d[1:], np.full(len(n) - 1, h0))
    nb, db = bin_sums(n, bins, g_max), bin_sums(d, bins, g_max)
    hb = hazard(nb, db)
    ok = nb > 0
    ll1 = _ll(nb[ok], db[ok], hb[ok])
    df = int(ok.sum()) - 1
    lr = max(0.0, 2 * (ll1 - ll0))
    p_lr = float(stats.chi2.sf(lr, df)) if df > 0 else float("nan")
    # Cluster-bootstrap Wald test of equal bin hazards.
    nbb, dbb = w @ bin_sums(n_ag, bins, g_max), w @ bin_sums(d_ag, bins, g_max)
    hbb = hazard(nbb, dbb)[:, ok]
    good = np.isfinite(hbb).all(1)
    wald, df_w, p_w = float("nan"), 0, float("nan")
    lo = np.full(len(bins), np.nan)
    hi = np.full(len(bins), np.nan)
    n_clusters = int((n_ag[:, 1:].sum(1) > 0).sum())
    if good.sum() > 10 and df > 0 and n_clusters >= 2:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            qs = np.nanpercentile(hazard(nbb, dbb)[good], [2.5, 97.5], axis=0)
        lo, hi = qs[0], qs[1]
    if good.sum() > 10 and df > 0 and n_clusters >= min_clusters:
        hb_ok = hb[ok]
        cov = np.cov(hbb[good].T)
        k = len(hb_ok)
        C = np.hstack([-np.ones((k - 1, 1)), np.eye(k - 1)])
        diff = C @ hb_ok
        V = C @ cov @ C.T
        df_w = int(np.linalg.matrix_rank(V))
        wald = float(diff @ np.linalg.pinv(V) @ diff)
        p_w = float(stats.chi2.sf(wald, df_w)) if df_w > 0 else float("nan")
    a = b = llbg = float("nan")
    if fit_betageom:
        g = np.arange(1, g_max + 1, dtype=float)
        a, b, llbg = fit_beta_geometric(n[1:g_max + 1], d[1:g_max + 1], g)
        # The overflow bin has no single g; it gets the hazard at g = G + 1 (an
        # approximation that only matters if many trials lie beyond G).
        if np.isfinite(a) and n[g_max + 1] > 0:
            llbg += _ll(n[g_max + 1:], d[g_max + 1:], np.array([a / (a + b + g_max)]))
    return H2Test(
        n_trials=float(N), n_events=float(D), h_geom=float(h0), ll_geom=ll0, ll_piecewise=ll1,
        lr=lr, df=df, p_lr=p_lr, wald=wald, df_wald=df_w, p_wald=p_w, bin_h=hb, bin_lo=lo,
        bin_hi=hi, bg_alpha=a, bg_beta=b, ll_betageom=llbg, aic_geom=2 - 2 * ll0,
        aic_betageom=4 - 2 * llbg, aic_piecewise=2 * (df + 1) - 2 * ll1,
    )


def simulate_geometric(
    n_agents: int, units_per_agent: int, cons_per_agent: int, h: float, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    """Units entering uniformly over an agent's consolidations, each lost with constant hazard h."""
    agent = np.repeat(np.arange(n_agents), units_per_agent)
    e = rng.integers(0, cons_per_agent, size=len(agent))
    life = rng.geometric(h, size=len(agent))  # trial of the loss, >= 1
    avail = cons_per_agent - e
    L = np.minimum(life, avail)
    event = (life <= avail).astype(np.int8)
    return {"agent": agent, "e": e, "L": L, "event": event}


# --- beta-discrete-Weibull ------------------------------------------------------

BDW_BOX = ((1e-8, 1e8), (1e-8, 1e8), (1e-3, 50.0))  # search range of alpha, beta and c
BDW_GAIN_TOL = 1e-3  # converged: one more Newton step would raise ll by at most this (nats) ...
BDW_C_TOL = 1e-3  # ... and move c by at most this
BDW_RCOND = 1e-6  # Hessian directions flatter than this share of the steepest one are not identified


@dataclass
class BdWFit:
    """converged: the estimate passes `bdw_newton_check` (not Nelder-Mead's own flag).

    gain_left, c_left: predicted log-likelihood gain and change of c of one more Newton step.
    """

    alpha: float
    beta: float
    c: float
    ll: float
    converged: bool
    gain_left: float = float("nan")
    c_left: float = float("nan")


def bdw_boundary(alpha: float, beta: float) -> bool:
    """The Beta mixing sits at a limit of its range (alpha or beta outside 1e-4..1e6).

    The likelihood is then nearly flat along a ridge towards the limit, so alpha and beta are
    not identified and c is only weakly identified.
    """
    return not (1e-4 < alpha < 1e6 and 1e-4 < beta < 1e6)


def bdw_log_survival(alpha: float, beta: float, c: float, g_max: int) -> np.ndarray:
    """log S(g) for g = 0..g_max: S(g) = B(alpha, beta + g^c) / B(alpha, beta)."""
    gg = np.arange(g_max + 1, dtype=np.float64)
    return special.betaln(alpha, beta + gg ** c) - special.betaln(alpha, beta)


def bdw_hazard(alpha: float, beta: float, c: float, g: np.ndarray) -> np.ndarray:
    """Population hazard h_g = 1 - S(g) / S(g - 1) for g >= 1."""
    g = np.asarray(g, dtype=np.int64)
    ls = bdw_log_survival(alpha, beta, c, int(g.max()))
    return -np.expm1(ls[g] - ls[g - 1])


def bdw_loglik(n: np.ndarray, d: np.ndarray, alpha: float, beta: float, c: float) -> float:
    """Log-likelihood of risk-set counts n[g], d[g] (array index = g, index 0 ignored)."""
    g = np.flatnonzero(n > 0)
    g = g[g >= 1]
    if len(g) == 0:
        return 0.0
    ls = bdw_log_survival(alpha, beta, c, int(g[-1]))
    delta = np.minimum(ls[g] - ls[g - 1], -1e-300)  # log(1 - h_g) < 0
    dd = d[g]
    log_h = np.log(-np.expm1(delta))
    return float(np.sum(np.where(dd > 0, dd * log_h, 0.0) + (n[g] - dd) * delta))


def _psi_gap(z: np.ndarray, s: np.ndarray) -> np.ndarray:
    """psi(z) - psi(z + s) for z > 0, s >= 0 (broadcast).

    For z > 1e4 an asymptotic expansion replaces the difference of two nearly equal digammas,
    which loses every digit once z / s nears 1e15 (k^c at large k and c).
    """
    z, s = np.broadcast_arrays(np.asarray(z, dtype=np.float64), np.asarray(s, dtype=np.float64))
    out = np.array(special.digamma(z) - special.digamma(z + s), dtype=np.float64)
    big = z > 1e4
    if np.any(big):
        sb = s[big]
        r1, r2 = 1.0 / z[big], 1.0 / (z[big] + sb)
        q = sb * r1 * r2
        out[big] = -np.log1p(sb * r1) - q / 2 - q * (r1 + r2) / 12 + q * (r1 + r2) * (r1 * r1 + r2 * r2) / 120
    return out


def bdw_score(n: np.ndarray, d: np.ndarray, alpha: float, beta: float, c: float,
              c_fixed: bool = False) -> np.ndarray:
    """Gradient of `bdw_loglik` with respect to (log alpha, log beta[, log c]).

    With delta_g = log S(g) - log S(g - 1), d ll / d delta_g = (n_g - d_g) - d_g / (exp(-delta_g) - 1);
    d log S(k) / d alpha = psi(a + b) - psi(a + b + k^c), d / d beta = psi(b + k^c) - psi(a + b + k^c)
    - psi(b) + psi(a + b) and d / d c = (psi(b + k^c) - psi(a + b + k^c)) k^c log k.
    """
    nn = np.asarray(n, dtype=np.float64)
    dd = np.asarray(d, dtype=np.float64)
    g = np.flatnonzero(nn > 0)
    g = g[g >= 1]
    if len(g) == 0:
        return np.zeros(2 if c_fixed else 3)
    k = np.arange(g[-1] + 1, dtype=np.float64)
    kc = k ** c
    ls = bdw_log_survival(alpha, beta, c, int(g[-1]))
    delta = np.minimum(ls[g] - ls[g - 1], -1e-300)
    dg = dd[g]
    with np.errstate(over="ignore", divide="ignore"):
        w = (nn[g] - dg) - np.where(dg > 0, dg / np.expm1(-delta), 0.0)
    dla = _psi_gap(alpha + beta, kc)
    gap = _psi_gap(beta + kc, alpha)  # psi(b + k^c) - psi(a + b + k^c)
    dlb = gap - gap[0]
    out = [alpha * np.sum(w * (dla[g] - dla[g - 1])), beta * np.sum(w * (dlb[g] - dlb[g - 1]))]
    if not c_fixed:
        dlc = gap * kc * np.log(np.maximum(k, 1.0))
        out.append(c * np.sum(w * (dlc[g] - dlc[g - 1])))
    return np.array(out)


def bdw_newton_check(n: np.ndarray, d: np.ndarray, alpha: float, beta: float, c: float,
                     c_fixed: bool = False, h: float = 1e-4) -> tuple[float, float, bool]:
    """Predicted log-likelihood gain and change of c of one Newton step from (alpha, beta, c).

    Uses `bdw_score` and a central-difference Hessian of it in the log-parameters, so it does
    not depend on the rounding noise of the log-likelihood (scipy's betaln loses up to ~1e-10 per
    term for arguments between ~170 and ~1e6 alpha; on the B1 risk sets that is 1e-6 to 2e-2
    nats of error in ll). A parameter at an edge of BDW_BOX whose score points outward stays
    fixed. Directions with curvature below BDW_RCOND times the largest are left out: the flat
    ridge of a mixing distribution at its limit (`bdw_boundary`) carries no gain and its
    curvature is below the resolution of the difference Hessian. Returns (gain, change of c,
    saddle); saddle: the log-likelihood curves clearly upwards in some direction (no maximum).
    """
    p = 2 if c_fixed else 3
    x = np.log([alpha, beta, c][:p])
    lo = np.log([b[0] for b in BDW_BOX[:p]])
    hi = np.log([b[1] for b in BDW_BOX[:p]])

    def score(xx: np.ndarray) -> np.ndarray:
        return bdw_score(n, d, float(np.exp(xx[0])), float(np.exp(xx[1])),
                         float(np.exp(xx[2])) if p == 3 else c, c_fixed)

    gr = score(x)
    H = np.zeros((p, p))
    for j in range(p):
        e = np.zeros(p)
        e[j] = h
        H[:, j] = (score(x + e) - score(x - e)) / (2 * h)
    if not (np.isfinite(gr).all() and np.isfinite(H).all()):
        return float("nan"), float("nan"), False
    pinned = ((x - lo < 1e-6) & (gr < 0)) | ((hi - x < 1e-6) & (gr > 0))
    free = ~pinned
    if not free.any():
        return 0.0, 0.0, False
    lam, V = np.linalg.eigh(-(H + H.T)[np.ix_(free, free)] / 2)
    if not np.abs(lam).max() > 0:
        return float("nan"), float("nan"), False
    cut = BDW_RCOND * np.abs(lam).max()
    keep = np.abs(lam) > cut
    step = np.zeros(p)
    step[free] = V[:, keep] @ ((V[:, keep].T @ gr[free]) / lam[keep])
    gain = 0.5 * float(gr[free] @ step[free])
    dc = float(c * np.expm1(step[2])) if p == 3 else 0.0
    return gain, dc, bool((lam < -cut).any())


def fit_bdw(
    n: np.ndarray,
    d: np.ndarray,
    c_fixed: float | None = None,
    start: tuple[float, ...] | None = None,
    maxiter: int = 4000,
) -> BdWFit:
    """Maximum-likelihood BdW fit to counts per g; c_fixed = 1 gives the beta-geometric.

    `start` holds the free parameters (alpha, beta[, c]) for a warm start;
    otherwise a small grid of starts is tried. Nelder-Mead's own convergence test
    (absolute tolerances of 1e-7) cannot be met when |ll| is 1e6 to 1e7, because the
    log-likelihood carries more rounding noise than that, so `converged` comes from
    `bdw_newton_check`: at most BDW_GAIN_TOL nats and a change of c of at most BDW_C_TOL
    left to gain, and no direction of upward curvature.
    """
    nn = np.asarray(n, dtype=np.float64)
    dd = np.asarray(d, dtype=np.float64)
    N, D = nn[1:].sum(), dd[1:].sum()
    nan = float("nan")
    if N <= 0 or D <= 0 or D >= N:
        return BdWFit(nan, nan, nan if c_fixed is None else float(c_fixed), nan, False)
    g_top = int(np.flatnonzero(nn > 0).max())
    nn, dd = nn[: g_top + 1], dd[: g_top + 1]
    (a_lo, a_hi), (b_lo, b_hi), (c_lo, c_hi) = BDW_BOX

    def nll(p: np.ndarray) -> float:
        a, b = np.exp(p[0]), np.exp(p[1])
        c = float(c_fixed) if c_fixed is not None else float(np.exp(p[2]))
        if not (a_lo < a < a_hi and b_lo < b < b_hi and c_lo < c < c_hi):
            return 1e300
        v = -bdw_loglik(nn, dd, a, b, c)
        return v if np.isfinite(v) else 1e300

    h0 = D / N
    if start is not None:
        x0s = [np.log(np.asarray(start, dtype=np.float64))]
    else:
        x0s = []
        for scale in (0.3, 1.0, 3.0):
            ab = [np.log(h0 * scale), np.log((1 - h0) * scale)]
            for c0 in ((None,) if c_fixed is not None else (0.6, 1.0, 1.6)):
                x0s.append(np.array(ab if c0 is None else ab + [np.log(c0)]))
    best = None
    for x0 in x0s:
        r = optimize.minimize(nll, x0, method="Nelder-Mead",
                              options={"xatol": 1e-7, "fatol": 1e-7, "maxiter": maxiter,
                                       "maxfev": 2 * maxiter})
        if best is None or r.fun < best.fun:
            best = r
    a, b = np.exp(best.x[:2])
    c = float(c_fixed) if c_fixed is not None else float(np.exp(best.x[2]))
    gain, dc, saddle = bdw_newton_check(nn, dd, float(a), float(b), c, c_fixed is not None)
    conv = bool(np.isfinite(gain) and not saddle and gain <= BDW_GAIN_TOL and abs(dc) <= BDW_C_TOL)
    return BdWFit(float(a), float(b), c, float(-best.fun), conv, gain, dc)


def bdw_profile_ci(n: np.ndarray, d: np.ndarray, fit: BdWFit, level: float = 0.95) -> tuple[float, float]:
    """Profile-likelihood CI for c (units treated as independent)."""
    if not np.isfinite(fit.c):
        return float("nan"), float("nan")
    crit = stats.chi2.ppf(level, 1) / 2

    def excess(logc: float) -> float:
        r = fit_bdw(n, d, c_fixed=float(np.exp(logc)), start=(fit.alpha, fit.beta), maxiter=2000)
        return (fit.ll - r.ll) - crit

    x0 = float(np.log(fit.c))
    out = []
    for side in (-1.0, 1.0):
        prev, found = x0, None
        for k in range(30):
            x = x0 + side * 0.002 * (2.0 ** k)
            if abs(x) > np.log(50):
                break
            if excess(x) > 0:
                found = optimize.brentq(excess, min(prev, x), max(prev, x), xtol=1e-6)
                break
            prev = x
        out.append(float(np.exp(found)) if found is not None else float("nan"))
    return out[0], out[1]


def bdw_bootstrap(n_ag: np.ndarray, d_ag: np.ndarray, w: np.ndarray, start: tuple[float, float, float]
                  ) -> np.ndarray:
    """(B, 4) array of alpha, beta, c, ll refitted to cluster-bootstrap replicates w @ counts."""
    nb, db = w @ n_ag, w @ d_ag
    out = np.full((len(w), 4), np.nan)
    for b in range(len(w)):
        f = fit_bdw(nb[b], db[b], start=start, maxiter=2000)
        out[b] = (f.alpha, f.beta, f.c, f.ll)
    return out


def simulate_bdw(n_units: int, alpha: float, beta: float, c: float, horizon: int,
                 rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Trial of loss L (censored at `horizon`) and event flags under the BdW."""
    theta = rng.beta(alpha, beta, n_units)
    u = rng.random(n_units)
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.log(u) / np.log1p(-theta)
    t = np.floor(np.nan_to_num(x, nan=0.0, posinf=1e18) ** (1.0 / c)) + 1
    L = np.minimum(t, horizon).astype(np.int64)
    return L, (t <= horizon).astype(np.int8)
