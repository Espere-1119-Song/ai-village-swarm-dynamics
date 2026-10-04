"""The AI Village work-dependency graph (SPEC 8.3, D2) and its structure statistics (SPEC 8.4, D3).

Nodes are computer-use sessions. Session B gets the edge A -> B when B touches artifact x (a read
or a write, `avsd.swarmsim.touches`) and session A was the last session other than B to write x
before B's first touch of x. The edge is labelled `write` when B also writes x and `read` when B
only reads it; write and read edges are reported separately and together (`all`).

Matching is hierarchical within an artifact's container (a repository, a document, a project
directory): a touch of a path inside a repository sees the last write to that path and the last
write to the repository as a whole (a push, a commit, an API call on the project); a touch of the
container itself (a clone, entering the directory, viewing the Pages site) sees the last write to
anything in it. The `exact` variant matches keys only.

An edge must point forward in session start order, so every graph is a DAG. An edge from a
session that started after B (possible while two sessions overlap) is dropped and counted.
Graphs are built per village goal from the global edge list; edges whose ends lie in different
goals are counted and dropped. Each node sits one layer below its deepest parent; roots are
layer 0 (SPEC 8.3, as in the blog).

`graph_parts` and `stats_from_parts` compute the D3 statistics the same way for an AI Village
graph and for a generated DAG (their values agree with `avsd.swarmsim.dag.structure_stats` on
generated DAGs, see tests/test_depgraph.py). Parent counts are taken over nodes with at least one
parent, the sibling share over nodes with at least two parents (two parents are siblings when
they share a parent, as in D1), out-degree inequality over nodes with at least one child, and the
cross-layer share over edges that span two or more layers.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import polars as pl

STAT_NAMES = (
    "multi_parent_share", "mean_parents", "sibling_merge_share", "outdeg_gini",
    "top10_child_share", "cross_layer_share",
)
STAT_LABELS = {
    "multi_parent_share": "Steps with 2+ parents",
    "mean_parents": "Mean parents per step",
    "sibling_merge_share": "Merges between siblings",
    "outdeg_gini": "Out-degree Gini",
    "top10_child_share": "Children of top 10% parents",
    "cross_layer_share": "Edges skipping 2+ layers",
}
PARENT_BINS = ("1", "2", "3", "4+")


# --- edges by last writer --------------------------------------------------------------------------

class _Top2:
    """The latest writer of a key and the latest writer distinct from it."""

    __slots__ = ("s1", "t1", "s2", "t2")

    def __init__(self) -> None:
        self.s1 = self.s2 = -1
        self.t1 = self.t2 = -math.inf

    def add(self, s: int, t: float) -> None:
        if s == self.s1:
            if t > self.t1:
                self.t1 = t
            return
        if t >= self.t1:
            self.s2, self.t2 = self.s1, self.t1
            self.s1, self.t1 = s, t
        elif t >= self.t2:
            self.s2, self.t2 = s, t

    def excluding(self, s: int) -> tuple[int, float]:
        return (self.s2, self.t2) if self.s1 == s else (self.s1, self.t1)


@dataclass
class EdgeBuild:
    edges: pl.DataFrame               # parent, child, label, n_keys, kinds, rules, first_t
    found: pl.DataFrame               # child, c, parent, label: every successful lookup
    dropped_order: int = 0            # parent started after the child
    lookups: int = 0
    lookups_with_writer: int = 0
    stats: dict = field(default_factory=dict)


def build_edges(touch: pl.DataFrame, start_rank: np.ndarray, hierarchical: bool = True) -> EdgeBuild:
    """Edges by last writer from per-(session, key) touches.

    `touch` has one row per (session `s` (int), key `k` (int), container `c` (int)) with
    `first_t` (first edge-mode touch, seconds), `wrote` (bool), `write_ts` (list of write times),
    `clevel` (any container-level touch), `kind` and `rule` (rule of the first touch).
    `start_rank[s]` orders sessions by start. Returns edges between session ints with label write
    or read, and every successful lookup.
    """
    events: list[tuple[float, int, int, int, int, int]] = []   # (t, order, s, k, c, flags)
    s_arr = touch["s"].to_numpy()
    k_arr = touch["k"].to_numpy()
    c_arr = touch["c"].to_numpy()
    ft = touch["first_t"].to_numpy()
    wrote = touch["wrote"].to_numpy()
    cl = touch["clevel"].to_numpy()
    kind = touch["kind"].to_list()
    rule = touch["rule"].to_list() if "rule" in touch.columns else [""] * touch.height
    wts = touch["write_ts"].to_list()
    for i in range(len(s_arr)):
        flags = (1 if wrote[i] else 0) | (2 if cl[i] or k_arr[i] == c_arr[i] else 0)
        events.append((float(ft[i]), 0, int(s_arr[i]), int(k_arr[i]), int(c_arr[i]), flags | (i << 2)))
        for t in wts[i] or ():
            events.append((float(t), 1, int(s_arr[i]), int(k_arr[i]), int(c_arr[i]), flags | (i << 2)))
    events.sort(key=lambda e: (e[0], e[1]))
    lw_key: dict[int, _Top2] = defaultdict(_Top2)
    lw_clevel: dict[int, _Top2] = defaultdict(_Top2)
    lw_any: dict[int, _Top2] = defaultdict(_Top2)
    out: dict[tuple[int, int], list] = {}
    lk: list[tuple[int, int, int, int]] = []
    dropped = lookups = found = 0
    for t, order, s, k, c, fl in events:
        is_c = bool(fl & 2)
        if order == 0:
            lookups += 1
            if hierarchical and is_c:
                a, ta = lw_any[c].excluding(s) if c in lw_any else (-1, -math.inf)
            else:
                a, ta = lw_key[k].excluding(s) if k in lw_key else (-1, -math.inf)
                if hierarchical and c in lw_clevel:
                    a2, t2 = lw_clevel[c].excluding(s)
                    if t2 > ta:
                        a, ta = a2, t2
            if a < 0:
                continue
            found += 1
            if start_rank[a] >= start_rank[s]:
                dropped += 1
                continue
            row = fl >> 2
            lab = 1 if fl & 1 else 0
            lk.append((s, c, a, lab))
            e = out.get((a, s))
            if e is None:
                out[(a, s)] = [lab, 1, {kind[row]}, t, {rule[row]}]
            else:
                e[0] = max(e[0], lab)
                e[1] += 1
                e[2].add(kind[row])
                e[4].add(rule[row])
        else:
            lw_key[k].add(s, t)
            lw_any[c].add(s, t)
            if is_c:
                lw_clevel[c].add(s, t)
    if out:
        keys = list(out)
        edges = pl.DataFrame({
            "parent": np.array([a for a, _ in keys], dtype=np.int64),
            "child": np.array([b for _, b in keys], dtype=np.int64),
            "label": ["write" if out[x][0] else "read" for x in keys],
            "n_keys": np.array([out[x][1] for x in keys], dtype=np.int64),
            "kinds": [",".join(sorted(out[x][2])) for x in keys],
            "rules": [",".join(sorted(out[x][4])) for x in keys],
            "first_t": np.array([out[x][3] for x in keys], dtype=float),
        })
    else:
        edges = pl.DataFrame(schema={"parent": pl.Int64, "child": pl.Int64, "label": pl.String,
                                     "n_keys": pl.Int64, "kinds": pl.String, "rules": pl.String,
                                     "first_t": pl.Float64})
    found_df = pl.DataFrame(lk, schema={"child": pl.Int64, "c": pl.Int64, "parent": pl.Int64,
                                        "write": pl.Int8}, orient="row")
    return EdgeBuild(edges, found_df, dropped, lookups, found)


# --- graphs and layers --------------------------------------------------------------------------------

def parent_lists(n: int, edges: Iterable[tuple[int, int]]) -> list[list[int]]:
    """Parent lists over local node ids 0..n-1 (ids in topological order)."""
    ps: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        ps[b].append(a)
    return ps


def layers_of(parents: Sequence[Sequence[int]]) -> np.ndarray:
    """Each node one layer below its deepest parent; roots at layer 0. Ids must be topological."""
    depth = np.zeros(len(parents), dtype=np.int64)
    for c, ps in enumerate(parents):
        if ps:
            depth[c] = 1 + max(depth[p] for p in ps)
    return depth


@dataclass
class GraphParts:
    """Counts behind the D3 statistics of one graph (summable across graphs)."""

    n: int
    n_edges: int
    n_roots: int
    n_isolated: int
    n_layers: int
    indeg: np.ndarray            # parent counts of nodes with >= 1 parent
    n_multi: int
    n_sib: int
    outdeg: np.ndarray           # child counts of nodes with >= 1 child
    n_cross: int


def graph_parts(parents: Sequence[Sequence[int]]) -> GraphParts:
    n = len(parents)
    depth = layers_of(parents)
    indeg = np.array([len(p) for p in parents], dtype=np.int64)
    outdeg = np.zeros(n, dtype=np.int64)
    n_cross = 0
    for c, ps in enumerate(parents):
        for p in ps:
            outdeg[p] += 1
            if depth[c] - depth[p] >= 2:
                n_cross += 1
    sets = [set(p) for p in parents]
    n_multi = n_sib = 0
    for ps in parents:
        if len(ps) >= 2:
            n_multi += 1
            if any(sets[a] & sets[b] for i, a in enumerate(ps) for b in ps[i + 1:]):
                n_sib += 1
    roots = indeg == 0
    return GraphParts(
        n=n, n_edges=int(indeg.sum()), n_roots=int(roots.sum()),
        n_isolated=int((roots & (outdeg == 0)).sum()),
        n_layers=int(depth.max()) + 1 if n else 0,
        indeg=indeg[indeg > 0], n_multi=n_multi, n_sib=n_sib, outdeg=outdeg[outdeg > 0],
        n_cross=n_cross)


def gini(x: np.ndarray) -> float:
    """Gini coefficient of non-negative values (the D1 formula)."""
    if len(x) == 0 or x.sum() == 0:
        return math.nan
    s = np.sort(x.astype(float))
    k = np.arange(1, len(s) + 1)
    return float((2 * k - len(s) - 1) @ s / (len(s) * s.sum()))


def top_share(x: np.ndarray, q: float = 0.1) -> float:
    """Share of the total held by the top ceil(q * len) values."""
    if len(x) == 0 or x.sum() == 0:
        return math.nan
    s = np.sort(x)[::-1]
    return float(s[:max(1, math.ceil(q * len(s)))].sum() / s.sum())


def stats_from_parts(parts: Sequence[GraphParts]) -> dict[str, float]:
    """D3 statistics of one graph, or pooled over several graphs (counts summed, arrays joined)."""
    indeg = np.concatenate([p.indeg for p in parts]) if parts else np.zeros(0, dtype=np.int64)
    outdeg = np.concatenate([p.outdeg for p in parts]) if parts else np.zeros(0, dtype=np.int64)
    n = sum(p.n for p in parts)
    n_edges = sum(p.n_edges for p in parts)
    n_multi = sum(p.n_multi for p in parts)
    nan = math.nan
    out = {
        "n_nodes": float(n),
        "n_edges": float(n_edges),
        "n_child_nodes": float(len(indeg)),
        "n_parent_nodes": float(len(outdeg)),
        "n_multi": float(n_multi),
        "root_share": sum(p.n_roots for p in parts) / n if n else nan,
        "isolated_share": sum(p.n_isolated for p in parts) / n if n else nan,
        "n_layers_max": float(max((p.n_layers for p in parts), default=0)),
        "multi_parent_share": float((indeg >= 2).mean()) if len(indeg) else nan,
        "mean_parents": float(indeg.mean()) if len(indeg) else nan,
        "sibling_merge_share": sum(p.n_sib for p in parts) / n_multi if n_multi else nan,
        "outdeg_gini": gini(outdeg),
        "top10_child_share": top_share(outdeg),
        "cross_layer_share": sum(p.n_cross for p in parts) / n_edges if n_edges else nan,
    }
    for b in PARENT_BINS:
        lo = int(b.rstrip("+"))
        sel = indeg >= lo if b.endswith("+") else indeg == lo
        out[f"parents_{b}"] = float(sel.mean()) if len(indeg) else nan
    return out


def quantile_of(obs: float, gen: np.ndarray) -> float:
    """Mid-rank quantile of `obs` in the generator values (share below plus half the ties)."""
    g = gen[np.isfinite(gen)]
    if not math.isfinite(obs) or len(g) == 0:
        return math.nan
    return float(((g < obs).sum() + 0.5 * (g == obs).sum()) / len(g))
