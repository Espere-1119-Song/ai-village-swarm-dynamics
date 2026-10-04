"""Example dependency graph for the write-up: one AI Village goal and one generator DAG of the same size.

Run after `avsd swarmsim calibrate`. Writes, without session ids or agent names:
- outputs/tables/depgraph_example_nodes.csv: graph, node (start order within the goal), layer, agent
  (rank by sessions in the goal, -1 for the generator) and whether the node has no edge at all;
- outputs/tables/depgraph_example_edges.csv: graph, parent, child, same_agent and the layer gap.

The generator DAG is replicate 0 of the first size rule for this goal in `run_calibration`, so it is
one of the 64 graphs behind the structure comparison.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import polars as pl

from avsd.config import REPO_ROOT, load_config
from avsd.swarmsim.calibrate import CalibConfig, _rng, goal_graphs
from avsd.swarmsim.dag import BLOG, grow_dag
from avsd.swarmsim.depgraph import layers_of
from avsd.swarmsim.depgraph_data import load_sessions, paths


def write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def summary(name: str, n: int, layer, pairs: list[tuple[int, int]], same: list[int] | None) -> None:
    linked = {a for a, _ in pairs} | {b for _, b in pairs}
    parents = Counter(b for _, b in pairs)
    gaps = [int(layer[b] - layer[a]) for a, b in pairs]
    print(f"{name}: {n} nodes, {len(linked)} with an edge, {len(pairs)} edges, {int(max(layer)) + 1} layers, "
          f"mean parents of a node with parents {sum(parents.values()) / max(len(parents), 1):.2f}, "
          f"edges skipping a layer {sum(g >= 2 for g in gaps) / max(len(gaps), 1):.3f}"
          + ("" if same is None else f", same-agent edges {sum(same) / max(len(same), 1):.3f}"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--goal", default="G43", help="goal label as in depgraph_goals.csv")
    args = ap.parse_args()
    cfg = load_config()
    cc = CalibConfig.from_cfg(cfg)
    T = Path(cfg["paths"]["tables"])
    sessions = load_sessions(cfg)
    edges = pl.read_parquet(paths(cfg)["dir"] / "edges_main.parquet")
    goals = pl.read_parquet(T / "village_goals.parquet", columns=["id", "start_time", "end_time"])
    gg = goal_graphs(sessions, edges, goals)
    g = next(x for x in gg.goal_ids if gg.goal_label[x] == args.goal)
    gi = gg.goal_ids.index(g)
    ids = [int(s) for s in gg.nodes[g]]
    local = {s: i for i, s in enumerate(ids)}
    agent_of = dict(zip(sessions["s"].to_list(), sessions["agent_id"].to_list(), strict=True))
    agents = [agent_of[s] for s in ids]
    rank = {a: r for r, (a, _) in enumerate(sorted(Counter(agents).items(), key=lambda kv: (-kv[1], kv[0])))}
    e = (edges.filter(pl.col("parent").is_in(ids) & pl.col("child").is_in(ids))
         .select("parent", "child").unique())
    pairs = sorted((local[int(a)], local[int(b)]) for a, b in zip(e["parent"].to_list(), e["child"].to_list(),
                                                                  strict=True))
    layer = gg.layer[g]
    same = [int(agents[a] == agents[b]) for a, b in pairs]
    linked = {a for a, _ in pairs} | {b for _, b in pairs}

    dag = grow_dag(len(ids), cc.gen_layers, BLOG.peak, BLOG.merge_p, _rng(cc.seed, 7, 0, gi, 0), BLOG)
    gpairs = [(p, c) for c, ps in enumerate(dag.parents) for p in ps]
    glayer = layers_of(dag.parents)
    glinked = {a for a, _ in gpairs} | {b for _, b in gpairs}

    out = REPO_ROOT / "outputs" / "tables"
    write(out / "depgraph_example_nodes.csv", ["graph", "goal", "node", "layer", "agent", "no_edge"],
          [["ai_village", args.goal, i, int(layer[i]), rank[agents[i]], int(i not in linked)] for i in range(len(ids))]
          + [["generator", args.goal, i, int(glayer[i]), -1, int(i not in glinked)] for i in range(len(glayer))])
    write(out / "depgraph_example_edges.csv", ["graph", "parent", "child", "same_agent", "layer_gap"],
          [["ai_village", a, b, s, int(layer[b] - layer[a])] for (a, b), s in zip(pairs, same, strict=True)]
          + [["generator", a, b, "", int(glayer[b] - glayer[a])] for a, b in gpairs])
    print(f"{args.goal}: {len(rank)} agents")
    summary("AI Village", len(ids), layer, pairs, same)
    summary("generator", len(glayer), glayer, gpairs, None)


if __name__ == "__main__":
    main()
