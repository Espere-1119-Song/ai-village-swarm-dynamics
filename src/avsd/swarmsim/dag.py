"""Task DAG generator of the swarm simulator (SPEC 8.2 D1, appendix B).

A DAG grows layer by layer. Layer 0 holds the root (value 0). Layer sizes follow the rise of a
logistic curve of steepness `width / (D - 1)` centred at `peak * (D - 1)` across each layer, times
`exp(size_noise * z)`. Each new step draws a main parent from the previous non-empty layer with
probability proportional to `exp(beta * delta)`, `delta` being that parent's change over its best
parent. With probability `merge_p` it merges K extra parents, P(K) ~ K^-alpha on 1..k_max. Each
extra parent is a sibling of the main parent (another main child of the main parent's main parent)
with probability `sibling`, else a step of the layer b levels up, b = 1, 2, ... continuing with
probability `back` and stopping at the root, drawn with the same softmax. A candidate that is an
ancestor of a chosen parent is skipped and a chosen parent that is an ancestor of the new one is
dropped, at most 8K tries. A step's value is its best parent's value plus N(mu_d + q, sigma^2),
mu_d falling linearly from `mu_root` at layer 0 to `mu_deep` at the deepest layer, q ~ N(0,
fertility_sd^2) once per DAG. Step cost c_d = 1 + (cost_ratio - 1) d / (D - 1).

A task varies around the language-modelling DAG: round(723 e^{0.4z}) steps, round(17 e^{0.2z})
layers, peak 0.28 + 0.07z, merge probability 0.46 e^{0.3z}, clock exp(delta_b) with delta_b ~
U(-0.3, 0.3). Every DAG of a task is scored on one scale: the 0.9 quantile of the best values of
64 DAGs grown like the task's is worth 1, higher values count as 1, values below the root's 0
count as 0.

Details the blog text leaves open (clamps on the task draws, the sibling definition, the stopping
rule of b, the rounding of layer sizes) follow the simulator code the blog page loads
(assets/data/edgebench-logsigmoid.js, v47); each is listed in outputs/qa/swarmsim_d1.md.

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GenParams:
    """Generator constants. Defaults are the blog's values."""

    n_steps: int = 723
    n_layers: int = 17
    peak: float = 0.28
    width: float = 6.4           # logistic steepness times (D - 1)
    size_noise: float = 0.35
    merge_p: float = 0.46
    alpha: float = 2.3
    k_max: int = 16
    back: float = 0.8
    sibling: float = 0.2
    beta: float = 1.4
    sigma: float = 1.0
    mu_root: float = 1.0
    mu_deep: float = -0.5
    fertility_sd: float = 0.2
    cost_ratio: float = 10.0
    # per-task variation
    steps_sd: float = 0.4
    layers_sd: float = 0.2
    peak_sd: float = 0.07
    merge_sd: float = 0.3
    clock_halfwidth: float = 0.3
    # score scale
    scale_draws: int = 64
    scale_quantile: float = 0.9


BLOG = GenParams()


class Draws:
    """Buffered uniforms and standard normals from one numpy Generator.

    Python loops draw one number at a time; pulling blocks from the Generator keeps that cheap.
    """

    __slots__ = ("_iu", "_iz", "_u", "_z", "block", "rng")

    def __init__(self, rng: np.random.Generator, block: int = 2048):
        self.rng, self.block = rng, block
        self._u: list[float] = []
        self._z: list[float] = []
        self._iu = self._iz = 0

    def u(self) -> float:
        if self._iu == len(self._u):
            self._u, self._iu = self.rng.random(self.block).tolist(), 0
        self._iu += 1
        return self._u[self._iu - 1]

    def z(self) -> float:
        if self._iz == len(self._z):
            self._z, self._iz = self.rng.standard_normal(self.block).tolist(), 0
        self._iz += 1
        return self._z[self._iz - 1]


@dataclass
class Dag:
    """A generated task DAG. Step ids are topological: parents always have smaller ids."""

    layer: np.ndarray            # int, generator layer of each step
    parents: list[list[int]]     # main parent first
    children: list[list[int]]
    value: np.ndarray
    imp: np.ndarray              # change over the best parent (delta)
    cost: np.ndarray             # layer cost c_d
    sizes: np.ndarray            # m_d, steps per layer
    fertility: float

    @property
    def n(self) -> int:
        return len(self.parents)

    @property
    def n_layers(self) -> int:
        return len(self.sizes)

    def edges(self) -> list[tuple[int, int]]:
        return [(p, c) for c, ps in enumerate(self.parents) for p in ps]


@dataclass(frozen=True)
class Task:
    """One task of a family: its DAG size, profile and clock."""

    n_steps: int
    n_layers: int
    peak: float
    merge_p: float
    clock: float                 # delta_b; the task's clock runs exp(delta_b) times slower


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def layer_sizes(n: int, n_layers: int, peak: float, draws: Draws, p: GenParams = BLOG) -> np.ndarray:
    """Steps per layer: the root, then the logistic rise across each layer times noise."""
    D = n_layers
    c, b = peak * (D - 1), p.width / max(1, D - 1)
    w = np.zeros(D)
    for d in range(1, D):
        rise = _sigmoid(b * (d + 0.5 - c)) - _sigmoid(b * (d - 0.5 - c))
        w[d] = rise * (math.exp(p.size_noise * draws.z()) if p.size_noise > 0 else 1.0)
    m = np.zeros(D, dtype=np.int64)
    m[0] = 1
    m[1:] = np.floor((n - 1) * w[1:] / w[1:].sum() + 0.5)
    # rounding residue goes to (or comes from) the fullest layer
    while m.sum() < n:
        m[1 + int(np.argmax(m[1:]))] += 1
    while m.sum() > n:
        k = 1 + int(np.argmax(m[1:]))
        if m[k] <= 0:
            break
        m[k] -= 1
    return m


def grow_dag(n: int, n_layers: int, peak: float, merge_p: float, rng: np.random.Generator,
             p: GenParams = BLOG) -> Dag:
    """Grow one scored DAG with `n` steps over `n_layers` layers (root included)."""
    dr = Draws(rng)
    u, z = dr.u, dr.z
    m = layer_sizes(n, n_layers, peak, dr, p)
    D = len(m)
    q = p.fertility_sd * z()
    cdf_k = np.cumsum(np.arange(1, p.k_max + 1, dtype=float) ** -p.alpha)
    cdf_k = (cdf_k / cdf_k[-1]).tolist()
    beta = p.beta

    layer: list[int] = [0]
    parents: list[list[int]] = [[]]
    children: list[list[int]] = [[]]
    main_kids: list[list[int]] = [[]]
    main_par: list[int] = [-1]
    val: list[float] = [0.0]
    imp: list[float] = [0.0]
    anc: list[int] = [0]                      # ancestor bitsets as Python ints
    layers: list[list[int]] = [[0]]
    cum: dict[int, list[float]] = {}          # softmax prefix sums of finished layers

    def pick_layer(d: int) -> int:
        ids = layers[d]
        c = cum.get(d)
        if c is None:
            top = max(imp[i] for i in ids)
            c, tot = [], 0.0
            for i in ids:
                tot += math.exp(beta * (imp[i] - top))
                c.append(tot)
            cum[d] = c
        return ids[min(bisect_left(c, u() * c[-1]), len(ids) - 1)]

    def pick_among(ids: list[int]) -> int:
        top = max(imp[i] for i in ids)
        c, tot = [], 0.0
        for i in ids:
            tot += math.exp(beta * (imp[i] - top))
            c.append(tot)
        return ids[min(bisect_left(c, u() * tot), len(ids) - 1)]

    prev_d = 0
    for d in range(1, D):
        if m[d] <= 0:
            layers.append([])
            continue
        mu = p.mu_root + (p.mu_deep - p.mu_root) * d / max(1, D - 1)
        cur: list[int] = []
        for _ in range(int(m[d])):
            pm = pick_layer(prev_d)
            ps = [pm]
            if u() < merge_p:
                K = bisect_left(cdf_k, u()) + 1
                K = min(K, p.k_max)
                gp = main_par[pm]
                sibs = [s for s in main_kids[gp] if s != pm] if gp >= 0 else []
                got = tries = 0
                while got < K and tries < 8 * K:
                    tries += 1
                    if sibs and u() < p.sibling:
                        cand = pick_among(sibs)
                    else:
                        b = 1
                        while b < d and u() < p.back:
                            b += 1
                        if not layers[d - b]:
                            continue
                        cand = pick_layer(d - b)
                    if cand in ps or any((anc[x] >> cand) & 1 for x in ps):
                        continue
                    a_c = anc[cand]
                    ps = [x for x in ps if not (a_c >> x) & 1]
                    ps.append(cand)
                    got += 1
            i = len(layer)
            a = 0
            best = -math.inf
            for x in ps:
                a |= anc[x] | (1 << x)
                children[x].append(i)
                best = max(best, val[x])
            change = q + mu + p.sigma * z()
            layer.append(d)
            parents.append(ps)
            children.append([])
            main_kids.append([])
            main_kids[ps[0]].append(i)
            main_par.append(ps[0])
            val.append(best + change)
            imp.append(change)
            anc.append(a)
            cur.append(i)
        layers.append(cur)
        prev_d = d

    lay = np.asarray(layer, dtype=np.int64)
    cost = 1.0 + (p.cost_ratio - 1.0) * lay / max(1, D - 1)
    return Dag(lay, parents, children, np.asarray(val), np.asarray(imp), cost, m, q)


def draw_task(rng: np.random.Generator, p: GenParams = BLOG) -> Task:
    """One task of a family. Clamps follow the blog's simulator code."""
    clock = p.clock_halfwidth * (2.0 * rng.random() - 1.0)
    z = rng.standard_normal(4)
    n = int(np.clip(math.floor(p.n_steps * math.exp(p.steps_sd * z[0]) + 0.5), 10, 1500))
    D = int(np.clip(math.floor(p.n_layers * math.exp(p.layers_sd * z[1]) + 0.5), 3, 30))
    pk = float(np.clip(p.peak + p.peak_sd * z[2], 0.1, 0.9))
    mp = float(np.clip(p.merge_p * math.exp(p.merge_sd * z[3]), 0.0, 0.9))
    return Task(n, D, pk, mp, clock)


def task_dag(task: Task, rng: np.random.Generator, p: GenParams = BLOG) -> Dag:
    return grow_dag(task.n_steps, task.n_layers, task.peak, task.merge_p, rng, p)


def score_scale(task: Task, rngs: list[np.random.Generator], p: GenParams = BLOG) -> float:
    """The value worth a best score of 1: the `scale_quantile` of best values over DAGs of the task."""
    best = sorted(float(task_dag(task, r, p).value.max()) for r in rngs)
    return best[round(p.scale_quantile * (len(best) - 1))]


def scores(dag: Dag, scale: float) -> np.ndarray:
    """Values on the task's scale: root 0, scale 1, clipped to [0, 1]."""
    if scale > 0:
        return np.clip(np.maximum(dag.value, 0.0) / scale, 0.0, 1.0)
    return (dag.value >= 0).astype(float)


def relayer(dag: Dag) -> np.ndarray:
    """Layers as measured on a real DAG: each step one layer below its deepest parent."""
    depth = np.zeros(dag.n, dtype=np.int64)
    for c in range(1, dag.n):
        depth[c] = 1 + max(depth[p] for p in dag.parents[c])
    return depth


def structure_stats(dag: Dag) -> dict[str, float]:
    """Statistics the blog reports or fits for generated DAGs (SPEC 8.2, 8.4)."""
    depth = relayer(dag)
    edges = dag.edges()
    span = np.array([depth[c] - depth[p] for p, c in edges])
    outdeg = np.array([len(k) for k in dag.children])
    indeg = np.array([len(ps) for ps in dag.parents[1:]])
    par_out = np.sort(outdeg[outdeg > 0])[::-1]
    n_top = max(1, math.ceil(0.1 * len(par_out)))
    srt = np.sort(par_out)
    gini = float((2 * np.arange(1, len(srt) + 1) - len(srt) - 1) @ srt / (len(srt) * srt.sum()))
    sets = [set(ps) for ps in dag.parents]
    multi = [ps for ps in dag.parents if len(ps) >= 2]
    sib = sum(any(sets[a] & sets[b] for i, a in enumerate(ps) for b in ps[i + 1:]) for ps in multi)
    deepest = int(dag.layer.max())
    return {
        "n_steps": float(dag.n),
        "n_layers": float(dag.n_layers),
        "n_edges": float(len(edges)),
        "cross_layer_share": float((span >= 2).mean()),
        "best_depth_share": float(dag.layer[int(np.argmax(dag.value))] / max(1, deepest)),
        "leaf_share": float((outdeg == 0).mean()),
        "multi_parent_share": float((indeg >= 2).mean()),
        "mean_parents": float(indeg.mean()),
        "sibling_merge_share": float(sib / len(multi)) if multi else float("nan"),
        "outdeg_gini": gini,
        "top10_child_share": float(par_out[:n_top].sum() / par_out.sum()),
        "peak_layer_share": float(int(np.argmax(dag.sizes[1:])) + 1) / max(1, dag.n_layers - 1),
    }
