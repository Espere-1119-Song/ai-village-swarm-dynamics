"""Agents on a task DAG: one agent, pass@k, the standard swarm and the recursive swarm (SPEC 8.2 D1).

Step rule (every agent). A step is ready once all its parents are finished. A ready step is on an
agent's list once the agent finished any of its parents, so a merge step can sit on several lists
and goes to whoever takes it first. The agent takes the deepest step on its list, ties at random,
and works on it for c_d * exp(time_noise * z).

Standard swarm (`layers=1`). At most `n_agents` agents are alive. An agent whose list is empty
after a step stops. Whenever fewer than `n_agents` agents are alive and ready steps wait, the
coordinator starts a new agent on a uniformly random ready step. A ready step is held by the agent
that made it ready (finished its last parent). All agents report to the coordinator.

Recursive swarm (`layers=L > 1`). When a finished step opens several steps, the agent keeps one
(the opened steps are shuffled) and forks a sub-agent for each other one while fewer than
`n_agents` agents are alive and its own layer is below L; steps it cannot hand out join its list.
A free slot goes to a random ready step: the agent holding it forks a sub-agent for it unless the
holder sits at layer L (or has stopped), in which case the coordinator dispatches a new agent of
layer 1. The coordinator starts the first agent.

Overheads (when `overheads` is given). Scheduling: `schedule` times the median step cost (the
median of c_d over steps) on an agent's first step, and again on any step with a parent finished by
another agent; a dispatch takes the coordinator no time. Communication, per group (a superior and
the agents directly under it; the coordinator is not counted): a group of g >= 2 alive agents adds
`comm + comm_per * (g - 2)` of a step's work to every step of each member. A coordinator-started
agent's group is all alive coordinator-started agents; a sub-agent's group is its forker (if
alive) and the forker's alive sub-agents; an agent with alive sub-agents also pays for its own
group. Group sizes are read when a step starts, after every start, fork and stop of that instant,
and hold for the whole step. One agent on its own pays nothing (the blog's baseline).

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

from avsd.swarmsim.dag import Dag, Draws


@dataclass(frozen=True)
class Overheads:
    """Swarm costs. Defaults are the blog's values."""

    schedule: float = 0.05       # median steps, per start and per handoff
    comm: float = 0.15           # share of a step's work for a group of two active agents
    comm_per: float = 0.01       # added for each active member beyond two


BLOG_OVERHEADS = Overheads()


def comm_factor(groups: list[int], ov: Overheads = BLOG_OVERHEADS) -> float:
    """Extra share of a step's work for an agent in groups of the given sizes."""
    return sum(ov.comm + ov.comm_per * (g - 2) for g in groups if g >= 2)


@dataclass
class Run:
    """One run: when each step finished and who did it, plus agent and cost accounting."""

    finish: np.ndarray           # finish time of every step (raw clock)
    start: np.ndarray            # start time of every step
    who: np.ndarray              # agent that finished each step
    agent_depth: np.ndarray      # layer of every spawned agent (1 = started by the coordinator)
    agent_up: np.ndarray         # forker of every agent, -1 for coordinator-started agents
    peak_active: int
    work: float                  # sum of step times without overheads
    schedule: float              # scheduling overhead paid
    comm: float                  # communication cost paid
    n_startups: int
    n_handoffs: int
    step_comm: np.ndarray = field(default_factory=lambda: np.zeros(0))  # comm share of each step

    @property
    def makespan(self) -> float:
        return float(self.finish.max())


def median_step_cost(dag: Dag) -> float:
    """The blog's unit for the scheduling overhead: the median (upper middle) step cost."""
    return float(np.sort(dag.cost)[dag.n >> 1])


def simulate(dag: Dag, n_agents: int, rng: np.random.Generator, layers: int = 1,
             overheads: Overheads | None = None, time_noise: float = 0.2) -> Run:
    """Run a swarm of at most `n_agents` agents (`layers` = 1 standard, > 1 recursive).

    `n_agents=1` without overheads is the single-agent baseline.
    """
    n, B, L = dag.n, n_agents, layers
    rec = L > 1
    dr = Draws(rng)
    u, z = dr.u, dr.z
    lay = dag.layer.tolist()
    cost = dag.cost.tolist()
    pars, kids = dag.parents, dag.children
    D = int(dag.layer.max()) + 1
    hard = overheads.schedule * median_step_cost(dag) if overheads else 0.0

    need = [len(ps) for ps in pars]
    who = [-1] * n
    fin = [math.inf] * n
    beg = [math.inf] * n
    sc = [0.0] * n
    owner = [-1] * n
    avail: list[int] = []
    pos = [-1] * n

    def push(i: int) -> None:
        pos[i] = len(avail)
        avail.append(i)

    def remove(i: int) -> None:
        k = pos[i]
        if k < 0:
            return
        last = avail.pop()
        if k < len(avail):
            avail[k] = last
            pos[last] = k
        pos[i] = -1

    # agents
    own: list[list[list[int]]] = []   # per agent, per layer, steps on its list (lazy deletion)
    top_l: list[int] = []             # deepest layer that may be non-empty on the list
    alive: list[bool] = []
    depth: list[int] = []
    up: list[int] = []
    kids_on: list[int] = []
    started: list[bool] = []
    target: list[int] = []
    st = {"active": 0, "top": 0, "peak": 0}
    acc = {"work": 0.0, "schedule": 0.0, "comm": 0.0, "startups": 0, "handoffs": 0}
    heap: list[tuple[float, int]] = []
    pend: list[tuple[int, int, float]] = []

    def spawn(parent: int) -> int:
        own.append([[] for _ in range(D)])
        top_l.append(-1)
        alive.append(True)
        depth.append(1 if parent < 0 else depth[parent] + 1)
        up.append(parent)
        kids_on.append(0)
        started.append(False)
        target.append(-1)
        if parent >= 0:
            kids_on[parent] += 1
        else:
            st["top"] += 1
        st["active"] += 1
        st["peak"] = max(st["peak"], st["active"])
        return len(alive) - 1

    def stop(a: int) -> None:
        alive[a] = False
        st["active"] -= 1
        if up[a] >= 0:
            kids_on[up[a]] -= 1
        else:
            st["top"] -= 1

    def add_to(a: int, c: int) -> None:
        own[a][lay[c]].append(c)
        top_l[a] = max(top_l[a], lay[c])

    def deepest(a: int) -> int:
        b, d = own[a], top_l[a]
        while d >= 0:
            if b[d]:
                ok = [c for c in b[d] if pos[c] >= 0]
                b[d] = ok
                if ok:
                    top_l[a] = d
                    return ok[int(u() * len(ok))]
            d -= 1
        top_l[a] = -1
        return -1

    def start(a: int, i: int) -> None:
        remove(i)
        target[a] = i
        pend.append((a, i, cost[i] * (math.exp(time_noise * z()) if time_noise > 0 else 1.0)))

    def flush(t: float) -> None:
        for a, i, base in pend:
            extra = cm = 0.0
            if overheads is not None:
                if any(who[p] != a for p in pars[i]):
                    extra += hard
                    acc["handoffs"] += 1
                if not started[a]:
                    extra += hard
                    acc["startups"] += 1
                g = [st["top"] if up[a] < 0 else kids_on[up[a]] + int(alive[up[a]])]
                if kids_on[a]:
                    g.append(kids_on[a] + 1)
                cm = base * comm_factor(g, overheads)
                sc[i] = cm / base
            started[a] = True
            acc["work"] += base
            acc["schedule"] += extra
            acc["comm"] += cm
            beg[i] = t
            heapq.heappush(heap, (t + extra + base + cm, a))
        pend.clear()

    def fill() -> None:
        while st["active"] < B and avail:
            i = avail[int(u() * len(avail))]
            h = owner[i]
            if rec and h >= 0 and alive[h] and depth[h] < L:
                start(spawn(h), i)
            else:
                start(spawn(-1), i)

    for i in range(n):
        if need[i] == 0:
            push(i)
    fill()
    flush(0.0)
    while heap:
        t, a = heapq.heappop(heap)
        i = target[a]
        target[a] = -1
        who[i] = a
        fin[i] = t
        opened = []
        for c in kids[i]:
            need[c] -= 1
            if need[c] == 0:
                opened.append(c)
        if rec and len(opened) > 1:
            for k in range(len(opened) - 1, 0, -1):
                j = int(u() * (k + 1))
                opened[k], opened[j] = opened[j], opened[k]
        forks = []
        for k, c in enumerate(opened):
            if k > 0 and rec and st["active"] < B and depth[a] < L:
                forks.append((spawn(a), c))
                continue
            add_to(a, c)
            owner[c] = a
            push(c)
            seen = {a}
            for p in pars[c]:
                h = who[p]
                if h >= 0 and h not in seen and alive[h]:
                    add_to(h, c)
                    seen.add(h)
        j = deepest(a)
        if j >= 0:
            start(a, j)
        else:
            stop(a)
        for b, c in forks:
            start(b, c)
        fill()
        flush(t)

    return Run(
        finish=np.asarray(fin), start=np.asarray(beg), who=np.asarray(who),
        agent_depth=np.asarray(depth), agent_up=np.asarray(up), peak_active=st["peak"],
        work=acc["work"], schedule=acc["schedule"], comm=acc["comm"],
        n_startups=acc["startups"], n_handoffs=acc["handoffs"], step_comm=np.asarray(sc),
    )


def single_agent(dag: Dag, rng: np.random.Generator, time_noise: float = 0.2) -> Run:
    """One agent on its own: deepest ready step first, no overheads."""
    return simulate(dag, 1, rng, time_noise=time_noise)


def pass_at_k(dags: list[Dag], rngs: list[np.random.Generator]) -> list[Run]:
    """k agents that each follow the step rule on their own, part j on `dags[j]`.

    The best score of pass@k is the best over its parts. When every part works on one DAG, a step
    counts as covered once any part finished it (the elementwise minimum of the finish times).
    """
    return [single_agent(d, r) for d, r in zip(dags, rngs, strict=True)]


def record_events(finish: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best score so far as events: (times, increments) of the record-setting steps, from 0."""
    order = np.argsort(finish, kind="stable")
    v = values[order]
    best = np.maximum.accumulate(np.concatenate([[0.0], v]))
    inc = np.diff(best)
    keep = inc > 0
    return finish[order][keep], inc[keep]
