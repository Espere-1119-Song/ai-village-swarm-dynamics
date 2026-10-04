"""Robustness of the D3 and D4 results to the GUI focus gap (owner's request, 2026-10-01).

GUI writes without a focus are actions the dependency graph cannot see. If they bias the results, the
results should move on goals where the gap is small. Per goal we measure, under the main touch rules:

- `gap`: unattributed GUI writes over all write actions, i.e. U / (U + W), where U counts GUI writes
  without a focus and W counts turns with at least one write touch on an artifact;
- `touch_share`: the share of the goal's sessions that touch an artifact.

`goal_subsets` defines the subsets compared with the full result: goals with gap below 20% and below
10%, goals where at least 80% of sessions touch an artifact, goals starting from 2025-10 (after the
agents moved from GUI terminals to the bash tool), and all goals except GUI-heavy early ones (goals
before 2025-10 whose gap is at least 80%, i.e. at least four unattributed GUI writes per attributed write
action; every goal before 2025-10 has a gap of at least 71%, so a 50% cut would equal the 2025-10 subset). `robustness_rows` recomputes, on each subset, the pooled D3
statistics with their generator quantiles (the generator pools the same goals' DAGs), the within-goal
slope of step cost on relative depth, and the D4 continuation rates with their baselines (pairs whose
next session belongs to the subset). `conclusion_checks` states for each subset whether each headline
conclusion holds.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from avsd.swarmsim.continuation import summarize
from avsd.swarmsim.depgraph import STAT_NAMES, GraphParts, quantile_of, stats_from_parts

GAP_THRESHOLDS = (0.20, 0.10)
TOUCH_MIN = 0.80
FROM_DATE = date(2025, 10, 1)
HEAVY_GAP = 0.80


def goal_coverage(sessions: pl.DataFrame, goals: pl.DataFrame, tk: pl.DataFrame, gui: pl.DataFrame,
                  touched: Sequence[int]) -> pl.DataFrame:
    """Per goal: sessions, touching sessions, unattributed GUI writes, write turns, gap, touch share.

    `sessions` has s, session_id, goal_id; `tk` the keyed touches (s, turn_id, mode); `gui` one row per
    session with gui_writes_unattributed; `touched` the session ints that touch an artifact.
    """
    ses = sessions.select("s", "session_id", "goal_id").filter(pl.col("goal_id").is_not_null())
    w = (tk.filter(pl.col("mode") == "write").group_by("s").agg(pl.col("turn_id").n_unique().alias("write_turns")))
    u = gui.select("session_id", pl.col("gui_writes_unattributed").alias("unattributed_gui"))
    t = pl.DataFrame({"s": list(touched)}, schema={"s": pl.Int64}).with_columns(pl.lit(True).alias("touches"))
    per = (ses.join(w, on="s", how="left").join(u, on="session_id", how="left").join(t, on="s", how="left")
           .with_columns(pl.col("write_turns").fill_null(0), pl.col("unattributed_gui").fill_null(0),
                         pl.col("touches").fill_null(False)))
    cov = (per.group_by("goal_id").agg(pl.len().alias("sessions"), pl.col("touches").sum().alias("touching_sessions"),
                                       pl.col("unattributed_gui").sum(), pl.col("write_turns").sum())
           .join(goals.select(pl.col("id").alias("goal_id"), pl.col("start_time").dt.date().alias("start")),
                 on="goal_id", how="left")
           .with_columns((pl.col("unattributed_gui") / (pl.col("unattributed_gui") + pl.col("write_turns")))
                         .fill_nan(None).alias("gap"),
                         (pl.col("touching_sessions") / pl.col("sessions")).alias("touch_share"))
           .sort("start"))
    return cov


def goal_subsets(cov: pl.DataFrame) -> dict[str, tuple[str, list[str]]]:
    """Subset name -> (definition, goal ids). `cov` comes from goal_coverage."""
    def ids(expr: pl.Expr) -> list[str]:
        return cov.filter(expr)["goal_id"].to_list()

    gap = pl.col("gap").fill_null(1.0)
    out = {"full": ("all goals", ids(pl.lit(True)))}
    for th in GAP_THRESHOLDS:
        out[f"gap < {int(100 * th)}%"] = (f"goals whose unattributed GUI writes are under {int(100 * th)}% of "
                                          "write actions", ids(gap < th))
    out[f"touch share >= {int(100 * TOUCH_MIN)}%"] = (f"goals where at least {int(100 * TOUCH_MIN)}% of sessions "
                                                      "touch an artifact", ids(pl.col("touch_share") >= TOUCH_MIN))
    out["from 2025-10"] = ("goals starting on or after 2025-10-01", ids(pl.col("start") >= FROM_DATE))
    out["no GUI-heavy early goals"] = (f"all goals except those before 2025-10 with a gap of at least "
                                       f"{int(100 * HEAVY_GAP)}%",
                                       ids(~((pl.col("start") < FROM_DATE) & (gap >= HEAVY_GAP))))
    return out


def robustness_rows(subsets: dict[str, tuple[str, list[str]]], parts: dict[tuple[str, str], GraphParts],
                    gen0: dict[int, list[GraphParts]], goal_ids: Sequence[str], n_sessions: dict[str, int],
                    layers: pl.DataFrame, pairs: dict[str, pl.DataFrame], rng: np.random.Generator, boot: int,
                    reps: int) -> list[dict[str, Any]]:
    """D3 pooled statistics, step-cost slopes and D4 rates for every subset (long format)."""
    from avsd.swarmsim.calibrate import cost_slopes

    gi = {g: i for i, g in enumerate(goal_ids)}
    rows: list[dict[str, Any]] = []
    for name, (definition, goals) in subsets.items():
        goals = [g for g in goals if g in gi]
        base = {"subset": name, "definition": definition, "n_goals": len(goals),
                "n_sessions": int(sum(n_sessions.get(g, 0) for g in goals))}
        if not goals:
            continue
        gen_stats = [stats_from_parts([gen0[gi[g]][r] for g in goals]) for r in range(reps)]
        for lab in ("all", "write"):
            obs = stats_from_parts([parts[(g, lab)] for g in goals])
            for st in STAT_NAMES:
                gv = np.array([x[st] for x in gen_stats])
                gv = gv[np.isfinite(gv)]
                rows.append({**base, "analysis": "D3", "edges": lab, "statistic": st, "window": "",
                             "value": obs[st], "gen_mean": float(gv.mean()) if len(gv) else math.nan,
                             "gen_p025": float(np.quantile(gv, 0.025)) if len(gv) else math.nan,
                             "gen_p975": float(np.quantile(gv, 0.975)) if len(gv) else math.nan,
                             "quantile": quantile_of(obs[st], gv), "n": int(obs["n_child_nodes"])})
        for cost, v in cost_slopes(layers, goals, rng, boot, "all").items():
            rows.append({**base, "analysis": "step cost", "edges": "all", "statistic": f"slope of {cost}",
                         "window": "", "value": v["slope"], "ci_low": v["ci_low"], "ci_high": v["ci_high"],
                         "n": v["n_sessions"]})
        for variant, pr in pairs.items():
            sub = pr.filter(pl.col("goal_id").is_in(goals))
            if sub.is_empty():
                continue
            for r in summarize(sub, variant, rng, boot):
                if r["stratum"] != "all" or r["measure"] == "own_work":
                    continue
                rows.append({**base, "analysis": "D4", "edges": variant, "statistic": r["measure"],
                             "window": r["window"], "value": r["rate"], "ci_low": r["rate_ci_low"],
                             "ci_high": r["rate_ci_high"], "baseline": r["baseline"],
                             "baseline_ci_low": r["baseline_ci_low"], "baseline_ci_high": r["baseline_ci_high"],
                             "n": r["n_pairs"], "n_agents": r["n_agents"]})
    return rows


CONCLUSIONS = (
    "more parents per step than the generator",
    "more layer-skipping edges than the generator",
    "a more even spread of children than the generator",
    "step cost does not grow with depth as the blog assumes",
    "continuation far above chance",
)


def conclusion_checks(rob: pl.DataFrame) -> pl.DataFrame:
    """For each subset and headline conclusion: holds or not, and the numbers behind it (all edges)."""
    out = []
    for name in rob["subset"].unique(maintain_order=True).to_list():
        r = rob.filter(pl.col("subset") == name)

        def d3(st: str) -> dict:
            x = r.filter((pl.col("analysis") == "D3") & (pl.col("edges") == "all") & (pl.col("statistic") == st))
            return x.row(0, named=True) if x.height else {"value": math.nan, "quantile": math.nan}

        def cost(c: str) -> dict:
            x = r.filter((pl.col("analysis") == "step cost") & (pl.col("statistic") == f"slope of {c}"))
            return x.row(0, named=True) if x.height else {"value": math.nan, "ci_low": math.nan, "ci_high": math.nan}

        def d4(window: str) -> dict:
            x = r.filter((pl.col("analysis") == "D4") & (pl.col("edges") == "all")
                         & (pl.col("statistic") == "with_parents") & (pl.col("window") == window))
            return x.row(0, named=True) if x.height else {}

        mp, mm = d3("mean_parents"), d3("multi_parent_share")
        cl = d3("cross_layer_share")
        gn, tp = d3("outdeg_gini"), d3("top10_child_share")
        ct, ca = cost("turns"), cost("active_min")
        cg, cd = d4("goal"), d4("day")
        q = lambda x: x.get("quantile", math.nan)  # noqa: E731
        checks = [
            (CONCLUSIONS[0], q(mp) >= 0.975 and q(mm) >= 0.975,
             f"mean parents {mp['value']:.3g} (quantile {q(mp):.3g}); steps with 2+ parents {mm['value']:.3g} "
             f"(quantile {q(mm):.3g})"),
            (CONCLUSIONS[1], q(cl) >= 0.975, f"edges skipping 2+ layers {cl['value']:.3g} (quantile {q(cl):.3g})"),
            (CONCLUSIONS[2], q(gn) <= 0.025 and q(tp) <= 0.025,
             f"out-degree Gini {gn['value']:.3g} (quantile {q(gn):.3g}); top-10% share {tp['value']:.3g} "
             f"(quantile {q(tp):.3g})"),
            (CONCLUSIONS[3], (ct.get("ci_high", math.nan) < 1) and (ca.get("ci_high", math.nan) < 1),
             f"slope of turns {ct['value']:.3g} [{ct['ci_low']:.3g}, {ct['ci_high']:.3g}], of active minutes "
             f"{ca['value']:.3g} [{ca['ci_low']:.3g}, {ca['ci_high']:.3g}] (blog: 9)"),
            (CONCLUSIONS[4], bool(cg) and bool(cd) and cg["ci_low"] > cg["baseline_ci_high"]
             and cd["ci_low"] > cd["baseline_ci_high"],
             (f"rate {cg['value']:.3g} [{cg['ci_low']:.3g}, {cg['ci_high']:.3g}] against {cg['baseline']:.3g} "
              f"(goal) and {cd['baseline']:.3g} (run day), {cg['n']:,} pairs" if cg else "no pairs")),
        ]
        for conclusion, holds, detail in checks:
            out.append({"subset": name, "conclusion": conclusion, "holds": bool(holds), "detail": detail})
    return pl.DataFrame(out)
