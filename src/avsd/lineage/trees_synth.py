"""Synthetic validation of the B2 tree inference (SPEC 6.4.5, 3.5).

Each replicate simulates transmission trees with AI Village quantities taken
from the real run, then runs the same inference (`trees_core`, a KDE refitted
on the simulated single-candidate edges, the real gamma) and the same H1 test:

- Agents and timing: each unit starts at the time of a random real unit's first
  occurrence; its population is the set of agents active on that run day
  (`roster_daily`). Active time runs at the median real run-day length, so L_B
  is 3 run days of active time.
- Branching: each occurrence has Poisson(R_g) children, with R_g the observed
  MAP mean offspring of generation g (g = 0, 1, 2 or more), at most
  `max_size` occurrences per unit. The channel of a child follows the MAP
  channel mix given the parent's source (chat parents: chat to another agent,
  chat to the same agent, chat to another agent's memory, chat to the same
  agent's memory; memory parents: back to chat). Serial intervals are drawn
  from the real kernels of those channels (chat channels within L_B).
- Independent observation: with the real MAP independent share, a node is a
  new env-observed occurrence of a random agent with an observation shortly
  before it (env kernel); it starts a new subtree. Agents of other children
  get a spurious observation before their first exposure with the real share
  of children that have an env candidate but a transmission MAP parent.
- Content: a child copies its parent's variants and adds a new one with
  probability c (the real share of MAP edges with a new non-root variant).
- Exposure: one room; every agent of the unit's population sees every chat
  occurrence; memory is never lost.

H1 holds by construction (intervals do not depend on the generation), so the
share of replicates with p < 0.05 estimates the type I error of the whole
procedure, inference included. The same test on the true trees separates the
test's own size from errors of the tree inference. Tests use agent-level
generations (one per transmission to a new agent; re-mentions keep the
generation), as the real analysis does, and occurrence-level generations for
reference. A power check scales the interval into every new agent's
acquisition at agent-level generation gA >= 2 by `alt_scale ** (gA - 1)`.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import multiprocessing as mp
import time

import numpy as np

from avsd.lineage import trees_stats as ts
from avsd.lineage.trees_core import (
    CHAT, ENV, I64_MAX, MEMORY, NONE, Occ, Ragged, finish_cands, forest, map_choice, posterior,
    single_candidate_edges, unit_candidates,
)
from avsd.lineage.trees_kernel import KEY_CODE, EmpiricalKernel

CHAT_KEYS = ("chat>chat:other", "chat>chat:self", "chat>memory:other", "chat>memory:self")


def real_params(inp: dict, c, main: dict, kernel: EmpiricalKernel, gamma: float) -> dict:
    """Quantities of the real MAP forest that drive the simulation."""
    occ: Occ = inp["occ"]
    f: ts.Forest = main["forest"]
    e: ts.Edges = main["edges_all"]
    kids = np.bincount(e.parent, minlength=occ.n)
    full = occ.pos <= inp["clock"].end - 3.0
    R = []
    for g in (0, 1):
        m = full & (f.gen == g)
        R.append(float(kids[m].mean()) if m.any() else 0.5)
    m = full & (f.gen >= 2)
    R.append(float(kids[m].mean()) if m.any() else R[-1])
    keys = c.key[e.row]
    chat_counts = np.array([int((keys == KEY_CODE[k]).sum()) for k in CHAT_KEYS], dtype=float)
    p_chat = chat_counts / chat_counts.sum() if chat_counts.sum() else np.array([0.7, 0.1, 0.15, 0.05])
    nonfirst = (f.parent >= 0) | (f.parent == ENV)
    p_env = float((f.parent == ENV).sum() / max(nonfirst.sum(), 1))
    kids_c, starts = c.offsets()
    has_env = np.zeros(occ.n, dtype=bool)
    has_env[c.child[c.parent == ENV]] = True
    trans = f.parent >= 0
    p_spur = float((has_env & trans).sum() / max(trans.sum(), 1))
    has_q = c.n_var_q[e.child] > 0
    var_new = (c.n_var_q[e.child] - c.S_q[e.row]) > 0
    c_change = float(var_new[has_q].mean()) if has_q.any() else 0.1
    roots = np.flatnonzero(occ.start[:-1] >= 0)
    first = occ.start[:-1]
    day_len = float(np.median(np.diff(inp["clock"].lo))) if len(inp["clock"].lo) > 1 else 14400.0
    act = inp["roster"].filter(inp["roster"]["active"]).group_by("run_day").agg("agent_id")
    pops = {int(rd): [inp["a_index"][a] for a in ags if a in inp["a_index"]] for rd, ags in act.iter_rows()}
    return {"R": R, "p_chat": p_chat, "p_env": p_env, "p_spur": p_spur, "c": c_change, "gamma": gamma,
            "root_t": occ.t[first].copy(), "root_pos": occ.pos[first].copy(), "day_len": day_len,
            "pops": pops, "kernel": kernel, "n_units_real": int(len(roots)),
            "n_edges_real": int(len(e.child)), "max_size": 30}


def simulate(par: dict, n_units: int, rng: np.random.Generator, alt_scale: float = 1.0) -> tuple[Occ, dict]:
    """One synthetic data set and its true parents (see the module docstring)."""
    kern: EmpiricalKernel = par["kernel"]
    D = par["day_len"]
    L = 3.0 * D
    units = []
    for _ in range(n_units):
        k = int(rng.integers(len(par["root_t"])))
        t0 = float(par["root_t"][k])
        pop = par["pops"].get(int(np.floor(par["root_pos"][k])), [])
        if len(pop) < 2:
            pop = list(range(8))
        pop = np.array(pop)
        # (t, src, actor, gen_true, parent_local or NONE/ENV, variants tuple, env_hit_t or nan, agent-level gen)
        nodes = []

        def add(t, src, actor, gen, parent, var, env_t=np.nan, ga=0):
            nodes.append([t, src, actor, gen, parent, var, env_t, ga])
            return len(nodes) - 1

        a0 = int(rng.choice(pop))
        add(t0, CHAT, a0, 0, NONE, ())
        holders = {a0: 0}  # agent -> agent-level generation of its acquisition (in order of simulation)
        mem_of: dict[int, int] = {}
        q = 0
        while q < len(nodes) and len(nodes) < par["max_size"]:
            t, src, actor, gen, _, var, _, ga = nodes[q]
            R = par["R"][min(gen, 2)]
            for _ in range(int(rng.poisson(R))):
                if len(nodes) >= par["max_size"]:
                    break
                if rng.random() < par["p_env"]:
                    a = int(rng.choice(pop))
                    tc = t + float(rng.uniform(0.0, 2 * D))
                    de = float(kern.sample(KEY_CODE["env>chat"], 1, rng)[0])
                    add(tc, CHAT, a, 0, ENV, (), tc - min(de, L * 0.99))
                    holders.setdefault(a, 0)
                    continue
                if src == MEMORY:
                    key = "memory>chat"
                    child_src, a = CHAT, actor
                else:
                    key = CHAT_KEYS[int(rng.choice(4, p=par["p_chat"]))]
                    others = pop[pop != actor]
                    other = int(rng.choice(others)) if len(others) else actor
                    a = other if key.endswith("other") else actor
                    child_src = MEMORY if "memory" in key else CHAT
                    if child_src == MEMORY and a in mem_of:
                        continue
                dt = float(kern.sample(KEY_CODE[key], 1, rng)[0])
                if key != "memory>chat":
                    for _ in range(20):
                        if dt <= L:
                            break
                        dt = float(kern.sample(KEY_CODE[key], 1, rng)[0])
                    dt = min(dt, L * 0.999)
                g_child = gen + 1
                new_agent = a not in holders
                ga_child = holders.get(actor, 0) + 1 if new_agent else holders[a]
                if new_agent:
                    holders[a] = ga_child
                if alt_scale != 1.0 and new_agent and ga_child >= 2:
                    dt *= alt_scale ** (ga_child - 1)
                newvar = var + ((int(rng.integers(1, 2 ** 62)),) if rng.random() < par["c"] else ())
                j = add(t + max(dt, 1.0), child_src, a, g_child, q, newvar, ga=ga_child)
                if child_src == MEMORY:
                    mem_of[a] = j
            q += 1
        units.append(nodes)
    return _to_occ(units, par, rng)


def _to_occ(units: list, par: dict, rng: np.random.Generator) -> tuple[Occ, dict]:
    """Arrays of the simulated occurrences. An agent that acquires a unit independently did not see the
    unit's earlier chat occurrences (it was elsewhere), so its observation precedes its first exposure."""
    D = par["day_len"]
    ts_l, t_l, src_l, act_l, var_l, start = [], [], [], [], [], [0]
    true_parent, true_gen = [], []
    env: dict = {}
    vis_all = []
    for u, nodes in enumerate(units):
        order = sorted(range(len(nodes)), key=lambda q: (nodes[q][0], q))
        newpos = {q: k for k, q in enumerate(order)}
        base = start[-1]
        pop_mask = 0
        for nd in nodes:
            pop_mask |= 1 << int(nd[2])
        # Agents that observe independently do not see chat posted before their own occurrence.
        blind = {}
        for q in order:
            t, _, actor, _, parent, _, _, _ = nodes[q]
            if parent == ENV:
                blind[int(actor)] = max(blind.get(int(actor), -np.inf), t)
        for q in order:
            t, src, actor, gen, parent, var, env_t, _ = nodes[q]
            ts_l.append(int(round(t * 1e6)))
            t_l.append(t)
            src_l.append(src)
            act_l.append(actor)
            var_l.append(np.array(var, dtype=np.int64))
            true_gen.append(gen)
            true_parent.append(base + newpos[parent] if parent >= 0 else parent)
            m = pop_mask
            for a, tb in blind.items():
                if t < tb:
                    m &= ~(1 << a)
            vis_all.append(m)
            if parent == ENV:
                env.setdefault((u, actor), []).append(env_t)
            elif parent >= 0 and rng.random() < par["p_spur"]:
                lo = max(nodes[parent][0] - 3 * D, 0.0)
                env.setdefault((u, actor), []).append(float(rng.uniform(lo, nodes[parent][0])))
        start.append(base + len(nodes))
    t = np.array(t_l)
    pos = t / D
    n = len(t)
    env_arr = {}
    for k, v in env.items():
        v = np.sort(np.array(v))
        env_arr[k] = ((v * 1e6).round().astype(np.int64), v, v / D)
    occ = Occ(
        start=np.array(start, dtype=np.int64), ts=np.array(ts_l, dtype=np.int64), t=t, pos=pos,
        src=np.array(src_l, dtype=np.int8), actor=np.array(act_l, dtype=np.int16),
        vis=np.array(vis_all, dtype=np.uint64), room=np.zeros(n, np.int32), vday=np.zeros(n, np.int32),
        s0=np.full(n, -1, np.int32), s1=np.full(n, -2, np.int32), rz=np.full(n, -1, np.int32),
        tin=np.full(n, np.nan), date=np.zeros(n, dtype="datetime64[D]"), mem_end=np.full(n, I64_MAX, np.int64),
        mem_rs={}, qv_key=Ragged.from_lists([[] for _ in range(n)]),
        qv_val=Ragged.from_lists([[] for _ in range(n)]), grams=Ragged.from_lists(var_l), env=env_arr)
    occ.unit = np.repeat(np.arange(len(units)), np.diff(np.array(start)))
    return occ, {"parent": np.array(true_parent, dtype=np.int64), "gen": np.array(true_gen, dtype=np.int64)}


def true_forest(truth: dict) -> ts.Forest:
    p = truth["parent"]
    gen = np.zeros(len(p), dtype=np.int32)
    root = np.arange(len(p), dtype=np.int64)
    for i in range(len(p)):
        if p[i] >= 0:
            gen[i] = gen[p[i]] + 1
            root[i] = root[p[i]]
    return ts.Forest(np.full(len(p), -1), p, gen, root)


def _edges_from_parent(occ: Occ, f: ts.Forest, key_of_child: np.ndarray) -> ts.Edges:
    child = np.flatnonzero(f.parent >= 0)
    par = f.parent[child]
    key = key_of_child[child].astype(np.int64)
    return ts.Edges(child, par, np.zeros(len(child), np.int64), key, ts.CH_OF_KEY[key], occ.t[child] - occ.t[par],
                    f.gen[child], f.root[child], ts.ST_OF_KEY[key])


def true_keys(occ: Occ, truth: dict) -> np.ndarray:
    p = truth["parent"]
    key = np.full(len(p), -1, dtype=np.int64)
    for i in np.flatnonzero(p >= 0):
        j = p[i]
        ps, cs = occ.src[j], occ.src[i]
        if ps == MEMORY:
            key[i] = KEY_CODE["memory>chat"]
        else:
            same = occ.actor[j] == occ.actor[i]
            if cs == MEMORY:
                key[i] = KEY_CODE["chat>memory:self" if same else "chat>memory:other"]
            else:
                key[i] = KEY_CODE["chat>chat:self" if same else "chat>chat:other"]
    return key


def one_replicate(par: dict, n_units: int, seed: int, perms: int, alt_scale: float = 1.0) -> dict:
    rng = np.random.default_rng(seed)
    occ, truth = simulate(par, n_units, rng, alt_scale)
    c = finish_cands(occ, [unit_candidates(occ, u, 3.0, "precede", "main") for u in range(occ.n_units)])
    single = single_candidate_edges(c)
    kern = EmpiricalKernel(min_edges=50, seed=seed).fit(c.key[single], c.dt[single])
    K = kern.density(c.edge_times(occ))
    post = posterior(c, K, par["gamma"])
    chosen = map_choice(c, post, occ.n)
    p_hat, g_hat, r_hat = forest(c, chosen)
    tp, tg = truth["parent"], truth["gen"]
    nonroot = tp != NONE
    out = {"seed": seed, "alt_scale": alt_scale, "n_units": occ.n_units, "n_occ": occ.n,
           "n_true_edges": int((tp >= 0).sum()), "n_true_env": int((tp == ENV).sum()),
           "parent_accuracy": float((p_hat[nonroot] == tp[nonroot]).mean()) if nonroot.any() else np.nan,
           "parent_accuracy_transmission": float((p_hat[tp >= 0] == tp[tp >= 0]).mean()) if (tp >= 0).any() else np.nan,
           "env_recall": float((p_hat[tp == ENV] == ENV).mean()) if (tp == ENV).any() else np.nan,
           "generation_accuracy": float((g_hat == tg).mean()),
           "generation_accuracy_nonroot": float((g_hat[nonroot] == tg[nonroot]).mean()) if nonroot.any() else np.nan,
           "generation_mae": float(np.abs(g_hat - tg).mean())}
    tf = true_forest(truth)
    end = float(occ.pos.max()) + 3.0
    e_true = _edges_from_parent(occ, tf, true_keys(occ, truth))
    f_hat = ts.Forest(chosen, p_hat, g_hat, r_hat)
    e_hat = ts.edges(c, f_hat)
    det = ts.determined(c, f_hat)
    av_t, av_h = ts.agent_view(tf, occ.actor, occ.unit), ts.agent_view(f_hat, occ.actor, occ.unit)
    det_a = ts.determined_agent(c, f_hat, av_h)
    acq_t = av_h.acq & (tp >= 0)
    out["agent_generation_accuracy"] = float((av_h.gen[acq_t] == av_t.gen[acq_t]).mean()) if acq_t.any() else np.nan
    out["determined_share"] = float(det_a[e_hat.child][av_h.acq[e_hat.child]].mean()) \
        if av_h.acq[e_hat.child].any() else np.nan
    dm = det_a & acq_t
    out["determined_parent_accuracy"] = float((p_hat[dm] == tp[dm]).mean()) if dm.any() else np.nan
    out["determined_agent_generation_accuracy"] = float((av_h.gen[dm] == av_t.gen[dm]).mean()) if dm.any() else np.nan
    ea_true, _ = ts.agent_edges(e_true, av_t)
    ea_hat, _ = ts.agent_edges(e_hat, av_h)
    views = (("", (("true", ea_true, None), ("inferred", ea_hat, None), ("determined", ea_hat, det_a))),
             ("occ_", (("true", e_true, None), ("inferred", e_hat, None), ("determined", e_hat, det))))
    for pre, trees in views:
        for name, e, extra in trees:
            ok = ts.forward_mask(e, occ.pos, end, 3.0)
            if extra is not None:
                ok &= extra[e.child]
            rows = ts.h1_ad_tests(e, ok, 30, perms, rng)
            for r in rows:
                out[f"{pre}p_{name}_{r['channel']}"] = r["p_perm"]
                out[f"{pre}ngen_{name}_{r['channel']}"] = r["n_generations"]
    return out


_P: dict = {}


def _job(args):
    from avsd.lineage.trees import single_thread

    single_thread()
    n_units, seed, perms, alt = args
    return one_replicate(_P["par"], n_units, seed, perms, alt)


def run_synthetic(inp: dict, c, main: dict, kernel: EmpiricalKernel, gamma: float, cl: dict, seed: int,
                  n_workers: int, log=print) -> dict:
    """Null replicates (H1 true) and power replicates; returns per-replicate rows and summaries."""
    t0 = time.perf_counter()
    par = real_params(inp, c, main, kernel, gamma)
    n_units = int(cl.get("synthetic_units", 20000))
    reps = int(cl.get("synthetic_reps", 100))
    perms = 199
    jobs = [(n_units, seed * 1000 + r, perms, 1.0) for r in range(reps)]
    jobs += [(n_units, seed * 1000 + 10_000 + r, perms, 1.5) for r in range(max(10, reps // 4))]
    _P["par"] = par
    if n_workers > 1:
        with mp.get_context("fork").Pool(min(n_workers, len(jobs))) as pool:
            rows = pool.map(_job, jobs, chunksize=1)
    else:
        rows = [_job(j) for j in jobs]
    log(f"synthetic: {len(rows)} replicates of {n_units:,} units in {time.perf_counter() - t0:.0f} s")
    par_out = {k: (v.tolist() if isinstance(v, np.ndarray) and v.size < 10 else v) for k, v in par.items()
               if k not in ("kernel", "root_t", "root_pos", "pops")}
    return {"rows": rows, "params": par_out, "n_units": n_units, "reps": reps}
