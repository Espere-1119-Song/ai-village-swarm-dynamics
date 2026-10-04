"""Reproduction checks of the blog's swarm results (SPEC 8.2 D1).

Protocol, as in the blog. A family is 16 tasks drawn around the language-modelling DAG. On each
task we run one agent 16 times (the baseline), and one standard swarm and one recursive swarm of
three layers for N = 2, 4, ..., 64 (one run per task and size, both kinds on the same random
stream). Each task's clock is divided by its mean single-agent time to finish every step and
stretched by exp(delta_b); T1 is then the slowest of the family's 256 single-agent runs, and every
time is reported in units of T1. Scores are averaged over the family's tasks (all 16 baseline runs
per task for one agent), and speedups g_x compare the first times the averages reach level x.

The blog reports one family. We simulate many independent families and report, for every
statistic, the mean over families, a bootstrap 95% CI of that mean, and the 2.5% to 97.5% range of
single families (the spread a single 16-task family such as the blog's shows). No parameter is
tuned to the blog's numbers.

Outputs: outputs/tables/swarmsim_reproduction.csv, outputs/tables/swarmsim_scaling.csv,
outputs/figures/swarmsim_coverage.pdf and .png, outputs/qa/swarmsim_d1.md, and the per-family
statistics data/interim/swarmsim_family_stats.parquet.

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

import math
import os
import platform
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, fields
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from avsd.config import REPO_ROOT
from avsd.swarmsim.dag import (
    BLOG, GenParams, draw_task, grow_dag, score_scale, scores, structure_stats, task_dag,
)
from avsd.swarmsim.figure import plot_coverage
from avsd.swarmsim.metrics import (
    coverage_curve, first_reach, mean_curve, on_grid, scaling_exponent,
)
from avsd.swarmsim.sim import BLOG_OVERHEADS, Overheads, record_events, simulate, single_agent

SOURCE = ('Wenhao Chai, "Predictable Swarm Scaling", 2026, '
          "https://wenhaochai.com/blogs/predictable-swarm-scaling.html")
SIZES = (1, 2, 4, 8, 16, 32, 64)
FIG_SIZES = (4, 16, 32, 64)
KINDS = ("standard", "recursive")
COV_LEVELS = {"cov25": 0.25, "cov50": 0.5, "cov75": 0.75, "cov90": 0.9, "cov100": 1.0}
BEST_LEVELS = {"best50": 0.5, "best80": 0.8}
GRID = np.geomspace(1e-4, 1.0, 481)
TOL = 0.20
CHECK_COLUMNS = ["check", "required", "blog", "blog_low", "blog_high", "ours", "ci95_low",
                 "ci95_high", "range_p025", "range_p975", "unit", "n", "blog_percentile",
                 "rel_deviation", "status", "note"]


@dataclass(frozen=True)
class ReproConfig:
    seed: int = 20261003
    families: int = 256
    tasks: int = 16
    sessions: int = 16
    sizes: tuple[int, ...] = SIZES
    recursive_layers: int = 3
    gen_dags: int = 1024
    workers: int = 0
    boot: int = 4000

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any]) -> ReproConfig:
        over = dict(cfg.get("swarmsim") or {})
        kw: dict[str, Any] = {"seed": int(cfg.get("seed", cls.seed))}
        for f in fields(cls):
            if f.name in over:
                v = over[f.name]
                kw[f.name] = tuple(int(x) for x in v) if f.name == "sizes" else type(getattr(cls, f.name))(v)
        return cls(**kw)


def _rng(seed: int, *key: int) -> np.random.Generator:
    """An independent stream per (purpose, family, task, kind, index) key."""
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=key))


# --- simulation units (run in worker processes) -----------------------------------------------

def _family(args: tuple[int, ReproConfig, GenParams, Overheads]) -> dict[str, Any]:
    """Simulate one family of tasks and return its statistics and coverage curves."""
    f, rc, p, ov = args
    c0 = time.process_time()
    seed = rc.seed
    tasks, base_cov, base_best, base_done = [], [], [], []
    swarm_cov: dict[tuple[str, int], list] = {}
    swarm_best: dict[tuple[str, int], list] = {}
    swarm_done: dict[tuple[str, int], list] = {}
    acct: dict[tuple[str, int], list] = {}
    for b in range(rc.tasks):
        rng = _rng(seed, 1, f, b, 0)
        task = draw_task(rng, p)
        dag = task_dag(task, rng, p)
        scale = score_scale(task, [_rng(seed, 1, f, b, 1, r) for r in range(p.scale_draws)], p)
        v = scores(dag, scale)
        singles = [single_agent(dag, _rng(seed, 1, f, b, 2, s)) for s in range(rc.sessions)]
        comp = np.array([r.makespan for r in singles])
        runs = {}
        for j, n in enumerate(rc.sizes):
            if n == 1:
                continue
            for kind, layers in (("standard", 1), ("recursive", rc.recursive_layers)):
                runs[(kind, n)] = simulate(dag, n, _rng(seed, 1, f, b, 3, j), layers=layers,
                                           overheads=ov)
        st = structure_stats(dag)
        tasks.append({
            "task": b, "n_steps": task.n_steps, "n_layers": task.n_layers, "peak": task.peak,
            "merge_p": task.merge_p, "clock": task.clock, "scale": scale,
            "best_score": float(v.max()), "t1_raw": float(comp.mean()),
            "slow_raw": float(comp.max()), "cross_layer_share": st["cross_layer_share"],
            "best_depth_share": st["best_depth_share"], "leaf_share": st["leaf_share"],
            "_singles": [r.finish for r in singles], "_runs": {k: r.finish for k, r in runs.items()},
            "_v": v,
        })
        for k, r in runs.items():
            acct.setdefault(k, []).append((r.schedule / r.work, r.comm / r.work, r.peak_active,
                                           len(r.agent_depth), r.n_handoffs / dag.n))
    shift = max(math.log(t["slow_raw"]) - math.log(t["t1_raw"]) + t["clock"] for t in tasks)
    for t in tasks:
        s = math.exp(t["clock"] - shift) / t["t1_raw"]       # t / T1 per raw time unit
        for fin in t.pop("_singles"):
            base_cov.append(fin * s)
            base_best.append(record_events(fin * s, t["_v"]))
            base_done.append(float(fin.max() * s))
        for k, fin in t.pop("_runs").items():
            swarm_cov.setdefault(k, []).append(fin * s)
            swarm_best.setdefault(k, []).append(record_events(fin * s, t["_v"]))
            swarm_done.setdefault(k, []).append(float(fin.max() * s))
        t.pop("_v")
        t["t1"] = math.exp(t["clock"] - shift)
        t["slow"] = t["slow_raw"] * s

    out: dict[str, Any] = {"family": f, "tasks": tasks, "shift": shift, "stats": {}, "grid": {}}

    def summarize(label: str, cov_runs: list, best_runs: list) -> None:
        cov = coverage_curve(cov_runs)
        best = mean_curve([e[0] for e in best_runs], [e[1] for e in best_runs])
        for name, x in COV_LEVELS.items():
            out["stats"][f"{label}:{name}"] = first_reach(cov, x)
        for name, x in BEST_LEVELS.items():
            out["stats"][f"{label}:{name}"] = first_reach(best, x)
        out["stats"][f"{label}:best_final"] = float(best[1][-1]) if len(best[1]) else 0.0
        out["grid"][label] = on_grid(cov, GRID)

    summarize("single:1", base_cov, base_best)
    for (kind, n), runs in swarm_cov.items():
        summarize(f"{kind}:{n}", runs, swarm_best[(kind, n)])
        out["stats"][f"{kind}:{n}:task_finish_mean"] = float(np.mean(swarm_done[(kind, n)]))
        a = np.array(acct[(kind, n)])
        for col, name in enumerate(("schedule_share", "comm_share", "peak_active", "agents",
                                    "handoffs_per_step")):
            out["stats"][f"{kind}:{n}:{name}"] = float(a[:, col].mean())
    out["stats"]["single:1:task_finish_mean"] = float(np.mean(base_done))
    out["cpu_s"] = time.process_time() - c0
    return out


def _gen_chunk(args: tuple[int, int, int, GenParams]) -> list[dict[str, float]]:
    """Structure statistics of generated DAGs at the language-modelling size (no task variation)."""
    seed, k0, k1, p = args
    return [structure_stats(grow_dag(p.n_steps, p.n_layers, p.peak, p.merge_p, _rng(seed, 0, k), p))
            for k in range(k0, k1)]


# --- aggregation ------------------------------------------------------------------------------

def _summary(x: np.ndarray, rng: np.random.Generator, boot: int,
             idx: np.ndarray | None = None) -> dict[str, Any]:
    """Mean with a bootstrap 95% CI, and the 2.5% to 97.5% range of the values.

    `idx` (boot x len(x) resampling indices) is reused when every value is finite.
    """
    x = np.asarray(x, dtype=float)
    fin = np.isfinite(x)
    if not fin.any():
        return {"mean": math.nan, "ci_low": math.nan, "ci_high": math.nan, "p025": math.nan,
                "p975": math.nan, "median": math.nan, "n": 0, "values": x[fin]}
    if idx is not None and fin.all() and idx.shape[1] == len(x):
        means = x[idx].mean(axis=1)
    else:
        x = x[fin]
        means = x[rng.integers(0, len(x), size=(boot, len(x)))].mean(axis=1)
    return {"mean": float(x.mean()), "ci_low": float(np.quantile(means, 0.025)),
            "ci_high": float(np.quantile(means, 0.975)), "p025": float(np.quantile(x, 0.025)),
            "p975": float(np.quantile(x, 0.975)), "median": float(np.median(x)), "n": len(x),
            "values": x}


def _derived(stats: dict[str, float], sizes: tuple[int, ...]) -> dict[str, float]:
    """Speedups and scaling exponents of one family from its first-reach times."""
    d = dict(stats)
    for kind in KINDS:
        for n in sizes:
            if n == 1:
                continue
            k = f"{kind}:{n}"
            for lvl in ("cov50", "cov90", "best50", "best80"):
                ref, t = stats.get(f"single:1:{lvl}", math.nan), stats.get(f"{k}:{lvl}", math.nan)
                d[f"{k}:g_{lvl}"] = ref / t if t > 0 else math.nan
            d[f"{k}:lambda"] = scaling_exponent(d[f"{k}:g_cov50"], n)
    for n in sizes:
        if n > 1:
            d[f"ratio:{n}:rec_over_std_g50"] = d[f"recursive:{n}:g_cov50"] / d[f"standard:{n}:g_cov50"]
    return d


def _deviation(ours: float, lo: float, hi: float) -> float:
    if not math.isfinite(ours):
        return math.nan
    if lo <= ours <= hi:
        return 0.0
    return min(abs(ours - lo) / abs(lo), abs(ours - hi) / abs(hi))


def _row(check: str, required: bool, blog: str, lo: float, hi: float, s: dict[str, Any],
         note: str = "", unit: str = "family") -> dict[str, Any]:
    dev = _deviation(s["mean"], lo, hi)
    status = "pass" if dev <= TOL else ("fail" if math.isfinite(dev) else "not checked")
    v = s["values"]
    pct = float((v < lo).mean()) if lo == hi and len(v) else math.nan
    return {"check": check, "required": required, "blog": blog, "blog_low": lo, "blog_high": hi,
            "ours": s["mean"], "ci95_low": s["ci_low"], "ci95_high": s["ci_high"],
            "range_p025": s["p025"], "range_p975": s["p975"], "unit": unit, "n": s["n"],
            "blog_percentile": pct, "rel_deviation": dev, "status": status, "note": note}


def _qual(check: str, required: bool, blog: str, ours: float, n: int, ok: bool,
          note: str) -> dict[str, Any]:
    """A qualitative check: `ours` is the share of families where it holds."""
    nan = math.nan
    return {"check": check, "required": required, "blog": blog, "blog_low": nan, "blog_high": nan,
            "blog_percentile": nan, "ours": ours, "ci95_low": nan,
            "ci95_high": nan, "range_p025": nan, "range_p975": nan, "unit": "family", "n": n,
            "rel_deviation": nan, "status": "pass" if ok else "fail", "note": note}


def build_checks(fam: list[dict[str, float]], gen: list[dict[str, float]],
                 tasks: pl.DataFrame, rc: ReproConfig) -> tuple[list[dict[str, Any]], dict]:
    """The reproduction table: SPEC 8.2 checks (required) and other blog numbers (extra)."""
    rng = _rng(rc.seed, 2)
    col = {k: np.array([f[k] for f in fam], dtype=float) for k in fam[0]}
    idx = rng.integers(0, len(fam), size=(rc.boot, len(fam)))

    def S(key: str) -> dict[str, Any]:
        return _summary(col[key], rng, rc.boot, idx)

    def times(lvl: str) -> np.ndarray:
        """Families x sizes first-reach times of the standard swarm (one agent for N = 1)."""
        return np.array([[f[f"single:1:{lvl}"] if n == 1 else f[f"standard:{n}:{lvl}"]
                          for n in rc.sizes] for f in fam], dtype=float)

    rows: list[dict[str, Any]] = []
    big = [n for n in rc.sizes if n > 1]
    # both curves shift earlier as the swarm grows
    for lvls, label, req in ((("cov25", "cov50", "cov75", "cov90"), "coverage", True),
                             (("best50", "best80"), "best score", False)):
        t = np.stack([times(lv) for lv in lvls])                  # levels x families x sizes
        defined = np.all(np.isfinite(t), axis=(0, 2))
        ok = np.all(np.diff(t, axis=2) < 0, axis=(0, 2)) & defined
        pooled = np.nanmean(t[:, defined], axis=1)                # levels x sizes
        mono = bool(np.all(np.diff(pooled, axis=1) < 0))
        rows.append(_qual(
            f"Standard swarm {label} curve shifts earlier at every larger N (N = 1 to 64)", req,
            "earlier as the swarm grows", float(ok[defined].mean()), int(defined.sum()), mono,
            f"levels {', '.join(str(BEST_LEVELS.get(lv, COV_LEVELS.get(lv))) for lv in lvls)}; "
            "ours = share of families where every level is reached strictly sooner at each larger "
            f"N; family-mean times to {lvls[1]}: " + " > ".join(f"{x:.3g}" for x in pooled[1])))
    for n in (32, 64):
        if n in rc.sizes:
            rows.append(_row(f"Standard swarm@{n} finishes every step (t / T1)", True, "about 0.10",
                             0.10, 0.10, S(f"standard:{n}:cov100"),
                             "first time the family-average coverage reaches 1"))
    if 32 in rc.sizes and 64 in rc.sizes:
        r = col["standard:64:cov100"] / col["standard:32:cov100"]
        rows.append(_row("Standard swarm finish time, 64 over 32 agents", True,
                         "about 1 (no sooner)", 1.0, 1.0, _summary(r, rng, rc.boot, idx)))
    if 64 in rc.sizes:
        rows.append(_row("Standard swarm@64 speedup at half coverage, g50", True, "33", 33, 33,
                         S("standard:64:g_cov50")))
        rows.append(_row("Standard swarm@64 speedup at best score 0.8", True, "16", 16, 16,
                         S("standard:64:g_best80"),
                         "families whose average best score never reaches 0.8 are left out"))
    for n in big:
        if 4 <= n <= 64:
            rows.append(_row(f"Recursive swarm@{n}, 3 layers, lambda = ln g50 / ln N", True,
                             "0.88 to 0.93", 0.88, 0.93, S(f"recursive:{n}:lambda")))
    for n in big:
        if 4 <= n <= 16:
            rows.append(_row(f"Standard swarm@{n}, lambda", True, "0.89 to 0.92", 0.89, 0.92,
                             S(f"standard:{n}:lambda")))
    if 64 in rc.sizes:
        rows.append(_row("Standard swarm@64, lambda", True, "0.84", 0.84, 0.84,
                         S("standard:64:lambda")))
    # other numbers the blog reports
    for n, val in ((16, 1.04), (64, 1.2)):
        if n in rc.sizes:
            rows.append(_row(f"Recursive (3 layers) over standard g50 at N = {n}", False, f"{val}",
                             val, val, S(f"ratio:{n}:rec_over_std_g50")))
    for n in (b for b in big if b >= 4):
        g50, gb50 = col[f"standard:{n}:g_cov50"], col[f"standard:{n}:g_best50"]
        ok = np.isfinite(g50) & np.isfinite(gb50)
        rows.append(_qual(f"Standard swarm@{n} speedup at best score 0.5 below g50", False,
                          "smaller from 4 agents on", float((gb50[ok] < g50[ok]).mean()),
                          int(ok.sum()), bool(np.nanmean(gb50) < np.nanmean(g50)),
                          f"ours = share of families; family means {np.nanmean(gb50):.3g} "
                          f"against {np.nanmean(g50):.3g}"))
    gcol = {k: np.array([g[k] for g in gen]) for k in gen[0]}
    gnote = f"{len(gen)} DAGs of 723 steps and 17 layers without task variation"
    rows.append(_row("Generator best recipe depth, language-modelling size", False, "94%", 0.94,
                     0.94, _summary(gcol["best_depth_share"], rng, rc.boot),
                     gnote + "; layer of the best value over the deepest layer", unit="DAG"))
    nan = math.nan
    rows.append({"check": "Generator best recipe depth, diffusion size", "required": False,
                 "blog": "88%", "blog_low": 0.88, "blog_high": 0.88, "blog_percentile": nan,
                 "ours": nan, "ci95_low": nan,
                 "ci95_high": nan, "range_p025": nan, "range_p975": nan, "unit": "DAG", "n": 0,
                 "rel_deviation": nan, "status": "not checked",
                 "note": "the blog does not give the diffusion DAG's size"})
    rows.append(_row("Generator cross-layer edge share", False, "18%", 0.18, 0.18,
                     _summary(gcol["cross_layer_share"], rng, rc.boot),
                     gnote + "; edges spanning 2 or more layers after relayering each step one "
                     "layer below its deepest parent", unit="DAG"))
    rows.append(_row("Generator leaf share (steps without children)", False, "about half", 0.5,
                     0.5, _summary(gcol["leaf_share"], rng, rc.boot), gnote, unit="DAG"))
    best = tasks["best_score"].to_numpy()
    med = float(np.median(best))
    bmed = np.median(best[rng.integers(0, len(best), size=(rc.boot // 4, len(best)))], axis=1)
    dev = _deviation(med, 0.83, 0.83)
    rows.append({"check": "Best recipe of a typical task DAG on the task's scale", "required": False,
                 "blog": "about 0.83", "blog_low": 0.83, "blog_high": 0.83,
                 "blog_percentile": float((best < 0.83).mean()), "ours": med,
                 "ci95_low": float(np.quantile(bmed, 0.025)),
                 "ci95_high": float(np.quantile(bmed, 0.975)),
                 "range_p025": float(np.quantile(best, 0.025)),
                 "range_p975": float(np.quantile(best, 0.975)), "unit": "task", "n": len(best),
                 "rel_deviation": dev, "status": "pass" if dev <= TOL else "fail",
                 "note": "ours = median over task DAGs, CI by bootstrap over tasks"})
    share = tasks.group_by("family").agg((pl.col("best_score") >= 0.95).mean().alias("s"))
    rows.append(_row("Share of task DAGs whose best recipe reaches 0.95", False, "about 1 in 6",
                     1 / 6, 1 / 6, _summary(share["s"].to_numpy(), rng, rc.boot),
                     "ours = mean over families of the share of their tasks"))
    agg: dict[str, Any] = {k: _summary(v, rng, rc.boot, idx) for k, v in col.items()}
    if 64 in rc.sizes:
        g, f64 = col["standard:64:g_cov50"], col["standard:64:cov100"]
        agg["_corr_g50_finish64"] = float(np.corrcoef(g, f64)[0, 1])
        agg["_blog_like_share"] = float(((g >= 32.5) & (f64 >= 0.095)).mean())
    return rows, agg


# --- report -----------------------------------------------------------------------------------

AMBIGUITIES = [
    ("Sources", "The project owner has no code from the author.",
     "Implemented from the blog text (English and Chinese versions) and SPEC appendix B. The blog "
     "page also loads its own simulator (assets/data/edgebench-logsigmoid.js v47 and "
     "assets/swarm-worker.js v31). We read those files as a specification only, never executed "
     "them, and used them to settle the points below where the text is silent."),
    ("Clamps on task draws", "Steps 723 e^{0.4z}, layers 17 e^{0.2z}, peak 0.28 + 0.07z, merge "
     "probability 0.46 e^{0.3z}, no bounds given.",
     "Rounded to integers and clamped as in the blog's code: steps to [10, 1500], layers to [3, 30], "
     "peak to [0.1, 0.9], merge probability to [0, 0.9]. The steps clamp binds when z > 1.82, "
     "about 3.4% of tasks (our share is under Generator statistics)."),
    ("Layer-size rounding", "Layer d gets the logistic rise across that layer times noise.",
     "Layer 0 holds the root, the other n - 1 steps are split by the noisy rises and rounded; the "
     "rounding residue is added to or taken from the fullest layer (blog code)."),
    ("Main parent layer", "Drawn from the layer above.",
     "From the previous non-empty layer (identical unless noise empties a layer)."),
    ("Sibling", "An extra parent is a sibling of the main parent with probability 0.2.",
     "A sibling is another main child of the main parent's main parent, drawn with the same "
     "softmax weights; when the main parent has no sibling the layer route is taken (blog code)."),
    ("Layer b of an extra parent", "P(b) proportional to 0.8^b as far as the root.",
     "b starts at 1 (the main parent's layer) and moves up one more layer with probability 0.8, "
     "stopping at the root. The root and any ancestor of a chosen parent are skipped as candidates; "
     "a skipped or empty-layer draw uses up one of at most 8K tries, so a step can end with fewer "
     "than K extra parents (blog code)."),
    ("Improvement delta", "delta is a parent's own improvement over what it built on.",
     "delta = the step's change, its value minus its best parent's value (root 0)."),
    ("Score scale", "90th percentile of the best recipes of 64 DAGs grown like the task's.",
     "64 DAGs with the task's steps, layers, peak and merge probability, each with its own layer "
     "noise and fertility; the value at sorted index round(0.9 x 63) = 57 is worth 1. Values below "
     "the root's 0 count as 0."),
    ("Clock and T1", "Each task's clock is stretched by e^{delta_b}; T1 is how long the slowest "
     "single-agent run takes to finish every step.",
     "Each task's raw times are divided by the mean time of its 16 single-agent runs to finish "
     "every step and multiplied by e^{delta_b}; then all times of the family are divided by the "
     "slowest of its 256 single-agent runs, so that run ends at exactly 1 (blog code)."),
    ("Averaging and speedup", "g_x is how many times sooner a swarm reaches level x than one agent.",
     "Scores are averaged over the family's tasks first (one agent over all 16 runs per task, a "
     "swarm over one run per task); g_x is the ratio of the first times the two averages reach x "
     "(blog code). We use exact step functions where the blog evaluates one agent on a grid of "
     "about 0.7% in log time."),
    ("Finish time", "It finishes every step at about 0.10 T1.",
     "The first time the family-average coverage reaches 1, i.e. the latest task finish. The mean "
     "over tasks is in swarmsim_scaling.csv (task_finish_mean)."),
    ("Scheduling overhead", "5% of a median step whenever an agent starts or builds on another "
     "agent's work.",
     "The median step is the median layer cost c_d over steps (no time noise). A new agent pays 5% "
     "on its first step, and any step with a parent finished by another agent pays 5%, so the first "
     "step of a dispatched or forked agent pays 10% (blog code adds both). One agent on its own pays "
     "nothing."),
    ("Communication cost", "+15% per step while two group members are active, +1% per further "
     "active member.",
     "Charged as a share of the step's work (time noise included), from the group sizes when the "
     "step starts, after all starts and stops of that instant, and fixed for the whole step. Alive "
     "agents count as active; an agent is never idle while alive (blog code)."),
    ("Who holds a ready step", "The running agent that made that step ready holds it.",
     "The agent that finished its last parent puts it on its list; it also joins the list of every "
     "other alive agent that finished one of its parents. A free slot draws uniformly among all "
     "ready, unstarted steps."),
    ("Standard swarm refill", "An agent that empties its list stops and the coordinator starts a "
     "new agent on a random ready step.",
     "The coordinator fills every free slot whenever ready steps wait, also while the swarm is "
     "first growing ('no budget sits idle while ready steps wait')."),
    ("Recursive forks", "Keep one new step, fork sub-agents for the rest within budget, up to the "
     "layer cap.",
     "The opened steps are shuffled; the agent keeps the first and forks for the others while "
     "fewer than N agents are alive and its own layer is below the cap. A free slot drawn to a "
     "step whose holder sits at the cap goes to the coordinator, which starts a new layer-1 agent. "
     "Standard and recursive runs of one task and size share a random stream (blog code)."),
    ("pass@k", "k agents that each follow the rule on their own.",
     "k independent single-agent runs; `pass_at_k` takes one DAG per part (the arena gives each "
     "part a DAG of its own) and the best score is the best over parts. Not part of the SPEC 8.2 "
     "checks."),
    ("Diffusion-size depth check", "88% at the diffusion DAG's size.",
     "Not checked; the blog does not give that DAG's steps or layers."),
]


def _fmt(x: Any, nd: int = 3) -> str:
    if isinstance(x, (bool, np.bool_)):
        return "yes" if x else "no"
    if isinstance(x, (int, np.integer)):
        return str(x)
    if isinstance(x, float) and not math.isfinite(x):
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}g}"
    return str(x)


def _md_table(header: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def write_qa(path: Path, rows: list[dict[str, Any]], scaling: pl.DataFrame, agg: dict,
             gen: list[dict[str, float]], tasks: pl.DataFrame, rc: ReproConfig, runtime: dict,
             outputs: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    req = [r for r in rows if r["required"]]
    n_fail = sum(r["status"] == "fail" for r in req)

    def ci(key: str) -> str:
        s = agg.get(key)
        return f"{s['mean']:.3g} (95% CI {s['ci_low']:.3g} to {s['ci_high']:.3g})" if s else "n/a"

    lam = {k: [agg[f"{k}:{n}:lambda"]["mean"] for n in rc.sizes if n >= 4 and f"{k}:{n}:lambda" in agg]
           for k in KINDS}
    head = []
    if 64 in rc.sizes and 32 in rc.sizes:
        head = [
            f"- Standard swarm@64: g50 = {ci('standard:64:g_cov50')} (blog 33); speedup at best "
            f"score 0.8 = {ci('standard:64:g_best80')} (blog 16); finishes every step at "
            f"{ci('standard:64:cov100')} T1, and at {ci('standard:32:cov100')} T1 with 32 agents "
            "(blog about 0.10 for both).",
            f"- lambda = ln g50 / ln N for N = 4 to 64: recursive swarm (3 layers) "
            f"{min(lam['recursive']):.3f} to {max(lam['recursive']):.3f} (blog 0.88 to 0.93); standard "
            f"swarm {', '.join(f'{x:.3f}' for x in lam['standard'])} (blog 0.89 to 0.92 for N = 4 to "
            "16, 0.84 at 64).",
        ]
    lines = [
        "# QA: swarm simulator reproduction (module D1)",
        "",
        f"Source: {SOURCE}. Re-implemented without the author's code (SPEC 8.1, 8.2, appendix B).",
        "",
        "## Summary",
        "",
        f"- Families simulated: {rc.families} of {rc.tasks} tasks each ({rc.families * rc.tasks} "
        f"task DAGs, {rc.families * rc.tasks * rc.sessions} single-agent runs, "
        f"{rc.families * rc.tasks * 2 * (len(rc.sizes) - 1)} swarm runs). Seed {rc.seed}.",
        f"- Required SPEC 8.2 checks: {len(req) - n_fail} of {len(req)} within the 20% tolerance.",
        *head,
        f"- Runtime: {runtime['wall_s']:.0f} s wall on {runtime['workers']} processes "
        f"({runtime['host']}), {runtime['cpu_s']:.0f} s of simulation CPU time.",
        "- No parameter was tuned to the blog's numbers; every parameter value is the blog's.",
        "",
        "## What is implemented",
        "",
        "- `avsd.swarmsim.dag`: the generator (`grow_dag`, `layer_sizes`, `draw_task`, `task_dag`), "
        "the task score scale (`score_scale`, `scores`) and structure statistics "
        "(`structure_stats`, `relayer`).",
        "- `avsd.swarmsim.sim`: readiness, the deepest-first step rule, one agent "
        "(`single_agent`), the standard swarm (`simulate(..., layers=1)`), the recursive swarm "
        "(`simulate(..., layers=L)`), pass@k (`pass_at_k`), scheduling overhead and communication "
        "cost (`Overheads`, `comm_factor`), best-score events (`record_events`).",
        "- `avsd.swarmsim.metrics`: averaged coverage and best-score curves, first-reach times, "
        "speedup g_x and lambda = ln g50 / ln N.",
        "- `avsd.swarmsim.reproduce`: the family protocol, the checks, outputs and this report. "
        "`avsd.swarmsim.run_reproduction(cfg)` runs everything.",
        "",
        "## Ambiguities and how we resolved them",
        "",
    ]
    for topic, blog, res in AMBIGUITIES:
        lines.append(f"- **{topic}.** Blog: {blog} Ours: {res}")
    lines += [
        "",
        "## SPEC appendix B against the blog",
        "",
        "Appendix B agrees with the blog text on every parameter and rule it states; we found no "
        "contradiction. It leaves out details the blog gives, which we take from the blog: the "
        "running agent that made a step ready holds it, a merge step can sit on several lists, and "
        "a sub-agent's group is its forker and the forker's other sub-agents. 'Each figure runs 16 "
        "tasks' (appendix B: 16 tasks per figure) means 16 tasks, each with its own DAG, per family; "
        "a family is the unit behind one figure and behind T1.",
        "",
        "## Reproduction table",
        "",
        "`Ours` is the mean over units (families, unless the range column names DAGs or tasks) "
        "with a bootstrap 95% CI of that mean. `Range` is the 2.5% to 97.5% range of single "
        "units; for families it is the spread expected for one 16-task family like the blog's. "
        "`Blog pctl` is the share of single units below the blog's value, i.e. where the "
        "blog's single family would sit among ours. "
        "For qualitative checks `Ours` is the share of families where the statement holds, and the "
        "status is set by the family means. Deviation is relative to the blog value, or to the "
        "nearest end of a blog range (0 inside it). Pass means a deviation of at most 20%.",
        "",
        _md_table(["Check", "Required", "Blog", "Ours", "95% CI", "Range", "n", "Blog pctl",
                   "Deviation", "Status"],
                  [[r["check"], r["required"], r["blog"], r["ours"],
                    "" if not math.isfinite(r["ci95_low"])
                    else f"{r['ci95_low']:.3g} to {r['ci95_high']:.3g}",
                    "" if not math.isfinite(r["range_p025"])
                    else f"{r['range_p025']:.3g} to {r['range_p975']:.3g} ({r['unit']})",
                    r["n"], "" if not math.isfinite(r["blog_percentile"])
                    else f"{r['blog_percentile']:.0%}", r["rel_deviation"], r["status"]]
                   for r in rows]),
        "",
        "Notes: " + " ".join(f"{r['check']}: {r['note']}." for r in rows if r["note"]),
        "",
        "## Scaling by swarm size",
        "",
        "Means over families (95% CI in swarmsim_scaling.csv). Times in T1.",
        "",
    ]
    show = scaling.filter(pl.col("n") > 1).sort(["kind", "n"])
    lines.append(_md_table(
        ["Kind", "N", "t50", "t at 0.8 best", "Finish", "g50", "g90", "g at 0.8 best", "lambda",
         "Scheduling share", "Comm share"],
        [[r["kind"], r["n"], r["cov50"], r["best80"], r["cov100"], r["g_cov50"], r["g_cov90"],
          r["g_best80"], r["lambda"], r["schedule_share"], r["comm_share"]]
         for r in show.iter_rows(named=True)]))
    base = scaling.filter(pl.col("n") == 1).row(0, named=True)
    lines += [
        "",
        f"One agent: t50 = {base['cov50']:.3g}, t at best 0.8 = {base['best80']:.3g}, mean task "
        f"finish = {agg['single:1:task_finish_mean']['mean']:.3g} T1. Scheduling and comm shares "
        "are paid time over work time, averaged over runs.",
        "",
        "## Generator statistics",
        "",
    ]
    gk = ["best_depth_share", "cross_layer_share", "leaf_share", "multi_parent_share",
          "mean_parents", "sibling_merge_share", "outdeg_gini", "top10_child_share",
          "peak_layer_share"]
    lines.append(f"{len(gen)} DAGs of 723 steps and 17 layers (no task variation), mean and 2.5% "
                 "to 97.5% range over DAGs. The blog reports only the first two (94%, 18%); the "
                 "others are the fitted shape statistics it names without values.")
    lines.append("")
    lines.append(_md_table(["Statistic", "Mean", "Range"],
                           [[k, float(np.mean([g[k] for g in gen])),
                             f"{np.nanquantile([g[k] for g in gen], 0.025):.3g} to "
                             f"{np.nanquantile([g[k] for g in gen], 0.975):.3g}"] for k in gk]))
    lines += [
        "",
        f"Task DAGs ({tasks.height}, with task variation): steps {tasks['n_steps'].mean():.0f} on "
        f"average, layers {tasks['n_layers'].mean():.1f}, cross-layer share "
        f"{tasks['cross_layer_share'].mean():.3f}, best-recipe depth {tasks['best_depth_share'].mean():.3f}, "
        f"leaf share {tasks['leaf_share'].mean():.3f}; steps clamped at 1500 in "
        f"{(tasks['n_steps'] == 1500).mean():.1%} of tasks.",
        "",
        "## Deviations",
        "",
    ]
    bad = [r for r in rows if r["status"] == "fail"]
    near = [r for r in rows if r["status"] == "pass" and r["rel_deviation"] > 0.10]
    lines.append("No check exceeds the 20% tolerance, so nothing goes to docs/decisions.md under "
                 "SPEC 8.2." if not bad else f"{len(bad)} checks exceed the 20% tolerance:")
    for r in bad + near:
        inside = r["range_p025"] <= r["blog_low"] and r["blog_high"] <= r["range_p975"]
        lines.append(f"- {r['check']}: blog {r['blog']}, ours {r['ours']:.3g} "
                     f"(deviation {r['rel_deviation']:.0%}, {r['status']})"
                     + (f"; the blog's value lies inside our {r['unit']} range "
                        f"{r['range_p025']:.3g} to {r['range_p975']:.3g}, so one 16-task family "
                        "like the blog's can show it" if inside and r["unit"] == "family" else "")
                     + ".")
    odd = [r for r in rows if math.isfinite(r["blog_percentile"])
           and not 0.05 <= r["blog_percentile"] <= 0.95]
    if odd:
        lines += ["", "Blog values outside the 5% to 95% band of our single-unit distribution:"]
        plural = {"family": "families", "DAG": "DAGs", "task": "tasks"}
        lines += [f"- {r['check']}: blog {r['blog']} sits at the {r['blog_percentile']:.1%} "
                  f"point of our {plural[r['unit']]} (range {r['range_p025']:.3g} to "
                  f"{r['range_p975']:.3g})." for r in odd]
        lines.append("The blog states the 64-agent ratio of recursive to standard g50 with one "
                     "decimal (1.2) and the 16-agent ratio with two (1.04).")
    point = [r for r in rows if r["required"] and math.isfinite(r["blog_percentile"])]
    if point and "_corr_g50_finish64" in agg:
        lines += [
            "",
            "Where the blog's single family sits among ours: "
            + "; ".join(f"{r['check']} at {r['blog_percentile']:.0%}" for r in point) + ". "
            f"Within a family, g50 and the finish time at 64 agents are negatively correlated "
            f"(r = {agg['_corr_g50_finish64']:.2f}), and {agg['_blog_like_share']:.1%} of our "
            "families have both g50 of at least 32.5 and a finish time of at least 0.095 (the "
            "values that round to the blog's 33 and 0.10). The blog gives the finish time only as "
            "'about 0.10', read off figures whose time axis is linear from 0 to 1 T1. Cause "
            "unidentified; no parameter was changed in response.",
        ]
    lines += [
        "",
        "## Figure",
        "",
        f"`{outputs['figure']}`: average coverage against time in units of T1 (log axis) over "
        f"{rc.families * rc.tasks} tasks, each family on its own T1. Panel a is the standard "
        f"swarm, panel b the recursive swarm with {rc.recursive_layers} layers; the dashed line is "
        "one agent and darker lines are larger swarms (4, 16, 32, 64 agents). The dotted line marks "
        "half coverage, where g50 is read.",
        "",
        "## Outputs and command",
        "",
        *[f"- `{v}`" for v in outputs.values()],
        "",
        "Command: `python scripts/swarmsim_reproduce.py` (Slurm: `sbatch "
        "scripts/swarmsim_reproduce.sbatch`). Library: "
        "`avsd.swarmsim.run_reproduction(load_config())`.",
        f"Python {platform.python_version()}, numpy {np.__version__}.",
        "",
    ]
    path.write_text("\n".join(lines))


def _scaling_table(agg: dict, rc: ReproConfig) -> pl.DataFrame:
    recs = []
    metrics = ["cov50", "cov90", "cov100", "best50", "best80", "best_final", "task_finish_mean",
               "g_cov50", "g_cov90", "g_best50", "g_best80", "lambda", "schedule_share",
               "comm_share", "peak_active", "agents", "handoffs_per_step"]
    for kind in ("single",) + KINDS:
        for n in rc.sizes:
            if (kind == "single") != (n == 1):
                continue
            rec: dict[str, Any] = {"kind": kind, "n": n}
            for m in metrics:
                s = agg.get(f"{kind}:{n}:{m}")
                rec[m] = s["mean"] if s else math.nan
                rec[f"{m}_ci_low"] = s["ci_low"] if s else math.nan
                rec[f"{m}_ci_high"] = s["ci_high"] if s else math.nan
                rec[f"{m}_n"] = s["n"] if s else 0
            recs.append(rec)
    return pl.DataFrame(recs)


# --- entry point ------------------------------------------------------------------------------

def run_reproduction(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run the D1 reproduction and write its outputs. `cfg` is the loaded project config.

    Optional overrides under `cfg["swarmsim"]`: families, tasks, sessions, sizes,
    recursive_layers, gen_dags, workers, boot.
    """
    t0, c0 = time.time(), time.process_time()
    rc = ReproConfig.from_cfg(cfg)
    p, ov = BLOG, BLOG_OVERHEADS
    workers = rc.workers or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) or (os.cpu_count() or 1)
    chunks = [(rc.seed, k, min(k + 64, rc.gen_dags), p) for k in range(0, rc.gen_dags, 64)]
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
        fam_res = list(ex.map(_family, [(f, rc, p, ov) for f in range(rc.families)]))
        gen = [s for chunk in ex.map(_gen_chunk, chunks) for s in chunk]
    sim_wall = time.time() - t0

    fam_stats = [_derived(r["stats"], rc.sizes) for r in fam_res]
    tasks = pl.DataFrame([{**t, "family": r["family"]} for r in fam_res for t in r["tasks"]])
    rows, agg = build_checks(fam_stats, gen, tasks, rc)
    scaling = _scaling_table(agg, rc)

    out = cfg["paths"]["outputs"]
    paths = {
        "reproduction": out / "tables" / "swarmsim_reproduction.csv",
        "scaling": out / "tables" / "swarmsim_scaling.csv",
        "figure": out / "figures" / "swarmsim_coverage.pdf",
        "qa": out / "qa" / "swarmsim_d1.md",
        "family_stats": cfg["paths"]["interim"] / "swarmsim_family_stats.parquet",
    }
    for pth in paths.values():
        pth.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([{c: r[c] for c in CHECK_COLUMNS} for r in rows]) \
        .write_csv(paths["reproduction"], float_precision=4)
    scaling.write_csv(paths["scaling"], float_precision=5)
    pl.DataFrame(fam_stats).with_columns(family=pl.Series([r["family"] for r in fam_res])) \
        .write_parquet(paths["family_stats"])
    curves = {}
    for kind in KINDS:
        for n in FIG_SIZES:
            if n in rc.sizes:
                curves[(kind, n)] = np.mean([r["grid"][f"{kind}:{n}"] for r in fam_res], axis=0)
    single = np.mean([r["grid"]["single:1"] for r in fam_res], axis=0)
    figs = plot_coverage(GRID, single, curves, paths["figure"].with_suffix(""), rc.recursive_layers)
    runtime = {"wall_s": time.time() - t0, "sim_wall_s": sim_wall, "workers": workers,
               "host": platform.node(), "cpu_s": float(sum(r["cpu_s"] for r in fam_res)),
               "main_cpu_s": time.process_time() - c0}
    def rel(pth: Path) -> str:
        return str(pth.relative_to(REPO_ROOT)) if pth.is_relative_to(REPO_ROOT) else str(pth)

    outputs = {k: rel(v) for k, v in paths.items()} | {"figure_png": rel(figs[1])}
    write_qa(paths["qa"], rows, scaling, agg, gen, tasks, rc, runtime, outputs)
    return {"checks": rows, "scaling": scaling, "outputs": outputs, "runtime": runtime,
            "config": asdict(rc), "n_failed_required": sum(r["status"] == "fail" for r in rows
                                                          if r["required"])}
