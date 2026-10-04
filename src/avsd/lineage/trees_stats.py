"""Statistics on a transmission forest for module B2 (SPEC 6.2 H1 and H3, 6.4.4).

Inputs are arrays over occurrences (time, run-day clock, unit, agent) and the
chosen parent rows of a forest (MAP or a posterior draw). Transmission edges
have an occurrence as parent; env_i edges start a new subtree and are not
transmission edges.

H1 (SPEC 6.2):
- Forward intervals: an edge enters only if its parent lies more than L_B
  (3 run days) before the end of the data, and every channel is truncated at
  L_B (memory is the only channel whose exposure is not already limited to
  L_B), so every parent has complete follow-up over the compared range.
- Per channel, the interval distributions of the generations with at least
  `min_edges` edges are compared with the Anderson-Darling k-sample statistic
  (Scholz and Stephens 1987, A2_kN without the tie correction) on log
  intervals; p by permutation of generation labels within the channel. The
  combined statistic sums the channel statistics (stratified permutation).
- T_k = t(node) - t(root) for generation-k nodes of trees whose root lies more
  than `margin` run days before the end; mean, variance, median and IQR per k
  with at least `min_edges` nodes, and weighted least squares of the mean and
  of the variance on (1, k) and (1, k, k^2).
- Spearman correlation of consecutive serial intervals along a path.
- Confidence intervals: cluster bootstrap by tree root (SPEC 6.2-3), with
  Poisson(1) weights per cluster (the Poisson bootstrap; replicate weights are
  regenerated from a seed in batches, so a million trees fit in memory).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np

from avsd.lineage.trees_core import Cands
from avsd.lineage.trees_kernel import KEY_CODE, KEYS

H1_CHANNELS: tuple[str, ...] = ("chat_other", "chat_self", "chat_to_memory", "memory", "search", "history", "human")
H1_LABELS = {
    "chat_other": "Chat, Other Agent", "chat_self": "Chat, Same Agent", "chat_to_memory": "Chat to Memory",
    "memory": "Own Memory", "search": "Search Answer", "history": "Chat to Search Answer",
    "human": "Chat to Human",
}
_KEY_TO_CH = {
    "chat>chat:other": "chat_other", "chat>chat:self": "chat_self", "chat>memory:other": "chat_to_memory",
    "chat>memory:self": "chat_to_memory", "memory>chat": "memory", "search>chat": "search",
    "search>memory": "search", "history>search": "history", "chat>human": "human",
}
CH_OF_KEY = np.array([H1_CHANNELS.index(_KEY_TO_CH[k]) if k in _KEY_TO_CH else -1 for k in KEYS], dtype=np.int64)
# H1 strata are the kernel keys: a channel group that pools two keys (for example chat to another agent's
# memory and chat to the agent's own memory) changes its mix with the generation, and the test would then see
# the mix instead of the generation (the synthetic null showed this).
_KEY_TO_ST = {
    "chat>chat:other": "chat_to_chat_other", "chat>chat:self": "chat_to_chat_self", "chat>human": "chat_to_human",
    "chat>memory:other": "chat_to_memory_other", "chat>memory:self": "chat_to_memory_self",
    "memory>chat": "memory_to_chat", "search>chat": "search_to_chat", "search>memory": "search_to_memory",
    "history>search": "chat_to_search_answer",
}
H1_STRATA: tuple[str, ...] = tuple(_KEY_TO_ST[k] for k in KEYS if k in _KEY_TO_ST)
ST_OF_KEY = np.array([H1_STRATA.index(_KEY_TO_ST[k]) if k in _KEY_TO_ST else -1 for k in KEYS], dtype=np.int64)
H1_LABELS.update({
    "chat_to_chat_other": "Chat to Chat, Other Agent", "chat_to_chat_self": "Chat to Chat, Same Agent",
    "chat_to_human": "Chat to Human", "chat_to_memory_other": "Chat to Memory, Other Agent",
    "chat_to_memory_self": "Chat to Memory, Same Agent", "memory_to_chat": "Own Memory to Chat",
    "search_to_chat": "Search Answer to Chat", "search_to_memory": "Search Answer to Memory",
    "chat_to_search_answer": "Chat to Search Answer",
})
AGENT_RETELL_KEYS = (KEY_CODE["chat>chat:other"], KEY_CODE["chat>memory:other"])


@dataclass
class Forest:
    chosen: np.ndarray  # candidate row per occurrence (-1 none)
    parent: np.ndarray  # global index, ENV, or -1
    gen: np.ndarray
    root: np.ndarray


@dataclass
class Edges:
    child: np.ndarray
    parent: np.ndarray
    row: np.ndarray
    key: np.ndarray
    ch: np.ndarray  # channel group (H1_CHANNELS), for channel shares
    dt: np.ndarray  # active seconds
    gen: np.ndarray  # generation of the child
    root: np.ndarray
    st: np.ndarray | None = None  # H1 stratum (H1_STRATA), the kernel key

    def strata(self) -> np.ndarray:
        return self.st if self.st is not None else ST_OF_KEY[np.asarray(self.key, dtype=np.int64)]


@dataclass
class AgentView:
    """Agent-level view of a forest (transmission between agents): one node per actor and unit, the actor's
    first occurrence of the unit (its acquisition; all humans count as one actor). The MAP parent of an
    acquisition (the carrier) is an occurrence of another actor; that actor's acquisition is the agent-level
    parent, one generation up. Later occurrences of an actor are re-mentions: they belong to the actor's
    acquisition and keep its generation, whatever their own MAP parent."""

    gen: np.ndarray  # agent-level generation of the occurrence's acquisition (0 for roots and env_i)
    acq: np.ndarray  # the occurrence is its actor's first occurrence of the unit
    owner: np.ndarray  # the acquisition of the occurrence's actor in its unit
    root: np.ndarray  # the root acquisition of the occurrence's agent-level tree


def _agent_pass_py(parent, owner, acq, gen, root):
    for v in range(len(parent)):
        if acq[v]:
            p = parent[v]
            if p >= 0:
                o = owner[p]
                gen[v] = gen[o] + 1
                root[v] = root[o]
        else:
            o = owner[v]
            gen[v] = gen[o]
            root[v] = root[o]


def _det_agent_py(parent, owner, acq, ncand, det):
    for v in range(len(parent)):
        if not acq[v]:
            continue
        p = parent[v]
        if p == -1:
            det[v] = ncand[v] == 0
        elif p == -2:
            det[v] = ncand[v] == 1
        else:
            det[v] = (ncand[v] == 1) and det[owner[p]]


def agent_view(f: Forest, actor: np.ndarray, unit: np.ndarray) -> AgentView:
    """Occurrences must be ordered by unit and time, with every parent before its child."""
    n = len(actor)
    key = unit.astype(np.int64) * 128 + (actor.astype(np.int64) + 1)
    _, first, inv = np.unique(key, return_index=True, return_inverse=True)
    owner = first[inv].astype(np.int64)
    acq = owner == np.arange(n)
    gen = np.zeros(n, dtype=np.int64)
    root = np.arange(n, dtype=np.int64)
    _agent_pass(np.asarray(f.parent, dtype=np.int64), owner, acq, gen, root)
    return AgentView(gen, acq, owner, root)


def determined_agent(c: Cands, f: Forest, av: AgentView) -> np.ndarray:
    """Acquisitions whose agent-level path to the root uses single-candidate acquisitions: a root without
    candidates, an env_i child whose only candidate was env_i, or an acquisition whose only candidate is its
    carrier and whose carrier's acquisition is determined. Parents and agent-level generations on such a path
    do not depend on the parent posterior."""
    n = len(f.gen)
    kids, starts = c.offsets()
    ncand = np.zeros(n, dtype=np.int64)
    ncand[kids] = np.diff(starts)
    det = np.zeros(n, dtype=bool)
    _det_agent(np.asarray(f.parent, dtype=np.int64), av.owner, av.acq, ncand, det)
    return det


def agent_edges(e: "Edges", av: AgentView) -> tuple["Edges", np.ndarray]:
    """The edges of e into acquisitions (transmission to a new actor), with the child's agent-level generation
    and agent-level tree root."""
    m = av.acq[e.child]
    return Edges(e.child[m], e.parent[m], e.row[m], e.key[m], e.ch[m], e.dt[m], av.gen[e.child[m]],
                 av.root[e.child[m]], None if e.st is None else e.st[m]), m


def restatement_summary(av: AgentView, f: Forest, actor: np.ndarray, cap: int = 10) -> dict:
    """Re-mentions: occurrences of an actor after its acquisition of a unit, by the kind of their MAP parent,
    and restatement depth (re-mentions per acquisition)."""
    n = len(f.gen)
    rem = ~av.acq
    par = f.parent
    has = par >= 0
    same = has & (actor[np.where(has, par, 0)] == actor)
    depth = np.bincount(av.owner[rem], minlength=n)[av.acq] if n else np.zeros(0, np.int64)
    counts = np.bincount(np.minimum(depth, cap), minlength=cap + 1)
    return {
        "n_occurrences": int(n), "n_acquisitions": int(av.acq.sum()), "n_remention": int(rem.sum()),
        "remention_parent_own": int((rem & same).sum()), "remention_parent_other_actor": int((rem & has & ~same).sum()),
        "remention_parent_env": int((rem & (par == -2)).sum()), "remention_no_parent": int((rem & (par == -1)).sum()),
        "depth": [{"depth": str(d) if d < cap else f"{cap}+", "n_acquisitions": int(v)}
                  for d, v in enumerate(counts.tolist())],
        "depth_mean": float(depth.mean()) if len(depth) else np.nan,
        "depth_median": float(np.median(depth)) if len(depth) else np.nan,
        "depth_max": int(depth.max()) if len(depth) else 0,
        "max_generation_occurrence_level": int(f.gen.max()) if n else 0,
        "max_generation_agent_level": int(av.gen.max()) if n else 0,
    }


try:
    from numba import njit as _njit

    _agent_pass = _njit(cache=False)(_agent_pass_py)
    _det_agent = _njit(cache=False)(_det_agent_py)
except ImportError:  # pragma: no cover
    _agent_pass, _det_agent = _agent_pass_py, _det_agent_py


def edges(c: Cands, f: Forest) -> Edges:
    child = np.flatnonzero((f.chosen >= 0) & (f.parent >= 0))
    row = f.chosen[child]
    key = c.key[row].astype(np.int64)
    return Edges(child, f.parent[child], row, key, CH_OF_KEY[key], c.dt[row], f.gen[child], f.root[child],
                 ST_OF_KEY[key])


def determined(c: Cands, f: Forest) -> np.ndarray:
    """Occurrences whose whole path to their tree root uses single-candidate edges: a root without
    candidates, a child of env_i whose only candidate was env_i, or a child whose only candidate is its
    parent and whose parent is determined. Under the exposure rules these parents are certain."""
    n = len(f.gen)
    kids, starts = c.offsets()
    ncand = np.zeros(n, dtype=np.int64)
    ncand[kids] = np.diff(starts)
    det = np.zeros(n, dtype=bool)
    _det_pass(f.parent, ncand, det)
    return det


def _det_pass_py(parent, ncand, det):
    for i in range(len(parent)):
        p = parent[i]
        if p == -1:
            det[i] = ncand[i] == 0
        elif p == -2:
            det[i] = ncand[i] == 1
        else:
            det[i] = (ncand[i] == 1) and det[p]


try:
    from numba import njit

    _det_pass = njit(cache=False)(_det_pass_py)
except ImportError:  # pragma: no cover
    _det_pass = _det_pass_py


def forward_mask(e: Edges, pos: np.ndarray, pos_end: float, L: float) -> np.ndarray:
    """Edges with complete follow-up: parent more than L before the end, interval within L."""
    pp, pc = pos[e.parent], pos[e.child]
    return (pp <= pos_end - L) & (pc - pp <= L)


# --- Anderson-Darling k-sample ------------------------------------------------------------------------

def ad_stat(x: np.ndarray, labels: np.ndarray, perms: np.ndarray | None = None) -> np.ndarray:
    """A2_kN for the observed labels (perms None) or for each row of `perms` (permuted labels).

    Uses sum_j (N M_ij - j n_i)^2 / (j (N - j)) = N^2 sum_j M_ij^2 w1_j - 2 N n_i sum_j M_ij w2_j
    + n_i^2 sum_j j w2_j with w1_j = 1 / (j (N - j)), w2_j = 1 / (N - j), so each label costs one cumulative
    sum and two matrix-vector products per batch of permutations."""
    order = np.argsort(x, kind="stable")
    k = int(labels.max()) + 1
    N = len(x)
    n_i = np.bincount(labels, minlength=k).astype(float)
    j = np.arange(1, N, dtype=float)
    w1 = 1.0 / (j * (N - j))
    w2 = 1.0 / (N - j)
    c3 = float((j * w2).sum())
    L = labels[order][None, :] if perms is None else perms[:, order]
    out = np.zeros(L.shape[0])
    for i in range(k):
        if n_i[i] == 0:
            continue
        M = np.cumsum(L == i, axis=1, dtype=np.int32)[:, :N - 1].astype(np.float64)
        s1 = (M * M) @ w1
        s2 = M @ w2
        out += (N * N * s1 - 2 * N * n_i[i] * s2 + n_i[i] ** 2 * c3) / n_i[i]
    return out / N


def ad_perm_null(x: np.ndarray, labels: np.ndarray, reps: int, rng: np.random.Generator, batch: int = 32
                 ) -> np.ndarray:
    """A2_kN under `reps` permutations of the labels."""
    out, left = [], reps
    bsz = max(1, min(batch, int(2e7 // max(len(x), 1))))
    while left > 0:
        b = min(bsz, left)
        P = np.stack([rng.permutation(labels) for _ in range(b)])
        out.append(ad_stat(x, labels, P))
        left -= b
    return np.concatenate(out) if out else np.zeros(0)


def h1_ad_tests(e: Edges, ok: np.ndarray, min_edges: int, reps: int, rng: np.random.Generator) -> list[dict]:
    """Per-stratum (kernel key) AD tests across generations and the combined stratified test."""
    rows, nulls, obs_all = [], [], 0.0
    est = e.strata()
    for ci_, ch in enumerate(H1_STRATA):
        m = ok & (est == ci_)
        gens, cnt = np.unique(e.gen[m], return_counts=True)
        keep = gens[cnt >= min_edges]
        mm = m & np.isin(e.gen, keep)
        row = {"channel": ch, "generations": ",".join(str(int(g)) for g in keep),
               "n_edges": int(mm.sum()), "n_generations": len(keep), "ad_stat": np.nan, "p_perm": np.nan,
               "n_perm": 0, "z_vs_null": np.nan}
        if len(keep) >= 2:
            x = np.log(np.maximum(e.dt[mm], 1.0))
            lab = np.searchsorted(keep, e.gen[mm])
            obs = float(ad_stat(x, lab)[0])
            null = ad_perm_null(x, lab, reps, rng)
            sd = float(null.std(ddof=1)) if len(null) > 1 else np.nan
            row.update({"ad_stat": obs, "p_perm": (1 + int((null >= obs - 1e-12).sum())) / (1 + len(null)),
                        "n_perm": len(null), "z_vs_null": (obs - float(null.mean())) / sd if sd and sd > 0 else np.nan})
            obs_all += obs
            nulls.append(null)
        rows.append(row)
    comb = {"channel": "combined", "generations": "", "n_edges": int(sum(r["n_edges"] for r in rows
                                                                          if r["n_generations"] >= 2)),
            "n_generations": int(sum(r["n_generations"] for r in rows if r["n_generations"] >= 2)),
            "ad_stat": np.nan, "p_perm": np.nan, "n_perm": 0, "z_vs_null": np.nan}
    if nulls:
        tot = np.sum(np.stack(nulls), axis=0)
        sd = float(tot.std(ddof=1)) if len(tot) > 1 else np.nan
        comb.update({"ad_stat": obs_all, "p_perm": (1 + int((tot >= obs_all - 1e-12).sum())) / (1 + len(tot)),
                     "n_perm": len(tot), "z_vs_null": (obs_all - float(tot.mean())) / sd if sd and sd > 0 else np.nan})
    rows.append(comb)
    return rows


# --- cluster bootstrap ------------------------------------------------------------------------------------

class ClusterBoot:
    """Poisson(1) cluster weights W[b, c], generated in seeded batches (never all at once)."""

    CACHE_MAX = 4e8  # replicate x cluster weights kept in memory (uint8) up to this size

    def __init__(self, cluster: np.ndarray, reps: int, rng: np.random.Generator, batch: int = 32):
        self.ids, self.inv = np.unique(np.asarray(cluster), return_inverse=True)
        self.C = len(self.ids)
        self.reps = int(reps)
        self.batch = max(1, min(batch, int(2e8 // max(self.C, 1))))
        self.seed = int(rng.integers(1 << 62))
        self._cache: dict[int, np.ndarray] | None = {} if self.reps * self.C <= self.CACHE_MAX else None

    def _block(self, b0: int) -> np.ndarray:
        if self._cache is not None and b0 in self._cache:
            return self._cache[b0].astype(np.float32)
        nb = min(self.batch, self.reps - b0)
        w = np.random.default_rng([self.seed, b0]).poisson(1.0, size=(nb, self.C))
        if self._cache is not None:
            self._cache[b0] = np.minimum(w, 255).astype(np.uint8)
        return w.astype(np.float32)

    def matmul(self, A: np.ndarray) -> np.ndarray:
        """W @ A for A of shape (C,) or (C, G)."""
        A = np.asarray(A, dtype=np.float32)
        return np.concatenate([self._block(b0) @ A for b0 in range(0, self.reps, self.batch)], axis=0) \
            if self.reps else np.zeros((0,) + A.shape[1:])

    def rows(self, limit: int):
        for b0 in range(0, min(limit, self.reps), self.batch):
            blk = self._block(b0)
            for r in blk[:min(self.batch, limit - b0)]:
                yield r

    def cluster_index(self, cluster_values: np.ndarray) -> np.ndarray:
        return np.searchsorted(self.ids, cluster_values)

    def sums(self, values: np.ndarray, groups: np.ndarray, n_groups: int, k: np.ndarray | None = None
             ) -> np.ndarray:
        """Replicate sums of `values` per group, (reps, n_groups); k: cluster index of each value
        (default: the clusters the bootstrap was built on, in order)."""
        k = self.inv if k is None else k
        A = np.zeros((self.C, n_groups), dtype=np.float64)
        np.add.at(A, (k, groups), values)
        return self.matmul(A)


def ci(x: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x):
        return (np.nan, np.nan)
    a = (1 - level) / 2
    return float(np.quantile(x, a)), float(np.quantile(x, 1 - a))


def boot_ratio(boot: ClusterBoot, num: np.ndarray, den: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Replicates of sum(num) / sum(den) over the items with cluster index k."""
    A = np.zeros((boot.C, 2))
    np.add.at(A, (k, 0), num)
    np.add.at(A, (k, 1), den)
    R = boot.matmul(A)
    with np.errstate(invalid="ignore", divide="ignore"):
        return R[:, 0] / R[:, 1]


def boot_median(boot: ClusterBoot, v: np.ndarray, k: np.ndarray, reps: int) -> np.ndarray:
    o = np.argsort(v)
    vs, ks = v[o], k[o]
    out = []
    for w in boot.rows(reps):
        cw = np.cumsum(w[ks], dtype=np.float64)
        if cw[-1] > 0:
            out.append(vs[min(int(np.searchsorted(cw, 0.5 * cw[-1])), len(vs) - 1)])
    return np.array(out)


# --- interval tables -----------------------------------------------------------------------------------------

def interval_table(e: Edges, ok: np.ndarray, boot: ClusterBoot, min_edges: int, n_boot_q: int = 200) -> list[dict]:
    """Serial intervals (active hours) per channel and generation, with cluster-bootstrap CIs."""
    rows = []
    hrs = e.dt / 3600.0
    est = e.strata()
    for ci_, ch in enumerate(H1_STRATA):
        m = ok & (est == ci_)
        for g in np.unique(e.gen[m]):
            idx = np.flatnonzero(m & (e.gen == g))
            v = hrs[idx]
            n = len(idx)
            row = {"channel": ch, "generation": int(g), "n_edges": n, "n_trees": int(len(np.unique(e.root[idx]))),
                   "reported": n >= min_edges, "mean_h": float(v.mean()), "median_h": float(np.median(v)),
                   "q25_h": float(np.quantile(v, 0.25)), "q75_h": float(np.quantile(v, 0.75))}
            if n >= min_edges:
                b = ClusterBoot(e.root[idx], boot.reps, np.random.default_rng([boot.seed, ci_, int(g)]))
                row["mean_lo"], row["mean_hi"] = ci(boot_ratio(b, v, np.ones(n), b.inv))
                row["median_lo"], row["median_hi"] = ci(boot_median(b, v, b.inv, n_boot_q))
            rows.append(row)
    return rows


# --- T_k ------------------------------------------------------------------------------------------------------

def _wls(k: np.ndarray, y: np.ndarray, w: np.ndarray, quad: bool) -> np.ndarray:
    X = np.column_stack([np.ones_like(k), k] + ([k ** 2] if quad else []))
    W = np.sqrt(np.maximum(w, 0))
    beta, *_ = np.linalg.lstsq(X * W[:, None], y * W, rcond=None)
    return beta


def tk_analysis(t: np.ndarray, pos: np.ndarray, gen: np.ndarray, root: np.ndarray, pos_end: float,
                margin: float, min_n: int, boot_reps: int, rng: np.random.Generator,
                node_mask: np.ndarray | None = None) -> dict:
    """Mean, variance, median and IQR of T_k by k (active hours), and the linearity regressions."""
    sel_nodes = (gen >= 1) & (pos[root] <= pos_end - margin)
    if node_mask is not None:
        sel_nodes &= node_mask
    nodes = np.flatnonzero(sel_nodes)
    T = (t[nodes] - t[root[nodes]]) / 3600.0
    kk = gen[nodes]
    ks, cnt = np.unique(kk, return_counts=True)
    ks = ks[cnt >= min_n]
    out = {"rows": [], "fits": [], "n_nodes": int(np.isin(kk, ks).sum())}
    if not len(ks):
        return out
    sel = np.isin(kk, ks)
    nodes, T, kk = nodes[sel], T[sel], kk[sel]
    boot = ClusterBoot(root[nodes], boot_reps, rng)
    gi = np.searchsorted(ks, kk)
    K = len(ks)
    S0, S1, S2 = (boot.sums(v, gi, K) for v in (np.ones_like(T), T, T * T))
    with np.errstate(invalid="ignore", divide="ignore"):
        bm = S1 / S0
        bv = (S2 / S0 - bm ** 2) * S0 / np.maximum(S0 - 1, 1)
    means = np.array([T[gi == q].mean() for q in range(K)])
    vars_ = np.array([T[gi == q].var(ddof=1) if (gi == q).sum() > 1 else np.nan for q in range(K)])
    ns = np.array([(gi == q).sum() for q in range(K)], dtype=float)
    for q, k in enumerate(ks):
        v = T[gi == q]
        meds = boot_median(boot, v, boot.inv[gi == q], 200)
        out["rows"].append({
            "k": int(k), "n_nodes": int(ns[q]), "n_trees": int(len(np.unique(root[nodes][gi == q]))),
            "mean_h": float(means[q]), "mean_lo": ci(bm[:, q])[0], "mean_hi": ci(bm[:, q])[1],
            "var_h2": float(vars_[q]), "var_lo": ci(bv[:, q])[0], "var_hi": ci(bv[:, q])[1],
            "sd_h": float(np.sqrt(vars_[q])), "median_h": float(np.median(v)),
            "median_lo": ci(meds)[0], "median_hi": ci(meds)[1],
            "q25_h": float(np.quantile(v, 0.25)), "q75_h": float(np.quantile(v, 0.75)),
        })
    kf = ks.astype(float)
    for name, y, yb in (("mean", means, bm), ("variance", vars_, bv)):
        good = [b for b in range(len(yb)) if np.all(np.isfinite(yb[b]))]
        if K >= 2:
            lin = _wls(kf, y, ns, False)
            blin = np.array([_wls(kf, yb[b], S0[b], False) for b in good]) if good else np.zeros((0, 2))
            out["fits"].append({"quantity": name, "model": "linear", "n_k": K, "intercept": float(lin[0]),
                                "slope": float(lin[1]), "slope_lo": ci(blin[:, 1])[0] if len(blin) else np.nan,
                                "slope_hi": ci(blin[:, 1])[1] if len(blin) else np.nan})
        if K >= 3:
            qd = _wls(kf, y, ns, True)
            bq = np.array([_wls(kf, yb[b], S0[b], True) for b in good]) if good else np.zeros((0, 3))
            lo, hi = ci(bq[:, 2]) if len(bq) else (np.nan, np.nan)
            p = float(min(1.0, 2 * min((bq[:, 2] <= 0).mean(), (bq[:, 2] >= 0).mean()))) if len(bq) else np.nan
            out["fits"].append({"quantity": name, "model": "quadratic", "n_k": K, "intercept": float(qd[0]),
                                "slope": float(qd[1]), "k2": float(qd[2]), "k2_lo": lo, "k2_hi": hi,
                                "p_k2_boot": p})
    return out


def adjacent_correlation(e: Edges, ok: np.ndarray, boot_reps: int, rng: np.random.Generator) -> dict:
    """Spearman correlation of the interval into a node with the interval into its parent."""
    from scipy import stats

    pos_of = np.full(int(e.child.max()) + 1 if len(e.child) else 0, -1, dtype=np.int64)
    pos_of[e.child] = np.arange(len(e.child))
    k = np.flatnonzero(ok)
    pk = np.where(e.parent[k] < len(pos_of), pos_of[np.minimum(e.parent[k], len(pos_of) - 1)], -1) \
        if len(pos_of) else np.zeros(0, np.int64)
    good = (pk >= 0)
    good[good] &= ok[pk[good]]
    a, b, r = e.dt[pk[good]], e.dt[k[good]], e.root[k[good]]
    res = {"n_pairs": int(len(a)), "rho": np.nan, "rho_lo": np.nan, "rho_hi": np.nan}
    if len(a) < 10:
        return res
    ra, rb = stats.rankdata(a), stats.rankdata(b)
    res["rho"] = float(stats.spearmanr(a, b).statistic)
    boot = ClusterBoot(r, boot_reps, rng)
    vals = []
    for w in boot.rows(boot_reps):
        ww = w[boot.inv].astype(float)
        sw = ww.sum()
        if sw <= 0:
            continue
        ma, mb = (ww * ra).sum() / sw, (ww * rb).sum() / sw
        cov = (ww * (ra - ma) * (rb - mb)).sum()
        va, vb = (ww * (ra - ma) ** 2).sum(), (ww * (rb - mb) ** 2).sum()
        vals.append(cov / np.sqrt(va * vb) if va > 0 and vb > 0 else np.nan)
    res["rho_lo"], res["rho_hi"] = ci(np.array(vals))
    return res


# --- per-generation table ----------------------------------------------------------------------------------

def generation_table(e: Edges, f: Forest, occ_pos: np.ndarray, pos_end: float, L: float, susceptible: np.ndarray,
                     var_new: np.ndarray, var_tot: np.ndarray, gen_alt: np.ndarray, root_alt: np.ndarray,
                     is_env: np.ndarray, boot_reps: int, rng: np.random.Generator, max_gen: int = 12,
                     node_mask: np.ndarray | None = None, alt_mask: np.ndarray | None = None) -> list[dict]:
    """Per generation g: nodes, channel shares of edges into g, offspring (observed and expected under the
    finite population), content change rate, and the share acquired independently by the generation a node
    would have if env parents were not allowed. node_mask and alt_mask restrict the nodes counted (the
    agent-level view counts acquisitions; offspring are then the edges whose parent maps to the node)."""
    n = len(f.gen)
    nm = np.ones(n, dtype=bool) if node_mask is None else node_mask
    am = np.ones(len(gen_alt), dtype=bool) if alt_mask is None else alt_mask
    gmax = int(f.gen[nm].max()) if nm.any() else 0
    G = min(gmax + 1, max_gen + 1)
    gg = np.minimum(f.gen, G - 1)
    kids = np.bincount(e.parent, minlength=n).astype(float)
    full = (occ_pos <= pos_end - L) & nm
    boot = ClusterBoot(f.root[full], boot_reps, rng)
    kf = boot.inv
    off_b = boot.sums(kids[full], gg[full], G, kf)
    cnt_b = boot.sums(np.ones(int(full.sum())), gg[full], G, kf)
    boot_e = ClusterBoot(e.root, boot_reps, rng) if len(e.root) else None
    boot_a = ClusterBoot(root_alt, boot_reps, rng)
    rows = []
    ga = np.minimum(gen_alt, G - 1)
    for g in range(G):
        m = (gg == g) & nm
        mf = m & full
        r = {"generation": str(g) if (g < G - 1 or gmax <= max_gen) else f"{g}+", "n_nodes": int(m.sum()),
             "n_trees": int(len(np.unique(f.root[m]))), "n_full_followup": int(mf.sum())}
        if mf.any():
            with np.errstate(invalid="ignore", divide="ignore"):
                b = off_b[:, g] / cnt_b[:, g]
            r["offspring_mean"] = float(kids[mf].mean())
            r["offspring_lo"], r["offspring_hi"] = ci(b)
            r["susceptible_share"] = float(susceptible[mf].mean())
        me = np.minimum(e.gen, G - 1) == g
        r["n_edges_in"] = int(me.sum())
        for ci_, ch in enumerate(H1_CHANNELS):
            r[f"share_{ch}"] = float((e.ch[me] == ci_).mean()) if me.any() else np.nan
        if me.any():
            tot = var_tot[e.child[me]].astype(float)
            new = var_new[me].astype(float)
            r["content_change_rate"] = float(new.sum() / tot.sum()) if tot.sum() > 0 else np.nan
            r["edges_with_new_variant"] = float((new > 0).mean())
            if boot_e is not None:
                r["content_change_lo"], r["content_change_hi"] = ci(
                    boot_ratio(boot_e, new, tot, boot_e.cluster_index(e.root[me])))
        ma = (ga == g) & am
        if ma.any():
            r["n_nodes_alt"] = int(ma.sum())
            r["independent_share"] = float(is_env[ma].mean())
            r["independent_lo"], r["independent_hi"] = ci(boot_ratio(
                boot_a, is_env[ma].astype(float), np.ones(int(ma.sum())), boot_a.cluster_index(root_alt[ma])))
        rows.append(r)
    base = rows[0] if rows else {}
    for r in rows:
        if "offspring_mean" in r and base.get("susceptible_share", 0) and "offspring_mean" in base:
            r["offspring_expected"] = base["offspring_mean"] * r["susceptible_share"] / base["susceptible_share"]
    return rows


# --- H3 ---------------------------------------------------------------------------------------------------------

def quantity_changes(e: Edges, qk, qv, sel: np.ndarray) -> tuple[np.ndarray, np.ndarray, list]:
    """Per selected edge: contexts carried (key in parent and child) and contexts whose value changed,
    plus (edge index, key, new values, parent values) of each change for the inheritance check."""
    carried = np.zeros(len(e.child), dtype=np.int64)
    changed = np.zeros(len(e.child), dtype=np.int64)
    changes = []
    for k in np.flatnonzero(sel):
        p, c = int(e.parent[k]), int(e.child[k])
        pk, pv, ck, cv = qk[p], qv[p], qk[c], qv[c]
        if not len(pk) or not len(ck):
            continue
        pd: dict[int, set] = {}
        for a, b in zip(pk.tolist(), pv.tolist()):
            pd.setdefault(a, set()).add(b)
        cd: dict[int, set] = {}
        for a, b in zip(ck.tolist(), cv.tolist()):
            cd.setdefault(a, set()).add(b)
        for key in pd.keys() & cd.keys():
            carried[k] += 1
            new = cd[key] - pd[key]
            if new:
                changed[k] += 1
                changes.append((k, key, frozenset(new), frozenset(pd[key])))
    return carried, changed, changes


def inheritance(e: Edges, qk, qv, changes: list) -> dict:
    """For each change on edge p->c, the children of c that carry the key: share holding the new value."""
    kids_of: dict[int, list[int]] = {}
    for k, p in enumerate(e.parent.tolist()):
        kids_of.setdefault(p, []).append(k)
    n_carry = n_new = n_old = 0
    for k, key, new, old in changes:
        c = int(e.child[k])
        for k2 in kids_of.get(c, ()):
            g = int(e.child[k2])
            vals = {b for a, b in zip(qk[g].tolist(), qv[g].tolist()) if a == key}
            if not vals:
                continue
            n_carry += 1
            n_new += bool(vals & new)
            n_old += bool(vals & old) and not (vals & new)
    return {"n_grandchild_contexts": n_carry, "inherited_share": n_new / n_carry if n_carry else np.nan,
            "reverted_share": n_old / n_carry if n_carry else np.nan}


# --- attractor ----------------------------------------------------------------------------------------------------

def attractor(win, unit_of: np.ndarray, nodes: np.ndarray, min_tokens: int = 5) -> dict[str, np.ndarray]:
    """Type-token ratio of each node's window and its Jaccard similarity to the unit's most common window
    (an exact window seen at least twice, else the medoid by mean Jaccard)."""
    ttr = np.full(len(nodes), np.nan)
    sim = np.full(len(nodes), np.nan)
    by_unit: dict[int, list[int]] = {}
    for k, i in enumerate(nodes.tolist()):
        by_unit.setdefault(int(unit_of[i]), []).append(k)
    for ks in by_unit.values():
        toks = [win[int(nodes[k])] for k in ks]
        tups = [tuple(t.tolist()) for t in toks]
        sets = [frozenset(t) for t in tups]
        valid = [q for q in range(len(ks)) if len(tups[q]) >= min_tokens]
        if not valid:
            continue
        cnt = Counter(tups[q] for q in valid)
        top, c = cnt.most_common(1)[0]
        if c >= 2:
            modal = frozenset(top)
        elif len(valid) > 1:
            best = max(valid, key=lambda q: np.mean([len(sets[q] & sets[r]) / max(len(sets[q] | sets[r]), 1)
                                                     for r in valid if r != q]))
            modal = sets[best]
        else:
            modal = sets[valid[0]]
        for q in valid:
            ttr[ks[q]] = len(sets[q]) / len(tups[q])
            sim[ks[q]] = len(sets[q] & modal) / max(len(sets[q] | modal), 1)
    return {"ttr": ttr, "sim": sim}
