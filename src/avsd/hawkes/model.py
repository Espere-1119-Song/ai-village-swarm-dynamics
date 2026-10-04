"""Multivariate Hawkes process with exogenous sources, fitted by EM (SPEC 5.2, 5.3).

Each run day d is one realization on [0, T_d], t = seconds since the day's run
start. Agent events (dimensions 0..K-1) are modeled. H >= 1 exogenous sources
(human, system nudges, ...) are sources K..K+H-1: they can parent agent events
but are conditioned on. Kernels are sums of M exponentials with fixed rates,
truncated at the maximum lag L. Baselines are piecewise constant per hour of
the run day; hours >= n_bins - 1 share the last bin. An event is a candidate
parent of a later event on the same day when 0 < dt <= L, so tied events never
parent each other.

Presence. An agent need not run on every day of a window. Day.present marks
the agents present on a day (default: all). An absent agent has no baseline
and no children that day, so target i accrues baseline exposure and kernel
compensator only over the days it is present: E_ib = sum over those days of
|B_b ∩ [0, T_d]|, and the compensator of source j's events counts only their
days. Counting absent days would let an agent that ran on few days of a window
explain its bursts by self-excitation (n_ii near 1, and rho set by that one
agent).

Kernel sharing. With F_m = 1 - exp(-beta_m L),
    alpha_ij^(m) = n_ij w_{c(i,j), m} / F_m,   sum_m w_cm = 1,  w >= 0,
so n_ij is the branching ratio of cell (i, j) and its normalized kernel
g_ij(tau) = sum_m w_cm beta_m exp(-beta_m tau) / F_m on (0, L] depends only on
the class c(i, j). kernel_sharing="cell" gives every cell its own class (the
SPEC 5.2 model, alpha free); "class" uses self (j = i), other (j another
agent) and one class per exogenous source; "global" uses one class. With
"class", tie_exo names exogenous sources whose cells take the "other" class
(a sensitivity variant for sources with too few events to fix a shape).

ECM M-step. Let S_ijm be the responsibility sums (expected number of i-events
whose parent is a j-event through component m), S_ij = sum_m S_ijm,
S_cm = sum_{ij in c} S_ijm, and G_ijm = sum_{l in j, i present} F_m(l) / F_m the
edge-truncated exposure of source j's events on the days target i is present,
F_m(l) = 1 - exp(-beta_m min(L, T_d - t_l)).
Up to constants the expected complete-data log-likelihood minus the L1 penalty
sum_ij lam_ij n_ij (lam_ij = l1 on penalized cells, see l1_weights) is
    Q = sum_ij S_ij log n_ij + sum_cm S_cm log w_cm - sum_ij n_ij (sum_m w_cm G_ijm + lam_ij).
Two closed-form conditional maximizations each raise Q:
  1. n given w:  n_ij = S_ij / (sum_m w_cm G_ijm + lam_ij).
  2. w and the scale s_c of n within class c, given n's within-class ratios.
     With theta_cm = s_c w_cm, Q restricted to class c is
     sum_m S_cm log theta_cm - theta_cm sum_{ij in c} n_ij (G_ijm + lam_ij), so
     theta_cm = S_cm / sum_{ij in c} n_ij (G_ijm + lam_ij); then s_c = sum_m theta_cm,
     w_c = theta_c / s_c and n_ij <- s_c n_ij (alpha unchanged when lam = 0).
Each CM step raises Q, so the observed-data objective never decreases (ECM,
Meng & Rubin 1993). Q is concave in (log n, log theta), so cycling the two
steps approaches the full M-step; ECM_CYCLES cycles run per E-step. "cell" has
the joint closed form alpha_ijm = S_ijm / (W_ijm + lam_ij F_m), W_ijm = G_ijm F_m.

Concavity. With kernel_sharing="cell" the observed log-likelihood is concave
in (mu, alpha) (lambda is linear in them), so every local maximum is global.
With shared kernels alpha = n w / F is bilinear in (n, w), and the observed
log-likelihood is not jointly concave: real and simulated windows have several
local maxima, which differ mostly in the shape of exogenous classes with few
events. Shared-kernel fits therefore run from several starts and finish with
projected Newton steps that certify a local maximum (see fit).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import polars as pl
from numba import njit

BETAS = (1 / 60, 1 / 600, 1 / 3600)
SHARES = ("baseline", "human", "other_agents", "self")
DEFAULT_EXO = ("human", "system")
SHARING = ("cell", "class", "global")
L1_SCOPES = ("all", "cross")
BACKGROUND = "background"
# EM stopping rule, common to fits and bootstrap refits (see fit()); XTOL applies to "cell" fits.
TOL = 1e-8
XTOL = 1e-5
MAX_ITER = 2000
ECM_CYCLES = 3
# Shared kernels: a fit is converged when the Newton model predicts at most NEWTON_TOL
# nats of further gain at a point where the reduced Hessian is negative definite.
NEWTON_TOL = 1e-6
NEWTON_STEPS = 50
NEWTON_ROUNDS = 3
# Starts of fits without init: "default" (uniform alpha) and warm starts from a fit
# with another kernel_sharing; the start with the highest objective is kept.
STARTS = {"cell": ("default",), "class": ("default", "global", "cell"), "global": ("default", "cell")}
_BOUND = 1e-9  # parameters at most this far above 0 count as on the bound in the Newton steps


def default_exo_names(H: int) -> tuple[str, ...]:
    """("human",) for one exogenous source, ("human", "system") for two."""
    if not 1 <= H <= len(DEFAULT_EXO):
        raise ValueError(f"name the {H} exogenous sources with exo_names")
    return DEFAULT_EXO[:H]


def share_names(exo_names: tuple[str, ...]) -> tuple[str, ...]:
    """Decomposition categories: baseline, one per exogenous source, other agents, self."""
    return ("baseline", *exo_names, "other_agents", "self")


def kernel_classes(K: int, exo_names: tuple[str, ...], sharing: str,
                   tie_exo: tuple[str, ...] = ()) -> tuple[np.ndarray, tuple[str, ...]]:
    """(K, K + H) class index of each cell and the class names. tie_exo (only with "class")
    puts the cells of those exogenous sources into the "other" class."""
    H = len(exo_names)
    if tie_exo and (sharing != "class" or not set(tie_exo) <= set(exo_names)):
        raise ValueError(f"tie_exo needs kernel_sharing='class' and names from {exo_names}")
    if sharing == "cell":
        names = tuple(f"{i}<-{j}" for i in range(K) for j in range(K + H))
        return np.arange(K * (K + H)).reshape(K, K + H), names
    if sharing == "class":
        own = tuple(x for x in exo_names if x not in tie_exo)
        cls = np.ones((K, K + H), np.int64)
        cls[np.arange(K), np.arange(K)] = 0
        cls[:, K:] = [1 if x in tie_exo else 2 + own.index(x) for x in exo_names]
        return cls, ("self", "other", *own)
    if sharing == "global":
        return np.zeros((K, K + H), np.int64), ("all",)
    raise ValueError(f"kernel_sharing must be one of {SHARING}")


def l1_weights(K: int, H: int, scope: str) -> np.ndarray:
    """(K, K + H) cells the L1 penalty applies to: "all", or "cross" (agent j != i only;
    self-excitation and exogenous sources unpenalized)."""
    if scope == "all":
        return np.ones((K, K + H))
    if scope == "cross":
        p = np.zeros((K, K + H))
        p[:, :K] = 1.0 - np.eye(K)
        return p
    raise ValueError(f"l1_scope must be one of {L1_SCOPES}")


@dataclass(frozen=True)
class HawkesSpec:
    """Fixed model settings: kernel rates beta_m (1/s), max lag L (s), baseline bins."""

    betas: tuple[float, ...] = BETAS
    max_lag: float = 3 * 3600.0
    n_bins: int = 8
    bin_width: float = 3600.0

    @classmethod
    def from_config(cls, cfg: dict) -> HawkesSpec:
        h = cfg.get("hawkes", cfg)
        return cls(tuple(float(b) for b in h["betas_per_s"]),
                   float(h["max_lag_hours"]) * 3600.0, int(h["baseline_hour_bins"]))

    @property
    def M(self) -> int:
        return len(self.betas)

    @property
    def beta(self) -> np.ndarray:
        return np.asarray(self.betas, dtype=np.float64)

    @property
    def trunc(self) -> np.ndarray:
        """F_m = 1 - exp(-beta_m L), the kernel mass inside (0, L]."""
        return -np.expm1(-self.beta * self.max_lag)

    def bins(self, t: np.ndarray, T: float) -> np.ndarray:
        """b(t) = min(floor(t / width), n_bins - 1). An event at t == T on a bin edge
        takes the bin to its left (left-continuous baseline), so its bin has exposure."""
        t = np.asarray(t, dtype=np.float64)
        f = np.floor(t / self.bin_width)
        edge = (t == T) & (t > 0) & (f * self.bin_width == t) & (f <= self.n_bins - 1)
        return np.minimum(f - edge, self.n_bins - 1).astype(np.int64)

    def exposure(self, T: float) -> np.ndarray:
        """|B_b ∩ [0, T]| for each bin."""
        lo = np.arange(self.n_bins) * self.bin_width
        hi = lo + self.bin_width
        hi[-1] = np.inf
        return np.clip(np.minimum(T, hi) - lo, 0.0, None)

    def branching(self, alpha: np.ndarray) -> np.ndarray:
        """n_ij = sum_m alpha_ij^(m) (1 - exp(-beta_m L))."""
        return alpha @ self.trunc

    def alpha_from(self, n: np.ndarray, w: np.ndarray) -> np.ndarray:
        """alpha_ij^(m) = n_ij w_ijm / F_m, w (..., M) the per-cell mixture weights."""
        return n[..., None] * w / self.trunc


@dataclass
class Day:
    """One run day on [0, T]: agent events (time, agent index) and H >= 1
    exogenous sources. Give human_times (H = 1) or exo_times, one array per
    source in the order of pack's exo_names; exo_times is filled from
    human_times when absent. After construction human_times and human_uids
    always hold source 0 (exo_times[0], exo_uids[0]). Both may be given when
    they agree, so dataclasses.replace and copies work. present (K,) marks the
    agents present that day (module docstring); None means all."""

    T: float
    agent_times: np.ndarray
    agent_dims: np.ndarray
    human_times: np.ndarray = field(default_factory=lambda: np.empty(0))
    agent_uids: np.ndarray | None = None
    human_uids: np.ndarray | None = None
    exo_times: tuple[np.ndarray, ...] | None = None
    exo_uids: tuple[np.ndarray | None, ...] | None = None
    present: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.present is not None:
            self.present = np.asarray(self.present, dtype=bool)
        human = np.asarray(self.human_times, dtype=np.float64)
        if self.exo_times is None:
            self.exo_times = (human,)
            self.exo_uids = (self.human_uids,) if self.exo_uids is None else tuple(self.exo_uids)
        else:
            self.exo_times = tuple(np.asarray(x, dtype=np.float64) for x in self.exo_times)
            self.exo_uids = (None,) * len(self.exo_times) if self.exo_uids is None else tuple(self.exo_uids)
            if self.exo_times and human.size and not np.array_equal(human, self.exo_times[0]):
                raise ValueError("human_times must equal exo_times[0] when both are given")
            if self.exo_uids and self.human_uids is not None and (
                    self.exo_uids[0] is None or not np.array_equal(np.asarray(self.human_uids, dtype=object),
                                                                   np.asarray(self.exo_uids[0], dtype=object))):
                raise ValueError("human_uids must equal exo_uids[0] when both are given")
        if not self.exo_times or len(self.exo_uids) != len(self.exo_times):
            raise ValueError("exo_times needs at least one source and matching exo_uids")
        self.human_times, self.human_uids = self.exo_times[0], self.exo_uids[0]

    @property
    def H(self) -> int:
        return len(self.exo_times)


@dataclass
class HawkesFit:
    spec: HawkesSpec
    mu: np.ndarray        # (K, n_bins), events / s
    alpha: np.ndarray     # (K, K + H, M); columns K.. are the exogenous sources
    loglik: np.ndarray    # log-likelihood of the iterate at each iteration (EM, then Newton steps)
    objective: np.ndarray  # loglik - l1 * sum of penalized n; equals loglik when l1 == 0
    n_iter: int
    converged: bool
    n_violations: int     # objective decreases beyond 1e-9 relative
    l1: float = 0.0
    exo_names: tuple[str, ...] = ("human",)
    kernel_sharing: str = "cell"
    w: np.ndarray | None = None  # (C, M) class mixture weights; None for "cell"
    l1_scope: str = "all"
    start: str = "default"                 # start this fit came from ("init" for a warm start)
    starts: tuple[str, ...] = ("default",)  # all starts tried (see fit)
    start_objective: np.ndarray | None = None  # final objective of each start, in `starts` order
    newton_gain: float = float("nan")  # remaining gain (nats) the Newton model predicts at the end; shared kernels
    tie_exo: tuple[str, ...] = ()       # exogenous sources tied to the "other" class (kernel_sharing="class")

    @property
    def start_spread(self) -> float:
        """Objective of the best start minus that of the worst (0 for a single start)."""
        so = self.start_objective
        return float(so.max() - so.min()) if so is not None and so.size else 0.0

    @property
    def K(self) -> int:
        return self.mu.shape[0]

    @property
    def H(self) -> int:
        return self.alpha.shape[1] - self.K

    @property
    def share_names(self) -> tuple[str, ...]:
        return share_names(self.exo_names)

    @property
    def classes(self) -> np.ndarray:
        """(K, K + H) kernel class of each cell."""
        return kernel_classes(self.K, self.exo_names, self.kernel_sharing, self.tie_exo)[0]

    @property
    def class_names(self) -> tuple[str, ...]:
        return kernel_classes(self.K, self.exo_names, self.kernel_sharing, self.tie_exo)[1]

    @property
    def n(self) -> np.ndarray:
        """Branching matrix N, (K, K + H): rows agents, columns agents then exogenous sources."""
        return self.spec.branching(self.alpha)

    @property
    def rho(self) -> float:
        """Spectral radius of the agent-agent block of N."""
        return spectral_radius(self.n[:, : self.K])

    @property
    def weights(self) -> np.ndarray:
        """(K, K + H, M) kernel mixture weights per cell, alpha F / n; nan where n == 0."""
        n = self.n[..., None]
        return np.divide(self.alpha * self.spec.trunc, n, out=np.full_like(self.alpha, np.nan), where=n > 0)

    def kernel(self, i: int, j: int, tau: np.ndarray) -> np.ndarray:
        """Normalized kernel g_ij(tau) on (0, L]; zero where n_ij == 0. With
        kernel_sharing="cell" the shape of a single cell is weakly identified (it
        trades off against the baseline and the other kernel components), so check
        it before using it as an interval law."""
        tau = np.asarray(tau, dtype=np.float64)
        nij = self.n[i, j]
        if nij <= 0:
            return np.zeros_like(tau)
        b = self.spec.beta
        g = (self.alpha[i, j] * b * np.exp(-np.multiply.outer(tau, b))).sum(-1) / nij
        return np.where((tau > 0) & (tau <= self.spec.max_lag), g, 0.0)


def spectral_radius(a: np.ndarray) -> float:
    return float(np.abs(np.linalg.eigvals(a)).max()) if a.size else 0.0


# --- packing: sparse candidate-parent lists --------------------------------


@njit(cache=True, error_model="numpy")
def _day_pairs(t, src, K, L):
    """For each agent event q of one day (t sorted), parents are the contiguous
    range [lo, hi) of earlier events with 0 < t[q] - t[l] <= L."""
    n_tgt = 0
    for q in range(t.shape[0]):
        if src[q] < K:
            n_tgt += 1
    tgt = np.empty(n_tgt, np.int64)
    lo = np.empty(n_tgt, np.int64)
    hi = np.empty(n_tgt, np.int64)
    k = 0
    for q in range(t.shape[0]):
        if src[q] >= K:
            continue
        h = q
        while h > 0 and t[h - 1] == t[q]:
            h -= 1
        l = h
        while l > 0 and t[q] - t[l - 1] <= L:
            l -= 1
        tgt[k], lo[k], hi[k] = q, l, h
        k += 1
    return tgt, lo, hi


@dataclass
class Packed:
    """All days flattened. Events are merged per day and sorted by time;
    targets are the agent events, pairs are (target, candidate parent)."""

    K: int
    spec: HawkesSpec
    ev_t: np.ndarray       # (E,) merged event times
    ev_src: np.ndarray     # (E,) 0..K-1 agent, K + h exogenous source h
    ev_uid: np.ndarray     # (E,) object
    ev_off: np.ndarray     # (D + 1,) day offsets into events
    tgt_ev: np.ndarray     # (N,) event index of each target
    tgt_day: np.ndarray    # (N,)
    tgt_dim: np.ndarray    # (N,)
    tgt_bin: np.ndarray    # (N,)
    tgt_lo: np.ndarray     # (N,) first event index within L (events before it are older than L)
    ptr: np.ndarray        # (N + 1,) CSR pointers into pairs
    par_ev: np.ndarray     # (P,) event index of the parent
    par_src: np.ndarray    # (P,)
    dt: np.ndarray         # (P,)
    phi: np.ndarray        # (P, M) beta_m exp(-beta_m dt)
    W: np.ndarray          # (D, K + H, M) sum over source events of 1 - exp(-beta_m min(L, T - t_l))
    E: np.ndarray          # (D, n_bins) exposure per bin
    day_T: np.ndarray      # (D,) day lengths
    exo_names: tuple[str, ...] = ("human",)
    present: np.ndarray | None = None  # (D, K) agents present on each day; pack sets it (all True by default)

    def __post_init__(self) -> None:
        if self.present is None:
            self.present = np.ones((self.E.shape[0], self.K), bool)

    @property
    def n_days(self) -> int:
        return self.E.shape[0]

    @property
    def H(self) -> int:
        return len(self.exo_names)

    def exposure(self, w_day: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-target exposures under day weights w_day: E (K, n_bins), the baseline time of each
        target, and W (K, K + H, M), the edge-truncated kernel mass of each source's events, both
        summed over the days the target is present."""
        wp = np.asarray(w_day, dtype=np.float64)[:, None] * self.present
        return wp.T @ self.E, np.einsum("dk,djm->kjm", wp, self.W)

    def source_counts(self) -> np.ndarray:
        """(D, K + H) events of each source on each day."""
        day = np.repeat(np.arange(self.n_days), np.diff(self.ev_off))
        return np.bincount(day * (self.K + self.H) + self.ev_src, minlength=self.n_days * (self.K + self.H)
                           ).reshape(self.n_days, self.K + self.H).astype(np.float64)

    def exo_times(self) -> list[tuple[np.ndarray, ...]]:
        """Per day, the event times of each exogenous source."""
        return [tuple(self.ev_t[a:b][self.ev_src[a:b] == self.K + h] for h in range(self.H))
                for a, b in zip(self.ev_off[:-1], self.ev_off[1:])]

    def human_times(self) -> list[np.ndarray]:
        """Per day, the times of the first exogenous source."""
        return [x[0] for x in self.exo_times()]

    def counts(self, w_day: np.ndarray) -> np.ndarray:
        return np.bincount(self.tgt_dim, weights=w_day[self.tgt_day], minlength=self.K)


def _packed(days: list[Day] | Packed, K: int, spec: HawkesSpec | None,
            exo_names: tuple[str, ...] | None = None) -> Packed:
    """Pack days, or check that a prebuilt Packed matches K, spec and exo_names."""
    if not isinstance(days, Packed):
        return pack(days, K, spec, exo_names=exo_names)
    if K != days.K or (spec is not None and spec != days.spec):
        raise ValueError(f"Packed was built for K={days.K}, {days.spec}; got K={K}, {spec}")
    if exo_names is not None and tuple(exo_names) != days.exo_names:
        raise ValueError(f"Packed has exogenous sources {days.exo_names}, got {tuple(exo_names)}")
    return days


def _check_params(pk: Packed, mu: np.ndarray, alpha: np.ndarray) -> None:
    """The numba kernels do no bounds checks, so shapes must match the packed data."""
    K, nb, M = pk.K, pk.spec.n_bins, pk.spec.M
    if np.shape(mu) != (K, nb) or np.shape(alpha) != (K, K + pk.H, M):
        raise ValueError(f"expected mu {(K, nb)} and alpha {(K, K + pk.H, M)}, "
                         f"got {np.shape(mu)} and {np.shape(alpha)}")


def _check_fit(pk: Packed, fit: HawkesFit) -> None:
    if fit.spec != pk.spec:
        raise ValueError("fit and packed data use different HawkesSpec settings")
    if tuple(fit.exo_names) != pk.exo_names:
        raise ValueError(f"fit has exogenous sources {fit.exo_names}, data {pk.exo_names}")
    _check_params(pk, fit.mu, fit.alpha)


def _check_day(d: Day, K: int, H: int, idx: int) -> None:
    if not d.T > 0:
        raise ValueError(f"day {idx}: T must be > 0 (drop zero-length run days)")
    if d.H != H:
        raise ValueError(f"day {idx}: {d.H} exogenous sources, expected {H}")
    named = [("agent_times", d.agent_times)] + [(f"exo_times[{h}]", x) for h, x in enumerate(d.exo_times)]
    for name, x in named:
        x = np.asarray(x, dtype=np.float64)
        if x.size and (x.min() < 0 or x.max() > d.T or not np.isfinite(x).all()):
            raise ValueError(f"day {idx}: {name} outside [0, T]")
    dims = np.asarray(d.agent_dims)
    if dims.size != np.asarray(d.agent_times).size:
        raise ValueError(f"day {idx}: agent_times and agent_dims differ in length")
    for u, t in ((d.agent_uids, d.agent_times), *zip(d.exo_uids, d.exo_times)):
        if u is not None and len(u) != np.size(t):
            raise ValueError(f"day {idx}: uids and times differ in length")
    if dims.size and (dims.min() < 0 or dims.max() >= K):
        raise ValueError(f"day {idx}: agent_dims outside 0..{K - 1}")
    if d.present is not None:
        if d.present.shape != (K,):
            raise ValueError(f"day {idx}: present must have shape ({K},)")
        if dims.size and not d.present[dims].all():
            raise ValueError(f"day {idx}: events of an agent that is not present")


def pack(days: list[Day], K: int, spec: HawkesSpec | None = None, *,
         exo_names: tuple[str, ...] | None = None) -> Packed:
    """Validate days and build the candidate-parent lists; reuse the result
    across fit, decompose, bootstrap and time_rescaling. exo_names labels the
    days' exogenous sources (default ("human",) or ("human", "system")).
    Packed.present (D, K) holds each day's presence mask (all True for a day
    without one)."""
    spec = spec or HawkesSpec()
    H = days[0].H if days else len(exo_names or ("human",))
    exo_names = tuple(exo_names) if exo_names is not None else default_exo_names(H)
    if len(exo_names) != H or len(set(exo_names)) != H:
        raise ValueError(f"exo_names {exo_names} must name the {H} exogenous sources uniquely")
    beta, L, M = spec.beta, float(spec.max_lag), spec.M
    ev_t, ev_src, ev_uid, tgt_ev, tgt_day, tgt_bin, lo_l, hi_l = ([] for _ in range(8))
    W = np.zeros((len(days), K + H, M))
    E = np.zeros((len(days), spec.n_bins))
    present = np.ones((len(days), K), bool)
    ev_off = np.zeros(len(days) + 1, np.int64)
    for d, day in enumerate(days):
        _check_day(day, K, H, d)
        if day.present is not None:
            present[d] = day.present
        at = np.asarray(day.agent_times, dtype=np.float64)
        au = day.agent_uids if day.agent_uids is not None else [f"d{d}:a{k}" for k in range(at.size)]
        ts, srcs, uids = [at], [np.asarray(day.agent_dims, dtype=np.int64)], [np.asarray(au, dtype=object)]
        for h, (xt, xu) in enumerate(zip(day.exo_times, day.exo_uids)):
            tag = "h" if h == 0 else f"x{h}_"
            ts.append(xt), srcs.append(np.full(xt.size, K + h, np.int64))
            xu = xu if xu is not None else [f"d{d}:{tag}{k}" for k in range(xt.size)]
            uids.append(np.asarray(xu, dtype=object))
        t, src, uid = np.concatenate(ts), np.concatenate(srcs), np.concatenate(uids)
        order = np.argsort(t, kind="stable")
        t, src, uid = t[order], src[order], uid[order]
        tg, lo, hi = _day_pairs(t, src, K, L)
        off = ev_off[d]
        ev_t.append(t), ev_src.append(src), ev_uid.append(uid)
        tgt_ev.append(tg + off), lo_l.append(lo + off), hi_l.append(hi + off)
        tgt_day.append(np.full(tg.size, d, np.int64)), tgt_bin.append(spec.bins(t[tg], day.T))
        integ = -np.expm1(-np.outer(np.minimum(L, day.T - t), beta))
        for m in range(M):
            W[d, :, m] = np.bincount(src, weights=integ[:, m], minlength=K + H)
        E[d] = spec.exposure(day.T)
        ev_off[d + 1] = off + t.size

    def cat(xs, dtype):
        return np.concatenate(xs).astype(dtype) if xs else np.empty(0, dtype)

    ev_t, ev_src, ev_uid = cat(ev_t, np.float64), cat(ev_src, np.int64), cat(ev_uid, object)
    tgt_ev, tgt_day, tgt_bin = cat(tgt_ev, np.int64), cat(tgt_day, np.int64), cat(tgt_bin, np.int64)
    lo, hi = cat(lo_l, np.int64), cat(hi_l, np.int64)
    cnt = hi - lo
    ptr = np.zeros(tgt_ev.size + 1, np.int64)
    np.cumsum(cnt, out=ptr[1:])
    par_ev = np.repeat(lo - ptr[:-1], cnt) + np.arange(ptr[-1])
    dt = np.repeat(ev_t[tgt_ev], cnt) - ev_t[par_ev]
    return Packed(
        K=K, spec=spec, ev_t=ev_t, ev_src=ev_src, ev_uid=ev_uid, ev_off=ev_off,
        tgt_ev=tgt_ev, tgt_day=tgt_day, tgt_dim=ev_src[tgt_ev], tgt_bin=tgt_bin,
        tgt_lo=lo, ptr=ptr, par_ev=par_ev, par_src=ev_src[par_ev], dt=dt,
        phi=beta * np.exp(-np.multiply.outer(dt, beta)), W=W, E=E,
        day_T=np.array([float(d.T) for d in days]), exo_names=exo_names, present=present,
    )


# --- EM ----------------------------------------------------------------------


@njit(cache=True, error_model="numpy")
def _estep(mu, alpha, w, tgt_dim, tgt_bin, ptr, par_src, phi):
    """Weighted sum of log lambda at targets and the EM numerators."""
    M = phi.shape[1]
    mu_num = np.zeros_like(mu)
    a_num = np.zeros_like(alpha)
    s = 0.0
    for k in range(tgt_dim.shape[0]):
        wk = w[k]
        if wk == 0.0:
            continue
        i, b = tgt_dim[k], tgt_bin[k]
        lam = mu[i, b]
        for p in range(ptr[k], ptr[k + 1]):
            j = par_src[p]
            for m in range(M):
                lam += alpha[i, j, m] * phi[p, m]
        s += wk * np.log(lam)
        c = wk / lam
        mu_num[i, b] += mu[i, b] * c
        for p in range(ptr[k], ptr[k + 1]):
            j = par_src[p]
            for m in range(M):
                a_num[i, j, m] += alpha[i, j, m] * phi[p, m] * c
    return s, mu_num, a_num


@njit(cache=True, error_model="numpy")
def _posterior(mu, alpha, w, tgt_dim, tgt_bin, ptr, par_src, phi):
    """Per-target background probability and per-pair parent probability
    (summed over m). Targets with zero weight get zeros."""
    M = phi.shape[1]
    p0 = np.zeros(tgt_dim.shape[0])
    pp = np.zeros(par_src.shape[0])
    for k in range(tgt_dim.shape[0]):
        if w[k] == 0.0:
            continue
        i = tgt_dim[k]
        lam = mu[i, tgt_bin[k]]
        for p in range(ptr[k], ptr[k + 1]):
            v = 0.0
            for m in range(M):
                v += alpha[i, par_src[p], m] * phi[p, m]
            pp[p] = v
            lam += v
        p0[k] = mu[i, tgt_bin[k]] / lam
        for p in range(ptr[k], ptr[k + 1]):
            pp[p] /= lam
    return p0, pp


@njit(cache=True, error_model="numpy")
def _shared_grad_hess(mu, n, wc, cls, finv, w, tgt_dim, tgt_bin, ptr, par_src, phi):
    """s = sum_k w_k log lambda_k with alpha_ijm = n_ij wc_{cls[i,j],m} finv_m, and its
    gradient and Hessian in theta = (mu.ravel(), n.ravel(), wc.ravel())."""
    K, nb = mu.shape
    KH = n.shape[1]
    C, M = wc.shape
    n0 = K * nb
    w0 = n0 + K * KH
    P = w0 + C * M
    g = np.zeros(P)
    hess = np.zeros((P, P))
    u = np.zeros(KH)           # d lambda / d n_ij
    q = np.zeros((KH, M))      # d2 lambda / d n_ij d w_{cls[i,j], m}
    v = np.zeros(C * M)        # d lambda / d w_cm
    mark = np.zeros(KH, np.int64)
    touched = np.empty(KH, np.int64)
    idx = np.empty(1 + KH + C * M, np.int64)
    val = np.empty(1 + KH + C * M)
    s = 0.0
    for k in range(tgt_dim.shape[0]):
        wk = w[k]
        if wk == 0.0:
            continue
        i, b = tgt_dim[k], tgt_bin[k]
        nt = 0
        for p in range(ptr[k], ptr[k + 1]):
            j = par_src[p]
            c = cls[i, j]
            if mark[j] != k + 1:
                mark[j] = k + 1
                touched[nt] = j
                nt += 1
                u[j] = 0.0
                for m in range(M):
                    q[j, m] = 0.0
            for m in range(M):
                f = phi[p, m] * finv[m]
                u[j] += wc[c, m] * f
                q[j, m] += f
                v[c * M + m] += n[i, j] * f
        lam = mu[i, b]
        for t in range(nt):
            lam += n[i, touched[t]] * u[touched[t]]
        s += wk * np.log(lam)
        a = wk / lam
        e = 1
        idx[0], val[0] = i * nb + b, 1.0
        for t in range(nt):
            idx[e], val[e] = n0 + i * KH + touched[t], u[touched[t]]
            e += 1
        for cm in range(C * M):
            if v[cm] != 0.0:
                idx[e], val[e] = w0 + cm, v[cm]
                e += 1
                v[cm] = 0.0
        a2 = a / lam
        for x in range(e):
            g[idx[x]] += a * val[x]
            ax = a2 * val[x]
            for y in range(e):
                hess[idx[x], idx[y]] -= ax * val[y]
        for t in range(nt):
            j = touched[t]
            r, c0 = n0 + i * KH + j, w0 + cls[i, j] * M
            for m in range(M):
                hess[r, c0 + m] += a * q[j, m]
                hess[c0 + m, r] += a * q[j, m]
    return s, g, hess


def _integral(mu, alpha, E, W) -> float:
    """sum_i int lambda_i with per-target exposures E (K, n_bins) and W (K, K + H, M)."""
    return float((mu * E).sum() + (alpha * W).sum())


def _loglik(pk: Packed, mu, alpha, w_day) -> float:
    s, _, _ = _estep(mu, alpha, w_day[pk.tgt_day], pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
    return s - _integral(mu, alpha, *pk.exposure(w_day))


def _init(pk: Packed, w_day: np.ndarray, init) -> tuple[np.ndarray, np.ndarray]:
    K, M, nb, H = pk.K, pk.spec.M, pk.spec.n_bins, pk.H
    rate = pk.counts(w_day) / np.maximum(pk.exposure(w_day)[0].sum(1), 1e-300)
    if init is None:
        return np.repeat(rate[:, None], nb, 1), np.full((K, K + H, M), 0.1 / ((K + H) * M))
    mu, alpha = (np.array(x, dtype=np.float64) for x in init)
    _check_params(pk, mu, alpha)
    # A warm start must keep lambda > 0 wherever events exist.
    return np.maximum(mu, 1e-3 * rate[:, None]), alpha


def _class_split(alpha: np.ndarray, cls: np.ndarray, C: int, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project alpha onto the shared model: n = branching, w_c = pooled shape of class c."""
    mass = alpha * F
    n = mass.sum(-1)
    pooled = np.stack([np.bincount(cls.ravel(), weights=mass[..., m].ravel(), minlength=C)
                       for m in range(F.size)], 1)
    tot = pooled.sum(1, keepdims=True)
    w = np.divide(pooled, tot, out=np.full_like(pooled, 1.0 / F.size), where=tot > 0)
    return n, w


def _class_sum(x: np.ndarray, cls: np.ndarray, C: int) -> np.ndarray:
    """(C, M) sums of x (K, K + H, M) over the cells of each class."""
    return np.stack([np.bincount(cls.ravel(), weights=x[..., m].ravel(), minlength=C)
                     for m in range(x.shape[-1])], 1)


def _ecm(n, wc, S, G, cls, C, lam, cycles):
    """ECM cycles of the shared-kernel M-step (module docstring); S (K, K + H, M)
    responsibility sums, G (K, K + H, M) per-target edge-truncated exposures (or (K + H, M) when
    every target has the same), lam (K, K + H) or scalar."""
    lam = np.broadcast_to(lam, S.shape[:2])
    S_ij = S.sum(-1)
    S_c = _class_sum(S, cls, C)
    for _ in range(cycles):
        den = (wc[cls] * G).sum(-1) + lam
        n = np.divide(S_ij, den, out=np.zeros_like(S_ij), where=den > 0)
        D = _class_sum(n[..., None] * (G + lam[..., None]), cls, C)
        theta = np.divide(S_c, D, out=np.zeros_like(S_c), where=D > 0)
        s = theta.sum(1)
        live = s > 0
        wc = np.where(live[:, None], theta / np.where(live, s, 1.0)[:, None], wc)
        n = n * np.where(live, s, 1.0)[cls]
    return n, wc


def _extrapolate(x0, x1, r, v, g):
    """SQUAREM point x0 - 2 g r + g^2 v, floored at a fraction of the EM step
    (EM cannot revive an exact zero)."""
    return tuple(np.maximum(a - 2 * g * dr + g * g * dv, 1e-3 * b) for a, b, dr, dv in zip(x0, x1, r, v))


def _rel_step(x0, x1) -> float:
    """Largest relative change, in L2 norm per block, from x0 to x1."""
    return max(float(np.linalg.norm(b - a) / max(np.linalg.norm(a), 1e-300)) for a, b in zip(x0, x1))


def _newton_shared(pk: Packed, w, E, W, cls, C, lam, x, steps=NEWTON_STEPS, tol=NEWTON_TOL):
    """Projected Newton steps on the shared-kernel objective in x = (mu, n, w).

    Active set (Bertsekas 1982): a parameter whose gradient points out of the
    feasible set (for w: below the class's weighted mean gradient) is held at 0
    when it is within _BOUND of 0 or a one-dimensional Newton step would take it
    below 0; its step moves it to 0. All other parameters are free, including
    ones at 0 with a positive gradient, which EM can only revive geometrically.
    w moves within the simplex of its class. On the free set the direction is
    the Newton step of the Jacobi-scaled Hessian with eigenvalues replaced by
    their absolute values, an ascent direction also where the objective is not
    locally concave. A step is kept only if the objective rises after
    projecting mu, n >= 0 and w onto the simplex (clip and renormalize), halving
    it up to 40 times. Certified when the free-set Hessian is negative definite
    and the predicted remaining gain (Newton decrement g' (-H)^-1 g / 2 on the
    free set plus the first-order gain of moving the active set to 0) is at
    most tol nats. E (K, n_bins) and W (K, K + H, M) are the per-target
    exposures. Returns (x, [(loglik, objective) per step], certified, gain)."""
    F = pk.spec.trunc
    G = W / F
    K, KH, nb, M = pk.K, pk.K + pk.H, pk.spec.n_bins, pk.spec.M
    n0, w0 = K * nb, K * nb + K * KH
    P = w0 + C * M
    shape = ((K, nb), (K, KH), (C, M))
    lam = np.broadcast_to(lam, (K, KH))
    expo = np.concatenate([E.ravel(), np.ones(P - n0)])   # mu is measured in expected events

    def evaluate(mu, n, wc):
        a = n[..., None] * wc[cls] / F
        s, _, _ = _estep(mu, a, w, pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
        ll = s - _integral(mu, a, E, W)
        return ll, ll - float((lam * n).sum())

    def grad_hess(mu, n, wc):
        _, g, hess = _shared_grad_hess(mu, n, wc, cls, 1.0 / F, w, pk.tgt_dim, pk.tgt_bin, pk.ptr,
                                       pk.par_src, pk.phi)
        g[:n0] -= E.ravel()
        g[n0:w0] -= ((wc[cls] * G).sum(-1) + lam).ravel()
        g[w0:] -= _class_sum(n[..., None] * G, cls, C).ravel()
        rows = n0 + np.arange(K * KH)
        for m in range(M):          # d2 integral / d n_ij d w_cm = G_ijm, c = cls[i, j]
            cols = w0 + cls.ravel() * M + m
            gm = G[..., m].ravel()
            hess[rows, cols] -= gm
            hess[cols, rows] -= gm
        return g, hess

    mu, n, wc = x
    ll, obj = evaluate(mu, n, wc)
    out, certified, gain = [], False, np.inf
    for it in range(steps + 1):
        g, hess = grad_hess(mu, n, wc)
        theta = np.concatenate([mu.ravel(), n.ravel(), wc.ravel()])
        live = _class_sum(n[..., None], cls, C)[:, 0] > _BOUND
        gd = g.copy()               # gradient along the feasible directions: w relative to its class mean
        gd[w0:] -= np.repeat((wc * g[w0:].reshape(C, M)).sum(1), M)
        step1 = np.abs(gd) / np.maximum(np.abs(np.diag(hess)), 1e-300)
        fixed = np.zeros(P, bool)
        fixed[:n0] = (E <= 0).ravel()
        fixed[w0:] = np.repeat(~live, M)
        active = ~fixed & (gd <= 0) & ((theta * expo <= _BOUND) | (theta <= step1))
        free = ~fixed & ~active
        fi = np.flatnonzero(free[:w0])
        free_w = free[w0:].reshape(C, M)
        basis = []                  # w directions e_m - e_last within each class's free components
        for c in range(C):
            ms = np.flatnonzero(free_w[c])
            for m in ms[:-1]:
                z = np.zeros(C * M)
                z[c * M + m], z[c * M + ms[-1]] = 1.0, -1.0
                basis.append(z)
        Z = np.array(basis).reshape(-1, C * M).T
        gain_active = float(np.abs(gd[active] * theta[active]).sum())
        hz = np.block([[hess[np.ix_(fi, fi)], hess[fi, w0:] @ Z],
                       [Z.T @ hess[w0:, fi], Z.T @ hess[w0:, w0:] @ Z]])
        gz = np.concatenate([g[fi], Z.T @ g[w0:]])
        if gz.size:
            d = np.sqrt(np.abs(np.diag(hz)))
            d[d == 0] = 1.0
            ev, V = np.linalg.eigh(-hz / d[:, None] / d[None, :])
            top = max(float(np.abs(ev).max()), 1e-300)
            y = V.T @ (gz / d)
            evm = np.maximum(np.abs(ev), 1e-10 * top)
            concave = ev.min() > 1e-10 * top
            gain = float(y @ (y / evm)) / 2 + gain_active
        else:
            concave, gain = True, gain_active
        if concave and gain <= tol:
            certified = True
            break
        if it == steps:
            break
        delta = np.zeros(P)
        if gz.size:
            dz = (V @ (y / evm)) / d
            delta[fi] = dz[:fi.size]
            delta[w0:] = Z @ dz[fi.size:]
        delta[active] = -theta[active]
        t, new = 1.0, None
        for _ in range(40):
            th = theta + t * delta
            m1, n1, w1 = (np.maximum(th[a:b], 0.0).reshape(s) for a, b, s in zip((0, n0, w0), (n0, w0, P), shape))
            w1 = w1 / np.maximum(w1.sum(1, keepdims=True), 1e-300)
            ll1, obj1 = evaluate(m1, n1, w1)
            if np.isfinite(obj1) and obj1 > obj:
                new = (m1, n1, w1)
                break
            t /= 2
        if new is None:
            break
        mu, n, wc = new
        ll, obj = ll1, obj1
        out.append((ll, obj))
    return (mu, n, wc), out, certified, gain


def _em(pk: Packed, w_day, mu, alpha, l1, tol, xtol, max_iter, accelerate, sharing, l1_scope="all",
        cycles=ECM_CYCLES, newton=True, tie_exo=()):
    """EM / ECM with optional SQUAREM. The state x is (mu, alpha) for "cell" and
    (mu, n, w) for shared kernels; the objective is loglik - sum(lam * n). For
    shared kernels (and newton=True) each pass of the objective test is followed
    by projected Newton steps, which must certify the point (see fit); otherwise
    EM resumes from where they ended, up to NEWTON_ROUNDS times."""
    w = w_day[pk.tgt_day]
    E, W = pk.exposure(w_day)          # per target: (K, n_bins), (K, K + H, M)
    F = pk.spec.trunc
    cls, names = kernel_classes(pk.K, pk.exo_names, sharing, tie_exo)
    C = len(names)
    lam = l1 * l1_weights(pk.K, pk.H, l1_scope)
    if sharing == "cell":
        den_a = W + lam[..., None] * F

        def to_alpha(x):
            return x[1]

        def mstep(x, a_num):
            return (np.divide(a_num, den_a, out=np.zeros_like(a_num), where=den_a > 0),)

        def project(x):
            return x

        x0 = (mu, alpha)
    else:
        G = W / F

        def to_alpha(x):
            return x[1][..., None] * x[2][cls] / F

        def mstep(x, a_num):
            return _ecm(x[1], x[2], a_num, G, cls, C, lam, cycles)

        def project(x):
            wc = x[2] / np.maximum(x[2].sum(1, keepdims=True), 1e-300)
            return (x[0], x[1], wc)

        x0 = (mu, *_class_split(alpha, cls, C, F))

    def counts(x):
        """Expected event counts implied by x, per baseline bin and per kernel component:
        the blocks of the parameter-step test (see fit)."""
        return x[0] * E, to_alpha(x) * W

    def step(x):
        """E-step at x: (loglik, penalized objective, EM update of x)."""
        m, a = x[0], to_alpha(x)
        s, mu_num, a_num = _estep(m, a, w, pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
        ll = s - _integral(m, a, E, W)
        mu1 = np.divide(mu_num, E, out=np.zeros_like(m), where=E > 0)
        return ll, ll - float((lam * (a @ F)).sum()), (mu1, *mstep(x, a_num))

    ll0, obj0, x1 = step(x0)
    lls, objs = [ll0], [obj0]
    converged = False
    it = rounds = 0
    dec = np.nan
    use_newton = sharing != "cell" and newton   # shared kernels: the Newton stage replaces the step test
    while np.isfinite(obj0) and it < max_iter:
        ll1, obj1, x2 = step(x1)
        nxt = (x1, ll1, obj1, x2)
        if accelerate:
            # SQUAREM (Varadhan & Roland 2008), kept only if it beats the plain EM step.
            # A rejected step length g moves halfway to -1 (two EM steps), at most twice.
            r = [b - a for a, b in zip(x0, x1)]
            v = [c - 2 * b + a for a, b, c in zip(x0, x1, x2)]
            nv = np.sqrt(sum((z * z).sum() for z in v))
            g = min(-np.sqrt(sum((z * z).sum() for z in r)) / nv, -1.0) if nv > 0 else -1.0
            for _ in range(3):
                if g >= -1.0:
                    break
                xp = project(_extrapolate(x0, x1, r, v, g))
                llp, objp, xp1 = step(xp)
                if np.isfinite(objp) and objp >= obj1:
                    nxt = (xp, llp, objp, xp1)
                    break
                g = (g - 1) / 2 if g <= -2.0 else -1.0
        x0, ll0, obj0, x1 = nxt
        lls.append(ll0), objs.append(obj0)
        it += 1
        # x1 is the EM update of the new x0.
        if not (abs(objs[-1] - objs[-2]) <= tol * abs(objs[-2])
                and (use_newton or _rel_step(counts(x0), counts(x1)) <= xtol)):
            continue
        if not use_newton:
            converged = True
            break
        x0, trace, converged, dec = _newton_shared(pk, w, E, W, cls, C, lam, x0, min(NEWTON_STEPS, max_iter - it))
        for a, b in trace:
            lls.append(a), objs.append(b)
        it += len(trace)
        rounds += 1
        if converged or rounds >= NEWTON_ROUNDS:
            break
        ll0, obj0, x1 = step(x0)
    if not np.isfinite(obj0):
        raise FloatingPointError("non-finite log-likelihood; an event has zero intensity")
    objs = np.asarray(objs)
    viol = int((np.diff(objs) < -1e-9 * np.abs(objs[:-1])).sum())
    if viol:
        warnings.warn(f"EM objective decreased in {viol} iterations", RuntimeWarning, stacklevel=3)
    wc = None if sharing == "cell" else x0[2]
    return x0[0], to_alpha(x0), wc, np.asarray(lls), objs, it, converged, viol, dec


def fit(days: list[Day] | Packed, K: int, spec: HawkesSpec | None = None, *, l1: float = 0.0,
        tol: float = TOL, xtol: float = XTOL, max_iter: int = MAX_ITER, accelerate: bool = True,
        init: tuple[np.ndarray, np.ndarray] | None = None, kernel_sharing: str = "cell",
        exo_names: tuple[str, ...] | None = None, l1_scope: str = "all",
        starts: tuple[str, ...] | None = None, tie_exo: tuple[str, ...] = ()) -> HawkesFit:
    """EM fit. `init` = (mu, alpha) warm start (projected onto the shared model
    when kernel_sharing is not "cell"); default mu = each dimension's average
    rate over the days it is present, alpha small and uniform. The days'
    presence masks (Day.present) give each target its own exposure (module
    docstring). l1 >= 0 is an L1 penalty on the branching
    ratios, objective = loglik - l1 * sum(n) over the cells chosen by l1_scope
    ("all", or "cross" for agent-to-other-agent cells only), with the MAP update
    n = S / (den + l1); every update is monotone in the penalized objective.

    kernel_sharing: "cell" (free kernel weights per cell, SPEC 5.2), "class"
    (one kernel shape for self, one for other agents, one per exogenous source)
    or "global" (one shape); see the module docstring for the ECM M-step.
    tie_exo (with "class") gives the named exogenous sources the "other" shape.

    Starts. The shared-kernel objective has several local maxima (module
    docstring), so without `init` a fit runs from each of `starts` and keeps
    the highest objective: "default" (uniform alpha), "global" and "cell" (warm
    starts from a fit with that kernel_sharing, same l1). The default is
    STARTS[kernel_sharing]: ("default", "global", "cell") for "class",
    ("default", "cell") for "global", ("default",) for "cell". The fit records
    start, starts, start_objective and start_spread (best minus worst start).

    Stopping, "cell" (concave objective): the objective changed by at most tol
    relative in the last iteration and a plain EM step from the current point
    moves mu and alpha by at most xtol relative, measured on the expected event
    counts they imply (mu * exposure per bin, alpha * W per kernel component; L2
    norm per block). The objective test alone (SPEC 5.3 uses tol=1e-6) stops
    early: the per-iteration gain is small along the baseline / slow-kernel
    ridge long before the maximum, by several nats at 1e-6, enough to move
    shares by 0.05.
    Shared kernels: no EM test is reliable. Along flat (n, w) ridges the step
    dips below any fixed xtol while the objective still rises (fits ended 0.1-1.9
    nats short at xtol=1e-5, some still 0.3 short at 1e-7), and EM cannot revive
    a branching ratio that has collapsed to ~0 although its gradient is
    positive. Once the objective test passes, projected Newton steps on the
    observed objective (_newton_shared) take over, and converged=True only when
    the reduced Hessian is negative definite and the gain a quadratic model
    still predicts is at most NEWTON_TOL = 1e-6 nats; otherwise EM resumes, up
    to NEWTON_ROUNDS times. xtol is not used. On 160 simulated windows and the
    real windows, continuing from such a fit with tol=1e-15 gains < 1e-4 nats.
    Newton steps count as iterations and are kept only if they raise the
    objective, so the trace stays monotone. converged=False after max_iter.

    accelerate=True adds a SQUAREM extrapolation to each iteration (two to four
    E-steps; a rejected step is shortened at most twice), kept only when it beats
    the plain EM step, so the objective stays monotone and the fixed point is the
    same. With kernel sharing it extrapolates (mu, n, w) and renormalizes w.
    accelerate=False gives the textbook iteration, which crawls along the ridge."""
    if l1 < 0:
        raise ValueError("l1 must be >= 0")
    pk = _packed(days, K, spec, exo_names)
    return _fit_pack(pk, np.ones(pk.n_days), l1=l1, tol=tol, xtol=xtol, max_iter=max_iter,
                     accelerate=accelerate, init=init, kernel_sharing=kernel_sharing, l1_scope=l1_scope,
                     starts=starts, tie_exo=tuple(tie_exo))


def _fit_pack(pk: Packed, w_day, *, l1=0.0, tol=TOL, xtol=XTOL, max_iter=MAX_ITER, accelerate=True,
              init=None, kernel_sharing="cell", l1_scope="all", starts=None, newton=True, tie_exo=()) -> HawkesFit:
    """fit() on packed data with day weights w_day; see fit for init and starts. Warm-start
    sub-fits ("global", "cell") never tie; the tie applies to the kernel_sharing fit."""
    kernel_classes(pk.K, pk.exo_names, kernel_sharing, tie_exo)  # validates the options
    l1_weights(pk.K, pk.H, l1_scope)
    kw = {"l1": l1, "tol": tol, "xtol": xtol, "max_iter": max_iter, "accelerate": accelerate, "l1_scope": l1_scope,
          "newton": newton}
    if init is not None:
        if starts is not None:
            raise ValueError("give init or starts, not both")
        return _fit_one(pk, w_day, init, kernel_sharing, "init", tie_exo=tie_exo, **kw)
    starts = STARTS[kernel_sharing] if starts is None else tuple(starts)
    if not starts or len(set(starts)) != len(starts) or not set(starts) <= {"default", *SHARING}:
        raise ValueError(f"starts must be distinct names from {('default', *SHARING)}")
    fits = []
    for s in starts:
        x = None
        if s != "default":
            sub = _fit_one(pk, w_day, None, s, "default", **kw)
            x = (sub.mu, sub.alpha)
        fits.append(_fit_one(pk, w_day, x, kernel_sharing, s, tie_exo=tie_exo, **kw))
    obj = np.array([f.objective[-1] for f in fits])
    best = fits[int(np.argmax(obj))]
    best.starts, best.start_objective = starts, obj
    return best


def _fit_one(pk: Packed, w_day, init, kernel_sharing, start, *, l1, tol, xtol, max_iter, accelerate, l1_scope,
             newton, tie_exo=()) -> HawkesFit:
    mu, alpha = _init(pk, w_day, init)
    mu, alpha, wc, ll, obj, it, conv, viol, dec = _em(pk, w_day, mu, alpha, l1, tol, xtol, max_iter, accelerate,
                                                      kernel_sharing, l1_scope, newton=newton, tie_exo=tie_exo)
    return HawkesFit(pk.spec, mu, alpha, ll, obj, it, conv, viol, l1, pk.exo_names, kernel_sharing, wc,
                     l1_scope, start, (start,), obj[-1:].copy(), dec, tuple(tie_exo))


def loglik(days: list[Day] | Packed, K: int, mu: np.ndarray, alpha: np.ndarray,
           spec: HawkesSpec | None = None, *, exo_names: tuple[str, ...] | None = None) -> float:
    """sum_i [sum_k log lambda_i(t_k) - int lambda_i], the integral over the days agent i is present."""
    pk = _packed(days, K, spec, exo_names)
    mu, alpha = np.asarray(mu, float), np.asarray(alpha, float)
    _check_params(pk, mu, alpha)
    return _loglik(pk, mu, alpha, np.ones(pk.n_days))


# --- posterior outputs -------------------------------------------------------


@dataclass
class Decomposition:
    shares: dict[str, float]  # share_names(exo_names) order; sums to 1
    by_dim: np.ndarray         # (K, 3 + H) same shares within each agent's events
    n_events: np.ndarray       # (K,)
    parents: pl.DataFrame      # event_uid, parent_uid ('background'), prob


def _share_sums(pk: Packed, p0, pp, w) -> np.ndarray:
    """(K, 3 + H) weighted responsibility sums per target dimension, in share_names order:
    baseline, exogenous sources, other agents, self."""
    K, H = pk.K, pk.H
    S = 3 + H
    pair_dim = np.repeat(pk.tgt_dim, np.diff(pk.ptr))
    cls = np.where(pk.par_src >= K, 1 + pk.par_src - K, np.where(pk.par_src == pair_dim, H + 2, H + 1))
    out = np.bincount(pair_dim * S + cls, weights=pp * np.repeat(w, np.diff(pk.ptr)),
                      minlength=S * K).reshape(K, S)
    out[:, 0] = np.bincount(pk.tgt_dim, weights=p0 * w, minlength=K)
    return out


def shares_of(sums: np.ndarray) -> np.ndarray:
    tot = sums.sum()
    return sums.sum(0) / tot if tot > 0 else np.full(sums.shape[1], np.nan)


def _shares(pk: Packed, mu: np.ndarray, alpha: np.ndarray, w_day: np.ndarray) -> np.ndarray:
    """(3 + H,) weighted decomposition shares, in share_names order."""
    w = w_day[pk.tgt_day]
    p0, pp = _posterior(mu, alpha, w, pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
    return shares_of(_share_sums(pk, p0, pp, w))


def decompose(days: list[Day] | Packed, fit: HawkesFit, min_prob: float = 0.01) -> Decomposition:
    pk = _packed(days, fit.K, fit.spec, fit.exo_names)
    _check_fit(pk, fit)
    w = np.ones(pk.tgt_dim.size)
    p0, pp = _posterior(fit.mu, fit.alpha, w, pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
    sums = _share_sums(pk, p0, pp, w)
    n_ev = sums.sum(1)
    by_dim = np.divide(sums, n_ev[:, None], out=np.full_like(sums, np.nan), where=n_ev[:, None] > 0)
    keep0 = p0 >= min_prob
    keepp = pp >= min_prob
    pair_tgt = np.repeat(pk.tgt_ev, np.diff(pk.ptr))
    parents = pl.DataFrame({
        "event_uid": np.concatenate([pk.ev_uid[pk.tgt_ev[keep0]], pk.ev_uid[pair_tgt[keepp]]]).astype(str),
        "parent_uid": np.concatenate([np.full(keep0.sum(), BACKGROUND, dtype=object),
                                      pk.ev_uid[pk.par_ev[keepp]]]).astype(str),
        "prob": np.concatenate([p0[keep0], pp[keepp]]),
    }, schema={"event_uid": pl.String, "parent_uid": pl.String, "prob": pl.Float64})
    return Decomposition(dict(zip(fit.share_names, shares_of(sums).tolist())), by_dim, n_ev, parents)
