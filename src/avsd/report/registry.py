"""What each report tab shows: known outputs with Chinese captions, expected files, and
name patterns that route new files to a tab automatically.

Paths are relative to outputs/. A known item whose file is missing is listed as
"尚未产出" in its tab; a file that matches no known item lands in the "其他文件"
section of the tab whose pattern it matches (first match wins), or of 总览.
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
    {"type": "text", "col": "series_id", "label": "序列"},
    _sel("method", "方法", "pelt_l2"),
    _sel("level", "层级"),
    _sel("aligned", "aligned"),
    _sel("cause", "cause"),
    _sel("cause_documented", "cause_documented"),
    {"type": "daterange", "col": "date", "label": "日期"},
]
ALIGNMENT_COLUMNS = [
    "method", "cp_set", "series_set", "entry_set", "holm_family", "w", "n_entries", "n_changepoints",
    "coverage_frac", "aligned", "aligned_frac", "null1_mean", "null1_q025", "null1_q975", "null1_p",
    "null1_p_holm", "null2_mean", "null2_q025", "null2_q975", "null2_p", "null2_p_holm",
]

DATA = Tab(
    "data", "数据与事件表", "数据与事件表",
    "原始表转 parquet、统一事件表、运行时段、roster 与 CHANGELOG。parquet 文件都在 data/ 下，"
    "不进入本报告；这里展示 QA 报告中的主要表格。",
    items=(
        Item("qa/ingest.md", "各表转 parquet 的行数核对",
             "解析自 ingest.md 各表小节：读入与写出行数、manifest 行数及差值、重复 id、无法解析的行、"
             "时间戳解析失败数。", kind="ingest"),
        Item("qa/build_events.md", "统一事件表：行数对账与 actor 分布",
             "摘自 build_events.md 第 1、2 节。", kind="md_sections", sections=("1.", "2.")),
        Item("qa/memory_versions.md", "memory 版本关系（路径 S）",
             "摘自 memory_versions.md 的前两节。", kind="md_sections",
             sections=("Previous-row classes", "Relations")),
        Item("tables/changelog_review.md", "CHANGELOG 条目与分类",
             "变更条目与 roster 加入、离开记录，分类经用户 9 月 30 日确认。", kind="md_table",
             view={"filters": [_sel("tags", "tags"), _sel("categories", "categories"),
                               _sel("flags", "flags")]}),
    ),
    patterns=("changelog*", "ingest*", "build_events*", "events*", "run_periods*", "pause_segments*",
              "roster*", "agents*", "memory_versions*", "rooms*"),
    qa=("ingest", "build_events", "memory_versions"),
)

HAWKES_WINDOW_FILTERS = [{"type": "text", "col": "window_id", "label": "窗口"}, _sel("group", "group")]

MODULE_A = Tab(
    "moduleA", "聊天激发", "聊天激发：多元 Hawkes 过程",
    "agent 事件分解为基线、人类触发、其他 agent 触发与自激；激发矩阵 N、agent 子系统的谱半径和块结构。"
    "主窗口按 village goal 划分，按聊天室（占窗口 agent 消息 10% 以上）分组拟合；agent 只在其在场的实现"
    "（该运行块内在该聊天室有行）上计基线与核暴露；核按来源类别共享，三起点，Newton 收敛认证；"
    "区间来自 1,000 次按运行日期的 bootstrap，每次取三起点与全数据拟合起点中目标值最高者。",
    items=(
        Item("figures/F1_excitation.png", "图 F1：各主窗口的激发矩阵 N",
             "行为目标 agent，列为来源 agent（按谱聚类分组排序，红线为组界），其后为 human 与 system；色阶为平方根。"),
        Item("figures/F2_activity_shares.png", "图 F2：agent 消息三部分比例随时期的变化",
             "agent 触发（其他 agent 与本人）、human 与 system、基线；R2 时期 best 与 rest 按每运行日事件数加权合并；"
             "斜线带为 95% bootstrap 区间。"),
        Item("tables/hawkes_windows.csv", "各主窗口：分解比例与 95% 区间、谱半径、恢复检验与收敛证书",
             "mae4 为 SPEC 5.6-1 恢复检验的平均误差（20 次重复，距门槛 2 个标准误以内时 40 次），"
             "recovery_* 为各比例与 n 的偏差；matched 为匹配真值各臂的 mae4 范围；"
             "K_part_time 为在场少于 80% 实现的 agent 数，rho_core 为其余 agent 的谱半径；"
             "children_* 为各核类别的期望子代数，少于 50 时 identified 为 false。",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_decomposition.csv", "分解比例：五类（基线、human、system、其他 agent、本人）与 SPEC 四类",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("scheme", "scheme", "five_way"),
                                                       _sel("category", "category")]}),
        Item("tables/hawkes_excitation.csv", "激发矩阵 n_ij 与 95% 区间（行为目标 agent，列为来源）",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("source_class", "source_class"),
                                                       {"type": "text", "col": "target", "label": "目标"}]}),
        Item("tables/hawkes_blocks.csv", "N_AA 的谱聚类分组，组内与组间 n_ij 均值",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_acceptance.csv", "SPEC 5.6-1 恢复检验与窗口合并记录（每轮）",
             view={"filters": [_sel("round", "round"), _sel("passed", "passed")] + HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_matched.csv", "匹配真值臂的恢复误差（各窗口、各臂）",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("arm", "arm")]}),
        Item("tables/hawkes_sensitivity.csv", "敏感性：L = 1、6 小时，G = 15、60 分钟，低计数外部来源核形绑定，"
             "以及只含常在 agent 的谱半径（core）",
             view={"filters": HAWKES_WINDOW_FILTERS + [_sel("variant", "variant")]}),
        Item("figures/hawkes_qq.png", "time-rescaling QQ 图（SPEC 5.6-2）",
             "深色为窗口内全部 agent，浅色为单个 agent。"),
        Item("tables/hawkes_gof.csv", "time-rescaling：每个 agent 维度的 KS 统计量",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_reference_check.csv", "显式引用对照（SPEC 5.6-3）：最可能父事件与 tier-1 标注的一致率",
             "基线为同一聊天室中最近一条他人消息；区间为按运行日的聚类 bootstrap。"),
        Item("tables/hawkes_opportunity.csv", "行动机会模型（SPEC 5.6-4）与 Hawkes 的 j→i 排序的 Spearman 相关",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_opportunity_disagreements.csv", "两种排序不一致的 agent 对",
             view={"filters": HAWKES_WINDOW_FILTERS}),
        Item("tables/hawkes_rolling_windows.csv", "滚动窗口（5 个运行日）的拟合结果，供变点检测",
             view={"filters": [_sel("group", "group"), _sel("fitted", "fitted")]}),
    ),
    expected=(("tables/hawkes_*.csv", "激发模型的结果表（`avsd hawkes fit` 产出；parquet 表与父事件概率不嵌入）"),),
    patterns=("hawkes*", "F1_*", "F2_*", "excitation*"),
    qa=("hawkes",),
)

MODULE_B1 = Tab(
    "moduleB1", "记忆保留", "记忆保留：memory 中的事实单元",
    "事实单元在逐次 consolidation 中的保留、丢失与修改；H2 检验风险率是否随代数保持不变。"
    "主口径为规则 v2（2026-10-03 按用户抽查标注选定，丢失识别 F1 最高）；v1、v3 的同名表（无后缀、_v3）作为敏感性分析，"
    "列在本页末尾的其他文件中。",
    items=(
        Item("figures/F6_memory_retention_v2.png", "图 F6：各模型家族的 memory 保留曲线与几何分布拟合（规则 v2）"),
        Item("tables/memory_h2_v2.csv", "H2 检验：几何分布（常数风险率）对分段常数风险率（规则 v2）",
             "似然比检验把单元当作独立，Wald 检验用按 agent 的聚类 bootstrap 协方差；另比较 beta-几何模型的 AIC。",
             view={"filters": SCOPE_FILTERS + [_sel("ci_method", "ci_method")],
                   "columns": ["scope", "stratum", "n_agents", "n_units", "n_trials", "h_geometric", "h1",
                               "h1_lo", "h1_hi", "h2", "h3_4", "h5_8", "h9plus", "lr", "df", "p_lr",
                               "wald_cluster", "p_wald_cluster", "aic_geometric", "aic_betageom",
                               "aic_piecewise", "ci_method"]}),
        Item("tables/memory_hazard_v2.csv", "按代数 g 的丢失风险率 h_g 与 95% 置信区间（规则 v2）",
             view={"filters": FAMILY_FILTERS + [_sel("ci_method", "ci_method")]}),
        Item("tables/memory_post_switch_rise.csv", "切换到持续 computer use 之后 h2 − h1 的配对检验（三版规则）",
             "同一组按 agent 重抽样的 bootstrap 上同时计算 h1 和 h2；只有 v2 的区间不含 0。"),
        Item("tables/memory_label_metrics.csv", "标注校验：三版规则与各模型相对用户抽查标注的精确率、召回率与 F1",
             "主结果为 scheme = weighted：用户盲标的 60 个分层抽查单元，按入样概率加权到 500 个校验单元；"
             "weighted_owner71 加入用户另标的 11 行，weighted_claude277 以 Claude 的 277 行盲标为准。",
             view={"filters": [_sel("scheme", "scheme", "weighted"), _sel("label", "label"),
                               _sel("metric", "metric")],
                   "columns": ["scheme", "label", "metric", "rule", "rule_lo", "rule_hi", "rule_v2", "rule_v2_lo",
                               "rule_v2_hi", "rule_v3", "rule_v3_lo", "rule_v3_hi", "v2_minus_v1",
                               "v2_minus_v1_lo", "v2_minus_v1_hi", "llm", "qwen35_122b", "gptoss_120b",
                               "gemini", "claude", "claude_lo", "claude_hi", "n_labelled"]}),
        Item("tables/memory_retention_v2.csv", "离散保留曲线（Kaplan-Meier 形式）与几何、beta-几何拟合值（规则 v2）",
             view={"filters": FAMILY_FILTERS}),
        Item("tables/memory_modification_v2.csv", "修改率随代数的变化，以及修改在丢失中的占比（规则 v2）",
             view={"filters": FAMILY_FILTERS}),
        Item("tables/memory_by_anchor_v2.csv", "按锚点类型分层的风险率、修改率与恢复率（规则 v2）",
             view={"filters": [_sel("anchor_type", "anchor_type"), _sel("stratum", "stratum")]}),
        Item("tables/memory_changelog_v2.csv", "memory 类 CHANGELOG 条目前后的风险率差与置信区间（规则 v2）",
             view={"filters": [_sel("categories", "categories")]}),
        Item("tables/memory_v1_v2_v3.csv", "三版规则的对照：v1 的丢失有多少在 v2、v3 下算保留，以及各版的主要统计量"),
    ),
    patterns=("memory_*", "lineage*", "F6_*"),
    qa=("lineage_memory_v2", "lineage_memory", "lineage_memory_v3", "memory_prelabel", "pilot_lineage_memory"),
)

H1_TEST_COLUMNS = ["channel", "generations", "n_edges", "n_generations", "ad_stat", "z_vs_null", "p_perm", "n_perm"]

MODULE_B2 = Tab(
    "moduleB2", "传播树", "传播树：agent 之间的信息传播",
    "信息单元（锚点与低频 4-gram）在聊天、memory 与查历史答案之间的传播。父节点后验 = 暴露约束 × 时间项 × "
    "exp(γ × 共有非根变化数)，取 MAP 树并做 200 次后验抽样。主视图是 agent 之间的传播：一代是跨一次 agent，"
    "同一 agent 的复述不加代数，另以复述深度报告。H1 检验各代序列间隔是否相同（按核键分层），以确定路径上的检验"
    "为主结论；H3 比较 agent 之间复述与 B1 memory 链的内容变化率。表中只有聚合数，单元以加密 id 表示。",
    items=(
        Item("figures/F3_interval_ecdf.png", "图 F3：agent 之间的前向序列间隔 ECDF，按 agent 级代数分组、按层分面",
             "横轴为 active 小时（对数），只画边数不少于 30 的代。"),
        Item("figures/F4_tk_mean_variance.png", "图 F4：T_k（从树根到第 k 次跨 agent 获得的时间）的均值与方差及加权线性拟合",
             "点为观测值与按根节点的 cluster bootstrap 95% 置信区间。"),
        Item("tables/trees_h1_tests_determined.csv", "H1 主结论：确定路径上（每条边只有一个候选父节点）的 Anderson-Darling 检验",
             "synthetic_type1 与 synthetic_power 是同一检验在合成数据上的第一类错误率与功效。",
             view={"columns": H1_TEST_COLUMNS + ["synthetic_type1", "synthetic_type1_lo", "synthetic_type1_hi",
                                                 "synthetic_power"]}),
        Item("tables/trees_h1_tests.csv", "H1：MAP 树上的检验，附其合成第一类错误率",
             "合成零假设下 MAP 树上的检验拒绝率远高于 5%，所以不作为 H1 的证据，只并列展示。",
             view={"columns": H1_TEST_COLUMNS + ["synthetic_type1", "synthetic_type1_lo", "synthetic_type1_hi"]}),
        Item("tables/trees_restatement.csv", "同一 agent 的复述链：各渠道的复述边数与复述深度分布"),
        Item("tables/trees_h1_tests_occurrence_level.csv", "参考：把复述也算作代数时的 H1 检验与合成第一类错误率"),
        Item("tables/trees_time_term.csv", "时间项：各 goal 窗口的聊天边用激发模型的核还是经验 KDE（候选边与 MAP 边）",
             view={"filters": [_sel("scope", "范围"), _sel("group", "房间")]}),
        Item("tables/trees_h1_intervals_determined.csv", "确定路径上各层、各代的前向序列间隔（active 小时）",
             view={"filters": [_sel("channel", "层"), _sel("reported", "reported", "true")]}),
        Item("tables/trees_h1_tk_determined.csv", "确定路径上 T_k 的均值、方差与线性检验",
             view={"filters": [_sel("row_type", "row_type")]}),
        Item("tables/trees_h1_intervals.csv", "各渠道、各代的前向序列间隔（active 小时）",
             view={"filters": [_sel("channel", "渠道"), _sel("reported", "reported", "true")]}),
        Item("tables/trees_h1_tk.csv", "T_k 的均值、方差、中位数与线性检验",
             view={"filters": [_sel("row_type", "row_type")]}),
        Item("tables/trees_h1_adjacent.csv", "相邻两代序列间隔的 Spearman 相关"),
        Item("tables/trees_generations.csv", "MAP 树逐代统计：渠道构成、后代数（实测与有限人数下的期望）、内容变化率、独立得到比例"),
        Item("tables/trees_h3.csv", "H3：各渠道的内容变化率 c 与 B1 memory 链对照",
             view={"filters": [_sel("source", "来源")]}),
        Item("tables/trees_ablation.csv", "父节点准确率消融：只用时间、只用内容、两者结合与基线",
             view={"filters": [_sel("label_set", "标注集", "name_tier1")]}),
        Item("tables/trees_gamma_grid.csv", "γ 网格搜索（一级点名标签与人工标签）"),
        Item("tables/trees_label_selection.csv", "用人工标签选时间项与 γ：用户 15 行、Claude 50 行与合并集上的准确率",
             view={"filters": [_sel("label_set", "标签集", "composite"), _sel("time_term", "时间项")]}),
        Item("tables/trees_synthetic.csv", "合成验证：父节点与代数准确率、H1 在零假设下的第一类错误率与功效",
             view={"filters": [_sel("scenario", "场景")]}),
        Item("tables/trees_posterior_samples.csv", "200 次后验抽样中各统计量的中位数与 95% 区间"),
        Item("tables/trees_sensitivity.csv", "敏感性：关掉激发模型的核、γ = 1、只计 agent 之间的内容项、独立观察规则、"
             "暴露规则、agent 级视图、B1 规则版本"),
        Item("tables/trees_parent_label_metrics.csv", "人工标注的 50 个父节点：MAP 与本地模型预标的准确率",
             "用户在 data/labels/parents_review.csv 标完后由 `python -m avsd.lineage.prelabel_parents metrics` 生成。"),
        Item("tables/trees_unit_summary.csv", "信息单元按类型汇总：单元数、出现数、有传播边的单元、最大代数"),
        Item("tables/trees_kernels.csv", "时间项：各渠道单一候选边的经验间隔分布"),
        Item("tables/trees_attractor.csv", "吸引子检验：type-token ratio 与最常见表述相似度随代数的变化",
             view={"filters": [_sel("measure", "指标")]}),
    ),
    expected=(("qa/lineage_trees.md", "QA 报告"),),
    patterns=("trees_*", "F3_*", "F4_*", "transmission*"),
    qa=("lineage_trees", "pilot_lineage_trees", "parent_prelabel"),
)

MODULE_C = Tab(
    "moduleC", "变点", "变点：变点检测与 CHANGELOG 对齐",
    "PELT（l2、rbf）与 BOCPD 检测各序列的变点，检验变点是否比随机更多地落在 CHANGELOG 条目附近。",
    items=(
        Item("figures/F5_changepoint_timeline.png", "图 F5：变点时间线",
             "各序列的变点为竖线，顶部为 CHANGELOG 条目与 goal 切换，对齐与未对齐的变点用两种颜色。"),
        Item("tables/changepoints.csv", "每个运行日的变点数与 CHANGELOG 条目",
             "柱为当天的变点数，按是否对齐分色；顶部短线为 CHANGELOG 条目（数据来自 changelog_review.md），"
             "圆点为 village goal 切换（取自 nearest_goal_transition_date）。"
             "图随下方变点表的筛选更新，点击柱子把表格筛到当天，再点一次取消。", kind="cp_chart"),
        Item("tables/changepoints.csv", "变点表",
             "每个变点与方法一行：位置与 bootstrap 置信区间、幅度、最近的 CHANGELOG 条目、是否对齐（±w 个运行日，"
             "w = 3）与原因标注。默认只看 PELT l2，可在“方法”中切换。",
             view={"filters": CHANGEPOINT_FILTERS, "columns": CHANGEPOINT_COLUMNS}),
        Item("tables/changepoint_alignment.csv", "对齐检验",
             "S 为落在任一条目 ±w 个运行日内的变点数；零分布一整体循环平移条目，零分布二均匀随机放置条目，"
             "p 为单侧。Holm 在同一方法、变点集、序列集和 w 内，分别对 CHANGELOG 类别行、goal 与 monitor 行校正"
             "（all 与 scaffolding 为汇总行，不校正）。默认显示 SPEC 主结果（PELT l2、全部变点、全部序列、w = 3）。",
             view={"filters": [_sel("method", "方法", "pelt_l2"), _sel("cp_set", "变点集", "all"),
                               _sel("series_set", "序列集", "all"), _sel("entry_set", "条目集"),
                               _sel("w", "w", "3")],
                   "columns": ALIGNMENT_COLUMNS}),
        Item("tables/changepoint_series.csv", "候选序列与各方法的变点数",
             "跳过的序列注明原因（点数太少、常数、太短）。",
             view={"filters": [{"type": "text", "col": "series_id", "label": "序列"}, _sel("level", "层级"),
                               _sel("skipped", "skipped")]}),
        Item("tables/lexical_words.csv", "各模型家族的特征词",
             "按家族之间的对数几率比（z 值）选前 20 个，附每千条消息的使用率。",
             view={"filters": [_sel("family", "family")]}),
        Item("tables/changepoints_weekday_adjusted.csv", "去除星期几效应后日序列的 PELT l2 变点（第三轮）",
             view={"filters": [{"type": "text", "col": "series_id", "label": "序列"},
                               {"type": "daterange", "col": "date", "label": "日期"}]}),
        Item("tables/monday_ratio.csv", "家族层面日序列的周一与周二至周五之比（第三轮）"),
    ),
    patterns=("changepoint*", "lexical*", "monday*", "weekday*", "F5_*"),
    qa=("changepoint",),
)

MODULE_D = Tab(
    "moduleD", "模拟与依赖图", "模拟与依赖图：swarm 模拟的复现与工作依赖图",
    "按 Wenhao Chai 的博文 Predictable Swarm Scaling 重写的模拟器（D1），以及 AI Village 工作依赖图的结构统计"
    "（D2 至 D4）。",
    items=(
        Item("figures/swarmsim_coverage.png", "D1：单个 agent 与 4 至 64 个 agent 的覆盖度曲线",
             "a 为标准 swarm，b 为三层递归 swarm；横轴为单 agent 完成时间 T₁ 的倍数（对数）。"),
        Item("tables/swarmsim_reproduction.csv", "D1 复现检查：与博文数值的对照",
             "相对偏差不超过 20% 记为 pass；ours 为多个模拟家族的均值，"
             "附 95% 置信区间与单个家族的 2.5% 至 97.5% 范围。",
             view={"filters": [_sel("status", "status"), _sel("required", "required")]}),
        Item("tables/swarmsim_scaling.csv", "D1 各规模的达到时间与加速比（家族均值与 95% 置信区间，时间以 T₁ 为单位）",
             view={"filters": [_sel("kind", "kind"), _sel("n", "n")]}),
        Item("figures/F7_depgraph_generator.png", "图 F7：AI Village 依赖图的各项统计在生成器分布中的位置",
             "柱为生成器分布（64 次重复，每次每个 goal 生成一张与该 goal session 数相同的 DAG，合并计算）；"
             "实线为 AI Village 全部边，虚线为写入边，均为各 goal 合并后的值。接触规则为 v2，用户 10 月 1 日确认。"),
        Item("tables/depgraph_structure.csv", "D3 结构统计：AI Village 值、生成器均值与 95% 范围、分位数",
             "scope 为 pooled（各 goal 合并）、goal_median（各 goal 中位数）或单个 goal（G01 至 G51）；"
             "edges 为 all、write、read；父节点数按至少有一个父节点的节点计。",
             view={"filters": [_sel("scope", "scope", "pooled"), _sel("edges", "edges"),
                               _sel("statistic", "statistic")]}),
        Item("tables/depgraph_parent_counts.csv", "D3 父节点数分布（至少有一个父节点的节点中 1、2、3、4+ 个父节点的比例）",
             view={"filters": [_sel("edges", "edges")]}),
        Item("tables/depgraph_goals.csv", "D2 各 goal 的依赖图规模：session 数、有接触的 session、边数（全部、写入、读取）、"
             "层数、根节点比例，以及 GUI 焦点缺口（gui_gap）与接触比例（touch_share）"),
        Item("tables/depgraph_cost_by_layer.csv", "D3 步骤代价与层数：session 的 turn 数与活跃分钟数（相对本 goal 第 0 层）",
             "blog_vs_layer0 为博文设定 c_d = 1 + 9d/(D-1) 下的比值；区间为按 goal 的 bootstrap。",
             view={"filters": [_sel("edges", "edges", "all"), _sel("axis", "axis")]}),
        Item("tables/depgraph_continuation.csv", "D4 延续率与随机选择基线（按 agent 的 bootstrap 95% 区间）",
             "with_parents 为下一个 session 至少有一个父节点的配对；window 为基线的可接触时期（goal 或运行日）；"
             "own_work 只在本人写过的 artifact 中随机选择。",
             view={"filters": [_sel("variant", "variant", "all"), _sel("window", "window"),
                               _sel("measure", "measure"), _sel("stratum", "stratum")]}),
        Item("tables/depgraph_rules.csv", "D2 动作读写分类规则（规则 v2，用户 10 月 1 日确认）与各规则的接触数、session 数"),
        Item("tables/depgraph_artifacts.csv", "D2 artifact 类型与边数；URL 只显示注册域名"),
        Item("tables/depgraph_robustness.csv", "稳健性：在 GUI 焦点缺口小的 goal 子集上重算 D3 合并统计（含生成器分位数）、"
             "步骤代价斜率与 D4 延续率（含基线）",
             "子集：缺口低于 20% 或 10%、至少 80% 的 session 有接触、2025-10 起的 goal、去掉早期以 GUI 为主的 goal；"
             "缺口为未归属 GUI 写入占写入动作的比例。",
             view={"filters": [_sel("subset", "subset", "full"), _sel("analysis", "analysis"),
                               _sel("edges", "edges", "all")]}),
        Item("tables/depgraph_sensitivity.csv", "敏感性：生成器按连通节点数或匹配层数、只按 key 精确匹配、"
             "把输出中观察到与文字中提到的标识计为读取、只用结构化 artifact",
             view={"filters": [_sel("variant", "variant"), _sel("edges", "edges"), _sel("statistic", "statistic")]}),
        Item("figures/F7_depgraph_generator_v1.png", "敏感性：图 F7（接触规则 v1，最初的草案）"),
        Item("tables/depgraph_structure_v1.csv", "敏感性：D3 结构统计（接触规则 v1）",
             view={"filters": [_sel("scope", "scope", "pooled"), _sel("edges", "edges"),
                               _sel("statistic", "statistic")]}),
        Item("tables/depgraph_continuation_v1.csv", "敏感性：D4 延续率与基线（接触规则 v1）",
             view={"filters": [_sel("variant", "variant", "all"), _sel("window", "window"),
                               _sel("measure", "measure"), _sel("stratum", "stratum")]}),
        Item("tables/depgraph_gui_gap.csv", "GUI 写入缺少焦点的原因：按动作、月份、阶段、模型家族、位置、文本类别与可能目标分解",
             "unattributed_rate 为该组 GUI 写入中没有焦点的比例，share_of_unattributed 为该组占全部未归属写入的比例。",
             view={"filters": [_sel("table", "table", "target")]}),
        Item("tables/depgraph_gui_heuristics.csv", "焦点启发式的验证：在已知焦点的写入上隐藏焦点后的准确率，以及对未归属写入的覆盖率"),
        Item("tables/depgraph_gui_eras.csv", "各月脚手架记录：bash 与 GUI 动作占比、使用 bash 的 session 比例"),
    ),
    expected=(
        ("qa/swarmsim_d1.md", "D1 的 QA 报告"),
        ("qa/swarmsim_d2_d4.md", "D2 至 D4 的 QA 报告（`avsd swarmsim calibrate`，接触规则 v2）"),
        ("qa/swarmsim_d2_d4_v1.md", "敏感性：接触规则 v1 下 D2 至 D4 的 QA 报告（`avsd swarmsim calibrate --rules v1`）"),
        ("qa/swarmsim_gui_gap.md", "GUI 写入焦点缺口的诊断报告（`python scripts/depgraph_gui_gap.py`）"),
    ),
    patterns=("swarmsim*", "depgraph*", "dag*", "workdep*", "F7_*"),
    qa=("swarmsim_d1", "swarmsim_d2_d4", "swarmsim_d2_d4_v1", "swarmsim_gui_gap", "swarmsim"),
)

VALIDATION = Tab(
    "validation", "外部验证", "外部验证：AI Village LLM monitor（V1–V3）",
    "AI Digest 的 LLM monitor 标注作为独立对照：它是对同一批日子的另一次阅读，不是标准答案，只作注释，不作原因"
    "（方案见 docs/decisions.md）。V1、V2 对照激发模型（`python -m avsd.validate.monitor_hawkes`），V3 在变点检测中。",
    items=(
        Item("qa/monitor.md", "monitor 标注汇总", "抓取与解析的 QA 报告，人名不出现。"),
        Item("qa/monitor_validation.md", "V1、V2：覆盖与结论摘要",
             "摘自 monitor_validation.md 的覆盖与结论两节，全文见 QA 报告页。", kind="md_sections",
             sections=("2.", "9.")),
        Item("tables/monitor_v1.csv", "V1：标注 ±30 分钟内涉事 agent 消息的父事件来源比例，与同一实现中其余消息之差",
             "后验按激发模型的拟合精确重算（hawkes_parents.parquet 只存概率 ≥ 0.01 的父事件）。对照为同一窗口、"
             "聊天室与实现中，该 agent 不在任何涉及它的 V1 标注 ±30 分钟内的消息；差值按（窗口、聊天室、实现、agent）"
             "分层，以标注消息数加权，区间为按实现重抽的 bootstrap。measure 为 other_msgs_10min 的行是前 10 分钟内"
             "其他 agent 的消息数，作候选父事件密度的参照。",
             view={"filters": [_sel("analysis", "analysis", "main"), _sel("subset", "subset"),
                               _sel("measure", "measure", "other_agents")]}),
        Item("tables/monitor_v2.csv", "V2：被标注 agent 对的 n_ij + n_ji 在同一拟合窗口全部 agent 对中的百分位，"
             "以及冲突是否落在同一谱聚类内",
             "参照为窗口内全部 agent 对（均匀抽取时百分位均值为 0.5）与当天在该聊天室发过言的 agent 之间的对；"
             "区间按标注日期重抽，每次取激发模型一个 bootstrap 重复中的 n。激发模型的特征间隙规则只分出一个聚类的窗口里，"
             "组内比例与按聚类大小的期望都是 1；强制 k = 2、3、4 的划分只是敏感性分析。",
             view={"filters": [_sel("part", "part"), _sel("subset", "subset"), _sel("unit", "unit"),
                               _sel("statistic", "statistic"), _sel("blocks", "blocks")]}),
        Item("tables/monitor_v2_pairs.csv", "V2：各被标注 agent 对的 n、百分位（激发模型 bootstrap 范围）与标注计数",
             "n_a_from_b 为 b 的一条消息引发 a 的期望消息数；表中只有 AI agent 名、类别计数与日期。",
             view={"filters": HAWKES_WINDOW_FILTERS + [{"type": "text", "col": "agent_a", "label": "agent a"}]}),
        Item("tables/changepoint_alignment.csv", "V3：monitor 标注日期与变点的对齐检验",
             "changepoint_alignment.csv 中条目集为 monitor 的行。中、高严重度标注几乎每天都有，"
             "w ≥ 1 时无法区分，另报告只用高严重度的结果。",
             view={"filters": [_sel("method", "方法", "pelt_l2"), _sel("cp_set", "变点集"),
                               _sel("series_set", "序列集"), _sel("entry_set", "条目集"), _sel("w", "w")],
                   "columns": ALIGNMENT_COLUMNS,
                   "fixed": [{"col": "entry_set", "op": "prefix", "value": "monitor"}]}),
        Item("tables/changepoints.csv", "V3：monitor 覆盖期内的变点与附近的标注计数",
             "changepoints.csv 中有 monitor 注释的变点：±w 个运行日内的标注数、按类别与严重度的计数。",
             view={"filters": [{"type": "text", "col": "series_id", "label": "序列"},
                               _sel("method", "方法", "pelt_l2"), _sel("level", "层级"), _sel("cause", "cause"),
                               {"type": "daterange", "col": "date", "label": "日期"}],
                   "columns": ["series_id", "method", "run_day", "date", "magnitude_std", "cause",
                               "cause_documented", "monitor_covered_days", "monitor_n_findings",
                               "monitor_n_series_agents", "monitor_by_category", "monitor_by_severity"],
                   "fixed": [{"col": "monitor_n_findings", "op": "notnull"}]}),
    ),
    patterns=("monitor*", "validation*", "v1_*", "v2_*", "v3_*"),
    qa=("monitor",),
)

MODULE_TABS = (DATA, MODULE_A, MODULE_B1, MODULE_B2, MODULE_C, MODULE_D, VALIDATION)
TAB_LABELS = {"overview": "总览", **{t.token: t.label for t in MODULE_TABS}, "qa": "QA 报告"}
# Pipeline order for the QA tab; other reports follow by name, pilot runs last.
QA_ORDER = ("ingest", "build_events", "memory_versions", "monitor", "changepoint", "lineage_memory_v2",
            "lineage_memory", "lineage_memory_v3", "memory_prelabel",
            "lineage_trees", "parent_prelabel",
            "hawkes", "monitor_validation", "swarmsim_d1", "swarmsim_d2_d4", "swarmsim_d2_d4_v1",
            "swarmsim_gui_gap")
