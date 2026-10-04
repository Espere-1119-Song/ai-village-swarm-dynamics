"""Tests of the swarm simulator re-implementation (SPEC 8.2 D1).

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pytest

from avsd.swarmsim.dag import (
    BLOG, Dag, Draws, GenParams, draw_task, grow_dag, layer_sizes, relayer, score_scale, scores,
    structure_stats,
)
from avsd.swarmsim.metrics import (
    coverage_curve, first_reach, mean_curve, on_grid, scaling_exponent,
)
from avsd.swarmsim.reproduce import ReproConfig, _family
from avsd.swarmsim.sim import (
    BLOG_OVERHEADS, comm_factor, median_step_cost, pass_at_k, record_events, simulate, single_agent,
)


def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def hand_dag(parents: list[list[int]], layer: list[int]) -> Dag:
    """A DAG from parent lists (topological ids) with blog costs c_d = 1 + 9 d / (D - 1)."""
    lay = np.asarray(layer)
    D = int(lay.max()) + 1
    children: list[list[int]] = [[] for _ in parents]
    for c, ps in enumerate(parents):
        for p in ps:
            children[p].append(c)
    sizes = np.bincount(lay, minlength=D)
    return Dag(lay, parents, children, np.zeros(len(parents)), np.zeros(len(parents)),
               1.0 + 9.0 * lay / max(1, D - 1), sizes, 0.0)


def ancestors(dag: Dag) -> list[set[int]]:
    anc: list[set[int]] = []
    for ps in dag.parents:
        a: set[int] = set()
        for p in ps:
            a |= anc[p] | {p}
        anc.append(a)
    return anc


# --- generator ---------------------------------------------------------------------------------

@pytest.mark.parametrize("seed,n,D,peak,mp", [(1, 723, 17, 0.28, 0.46), (2, 300, 12, 0.35, 0.9),
                                              (3, 80, 25, 0.15, 0.6), (4, 40, 3, 0.5, 0.46)])
def test_generator_invariants(seed: int, n: int, D: int, peak: float, mp: float) -> None:
    dag = grow_dag(n, D, peak, mp, rng(seed))
    assert dag.n == n == int(dag.sizes.sum())
    assert np.array_equal(np.bincount(dag.layer, minlength=D), dag.sizes)
    assert dag.layer[0] == 0 and dag.parents[0] == [] and dag.value[0] == 0.0
    assert dag.sizes[0] == 1
    g = nx.DiGraph(dag.edges())
    assert nx.is_directed_acyclic_graph(g)
    anc = ancestors(dag)
    nonempty = [d for d in range(D) if dag.sizes[d] > 0]
    for c in range(1, n):
        ps = dag.parents[c]
        assert ps and len(set(ps)) == len(ps)
        assert all(p < c and dag.layer[p] < dag.layer[c] for p in ps)
        # the main parent comes from the previous non-empty layer
        prev = max(d for d in nonempty if d < dag.layer[c])
        assert dag.layer[ps[0]] == prev
        # no two parents lie on one chain
        for p in ps:
            assert not any(p in anc[x] for x in ps if x != p)
        assert dag.value[c] == pytest.approx(max(dag.value[p] for p in ps) + dag.imp[c])
        assert c in dag.children[ps[0]]
    assert np.allclose(dag.cost, 1 + 9 * dag.layer / (D - 1))
    assert np.array_equal(relayer(dag), dag.layer) or 0 in dag.sizes


def test_layer_profile_peaks_near_28_percent() -> None:
    dr = Draws(rng(5))
    flat = layer_sizes(723, 17, 0.28, dr, GenParams(size_noise=0.0))
    assert int(np.argmax(flat[1:])) + 1 in (4, 5)          # 0.28 * 16 = 4.48
    peaks = [(int(np.argmax(m[1:])) + 1) / 16 for m in (layer_sizes(723, 17, 0.28, dr) for _ in range(400))]
    assert abs(np.mean(peaks) - 0.28) < 0.03
    mean_profile = np.mean([layer_sizes(723, 17, 0.28, dr) for _ in range(400)], axis=0)
    assert int(np.argmax(mean_profile[1:])) + 1 in (4, 5)


def test_task_draws_and_scale() -> None:
    r = rng(6)
    for _ in range(200):
        t = draw_task(r)
        assert 10 <= t.n_steps <= 1500 and 3 <= t.n_layers <= 30
        assert 0.1 <= t.peak <= 0.9 and 0.0 <= t.merge_p <= 0.9 and abs(t.clock) <= 0.3
    t = draw_task(rng(7))
    p = GenParams(scale_draws=8)
    h = score_scale(t, [rng(100 + k) for k in range(8)], p)
    best = sorted(grow_dag(t.n_steps, t.n_layers, t.peak, t.merge_p, rng(100 + k)).value.max()
                  for k in range(8))
    assert h == best[round(0.9 * 7)]
    dag = grow_dag(t.n_steps, t.n_layers, t.peak, t.merge_p, rng(8))
    v = scores(dag, h)
    assert v[0] == 0.0 and v.min() >= 0.0 and v.max() <= 1.0


def test_structure_stats_ranges() -> None:
    st = structure_stats(grow_dag(723, 17, 0.28, 0.46, rng(9)))
    for k in ("cross_layer_share", "best_depth_share", "leaf_share", "multi_parent_share",
              "outdeg_gini", "top10_child_share"):
        assert 0.0 <= st[k] <= 1.0
    assert st["mean_parents"] >= 1.0


# --- agents ------------------------------------------------------------------------------------

def check_readiness(dag: Dag, run) -> None:
    assert np.all(np.isfinite(run.finish))
    for c in range(dag.n):
        assert run.finish[c] >= run.start[c]
        for p in dag.parents[c]:
            assert run.start[c] >= run.finish[p]


@pytest.mark.parametrize("n_agents,layers", [(1, 1), (4, 1), (16, 1), (4, 3), (16, 3), (8, 99)])
def test_readiness_and_budget(n_agents: int, layers: int) -> None:
    dag = grow_dag(300, 12, 0.28, 0.46, rng(10))
    run = simulate(dag, n_agents, rng(11), layers=layers,
                   overheads=BLOG_OVERHEADS if n_agents > 1 else None)
    check_readiness(dag, run)
    assert run.peak_active <= n_agents
    assert run.agent_depth.max() <= layers
    if layers == 1:
        assert np.all(run.agent_depth == 1) and np.all(run.agent_up == -1)
    # an agent's layer is one below its forker's
    for a, up in enumerate(run.agent_up):
        if up >= 0:
            assert run.agent_depth[a] == run.agent_depth[up] + 1


def test_single_agent_takes_the_deepest_ready_step() -> None:
    dag = grow_dag(400, 14, 0.28, 0.6, rng(12))
    run = single_agent(dag, rng(13))
    check_readiness(dag, run)
    assert run.schedule == 0.0 and run.comm == 0.0
    order = np.argsort(run.start, kind="stable")
    started: set[int] = set()
    for i in order:
        t = run.start[i]
        ready = [c for c in range(dag.n) if c not in started
                 and all(run.finish[p] <= t for p in dag.parents[c])]
        assert dag.layer[i] == max(dag.layer[c] for c in ready)
        started.add(int(i))
    # one agent works one step at a time
    assert np.all(run.start[order][1:] >= run.finish[order][:-1] - 1e-9)


def test_deepest_first_on_hand_built_dag() -> None:
    # root -> a1, b1; a1 -> a2 -> a3
    dag = hand_dag([[], [0], [0], [1], [3]], [0, 1, 1, 2, 3])
    seen = set()
    for s in range(30):
        run = single_agent(dag, rng(s), time_noise=0.0)
        seen.add(tuple(np.argsort(run.finish)))
    assert seen == {(0, 1, 3, 4, 2), (0, 2, 1, 3, 4)}


def test_merge_step_waits_for_every_parent() -> None:
    # root -> a, b; c merges a and b
    dag = hand_dag([[], [0], [0], [1, 2]], [0, 1, 1, 2])
    run = simulate(dag, 2, rng(1), overheads=None, time_noise=0.0)
    assert run.start[3] >= max(run.finish[1], run.finish[2])


def test_overhead_accounting_standard_two_agents() -> None:
    # root (cost 1) -> a, b (cost 10); median step cost 10, so scheduling is 0.5 per event
    dag = hand_dag([[], [0], [0]], [0, 1, 1])
    assert median_step_cost(dag) == 10.0
    run = simulate(dag, 2, rng(3), overheads=BLOG_OVERHEADS, time_noise=0.0)
    assert run.finish[0] == pytest.approx(1.5)                  # startup 0.5 + work 1
    assert sorted(run.finish[1:]) == pytest.approx([13.0, 14.0])  # 10 * 1.15; new agent + 0.5 + 0.5
    assert run.work == pytest.approx(21.0)
    assert run.schedule == pytest.approx(1.5)
    assert run.comm == pytest.approx(3.0)
    assert (run.n_startups, run.n_handoffs) == (2, 1)
    # the agent that finished the root continues without scheduling overhead
    cont = 1 if run.who[1] == run.who[0] else 2
    assert run.finish[cont] == pytest.approx(13.0)


def test_overhead_accounting_four_agents() -> None:
    # root -> four steps of layer 1, every agent busy at once
    dag = hand_dag([[], [0], [0], [0], [0]], [0, 1, 1, 1, 1])
    std = simulate(dag, 4, rng(4), layers=1, overheads=BLOG_OVERHEADS, time_noise=0.0)
    assert std.step_comm[1:] == pytest.approx([0.17] * 4)     # 15% + 2 x 1%
    assert std.schedule == pytest.approx(0.5 + 3 * 1.0)
    assert std.comm == pytest.approx(4 * 10 * 0.17)
    assert sorted(std.finish[1:]) == pytest.approx([13.2, 14.2, 14.2, 14.2])
    rec = simulate(dag, 4, rng(4), layers=3, overheads=BLOG_OVERHEADS, time_noise=0.0)
    assert sorted(rec.agent_depth) == [1, 2, 2, 2]
    assert rec.step_comm[1:] == pytest.approx([0.17] * 4)     # forker's group of four
    rec2 = simulate(hand_dag([[], [0], [0]], [0, 1, 1]), 2, rng(4), layers=2,
                    overheads=BLOG_OVERHEADS, time_noise=0.0)
    assert sorted(rec2.agent_depth) == [1, 2]
    assert rec2.step_comm[1:] == pytest.approx([0.15, 0.15])


def test_comm_factor_blog_examples() -> None:
    assert comm_factor([4]) == pytest.approx(0.17)          # standard swarm@4, all at work
    assert comm_factor([2, 2]) == pytest.approx(0.30)       # dispatched agent with a sub-agent
    assert comm_factor([2]) == pytest.approx(0.15)          # its sub-agent
    assert comm_factor([1]) == 0.0
    assert comm_factor([64]) == pytest.approx(0.77)


def test_single_agent_time_is_total_cost_without_noise() -> None:
    dag = grow_dag(200, 10, 0.28, 0.46, rng(14))
    run = single_agent(dag, rng(15), time_noise=0.0)
    assert run.makespan == pytest.approx(dag.cost.sum())


def test_pass_at_k_and_records() -> None:
    dags = [grow_dag(150, 9, 0.28, 0.46, rng(20 + j)) for j in range(3)]
    runs = pass_at_k(dags, [rng(30 + j) for j in range(3)])
    assert len(runs) == 3 and all(r.schedule == r.comm == 0.0 for r in runs)
    v = np.array([0.0, 0.4, 0.2, 0.9, 0.5])
    t, w = record_events(np.array([0.0, 1.0, 2.0, 3.0, 4.0]), v)
    assert t.tolist() == [1.0, 3.0] and w == pytest.approx([0.4, 0.5])


def test_determinism() -> None:
    a, b = grow_dag(500, 15, 0.28, 0.46, rng(40)), grow_dag(500, 15, 0.28, 0.46, rng(40))
    assert a.parents == b.parents and np.array_equal(a.value, b.value)
    c = grow_dag(500, 15, 0.28, 0.46, rng(41))
    assert not np.array_equal(a.value, c.value)
    for n_agents, layers in ((1, 1), (16, 1), (16, 3)):
        ov = BLOG_OVERHEADS if n_agents > 1 else None
        r1 = simulate(a, n_agents, rng(42), layers=layers, overheads=ov)
        r2 = simulate(a, n_agents, rng(42), layers=layers, overheads=ov)
        r3 = simulate(a, n_agents, rng(43), layers=layers, overheads=ov)
        assert np.array_equal(r1.finish, r2.finish) and np.array_equal(r1.who, r2.who)
        assert not np.array_equal(r1.finish, r3.finish)


# --- metrics and protocol ------------------------------------------------------------------------

def test_curves_and_speedup() -> None:
    cov = coverage_curve([np.array([1.0, 2.0, 3.0, 4.0]), np.array([2.0, 4.0, 6.0, 8.0])])
    assert first_reach(cov, 0.5, t_max=10) == 3.0          # 2/8 + 1/8 + ... reaches 0.5 at t = 3
    assert first_reach(cov, 1.0, t_max=10) == 8.0
    assert math.isnan(first_reach(cov, 1.0, t_max=5))
    assert on_grid(cov, np.array([0.5, 2.0, 9.0])).tolist() == [0.0, 0.375, 1.0]
    best = mean_curve([np.array([1.0]), np.array([2.0])], [np.array([0.6]), np.array([1.0])])
    assert first_reach(best, 0.8, t_max=10) == 2.0
    assert scaling_exponent(33.0, 64) == pytest.approx(0.8407, abs=1e-4)


def test_repro_config_overrides() -> None:
    rc = ReproConfig.from_cfg({"seed": 7, "swarmsim": {"families": 3, "sizes": [1, 4]}})
    assert (rc.seed, rc.families, rc.sizes, rc.tasks) == (7, 3, (1, 4), 16)


def test_family_protocol_small() -> None:
    rc = ReproConfig(seed=1, families=1, tasks=3, sessions=3, sizes=(1, 2, 4))
    p = GenParams(n_steps=120, n_layers=9, scale_draws=8)
    out = _family((0, rc, p, BLOG_OVERHEADS))
    st = out["stats"]
    # T1 is the slowest single-agent run of the family
    assert max(t["slow"] for t in out["tasks"]) == pytest.approx(1.0)
    assert st["single:1:cov100"] == pytest.approx(1.0)
    assert st["standard:4:cov50"] < st["single:1:cov50"]
    for k in ("standard:2", "standard:4", "recursive:2", "recursive:4"):
        assert 0 < st[f"{k}:cov50"] <= st[f"{k}:cov90"] <= st[f"{k}:cov100"] <= 1.0
    assert out["tasks"][0]["scale"] > 0
    assert BLOG.n_steps == 723 and BLOG.n_layers == 17
