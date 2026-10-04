"""QA report of modules D2 to D4 (outputs/qa/swarmsim_d2_d4.md). Aggregates only: no artifact
key, URL, path, document id or text reaches the report.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import platform
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from avsd.swarmsim.depgraph import STAT_LABELS, STAT_NAMES
from avsd.swarmsim.robustness import FROM_DATE

SOURCE_BLOG = ('Wenhao Chai, "Predictable Swarm Scaling", 2026, '
               "https://wenhaochai.com/blogs/predictable-swarm-scaling.html")
DATA_CITE = 'AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village'


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return ""
    if isinstance(x, (bool, np.bool_)):
        return "yes" if x else "no"
    if isinstance(x, (int, np.integer)):
        return f"{int(x):,}"
    if isinstance(x, (float, np.floating)):
        x = float(x)
        if not math.isfinite(x):
            return ""
        if abs(x) >= 1000:
            return f"{x:,.0f}"
        return f"{x:.{nd}g}"
    return str(x)


def md_table(df: pl.DataFrame, cols: list[str] | None = None, header: list[str] | None = None) -> str:
    cols = cols or df.columns
    header = header or cols
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in df.select(cols).iter_rows():
        out.append("| " + " | ".join(_fmt(v) for v in r) + " |")
    return "\n".join(out)


def _ci(row: dict, key: str, lo: str | None = None, hi: str | None = None) -> str:
    v, a, b = row.get(key), row.get(lo or f"{key}_ci_low"), row.get(hi or f"{key}_ci_high")
    if v is None or not math.isfinite(v):
        return "n/a"
    return f"{v:.3g} (95% CI {a:.3g} to {b:.3g})"


def _robustness_section(rob: pl.DataFrame | None, checks: pl.DataFrame | None,
                        cov: pl.DataFrame | None) -> list[str]:
    """Section 8b: the D3, step-cost and D4 results on goal subsets with a small GUI focus gap."""
    if rob is None or rob.is_empty():
        return []
    subs = (rob.select("subset", "definition", "n_goals", "n_sessions").unique(maintain_order=True))
    lines = [
        "## 8b. Robustness to the GUI focus gap",
        "",
        "GUI writes without a focus are actions the graph cannot see. Per goal, `gap` is the share of write "
        "actions that are GUI writes without a focus (unattributed GUI writes over those plus turns with a write "
        "touch on an artifact), and `touch share` the share of sessions that touch an artifact. The pooled D3 "
        "statistics with their generator quantiles (the generator pools the same goals' DAGs), the within-goal "
        "step-cost slopes and the D4 rates with their baselines are recomputed on each subset of goals "
        "(D4: pairs whose next session belongs to the subset). CIs: goal bootstrap for slopes, agent bootstrap "
        "for D4; n is nodes with a parent (D3), sessions (cost) or pairs (D4).",
        "",
        md_table(subs, header=["Subset", "Definition", "Goals", "Sessions"]),
        "",
    ]
    if cov is not None and not cov.is_empty():
        early = cov.filter(pl.col("start") < FROM_DATE)
        late = cov.filter(pl.col("start") >= FROM_DATE)
        def med(df: pl.DataFrame, col: str) -> str:
            v = df[col].median() if df.height else None
            return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.3g}"

        lines += [f"Gap by goal: median {med(cov, 'gap')} (goals before 2025-10: median {med(early, 'gap')}; "
                  f"from 2025-10: median {med(late, 'gap')}); touch share: median {med(cov, 'touch_share')}.", ""]
    d3 = rob.filter((pl.col("analysis") == "D3") & (pl.col("edges") == "all"))
    lines += ["D3, all edges (AI Village value, generator mean and 95% range, quantile):", "",
              md_table(d3, ["subset", "statistic", "value", "gen_mean", "gen_p025", "gen_p975", "quantile", "n"],
                       ["Subset", "Statistic", "AI Village", "Generator mean", "Generator 2.5%", "Generator 97.5%",
                        "Quantile", "n"]), ""]
    sc = rob.filter(pl.col("analysis") == "step cost")
    lines += ["Step cost, within-goal slope of relative cost on relative depth (blog: 9):", "",
              md_table(sc, ["subset", "statistic", "value", "ci_low", "ci_high", "n"],
                       ["Subset", "Cost", "Slope", "CI low", "CI high", "Sessions"]), ""]
    d4 = rob.filter((pl.col("analysis") == "D4") & (pl.col("edges") == "all"))
    lines += ["D4, continuation (all edges):", "",
              md_table(d4, ["subset", "statistic", "window", "value", "ci_low", "ci_high", "baseline",
                            "baseline_ci_low", "baseline_ci_high", "n", "n_agents"],
                       ["Subset", "Measure", "Window", "Rate", "CI low", "CI high", "Baseline", "CI low", "CI high",
                        "Pairs", "Agents"]), ""]
    if checks is not None and not checks.is_empty():
        lines += ["Do the conclusions hold on each subset? (Write edges and all D4 rows are in "
                  "outputs/tables/depgraph_robustness.csv.)", ""]
        for concl in checks["conclusion"].unique(maintain_order=True).to_list():
            x = checks.filter(pl.col("conclusion") == concl)
            bad = x.filter(~pl.col("holds"))["subset"].to_list()
            verdict = "holds on every subset" if not bad else f"does not hold on: {', '.join(bad)}"
            full = x.filter(pl.col("subset") == "full")
            lines.append(f"- {concl[0].upper() + concl[1:]}: {verdict}. Full data: "
                         f"{full['detail'][0] if full.height else ''}.")
        lines.append("")
    return lines


def _v2_gui_sentence(c: dict) -> str:
    """Counts of the rules-v2 GUI decisions (empty under v1)."""
    keys = ("gui_via_carry", "gui_via_narrative", "gui_shell", "gui_search", "gui_input", "gui_nav_extra",
            "gui_click_nonwrite")
    if not any(c.get(k) for k in keys):
        return ""
    carry = ""
    if c.get("gui_via_carry") or c.get("gui_via_narrative"):
        carry = (f" {c.get('gui_via_carry', 0):,} GUI writes take the focus carried over from the agent's previous "
                 f"session and {c.get('gui_via_narrative', 0):,} the artifact the agent named just before.")
    return (f" Rules v2 do not count as GUI writes {c.get('gui_shell', 0):,} typed shell commands (parsed as bash "
            f"instead), {c.get('gui_input', 0):,} sign-in values and short inputs (game moves, single keys), "
            f"{c.get('gui_search', 0):,} searches, {c.get('gui_nav_extra', 0):,} navigations v1 missed and "
            f"{c.get('gui_click_nonwrite', 0):,} clicks on text boxes, links or menus (see "
            "outputs/qa/swarmsim_gui_gap.md)." + carry)


def write_qa(path: Path, cc: Any, outputs: dict, runtime: dict, ex: dict, goals: pl.DataFrame,
             structure: pl.DataFrame, parent_counts: pl.DataFrame, sensitivity: pl.DataFrame,
             cost: pl.DataFrame, continuation: pl.DataFrame, rules: pl.DataFrame,
             artifacts: pl.DataFrame, rob: pl.DataFrame | None = None, checks: pl.DataFrame | None = None,
             cov: pl.DataFrame | None = None) -> None:
    pooled = structure.filter(pl.col("scope") == "pooled")
    gmed = structure.filter(pl.col("scope") == "goal_median")
    per_goal = structure.filter(~pl.col("scope").is_in(["pooled", "goal_median"]))
    who = pl.DataFrame(ex["who"])
    who_all = who.filter((pl.col("edges") == "all") & (pl.col("scope") == "within_goal")).row(0, named=True)
    gui = ex["gui"]
    cf = ex["cost_fit"]

    def pv(lab: str, st: str) -> dict:
        return pooled.filter((pl.col("edges") == lab) & (pl.col("statistic") == st)).row(0, named=True)

    def cont(var: str, win: str, meas: str, stratum: str = "all") -> dict:
        return continuation.filter((pl.col("variant") == var) & (pl.col("window") == win)
                                   & (pl.col("measure") == meas) & (pl.col("stratum") == stratum)).row(0, named=True)

    n_child = int(pv("all", "multi_parent_share")["n_child_nodes"])
    c_main = cont("all", "goal", "with_parents")
    c_day = cont("all", "day", "with_parents")
    stat_lines = []
    for st in STAT_NAMES:
        a, w = pv("all", st), pv("write", st)
        stat_lines.append(
            f"  - {STAT_LABELS[st]}: all edges {a['observed']:.3f}, write edges {w['observed']:.3f}; "
            f"generator {a['gen_mean']:.3f} (95% range {a['gen_p025']:.3f} to {a['gen_p975']:.3f}); "
            f"quantile {a['quantile']:.3f} (all) and {w['quantile']:.3f} (write).")
    from avsd.swarmsim.touches import MAIN_RULES

    version = ex.get("rules", MAIN_RULES)
    main = version == MAIN_RULES
    title_rules = "" if main else f", touch rules {version} (sensitivity version)"
    status = (f"The touch rules (section 2) are rules {version}, confirmed by the owner on 2026-10-01 (SPEC 8.3). "
              "Rules v1, the first draft, are kept as a sensitivity version (the same outputs with the suffix "
              "`_v1`); the GUI follow-up that led to v2 is in outputs/qa/swarmsim_gui_gap.md."
              if main else
              f"This report uses touch rules {version}, the first draft, kept as a sensitivity version. The main "
              f"version is rules {MAIN_RULES}, confirmed by the owner on 2026-10-01 (outputs/qa/swarmsim_d2_d4.md).")
    lines = [
        f"# QA: AI Village dependency graph, structure and continuation (modules D2 to D4{title_rules})",
        "",
        f"Data: {DATA_CITE}. Generator: {SOURCE_BLOG}, re-implemented in module D1 (`avsd.swarmsim.dag`).",
        "",
        status,
        "",
        "## Summary",
        "",
        f"- Graph. {ex['n_sessions']:,} computer-use sessions in {goals.height} village-goal graphs. "
        f"{ex['sessions_touched']:,} sessions touch at least one artifact. The goal graphs hold "
        f"{int(pv('all', 'mean_parents')['n_edges']):,} edges ({int(pv('write', 'mean_parents')['n_edges']):,} write, "
        f"{int(pv('read', 'mean_parents')['n_edges']):,} read), and {n_child:,} sessions have at least one parent. "
        f"{who_all['same_agent_share']:.1%} of the edges join two sessions of the same agent.",
        "- Structure against the generator (pooled over goals; the generator distribution pools one generated DAG "
        f"per goal with that goal's session count, {cc.gen_dags} replicates):",
        *stat_lines,
        f"- Step cost. Session turn counts do not grow with depth: the within-goal slope of turns relative to the "
        f"goal's layer-0 sessions on relative depth is {cf['all']['turns']['slope']:.3g} (95% CI "
        f"{cf['all']['turns']['ci_low']:.3g} to {cf['all']['turns']['ci_high']:.3g}), against 9 in the blog's "
        f"c_d = 1 + 9 d / (D - 1). For active minutes it is {cf['all']['active_min']['slope']:.3g} (95% CI "
        f"{cf['all']['active_min']['ci_low']:.3g} to {cf['all']['active_min']['ci_high']:.3g}).",
        f"- Continuation. Among next sessions with at least one parent, {c_main['rate']:.3g} (95% CI "
        f"{c_main['rate_ci_low']:.3g} to {c_main['rate_ci_high']:.3g}; {c_main['n_pairs']:,} pairs, "
        f"{c_main['n_agents']} agents) have the agent's previous session among their parents. A random choice "
        f"among the artifacts written earlier in the same goal gives {c_main['baseline']:.3g} (95% CI "
        f"{c_main['baseline_ci_low']:.3g} to {c_main['baseline_ci_high']:.3g}); among those written earlier on the "
        f"same run day {c_day['baseline']:.3g} (95% CI {c_day['baseline_ci_low']:.3g} to "
        f"{c_day['baseline_ci_high']:.3g}).",
        f"- Runtime {runtime['wall_s']:.0f} s on {runtime['workers']} processes ({runtime['host']}); the touch "
        "extraction is cached and takes about 2 minutes more when it runs.",
        "",
        "## 1. Sessions",
        "",
        f"- Sessions {ex['n_sessions']:,}, of which {ex['n_sessions_with_turns']:,} have turns. Nodes are all "
        "sessions of a goal, including those without any artifact touch (isolated nodes).",
        "- Turns per session (10%, 50%, 90%, 99% quantiles): "
        + ", ".join(_fmt(v) for v in cf["turn_quantiles"].values())
        + ". The scaffold ends most sessions near 40 turns, so turn counts are capped.",
        "- Active minutes per session (gaps between turns of at most G = 30 minutes, SPEC 4.2): "
        + ", ".join(_fmt(v) for v in cf["active_quantiles"].values())
        + ". Wall minutes from start to last turn: "
        + ", ".join(_fmt(v) for v in cf["wall_quantiles"].values()) + ".",
        "",
        "## 2. Touches and the classification rules",
        "",
        "A touch is a turn that acts on an artifact. `write` and `read` touches make edges. `observed` "
        "(the identifier is only in the tool output) and `mention` (only in text the agent wrote: chat, typed or "
        "written content, commit messages, the provider response) are counted and enter only the sensitivity "
        "variant `with observed mentions`. `edges_first_touch` counts main-graph edges for which the rule produced "
        "the child's first touch of the shared artifact (GUI writes follow a navigation, so they never come first).",
        "",
        md_table(rules, ["rule", "mode", "description", "touches", "sessions", "session_share", "artifact_touches",
                         "edges_first_touch"],
                 ["Rule", "Mode", "Description", "Touches", "Sessions", "Share of sessions", "On artifacts",
                  "Edges (first touch)"]),
        "",
        "Touch rows by mode: " + ", ".join(f"{k} {v:,}" for k, v in sorted(ex["touch_modes"].items())) + ".",
        "",
        f"GUI writes (typed text, ctrl+s or ctrl+Enter, clicks on located write buttons, xdotool input): "
        f"{gui['gui_writes']:,}, of which {gui['gui_writes_unattributed']:,} "
        f"({gui['gui_writes_unattributed'] / max(gui['gui_writes'], 1):.1%}) happen without a GUI focus (no URL was "
        f"navigated to earlier in the session) and are tied to no artifact. {gui['sessions_gui_unattributed']:,} of "
        f"the {gui['sessions_gui']:,} sessions with GUI writes have only such writes. As the SPEC 2.3-7 verification "
        "found, these writes cannot reach an artifact without the screenshots (module E)."
        + _v2_gui_sentence(ex.get("gui_counts") or {}),
        "",
        "## 3. Artifact keys",
        "",
        "Keys follow SPEC 8.3 on top of `avsd.events.refs`: Google documents by id (document, sheet, slides, form "
        "and Drive file URLs of one id share a key), GitHub and GitLab by owner/repo/path, GitLab API project ids "
        f"mapped to the project path when the API output names exactly one project ({ex['gitlab_pid_mapped']} ids), "
        f"GitHub and GitLab Pages URLs mapped to their repository ({ex['pages_projects']} unique GitLab Pages "
        "project names resolvable), other URLs without query and fragment, and file paths. Paths, localhost URLs "
        "and personal account apps (mail, calendar, Drive home, studio pages) are local to the agent's computer or "
        "account, so their key includes the agent. Bare domains, search engines, sign-in, CDN and XML-namespace "
        "hosts are not artifacts. Dot directories under home (configuration) are not artifacts. Containers are the "
        "repository, the document, the URL itself, or the project directory (the deepest known repository root of "
        "the agent, else the first directory below home or /tmp, one level deeper under generic parents such as "
        "~/work).",
        "",
        f"Keyed touch rows {ex['n_keyed']:,}; distinct keys {ex['n_keys']:,}; containers {ex['n_containers']:,}. "
        "URL domains are shown as registrable domains only.",
        "",
        md_table(artifacts, ["kind", "domain", "keys", "containers", "written_keys", "touches_read_write", "sessions",
                             "edges_main"],
                 ["Kind", "Domain", "Keys", "Containers", "Written keys", "Read and write touches", "Sessions",
                  "Edges (main)"]),
        "",
        "## 4. Edges",
        "",
        "Session B gets the edge A -> B when B touches artifact x and A was the last other session to write x "
        "before B's first touch of x. Matching is hierarchical within a container (a touch of a path sees writes to "
        "that path and to the container as a whole; a touch of the container sees any write inside it). An edge "
        "is `write` when B also writes x, `read` otherwise; one pair of sessions linked through several artifacts "
        "is one edge, `write` if any link is. Edges must follow session start order, so the graph is a DAG.",
        "",
        md_table(pl.DataFrame([{"variant": k.replace("_", " "), **v} for k, v in ex["builds"].items()]),
                 ["variant", "edges", "write", "read", "dropped_order", "lookups", "lookups_with_writer"],
                 ["Variant", "Edges", "Write", "Read", "Dropped (parent started later)", "First touches",
                  "With an earlier writer"]),
        "",
        f"Edges between sessions of different goals ({ex['cross_goal']:,} in the main variant) are dropped from the "
        "per-goal graphs; module D4 uses the global graph. Who builds on whom:",
        "",
        md_table(who, ["edges", "scope", "n_edges", "same_agent_share", "local_only_share"],
                 ["Edges", "Scope", "Edges", "Same agent", "Only through local artifacts"]),
        "",
        "## 5. Graph size per goal",
        "",
        md_table(goals, header=["Goal", "Start", "End", "Sessions", "Agents", "Touching", "Edges", "Write", "Read",
                                "Cross-goal dropped", "Layers", "Layers (write)", "Root share", "Isolated share",
                                "2+ parents"]),
        "",
        "Goals before about 2025-10 have few touching sessions: most of their work was GUI work without a focus "
        "(section 2). The open goal G51 (from 2026-07-06) holds most sessions and edges, so pooled statistics "
        "lean on it; the median over goals weights goals equally.",
        "",
        "## 6. Structure against the generator (D3)",
        "",
        f"Generator: `grow_dag` with the blog's parameters (17 layers, layer peak at 28% depth, merge probability "
        f"0.46, no task variation, seed {cc.seed}), {cc.gen_dags} DAGs per goal with the goal's session count. "
        "Statistics are computed the same way on both sides (`avsd.swarmsim.depgraph`): parent counts over nodes "
        "with at least one parent, the sibling share over nodes with at least two parents (two parents are "
        "siblings when they share a parent), out-degree inequality over nodes with at least one child, and the "
        "cross-layer share over edges spanning two or more layers after relayering (each node one below its "
        "deepest parent). Pooled rows join the counts of all goal graphs; the generator side pools one DAG per "
        "goal per replicate. The quantile is the share of generator values below the observed value (ties count "
        "half). The generator has one root by construction, while "
        f"{pv('all', 'mean_parents')['n_nodes'] - n_child:,.0f} AI Village sessions have no parent.",
        "",
        md_table(pooled.filter(pl.col("statistic").is_in(list(STAT_NAMES))),
                 ["edges", "statistic", "observed", "gen_mean", "gen_p025", "gen_p975", "quantile", "n_child_nodes",
                  "n_multi"],
                 ["Edges", "Statistic", "AI Village", "Generator mean", "Generator 2.5%", "Generator 97.5%",
                  "Quantile", "Nodes with parents", "Nodes with 2+ parents"]),
        "",
        "Parent-count distribution (share of nodes with at least one parent):",
        "",
        md_table(parent_counts, header=["Edges", "Parents", "AI Village", "Generator mean", "Generator 2.5%",
                                        "Generator 97.5%", "Quantile", "Nodes with parents"]),
        "",
        "Median over goals (each goal weighted equally; the generator value of a replicate is the median over "
        "goals of that replicate's DAGs):",
        "",
        md_table(gmed, ["edges", "statistic", "observed", "gen_mean", "gen_p025", "gen_p975", "quantile", "n_goals"],
                 ["Edges", "Statistic", "AI Village", "Generator mean", "Generator 2.5%", "Generator 97.5%",
                  "Quantile", "Goals"]),
        "",
        "Single goals: number of goal graphs whose value lies below the generator's 2.5% point or above its 97.5% "
        "point (undefined where the goal graph has no qualifying node or edge):",
        "",
        md_table(per_goal.group_by("edges", "statistic")
                 .agg((pl.col("quantile") < 0.025).sum().alias("below"),
                      (pl.col("quantile") > 0.975).sum().alias("above"),
                      ((pl.col("quantile") >= 0.025) & (pl.col("quantile") <= 0.975)).sum().alias("inside"),
                      pl.col("quantile").is_nan().sum().alias("undefined"))
                 .sort("edges", "statistic"),
                 header=["Edges", "Statistic", "Below 2.5%", "Above 97.5%", "Inside", "Undefined"]),
        "",
        "Sensitivity (pooled): other generator sizes (connected sessions only; depth matched to the goal graph's "
        "layer count), exact-key matching, observed and mentioned identifiers counted as reads, and structured "
        "artifacts only (no plain URLs).",
        "",
        md_table(sensitivity, ["variant", "edges", "statistic", "observed", "gen_mean", "gen_p025", "gen_p975",
                               "quantile"],
                 ["Variant", "Edges", "Statistic", "AI Village", "Generator mean", "Generator 2.5%",
                  "Generator 97.5%", "Quantile"]),
        "",
        "## 7. Step cost by layer",
        "",
        "Each session's turns and active minutes are divided by the mean of the layer-0 sessions of its goal. The "
        "blog sets the cost of a step at depth d to c_d = 1 + 9 d / (D - 1), ten times the root's at the deepest "
        "layer; `blog` gives that ratio for the sessions in each bin. CIs come from a bootstrap over goals.",
        "",
        md_table(cost.filter(pl.col("edges") == "all"),
                 ["axis", "bin", "n_sessions", "n_goals", "mean_turns", "turns_vs_layer0", "turns_vs_layer0_ci_low",
                  "turns_vs_layer0_ci_high", "mean_active_min", "active_vs_layer0", "active_vs_layer0_ci_low",
                  "active_vs_layer0_ci_high", "blog_vs_layer0"],
                 ["Axis", "Bin", "Sessions", "Goals", "Turns", "Turns vs layer 0", "CI low", "CI high",
                  "Active min", "Active vs layer 0", "CI low", "CI high", "Blog"]),
        "",
        "Within-goal least-squares slope of relative cost on relative depth d / (D - 1) (the blog's slope is 9):",
        "",
        md_table(pl.DataFrame([{"edges": lab, "cost": c, **v} for lab in ("all", "write")
                               for c, v in cf[lab].items()]),
                 ["edges", "cost", "slope", "ci_low", "ci_high", "n_sessions", "n_goals"],
                 ["Edges", "Cost", "Slope", "CI low", "CI high", "Sessions", "Goals"]),
        "",
        "The write-edge table is in depgraph_cost_by_layer.csv.",
        "",
        "## 8. Continuation (D4)",
        "",
        "For each pair of consecutive sessions (p, n) of one agent, the indicator is 1 when p is among n's parents "
        "in the global graph. `with_parents` keeps pairs whose n has a parent; `all_pairs` keeps every pair. The "
        "baseline draws n's parented containers at random from the containers written before n started in the "
        "same goal (`goal`) or run day (`day`), shared ones by anyone and local ones by the agent itself; `own_work` "
        "restricts the pool to containers last written by the agent and the draws to n's containers with an own "
        "parent. 95% CIs from 2,000 bootstrap replicates over agents. Strata: all pairs and the two computer-use "
        "regimes (`regime_cu`, before and after the switch to continuous computer use).",
        "",
        md_table(continuation.filter(pl.col("variant") == "all"),
                 ["window", "measure", "stratum", "rate", "rate_ci_low", "rate_ci_high", "baseline",
                  "baseline_ci_low", "baseline_ci_high", "ratio", "ratio_ci_low", "ratio_ci_high", "n_pairs",
                  "n_agents", "median_pool"],
                 ["Window", "Measure", "Stratum", "Rate", "CI low", "CI high", "Baseline", "CI low", "CI high",
                  "Ratio", "CI low", "CI high", "Pairs", "Agents", "Median pool"]),
        "",
        "With write edges only (the parent link must come through an artifact the next session also writes):",
        "",
        md_table(continuation.filter((pl.col("variant") == "write") & (pl.col("stratum") == "all")),
                 ["window", "measure", "rate", "rate_ci_low", "rate_ci_high", "baseline", "baseline_ci_low",
                  "baseline_ci_high", "n_pairs", "n_agents"],
                 ["Window", "Measure", "Rate", "CI low", "CI high", "Baseline", "CI low", "CI high", "Pairs",
                  "Agents"]),
        "",
        *_robustness_section(rob, checks, cov),
        "## 9. Choices beyond the SPEC text",
        "",
        "- Touch modes `observed` and `mention` are kept apart from `read`; only write and read touches make edges "
        "in the main graph (sensitivity variant above).",
        "- Matching within containers (repository, project directory) on top of the SPEC 8.3 keys, so that a push "
        "or a clone links to the files inside the repository; exact-key matching is a sensitivity variant.",
        "- Local artifacts (paths, localhost, personal account apps) are keyed per agent because every agent has "
        "its own computer and accounts.",
        "- Edges from a session that started after the child are dropped to keep a DAG; edges across goals are "
        "dropped from the per-goal graphs.",
        "- The generator uses the goal's session count (isolated sessions included) and the blog's 17 layers; "
        "connected-session counts and matched depth are sensitivity variants.",
        "- Parent-count statistics are taken over nodes with at least one parent, because the generator has one "
        "root and the AI Village graphs have many.",
        "- D4 counts artifacts at the container level, takes the parents from the global graph, and uses two "
        "periods (goal, run day) for the reachable pool.",
        "- Step cost uses active minutes (pauses longer than G removed) and costs relative to the goal's layer-0 "
        "sessions.",
        "",
        "## 10. Outputs and command",
        "",
        *[f"- `{v}`" for v in outputs.values()],
        "- Private, under `data/interim/depgraph/`: touches, keyed session-artifact table, edges, continuation "
        "pairs, provider-response refs.",
        "",
        "Command: `avsd swarmsim calibrate` (Slurm: `sbatch scripts/depgraph_calibrate.sbatch`; "
        "`--force-extract` re-extracts the touches). Library: `avsd.swarmsim.calibrate.run_calibration(cfg)`.",
        f"Python {platform.python_version()}, numpy {np.__version__}, polars {pl.__version__}.",
        "",
    ]
    path.write_text("\n".join(lines))
