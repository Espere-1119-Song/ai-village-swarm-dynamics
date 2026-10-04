"""Modules D2 to D4 on the real data: dependency graph, structure against the generator,
step cost by layer and the continuation rule (SPEC 8.3 to 8.5, figure F7 of SPEC 10.3).

`run_calibration(cfg)` runs everything and writes aggregates only:

- outputs/tables/depgraph_goals.csv: graph size per village goal;
- outputs/tables/depgraph_structure.csv: D3 statistics (pooled over goals, the median over goals,
  each goal), for all, write and read edges, with the generator mean, 95% range and the quantile
  of the AI Village value among 64 generated DAGs per goal;
- outputs/tables/depgraph_parent_counts.csv: the parent-count distribution, observed and generated;
- outputs/tables/depgraph_sensitivity.csv: pooled D3 statistics under other matching rules, touch
  sets and generator sizes;
- outputs/tables/depgraph_cost_by_layer.csv: session turns and duration by layer;
- outputs/tables/depgraph_continuation.csv: D4 continuation rates and baselines;
- outputs/tables/depgraph_rules.csv: touch counts per classification rule;
- outputs/tables/depgraph_robustness.csv: D3, step cost and D4 recomputed on goal subsets with a small
  GUI focus gap (avsd.swarmsim.robustness);
- outputs/tables/depgraph_artifacts.csv: artifact keys and edges by artifact kind;
- outputs/figures/F7_depgraph_generator.pdf and .png;
- outputs/qa/swarmsim_d2_d4.md.

Private intermediates (artifact keys, touches, edges) stay under data/interim/depgraph/. The main
touch rules are v2 (confirmed by the owner on 2026-10-01); `rules="v1"` writes the same files with the
suffix `_v1` (sensitivity version).

Generator: `avsd.swarmsim.dag.grow_dag` with the blog's parameters (17 layers, peak 0.28, merge
probability 0.46, no task variation), one DAG per goal and replicate with that goal's session
count. Sources: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html ; AI Digest, "AI Village dataset",
2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import platform
import time
from concurrent.futures import ProcessPoolExecutor
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from multiprocessing import get_context
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import polars as pl

from avsd.config import REPO_ROOT
from avsd.swarmsim.continuation import continuation_pairs, summarize
from avsd.swarmsim.dag import BLOG, grow_dag
from avsd.swarmsim.depgraph import (
    PARENT_BINS, STAT_NAMES, GraphParts, build_edges, graph_parts, layers_of, parent_lists,
    quantile_of, stats_from_parts,
)
from avsd.swarmsim.depgraph_data import default_workers, extract_touches, load_sessions, paths
from avsd.swarmsim.figure_f7 import plot_f7
from avsd.swarmsim.robustness import conclusion_checks, goal_coverage, goal_subsets, robustness_rows
from avsd.swarmsim.touches import MAIN_RULES, RULE_SETS, RULES, KeyMaps, artifact_key, build_key_maps

LABELS = ("all", "write", "read")
SOURCE_BLOG = ('Wenhao Chai, "Predictable Swarm Scaling", 2026, '
               "https://wenhaochai.com/blogs/predictable-swarm-scaling.html")
DATA_CITE = 'AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village'
LAYER_BINS = ((0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 4, "3-4"), (5, 8, "5-8"), (9, 16, "9-16"),
              (17, 32, "17-32"), (33, 64, "33-64"), (65, 10**9, "65+"))
DEPTH_BINS = ((0.0, 0.0, "0"), (1e-9, 0.2, "(0, 0.2]"), (0.2 + 1e-9, 0.4, "(0.2, 0.4]"),
              (0.4 + 1e-9, 0.6, "(0.4, 0.6]"), (0.6 + 1e-9, 0.8, "(0.6, 0.8]"), (0.8 + 1e-9, 1.0, "(0.8, 1]"))


@dataclass(frozen=True)
class CalibConfig:
    seed: int = 20261003
    gen_dags: int = 64            # SPEC 8.4
    gen_layers: int = 17          # the blog's language-modelling DAG
    boot: int = 2000
    workers: int = 0
    rules: str = MAIN_RULES       # touch rule version (avsd.swarmsim.touches.RULE_SETS)

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any]) -> CalibConfig:
        over = dict(cfg.get("swarmsim_calibrate") or {})
        kw: dict[str, Any] = {"seed": int(cfg.get("seed", cls.seed))}
        for f in fields(cls):
            if f.name in over:
                kw[f.name] = type(getattr(cls, f.name))(over[f.name])
        return cls(**kw)


def _rng(seed: int, *key: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=key))


# --- keys and per-(session, key) touches -------------------------------------------------------------

def key_maps(touches: pl.DataFrame, roots: pl.DataFrame) -> KeyMaps:
    """GitLab project-id map, unique-Pages map and local repository roots from the touches."""
    act = touches.filter(pl.col("mode").is_in(["read", "write"]))
    pid = (act.filter(pl.col("ref").str.starts_with("gitlab-pid:"))
           .with_columns(pl.col("ref").str.extract(r"^gitlab-pid:(\d+)").alias("pid"))
           .group_by("turn_id").agg(pl.col("pid").unique()))
    obs = (touches.filter((pl.col("mode") == "observed") & pl.col("ref").str.starts_with("gitlab:"))
           .with_columns(pl.col("ref").str.extract(r"^(gitlab:[^/]+/[^/]+)").alias("cont"))
           .drop_nulls("cont").group_by("turn_id").agg(pl.col("cont").unique()))
    votes = (pid.join(obs, on="turn_id")
             .filter((pl.col("pid").list.len() == 1) & (pl.col("cont").list.len() == 1))
             .select(pl.col("pid").list.first(), pl.col("cont").list.first()))
    conts = (touches.filter(pl.col("ref").str.starts_with("gitlab:"))
             .select(pl.col("ref").str.extract(r"^(gitlab:[^/]+/[^/]+)").alias("c")).drop_nulls()
             .unique()["c"].to_list())
    maps = build_key_maps(votes.iter_rows(), conts)
    rr: dict[str, set[str]] = {}
    for a, r in roots.iter_rows():
        rr.setdefault(a, set()).add(r)
    maps.repo_roots = {a: frozenset(v) for a, v in rr.items()}
    return maps


def keyed_touches(touches: pl.DataFrame, sessions: pl.DataFrame, maps: KeyMaps) -> pl.DataFrame:
    """Touches with artifact key, container and kind; refs that are not artifacts dropped."""
    pairs = touches.select("ref", "agent_id").unique()
    out_k, out_c, out_kind = [], [], []
    for ref, agent in pairs.iter_rows():
        r = artifact_key(ref, agent, maps)
        if r is None:
            out_k.append(None)
            out_c.append(None)
            out_kind.append(None)
        else:
            out_k.append(r[0])
            out_c.append(r[1])
            out_kind.append(r[2])
    keyed = pairs.with_columns(pl.Series("key", out_k, dtype=pl.String),
                               pl.Series("container", out_c, dtype=pl.String),
                               pl.Series("kind", out_kind, dtype=pl.String)).drop_nulls("key")
    sid = sessions.select("session_id", "s")
    t = (touches.join(keyed, on=["ref", "agent_id"], how="inner")
         .join(sid, on="session_id", how="inner")
         .with_columns((pl.col("ts").dt.epoch("us") / 1e6).alias("t")))
    # a ref whose key equals its container is a container-level touch
    t = t.with_columns((pl.col("clevel") | (pl.col("key") == pl.col("container"))).alias("clevel"))
    keys = t.select("key").unique().sort("key").with_row_index("k")
    conts = t.select("container").unique().sort("container").with_row_index("c")
    return (t.join(keys, on="key").join(conts, on="container")
            .with_columns(pl.col("k").cast(pl.Int64), pl.col("c").cast(pl.Int64)))


def per_session_key(t: pl.DataFrame, modes: tuple[str, ...], as_read: tuple[str, ...] = (),
                    kinds: tuple[str, ...] | None = None) -> pl.DataFrame:
    """One row per (session, key): first touch, writes, container-level flag, kind, first rule."""
    x = t.filter(pl.col("mode").is_in(list(modes) + list(as_read)))
    if kinds is not None:
        x = x.filter(pl.col("kind").is_in(list(kinds)))
    if as_read:
        x = x.with_columns(pl.when(pl.col("mode").is_in(list(as_read))).then(pl.lit("read"))
                           .otherwise(pl.col("mode")).alias("mode"))
    return (x.sort("t")
            .group_by("s", "k")
            .agg(pl.col("t").min().alias("first_t"),
                 (pl.col("mode") == "write").any().alias("wrote"),
                 pl.col("t").filter(pl.col("mode") == "write").unique().alias("write_ts"),
                 pl.col("clevel").any().alias("clevel"),
                 pl.col("c").first(), pl.col("kind").first(), pl.col("rule").first(),
                 pl.col("container").first())
            .sort("s", "k"))


# --- graphs per goal -------------------------------------------------------------------------------

@dataclass
class GoalGraphs:
    goal_ids: list[str]
    goal_label: dict[str, str]
    nodes: dict[str, np.ndarray]                       # goal -> global session ints (start order)
    parts: dict[tuple[str, str], GraphParts]           # (goal, label) -> parts
    layer: dict[str, np.ndarray]                       # goal -> layer of each node (all edges)
    layer_write: dict[str, np.ndarray]
    edges_in: dict[tuple[str, str], int]
    cross_goal: dict[str, int]


def goal_graphs(sessions: pl.DataFrame, edges: pl.DataFrame, goals: pl.DataFrame) -> GoalGraphs:
    """Per-goal graphs from the global edges (edges across goals dropped)."""
    goal_of = dict(zip(sessions["s"].to_list(), sessions["goal_id"].to_list(), strict=True))
    order = goals.sort("start_time")["id"].to_list()
    label = {g: f"G{i + 1:02d}" for i, g in enumerate(order)}
    nodes: dict[str, np.ndarray] = {}
    for (g,), df in sessions.filter(pl.col("goal_id").is_not_null()).group_by(["goal_id"]):
        nodes[g] = np.sort(df["s"].to_numpy())
    e = edges.with_columns(pl.col("parent").replace_strict(goal_of, default=None).alias("gp"),
                           pl.col("child").replace_strict(goal_of, default=None).alias("gc"))
    cross = e.filter(pl.col("gp") != pl.col("gc")).group_by("gc").len()
    cross_goal = dict(zip(cross["gc"].to_list(), cross["len"].to_list(), strict=True))
    within = e.filter(pl.col("gp") == pl.col("gc"))
    parts: dict[tuple[str, str], GraphParts] = {}
    layer: dict[str, np.ndarray] = {}
    layer_w: dict[str, np.ndarray] = {}
    edges_in: dict[tuple[str, str], int] = {}
    by_goal = {g: df for (g,), df in within.group_by(["gc"])}
    for g in [x for x in order if x in nodes]:
        ids = nodes[g]
        local = {int(s): i for i, s in enumerate(ids)}
        df = by_goal.get(g)
        for lab in LABELS:
            if df is None:
                sel = []
            else:
                d = df if lab == "all" else df.filter(pl.col("label") == lab)
                sel = [(local[a], local[b]) for a, b in zip(d["parent"].to_list(), d["child"].to_list(),
                                                             strict=True)]
            ps = parent_lists(len(ids), sel)
            parts[(g, lab)] = graph_parts(ps)
            edges_in[(g, lab)] = len(sel)
            if lab == "all":
                layer[g] = layers_of(ps)
            elif lab == "write":
                layer_w[g] = layers_of(ps)
    return GoalGraphs([x for x in order if x in nodes], label, nodes, parts, layer, layer_w, edges_in,
                      {g: int(cross_goal.get(g, 0)) for g in nodes})


# --- generator ---------------------------------------------------------------------------------------

def _gen_goal(args: tuple[int, int, int, int, int, int]) -> tuple[int, int, list[GraphParts]]:
    """`reps` generated DAGs of `n` steps over `D` layers (blog parameters, no task variation)."""
    tag, gi, n, D, seed, reps = args
    out = []
    for r in range(reps):
        dag = grow_dag(n, D, BLOG.peak, BLOG.merge_p, _rng(seed, 7, tag, gi, r), BLOG)
        out.append(graph_parts(dag.parents))
    return tag, gi, out


def generate(sizes: dict[int, list[tuple[int, int]]], seed: int, reps: int, workers: int
             ) -> dict[int, dict[int, list[GraphParts]]]:
    """Generated parts per tag and goal index. `sizes[tag]` lists (n, layers) per goal."""
    jobs = [(tag, gi, n, D, seed, reps) for tag, lst in sizes.items() for gi, (n, D) in enumerate(lst)]
    jobs.sort(key=lambda j: -j[2])
    out: dict[int, dict[int, list[GraphParts]]] = {tag: {} for tag in sizes}
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
        for tag, gi, parts in ex.map(_gen_goal, jobs, chunksize=1):
            out[tag][gi] = parts
    return out


def _stat_row(scope: str, label: str, stat: str, obs: float, gen: np.ndarray, extra: dict) -> dict:
    g = gen[np.isfinite(gen)]
    nan = math.nan
    return {"scope": scope, "edges": label, "statistic": stat, "observed": obs,
            "gen_mean": float(g.mean()) if len(g) else nan,
            "gen_sd": float(g.std(ddof=1)) if len(g) > 1 else nan,
            "gen_p025": float(np.quantile(g, 0.025)) if len(g) else nan,
            "gen_p975": float(np.quantile(g, 0.975)) if len(g) else nan,
            "quantile": quantile_of(obs, g), "gen_n": int(len(g)), **extra}


# --- cost by layer -----------------------------------------------------------------------------------

def _within_slope(byg: dict[str, tuple[np.ndarray, np.ndarray]], sel: list[str]) -> float:
    """Least-squares slope of y on x with a separate intercept per goal (goals may repeat)."""
    num = den = 0.0
    for g in sel:
        xx, yy = byg[g]
        if len(xx) < 2:
            continue
        xc = xx - xx.mean()
        num += float(xc @ (yy - yy.mean()))
        den += float(xc @ xc)
    return num / den if den > 0 else math.nan


COSTS = (("turns", "n_turns"), ("active_min", "active_min"))


def session_layers(sessions: pl.DataFrame, gg: GoalGraphs) -> pl.DataFrame:
    """One row per (goal, edge label, session with turns): layer, relative depth and costs, each cost
    also relative to the mean of the goal's layer-0 sessions (`rel_turns`, `rel_active_min`)."""
    recs = []
    for g in gg.goal_ids:
        for lab, lay in (("all", gg.layer[g]), ("write", gg.layer_write[g])):
            D = int(lay.max()) + 1 if len(lay) else 1
            for s, d in zip(gg.nodes[g].tolist(), lay.tolist(), strict=True):
                recs.append((g, lab, s, d, d / (D - 1) if D > 1 else 0.0, D))
    lay = pl.DataFrame(recs, schema={"goal_id": pl.String, "edges": pl.String, "s": pl.Int64,
                                     "layer": pl.Int64, "rel_depth": pl.Float64, "goal_layers": pl.Int64},
                       orient="row")
    d = (lay.join(sessions.select("s", "n_turns", "active_min"), on="s", how="left")
         .filter(pl.col("n_turns") > 0))
    for name, col in COSTS:
        base = (d.filter(pl.col("layer") == 0).group_by("goal_id", "edges")
                .agg(pl.col(col).mean().alias(f"c0_{name}")))
        d = d.join(base, on=["goal_id", "edges"], how="left").with_columns(
            (pl.col(col) / pl.col(f"c0_{name}")).alias(f"rel_{name}"))
    return d


def cost_slopes(d: pl.DataFrame, goals: Sequence[str] | None, rng: np.random.Generator, boot: int,
                lab: str = "all") -> dict[str, dict]:
    """Within-goal least-squares slope of relative cost on relative depth, with a goal-bootstrap CI."""
    q = lambda x, p: float(np.nanquantile(x, p)) if np.isfinite(x).any() else math.nan  # noqa: E731
    dl = d.filter((pl.col("edges") == lab) & (pl.col("goal_layers") > 1))
    if goals is not None:
        dl = dl.filter(pl.col("goal_id").is_in(list(goals)))
    res = {}
    for name, _ in COSTS:
        x = dl.filter(pl.col(f"rel_{name}").is_finite())
        byg = {g: (df["rel_depth"].to_numpy(), df[f"rel_{name}"].to_numpy()) for (g,), df in x.group_by(["goal_id"])}
        gl = sorted(byg)
        est = _within_slope(byg, gl) if gl else math.nan
        bs = np.array([_within_slope(byg, [gl[i] for i in rng.integers(0, len(gl), size=len(gl))])
                       for _ in range(min(boot, 1000))]) if gl else np.array([math.nan])
        res[name] = {"slope": est, "ci_low": q(bs, 0.025), "ci_high": q(bs, 0.975),
                     "n_sessions": int(x.height), "n_goals": len(gl), "blog_slope": 9.0}
    return res


def cost_by_layer(sessions: pl.DataFrame, gg: GoalGraphs, rng: np.random.Generator, boot: int
                  ) -> tuple[pl.DataFrame, dict, pl.DataFrame]:
    """Session cost by layer against the blog's c_d = 1 + 9 d / (D - 1).

    Costs are the session's turn count and its active minutes. Each session's cost is divided by
    the mean cost of the layer-0 sessions of its own goal, so goals with longer or shorter
    sessions do not mix into the depth comparison. Bins are absolute layers and relative depth
    d / (D - 1), D being the goal graph's number of layers. CIs come from a bootstrap over goals.
    `fit[edges][cost]` is the within-goal least-squares slope of relative cost on relative depth
    (the blog's slope is 9). Also returns the per-session layer table (`session_layers`).
    """
    d = session_layers(sessions, gg)
    bins_l = pl.lit(None, dtype=pl.String)
    for lo, hi, nm in reversed(LAYER_BINS):
        bins_l = pl.when((pl.col("layer") >= lo) & (pl.col("layer") <= hi)).then(pl.lit(nm)).otherwise(bins_l)
    bins_r = pl.lit(None, dtype=pl.String)
    for lo, hi, nm in reversed(DEPTH_BINS):
        bins_r = pl.when((pl.col("rel_depth") >= lo) & (pl.col("rel_depth") <= hi)).then(pl.lit(nm)).otherwise(bins_r)
    d = d.with_columns(bins_l.alias("layer_bin"), bins_r.alias("depth_bin"),
                       (1.0 + 9.0 * pl.col("rel_depth")).alias("blog_ratio"))
    goals = gg.goal_ids
    gi = {g: i for i, g in enumerate(goals)}
    pick = rng.integers(0, len(goals), size=(boot, len(goals)))
    rows = []
    q = lambda x, p: float(np.nanquantile(x, p)) if np.isfinite(x).any() else math.nan  # noqa: E731
    sums = ["n_turns", "active_min", "rel_turns", "rel_active_min", "blog_ratio"]
    for lab in ("all", "write"):
        dl = d.filter(pl.col("edges") == lab)
        for axis, col, bins in (("layer", "layer_bin", LAYER_BINS), ("relative_depth", "depth_bin", DEPTH_BINS)):
            agg = (dl.group_by("goal_id", col)
                   .agg(*[pl.col(c).cast(pl.Float64).drop_nans().drop_nulls().sum().alias(c) for c in sums],
                        *[pl.col(c).cast(pl.Float64).drop_nans().drop_nulls().len().alias(f"n_{c}") for c in sums]))
            for nm in [b[2] for b in bins]:
                a = agg.filter(pl.col(col) == nm)
                if a.is_empty():
                    continue
                M = np.zeros((len(goals), 2 * len(sums)))
                for r in a.iter_rows(named=True):
                    M[gi[r["goal_id"]]] = [r[c] for c in sums] + [r[f"n_{c}"] for c in sums]
                tot = M.sum(axis=0)
                bs = M[pick].sum(axis=1)
                rec: dict[str, Any] = {"edges": lab, "axis": axis, "bin": nm,
                                       "n_sessions": int(tot[len(sums)]),
                                       "n_goals": int((M[:, len(sums)] > 0).sum())}
                for j, c in enumerate(sums):
                    with np.errstate(invalid="ignore", divide="ignore"):
                        est = tot[j] / tot[len(sums) + j] if tot[len(sums) + j] else math.nan
                        b = bs[:, j] / bs[:, len(sums) + j]
                    key = {"n_turns": "mean_turns", "active_min": "mean_active_min",
                           "rel_turns": "turns_vs_layer0", "rel_active_min": "active_vs_layer0",
                           "blog_ratio": "blog_vs_layer0"}[c]
                    rec[key] = est
                    if c != "blog_ratio":
                        rec[f"{key}_ci_low"], rec[f"{key}_ci_high"] = q(b, 0.025), q(b, 0.975)
                rows.append(rec)
    fit: dict[str, dict] = {lab: cost_slopes(d, None, rng, boot, lab) for lab in ("all", "write")}
    dist = sessions.filter(pl.col("n_turns") > 0)
    fit["turn_quantiles"] = {str(p): float(dist["n_turns"].quantile(p)) for p in (0.1, 0.5, 0.9, 0.99)}
    fit["active_quantiles"] = {str(p): float(dist["active_min"].quantile(p)) for p in (0.1, 0.5, 0.9, 0.99)}
    fit["wall_quantiles"] = {str(p): float(dist["duration_min"].quantile(p)) for p in (0.1, 0.5, 0.9, 0.99)}
    return pl.DataFrame(rows), fit, d


# --- the run -----------------------------------------------------------------------------------------

def run_calibration(cfg: dict[str, Any], force_extract: bool = False, log=print,
                    rules: str | None = None) -> dict[str, Any]:
    """Run D2 to D4 and write the outputs listed in the module docstring.

    `rules` picks the touch rule version (`avsd.swarmsim.touches.RULE_SETS`); by default the config's
    `swarmsim_calibrate.rules`, else MAIN_RULES (v2, confirmed by the owner on 2026-10-01). The main
    version writes the files named in the module docstring; any other version adds `_<version>` to every
    output name (v1, the first draft, is the sensitivity version `_v1`).
    """
    t0 = time.time()
    cc = CalibConfig.from_cfg(cfg)
    rules = rules or cc.rules
    if rules not in RULE_SETS:
        raise ValueError(f"unknown touch rules {rules!r}; known: {sorted(RULE_SETS)}")
    sfx = "" if rules == MAIN_RULES else f"_{rules}"
    workers = cc.workers or default_workers()
    rng = _rng(cc.seed, 11)
    T = Path(cfg["paths"]["tables"])
    sessions = load_sessions(cfg).with_columns((pl.col("start").dt.epoch("us") / 1e6).alias("start_t"))
    goals = pl.read_parquet(T / "village_goals.parquet", columns=["id", "start_time", "end_time"])
    raw = extract_touches(cfg, workers, force=force_extract, log=log, rules=rules)
    maps = key_maps(raw["touches"], raw["roots"])
    tk = keyed_touches(raw["touches"], sessions, maps)
    log(f"keyed touches {tk.height:,}; gitlab ids mapped {len(maps.gitlab_pid)}; "
        f"pages projects {len(maps.pages_project)} ({time.time() - t0:.0f} s)")
    start_rank = np.zeros(sessions.height, dtype=np.int64)
    start_rank[sessions["s"].to_numpy()] = np.arange(sessions.height)

    variants = {
        "main": dict(modes=("write", "read"), hierarchical=True),
        "exact_keys": dict(modes=("write", "read"), hierarchical=False),
        "with_observed_mentions": dict(modes=("write", "read"), as_read=("observed", "mention"), hierarchical=True),
        "structured_only": dict(modes=("write", "read"), kinds=("gdoc", "github", "gitlab", "local"),
                                hierarchical=True),
    }
    builds = {}
    psk_main = None
    for name, v in variants.items():
        psk = per_session_key(tk, v["modes"], v.get("as_read", ()), v.get("kinds"))
        if name == "main":
            psk_main = psk
        builds[name] = build_edges(psk, start_rank, hierarchical=v["hierarchical"])
        log(f"edges {name}: {builds[name].edges.height:,} (dropped by start order "
            f"{builds[name].dropped_order:,}) ({time.time() - t0:.0f} s)")
    main = builds["main"]
    pdir = paths(cfg)["dir"]
    main.edges.write_parquet(pdir / f"edges_main{sfx}.parquet")
    psk_main.drop("write_ts").write_parquet(pdir / f"session_keys_main{sfx}.parquet")

    gg = goal_graphs(sessions, main.edges, goals)
    gg_var = {name: goal_graphs(sessions, b.edges, goals) for name, b in builds.items() if name != "main"}
    goal_ids = gg.goal_ids
    n_goal = [len(gg.nodes[g]) for g in goal_ids]
    conn = []
    for g in goal_ids:
        p = gg.parts[(g, "all")]
        conn.append(max(p.n - p.n_isolated, 2))
    depth = [max(gg.parts[(g, "all")].n_layers, 3) for g in goal_ids]
    sizes = {0: [(n, cc.gen_layers) for n in n_goal],
             1: [(n, cc.gen_layers) for n in conn],
             2: [(n, min(D, n)) for n, D in zip(n_goal, depth, strict=True)]}
    gen = generate(sizes, cc.seed, cc.gen_dags, workers)
    log(f"generator: {cc.gen_dags} DAGs for each of {len(goal_ids)} goals x 3 size rules "
        f"({time.time() - t0:.0f} s)")

    # --- D3 statistics ---
    stat_rows: list[dict] = []
    all_stats = [*STAT_NAMES, *[f"parents_{b}" for b in PARENT_BINS]]
    pooled_gen = {st: np.array([stats_from_parts([gen[0][gi][r] for gi in range(len(goal_ids))])[st]
                                for r in range(cc.gen_dags)]) for st in all_stats}
    pooled_obs = {lab: stats_from_parts([gg.parts[(g, lab)] for g in goal_ids]) for lab in LABELS}
    per_goal_gen = {gi: [stats_from_parts([gen[0][gi][r]]) for r in range(cc.gen_dags)] for gi in range(len(goal_ids))}
    per_goal_obs = {(g, lab): stats_from_parts([gg.parts[(g, lab)]]) for g in goal_ids for lab in LABELS}
    for lab in LABELS:
        po = pooled_obs[lab]
        extra = {"n_goals": len(goal_ids), "n_nodes": int(po["n_nodes"]), "n_edges": int(po["n_edges"]),
                 "n_child_nodes": int(po["n_child_nodes"]), "n_multi": int(po["n_multi"])}
        for st in [*STAT_NAMES, *[f"parents_{b}" for b in PARENT_BINS]]:
            stat_rows.append(_stat_row("pooled", lab, st, po[st], pooled_gen[st], extra))
        for st in STAT_NAMES:
            ov = np.array([per_goal_obs[(g, lab)][st] for g in goal_ids])
            ok = np.isfinite(ov)
            gmed = np.array([np.nanmedian([per_goal_gen[gi][r][st] for gi in range(len(goal_ids)) if ok[gi]])
                             if ok.any() else math.nan for r in range(cc.gen_dags)])
            stat_rows.append(_stat_row("goal_median", lab, st, float(np.median(ov[ok])) if ok.any() else math.nan,
                                       gmed, {"n_goals": int(ok.sum())}))
        for gi, g in enumerate(goal_ids):
            o = per_goal_obs[(g, lab)]
            extra = {"n_goals": 1, "n_nodes": int(o["n_nodes"]), "n_edges": int(o["n_edges"]),
                     "n_child_nodes": int(o["n_child_nodes"]), "n_multi": int(o["n_multi"])}
            for st in STAT_NAMES:
                stat_rows.append(_stat_row(gg.goal_label[g], lab, st, o[st],
                                           np.array([per_goal_gen[gi][r][st] for r in range(cc.gen_dags)]), extra))
    structure = pl.DataFrame(stat_rows)

    # --- sensitivity (pooled) ---
    sens_rows = []
    gen_alt = {1: "generator at connected-node count", 2: "generator with depth matched to the goal graph"}
    for tag, desc in gen_alt.items():
        pg = {st: np.array([stats_from_parts([gen[tag][gi][r] for gi in range(len(goal_ids))])[st]
                            for r in range(cc.gen_dags)]) for st in STAT_NAMES}
        for lab in ("all", "write"):
            for st in STAT_NAMES:
                sens_rows.append({"variant": desc, **_stat_row("pooled", lab, st, pooled_obs[lab][st], pg[st], {})})
    for name, g2 in gg_var.items():
        for lab in ("all", "write"):
            po = stats_from_parts([g2.parts[(g, lab)] for g in goal_ids])
            for st in STAT_NAMES:
                sens_rows.append({"variant": name.replace("_", " "),
                                  **_stat_row("pooled", lab, st, po[st], pooled_gen[st],
                                              {"n_edges": int(po["n_edges"])})})
    sensitivity = pl.DataFrame(sens_rows)

    # --- graph sizes per goal ---
    gstart = dict(zip(goals["id"].to_list(), goals["start_time"].to_list(), strict=True))
    gend = dict(zip(goals["id"].to_list(), goals["end_time"].to_list(), strict=True))
    n_agents = dict(sessions.group_by("goal_id").agg(pl.col("agent_id").n_unique()).iter_rows())
    touched = set(psk_main["s"].unique().to_list())
    goal_rows = []
    for g in goal_ids:
        pa, pw, pr = (gg.parts[(g, lab)] for lab in LABELS)
        ids = gg.nodes[g]
        goal_rows.append({
            "goal": gg.goal_label[g], "start": gstart[g].date().isoformat(),
            "end": gend[g].date().isoformat() if gend[g] is not None else "open",
            "sessions": len(ids), "agents": int(n_agents.get(g, 0)),
            "sessions_with_touches": int(sum(1 for s in ids.tolist() if s in touched)),
            "edges_all": pa.n_edges, "edges_write": pw.n_edges, "edges_read": pr.n_edges,
            "edges_cross_goal_dropped": gg.cross_goal.get(g, 0),
            "layers_all": pa.n_layers, "layers_write": pw.n_layers,
            "root_share_all": pa.n_roots / pa.n if pa.n else math.nan,
            "isolated_share_all": pa.n_isolated / pa.n if pa.n else math.nan,
            "multi_parent_share_all": per_goal_obs[(g, "all")]["multi_parent_share"],
        })
    goals_tab = pl.DataFrame(goal_rows)

    # --- parent-count distribution ---
    pc_rows = []
    for lab in LABELS:
        for b in PARENT_BINS:
            st = f"parents_{b}"
            pc_rows.append({"edges": lab, "parents": b, "observed": pooled_obs[lab][st],
                            "gen_mean": float(np.nanmean(pooled_gen[st])),
                            "gen_p025": float(np.nanquantile(pooled_gen[st], 0.025)),
                            "gen_p975": float(np.nanquantile(pooled_gen[st], 0.975)),
                            "quantile": quantile_of(pooled_obs[lab][st], pooled_gen[st]),
                            "n_child_nodes": int(pooled_obs[lab]["n_child_nodes"])})
    parent_counts = pl.DataFrame(pc_rows)

    # --- cost by layer ---
    cost, cost_fit, layers = cost_by_layer(sessions, gg, rng, cc.boot)

    # --- D4 continuation ---
    writes = (tk.filter(pl.col("mode") == "write")
              .select("s", "c", "t", (pl.col("kind") == "local").alias("local")).unique())
    cont_rows = []
    pairs_by: dict[str, pl.DataFrame] = {}
    child_goal = sessions.select(pl.col("s").alias("child"), "goal_id")
    for name, lab_filter in (("all", None), ("write", "write")):
        f = main.found if lab_filter is None else main.found.filter(pl.col("write") == 1)
        pairs = continuation_pairs(sessions.select("s", "agent_id", "start_t", "goal_id", "run_day", "regime_cu"),
                                   writes, f.select("child", "c", "parent"))
        pairs_by[name] = pairs.join(child_goal, on="child", how="left")
        cont_rows += summarize(pairs, name, rng, cc.boot)
    pairs_main = pairs_by["all"]
    continuation = pl.DataFrame(cont_rows)

    # --- robustness to the GUI focus gap ---
    cov = goal_coverage(sessions, goals, tk, raw["gui"], sorted(touched))
    subsets = goal_subsets(cov)
    rob = pl.DataFrame(robustness_rows(subsets, gg.parts, gen[0], goal_ids, {g: len(gg.nodes[g]) for g in goal_ids},
                                       layers, pairs_by, _rng(cc.seed, 13), cc.boot, cc.gen_dags),
                       infer_schema_length=None)
    checks = conclusion_checks(rob)
    gap_of = dict(zip(cov["goal_id"].to_list(), cov["gap"].to_list(), strict=True))
    goals_tab = goals_tab.with_columns(
        pl.Series("gui_gap", [gap_of.get(g) for g in goal_ids], dtype=pl.Float64),
        (pl.col("sessions_with_touches") / pl.col("sessions")).alias("touch_share"))
    log(f"robustness: {len(subsets)} goal subsets, {sum(checks['holds'])} of {checks.height} checks hold "
        f"({time.time() - t0:.0f} s)")

    # --- who builds on whom ---
    agent_of = sessions.select(pl.col("s").alias("parent"), pl.col("agent_id").alias("pa"),
                               pl.col("goal_id").alias("gp"))
    e2 = (main.edges.join(agent_of, on="parent")
          .join(agent_of.rename({"parent": "child", "pa": "ca", "gp": "gc"}), on="child"))
    who = []
    for lab in LABELS:
        x = e2 if lab == "all" else e2.filter(pl.col("label") == lab)
        xin = x.filter(pl.col("gp") == pl.col("gc"))
        for scope, df in (("global", x), ("within_goal", xin)):
            same = df.filter(pl.col("pa") == pl.col("ca"))
            who.append({"edges": lab, "scope": scope, "n_edges": df.height,
                        "same_agent_share": same.height / df.height if df.height else math.nan,
                        "local_only_share": (df.filter(pl.col("kinds") == "local").height / df.height
                                             if df.height else math.nan)})

    # --- rules and artifacts ---
    rt = raw["touches"]
    rules_rows = []
    rule_edges = main.edges.select(pl.col("rules").str.split(",")).explode("rules")["rules"].value_counts()
    rule_edge_n = dict(rule_edges.iter_rows())
    n_ses = sessions.filter(pl.col("n_turns") > 0).height
    for rid, (mode, desc) in RULES.items():
        x = rt.filter(pl.col("rule") == rid)
        xk = tk.filter(pl.col("rule") == rid)
        rules_rows.append({"rule": rid, "mode": mode, "description": desc, "touches": x.height,
                           "turns": x["turn_id"].n_unique(), "sessions": x["session_id"].n_unique(),
                           "session_share": x["session_id"].n_unique() / n_ses,
                           "agents": x["agent_id"].n_unique(), "artifact_touches": xk.height,
                           "edges_first_touch": int(rule_edge_n.get(rid, 0))})
    rules_tab = pl.DataFrame(rules_rows)
    art_rows = []
    kind_edges = main.edges.select(pl.col("kinds").str.split(",")).explode("kinds")["kinds"].value_counts()
    ke = dict(kind_edges.iter_rows())
    for (kind,), x in tk.group_by(["kind"]):
        art_rows.append({"kind": kind, "domain": "", "keys": x["key"].n_unique(),
                         "containers": x["container"].n_unique(),
                         "written_keys": x.filter(pl.col("mode") == "write")["key"].n_unique(),
                         "touches_read_write": x.filter(pl.col("mode").is_in(["read", "write"])).height,
                         "sessions": x["s"].n_unique(), "edges_main": int(ke.get(kind, 0))})
    url_w = (tk.filter((pl.col("kind") == "url") & (pl.col("mode") == "write"))
             .with_columns(pl.col("key").map_elements(registrable_domain, return_dtype=pl.String)
                           .alias("domain"))
             .group_by("domain").agg(pl.col("key").n_unique().alias("written_keys"),
                                     pl.col("s").n_unique().alias("sessions"))
             .sort("sessions", descending=True).head(15))
    for dom, wk, ns in url_w.iter_rows():
        art_rows.append({"kind": "url (top written domains)", "domain": dom, "keys": None, "containers": None,
                         "written_keys": wk, "touches_read_write": None, "sessions": ns, "edges_main": None})
    artifacts = pl.DataFrame(art_rows).sort("kind", "sessions", descending=[False, True])

    # --- write ---
    out = Path(cfg["paths"]["outputs"])
    files = {
        "goals": out / "tables" / f"depgraph_goals{sfx}.csv",
        "structure": out / "tables" / f"depgraph_structure{sfx}.csv",
        "parent_counts": out / "tables" / f"depgraph_parent_counts{sfx}.csv",
        "sensitivity": out / "tables" / f"depgraph_sensitivity{sfx}.csv",
        "cost": out / "tables" / f"depgraph_cost_by_layer{sfx}.csv",
        "continuation": out / "tables" / f"depgraph_continuation{sfx}.csv",
        "rules": out / "tables" / f"depgraph_rules{sfx}.csv",
        "artifacts": out / "tables" / f"depgraph_artifacts{sfx}.csv",
        "robustness": out / "tables" / f"depgraph_robustness{sfx}.csv",
        "figure": out / "figures" / f"F7_depgraph_generator{sfx}.pdf",
        "qa": out / "qa" / f"swarmsim_d2_d4{sfx}.md",
    }
    for p in files.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    goals_tab.write_csv(files["goals"], float_precision=4)
    structure.write_csv(files["structure"], float_precision=5)
    parent_counts.write_csv(files["parent_counts"], float_precision=5)
    sensitivity.write_csv(files["sensitivity"], float_precision=5)
    cost.write_csv(files["cost"], float_precision=4)
    continuation.write_csv(files["continuation"], float_precision=5)
    rob.write_csv(files["robustness"], float_precision=5)
    rules_tab.write_csv(files["rules"], float_precision=4)
    artifacts.write_csv(files["artifacts"], float_precision=4)
    figs = plot_f7(pooled_gen, {lab: pooled_obs[lab] for lab in ("all", "write")}, list(STAT_NAMES),
                   files["figure"].with_suffix(""), len(goal_ids), cc.gen_dags)
    pairs_main.write_parquet(pdir / f"continuation_pairs_main{sfx}.parquet")

    def rel(p: Path) -> str:
        return str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)

    outputs = {k: rel(v) for k, v in files.items()} | {"figure_png": rel(figs[1])}
    runtime = {"wall_s": time.time() - t0, "workers": workers, "host": platform.node()}
    extras = {
        "n_sessions": sessions.height, "n_sessions_with_turns": n_ses,
        "touch_modes": dict(raw["touches"].group_by("mode").len().iter_rows()),
        "n_touch_rows": raw["touches"].height, "n_keyed": tk.height,
        "n_keys": tk["key"].n_unique(), "n_containers": tk["container"].n_unique(),
        "gitlab_pid_mapped": len(maps.gitlab_pid), "pages_projects": len(maps.pages_project),
        "rules": rules,
        "gui_counts": {k: int(raw["gui"][k].sum()) for k in raw["gui"].columns if k.startswith("gui_")},
        "gui": raw["gui"].select(pl.col("gui_writes").sum(), pl.col("gui_writes_unattributed").sum(),
                                 (pl.col("gui_writes") > 0).sum().alias("sessions_gui"),
                                 ((pl.col("gui_writes") > 0)
                                  & (pl.col("gui_writes") == pl.col("gui_writes_unattributed")))
                                 .sum().alias("sessions_gui_unattributed")).row(0, named=True),
        "builds": {k: {"edges": b.edges.height, "write": int((b.edges["label"] == "write").sum()),
                       "read": int((b.edges["label"] == "read").sum()), "dropped_order": b.dropped_order,
                       "lookups": b.lookups, "lookups_with_writer": b.lookups_with_writer}
                   for k, b in builds.items()},
        "cross_goal": sum(gg.cross_goal.values()),
        "who": who,
        "sessions_touched": len(touched),
        "cost_fit": cost_fit,
    }
    from avsd.swarmsim.calibrate_report import write_qa

    write_qa(files["qa"], cc, outputs, runtime, extras, goals_tab, structure, parent_counts, sensitivity,
             cost, continuation, rules_tab, artifacts, rob, checks, cov)
    log(f"done in {time.time() - t0:.0f} s")
    return {"outputs": outputs, "runtime": runtime, "config": asdict(cc), "extras": extras,
            "structure": structure, "continuation": continuation, "robustness": rob, "checks": checks}


_SLD = frozenset({"co", "com", "org", "net", "ac", "gov", "edu", "or", "ne", "go"})


def registrable_domain(url_key: str) -> str:
    """Registrable domain of a `url:` key (`a.b.example.org` -> `example.org`).

    Aggregate tables show only this part, so subdomains that name a person or an account (blogs,
    shops, Pages sites) never reach outputs/.
    """
    host = urlsplit("https://" + url_key.split(":", 1)[1]).hostname or ""
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SLD:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])
