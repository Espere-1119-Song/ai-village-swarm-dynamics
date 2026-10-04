"""What each report tab shows: known outputs with captions, expected files, and
name patterns that route new files to a tab automatically.

Paths are relative to outputs/. A known item whose file is missing is listed as
"not produced yet" in its tab; a file that matches no known item lands in the "Other files"
section of the tab whose pattern it matches (first match wins), or of Overview.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    path: str                      # relative to outputs/, e.g. "tables/changepoints.csv"
    title: str                     # Chinese caption
    note: str = ""
    kind: str = ""                 # table | figure | markdown | md_table | md_sections | ingest | cp_chart
    view: dict = field(default_factory=dict)   # table view: filters (with defaults), columns, fixed
    sections: tuple[str, ...] = ()             # md_sections: level-2 heading prefixes

    @property
    def resolved_kind(self) -> str:
        if self.kind:
            return self.kind
        return {"csv": "table", "png": "figure", "md": "markdown"}.get(self.path.rsplit(".", 1)[-1], "file")


@dataclass(frozen=True)
class Tab:
    token: str
    label: str
    title: str = ""
    intro: str = ""
    items: tuple[Item, ...] = ()
    expected: tuple[tuple[str, str], ...] = ()     # (path pattern, description) for unnamed outputs
    patterns: tuple[str, ...] = ()                 # fnmatch patterns on file names
    qa: tuple[str, ...] = ()                       # QA report stems linked from the tab


def _sel(col: str, label: str = "", default: str | None = None) -> dict:
    f = {"type": "select", "col": col, "label": label or col}
    if default is not None:
        f["default"] = default
    return f


SCOPE_FILTERS = [_sel("scope", "scope"), _sel("stratum", "stratum")]
FAMILY_FILTERS = [_sel("scope", "scope", "family"), _sel("stratum", "stratum")]   # model families first

CHANGEPOINT_COLUMNS = [
    "series_id", "level", "metric_label", "method", "run_day", "date", "magnitude", "rel_change",
    "magnitude_std", "ci_lo_date", "ci_hi_date", "boot_detect_rate", "persists_2x_penalty",
    "bocpd_agree", "comp_verdict", "nearest_entry_id", "nearest_entry_date", "nearest_entry_categories",
    "nearest_entry_offset_run_days", "aligned", "cause", "aligned_documented", "cause_documented",
    "ui_links",
]
CHANGEPOINT_FILTERS = [
    {"type": "text", "col": "series_id", "label": "Series"},
    _sel("method", "Method", "pelt_l2"),
    _sel("level", "Level"),
    _sel("aligned", "aligned"),
    _sel("cause", "cause"),
    _sel("cause_documented", "cause_documented"),
    {"type": "daterange", "col": "date", "label": "Date"},
]
ALIGNMENT_COLUMNS = [
    "method", "cp_set", "series_set", "entry_set", "holm_family", "w", "n_entries", "n_changepoints",
    "coverage_frac", "aligned", "aligned_frac", "null1_mean", "null1_q025", "null1_q975", "null1_p",
    "null1_p_holm", "null2_mean", "null2_q025", "null2_q975", "null2_p", "null2_p_holm",
]

DATA = Tab(
    "data", "Data and event table", "Data and event table",
    "Raw tables to parquet, the unified event table, run periods, roster and CHANGELOG. The parquet files stay in data/ and are not part of this report; the main tables of the QA reports are shown here.",
    items=(
        Item("qa/ingest.md", "Row counts of the parquet conversion",
             "Parsed from the table sections of ingest.md: rows read and written, manifest rows and differences, duplicate ids, unparseable rows and timestamp failures.", kind="ingest"),
        Item("qa/build_events.md", "Unified event table: row reconciliation and actor types",
             "From sections 1 and 2 of build_events.md.", kind="md_sections", sections=("1.", "2.")),
        Item("qa/memory_versions.md", "Memory version links (path S)",
             "From the first two sections of memory_versions.md.", kind="md_sections",
             sections=("Previous-row classes", "Relations")),
        Item("tables/changelog_review.md", "CHANGELOG entries and categories",
             "Change entries and roster joins and departures; categories reviewed by hand on 30 September.", kind="md_table",
             view={"filters": [_sel("tags", "tags"), _sel("categories", "categories"),
                               _sel("flags", "flags")]}),
    ),
    patterns=("changelog*", "ingest*", "build_events*", "events*", "run_periods*", "pause_segments*",
              "roster*", "agents*", "memory_versions*", "rooms*"),
    qa=("ingest", "build_events", "memory_versions"),
)

HAWKES_WINDOW_FILTERS = [{"type": "text", "col": "window_id", "label": "Window"}, _sel("group", "group")]

MODULE_A = Tab(
    "moduleA", "Chat excitation", "Chat excitation: multivariate Hawkes process",
    "Agent events split into baseline, human-triggered, triggered by other agents and self-excitation; the excitation matrix N, the spectral radius of the agent subsystem and its block structure. Main windows follow village goals and are fitted per chat room; agents count only on realizations where they are present.",
    items=(
        Item("figures/F1_excitation.png", "Figure F1: excitation matrix N of each main window",
             "Rows are target agents and columns source agents (sorted by spectral cluster, red lines at cluster bounds), then human and system; square-root colour scale."),
        Item("figures/F2_activity_shares.png", "Figure F2: shares of agent messages over time",
             "Triggered by agents (other agents and self), human and system, and baseline; best and rest rooms merged by events per run day; hatched bands are 95% bootstrap intervals."),
        Item("tables/hawkes_windows.csv", "Main windows: shares with 95% intervals, spectral radius, recovery check and convergence certificate",
             "mae4 is the mean error of the recovery check (20 replicates, 40 near the threshold); recovery_* are the biases of each share and of n; matched gives the mae4 range of matched-truth arms; K_part_time counts agents present in under 80% of realizations, and rho_core is the spectral radius of the others; children_* are expected offspring per kernel class, and identified is false below 50.",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_decomposition.csv", "Shares in five classes (baseline, human, system, other agents, self) and in four classes",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("scheme", "scheme", "five_way"),
                                                       _sel("category", "category")]}),
        Item("tables/hawkes_excitation.csv", "Excitation matrix n_ij with 95% intervals (rows target agents, columns sources)",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("source_class", "source_class"),
                                                       {"type": "text", "col": "target", "label": "Target"}]}),
        Item("tables/hawkes_blocks.csv", "Spectral clusters of N_AA with mean n_ij within and between clusters",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_acceptance.csv", "Recovery check and window merges (each round)",
             view={"filters": [_sel("round", "round"), _sel("passed", "passed")] + HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_matched.csv", "Recovery errors of matched-truth arms (each window and arm)",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("arm", "arm")]}),
        Item("tables/hawkes_sensitivity.csv", "Sensitivity: L = 1 and 6 hours, G = 15 and 60 minutes, tied kernel shapes for low-count external sources, and the spectral radius of steady agents only (core)",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("variant", "variant")]}),
        Item("figures/hawkes_qq.png", "Time-rescaling QQ plots",
             "Dark: all agents of a window; light: single agents."),
        Item("tables/hawkes_gof.csv", "Time-rescaling: KS statistic of each agent dimension",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_reference_check.csv", "Explicit references: agreement of the most probable parent with tier-1 labels",
             "The baseline is the latest message by someone else in the same room; intervals are run-day cluster bootstraps."),
        Item("tables/hawkes_opportunity.csv", "Spearman correlation between the opportunity model and the Hawkes ranking of j→i",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_opportunity_disagreements.csv", "Agent pairs where the two rankings disagree",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_rolling_windows.csv", "Fits on rolling windows of 5 run days, for change-point detection",
             view={"filters": [_sel("group", "group"), _sel("fitted", "fitted")]}),
    ),
    expected=(("tables/hawkes_*.csv", "Result tables of the excitation model (written by `avsd hawkes fit`; parquet tables and parent probabilities are not embedded)"),),
    patterns=("hawkes*", "F1_*", "F2_*", "excitation*"),
    qa=("hawkes",),
)

MODULE_B1 = Tab(
    "moduleB1", "Memory retention", "Memory retention: fact units in memory",
    "Survival, loss and modification of fact units across consolidations, and whether the hazard stays constant. The main rule is literal match (v2), chosen on the audit labels; tables for anchor match (no suffix) and context match (_v3) are sensitivity analyses among the other files at the end of this page.",
    items=(
        Item("figures/F6_memory_retention_v2.png", "Figure F6: memory retention by model family with geometric fits (literal match)"),
        Item("tables/memory_h2_v2.csv", "Test of a constant hazard against a piecewise-constant hazard (literal match)",
             "The likelihood-ratio test treats units as independent; the Wald test uses an agent-clustered bootstrap covariance; the AIC of the beta-geometric model is compared too.",
             view={"filters": SCOPE_FILTERS + [_sel("ci_method", "ci_method")],
                   "columns": ["scope", "stratum", "n_agents", "n_units", "n_trials", "h_geometric", "h1",
                               "h1_lo", "h1_hi", "h2", "h3_4", "h5_8", "h9plus", "lr", "df", "p_lr",
                               "wald_cluster", "p_wald_cluster", "aic_geometric", "aic_betageom",
                               "aic_piecewise", "ci_method"]}),
        Item("tables/memory_hazard_v2.csv", "Hazard of loss h_g by consolidation g with 95% intervals (literal match)",
             view={"filters": FAMILY_FILTERS + [_sel("ci_method", "ci_method")]}),
        Item("tables/memory_post_switch_rise.csv", "Paired test of h2 − h1 after the switch to continuous computer use (three rules)",
             "h1 and h2 come from the same agent bootstrap replicates; only literal match has an interval that excludes 0."),
        Item("tables/memory_label_metrics.csv", "Label validation: precision, recall and F1 of the three rules and the models against the audit labels",
             "Main result scheme = weighted: 60 stratified audit units labelled blind by the first author, weighted to the 500 validation units by inclusion probability; weighted_owner71 adds 11 more rows labelled by the first author, and weighted_claude277 uses Claude's 277 blind labels.",
             view={"filters": [_sel("scheme", "scheme", "weighted"), _sel("label", "label"),
                               _sel("metric", "metric")],
                   "columns": ["scheme", "label", "metric", "rule", "rule_lo", "rule_hi", "rule_v2", "rule_v2_lo",
                               "rule_v2_hi", "rule_v3", "rule_v3_lo", "rule_v3_hi", "v2_minus_v1",
                               "v2_minus_v1_lo", "v2_minus_v1_hi", "llm", "qwen35_122b", "gptoss_120b",
                               "gemini", "claude", "claude_lo", "claude_hi", "n_labelled"]}),
        Item("tables/memory_retention_v2.csv", "Discrete retention curves (Kaplan-Meier form) with geometric and beta-geometric fits (literal match)",
             view={"filters": FAMILY_FILTERS}),
        Item("tables/memory_modification_v2.csv", "Modification rate by consolidation and the modified share of losses (literal match)",
             view={"filters": FAMILY_FILTERS}),
        Item("tables/memory_by_anchor_v2.csv", "Hazard, modification and restoration rates by anchor type (literal match)",
             view={"filters": [_sel("anchor_type", "anchor_type"), _sel("stratum", "stratum")]}),
        Item("tables/memory_changelog_v2.csv", "Hazard differences around memory-related CHANGELOG entries (literal match)",
             view={"filters": [_sel("categories", "categories")]}),
        Item("tables/memory_v1_v2_v3.csv", "The three rules compared: how many anchor-match losses count as kept under literal and context match, and the main statistics of each"),
    ),
    patterns=("memory_*", "lineage*", "F6_*"),
    qa=("lineage_memory_v2", "lineage_memory", "lineage_memory_v3", "memory_prelabel", "pilot_lineage_memory"),
)

H1_TEST_COLUMNS = ["channel", "generations", "n_edges", "n_generations", "ad_stat", "z_vs_null", "p_perm", "n_perm"]

MODULE_B2 = Tab(
    "moduleB2", "Transmission trees", "Transmission trees: information passed between agents",
    "Information units (anchors and rare 4-grams) passed between chat, memory and search answers. The parent posterior is exposure × time term × exp(γ × shared non-root variants), with the MAP forest and 200 posterior samples. The main view counts generations between agents only, and retelling within one agent is reported as depth.",
    items=(
        Item("figures/F3_interval_ecdf.png", "Figure F3: ECDF of forward serial intervals between agents, by generation and channel",
             "Active hours on a log axis; only generations with at least 30 edges."),
        Item("figures/F4_tk_mean_variance.png", "Figure F4: mean and variance of T_k (time from the root to the k-th acquisition across agents) with weighted linear fits",
             "Points are observed values with root-clustered bootstrap 95% intervals."),
        Item("tables/trees_h1_tests_determined.csv", "Main serial-interval test: Anderson-Darling on determined paths (one candidate parent per edge)",
             "synthetic_type1 and synthetic_power are the type I error and power of the same test on synthetic data.",
             view={"columns": H1_TEST_COLUMNS + ["synthetic_type1", "synthetic_type1_lo", "synthetic_type1_hi",
                                                 "synthetic_power"]}),
        Item("tables/trees_h1_tests.csv", "Serial-interval test on the MAP forest, with its synthetic type I error",
             "On synthetic null trees this test rejects far more often than 5%, so it is shown for reference only.",
             view={"columns": H1_TEST_COLUMNS + ["synthetic_type1", "synthetic_type1_lo", "synthetic_type1_hi"]}),
        Item("tables/trees_restatement.csv", "Retelling chains within one agent: edges and depth by channel"),
        Item("tables/trees_h1_tests_occurrence_level.csv", "Reference: the serial-interval test when retellings count as generations"),
        Item("tables/trees_time_term.csv", "Time term: excitation kernel or empirical KDE for chat edges in each goal window",
             view={"filters": [_sel("scope", "Scope"), _sel("group", "Room")]}),
        Item("tables/trees_h1_intervals_determined.csv", "Forward serial intervals on determined paths by channel and generation (active hours)",
             view={"filters": [_sel("channel", "Layer"), _sel("reported", "reported", "true")]}),
        Item("tables/trees_h1_tk_determined.csv", "Mean, variance and linearity test of T_k on determined paths",
             view={"filters": [_sel("row_type", "row_type")]}),
        Item("tables/trees_h1_intervals.csv", "Forward serial intervals by channel and generation (active hours)",
             view={"filters": [_sel("channel", "Channel"), _sel("reported", "reported", "true")]}),
        Item("tables/trees_h1_tk.csv", "Mean, variance, median and linearity test of T_k",
             view={"filters": [_sel("row_type", "row_type")]}),
        Item("tables/trees_h1_adjacent.csv", "Spearman correlation of consecutive serial intervals"),
        Item("tables/trees_generations.csv", "Statistics by generation on the MAP forest: channel mix, offspring (observed and expected in a finite population), content change and independent acquisition"),
        Item("tables/trees_h3.csv", "Content change c by channel against memory consolidation",
             view={"filters": [_sel("source", "Source")]}),
        Item("tables/trees_ablation.csv", "Parent accuracy ablation: time only, content only, both, and baselines",
             view={"filters": [_sel("label_set", "Finding set", "name_tier1")]}),
        Item("tables/trees_gamma_grid.csv", "γ grid search (tier-1 name references and hand labels)"),
        Item("tables/trees_label_selection.csv", "Choosing the time term and γ on hand labels: accuracy on 15 first-author rows, 50 Claude rows and the combined set",
             view={"filters": [_sel("label_set", "Label set", "composite"), _sel("time_term", "Time term")]}),
        Item("tables/trees_synthetic.csv", "Synthetic validation: parent and generation accuracy, type I error and power of the serial-interval test",
             view={"filters": [_sel("scenario", "Scenario")]}),
        Item("tables/trees_posterior_samples.csv", "Medians and 95% ranges over 200 posterior samples"),
        Item("tables/trees_sensitivity.csv", "Sensitivity: no excitation kernel, γ = 1, content term between agents only, independent-observation rule, exposure rule, agent-level view, memory presence rule"),
        Item("tables/trees_parent_label_metrics.csv", "50 hand-labelled parents: accuracy of the MAP parent and of local model pre-labels",
             "Generated by `python -m avsd.lineage.prelabel_parents metrics` after data/labels/parents_review.csv is labelled."),
        Item("tables/trees_unit_summary.csv", "Information units by type: units, occurrences, units with transmissions, maximum generation"),
        Item("tables/trees_kernels.csv", "Time term: empirical interval distributions of single-candidate edges by channel"),
        Item("tables/trees_attractor.csv", "Attractor test: type-token ratio and similarity to the commonest wording by generation",
             view={"filters": [_sel("measure", "Metric")]}),
    ),
    expected=(("qa/lineage_trees.md", "QA reports"),),
    patterns=("trees_*", "F3_*", "F4_*", "transmission*"),
    qa=("lineage_trees", "pilot_lineage_trees", "parent_prelabel"),
)

MODULE_C = Tab(
    "moduleC", "Change points", "Change points: detection and alignment with the CHANGELOG",
    "Change points of each series by PELT (l2, rbf) and BOCPD, and whether they fall near CHANGELOG entries more often than chance.",
    items=(
        Item("figures/F5_changepoint_timeline.png", "Figure F5: change-point timeline",
             "Change points of each series as vertical lines, CHANGELOG entries and goal transitions on top; aligned and unaligned change points in two colours."),
        Item("tables/changepoints.csv", "Change points per run day and CHANGELOG entries",
             "Bars are change points per day, coloured by alignment; ticks on top are CHANGELOG entries and dots are village goal transitions. The chart follows the filters of the table below; click a bar to filter the table to that day, and click again to clear.", kind="cp_chart"),
        Item("tables/changepoints.csv", "Change-point table",
             "One row per change point and method: location with bootstrap interval, magnitude, nearest CHANGELOG entry, alignment (±w run days, w = 3) and cause label. PELT l2 by default; switch under Method.",
             view={"filters": CHANGEPOINT_FILTERS, "columns": CHANGEPOINT_COLUMNS}),
        Item("tables/changepoint_alignment.csv", "Alignment test",
             "S counts change points within ±w run days of an entry; null 1 shifts all entries together around the run days, null 2 places them uniformly at random, and p is one-sided. Holm corrections run within each method, change-point set, series set and w. The default view is the main result (PELT l2, all change points, all series, w = 3).",
             view={"filters": [_sel("method", "Method", "pelt_l2"), _sel("cp_set", "Change-point set", "all"),
                               _sel("series_set", "Series set", "all"), _sel("entry_set", "Entry set"),
                               _sel("w", "w", "3")],
                   "columns": ALIGNMENT_COLUMNS}),
        Item("tables/changepoint_series.csv", "Candidate series and change points per method",
             "Skipped series give the reason (too few points, constant, too short).",
             view={"filters": [{"type": "text", "col": "series_id", "label": "Series"}, _sel("level", "Level"),
                               _sel("skipped", "skipped")]}),
        Item("tables/lexical_words.csv", "Characteristic words of each model family",
             "Top 20 by log-odds ratio between families (z score), with use per thousand messages.",
             view={"filters": [_sel("family", "family")]}),
        Item("tables/changepoints_weekday_adjusted.csv", "PELT l2 change points of daily series after removing weekday effects",
             view={"filters": [{"type": "text", "col": "series_id", "label": "Series"},
                               {"type": "daterange", "col": "date", "label": "Date"}]}),
        Item("tables/monday_ratio.csv", "Monday against Tuesday-to-Friday ratio of family-level daily series"),
    ),
    patterns=("changepoint*", "lexical*", "monday*", "weekday*", "F5_*"),
    qa=("changepoint",),
)

MODULE_D = Tab(
    "moduleD", "Simulator and dependency graphs", "Simulator and dependency graphs: the swarm simulator and graphs of shared work",
    "The swarm simulator and the structure statistics of the AI Village dependency graphs.",
    items=(
        Item("figures/swarmsim_coverage.png", "Coverage curves for one agent and swarms of 4 to 64 agents",
             "a: standard swarm; b: three-level recursive swarm; x axis in multiples of the single-agent completion time T1 (log)."),
        Item("tables/swarmsim_reproduction.csv", "Simulator checks against the model's reference values",
             "A relative deviation up to 20% passes; ours is the mean over simulated families with a 95% interval and the 2.5% to 97.5% range of single families.",
             view={"filters": [_sel("status", "status"), _sel("required", "required")]}),
        Item("tables/swarmsim_scaling.csv", "Times to target and speedups by swarm size (family means with 95% intervals, in units of T1)",
             view={"filters": [_sel("kind", "kind"), _sel("n", "n")]}),
        Item("figures/F7_depgraph_generator.png", "Figure F7: AI Village dependency-graph statistics within the generator distribution",
             "Bars are the generator distribution (64 replicates, one DAG per goal with the goal's session count, pooled); solid lines are all AI Village edges and dashed lines write edges, pooled over goals. Touch rules v2."),
        Item("tables/depgraph_structure.csv", "Structure statistics: AI Village value, generator mean with 95% range, and quantile",
             "scope is pooled (all goals), goal_median or a single goal (G01 to G51); edges are all, write or read; parent counts cover nodes with at least one parent.",
             view={"filters": [_sel("scope", "scope", "pooled"), _sel("edges", "edges"),
                               _sel("statistic", "statistic")]}),
        Item("tables/depgraph_parent_counts.csv", "Parent-count distribution (shares with 1, 2, 3 and 4+ parents among nodes with parents)",
             view={"filters": [_sel("edges", "edges")]}),
        Item("tables/depgraph_goals.csv", "Graph size per goal: sessions, sessions with touches, edges (all, write, read), layers, root share, GUI focus gap (gui_gap) and touch share (touch_share)"),
        Item("tables/depgraph_cost_by_layer.csv", "Step cost by layer: turns and active minutes per session relative to the goal's layer 0",
             "blog_vs_layer0 is the ratio under the model cost c_d = 1 + 9d/(D-1); intervals are goal bootstraps.",
             view={"filters": [_sel("edges", "edges", "all"), _sel("axis", "axis")]}),
        Item("tables/depgraph_continuation.csv", "Continuation rate and random-parent baselines (agent bootstrap 95% intervals)",
             "with_parents counts pairs whose later session has a parent; window is the baseline's period (goal or run day); own_work draws only among artifacts the agent wrote.",
             view={"filters": [_sel("variant", "variant", "all"), _sel("window", "window"),
                               _sel("measure", "measure"), _sel("stratum", "stratum")]}),
        Item("tables/depgraph_rules.csv", "Read and write rules for actions (touch rules v2) with touches and sessions per rule"),
        Item("tables/depgraph_artifacts.csv", "Artifact types and edges; URLs show the registrable domain only"),
        Item("tables/depgraph_robustness.csv", "Robustness: pooled structure statistics (with generator quantiles), step-cost slopes and continuation rates (with baselines) on goals with a small GUI focus gap",
             "Subsets: gap under 20% or 10%, at least 80% of sessions with touches, goals from October 2025, without early GUI-heavy goals; the gap is the share of unattributed GUI writes among writes.",
             view={"filters": [_sel("subset", "subset", "full"), _sel("analysis", "analysis"),
                               _sel("edges", "edges", "all")]}),
        Item("tables/depgraph_sensitivity.csv", "Sensitivity: generator at the connected-node count or matched depth, exact key matching only, observed and mentioned identifiers counted as reads, structured artifacts only",
             view={"filters": [_sel("variant", "variant"), _sel("edges", "edges"), _sel("statistic", "statistic")]}),
        Item("figures/F7_depgraph_generator_v1.png", "Sensitivity: Figure F7 under touch rules v1 (first draft)"),
        Item("tables/depgraph_structure_v1.csv", "Sensitivity: structure statistics under touch rules v1",
             view={"filters": [_sel("scope", "scope", "pooled"), _sel("edges", "edges"),
                               _sel("statistic", "statistic")]}),
        Item("tables/depgraph_continuation_v1.csv", "Sensitivity: continuation rates and baselines under touch rules v1",
             view={"filters": [_sel("variant", "variant", "all"), _sel("window", "window"),
                               _sel("measure", "measure"), _sel("stratum", "stratum")]}),
        Item("tables/depgraph_gui_gap.csv", "Why GUI writes lack a focus: by action, month, phase, model family, position, text class and likely target",
             "unattributed_rate is the share of the group's GUI writes without a focus; share_of_unattributed is the group's share of all unattributed writes.",
             view={"filters": [_sel("table", "table", "target")]}),
        Item("tables/depgraph_gui_heuristics.csv", "Validation of the focus heuristics: accuracy when the known focus is hidden, and coverage of unattributed writes"),
        Item("tables/depgraph_gui_eras.csv", "Scaffold records by month: bash and GUI action shares, share of sessions using bash"),
    ),
    expected=(
        ("qa/swarmsim_d1.md", "QA report of the simulator checks"),
        ("qa/swarmsim_d2_d4.md", "QA report of the dependency graphs (`avsd swarmsim calibrate`, touch rules v2)"),
        ("qa/swarmsim_d2_d4_v1.md", "Sensitivity: QA report of the dependency graphs under touch rules v1 (`avsd swarmsim calibrate --rules v1`)"),
        ("qa/swarmsim_gui_gap.md", "Diagnosis of the GUI focus gap (`python scripts/depgraph_gui_gap.py`)"),
    ),
    patterns=("swarmsim*", "depgraph*", "dag*", "workdep*", "F7_*"),
    qa=("swarmsim_d1", "swarmsim_d2_d4", "swarmsim_d2_d4_v1", "swarmsim_gui_gap", "swarmsim"),
)

VALIDATION = Tab(
    "validation", "External validation", "External validation: the AI Village LLM monitor",
    "Findings of the AI Digest LLM monitor serve as an independent comparison: a second reading of the same days, not ground truth, used for annotation only (see docs/decisions.md). The first two comparisons use the excitation model (`python -m avsd.validate.monitor_hawkes`); the third uses the change points.",
    items=(
        Item("qa/monitor.md", "Monitor findings summary", "QA report of the fetch and parse; no personal names appear."),
        Item("qa/monitor_validation.md", "Comparisons 1 and 2: coverage and conclusions",
             "From the coverage and conclusion sections of monitor_validation.md; the full text is on the QA reports page.", kind="md_sections",
             sections=("2.", "9.")),
        Item("tables/monitor_v1.csv", "Comparison 1: parent sources of involved agents' messages within ±30 minutes of a finding, against their other messages in the same realization",
             "Posteriors are recomputed exactly from the excitation fit. Controls are the agent's messages in the same window, room and realization outside ±30 minutes of any finding involving it; differences are stratified by window, room, realization and agent, weighted by flagged messages, with realization bootstrap intervals.",
             view={"filters": [_sel("analysis", "analysis", "main"), _sel("subset", "subset"),
                               _sel("measure", "measure", "other_agents")]}),
        Item("tables/monitor_v2.csv", "Comparison 2: percentile of n_ij + n_ji of flagged agent pairs among all pairs of the fit window, and whether conflicts fall within one spectral cluster",
             "References are all agent pairs of the window (mean percentile 0.5 under uniform draws) and pairs of agents who spoke in that room that day; intervals resample finding dates, each with n from one excitation bootstrap replicate. Forced splits into k = 2, 3 and 4 clusters are sensitivity analyses only.",
             view={"filters": [_sel("part", "part"), _sel("subset", "subset"), _sel("unit", "unit"),
                               _sel("statistic", "statistic"), _sel("blocks", "blocks")]}),
        Item("tables/monitor_v2_pairs.csv", "Comparison 2: n, percentile (excitation bootstrap range) and finding counts of each flagged pair",
             "n_a_from_b is the expected number of messages of a triggered by one message of b; only AI agent names, category counts and dates appear.",
             view={"filters": HAWKES_WINDOW_FILTERS + [{"type": "text", "col": "agent_a", "label": "agent a"}]}),
        Item("tables/changepoint_alignment.csv", "Comparison 3: alignment of finding dates with change points",
             "Rows of changepoint_alignment.csv with the monitor entry set. Medium and high severity findings occur almost daily and cannot separate at w ≥ 1, so results with high severity only are reported too.",
             view={"filters": [_sel("method", "Method", "pelt_l2"), _sel("cp_set", "Change-point set"),
                               _sel("series_set", "Series set"), _sel("entry_set", "Entry set"), _sel("w", "w")],
                   "columns": ALIGNMENT_COLUMNS,
                   "fixed": [{"col": "entry_set", "op": "prefix", "value": "monitor"}]}),
        Item("tables/changepoints.csv", "Comparison 3: change points in the monitor period and nearby finding counts",
             "Change points in changepoints.csv with monitor notes: findings within ±w run days, by category and severity.",
             view={"filters": [{"type": "text", "col": "series_id", "label": "Series"},
                               _sel("method", "Method", "pelt_l2"), _sel("level", "Level"), _sel("cause", "cause"),
                               {"type": "daterange", "col": "date", "label": "Date"}],
                   "columns": ["series_id", "method", "run_day", "date", "magnitude_std", "cause",
                               "cause_documented", "monitor_covered_days", "monitor_n_findings",
                               "monitor_n_series_agents", "monitor_by_category", "monitor_by_severity"],
                   "fixed": [{"col": "monitor_n_findings", "op": "notnull"}]}),
    ),
    patterns=("monitor*", "validation*", "v1_*", "v2_*", "v3_*"),
    qa=("monitor",),
)

MODULE_TABS = (DATA, MODULE_A, MODULE_B1, MODULE_B2, MODULE_C, MODULE_D, VALIDATION)
TAB_LABELS = {"overview": "Overview", **{t.token: t.label for t in MODULE_TABS}, "qa": "QA reports"}
# Pipeline order for the QA tab; other reports follow by name, pilot runs last.
QA_ORDER = ("ingest", "build_events", "memory_versions", "monitor", "changepoint", "lineage_memory_v2",
            "lineage_memory", "lineage_memory_v3", "memory_prelabel",
            "lineage_trees", "parent_prelabel",
            "hawkes", "monitor_validation", "swarmsim_d1", "swarmsim_d2_d4", "swarmsim_d2_d4_v1",
            "swarmsim_gui_gap")
