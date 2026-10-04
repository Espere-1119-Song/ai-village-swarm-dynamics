"""outputs/qa/hawkes.md: the QA report of module A on the real data (SPEC 0.6, 5.6, 5.7).

Aggregates and agent names only; humans appear only as the source "human". Every number is computed
from the stage results and output tables of the run.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import polars as pl

from avsd.hawkes import pipeline as P
from avsd.hawkes.matched import ARMS

CLASSES = ("self", "other", "human", "system")


def _f(x, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    return "n/a" if not np.isfinite(x) else f"{x:.{nd}f}"


def _ci(v, lo, hi, nd: int = 3) -> str:
    return f"{_f(v, nd)} [{_f(lo, nd)}, {_f(hi, nd)}]"


def _table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _yes(b) -> str:
    return "yes" if b else "no"


def _sum(df: pl.DataFrame | None, col: str) -> int:
    return int(df[col].fill_null(0).sum()) if df is not None and col in df.columns else 0


def render(cfg: dict, res: dict, runtime: list[str]) -> str:
    h = cfg.get("hawkes", {})
    win: pl.DataFrame | None = res.get("windows")
    lines = [
        "# QA: module A, multivariate Hawkes process on the real data",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `avsd hawkes fit` "
        "(avsd.hawkes.pipeline, avsd.hawkes.report). Data: AI Digest, \"AI Village dataset\", 2026, "
        "https://theaidigest.org/village. Only aggregates and agent names appear here; human messages are the "
        "source `human`.",
        "",
        "## 1. Settings",
        "",
        f"- Model: kernel_sharing `class` (self, other agents, human, system), betas {h.get('betas_per_s')} per s "
        f"(1 min, 10 min, 1 h), L = {h.get('max_lag_hours')} h, {h.get('baseline_hour_bins')} hourly baseline bins, "
        "l1 = 0, three starts (uniform, global, cell), Newton-certified stopping (docs/decisions.md).",
        "- Events: agent messages in the group's room are the dimensions; human messages (run markers typed by "
        "staff included) and auto-nudger nudges are the exogenous sources `human` and `system`; bot run markers "
        "are left out. Each run_periods block is one realization with t = 0 at its start; same-date exogenous "
        "messages before the start sit at t = 0. G = 30 min.",
        "- Presence: an agent is present in a realization when it has an agent row inside the block while in the "
        "group's room (roster_daily.active refined to the block and the room). Its baseline and the kernel "
        "compensator of its row count only over the realizations it is present; on the others it has no events "
        "and no children, in the fits, the simulations and the time-rescaling check alike.",
        f"- Windows: village goals; groups are rooms with more than 10% of a window's agent messages; a goal "
        f"window with fewer than {h.get('min_agent_msgs_per_window', 500)} agent messages in its room is merged "
        "with its adjacent window that has fewer messages (smallest first, earlier on ties); windows that fail "
        f"the recovery check (mean mae4 >= {P.BAR:g} over {P.N_REC} replicates, {P.N_REC + P.N_REC_EXTRA} when the "
        f"mean is within {P.BORDER_SE:g} standard errors of the bar) are merged by the same rule, one round at a "
        "time. Rolling windows are blocks of 5 run days from run day 1 and are never merged.",
        f"- Seed {cfg.get('seed')}; bootstrap {P.N_BOOT} replicates per goal window that draw run dates with "
        "replacement (both blocks of a date with an extra block go together). Each replicate is fitted from the "
        "three starts and from the full-data fit, and keeps the highest objective (the point estimator plus the "
        "full-data optimum as a fourth start).",
        "",
    ]
    if win is None or win.is_empty():
        lines += ["Goal windows have not been fitted yet.", ""]
    else:
        lines += _coverage_section(res.get("coverage"), win)
        lines += _acceptance(res, win)
        lines += _windows_section(win, res.get("decomposition"))
        lines += _part_time_section(res.get("part_time"))
        lines += _identification(win, res.get("sens"))
    if res.get("rolling"):
        lines += _rolling_section(res["rolling"]["table"])
    if win is not None and not win.is_empty():
        lines += _gof_section(res.get("gof"))
        lines += _refs_section(res)
        lines += _opp_section(res.get("opp"))
        lines += _sens_section(res.get("sens"))
        lines += _blocks_section(res.get("blocks"))
        lines += _matched_section(res.get("matched"))
    if res.get("figure_windows"):
        k, n = res["figure_windows"]
        lines += [f"F1 and F2 show the {k} of {n} final goal windows that passed the recovery check; F1 wraps the "
                  "panels into rows of nine.", ""]
    lines += ["## 13. Outputs and runtime", ""]
    lines += [f"- `{p}`" for p in sorted({str(x).split('/outputs/')[-1] if '/outputs/' in str(x) else str(x)
                                          for x in res.get("files", [])})]
    if res.get("n_parents") is not None:
        lines += [f"- `data/processed/hawkes_parents.parquet` (private): {res['n_parents']:,} rows with prob >= 0.01 "
                  f"for {res['n_parent_events']:,} agent events."]
    lines += ["", "Stage runtimes (wall clock, seconds):", ""] + [f"- {r}" for r in runtime] + [""]
    return "\n".join(lines) + "\n"


def _coverage_section(cov: dict | None, win: pl.DataFrame) -> list[str]:
    out = ["## 2. Inputs and coverage (SPEC 0.6)", ""]
    if not cov:
        return out + ["Not available.", ""]
    out += [f"Agent messages: {cov['agent_total']:,}, of which {cov['agent_in']:,} lie in a fitted goal-window "
            f"group and {cov['agent_total'] - cov['agent_in']:,} do not (rooms below 10% of their window's agent "
            "messages). By room:", ""]
    rows = [[r["room"], f"{r['agent_msgs']:,}", f"{r['in_fitted_groups']:,}", f"{r['outside']:,}"]
            for r in cov["rooms"].iter_rows(named=True)]
    out += [_table(["Room", "Agent messages", "In fitted groups", "Outside"], rows), ""]
    rows = [[r["source"], f"{r['messages']:,}", f"{r['attached']:,}", f"{r['not_attached']:,}"]
            for r in cov["exo"].iter_rows(named=True)]
    out += [_table(["Exogenous source", "Messages", "Attached to a fitted realization", "Not attached"], rows), ""]
    out += [f"Of the attached messages, {cov['clipped']:,} were posted before their realization started and sit at "
            f"t = 0; {cov['dropped']:,} messages in a fitted group's room were dropped because they came after the "
            "last block of their date. The rest of the unattached messages lie in rooms or on dates without a "
            "fitted realization. Per window: `exo_clipped_to_start` and `exo_dropped_after_run` in "
            "`tables/hawkes_windows.csv`.", ""]
    nulls = cov.get("nulls", {})
    if nulls:
        bad = {k: v for k, v in nulls.items() if v}
        out += ["Missing values in the input columns the fits use (" + ", ".join(nulls) + "): "
                + ("none." if not bad else ", ".join(f"{k} {v:,}" for k, v in bad.items()) + "."), ""]
    return out


def _acceptance(res: dict, win: pl.DataFrame) -> list[str]:
    acc: pl.DataFrame = res["accept"]
    n_fail = int((~win["accepted"].fill_null(False)).sum())
    sens = res.get("sens")
    refits = sens.filter(pl.col("refit").fill_null(False)) if sens is not None and "refit" in sens.columns else None
    matched = res.get("matched")
    rec = (acc.sort("round").group_by("key").agg(pl.col("n_reps").max(), pl.col("n_exploded").max(),
                                                  pl.col("rec_violations").max())
           if {"n_reps", "n_exploded", "rec_violations"} <= set(acc.columns) else None)
    n_rec = int((rec["n_reps"] - rec["n_exploded"].fill_null(0)).sum()) if rec is not None else 0
    viol = [("final goal fits", int(win["n_violations"].sum()), win.height),
            ("sensitivity refits", _sum(refits, "n_violations"), 0 if refits is None else refits.height),
            ("bootstrap replicates (every refit of each)", _sum(win, "boot_violations"), _sum(win, "boot_reps")),
            ("recovery refits of every window checked", _sum(rec, "rec_violations"), n_rec),
            ("matched-truth refits", _sum(matched, "n_violations"), _sum(matched, "reps"))]
    conv = int(win["converged"].sum())
    has_ci = int((win["boot_reps"] > 0).sum())
    rounds = int(acc["round"].max()) + 1 if acc.height else 0
    extra = acc.filter(pl.col("n_reps") > P.N_REC)["key"].n_unique() if "n_reps" in acc.columns else 0
    out = [
        "## 3. SPEC 5.7 acceptance",
        "",
        _table(["Item", "Result"], [
            ["EM objective never decreases", "; ".join(f"{v} decreases over {n:,} {k}" for k, v, n in viol)],
            ["Fits certified (Newton)", f"{conv} of {win.height} final goal fits"],
            ["Synthetic recovery (SPEC 5.6-1, mean mae4 < 0.05)",
             f"{win.height - n_fail} of {win.height} final windows pass after {rounds} check rounds "
             f"({rounds - 1} merge round{'' if rounds == 2 else 's'}); {extra} windows were within "
             f"{P.BORDER_SE:g} standard errors of the bar after {P.N_REC} replicates and got {P.N_REC_EXTRA} more"],
            ["At least 3 main windows with shares, CIs and rho", f"{has_ci} windows with bootstrap intervals"],
            ["Validation 2 to 5", "sections 7 to 10"],
        ]),
        "",
        "Recovery check by round (SPEC 5.6-1): mean mae4 with its Monte Carlo standard error, and the mean bias "
        "(refit minus realized) of the shares and of n by cell type (self n_ii, other agents n_ij, exogenous). "
        "A replicate whose simulation exceeds 10 times the window's agent events or 50 times its candidate "
        "parent pairs counts as exploded (a supercritical fit generates data unlike the window's) and fails the "
        "window. Windows that failed were merged.",
        "",
    ]
    rows = []
    for r in acc.sort("round", "window_id", "group").iter_rows(named=True):
        rows.append([r["round"], r["window_id"], r["group"], f"{r['n_msgs']:,}", r.get("n_reps"), r.get("n_exploded"),
                     _f(r["mae4"]), _f(r.get("mae4_se")), _f(r.get("bias_baseline"), 3),
                     _f((r.get("bias_human") or 0) + (r.get("bias_system") or 0), 3), _f(r.get("bias_other_agents"), 3),
                     _f(r.get("bias_self"), 3), _f(r.get("n_self_bias"), 3), _f(r.get("n_other_bias"), 3),
                     _f(r.get("n_exogenous_bias"), 3), _yes(r["passed"]), r["merged"] or ""])
    out += [_table(["Round", "Window", "Group", "Agent msgs", "Reps", "Exploded", "mae4", "SE", "Bias baseline",
                    "Bias exogenous", "Bias other", "Bias self", "n bias self", "n bias other", "n bias exogenous",
                    "Pass", "Merged for"], rows), ""]
    last = win.filter(pl.col("recovery_bias_self").is_not_null()) if "recovery_bias_self" in win.columns else None
    if last is not None and last.height:
        out += [f"Final windows: mean self-share bias {_f(last['recovery_bias_self'].mean())} (range "
                f"{_f(last['recovery_bias_self'].min())} to {_f(last['recovery_bias_self'].max())}); mean n_ii bias "
                f"{_f(last['recovery_n_self_bias'].mean())}; mean exogenous n bias "
                f"{_f(last['recovery_n_exogenous_bias'].mean())}.", ""]
    return out


def _boot_check(win: pl.DataFrame, dec: pl.DataFrame | None) -> list[str]:
    """How far the run-day bootstrap replicates sit from the estimates, and which start won."""
    if dec is None or dec.is_empty() or dec["estimate_in_ci"].null_count() == dec.height:
        return []
    d = dec.filter(pl.col("scheme") == "spec_four_way")
    w5 = win.filter(pl.col("n_dates") == 5)
    kept = (f"windows of 5 run dates keep {_f(w5['boot_dates_kept'].mean() * 5, 2)} of 5 dates on average "
            f"({_f(w5['boot_dates_kept'].mean(), 3)}; 5(1 - 0.8^5)/5 = 0.672 expected), " if w5.height else "")
    reps = int(win["boot_reps"].sum())
    sb, wb = int(win["boot_starts_better"].sum()), int(win["boot_warm_better"].sum())
    out = [f"Bootstrap check. Replicates draw run dates with replacement, so they keep fewer distinct dates than the "
           f"data: {kept}over all windows {_f(win['boot_dates_kept'].mean(), 3)} of the dates. With few distinct "
           "days the refit can move activity between the baseline and self-excitation, so the replicate "
           "distribution can sit beside the estimate. Starts: over "
           f"{reps:,} replicates the three-start refit beat the warm start by more than 0.1 nats in {sb:,} "
           f"(in {int((win['boot_starts_better'] > 0).sum())} windows) and the warm start beat the three starts in "
           f"{wb:,} (in {int((win['boot_warm_better'] > 0).sum())} windows); the largest gap was "
           f"{_f(win['boot_max_gap'].max(), 2)} nats. Each replicate keeps the better of the two.", ""]
    rows = []
    for (c,), g in sorted(d.partition_by("category", as_dict=True).items()):
        few, many = g.filter(pl.col("n_dates") <= 6), g.filter(pl.col("n_dates") > 6)
        q = g["estimate_quantile"].fill_null(0.5)
        rows.append([c, g.height, int(g["estimate_in_ci"].fill_null(True).not_().sum()),
                     int(((q <= 0.05) | (q >= 0.95)).sum()),
                     _f((g["boot_mean"] - g["share"]).median()), _f((few["boot_mean"] - few["share"]).median()),
                     _f((many["boot_mean"] - many["share"]).median()), _f(g["boot_sd"].median())])
    out += [_table(["Category", "Windows", "Estimate outside percentile CI", "Estimate beyond 95% of replicates",
                    "Median bootstrap mean minus estimate", "Same, windows with <= 6 run dates",
                    "Same, windows with > 6 run dates", "Median bootstrap SD"], rows), ""]
    rho_out = int(((win["rho"] < win["rho_lo"]) | (win["rho"] > win["rho_hi"])).sum())
    shift = _f((win["rho_boot_mean"] - win["rho"]).median())
    out += [f"rho: estimate outside its percentile interval in {rho_out} of {win.height} windows; median bootstrap "
            f"mean minus estimate {shift}. `tables/hawkes_decomposition.csv` also gives the bootstrap mean and "
            "SD and the normal interval (estimate +/- 1.96 SD, clipped to [0, 1]).", ""]
    return out


def _windows_section(win: pl.DataFrame, dec: pl.DataFrame | None = None) -> list[str]:
    out = ["## 4. Goal windows: decomposition and spectral radius", "",
           "Shares of agent events (SPEC 5.5), point estimate [95% run-day bootstrap interval]. Exogenous = human "
           "plus system (SPEC four-way). Dates = run dates (realizations when different). Part-time = agents "
           f"present on fewer than {P.CORE_PRESENCE:.0%} of the realizations; rho core = rho of N_AA over the "
           "others. Matched = range of mean mae4 over the matched-truth arms "
           f"({', '.join(ARMS)}).", ""]
    rows = []
    for r in win.sort("date_start", "group").iter_rows(named=True):
        days = f"{r['n_dates']}" + (f" ({r['n_days']})" if r["n_days"] != r["n_dates"] else "")
        rows.append([
            r["window_id"], r["group"], f"{r['date_start']} to {r['date_end']}", days, r["K"], r["K_part_time"],
            f"{r['agent_events']:,}", _ci(r["rho"], r["rho_lo"], r["rho_hi"]), _f(r["rho_core"]),
            _ci(r["share_baseline"], r["share_baseline_lo"], r["share_baseline_hi"], 2),
            _ci(r["share_human"], r["share_human_lo"], r["share_human_hi"], 2),
            _ci(r["share_system"], r["share_system_lo"], r["share_system_hi"], 2),
            _ci(r["share_other_agents"], r["share_other_agents_lo"], r["share_other_agents_hi"], 2),
            _ci(r["share_self"], r["share_self_lo"], r["share_self_hi"], 2),
            _ci(r["share4_exogenous"], r["share4_exogenous_lo"], r["share4_exogenous_hi"], 2),
            _f(r["mae4"]), f"{_f(r['matched_mae4_min'])} to {_f(r['matched_mae4_max'])}",
            "accepted" if r["accepted"] else "failed", r["merged"] or "",
        ])
    out += [_table(["Window", "Group", "Dates", "Run dates", "K", "Part-time", "Agent events", "rho", "rho core",
                    "Baseline", "Human", "System", "Other agents", "Self", "Exogenous", "mae4", "Matched", "Status",
                    "Merged for"], rows), ""]
    w = win["agent_events"].to_numpy().astype(float)
    pooled = {c: float(np.average(win[f"share_{c}"].to_numpy(), weights=w))
              for c in ("baseline", "human", "system", "other_agents", "self")}
    acc = win.filter(pl.col("accepted").fill_null(False))
    n_above, n_ci_above = int((acc["rho"] > 1).sum()), int((acc["rho_lo"] > 1).sum())
    core_above = int((acc["rho_core"] > 1).sum())
    out += [f"Event-weighted mean over the {win.height} windows: "
            + ", ".join(f"{k} {_f(v)}" for k, v in pooled.items())
            + f". Accepted windows: rho > 1 in {n_above} of {acc.height}, rho interval above 1 in {n_ci_above}, "
              f"rho over the core agents > 1 in {core_above}.", ""]
    out += _boot_check(win, dec)
    out += ["Convergence certificate of every final fit (all `converged` = Newton-certified):", ""]
    rows = [[r["window_id"], r["group"], _yes(r["converged"]), f"{r['newton_gain']:.1e}", r["n_violations"], r["start"],
             _f(r["start_spread"]), r["n_iter"], _f(r["boot_converged"], 3), _f(r["recovery_converged"], 2),
             _f(r["fit_secs"], 1)]
            for r in win.sort("date_start", "group").iter_rows(named=True)]
    out += [_table(["Window", "Group", "Certified", "Newton gain (nats)", "Objective decreases", "Best start",
                    "Start spread (nats)", "Iterations", "Bootstrap refits certified", "Recovery refits certified",
                    "Fit s"], rows), ""]
    return out


def _part_time_section(pt: pl.DataFrame | None) -> list[str]:
    if pt is None or pt.is_empty():
        return []
    out = [f"Part-time agents (present on fewer than {P.CORE_PRESENCE:.0%} of their window's realizations; their "
           "baseline and excitation count only on the realizations they are present). Agents with few events can "
           "still carry a large n_ii, which then sets rho; rho core leaves them out.", ""]
    rows = [[r["window_id"], r["group"], r["agent"], _f(r["presence"], 2), f"{r['events']:,}", _f(r["n_self"])]
            for r in pt.sort("window_id", "group", "agent").iter_rows(named=True)]
    return out + [_table(["Window", "Group", "Agent", "Presence", "Events", "n_ii"], rows), ""]


def _identification(win: pl.DataFrame, sens: pl.DataFrame | None) -> list[str]:
    out = ["## 5. Kernel classes: expected children and identification", "",
           f"A class shape rests on its expected children (sum over its cells of n_ij times the events of source j "
           f"on the days target i is present); shapes with fewer than {P.IDENTIFIED:g} are not identified "
           "(docs/decisions.md) and are flagged in `hawkes_kernels.parquet`, where every class of a window that "
           "failed the recovery check is flagged too.", ""]
    rows = []
    for r in win.sort("date_start", "group").iter_rows(named=True):
        rows.append([r["window_id"], r["group"]] + [
            f"{_f(r.get(f'children_{c}'), 0)} ({_yes(r.get(f'identified_{c}'))})" for c in CLASSES])
    out += [_table(["Window", "Group", "Self", "Other", "Human", "System"], rows), ""]
    for c in ("human", "system", "self", "other"):
        n_ok = int(win[f"identified_{c}"].fill_null(False).sum())
        out.append(f"- {c}: identified in {n_ok} of {win.height} windows.")
    out.append("")
    if sens is not None and not sens.is_empty():
        t = sens.filter(pl.col("variant") == "tie")
        if "tied" in t.columns:
            t = t.filter(pl.col("tied").is_not_null() & (pl.col("tied") != ""))
            if t.height:
                out += ["Tied variant (low-count exogenous shapes take the other-agent shape), change against the "
                        "main fit:", ""]
                rows = [[r["window_id"], r["group"], r["tied"], _f(r["d_rho"]), _f(r["d_baseline"]), _f(r["d_human"]),
                         _f(r["d_system"]), _f(r["d_other_agents"]), _f(r["d_self"])] for r in t.iter_rows(named=True)]
                out += [_table(["Window", "Group", "Tied", "d rho", "d baseline", "d human", "d system", "d other",
                                "d self"], rows), ""]
                d = t.select([pl.col(c).abs().max() for c in ("d_rho", "d_baseline", "d_human", "d_system",
                                                                "d_other_agents", "d_self")]).row(0)
                out += [f"Largest absolute change over tied windows: rho {_f(d[0])}, baseline {_f(d[1])}, human "
                        f"{_f(d[2])}, system {_f(d[3])}, other agents {_f(d[4])}, self {_f(d[5])}.", ""]
    return out


def _rolling_section(t: pl.DataFrame) -> list[str]:
    fitted = t.filter(pl.col("fitted"))
    out = ["## 6. Rolling windows (module C input)", "",
           f"{t.height} rolling groups (rooms above 10% of a 5-run-day block), {fitted.height} with at least 500 agent "
           "messages fitted; `hawkes_rolling.parquet` holds share_baseline, share_exogenous, share_agent, "
           "spectral_radius and n_agents per group (the schema of changepoint.series.load_external).", ""]
    if fitted.height:
        rows = []
        for (g,), s in sorted(fitted.partition_by("group", as_dict=True).items()):
            rows.append([g, s.height, f"{s['date_start'].min()} to {s['date_end'].max()}", _f(s["rho"].median()),
                         f"{_f(s['rho'].min())} to {_f(s['rho'].max())}", int((s["rho"] > 1).sum()),
                         int((s["rho_core"] > 1).sum()), _f(s["share_baseline"].median(), 2),
                         _f((s["share_other_agents"] + s["share_self"]).median(), 2),
                         _f((s["share_human"] + s["share_system"]).median(), 2), int(s["converged"].sum())])
        out += [_table(["Group", "Windows", "Dates", "Median rho", "rho range", "rho > 1", "rho core > 1",
                        "Median baseline", "Median agent-triggered", "Median exogenous", "Certified"], rows), ""]
        nf = t.filter(~pl.col("fitted"))
        if nf.height:
            out += ["Not fitted (fewer than 500 agent messages): " + ", ".join(
                f"{r['window_id']} {r['group']} ({r['n_msgs']:,})" for r in nf.sort("window_id").iter_rows(named=True))
                + ".", ""]
    return out


def _gof_section(gof: pl.DataFrame | None) -> list[str]:
    out = ["## 7. Validation 2: time-rescaling (SPEC 5.6-2)", ""]
    if gof is None or gof.is_empty():
        return out + ["Not run.", ""]
    g = gof.filter(pl.col("n_increments") >= 20)
    by = g.group_by("window_id", "group").agg(pl.col("ks").median().alias("med"), pl.col("ks").max().alias("max"),
                                              (pl.col("ks_p") < 0.05).mean().alias("rej"), pl.len().alias("dims"))
    out += [f"Compensator increments pooled end to end over the days each agent is present (pool=\"concat\"), KS "
            f"against Exp(1) per agent dimension with at least 20 increments ({g.height} of {gof.height} dimensions). "
            f"KS statistic median {_f(g['ks'].median())}, 90th percentile {_f(g['ks'].quantile(0.9))}; "
            f"{int((g['ks_p'] < 0.05).sum())} dimensions ({_f((g['ks_p'] < 0.05).mean(), 2)}) reject at 5%. QQ "
            "plots: `figures/hawkes_qq.png`; per-dimension values: `tables/hawkes_gof.csv`.", ""]
    rows = [[r["window_id"], r["group"], r["dims"], _f(r["med"]), _f(r["max"]), _f(r["rej"], 2)]
            for r in by.sort("window_id", "group").iter_rows(named=True)]
    return out + [_table(["Window", "Group", "Dimensions", "Median KS", "Max KS", "Share rejected"], rows), ""]


def _refs_section(res: dict) -> list[str]:
    out = ["## 8. Validation 3: explicit references (SPEC 5.6-3)", ""]
    refs = res.get("refs")
    if refs is None or refs.is_empty():
        return out + ["No tier-1 labels in the fitted windows.", ""]
    out += [f"Tier-1 labels (docs/decisions.md \"Parent labels\", from 2026-02-25): {res.get('n_labels_total')} "
            "children in all rooms; the table counts those in fitted groups. Hawkes = the most probable parent of the "
            "child (background and the child's own earlier messages count as misses); Hawkes, other speakers = the "
            "most probable parent among other speakers' events; baseline = the most recent earlier message in the "
            "room by someone else. Intervals: run-day cluster bootstrap (1,000 replicates, clusters in realization "
            "order, so the seed fixes them). Background and self = share of labelled children whose most probable "
            "parent is the background or the child's own message.", ""]
    rows = [[r["window_id"], r["group"], f"{r['n_labels']:,}",
             _ci(r["hawkes_match"], r["hawkes_match_lo"], r["hawkes_match_hi"]),
             _ci(r["hawkes_other_match"], r["hawkes_other_match_lo"], r["hawkes_other_match_hi"]),
             _ci(r["baseline_match"], r["baseline_match_lo"], r["baseline_match_hi"]),
             f"[{_f(r['hawkes_match_minus_baseline_lo'])}, {_f(r['hawkes_match_minus_baseline_hi'])}]",
             f"[{_f(r['hawkes_other_match_minus_baseline_lo'])}, {_f(r['hawkes_other_match_minus_baseline_hi'])}]",
             _f(r["label_in_candidates"]), _f(r["argmax_background"]), _f(r["argmax_self"])]
            for r in refs.iter_rows(named=True)]
    out += [_table(["Window", "Group", "Labels", "Hawkes", "Hawkes, other speakers", "Baseline",
                    "Hawkes minus baseline", "Other speakers minus baseline", "Label among candidates", "Background",
                    "Self"], rows), ""]
    bl = res.get("refs_by_label")
    if bl is not None and bl.height:
        out += ["By label type: " + "; ".join(
            f"{r['label']} n = {r['n']:,}, Hawkes {_f(r['hawkes_match'])}, Hawkes other speakers "
            f"{_f(r['hawkes_other_match'])}, baseline {_f(r['baseline_match'])}" for r in bl.iter_rows(named=True))
            + ".", ""]
    return out


def _opp_section(opp: pl.DataFrame | None) -> list[str]:
    out = ["## 9. Validation 4: action-opportunity model (SPEC 5.6-4)", ""]
    if opp is None or opp.is_empty():
        return out + ["Not run.", ""]
    out += ["Per agent, an L2 logistic regression (C = 1, standardized features) of whether an action is a message in "
            "the room on the decayed counts x_{e,j,m}; the integrated effect I_ij = sum_m gamma_ijm "
            "(1 - exp(-beta_m L)) / beta_m is compared with n_ij (avsd.hawkes.opportunity). Spearman over agent "
            "pairs j != i; per-agent mean over targets with at least 4 sources; top-source agreement = share of "
            "agents whose strongest other agent is the same in both; disagreements = pairs in the top decile of "
            "one ranking and the bottom half of the other (`tables/hawkes_opportunity_disagreements.csv`).", ""]
    rows = [[r["window_id"], r["group"], f"{r['n_actions']:,}", _f(r["msg_share"], 2), r["agents_fitted"], r["pairs"],
             _f(r["spearman"]), _f(r["spearman_per_agent_mean"]), _f(r["spearman_self"]), _f(r["top_source_agree"], 2),
             r["n_disagree"]] for r in opp.sort("window_id", "group").iter_rows(named=True)]
    out += [_table(["Window", "Group", "Actions", "Message share", "Agents", "Pairs", "Spearman (pairs)",
                    "Spearman per agent", "Spearman self", "Top source agrees", "Disagreements"], rows), ""]
    s = opp["spearman"].drop_nans().drop_nulls()
    if s.len():
        out += [f"Spearman over pairs: median {_f(s.median())}, range {_f(s.min())} to {_f(s.max())}; negative in "
                f"{int((s < 0).sum())} of {s.len()} windows.", ""]
    return out


def _sens_section(sens: pl.DataFrame | None) -> list[str]:
    out = ["## 10. Validation 5: sensitivity to L and G (SPEC 5.6-5)", ""]
    if sens is None or sens.is_empty():
        return out + ["Not run.", ""]
    s = sens.filter(~pl.col("variant").is_in(["tie", "core"]))
    out += ["One setting changed at a time: L = 1 h and 6 h at G = 30 min; G = 15 and 60 min at L = 3 h. The G "
            "variants rebuild the run blocks with the stage-0 rule (avsd.events.runs.find_blocks on the agent rows); "
            "no run_periods variants existed. A G variant whose blocks equal the G = 30 blocks reuses the main "
            "fit and is not a refit; the changes and the certified count below are over refits only.", ""]
    rows = []
    for (v,), g in sorted(s.partition_by("variant", as_dict=True).items()):
        ref = g.filter(pl.col("refit").fill_null(False))
        rows.append([v, g.height, g.height - ref.height, ref.height,
                     _f(ref["d_rho"].abs().median()) if ref.height else "n/a",
                     _f(ref["d_rho"].abs().max()) if ref.height else "n/a",
                     _f(ref["d_baseline"].abs().max()) if ref.height else "n/a",
                     _f((ref["d_human"] + ref["d_system"]).abs().max()) if ref.height else "n/a",
                     _f(ref["d_other_agents"].abs().max()) if ref.height else "n/a",
                     _f(ref["d_self"].abs().max()) if ref.height else "n/a",
                     _f(ref["d4_max"].median()) if ref.height else "n/a", int(ref["converged"].sum())])
    out += [_table(["Variant", "Windows", "Same blocks (main fit reused)", "Refits", "Median abs d rho",
                    "Max abs d rho", "Max abs d baseline", "Max abs d exogenous", "Max abs d other", "Max abs d self",
                    "Median max abs d (4-way)", "Certified refits"], rows), ""]
    core = sens.filter(pl.col("variant") == "core")
    if core.height:
        out += [f"Core agents (variant `core`): rho of N_AA over the agents present on at least {P.CORE_PRESENCE:.0%} "
                f"of the realizations, a submatrix of the main fit. It differs from rho in "
                f"{int((core['d_rho'].abs() > 1e-9).sum())} of {core.height} windows (median change "
                f"{_f(core['d_rho'].median())}, largest decrease {_f(core['d_rho'].min())}); above 1 in "
                f"{int((core['rho'] > 1).sum())} windows.", ""]
    return out


def _blocks_section(blocks: pl.DataFrame | None) -> list[str]:
    out = ["## 11. Block structure of N_AA (SPEC 5.5)", ""]
    if blocks is None or blocks.is_empty():
        return out + ["Not available.", ""]
    n_multi = int((blocks["n_blocks"] > 1).sum())
    out += ["Spectral clustering of (N_AA + N_AA^T) / 2 without the diagonal; the number of blocks (1 to 6) maximizes "
            f"the eigengap of the normalized Laplacian (1 when K < 4). Means are over cells j != i. One block in "
            f"{blocks.height - n_multi} windows, more in {n_multi}.", ""]
    rows = [[r["window_id"], r["group"], r["K"], r["n_blocks"], _f(r["mean_within"]), _f(r["mean_between"]),
             _f(r["ratio_within_between"], 2), _f(r["mean_self"]), r["blocks"]]
            for r in blocks.sort("window_id", "group").iter_rows(named=True)]
    return out + [_table(["Window", "Group", "K", "Blocks", "Mean within", "Mean between", "Ratio", "Mean self",
                          "Members"], rows), ""]


def _matched_section(m: pl.DataFrame | None) -> list[str]:
    out = ["## 12. Matched-truth arms", ""]
    if m is None or m.is_empty():
        return out + ["Not run.", ""]
    by = m.group_by("arm").agg(pl.col("mae4").median().alias("med"), pl.col("mae4").max().alias("max"),
                               (pl.col("mae4") >= P.BAR).sum().alias("above"), pl.len().alias("n"),
                               pl.col("bias_self").median().alias("bias_self"),
                               pl.col("n_self_bias").median().alias("n_self_bias"),
                               pl.col("exploded").fill_null(0).sum().alias("exploded"))
    out += [f"{P.MATCHED_REPS} replicates per arm and window, each simulated with the window's presence masks, "
            "refit with three starts and scored against the realized parent labels (`tables/hawkes_matched.csv`). "
            "An arm identical to the fit (no weight to move) is skipped, so some arms cover fewer windows.", ""]
    rows = [[r["arm"], r["n"], _f(r["med"]), _f(r["max"]), r["above"], _f(r["bias_self"]), _f(r["n_self_bias"]),
             r["exploded"]] for r in by.sort("arm").iter_rows(named=True)]
    header = ["Arm", "Windows", "Median mae4", "Max mae4", "Windows >= 0.05", "Median self-share bias",
              "Median n_ii bias", "Exploded replicates (no refit)"]
    k = m.group_by("key").agg((pl.col("mae4") >= P.BAR).any().alias("any"))
    return out + [_table(header, rows), "", f"Windows with at least one arm at mean mae4 >= {P.BAR:g}: "
                  f"{int(k['any'].sum())} of {k.height}.", ""]
