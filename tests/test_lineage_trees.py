"""Tests for module B2 (transmission trees): units, exposure, kernels, posterior, H1 and H3 tools.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

import json
from datetime import date

import numpy as np
import polars as pl
import pytest

from avsd.lineage import b2_units as bu
from avsd.lineage import trees_stats as ts
from avsd.lineage.b2_refs import NameMatcher, quote_spans
from avsd.lineage.trees_core import (
    CHAT, ENV, I64_MAX, MEMORY, NONE, SEARCH, Occ, Ragged, all_candidates, finish_cands, forest, map_choice,
    nonroot_variants, posterior, sample_choice, shared_counts, single_candidate_edges, unit_candidates,
)
from avsd.lineage.trees_kernel import KEY_CODE, KEYS, EdgeTimes, EmpiricalKernel, HawkesKernel, hawkes_g

DAY = 14400.0


def make_occ(rows, env=None, n_units=None):
    """rows: dicts with unit, t (active s), src, actor (-1 human), vis (agents), mem_end, grams, qv, vday, s0, s1."""
    rows = sorted(rows, key=lambda r: (r["unit"], r["t"]))
    n = len(rows)
    units = np.array([r["unit"] for r in rows])
    U = n_units or (int(units.max()) + 1)
    start = np.searchsorted(units, np.arange(U + 1))
    t = np.array([r["t"] for r in rows], dtype=float)
    vis = np.array([sum(1 << a for a in r.get("vis", range(8))) for r in rows], dtype=np.uint64)
    occ = Occ(
        start=start.astype(np.int64), ts=(t * 1e6).astype(np.int64), t=t, pos=t / DAY,
        src=np.array([r.get("src", CHAT) for r in rows], dtype=np.int8),
        actor=np.array([r["actor"] for r in rows], dtype=np.int16), vis=vis, room=np.zeros(n, np.int32),
        vday=np.array([r.get("vday", 0) for r in rows], dtype=np.int32),
        s0=np.array([r.get("s0", -1) for r in rows], dtype=np.int32),
        s1=np.array([r.get("s1", -2) for r in rows], dtype=np.int32),
        rz=np.zeros(n, np.int32), tin=t.copy(), date=np.zeros(n, dtype="datetime64[D]"),
        mem_end=np.array([r.get("mem_end", I64_MAX) for r in rows], dtype=np.int64), mem_rs={},
        qv_key=Ragged.from_lists([[k for k, _ in r.get("qv", [])] for r in rows]),
        qv_val=Ragged.from_lists([[v for _, v in r.get("qv", [])] for r in rows]),
        grams=Ragged.from_lists([r.get("grams", []) for r in rows]), env=env or {},
    )
    occ.unit = units
    return occ


# --- tokens, grams, provider responses -------------------------------------------------------------------------

def test_gram_ids_stable_and_spans_respected():
    bu.set_uninformative(frozenset({"the", "a", "of"}))
    g1 = bu.text_grams("Donations reached the new record level today")
    g2 = bu.text_grams("donations reached THE new record level today!")
    assert np.array_equal(g1, g2) and len(g1) == 4
    # A dropped span (a URL) splits the text: no gram crosses it.
    text = "alpha beta gamma https://x.org/a delta epsilon zeta eta"
    s = text.index("https")
    e = s + len("https://x.org/a")
    g = bu.text_grams(text, [(s, e)])
    assert len(g) == 1  # only "delta epsilon zeta eta"; "alpha beta gamma" has 3 tokens
    # Grams made only of stop words, digits and agent tokens are dropped.
    assert len(bu.text_grams("the of a the")) == 0


def test_in_sorted_matches_isin():
    rng = np.random.default_rng(0)
    ref = np.sort(rng.integers(-1000, 1000, 300))
    x = rng.integers(-1200, 1200, 500)
    assert np.array_equal(bu.in_sorted(x, ref), np.isin(x, ref))


def test_narrative_text_keeps_text_and_drops_tool_arguments():
    anthropic = {"content": [{"type": "thinking", "thinking": "seen 56 donors", "signature": "x" * 50},
                             {"type": "text", "text": "page says 56"},
                             {"type": "tool_use", "name": "bash", "input": {"command": "echo SECRET_TYPED"}}]}
    gemini = {"candidates": [{"content": {"parts": [{"text": "gemini view"}, {"functionCall": {"args": {"t": "TYPED"}}}]}}]}
    chat = {"role": "assistant", "content": "chat text", "reasoning_content": "why",
            "tool_calls": [{"function": {"arguments": "{\"message\": \"TYPED\"}"}}]}
    responses = [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "summary"}]},
                 {"type": "function_call", "arguments": "{\"x\": \"TYPED\"}"},
                 {"type": "message", "content": [{"type": "output_text", "text": "final"}]}]
    out = "\n".join(bu.narrative_text(json.dumps(o)) for o in (anthropic, gemini, chat, responses))
    for want in ("seen 56 donors", "page says 56", "gemini view", "chat text", "why", "summary", "final"):
        assert want in out
    assert "TYPED" not in out and "SECRET_TYPED" not in out
    assert bu.narrative_text(None) == "" and bu.narrative_text("not json") == ""


def test_own_day_values():
    from datetime import date

    v = bu.own_day_values(date(2026, 7, 13), 468)
    assert {"2026-07-13", "2026-07-12", "2026-07-14", "--07-13", "day:468", "day:467", "2026-07"} <= v
    assert "2026-07-20" not in v and "day:470" not in v


def test_observation_hits_quantities_need_context():
    from avsd.lineage.anchors import AnchorExtractor, TYPE_CODE

    ex = AnchorExtractor(["Claude Opus 4.5"], bytes(range(32)), None)
    bu.set_uninformative(frozenset())
    m = {"url": {"https://example.org/doc": [0]}, "date": {}, "quant": {(TYPE_CODE["number"], "56"): [(1, "donor")]},
         "ent": {"red cross": [2]}, "person": {}, "email": {}, "phone": {},
         "gram_ids": np.zeros(0, np.int64), "gram_unit": []}
    assert bu.observation_hits("see https://example.org/doc now", m, ex) == {0}
    assert bu.observation_hits("we have 56 donors so far", m, ex) == {1}
    assert bu.observation_hits("we have 56 items so far", m, ex) == set()
    assert bu.observation_hits("Thanks to the Red Cross team", m, ex) == {2}


# --- kernels ---------------------------------------------------------------------------------------------------------

def test_empirical_kernel_recovers_lognormal_and_falls_back():
    rng = np.random.default_rng(1)
    dt = np.exp(rng.normal(np.log(600), 0.5, 4000))
    key = np.full(len(dt), KEY_CODE["chat>chat:other"])
    k = EmpiricalKernel(min_edges=50, seed=1).fit(key, dt)
    assert k.info[KEY_CODE["chat>chat:other"]]["fit_on"] == "own"
    assert abs(k.info[KEY_CODE["chat>chat:other"]]["dt_median_h"] * 3600 - 600) < 60
    # Keys without edges fall back to the pooled fit.
    assert k.info[KEY_CODE["memory>chat"]]["fit_on"] in ("channel", "all")
    x = np.logspace(0, 7, 20000)
    dens = k.density(EdgeTimes(np.full(len(x), KEY_CODE["chat>chat:other"]), x))
    assert abs(np.trapezoid(dens, x) - 1) < 0.05
    d1, d2 = k.density(EdgeTimes(np.array([0, 0]), np.array([600.0, 60000.0])))
    assert d1 > 10 * d2
    s = k.sample(KEY_CODE["chat>chat:other"], 5000, rng)
    assert abs(np.median(s) - 600) < 80


def test_hawkes_kernel_integrates_and_hook_falls_back():
    w = np.array([0.5, 0.3, 0.2])
    L = 10800.0
    x = np.linspace(1e-3, L, 400000)
    assert abs(np.trapezoid(hawkes_g(x, w, L), x) - 1) < 1e-3
    assert hawkes_g(np.array([L + 1.0]), w, L)[0] == 0
    fb = EmpiricalKernel(seed=1).fit(np.full(500, 0), np.exp(np.random.default_rng(2).normal(7, 1, 500)))
    table = pl.DataFrame({"window_kind": ["goal", "goal"], "window_id": ["g1", "g1"], "group": ["general", "general"],
                          "date_start": [date(2026, 7, 1)] * 2, "date_end": [date(2026, 7, 31)] * 2,
                          "source_class": ["other", "human"], "w_1m": [0.5, 0.2], "w_10m": [0.3, 0.3], "w_1h": [0.2, 0.5],
                          "L_s": [L, L], "expected_children": [400.0, 20.0], "identified": [True, False]})
    hk = HawkesKernel(table, fb, {"roomA": "general"})
    e = EdgeTimes(key=np.array([KEY_CODE["chat>chat:other"]] * 4 + [KEY_CODE["memory>chat"]]),
                  dt=np.array([120.0, 120.0, 120.0, 20000.0, 120.0]),
                  same_block=np.array([True, False, True, True, True]), tau=np.array([120.0, 120.0, 120.0, 20000.0, 120.0]),
                  source_class=np.array([1, 1, 2, 1, -1], dtype=np.int8),
                  room=np.array(["roomA", "roomA", "roomA", "roomA", "roomA"], dtype=object),
                  child_date=np.array(["2026-07-10"] * 5, dtype="datetime64[D]"))
    d = hk.density(e)
    assert d[0] == pytest.approx(hawkes_g(np.array([120.0]), np.array([0.5, 0.3, 0.2]), L)[0])
    fbd = fb.density(e)
    assert d[1] == fbd[1] and d[2] == fbd[2] and d[3] == fbd[3] and d[4] == fbd[4]
    assert hk.used["hawkes"] == 1 and hk.used["kde_cross_day"] == 1 and hk.used["kde_not_chat"] == 1
    assert hk.used["kde_not_identified"] == 1 and hk.used["kde_beyond_L"] == 1


# --- candidates and exposure ---------------------------------------------------------------------------------------

def test_exposure_rules():
    rows = [
        dict(unit=0, t=100.0, src=CHAT, actor=0, vis=[0, 1]),            # 0 root by agent 0, seen by 0 and 1
        dict(unit=0, t=200.0, src=CHAT, actor=2, vis=[2]),               # 1 agent 2 did not see 0
        dict(unit=0, t=300.0, src=MEMORY, actor=1, mem_end=int(1000e6)),  # 2 agent 1 writes memory
        dict(unit=0, t=400.0, src=CHAT, actor=1, vis=[0, 1, 2]),         # 3 agent 1 speaks
        dict(unit=0, t=500.0, src=SEARCH, actor=0, vday=0, s0=0, s1=0),  # 4 search answer of agent 0
        dict(unit=0, t=2000.0, src=CHAT, actor=1, vis=[0, 1, 2]),        # 5 memory lost by then
        dict(unit=0, t=5 * DAY, src=CHAT, actor=0, vis=[0, 1, 2]),       # 6 beyond L_B of everything
    ]
    occ = make_occ(rows)
    c = all_candidates(occ)
    cand = {int(i): sorted(int(p) for p in c.parent[c.child == i]) for i in np.unique(c.child)}
    assert 1 not in cand  # agent 2 saw nothing
    assert cand[2] == [0]  # memory child: chat it saw
    assert cand[3] == [0, 2]  # chat 0 (seen) and own memory 2
    assert cand[4] == [0, 1, 3]  # search answer: chat of the covered day, any room
    assert 2 not in cand[5]  # memory no longer present
    assert 6 not in cand
    keys = dict(zip(zip(c.child.tolist(), c.parent.tolist()), c.key.tolist()))
    assert keys[(3, 2)] == KEY_CODE["memory>chat"] and keys[(2, 0)] == KEY_CODE["chat>memory:other"]
    assert keys[(4, 0)] == KEY_CODE["history>search"]


def test_env_precede_and_any():
    rows = [dict(unit=0, t=100.0, actor=0), dict(unit=0, t=500.0, actor=1)]
    env_late = {(0, 1): (np.array([300e6], dtype=np.int64), np.array([300.0]), np.array([300.0 / DAY]))}
    env_early = {(0, 1): (np.array([50e6], dtype=np.int64), np.array([50.0]), np.array([50.0 / DAY]))}
    for env, rule, has in ((env_late, "precede", False), (env_late, "any", True), (env_early, "precede", True)):
        c = all_candidates(make_occ(rows, env), env_rule=rule)
        assert (ENV in c.parent.tolist()) == has, (rule, has)
    c = all_candidates(make_occ(rows, env_early))
    assert c.dt[c.parent == ENV][0] == pytest.approx(450.0) and c.key[c.parent == ENV][0] == KEY_CODE["env>chat"]


def test_nonroot_variants_and_shared_counts():
    rows = [dict(unit=0, t=1.0, actor=0, qv=[(7, 56)], grams=[1, 2]),
            dict(unit=0, t=2.0, actor=1, qv=[(7, 57)], grams=[1, 3, 4]),
            dict(unit=0, t=3.0, actor=2, qv=[(7, 57), (8, 9)], grams=[3, 4]),
            dict(unit=0, t=4.0, actor=3, qv=[(7, 56)], grams=[2])]
    occ = make_occ(rows)
    var = nonroot_variants(occ, 0, 4)
    assert len(var[0]) == 0 and len(var[3]) == 0  # the root's values are not variants
    assert len(var[1]) == 3  # value 57 under key 7, grams 3 and 4
    assert len(var[2]) == 3  # key 8 is not in the root, so (8, 9) is no variant
    S = shared_counts(var)
    assert S[2, 1] == 3 and S[3, 1] == 0


def test_posterior_time_and_content():
    rows = [dict(unit=0, t=0.0, actor=0, grams=[]), dict(unit=0, t=100.0, actor=1, grams=[11, 12]),
            dict(unit=0, t=150.0, actor=2, grams=[]), dict(unit=0, t=200.0, actor=3, grams=[11, 12])]
    occ = make_occ(rows)
    c = all_candidates(occ)
    K = np.ones(c.n)
    post = posterior(c, K, 1.0)
    rows3 = c.child == 3
    p = dict(zip(c.parent[rows3].tolist(), post[rows3].tolist()))
    assert p[1] > p[0] and p[1] > p[2]
    assert sum(p.values()) == pytest.approx(1.0)
    post0 = posterior(c, K, 0.0)
    assert np.allclose(post0[rows3], 1 / 3)
    # Time only: a closer parent wins under a decreasing kernel.
    k = EmpiricalKernel(seed=0).fit(np.zeros(500, int), np.exp(np.random.default_rng(0).normal(3, 0.7, 500)))
    pt = posterior(c, k.density(c.edge_times(occ)), 1.0, use_content=False)
    pp = dict(zip(c.parent[rows3].tolist(), pt[rows3].tolist()))
    assert pp[2] > pp[0]


def test_forest_env_restarts_generation_and_sampling():
    rows = [dict(unit=0, t=float(i * 100), actor=i % 3) for i in range(5)]
    env = {(0, 1): (np.array([350e6], dtype=np.int64), np.array([350.0]), np.array([350.0 / DAY]))}
    occ = make_occ(rows, env, n_units=1)
    c = all_candidates(occ, env_rule="any")
    K = np.ones(c.n)
    K[c.parent == ENV] = 1e6  # force env for the child that has it
    post = posterior(c, K, 0.0)
    ch = map_choice(c, post, occ.n)
    par, gen, root = forest(c, ch)
    assert par[4] == ENV and gen[4] == 0 and root[4] == 4
    assert gen[0] == 0 and gen[1] == 1
    rng = np.random.default_rng(3)
    counts = np.zeros(c.n)
    for _ in range(3000):
        s = sample_choice(c, post, occ.n, rng)
        counts[s[s >= 0]] += 1
    kids, starts = c.offsets()
    for a, b in zip(starts[:-1], starts[1:]):
        assert np.allclose(counts[a:b] / counts[a:b].sum(), post[a:b], atol=0.04)


def test_single_candidate_edges():
    rows = [dict(unit=0, t=0.0, actor=0), dict(unit=0, t=10.0, actor=1), dict(unit=0, t=20.0, actor=2)]
    c = all_candidates(make_occ(rows))
    one = single_candidate_edges(c)
    assert c.child[one].tolist() == [1]


# --- known-tree recovery (SPEC 3.5) ----------------------------------------------------------------------------------

def test_known_tree_recovery():
    """SPEC 3.5: a known tree with well-separated times and inherited variants is recovered exactly."""
    rows, true_par = [], []
    for u in range(30):
        base = u * 10 * DAY
        # root 0 -> 1 -> 2 (agent 3 is in another room then), root 0 -> 3; agent 4 sees no chat and
        # observes the unit itself before it posts.
        spec = [(0.0, 0, -1, [], [0, 1, 2, 3]), (600.0, 1, 0, [u * 10 + 1], [0, 1, 2]),
                (1300.0, 2, 1, [u * 10 + 1, u * 10 + 2], [0, 1, 2]), (4000.0, 3, 0, [u * 10 + 3], [0, 1, 2, 3]),
                (9000.0, 4, ENV, [], [0, 1, 2, 3])]
        for t, a, p, g, vis in spec:
            rows.append(dict(unit=u, t=base + t, actor=a, grams=g, vis=vis))
            true_par.append(p)
    env = {(u, 4): (np.array([(u * 10 * DAY + 8000.0) * 1e6], dtype=np.int64),
                    np.array([u * 10 * DAY + 8000.0]), np.array([(u * 10 * DAY + 8000.0) / DAY])) for u in range(30)}
    occ = make_occ(rows, env, n_units=30)
    c = all_candidates(occ)
    kern = EmpiricalKernel(seed=0).fit(np.r_[np.zeros(400, int), np.full(100, KEY_CODE["env>chat"])],
                                       np.r_[np.exp(np.random.default_rng(0).normal(np.log(700), 0.4, 400)),
                                             np.full(100, 1000.0)])
    post = posterior(c, kern.density(c.edge_times(occ)), 2.0)
    p_hat, g_hat, _ = forest(c, map_choice(c, post, occ.n))
    want = []
    for u in range(30):
        lo = u * 5
        want += [NONE, lo, lo + 1, lo, ENV]
    assert p_hat.tolist() == want
    assert g_hat.tolist() == [0, 1, 2, 1, 0] * 30


def test_synthetic_replicate_runs():
    from avsd.lineage import trees_synth as sy

    rng = np.random.default_rng(5)
    kern = EmpiricalKernel(seed=5).fit(np.repeat(np.arange(len(KEYS)), 300),
                                       np.exp(rng.normal(np.log(900), 0.6, 300 * len(KEYS))))
    par = {"R": [1.0, 0.8, 0.5], "p_chat": np.array([0.7, 0.05, 0.2, 0.05]), "p_env": 0.1, "p_spur": 0.05,
           "c": 0.6, "gamma": 2.0, "root_t": rng.uniform(0, 300 * DAY, 500), "root_pos": np.zeros(500),
           "day_len": DAY, "pops": {}, "kernel": kern, "max_size": 15}
    out = sy.one_replicate(par, 300, seed=11, perms=49)
    assert out["parent_accuracy"] > 0.5 and out["env_recall"] > 0.5
    assert 0 <= out["generation_accuracy"] <= 1 and out["generation_mae"] < 1.5
    assert "p_true_combined" in out and "p_inferred_combined" in out


# --- H1 tools ----------------------------------------------------------------------------------------------------------

def _ad_slow(x, lab):
    z = np.sort(x)
    N, k = len(x), lab.max() + 1
    tot = 0.0
    for i in range(k):
        xi = x[lab == i]
        ni = len(xi)
        s = 0.0
        for j in range(1, N):
            M = (xi <= z[j - 1]).sum()
            s += (N * M - j * ni) ** 2 / (j * (N - j))
        tot += s / ni
    return tot / N


def test_ad_stat_formula_and_power():
    rng = np.random.default_rng(2)
    x = rng.normal(size=60)
    lab = rng.integers(0, 3, 60)
    assert ts.ad_stat(x, lab)[0] == pytest.approx(_ad_slow(x, lab))
    perms = np.stack([rng.permutation(lab) for _ in range(5)])
    assert np.allclose(ts.ad_stat(x, lab, perms), [_ad_slow(x, p) for p in perms])
    # Same distribution: p is not small on average; shifted: p is small.
    y = np.concatenate([rng.normal(0, 1, 200), rng.normal(1, 1, 200)])
    ly = np.repeat([0, 1], 200)
    obs = ts.ad_stat(y, ly)[0]
    null = ts.ad_perm_null(y, ly, 199, rng)
    assert (null >= obs).mean() < 0.01


def test_h1_tests_on_iid_chains_and_tk_linear():
    rng = np.random.default_rng(4)
    n_tree, depth = 400, 4
    rows = []
    for u in range(n_tree):
        t = rng.uniform(0, 50 * DAY)
        for g in range(depth):
            rows.append(dict(unit=u, t=t, actor=g))
            t += rng.exponential(0.2 * DAY)
    occ = make_occ(rows, n_units=n_tree)
    c = all_candidates(occ, L=1e9)
    # Force the chain parent (the previous occurrence).
    chosen = np.full(occ.n, -1)
    kids, starts = c.offsets()
    for k, (a, b) in enumerate(zip(starts[:-1], starts[1:])):
        chosen[kids[k]] = b - 1
    p, g, r = forest(c, chosen)
    f = ts.Forest(chosen, p, g, r)
    e = ts.edges(c, f)
    ok = np.ones(len(e.child), bool)
    res = ts.h1_ad_tests(e, ok, 30, 199, rng)
    chat = next(x for x in res if x["channel"] == "chat_to_chat_other")
    assert chat["n_generations"] == 3 and chat["p_perm"] > 0.001
    tk = ts.tk_analysis(occ.t, occ.pos, g, r, 1e9, 0.0, 30, 200, rng)
    lin = next(x for x in tk["fits"] if x["quantity"] == "mean" and x["model"] == "linear")
    assert lin["slope"] == pytest.approx(0.2 * DAY / 3600, rel=0.15)
    quad = next(x for x in tk["fits"] if x["quantity"] == "mean" and x["model"] == "quadratic")
    assert quad["k2_lo"] < 0 < quad["k2_hi"]


def test_cluster_boot_is_deterministic_and_covers():
    rng = np.random.default_rng(9)
    clusters = np.repeat(np.arange(300), 3)
    v = rng.normal(5, 1, len(clusters))
    b1 = ts.ClusterBoot(clusters, 200, np.random.default_rng(1))
    b2 = ts.ClusterBoot(clusters, 200, np.random.default_rng(1))
    r1 = ts.boot_ratio(b1, v, np.ones(len(v)), b1.inv)
    r2 = ts.boot_ratio(b2, v, np.ones(len(v)), b2.inv)
    assert np.allclose(r1, r2)
    lo, hi = ts.ci(r1)
    assert lo < v.mean() < hi and hi - lo < 0.4


def test_quantity_changes_and_inheritance():
    rows = [dict(unit=0, t=1.0, actor=0, qv=[(7, 56)]), dict(unit=0, t=2.0, actor=1, qv=[(7, 57)]),
            dict(unit=0, t=3.0, actor=2, qv=[(7, 57)]), dict(unit=0, t=4.0, actor=3, qv=[(7, 56)])]
    occ = make_occ(rows)
    e = ts.Edges(child=np.array([1, 2, 3]), parent=np.array([0, 1, 1]), row=np.zeros(3, int),
                 key=np.zeros(3, int), ch=np.zeros(3, int), dt=np.ones(3), gen=np.array([1, 2, 2]),
                 root=np.zeros(3, int))
    carried, changed, changes = ts.quantity_changes(e, occ.qv_key, occ.qv_val, np.ones(3, bool))
    assert carried.tolist() == [1, 1, 1] and changed.tolist() == [1, 0, 1]
    inh = ts.inheritance(e, occ.qv_key, occ.qv_val, changes[:1])
    assert inh["n_grandchild_contexts"] == 2 and inh["inherited_share"] == 0.5 and inh["reverted_share"] == 0.5


def test_attractor_measures():
    win = Ragged.from_lists([[1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 9, 9], [6, 7, 8, 10, 11]])
    out = ts.attractor(win, np.zeros(4, int), np.arange(4))
    assert out["sim"][0] == 1.0 and out["sim"][3] == 0.0
    assert out["ttr"][2] == pytest.approx(4 / 5)


# --- labels ---------------------------------------------------------------------------------------------------------------

def test_name_matcher_and_quotes():
    agents = pl.DataFrame({"agent_id": ["a1", "a2", "a3"], "name": ["Claude Opus 4.5", "GPT-5.1", "Gemini 2.5 Pro"]})
    nm = NameMatcher(agents)
    refs = nm.refs("@Opus 4.5 good point. As GPT-5.1 said, the doc is live.", set(), "a3")
    targets = {t: k for t, k in refs}
    assert "a1" in targets and "at" in targets["a1"]
    assert "a2" in targets and "attr" in targets["a2"]
    # A bare family word resolves to the only recent speaker of that family.
    refs = nm.refs("Thanks Claude!", {"a1", "a2"}, "a3")
    assert refs and refs[0][0] == "a1"
    q = quote_spans('He wrote "the fundraiser closes at noon on Friday" and left.')
    assert q == ["the fundraiser closes at noon on friday"]


def test_score_cases_ties_and_logp():
    from avsd.lineage.trees import score_cases

    cases = {"a": np.array([0, 3]), "b": np.array([3, 5]), "row": np.array([1, 4]), "cluster": np.array([1, 2]),
             "kind": np.array(["name", "name"]), "tier": np.array([1, 1]), "child": np.array([10, 11])}
    lw = np.array([0.0, 0.0, -1.0, 2.0, 2.0])
    sc = score_cases(cases, np.array([True, True]), lw)
    assert sc["acc"].tolist() == [0.5, 0.5]
    assert sc["logp"][1] == pytest.approx(np.log(0.5))


def test_report_registers_b2():
    from avsd.report.progress import _tab_of
    from avsd.report.registry import MODULE_TABS, QA_ORDER

    tokens = [t.token for t in MODULE_TABS]
    assert "moduleB2" in tokens and tokens.index("moduleB2") == tokens.index("moduleB1") + 1
    b2 = next(t for t in MODULE_TABS if t.token == "moduleB2")
    assert any(i.path == "figures/F3_interval_ecdf.png" for i in b2.items)
    assert all(i.path.startswith(("tables/trees_", "figures/F3_", "figures/F4_")) for i in b2.items)
    assert "lineage_trees" in QA_ORDER
    assert _tab_of("Module B2 (P1)", "B2 transmission trees") == "moduleB2"
    assert _tab_of("Module B1, C (P0)", "B1 memory chains") == "moduleB1"


def test_determined_paths():
    rows = [dict(unit=0, t=0.0, actor=0, vis=[0, 1, 2]),   # root, seen by everyone
            dict(unit=0, t=100.0, actor=1, vis=[1, 2]),    # sees only the root: determined
            dict(unit=0, t=200.0, actor=2, vis=[1, 2]),    # sees the root and 1: not determined
            dict(unit=0, t=300.0, actor=0, vis=[0])]       # agent 0 saw neither 1 nor 2: determined
    occ = make_occ(rows)
    c = all_candidates(occ)
    post = posterior(c, np.ones(c.n), 0.0)
    ch = map_choice(c, post, occ.n)
    p, g, r = forest(c, ch)
    det = ts.determined(c, ts.Forest(ch, p, g, r))
    assert det.tolist() == [True, True, False, True]


def test_agent_view_uses_acquisitions():
    # One unit. 0 agent 0 (root) -> 1 agent 0 re-mention -> 2 agent 1 (carrier 1, so generation 1) -> 3 agent 1
    # re-mention whose MAP parent is agent 0 (still agent 1's generation) -> 4 agent 2 (carrier 3: generation 2);
    # 5 env child of agent 3 (generation 0, own root) -> 6 agent 4 (generation 1 under 5); 7 human, 8 human again.
    parent = np.array([-1, 0, 1, 1, 3, -2, 5, -1, 7])
    actor = np.array([0, 0, 1, 1, 2, 3, 4, -1, -1])
    unit = np.zeros(9, dtype=np.int64)
    gen = np.array([0, 1, 2, 2, 3, 0, 1, 0, 1])
    root = np.array([0, 0, 0, 0, 0, 5, 5, 7, 7])
    f = ts.Forest(np.zeros(9, int), parent, gen, root)
    av = ts.agent_view(f, actor, unit)
    assert av.acq.tolist() == [True, False, True, False, True, True, True, True, False]
    assert av.gen.tolist() == [0, 0, 1, 1, 2, 0, 1, 0, 0]
    assert av.owner.tolist() == [0, 0, 2, 2, 4, 5, 6, 7, 7]
    assert av.root.tolist() == [0, 0, 0, 0, 0, 5, 5, 7, 7]
    child = np.flatnonzero(parent >= 0)
    e = ts.Edges(child, parent[child], np.zeros(len(child), int), np.zeros(len(child), int),
                 np.zeros(len(child), int), np.ones(len(child)), gen[child], root[child], np.zeros(len(child), int))
    ea, m = ts.agent_edges(e, av)
    assert ea.child.tolist() == [2, 4, 6] and ea.gen.tolist() == [1, 2, 1] and ea.root.tolist() == [0, 0, 5]
    rs = ts.restatement_summary(av, f, actor)
    assert rs["n_remention"] == 3 and rs["n_acquisitions"] == 6
    assert rs["remention_parent_own"] == 2 and rs["remention_parent_other_actor"] == 1
    assert rs["max_generation_occurrence_level"] == 3 and rs["max_generation_agent_level"] == 2
    assert rs["depth_max"] == 1


def test_hand_label_cases_map_sheet_rows(tmp_path):
    import csv

    from avsd.lineage.trees import hand_label_cases

    rows = [dict(unit=0, t=0.0, actor=0), dict(unit=0, t=60.0, actor=1), dict(unit=0, t=120.0, actor=2)]
    occ = make_occ(rows)
    c = all_candidates(occ)
    inp = {"occ_df": pl.DataFrame({"occ_uid": ["u0", "u1", "u2"]})}
    path = tmp_path / "parents_review.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["child_uid", "cand_1_uid", "cand_2_uid", "human_parent"])
        w.writerow(["u2", "u1", "u0", "2"])
        w.writerow(["u1", "u0", "", ""])
        w.writerow(["u1", "u0", "", "none"])
        w.writerow(["u1", "u9", "", "1"])
    h = hand_label_cases(inp, c, path)
    assert len(h["child"]) == 1 and h["n_labelled"] == 2 and h["n_unmatched"] == 1
    assert int(c.child[h["row"][0]]) == 2 and int(c.parent[h["row"][0]]) == 0


def test_edge_times_carry_room_ids_for_the_hook():
    rows = [dict(unit=0, t=0.0, actor=0), dict(unit=0, t=60.0, actor=1)]
    occ = make_occ(rows)
    occ.room_ids = np.array(["roomA"], dtype=object)
    c = all_candidates(occ)
    et = c.edge_times(occ)
    assert et.room.tolist() == ["roomA"]
    fb = EmpiricalKernel(seed=1).fit(np.zeros(200, int), np.exp(np.random.default_rng(1).normal(5, 1, 200)))
    table = pl.DataFrame({"window_kind": ["goal"], "window_id": ["g1"], "group": ["general"],
                          "date_start": [date(1970, 1, 1)], "date_end": [date(1970, 1, 31)], "source_class": ["other"],
                          "w_1m": [1.0], "w_10m": [0.0], "w_1h": [0.0], "L_s": [10800.0],
                          "expected_children": [100.0], "identified": [True]})
    hk = HawkesKernel(table, fb, {"roomA": "general"})
    d = hk.density(et)
    assert hk.used["hawkes"] == 1
    assert d[0] == pytest.approx(hawkes_g(np.array([60.0]), np.array([1.0, 0.0, 0.0]), 10800.0)[0])


def test_site_domain_drops_subdomains():
    from avsd.lineage.trees_report import site_domain

    assert site_domain("someone.substack.com") == "substack.com"
    assert site_domain("owner_ab12.github.io") == "github.io"
    assert site_domain("a.b.workers.dev") == "workers.dev"
    assert site_domain("news.bbc.co.uk") == "bbc.co.uk"
    assert site_domain("example.org") == "example.org"
    assert site_domain("10.0.0.1") == "ip address"
    assert site_domain("hashed") == "hashed" and site_domain(None) is None


def test_public_domains_hide_rare_and_name_like_sites():
    from avsd.lineage.trees_report import public_domains

    dom = pl.Series("domain", ["a.substack.com", "b.substack.com", "c.substack.com", "solo.dev", None,
                               "x.alicewalker.net", "y.alicewalker.net", "z.alicewalker.net"])
    out = public_domains(dom, {"walker"}).to_list()
    assert out[:3] == ["substack.com"] * 3
    assert out[3] == "other" and out[4] is None
    assert out[5:] == ["other"] * 3


def test_hawkes_window_lookup_uses_room_and_date_together():
    """Goal windows of different rooms overlap in dates (best and rest in 2026). The lookup must take the
    window of the child's room that contains the child's date; G40 has no identified row."""
    fb = EmpiricalKernel(seed=1).fit(np.full(500, 0), np.exp(np.random.default_rng(2).normal(7, 1, 500)))
    wins = [("g35", "rest", date(2026, 3, 16), date(2026, 3, 20), [0.9, 0.1, 0.0], True),
            ("g35-39", "best", date(2026, 3, 16), date(2026, 5, 1), [0.1, 0.8, 0.1], True),
            ("g36-37", "rest", date(2026, 3, 23), date(2026, 4, 1), [0.2, 0.2, 0.6], True),
            ("g40", "universe-coordination", date(2026, 5, 4), date(2026, 5, 8), [1.0, 0.0, 0.0], False)]
    table = pl.DataFrame({"window_kind": ["goal"] * 4, "window_id": [x[0] for x in wins],
                          "group": [x[1] for x in wins], "date_start": [x[2] for x in wins],
                          "date_end": [x[3] for x in wins], "source_class": ["other"] * 4,
                          "w_1m": [x[4][0] for x in wins], "w_10m": [x[4][1] for x in wins],
                          "w_1h": [x[4][2] for x in wins], "L_s": [10800.0] * 4,
                          "expected_children": [100.0, 100.0, 100.0, 10.0], "identified": [x[5] for x in wins]})
    hk = HawkesKernel(table, fb, {"rB": "best", "rR": "rest", "rU": "universe-coordination", "rS": "sol"})
    rooms = np.array(["rB", "rR", "rB", "rR", "rU", "rS"], dtype=object)
    days = np.array(["2026-03-25", "2026-03-25", "2026-03-17", "2026-03-21", "2026-05-05", "2026-03-25"],
                    dtype="datetime64[D]")
    n = len(rooms)
    e = EdgeTimes(key=np.full(n, KEY_CODE["chat>chat:other"]), dt=np.full(n, 300.0), same_block=np.ones(n, bool),
                  tau=np.full(n, 300.0), source_class=np.ones(n, dtype=np.int8), room=rooms, child_date=days)
    d = hk.density(e)
    g = {wid: hawkes_g(np.array([300.0]), np.array(w), 10800.0)[0] for wid, _, _, _, w, _ in wins}
    assert d[0] == pytest.approx(g["g35-39"])  # best room inside both best and rest windows
    assert d[1] == pytest.approx(g["g36-37"])  # rest room on the same date
    assert d[2] == pytest.approx(g["g35-39"])
    fbd = fb.density(e)
    assert d[3] == fbd[3]  # rest room between its windows: no window
    assert d[4] == fbd[4]  # G40: not identified
    assert d[5] == fbd[5]  # a room without goal windows
    br = [HawkesKernel.BRANCHES[b] for b in hk.last["branch"]]
    assert br == ["hawkes", "hawkes", "hawkes", "kde_no_window", "kde_not_identified", "kde_no_window"]
    tab = {(r["window_id"], r["group"]): r for r in hk.window_table(hk.last, scope="candidate_edges")}
    assert tab[("g35-39", "best")]["hawkes"] == 2 and tab[("g36-37", "rest")]["hawkes"] == 1
    assert tab[("g40", "universe-coordination")]["kde_not_identified"] == 1
    assert tab[("none", "rest")]["kde_no_window"] == 1 and tab[("none", "sol")]["kde_no_window"] == 1
    assert tab[("all", "all")]["n_chat_edges"] == 6 and tab[("all", "all")]["hawkes"] == 3


def test_composite_labels_and_selection(tmp_path):
    import csv

    from avsd.lineage.trees import composite_label_cases, select_by_labels, sheet_label_cases

    # Three children (u2, u3, u4) of one unit; candidates are the earlier occurrences.
    rows = [dict(unit=0, t=0.0, actor=0), dict(unit=0, t=60.0, actor=1), dict(unit=0, t=120.0, actor=2),
            dict(unit=0, t=180.0, actor=3), dict(unit=0, t=10000.0, actor=4)]
    occ = make_occ(rows)
    c = all_candidates(occ)
    inp = {"occ_df": pl.DataFrame({"occ_uid": ["u0", "u1", "u2", "u3", "u4"]})}

    def sheet(name, labels):
        path = tmp_path / name
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["child_uid", "cand_1_uid", "cand_2_uid", "human_parent"])
            for child, lab in labels:
                w.writerow([child, "u0", "u1", lab])
        return path

    owner = sheet_label_cases(inp, c, sheet("owner.csv", [("u2", "2"), ("u3", "none")]), "hand")
    claude = sheet_label_cases(inp, c, sheet("claude.csv", [("u2", "1"), ("u3", "1"), ("u4", "2")]), "claude")
    comp = composite_label_cases(owner, claude)
    # u2 from the owner, u3 skipped (the owner said none), u4 from Claude.
    assert sorted(int(x) for x in comp["child"]) == [2, 4] and set(comp["kind"]) == {"composite"}
    rows_comp = {int(ch): int(c.parent[r]) for ch, r in zip(comp["child"], comp["row"])}
    assert rows_comp == {2: 1, 4: 1}
    cases = {k: np.asarray(comp[k]) for k in ("child", "row", "a", "b", "kind", "tier", "cluster")}
    # Two time terms: one prefers the latest candidate (right for u2 and u4), one the earliest.
    t_par = occ.t[np.maximum(c.parent, 0)]
    good = np.exp(t_par / 1000.0)
    bad = np.exp(-t_par / 1000.0)
    best, sel_rows = select_by_labels(c, cases, {"composite": np.ones(len(cases["child"]), bool)},
                                      [("bad", bad), ("good", good)])
    assert best["composite"][0] == "good"
    assert any(r["best_for_set"] for r in sel_rows) and {r["time_term"] for r in sel_rows} == {"bad", "good"}


def test_claude_sheet_maps_blind_numbers(tmp_path):
    import csv

    from avsd.lineage import prelabel_parents as pp

    lab = tmp_path / "labels"
    (lab / "claude_blind").mkdir(parents=True)
    cols = ["review_priority", "child_uid", "cand_1_uid", "cand_2_uid", "cand_3_uid", "human_parent", "notes"]
    with open(lab / pp.REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerow(["1", "a", "p1", "env", "p3", "2", ""])
        w.writerow(["2", "b", "p1", "p2", "", "", ""])
    (lab / pp.BLIND_MAP).write_text(json.dumps({"a": {"1": "3", "2": "2", "3": "1"}, "b": {"1": "2", "2": "1"}}))
    with open(lab / pp.CLAUDE_BLIND, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "child_uid", "claude_parent", "confidence", "reason"])
        w.writerow(["1", "a", "2", "high", ""])
        w.writerow(["2", "b", "1", "low", ""])
    res = pp.claude_sheet({"paths": {"labels": str(lab)}}, log=lambda m: None)
    with open(lab / pp.CLAUDE_FILE, encoding="utf-8-sig") as fh:
        got = {r["child_uid"]: r["human_parent"] for r in csv.DictReader(fh)}
    assert got == {"a": "2", "b": "2"}
    assert res["owner_both"] == 1 and res["owner_agree"] == 1


def test_sheet_labels_resolve_shared_uids_through_requests(tmp_path):
    import csv

    from avsd.lineage.trees import sheet_label_cases

    # Two units carried by the same two messages: uids repeat, so the item's unit comes from the request file.
    rows = [dict(unit=0, t=0.0, actor=0), dict(unit=0, t=60.0, actor=1),
            dict(unit=1, t=0.0, actor=0), dict(unit=1, t=60.0, actor=1)]
    occ = make_occ(rows)
    c = all_candidates(occ)
    inp = {"occ_df": pl.DataFrame({"occ_uid": ["m0", "m1", "m0", "m1"], "uidx": [0, 0, 1, 1]})}
    req = tmp_path / "requests.jsonl"
    req.write_text(json.dumps({"item": 1, "gi": 3, "child_uid": "m1"}) + "\n")
    sheet = tmp_path / "sheet.csv"
    with open(sheet, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "child_uid", "cand_1_uid", "human_parent"])
        w.writerow(["1", "m1", "m0", "1"])
    h = sheet_label_cases(inp, c, sheet, "hand", req)
    assert h["child"].tolist() == [3] and int(c.parent[h["row"][0]]) == 2
