"""D4 behaviour rule: continuation rate against a random-choice baseline (SPEC 8.5).

For every pair of consecutive sessions (p, n) of one agent, the continuation indicator is 1 when
p is among n's parents in the dependency graph. The continuation rate is its mean over pairs
(`all pairs`), or over pairs whose next session has at least one parent (`with parents`).

Baseline. Artifacts are counted at the container level (a repository, a document, a project
directory, a URL), as the graph matches them. At n's start, the pool W_n holds the containers
written before in the same period (the same village goal, or the same run day) that the agent can
reach: every shared container (documents, repositories, URLs) and the agent's own local ones.
m_n of them were last written by p. If n drew its k_n parented containers at random from W_n,
p would be a parent with probability 1 - C(W_n - m_n, k_n) / C(W_n, k_n). The baseline rate is the
mean of these probabilities over the same pairs. A second baseline (`own work`) restricts the pool
to containers whose last writer in the period is one of the agent's own sessions and the draws to
n's containers with an own parent; it asks whether the agent prefers its latest session over its
older work.

CIs: 95% percentile intervals from a bootstrap over agents (all pairs of a resampled agent kept
together). Strata: all pairs, and the two computer-use regimes (before and after the switch to
continuous computer use, `regime_cu`).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import polars as pl

WINDOWS = ("goal", "day")


def _p_hit(W: int, m: int, k: int) -> float:
    """P(at least one of k draws without replacement from W items hits one of m marked items)."""
    if k <= 0 or m <= 0:
        return 0.0
    W = max(W, m, k)
    if W - m < k:
        return 1.0
    return 1.0 - math.exp(math.lgamma(W - m + 1) - math.lgamma(W - m - k + 1)
                          - math.lgamma(W + 1) + math.lgamma(W - k + 1))


def continuation_pairs(sessions: pl.DataFrame, writes: pl.DataFrame, lookups: pl.DataFrame) -> pl.DataFrame:
    """One row per consecutive session pair with the indicator and both baseline probabilities.

    `sessions`: s (start order), agent_id, start_t (seconds), goal_id, run_day, regime_cu.
    `writes`: s, c (container int), t (seconds), local (bool), one row per write event.
    `lookups`: child, c, parent: the successful container lookups of the edge build.
    """
    ses = sessions.sort("s")
    agent = ses["agent_id"].to_list()
    goal = ses["goal_id"].to_list()
    day = ses["run_day"].to_list()
    start = ses["start_t"].to_numpy()
    s_ids = ses["s"].to_numpy()
    idx = {int(s): i for i, s in enumerate(s_ids)}
    # previous session of the same agent
    prev: dict[int, int] = {}
    last: dict[str, int] = {}
    for i in np.argsort(start, kind="stable"):
        a = agent[i]
        if a in last:
            prev[int(s_ids[i])] = last[a]
        last[a] = int(s_ids[i])
    # lookups per child
    par_c: dict[int, set[int]] = defaultdict(set)
    own_c: dict[int, set[int]] = defaultdict(set)
    parents: dict[int, set[int]] = defaultdict(set)
    for ch, c, pa in lookups.select("child", "c", "parent").iter_rows():
        par_c[ch].add(c)
        parents[ch].add(pa)
        if agent[idx[pa]] == agent[idx[ch]]:
            own_c[ch].add(c)
    # sweep: writes and session starts in time order (starts first at equal times)
    ev: list[tuple[float, int, int, int, bool]] = []
    for s, c, t, loc in writes.select("s", "c", "t", "local").iter_rows():
        ev.append((t, 1, s, c, loc))
    for n in prev:
        ev.append((float(start[idx[n]]), 0, n, -1, False))
    ev.sort(key=lambda e: (e[0], e[1]))
    last_w: dict[int, int] = {}
    written_by: dict[int, set[int]] = defaultdict(set)
    shared = {w: defaultdict(set) for w in WINDOWS}           # period -> shared containers
    local = {w: defaultdict(set) for w in WINDOWS}            # (period, agent) -> local containers
    owner = {w: defaultdict(dict) for w in WINDOWS}           # period -> container -> agent
    own_n = {w: defaultdict(int) for w in WINDOWS}            # (period, agent) -> own containers
    rows = []
    for t, kind, s, c, loc in ev:
        i = idx[s]
        periods = {"goal": goal[i], "day": day[i]}
        if kind == 1:
            a = agent[i]
            last_w[c] = s
            written_by[s].add(c)
            for w, per in periods.items():
                if per is None:
                    continue
                if loc:
                    local[w][(per, a)].add(c)
                else:
                    shared[w][per].add(c)
                prev_owner = owner[w][per].get(c)
                if prev_owner != a:
                    if prev_owner is not None:
                        own_n[w][(per, prev_owner)] -= 1
                    own_n[w][(per, a)] += 1
                    owner[w][per][c] = a
            continue
        n, p = s, prev[s]
        a = agent[i]
        rec = {"child": n, "prev": p, "agent_id": a, "cont": int(p in parents.get(n, ())),
               "k": len(par_c.get(n, ())), "k_own": len(own_c.get(n, ()))}
        for w, per in periods.items():
            if per is None:
                rec[f"W_{w}"] = rec[f"m_{w}"] = rec[f"Wown_{w}"] = 0
                rec[f"e_{w}"] = rec[f"eown_{w}"] = math.nan
                continue
            pool_sh = shared[w][per]
            pool_lo = local[w][(per, a)]
            W = len(pool_sh) + len(pool_lo)
            m = sum(1 for c2 in written_by.get(p, ()) if last_w.get(c2) == p and (c2 in pool_sh or c2 in pool_lo))
            W_own = own_n[w][(per, a)]
            rec[f"W_{w}"], rec[f"m_{w}"], rec[f"Wown_{w}"] = W, m, W_own
            rec[f"e_{w}"] = _p_hit(W, m, rec["k"])
            rec[f"eown_{w}"] = _p_hit(W_own, m, rec["k_own"])
        rows.append(rec)
    out = pl.DataFrame(rows)
    return out.join(ses.select(pl.col("s").alias("child"), "regime_cu"), on="child", how="left")


def _boot_ratio(groups: list[np.ndarray], num: list[np.ndarray], den: list[np.ndarray],
                rng: np.random.Generator, B: int) -> np.ndarray:
    """Bootstrap over clusters of sum(num) / sum(den); returns B values."""
    nums = np.array([x.sum() for x in num])
    dens = np.array([x.sum() for x in den])
    k = len(groups)
    pick = rng.integers(0, k, size=(B, k))
    with np.errstate(invalid="ignore", divide="ignore"):
        return nums[pick].sum(axis=1) / dens[pick].sum(axis=1)


def summarize(pairs: pl.DataFrame, variant: str, rng: np.random.Generator, B: int = 2000) -> list[dict]:
    """Rates, baselines, differences and ratios with agent-bootstrap CIs, by window and stratum."""
    rows = []
    strata = [("all", pairs)] + [(f"regime_{r}", pairs.filter(pl.col("regime_cu") == r))
                                 for r in ("pre", "post")]
    for stratum, df in strata:
        if df.is_empty():
            continue
        for w in WINDOWS:
            for measure, sel_expr, e_col in (
                ("with_parents", pl.col("k") >= 1, f"e_{w}"),
                ("all_pairs", pl.lit(True), f"e_{w}"),
                ("own_work", pl.col("k_own") >= 1, f"eown_{w}"),
            ):
                d = df.filter(sel_expr & pl.col(e_col).is_not_nan())
                if d.is_empty():
                    continue
                agents = d["agent_id"].unique().sort().to_list()
                by = {a: g for (a,), g in d.group_by(["agent_id"])}
                obs_l = [by[a]["cont"].to_numpy().astype(float) for a in agents]
                exp_l = [by[a][e_col].to_numpy() for a in agents]
                one_l = [np.ones(len(x)) for x in obs_l]
                r_obs = float(d["cont"].mean())
                r_exp = float(d[e_col].mean())
                bo = _boot_ratio(agents, obs_l, one_l, rng, B)
                be = _boot_ratio(agents, exp_l, one_l, rng, B)
                diff = bo - be
                with np.errstate(invalid="ignore", divide="ignore"):
                    ratio = bo / be
                q = lambda x, p: float(np.nanquantile(x, p)) if np.isfinite(x).any() else math.nan  # noqa: E731
                rows.append({
                    "variant": variant, "window": w, "measure": measure, "stratum": stratum,
                    "rate": r_obs, "rate_ci_low": q(bo, 0.025), "rate_ci_high": q(bo, 0.975),
                    "baseline": r_exp, "baseline_ci_low": q(be, 0.025), "baseline_ci_high": q(be, 0.975),
                    "difference": r_obs - r_exp, "difference_ci_low": q(diff, 0.025),
                    "difference_ci_high": q(diff, 0.975),
                    "ratio": r_obs / r_exp if r_exp > 0 else math.nan,
                    "ratio_ci_low": q(ratio, 0.025), "ratio_ci_high": q(ratio, 0.975),
                    "n_pairs": d.height, "n_agents": len(agents),
                    "median_pool": float(d[f"W_{w}" if measure != "own_work" else f"Wown_{w}"].median()),
                    "median_k": float(d["k" if measure != "own_work" else "k_own"].median()),
                })
    return rows
