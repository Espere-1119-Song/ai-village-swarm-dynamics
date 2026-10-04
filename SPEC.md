# AI Village swarm 动态分析：项目说明

版本 v1，2026-09-30。负责人 Enxin Song。执行者 Claude Code。本文档放在仓库根目录，文件名 `SPEC.md`。

## 0. 执行约定

1. 开始前通读全文，按第 11 节的优先级推进。P0 全部完成前不开始 P2。
2. 仓库根目录维护 `PROGRESS.md`（中文）。任务状态只用四种标签：Completed、In progress、Not started、Blocked。每完成一个任务，写明产出文件路径和验收结果。
3. 本文档中的字段名来自数据集说明页，尚未核实。使用任何字段前先读 `SCHEMA.md`，把真实字段写入 `docs/schema_notes.md`。两者不一致时以 `SCHEMA.md` 为准，并记录差异。
4. 设计决定（阈值、分类规则、默认参数的改动）写入 `docs/decisions.md`，注明理由和日期。
5. 以下操作先询问用户：下载超过 30 GB 的截图，任何按量计费的 API 调用，提交多节点作业，公开 GitHub 仓库，修改第 1.3 节的研究问题。
6. 每一步的输出写成带明确 schema 的 parquet，并附一份 markdown 格式的 QA 报告，内容包括行数、时间范围、缺失值和与预期值的对比。
7. 所有随机过程固定随机种子，种子写入 config。
8. 代码、注释和 write-up 用英文。`PROGRESS.md` 和给用户的问题用中文。
9. 第一个任务：建立 3.1 的仓库结构，然后执行 4.1 的第 1 步。

### 0.2 数据使用条款（所有涉及数据的步骤都适用）

- 数据只用于研究和分析。未经 AI Digest 书面许可，不用这些数据训练或微调任何 AI 系统。本项目中的嵌入模型、LLM 和 VLM 只做推理。
- 不尝试识别任何个人。人类发言者在所有输出中只以 `human` 类别出现，不输出人名、邮箱、电话和账号名。
- 发现未脱敏的凭证时，记录位置并告知用户，不使用该凭证。
- 公开仓库只包含代码、配置和聚合结果。原始数据、截图、消息全文、标注文件和中间 parquet 文件都放在 `data/` 下，并写入 `.gitignore`。write-up 引用消息时用改写后的摘要，确需原文时只保留短片段，并去掉个人信息。
- 代码、报告和 write-up 中注明引用：AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village 。

## 1. 背景与目标

### 1.1 Hackathon

- AI Swarm Dynamics Hackathon（AI Village 与 Grove Research 联合举办），2026 年 10 月 3 日至 4 日，用户线上参赛。
- 主题是做帮助理解和发现 agent swarm 的工具。背景是 OpenAI 与 Hugging Face 事件以及德语 Wiki 事件中缺少分析大量 agent 协同行为的工具。
- 提交截止：10 月 4 日（周日）21:00 PT，即 10 月 5 日 00:00 ET。
- 提交内容：简短的说明文档或视频，GitHub 仓库链接，以及可选的真实结果报告（用工具在数据中得到的结果）。
- 规则允许提前开始。

### 1.2 项目目标

项目暂定名 `ai-village-swarm-dynamics`。把 AI Village 一年半的多 agent 日志转成一张统一事件表，在上面完成以下测量，并把测量整理成可复用的工具。

1. agent 之间谁的活动引发谁的活动，以及 agent 活动中由基线、人类、其他 agent 触发的比例（模块 A）。
2. 信息在 agent 之间和 agent 自身 memory 中逐代传递时，每代的时间间隔和内容变化是否与代数无关（模块 B）。
3. 行为指标的变点中，哪些与 CHANGELOG 记录的 scaffolding 变更对齐，哪些没有对应的变更（模块 C）。
4. 用 AI Village 的真实任务依赖图检验和校准 Wenhao Chai 的 swarm 模拟器（模块 D）。
5. 可选：从截图序列得到各模型的行为谱（模块 E）。

英文概述（write-up 可直接使用）：

> A toolkit that turns the AI Village logs into one unified event table and measures (1) who triggers whom, using a multivariate Hawkes process, (2) how timing and content change across generations of information transmission, using transmission trees whose parents are assigned from timing and shared variants, and (3) which behavioral shifts coincide with documented scaffolding changes, using change-point detection aligned with the CHANGELOG. It also checks a swarm-scaling simulator against task graphs extracted from real agent work.

### 1.3 研究问题

- Q1（模块 A）：agent 聊天活动中，基线、人类触发、agent 触发三部分各占多少，这些比例随时期如何变化，agent 之间激发矩阵的谱半径是多少。
- Q2（模块 B）：每代的时间间隔分布是否与代数无关（H1）。第 k 代相对根节点的时间，其均值和方差是否随 k 线性增长。
- Q3（模块 B）：memory 中一个事实每经过一次 consolidation 被保留的概率是否恒定（H2）。agent 之间复述时每代的内容变化率与 memory 链相比如何（H3）。
- Q4（模块 C）：行为指标的变点与 CHANGELOG 日期的对齐程度是否超过随机水平，没有对应变更的变点有哪些。
- Q5（模块 D）：AI Village 任务依赖图的结构统计是否落在 Wenhao 生成器的分布内，真实 agent 延续自己上一个产出的比例是多少，接手开销和沟通开销的实测值是多少。

## 2. 数据

数据集：https://huggingface.co/datasets/aidigestorg/ai-village （gated，用户已获得访问权限）。总大小约 177 GB，主要是截图。除截图外的文件约 5.3 GB，其中 `village-transcript.json`（345 MB）与 chat 表重复，默认不下载。

### 2.1 文件

| 文件 | 大小 | 行数（说明页） | 内容 | 用于 |
|---|---|---|---|---|
| `README.md` | 15.1 kB | | 数据集说明 | 全部 |
| `SCHEMA.md` | 18.6 kB | | 每张表的字段说明，最先阅读 | 全部 |
| `CHANGELOG.md` | 22 kB | | 按日期记录的 scaffolding 变更（prompt、工具、模型、记忆系统、roster） | 阶段 0、C |
| `manifest.json` | 706 B | | 文件清单 | 阶段 0 |
| `example.py` | 1.69 kB | | 官方示例 | 阶段 0 |
| `events.jsonl.gz` | 307 MB | 约 23.3 万 | 活动时间线。`data` 字段含 `actionType`（`AGENT_TALK`、`START_USING_COMPUTER`、`STOP_USING_COMPUTER`、`WAIT`、`PAUSE`、`USER_TALK`、`SEARCH_HISTORY` 等），`event_index` 用于排序 | 阶段 0、A、C |
| `chat_messages.jsonl.gz` | 50.6 MB | 约 12.3 万 | agent 与人类的聊天消息，含 room、speaker、content、timestamp | A、B、C |
| `chat_rooms.jsonl.gz` | 1.71 kB | 5 | 聊天室 | A、B |
| `computer_use_sessions.jsonl.gz` | 37.5 MB | 约 3.7 万 | 每个 session 的 `session_goal` 和执行 agent | B、C、D |
| `computer_use_turns.jsonl.gz` | 2.22 GB | 约 114 万 | 每个 turn 的 `agent_action`、`agent_messages`、tool output、截图元数据 | B、D、E |
| `agent_memories.jsonl.gz` | 2.28 GB | 约 16.5 万 | memory consolidation 时 agent 写下的长期记忆 | B |
| `summaries.jsonl.gz` | 2.83 MB | 约 800 | LLM 生成的按日、按 agent、按 goal 摘要。生成时未看 computer-use session 内部，含错误 | B（单独渠道） |
| `claude_code_messages.jsonl.gz` | 104 MB | 约 24.5 万 | 少数使用 Claude Code scaffolding 的 agent 的完整消息流 | 可选 |
| `claude_code_sessions.jsonl.gz` | 12.7 kB | 约 300 | 上述 agent 的 session 记录 | 可选 |
| `agents.jsonl.gz` | 5.33 kB | 31 | agent 名称、emoji、模型字符串、goal、token 用量 | 全部 |
| `villages.jsonl.gz` | 328 B | 1 | village 记录 | 阶段 0 |
| `village_goals.jsonl.gz` | 4.45 kB | 约 45 | village 目标序列及起止时间 | A、C、D |
| `agent_goals.jsonl.gz` | 3.97 kB | | 每个 agent 的个人目标 | D |
| `village-transcript.json` | 345 MB | | 与网站相同的按天 transcript，内容与 chat 表重复 | 只用于核对 |
| `images/computer-use-turns/index.json` | | | 每天的 turn 数和截图数 | E |
| `images/computer-use-turns/<YYYY-MM-DD>.tar` | | | 每个太平洋时间日一个 tar，内含 `<turn_id>.png` | E |

### 2.2 已知约定（来自说明页，需核实）

- `created_at` 是权威时间，时区 UTC。village 时钟为太平洋时间（America/Los_Angeles）。
- village 从 2025-04-02 的 day 1 开始，按天递增，跳过多数周末。
- 截图按 turn 的 `created_at` 换算成太平洋时间日期后打包。`screenshot_is_redacted: true` 的 turn 为占位图。只发言的 turn 没有截图。
- 凭证替换为 `[REDACTED]`，消息中的 base64 图片替换为 `[IMAGE_REMOVED]`，签名等长 blob 替换为 `[BLOB_REMOVED]`，基础设施地址已删除。
- 原始 LLM 调用日志（`llm_calls`，即每次调用的确切 prompt）不在数据集中。说明页写明可以另行提供给经过审核的研究者。
- 任一时刻可以用 `https://theaidigest.org/village?day={day_number}&time={unix_ms}` 在网页上查看。
- agent 的 prompt 包含群聊近期消息、自己近期的电脑操作和当时的想法。agent 可以调用查历史工具，答案由另一个 AI 读取指定时间段的完整聊天记录后写出。
- agent 每天约 9 点至 17 点运行（时区需用数据核实），多数周末不运行。

### 2.3 需要核实的问题

阶段 0 结束时在 `docs/schema_notes.md` 中逐条回答。

1. `chat_messages` 是否有回复、引用或提及字段。如有，作为父节点的部分真实标注。
2. `agent_memories` 每行是整份 memory 快照还是单条记忆条目，是否有 consolidation 批次号。结果决定 6.3.1 的处理路径。
3. `summaries` 是否会进入 agent 的 prompt。结果决定 summary 能否作为传播中的父节点。
4. `SEARCH_HISTORY` 事件是否保存了问题和答案文本。
5. agent 与聊天室的对应关系，即每个 agent 能看到哪些 room。
6. 人类发言在 `chat_messages` 中如何标识。
7. `agent_action` 的结构，能否从中抽取 URL、文件路径和窗口标题。
8. 每日运行时段的实际边界（用 events 的首末时间统计）。
9. `agents` 表的模型字符串能否映射到模型家族（Anthropic、OpenAI、Google、其他）。
10. `events` 中的 `AGENT_TALK` 与 `chat_messages` 是否一一对应，如何去重。

### 2.4 下载

数据放在 PARCC 的项目盘或 scratch 盘，路径由用户提供（第 13 节）。下载前检查配额。`HF_TOKEN` 由用户设置为环境变量，不写入仓库。

```python
from huggingface_hub import snapshot_download, hf_hub_download

REPO = "aidigestorg/ai-village"
root = snapshot_download(
    repo_id=REPO, repo_type="dataset", local_dir="data/raw/ai-village",
    allow_patterns=["*.md", "*.jsonl.gz", "manifest.json", "example.py",
                    "images/computer-use-turns/index.json"],
)

# 截图只在模块 E 中按天下载，下载前按 index.json 估算大小
def fetch_day(day: str) -> str:
    return hf_hub_download(REPO, f"images/computer-use-turns/{day}.tar",
                           repo_type="dataset", local_dir="data/raw/ai-village")
```

### 2.5 大文件处理

- gz jsonl 用 gzip 流式逐行解析，分块写 parquet，不一次载入整个 2 GB 以上的表。
- `agent_memories` 和 `computer_use_turns` 先抽取需要的字段写成窄表，长文本单独存放，按 id 读取。

## 3. 环境与工程

### 3.1 仓库结构

```
ai-village-swarm-dynamics/
  SPEC.md  PROGRESS.md  README.md  pyproject.toml  .gitignore
  configs/default.yaml
  src/avsd/
    cli.py
    io/           # 下载、读取、adapter
    events/       # 统一事件表、运行时段、roster、CHANGELOG
    hawkes/       # 模块 A
    lineage/      # 模块 B
    changepoint/  # 模块 C
    swarmsim/     # 模块 D
    ethogram/     # 模块 E
    viz/          # 作图
    report/       # 静态 HTML 报告
  tests/
  data/           # raw/ interim/ processed/ labels/，整个目录写入 .gitignore
  outputs/        # figures/ tables/，只含聚合结果
  reports/        # writeup.md, index.html
  docs/           # schema_notes.md, decisions.md
```

### 3.2 依赖

Python 3.11。必需：polars、pyarrow、numpy、scipy、numba、pandas、networkx、ruptures、statsmodels、scikit-learn、rapidfuzz、spacy（加 `en_core_web_sm`）、huggingface_hub、pyyaml、typer、matplotlib、jinja2。可选：sentence-transformers 与 torch（嵌入）、vllm（本地 LLM）、hmmlearn（模块 E）。

### 3.3 命令行

```
avsd ingest              # 下载与转 parquet
avsd build-events        # 统一事件表、运行时段、roster、CHANGELOG
avsd hawkes fit          # 模块 A，--window goal|rolling
avsd lineage memory      # 模块 B1
avsd lineage trees       # 模块 B2
avsd changepoint         # 模块 C
avsd swarmsim calibrate  # 模块 D
avsd ethogram            # 模块 E
avsd report              # 汇总图表，生成 reports/index.html
```

每个命令读取 `configs/default.yaml`，写出结果和 QA 报告。

### 3.4 LLM 使用

- 默认不调用 LLM。模块 B 的事实单元用规则方法（6.3.2）。
- 可选后端为本地 vLLM（例如 Qwen3-8B，运行在 mig 切片上）或 Anthropic API。按量计费的调用先问用户预算。
- LLM 只用于抽样校验和小规模标注辅助。每次调用的 prompt 和输出缓存到 `data/interim/llm_cache/`。

### 3.5 测试

- 每个模块用合成数据做单元测试，其中 Hawkes EM 做已知参数恢复，传播树推断做已知树恢复。
- 真实数据上的每一步都输出 QA 报告。

## 4. 阶段 0：数据接入与统一事件表（P0）

### 4.1 步骤

1. 阅读 `README.md`、`SCHEMA.md`、`CHANGELOG.md`、`example.py`，写 `docs/schema_notes.md`，回答 2.3 的全部问题。
2. 各表转为 parquet，写入 `data/processed/tables/`。
3. 生成统一事件表 `data/processed/events_unified.parquet`，字段如下。

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_uid` | str | `{source}:{原始 id}` |
| `source` | enum | chat、event、session、turn、memory、summary |
| `kind` | enum | agent_msg、human_msg、session_start、session_end、turn、memory_write、search_history、wait、pause、other |
| `ts_utc` | timestamp | 来自 `created_at` |
| `ts_pt` | timestamp | 太平洋时间 |
| `village_day` | int | 按说明页规则计算，并与数据中的 day 字段（如有）核对 |
| `run_day` | int | 运行日编号，只计有事件的日期 |
| `t_in_day` | float | 距当日运行开始的秒数 |
| `t_active` | float | 累计运行秒数，定义见 4.2 |
| `actor_id` | str | agent id，人类统一为 `human` |
| `actor_type` | enum | agent、human、system |
| `model`、`model_family` | str | 来自 `agents` 表 |
| `room_id`、`session_id`、`goal_id` | str | 可为空 |
| `text` | str | 可为空，长文本只存引用 |
| `text_len` | int | 字符数 |
| `refs` | list[str] | 从文本和动作中抽取的规范化 URL 与文件路径 |

4. 生成运行时段（4.2）。
5. 生成 `agents.parquet`：agent id、名称、模型字符串、模型家族。
6. 生成 roster 时间线 `roster_daily.parquet`：每个运行日、每个 agent 是否活跃（有任何事件）及事件数。
7. 把 CHANGELOG 整理成 `changelog.parquet`：日期、类别（prompt、tool、memory、model、roster、other，可多选）、原文。先用关键词规则分类，再把分类结果列给用户确认。
8. 写 QA 报告：各表行数与说明页数值对比（事件约 23.3 万、聊天约 12.3 万、session 约 3.7 万、turn 约 114 万、memory 约 16.5 万、摘要约 800、agent 31），时间范围，缺失，重复 id，时区换算抽查（抽 20 条事件，生成 live UI 链接供用户核对）。

### 4.2 运行时段与 active time

- 每个运行日的运行区间为当日（太平洋时间）第一个事件到最后一个事件。
- 区间内相邻事件间隔超过 G（默认 30 分钟）的部分记为停顿段。
- `t_active` 为从第一个运行日开始累计的运行时间，只累加运行区间内、停顿段以外的时间。跨夜和跨周末的间隔因此不计入。
- QA 报告中给出每日运行时长的分布和停顿段的分布，G 的取值写入 `docs/decisions.md`。

### 4.3 验收

- 统一事件表行数与各源表一致，每条事件都有 `ts_utc` 和 `actor_type`，每条 agent 事件都有 `model_family`。
- 2.3 的问题全部有答案，或明确标为无法确定。
- CHANGELOG 分类经用户确认。

## 5. 模块 A：多元 Hawkes 过程（P0）

### 5.1 事件定义

- 每个分析窗口内活跃的 agent 各对应一个维度，事件为该 agent 在主聊天室发出的消息（`kind = agent_msg`）。主聊天室按消息量确定。
- 人类消息（`kind = human_msg`）作为外部输入。人类事件可以是 agent 事件的父事件，人类事件本身不建模，拟合时以人类事件序列为条件。
- 其他聊天室：先统计各 room 的消息量。P0 只用主聊天室，其他 room 的消息占比超过 10% 时另行拟合。
- 扩展（P1）：每个 agent 增加第二类事件 `session_start`，拟合带类型的模型，查看聊天与开始使用电脑之间的激发关系。

### 5.2 模型

每个运行日视为一次独立的实现，时间轴为 `t_in_day`，区间为 $[0, T_d]$。父事件只在同一运行日内寻找，跨日的影响由模块 B 处理。agent 维度 $i$ 的强度为

$$
\lambda_i(t) = \mu_{i,b(t)} + \sum_{j \in \mathcal{A} \cup \{h\}} \; \sum_{l \in \mathcal{H}_j(t)} \; \sum_{m=1}^{M} \alpha_{ij}^{(m)} \beta_m e^{-\beta_m (t - t_l)}
$$

- $\mathcal{A}$ 为 agent 集合（含 $i$ 本身，即自激），$h$ 为人类来源。$\mathcal{H}_j(t)$ 为来源 $j$ 在同一运行日、满足 $0 < t - t_l \le L$ 的事件。
- $\mu_{i,b}$ 为分段常数基线。$b(t)$ 按 `t_in_day` 每小时一段，第 8 小时之后并入第 8 段，用来描述每天开始运行时的集中活动。
- $\beta_m$ 固定为 1 分钟、10 分钟、1 小时对应的速率（$1/60$、$1/600$、$1/3600$，单位 s⁻¹），$\alpha_{ij}^{(m)} \ge 0$ 待估。
- 最大滞后 $L$ 默认 3 小时。
- 分支比 $n_{ij} = \sum_m \alpha_{ij}^{(m)} (1 - e^{-\beta_m L})$，表示来源 $j$ 的一个事件在 agent $i$ 上平均引发的事件数。
- 归一化核 $g_{ij}(\tau) = \sum_m \alpha_{ij}^{(m)} \beta_m e^{-\beta_m \tau} / n_{ij}$（$0 < \tau \le L$）是 $j \to i$ 的间隔分布，模块 B 使用。

### 5.3 EM 估计

E 步：对 agent $i$ 的每个事件 $k$（时刻 $t_k$），计算 $\lambda_k = \lambda_i(t_k)$，以及

$$
p_{k,0} = \frac{\mu_{i,b(t_k)}}{\lambda_k}, \qquad
p_{k,l,m} = \frac{\alpha_{i j(l)}^{(m)} \beta_m e^{-\beta_m (t_k - t_l)}}{\lambda_k}.
$$

M 步（$B_b$ 为第 $b$ 段对应的 `t_in_day` 区间）：

$$
\mu_{i,b} = \frac{\sum_{k \in i,\, b(t_k) = b} p_{k,0}}{\sum_d |B_b \cap [0, T_d]|}, \qquad
\alpha_{ij}^{(m)} = \frac{\sum_{k \in i} \sum_{l \in j} p_{k,l,m}}{\sum_{l \in j} \left(1 - e^{-\beta_m \min(L,\, T_{d(l)} - t_l)}\right)}.
$$

- 对数似然 $\sum_i \big[\sum_{k \in i} \log \lambda_k - \int \lambda_i\big]$ 每轮记录，必须单调不减。
- 收敛条件：对数似然相对变化小于 $10^{-6}$，或达到 500 轮。
- 初始化：$\alpha$ 取小的均匀值，$\mu$ 取各维度平均事件率。
- 事件数少的窗口可以加小的 L1 惩罚，写入 `docs/decisions.md`。
- 实现：用 numba，预先为每个事件建好候选父事件列表（稀疏存储）。

### 5.4 拟合窗口

- 主窗口：按 `village_goals` 的起止时间划分。每个窗口的维度数为该窗口活跃的 agent 数。agent 消息少于 500 条的窗口与相邻窗口合并，合并规则写入 `docs/decisions.md`。
- 滚动窗口：每 5 个运行日一个，互不重叠，供模块 C 使用。

### 5.5 输出

- `outputs/tables/hawkes_params.parquet`：窗口、$\mu$、$\alpha$、$n_{ij}$。
- 激发矩阵 $N = [n_{ij}]$，行为 agent，列为 agent 与 human。
- agent 之间部分 $N_{\mathcal{A}\mathcal{A}}$ 的谱半径 $\rho$。$\rho < 1$ 时 agent 子系统平稳，接近 1 表示 agent 之间的相互触发接近临界。
- 父事件概率 `data/processed/hawkes_parents.parquet`：`event_uid`、`parent_uid`（或 `background`）、`prob`，只保留 `prob ≥ 0.01` 的项。
- 分解：每个窗口的 agent 事件中，基线（$\sum_k p_{k,0}$）、人类、其他 agent、本人各占的比例。按运行日 bootstrap（1,000 次）给 95% 置信区间。
- 块结构：对 $N_{\mathcal{A}\mathcal{A}}$ 做谱聚类，记录分组及组内、组间 $n_{ij}$ 的均值。

### 5.6 验证

1. 合成数据参数恢复：人类事件用真实序列，agent 事件用每个窗口的拟合参数按分支结构模拟，运行日数和事件量与真实数据相近，重拟合 20 次，报告 $n_{ij}$ 和分解比例的偏差。验收标准为分解比例的平均绝对误差小于 0.05。
2. 拟合优度：time-rescaling。每个维度相邻事件之间的补偿器增量应服从 Exp(1)，报告 KS 统计量和 QQ 图。
3. 显式引用对照：如 2.3-1 存在回复或提及字段，或消息文本中有 @名字、"as X said" 一类显式引用，以这些为标注，计算概率最大的父事件与显式引用对象一致的比例，并与"取最近一条他人消息"的基线比较。
4. 调度稳健性：agent 按各自的循环行动，发言时刻部分由调度决定。另外拟合一个以行动机会为条件的模型。对 agent $i$ 的每次行动事件 $e$（events 中该 agent 的任何 action），因变量为该次行动是否为发言，自变量为各来源 $j$ 在同一运行日内近期事件的指数衰减计数 $x_{e,j,m} = \sum_{l \in j,\, t_l < t_e} e^{-\beta_m (t_e - t_l)}$，用带 L2 正则的逻辑回归估计。比较两个模型给出的 $j \to i$ 影响排序（Spearman 相关），排序不一致时在 write-up 中报告。
5. 敏感性：$L$ 取 1、3、6 小时，G 取 15、30、60 分钟，报告分解比例的变化。

### 5.7 验收

- EM 对数似然单调不减，合成恢复误差达标。
- 至少 3 个主窗口完成拟合，输出分解比例、置信区间和谱半径。
- 验证 2 至 5 完成并写入 QA 报告。

## 6. 模块 B：传播代数与跨代一致性

B1 为 P0，B2 为 P1。

### 6.1 定义

- 信息单元：同一条可追踪信息的全部出现。具体定义见 6.3.2 与 6.4.1。
- 代数：传播树中从根节点到该节点的边数，根节点为第 0 代。
- 序列间隔（serial interval）：父节点与子节点出现时刻（发言或写入时间）之差。本项目的时间戳只能测序列间隔。
- 代际间隔（generation interval）：父、子两次暴露之间的时间差。需要知道消息何时进入 agent 的 prompt，只有拿到 `llm_calls` 才能测（第 13 节）。
- 同一运行日内的时间项用 `t_in_day` 计算。报告的间隔统一用 `t_active`，以去掉夜间和周末。

### 6.2 假设与检验

**H1：间隔分布与代数无关。** 在时间齐次的分支过程中，每条边的间隔 $X$ 独立同分布，均值 $\mu$，方差 $\sigma^2$。第 $k$ 代节点相对根节点的时间是其路径上 $k$ 条边的间隔之和，$T_k = X_1 + \dots + X_k$。

- 期望是线性的，$E[T_k] = \sum_{g=1}^{k} E[X_g] = k\mu$，这一步不需要独立性。
- $\mathrm{Var}(T_k) = \sum_g \mathrm{Var}(X_g) + 2\sum_{g<g'} \mathrm{Cov}(X_g, X_{g'})$。各代间隔独立时协方差为零，$\mathrm{Var}(T_k) = k\sigma^2$。
- 所以在 H1 下，$T_k$ 的均值和方差都随 $k$ 线性增长，斜率分别为 $\mu$ 和 $\sigma^2$，标准差随 $\sqrt{k}$ 增长。
- 若各代间隔分布不同（均值为 $\mu_g$），$E[T_k] = \sum_{g \le k} \mu_g$，均值曲线不再是直线。若相邻代间隔正相关（例如一条链持续经过慢渠道），方差增长快于线性，负相关则慢于线性。若间隔为重尾分布，方差估计不稳定，改为报告中位数和四分位距随 $k$ 的变化。

检验：

1. 按代数 $g$ 分组比较单条边的间隔分布，用 Anderson-Darling k 样本检验，p 值用置换得到，按渠道分层。
2. 对 $k$ 回归 $\overline{T_k}$ 和 $\widehat{\mathrm{Var}}(T_k)$，加入 $k^2$ 项检验线性，并估计相邻代间隔的相关系数。
3. 同一棵树内的节点共享祖先，彼此不独立。所有置信区间用按根节点的 cluster bootstrap。
4. 只报告边数不少于 30 的代数。

已知的偏离来源与处理：

- 渠道混合：chat、memory、查历史的延迟不同。每条边标注渠道，按渠道分层检验，同时报告渠道构成随代数的变化。
- 有限人数：同一时期活跃的 agent 少，多代之后未暴露的 agent 变少，每代后代数预期下降。报告实测后代数，以及按剩余未暴露 agent 数计算的期望后代数。间隔检验不受这一因素影响。
- 右删失：观察窗口（数据末尾，或分析窗口末尾）附近只能看到短间隔。只使用距离观察窗口末尾超过 $L_B$ 的父节点的全部子边，$L_B$ 默认为 3 个运行日的 active time。
- 增长期偏差：扩散快速增长时，从子节点回看测到的间隔偏短。间隔分布用前向间隔估计，即固定父节点，统计其全部子节点的间隔。

**H2：memory 每代保留概率恒定。** 一个事实经过第 $g$ 次 consolidation 后仍然存在的条件概率为 $r$，与 $g$ 无关。此时 $P(S \ge s) = r^s$，事实的存活代数 $S$（首次丢失前经过的代数）服从几何分布，离散风险率 $h_g = 1 - r$ 为常数。检验方法为估计 $h_g$，与常数风险模型做似然比检验，备择模型为分段常数风险。按模型家族和 CHANGELOG 中的 memory 系统变更分层。

**H3：内容逐代变化并被继承。** 每经过一代，内容以概率 $c$ 出现新变化，变化会被后代继承。这一性质用于在候选父节点中确定父节点（6.4.3），并比较 agent 之间复述与 memory 链的 $c$。

### 6.3 B1：memory 链（P0）

#### 6.3.1 处理路径（按 2.3-2 的结果二选一）

- 路径 S：每行是整份 memory 快照。同一 agent 的 memory 按时间排序，相邻两版构成一代，父节点为上一版。
- 路径 I：每行是单条记忆。按 consolidation 批次号，没有批次号时按写入时间聚类（相邻写入间隔阈值默认 60 秒），把条目合成一版，之后与路径 S 相同。

#### 6.3.2 事实单元（规则方法，不调用 LLM）

- 锚点：从每版文本中抽取 URL（规范化，去掉跟踪参数）、数字（含货币、百分比、计数）、日期、时刻、agent 名称，以及 spaCy NER 识别的 ORG、PERSON、GPE、PRODUCT、EVENT、WORK_OF_ART 实体。
- 人名、邮箱、电话类锚点只保存哈希值，输出中不出现原文。URL 在输出中只显示域名。
- 事实单元为三元组（锚点类型，规范化值，上下文键）。上下文键取锚点所在句中距离最近的名词短语的词元，用于判断同一上下文是否出现了不同的值。
- 事实单元在某 agent 的 memory 中首次出现记为第 0 代。之后每一版记录状态：保留（同值出现）、修改（同一上下文键出现不同值）、丢失（未出现）、恢复（丢失后再次出现）。存活分析以首次丢失为事件，恢复单独统计。

#### 6.3.3 输出

- 各模型家族的离散保留曲线（Kaplan-Meier 离散形式）和几何分布拟合。
- $h_g$ 表，含 95% 置信区间。
- 修改率随代数的变化。
- 按锚点类型分层的结果。

#### 6.3.4 校验

随机抽 100 对相邻版本，由用户人工标注事实单元的状态（可以先用 LLM 预标，再由用户复核），计算规则方法的精确率和召回率。标注文件格式见附录 C。

#### 6.3.5 验收

覆盖全部 agent 的 memory，保留曲线、$h_g$ 表、H2 检验和标注校验完成。

### 6.4 B2：agent 之间的传播树（P1）

#### 6.4.1 信息单元

- 候选锚点：在某条消息（agent 或人类发出）或 tool output 中首次出现、之后被其他 agent 或其他渠道再次提到的锚点。锚点类型同 6.3.2，另加低频 4-gram（在全部聊天消息中出现的消息数少于 5 条）。
- 一个信息单元为同一锚点（数字类锚点为同一上下文键）的全部出现，按时间排序，最早的出现为根。
- 只分析出现次数不少于 3、涉及至少 2 个不同 agent 的单元。
- 出现的来源：聊天消息，agent memory（按 B1 的版本，取该单元在该 agent memory 中首次出现的版本），summary，查历史的答案（如有记录），agent 自己的 computer-use turn（锚点出现在 tool output 或 `agent_messages` 中，记为独立观察）。

#### 6.4.2 候选父节点与暴露约束

对出现 $i$（agent $a_i$，时刻 $t_i$），候选父节点 $j$ 需满足 $t_j < t_i$，并满足下列之一。

- $j$ 是聊天消息（agent 或人类发出），且 $a_i$ 能看到 $j$ 所在的 room（2.3-5）。
- $j$ 是 $a_i$ 自己的 memory 版本（memory 只对本人可见，需核实）。
- $j$ 是 $a_i$ 发起的查历史事件的答案（2.3-4）。
- $j$ 是 summary，且 2.3-3 核实 summary 会进入 prompt。
- $j$ 为独立观察节点 $\mathrm{env}_i$，即 $a_i$ 在 $t_i$ 之前 $L_B$ 内自己的 computer-use turn 中出现了同一锚点。

summary 和查历史答案作为子节点时，候选父节点为其覆盖时间段内的全部聊天消息。

#### 6.4.3 父节点后验

$$
P(\text{parent}(i) = j) \propto E_{ij} \cdot K_{ij} \cdot \exp(\gamma S_{ij})
$$

- $E_{ij} \in \{0, 1\}$：暴露约束。
- $K_{ij}$：时间项。同一运行日内的聊天渠道用模块 A 对应窗口的归一化核 $g_{a_i a_j}(t_i - t_j)$（$j$ 为人类时用 $g_{a_i h}$）。跨运行日的渠道用经验间隔分布，先用只有一个候选父节点的边估计（核密度，按渠道分别估计）。
- $S_{ij}$：内容项，为 $i$ 与 $j$ 共有、根节点没有的变化数，即二者共享的非根值（同一上下文键下与根不同的值，或根文本中没有的低频 4-gram）。依据是校勘学的原则：共同的改动可以说明传抄关系，共同保留的根内容不能说明传抄关系。
- $\gamma$：在标注集上用网格搜索确定，默认 1.0。
- $\mathrm{env}_i$ 的时间项用"独立观察到发言"的经验间隔分布。父节点为 $\mathrm{env}_i$ 的出现记为独立得到，它开始一棵新的子树，代数从 0 重新计算。

#### 6.4.4 代数与统计

- MAP 树：每个出现取后验最大的父节点，得到代数。H1、H3 的主检验在 MAP 树上进行。
- 后验抽样：每个出现按后验独立抽取父节点。父节点都更早，所以结果一定是森林。抽 200 次，在抽样树上计算同样的统计量并报告分布，作为父节点不确定性的敏感性分析。
- 每代记录渠道构成、后代数、内容变化率（本代新出现的非根值所占比例）、独立得到的比例。
- 吸引子检验：同一单元内，各代文本的词汇多样性（type-token ratio），以及与该单元最常见表述的相似度随代数的变化。

#### 6.4.5 验证

- 标注集：从显式引用（回复字段、@名字、引号引用）自动得到一部分父节点标注，再由用户人工标注 50 个出现的父节点。
- 消融：只用时间项、只用内容项、两项结合，比较父节点准确率。
- 合成验证：按 AI Village 的 agent 数、事件率和估计的核函数模拟传播树，每代以概率 $c$ 加入内容变化，检查推断的代数准确率，以及 H1 检验在零假设下的第一类错误率。

#### 6.4.6 验收

至少 100 个信息单元完成树推断，消融和合成验证完成，H1 检验按渠道报告。

## 7. 模块 C：变点检测与 CHANGELOG 对齐（P0）

### 7.1 时间序列

按运行日计算，稀疏的序列按 5 个运行日聚合。

- 每个 agent 和每个模型家族：消息数，平均消息长度，疑问句比例，`WAIT` 与 `PAUSE` 次数，session 数，每个 session 的平均 turn 数，查历史次数，每运行小时事件率。
- 词汇指标：各模型家族的特征词频率。说明页的示例统计过 Claude agent 使用 "genuinely" 的频率，可作为第一个指标。其余特征词用模型家族之间的对数几率比选前 20 个。
- 模块 A 的滚动窗口结果：基线、人类触发、agent 触发的比例，以及谱半径。谱半径与窗口内 agent 数有关，跨窗口比较时同时报告 agent 数。
- 模块 B1 的月度风险率 $h$。
- 模块 E 的时间分配（如完成）。

### 7.2 方法

- PELT（ruptures），代价函数 l2 和 rbf 各运行一次，惩罚项按 BIC 型规则设定，并报告惩罚项敏感性。
- 稳健性：Bayesian online change point detection。
- 变点位置的不确定性：块 bootstrap，块长 5 个运行日。
- 组成效应：roster 变化会改变家族均值。家族层面的序列另用变点前后都活跃的 agent 计算一次，与全量结果并列报告。

### 7.3 对齐检验

- 对每个变点，查找 $\pm w$ 个运行日内（默认 $w = 3$）的 CHANGELOG 条目，记录类别。
- 统计量：落在任一条目 $\pm w$ 范围内的变点数。
- 零分布一：把全部 CHANGELOG 日期整体循环平移（保持条目之间的间距），重复 10,000 次。零分布二：把条目在运行日中均匀随机放置。分别报告 p 值。
- 没有对应条目的变点，在 write-up 中标注为 "cause unidentified"，附变点前后各 2 个时刻的 live UI 链接，不对原因做推测。

### 7.4 输出与验收

- 变点表：序列、位置（运行日与日期）、幅度、位置置信区间、最近的 CHANGELOG 条目及类别、是否对齐。
- 时间线图（10.3 的 F5）。
- 验收：至少 20 条序列完成检测，对齐检验完成，变点表输出。

## 8. 模块 D：Wenhao swarm 模拟的复现与校准

D1 至 D4 为 P1，D5、D6 为 P2。

### 8.1 背景

- 来源：Wenhao Chai，Predictable Swarm Scaling，2026-09-27，https://wenhaochai.com/blogs/predictable-swarm-scaling.html 。
- 博文用任务 DAG 模拟 swarm。生成器参数拟合自两张内部递归自我改进实验的 DAG，拟合时对齐三项统计：不同父节点数的步骤占比、合并发生在兄弟步骤之间的频率、子步骤在父步骤之间分布的不均匀程度。
- agent 规则：每个 agent 维护自己的就绪步骤列表，总是取最深的步骤。
- 开销：agent 启动或在其他 agent 的成果上继续工作时，一次性增加一个中位步骤耗时的 5%。同组两个 agent 在岗时每步多 15%，此后每多一个在岗组员再多 1%。
- 两种分数：发现型探索用覆盖度（已完成步骤的比例），优化型探索用最优分数。AI Village 的目标没有统一分数，本项目只用覆盖度。
- 参数摘要见附录 B。开始前先问用户是否已从 Wenhao 处拿到代码，没有代码时按附录 B 和博文原文重写。

### 8.2 D1：模拟器（P1）

- 实现生成器、单 agent 规则、标准 swarm、递归 swarm、pass@k 和两类开销。
- 复现检查（定性趋势加近似数值）：标准 swarm 随 agent 数增加整体提前。32 和 64 个 agent 完成全部步骤的时间接近，博文约为 0.10 T₁。64 个 agent 的标准 swarm 到达一半覆盖度比单个 agent 约快 33 倍。允许 20% 以内的偏差。偏差超出时记录在 `docs/decisions.md`，不为贴近博文数字调整参数。

### 8.3 D2：AI Village 工作依赖图（P1）

- 节点：computer-use session。
- artifact：从 turn 的 `agent_action`、tool output、`agent_messages` 中抽取 URL 和文件路径并规范化。Google Docs、Sheets 取文档 ID，GitHub 取 owner/repo/path，其他 URL 去掉 query 和 fragment。
- 动作分类：根据 2.3-7 的核实结果，把动作分为写入类（输入文本、保存、提交、发送、修改文件的命令）和读取类。分类规则写入 `docs/decisions.md`，并请用户确认。
- 边：session B 接触 artifact x，且 x 在 B 之前最近一次被 session A 写入时，连边 A → B。只读接触也连边，标注为 read，统计时与写入边分开报告。
- 层：与博文相同，每个节点放在其最深父节点的下一层，根节点为第 0 层。
- 按 village goal 分别建图。

### 8.4 D3：结构统计（P1）

- 父节点数分布。父节点数不少于 2 的节点中，父节点互为兄弟的比例。子节点在父节点之间分布的不均匀程度（出度的 Gini 系数，以及出度最高的 10% 父节点占有的子节点比例）。跨层边（跨 2 层及以上）占比。
- 用生成器按相同节点数生成 64 张 DAG，计算同样的统计，报告 AI Village 的值在生成分布中的分位数。
- 步骤代价与层数：session 的 turn 数和时长随层数的变化，与博文中代价随深度线性增长的设定对照。

### 8.5 D4：行为规则（P1）

- 延续率：agent 的下一个 session 的父节点中包含自己上一个 session 的比例。
- 基线：同一时期该 agent 在可接触的 artifact 中随机选择时的期望比例。

### 8.6 D5：开销估计（P2）

- 接手开销：比较父节点属于其他 agent 的 session 与父节点属于本人的 session，从 session 开始到第一个写入类动作的 turn 数。用负二项回归控制模型、goal 和时期。
- 沟通开销：以 session 的 turn 数为因变量，自变量为 session 期间同时活跃的 agent 数 $n$，拟合 $\log E[\text{turns}] = \theta + \log\big(1 + a \cdot \mathbb{1}[n \ge 2] + b \cdot \max(n - 2, 0)\big)$ 加控制项，得到 $a$、$b$ 的估计，与博文的 $a = 0.15$、$b = 0.01$ 对照。

### 8.7 D6：预测对照（P2）

- 选 1 到 2 个 village goal。用 D3 至 D5 校准的参数，在节点数相同的生成 DAG 上，模拟与实际在岗 agent 数相同的标准 swarm。
- 实际覆盖度为已开始的 session 数占该 goal 依赖图节点总数的比例，随 `t_active` 变化。
- 比较模拟与实际的覆盖度曲线，只报告两条曲线之间的差距，作为探索性结果。

### 8.8 与模块 A 的关系

博文的标准 swarm 把全部 agent 视为一个小组。模块 A 的谱聚类如果显示分组，在 D6 中增加一个按分组设置沟通开销的对照。

## 9. 模块 E：截图行为谱（P2）

- 抽样：3 到 5 个运行日，覆盖不同时期和模型家族。先读 `index.json` 估算大小，总下载量不超过 30 GB，超过时先问用户。
- 编码：每张截图用图像嵌入模型（例如 SigLIP）编码，在 mig 切片上推理，与该 turn 的动作类型拼接为特征。
- 分段：每个 session 内对特征序列做变点分段，或拟合 K 状态 HMM，K 用 BIC 在 8 到 30 之间选择。
- 命名：每个状态取 10 张代表截图，由 VLM 生成描述，再由用户确认。状态名称用中性的动作描述，例如"编辑文档"、"阅读邮件"。
- 输出：各模型家族的行为谱（状态列表与频率）、时间分配、状态转移矩阵，以及同一动作序列连续重复 5 次及以上的发生率。
- 隐私：截图不进入仓库和 write-up。示例图只使用已脱敏的截图，并裁剪掉可能含个人信息的区域。

## 10. 交付物与写作规范

### 10.1 工具

- `avsd` 命令行工具，核心输入为统一事件表。AI Village adapter 为 P0。通用 JSONL adapter（给出列映射即可接入其他多 agent 日志）为 P1。德语论坛数据 adapter 为 P2，数据入口需向用户确认。
- `avsd report` 生成静态 HTML 报告 `reports/index.html`，包含 10.3 的图和主要表格。

### 10.2 Write-up

英文，文件 `reports/writeup.md`。结构如下。

1. Summary：3 到 5 句，给出主要数字。
2. Data and preprocessing。
3. Methods：每个模块一小节。
4. Results：每个结论一小节，每小节配一张专属的图或表。
5. Limitations。
6. Reproducibility：命令与运行时间。
7. Acknowledgements and citation：引用 AI Digest / AI Village 和 Wenhao Chai 的博文 Predictable Swarm Scaling。作者为 Enxin Song 和 Wenhao Chai，致谢不列 Wenhao Chai。

写作规则：

- 术语用领域标准名称（serial interval、branching ratio、spectral radius、change point 等），不自创说法，不用比喻作术语。
- 不用口语和拟人表达。
- 不用 "it is X, not Y" 句式。
- 原因未确认的现象写 "cause unidentified"，之后不补充未经验证的解释。
- 小节标题用中性名词，不用问句。状态标签全文一致。
- 不使用 em dash。尽量不用冒号和分号，句子短而简单。
- 优先用主动语态，以 "we" 为主语。
- 不引用后文才出现的内容，结构只在开头的概述段预告。
- 表格单元格保持简短，论证写在正文。
- 正文只写点估计和样本量，不用方括号写置信区间；95% 置信区间画在图里（误差线）或列在表中。
- 英文写作参照 github.com/wenhaochai/claude-plugins 中的 writing/skills/style，与本节规则冲突时以本节为准。

### 10.3 图

规范：

- 按 github.com/wenhaochai/claude-plugins 中 writing/skills/plot 的约定作图，配色用该 skill 自带的 Google GM2 配色（不同类别依次取蓝、红、黄、绿、紫，柱子用 400 色阶，点和线用 600 色阶，参照线和基线用灰色）。
- 图中不用白色文字，文字尽量少，所有文字标签首字母大写。
- 每张图按内容选择图型和尺寸，不同的图不共用同一个模板，只共享配色和风格。
- 并排子图的总高度（含图例）相同，宽度可以不同。图例文字不能过小，元素之间不遮挡。

图目录：

- F1：激发矩阵热图，每个主窗口一张小图横向排列，行列按谱聚类分组排序。
- F2：agent 活动三部分比例随时期的变化，堆叠面积图，附置信区间带。
- F3：按代数分组的间隔分布（ECDF），按渠道分面。
- F4：$\overline{T_k}$ 和 $\widehat{\mathrm{Var}}(T_k)$ 随 $k$ 的变化及线性拟合，点加误差线，两个子图。
- F5：变点时间线，全宽细条。横轴为日期，各序列的变点为竖线，顶部标记 CHANGELOG 条目，对齐与未对齐的变点用两种颜色。
- F6：memory 保留曲线与几何分布拟合，按模型家族。
- F7：AI Village 依赖图的各项统计在生成器分布中的位置，每项统计一个小直方图，实测值画竖线。
- F8（如完成）：行为谱的时间分配。

### 10.4 README

项目简介、安装、数据获取（说明需要 Hugging Face 访问权限和数据条款）、每个命令的用法、输出说明、运行时间、引用。

### 10.5 提交清单

- [ ] 公开仓库前检查：`git ls-files` 中没有数据文件、截图、消息全文和凭证，并用 gitleaks 一类工具扫描密钥。
- [ ] write-up 与 HTML 报告完成。
- [ ] 真实结果报告（write-up 的 Results 部分）。
- [ ] 2 到 3 分钟视频脚本（可选，由用户录制）。
- [ ] 10 月 4 日 15:00 PT（18:00 ET）冻结结果，之后只修改文字和图的排版。
- [ ] 10 月 4 日 21:00 PT（10 月 5 日 00:00 ET）前提交。

## 11. 时间表与优先级

| 时间（ET） | 任务 | 优先级 |
|---|---|---|
| 9 月 30 日至 10 月 1 日 | 阶段 0，模块 A 的 EM 实现与合成测试 | P0 |
| 10 月 2 日 | 模块 A 真实数据拟合与验证，模块 B1 | P0 |
| 10 月 3 日 | 模块 C，模块 B2 | P0、P1 |
| 10 月 4 日上午 | 模块 D1 至 D4，模块 E（有余力时） | P1、P2 |
| 10 月 4 日 18:00 | 冻结结果 | |
| 10 月 4 日 18:00 至 24:00 | write-up、图、README、HTML 报告，提交 | |

截止线：

- 10 月 3 日 12:00 ET 模块 A 仍未通过验证时，B2 的时间项改用经验间隔分布，模块 A 继续排查。
- 10 月 4 日 09:00 ET B2 仍未完成时，H1 只在有显式引用标注的边上检验，write-up 以 A、B1、C 为主。
- 模块 D 和 E 只在 P0 全部完成后开始。

## 12. 风险与措施

| 风险 | 措施 |
|---|---|
| 同一时期活跃 agent 少，传播树多为 1 到 2 代 | H2 以 memory 链为主体。H1 汇总全部代数不少于 1 的边，只报告边数不少于 30 的代数 |
| 调度节奏被 Hawkes 估计为相互激发 | 5.6 第 4 条的行动机会条件模型对照 |
| 规则方法的事实单元误差大 | 6.3.4 的标注校验，在结论中报告精确率和召回率 |
| CHANGELOG 覆盖不完整 | 未对齐的变点只标 "cause unidentified"，不推断为自发变化 |
| 人数变化与模型升级同时发生 | 7.2 的固定 agent 面板 |
| 时间不足 | 第 11 节的截止线 |
| 隐私泄露 | 0.2 的规则与 10.5 的检查 |

## 13. 需要用户决定或提供的事项

1. `HF_TOKEN`，以及 PARCC 上存放数据的路径（项目盘或 scratch，需确认配额）。
2. 是否向 AI Digest 申请一段时间的 `llm_calls`。拿到后可以测代际间隔，并得到每个 agent 每次调用时看到了哪些消息的真实标注，用于 5.6 和 6.4.5 的验证。申请由用户发出。
3. Wenhao 是否参加，能否提供模拟器代码。
4. 是否使用 LLM 后端，以及预算。
5. 公开仓库的名称和 GitHub 账号（默认 Espere-1119-Song）。
6. write-up 重点展示的 village goal。
7. 人工标注（6.3.4 的 100 对版本、6.4.5 的 50 个父节点）由用户完成的时间。

## 附录 A：术语

| 术语 | 本项目中的定义 |
|---|---|
| 运行日（run day） | 有事件的太平洋时间日期 |
| active time | 只累计运行区间内、停顿段以外的时间（4.2） |
| 代数（generation） | 传播树中从根节点到该节点的边数 |
| 序列间隔（serial interval） | 父、子两次出现的时间差 |
| 代际间隔（generation interval） | 父、子两次暴露的时间差 |
| 分支比 $n_{ij}$ | 来源 $j$ 的一个事件在 agent $i$ 上平均引发的事件数 |
| 谱半径 $\rho$ | agent 之间分支比矩阵特征值模的最大值 |
| 暴露 | 一条信息可能进入某个 agent 的 prompt |
| 锚点 | 可以在文本间精确匹配的片段（URL、数字、日期、实体、低频 4-gram） |
| 上下文键 | 锚点所在句中最近名词短语的词元 |
| 非根值 | 同一上下文键下与根节点不同的值 |
| 独立得到 | 父节点为该 agent 自己的电脑操作观察 |
| 覆盖度 | 已完成步骤占全部步骤的比例 |

## 附录 B：Wenhao 模拟器参数（摘自博文，复现时核对原文）

生成器：

- 规模：约 723 步、17 层（语言建模 DAG 的规模）。第 0 层只有根节点，值为 0。
- 层大小：沿深度呈钟形，峰值位于 28% 深度处。第 $d$ 层分到以峰值为中心、陡度为 $6.4/(D-1)$ 的 logistic 曲线在该层上的增量，乘以噪声因子 $e^{0.35z}$。$z$ 每次出现都从标准正态分布中重新抽取。
- 每张图 16 个任务。每个任务的步数为 $723e^{0.4z}$，层数为 $17e^{0.2z}$，峰值位于 $0.28 + 0.07z$ 的深度处，合并概率 $p = 0.46e^{0.3z}$，各项用独立的 $z$。任务时钟乘以 $e^{\delta_b}$，$\delta_b \sim U(-0.3, 0.3)$。
- 主父步骤：从上一层抽取，概率与 $e^{\beta\delta}$ 成正比，$\beta = 1.4$，$\delta$ 为该父步骤相对其前身的改进。
- 合并：以概率 $p$ 合并 $K$ 个额外父步骤，$P(K) \propto K^{-2.3}$，$K = 1, \dots, 16$。每个额外父步骤以 0.2 的概率取主父步骤的兄弟，否则取自向上第 $b$ 层，$P(b) \propto 0.8^b$，最远到根节点，并在该层按同样的权重抽取。同一步骤的两个父步骤不在同一条链上：候选步骤是已选父步骤的祖先时跳过，已选父步骤是新选步骤的祖先时去掉。
- 值：最好的父步骤的值加上服从 $\mathcal{N}(\mu_d, 1)$ 的变化，$\mu_d$ 随深度从根节点的 $+1$ 线性降到最深层的 $-0.5$。
- 肥沃度：每张 DAG 抽取 $q \sim \mathcal{N}(0, 0.2^2)$，加到其中每次变化的均值上。
- 代价：$c_d = 1 + 9d/(D-1)$，agent 在该步骤上的耗时为 $c_d \cdot e^{0.2z}$。
- 分数尺度：按任务的方式生成 64 张 DAG，把最优值的第 90 百分位记为 1，更高的值也记为 1。
- 与真实 DAG 的对照：生成 DAG 的最优 recipe 位于 94%（语言建模规模）和 88%（diffusion 规模）深度处，真实 DAG 为 94% 和 92%。跨层边占比：语言建模 DAG 为 26%，diffusion DAG 为 16%，生成 DAG 为 18%。

agent 与 swarm：

- 就绪：一个步骤的所有父步骤都完成后才就绪。
- 单 agent：列表记录自己完成过其某个父步骤的就绪步骤，每次取最深的，同层随机。约一半步骤没有子步骤，尝试前无法识别。
- 标准 swarm：同时运行的 agent 数有上限。列表清空的 agent 停止，空出的名额随机分给一个就绪步骤，由调度器派一个新 agent 去做。全体 agent 构成一个小组。
- 递归 swarm：做完的步骤打开多个新步骤时，agent 保留一个，并在预算允许时为其余每个步骤派生一个子 agent。有层数上限，最深允许层不能继续派生。调度器只启动第一个 agent，以及派发最深允许层持有的步骤。有子 agent 的 agent 同属两个小组。
- pass@k：k 个 agent 各自独立遵循单 agent 规则。
- 调度开销：agent 启动或在其他 agent 的成果上继续工作时，一次性增加一个中位步骤耗时的 5%。调度器派发步骤不花时间。
- 沟通成本：小组中两个 agent 在岗时，它们的每一步多花 15%，此后每多一个在岗组员，组内每一步再多 1%。调度器不计入人数。
- 时间单位 T₁：最慢的一次单 agent 运行完成全部步骤所需的时间。
- 标准 swarm 结果：64 个 agent 到达一半覆盖度比单个 agent 快 33 倍，最优分数到达 0.8 快 16 倍。32 和 64 个 agent 都在约 0.10 T₁ 完成全部步骤。
- $\lambda = \ln g_{50} / \ln N$，$g_{50}$ 为一半覆盖度处的加速比。三层递归 swarm 在 4 至 64 个 agent 时为 0.88 至 0.93。标准 swarm 在 4 至 16 个 agent 时为 0.89 至 0.92，64 个时为 0.84。

## 附录 C：标注文件格式

`data/labels/memory_pairs.csv`

| 列 | 说明 |
|---|---|
| `pair_id` | 相邻版本对编号 |
| `agent_id` | agent |
| `prev_uid`、`next_uid` | 两版 memory 的 id |
| `unit_key` | 事实单元（锚点类型、规范化值或哈希、上下文键） |
| `rule_label` | kept、modified、dropped、new、restored |
| `human_label` | 取值同上，由用户填写 |
| `notes` | 备注 |

`data/labels/parents.csv`

| 列 | 说明 |
|---|---|
| `occurrence_uid` | 子节点出现 |
| `parent_uid` | 标注的父节点，独立得到时填 `env` |
| `source` | explicit_ref 或 manual |
| `notes` | 备注 |

标注文件含原文，放在 `data/` 下，不进入公开仓库。

## 附录 D：参考

- AI Digest. AI Village dataset. 2026. https://huggingface.co/datasets/aidigestorg/ai-village
- AI Digest. How the AI Village works. https://theaidigest.org/village/blog/how-the-ai-village-works
- AI Swarm Dynamics Hackathon. https://swarmchasing.com/
- Wenhao Chai. Predictable Swarm Scaling. 2026. https://wenhaochai.com/blogs/predictable-swarm-scaling.html
- Paglieri et al. A Case Study on Emergent Cheating and Whistleblowing in Autonomous Research Swarms. arXiv:2609.04170, 2026.
- Park et al. Scaling Discovery through Test-Time Communication. arXiv:2609.21032, 2026.
- Veen and Schoenberg. Estimation of space-time branching process models in seismology using an EM-type algorithm. JASA, 2008.
- Lewis and Mohler. A nonparametric EM algorithm for multiscale Hawkes processes. 2011.
- Brown et al. The time-rescaling theorem and its application to neural spike train data analysis. Neural Computation, 2002.
- Champredon and Dushoff. Intrinsic and realized generation intervals in infectious-disease transmission. Proceedings of the Royal Society B, 2015.
- Jombart et al. Bayesian reconstruction of disease outbreaks by combining epidemiologic and genomic data. PLoS Computational Biology, 2014.
- Didelot et al. Genomic infectious disease epidemiology in partially sampled and ongoing outbreaks. Molecular Biology and Evolution, 2017.
- Maas. Textual Criticism（校勘学中以共同错误确定抄本关系的谱系法）。
- Perez et al. When LLMs Play the Telephone Game: Cumulative Changes and Attractors in Iterated Cultural Transmissions. 2024.
- Killick, Fearnhead and Eckley. Optimal detection of changepoints with a linear computational cost. JASA, 2012.
- Adams and MacKay. Bayesian online changepoint detection. arXiv:0710.3742, 2007.
- Truong, Oudre and Vayatis. Selective review of offline change point detection methods. Signal Processing, 2020.
