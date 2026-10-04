# Design decisions

Each entry gives the date, the decision and the reason.

## 2026-09-30. Compute host is GRASP, not PARCC

The repository and data live on the SEAS GRASP cluster at `~/ai-village-swarm-dynamics` (login `grasp-login1.seas.upenn.edu`, Slurm account `gu-account`, lab partition `gu-compute`). The owner chose this. The Mac to GRASP link is fast, while the Mac to PARCC link runs at 4 to 10 KB/s. The PARCC rules in SPEC 0.1 carry over in spirit. Heavy computation runs as Slurm jobs, not on the login node. The lab project disk `/mnt/projects/jg` is not writable by this account, so data goes under the home directory.

## 2026-09-30. No paid LLM API

The owner has no API budget for this project. `llm.backend` defaults to `none`. Module B uses the rule-based fact units (SPEC 6.3.2). Any LLM pre-labeling uses a local open-weight model on a GPU node through vLLM, inference only.

## 2026-09-30. Random seed

All stochastic steps read `seed: 20261003` from `configs/default.yaml`.

## 2026-09-30. Pause gap G

G = 30 minutes as in SPEC 4.2, pending the run-period QA report.

## 2026-09-30. Pin the dataset revision

The dataset is refreshed about weekly. All downloads use revision `838b4150303ca8228e8edb432d8b8ccae353d258` (export of 2026-09-20). This export is larger than the dataset card says (for example 381,610 events instead of about 233k). The QA reports compare against `manifest.json` of this revision. See `docs/schema_notes.md` section 1.

## 2026-09-30. Summaries are not transmission parents

The scaffold does not put the `summaries` table into prompts. Summary phrases reappear in later agent text no more often than phrases from a placebo set (schema_notes 4.3). Agents do read summary text through their tools (the village API, goal pages, agent-built sites). Summaries are therefore never a parent in module B2. A tool read of summary text counts as an independent observation (env_i), as for any other tool output.

## 2026-09-30. Python environment on node-local disk

GRASP's NFS home takes about 0.36 s per small-file operation, so installing Python packages there takes hours. The venv and its Python build live on node-local `/scratch/tmp/enxinson/`. `scripts/pack_env.sh` packs them into one tarball `~/envs/avsd-env.tar` (1.3 GB). Every job sources `scripts/env.sh`, which unpacks the tarball on the node when the node lacks the current copy. All nodes use the same prefix, so absolute paths in the venv stay valid. After a dependency change, rerun `scripts/pack_env.sh`.

## 2026-09-30. Raw files downloaded with curl

The first download used `scripts/fetch_raw.sh` (curl with the token file) because the Python env was not ready. All 13 table files and the docs match the Hugging Face sizes and LFS sha256 at the pinned revision. `village-transcript.json` is not downloaded (SPEC 2.1).

## 2026-09-30. Full event payload kept

`events_text.parquet` keeps each event's full `data` payload as JSON (`data_json`), minus the raw model output (stored separately) and the viewer names of `USER_NAME_CHANGE`. The ingest QA showed payload keys that SCHEMA.md does not list (for example `currentRooms` on `ENTER_ROOM`, `speakerType` and `chatMessageId` on `USER_TALK`).

## 2026-09-30. Unified event table conventions (SPEC 4.1 steps 3 to 6)

Based on the SPEC 2.3 verification (`docs/schema_notes.md` section 4). Row counts are those observed on the pinned export.

- **Messages come only from `chat_messages`.** One row per chat id, timed by `chat_messages.created_at`. AGENT_TALK and USER_TALK events and `send_message_back_to_chat` turns are linked to that row, not emitted as messages. The 57 USER_TALK events without a chat row are emitted from events with a flag. Nothing is deduplicated by content.
- **Session starts come from `computer_use_sessions`.** One `session_start` row per session, because sessions after 2026-03-24 have no START event. START events become attributes of that row. STOP and CONSOLIDATE are `session_end`.
- **Duplicate turns.** Turns that mirror a chat row or an event (send message, search_history, pause, move_to_room, Google sign-in, outreach and human-helper requests) are kept with `dup_of_uid`. Modules A and D count the message or event, never the duplicate turn.
- **actor_type.** `agent` for agent rows, keyed by `coalesce(agent_id, speaker_id)` for events (never `speaker_type`). `system` for the scaffolding bot account (auto-nudger and daily run markers, 2,230 chat rows), RESTARTING_AFTER_GOOGLE_SIGN_IN, ENTER_ROOM rows with cost 0 and no output, the "Start up" session starts, STOP_HUMAN_USE_SESSION by timeout, and summaries. `human` for all other human rows, including staff-typed run markers, which get an `is_run_marker` flag. Outreach approvals are `human`, with the requesting agent kept as `target_agent_id`.
- **kind.** SPEC's list plus `system_msg` for bot chat rows. A `subkind` column keeps the finer type (raw action type, turn action, memory version type, summary type).
- **USER_NAME_CHANGE** (3,711 viewer renames) is not emitted. The QA report counts it.
- **village_day** is `(PT date - 2025-04-02) + 1`, counting weekends. This reproduces all 789 daily-summary targets. SPEC 2.2 describes a different rule that the data do not follow. `run_day` ranks PT dates with agent activity (389 days). Dates with only human chat (10 weekend dates) get no `run_day`.
- **Run intervals** come from agent rows only. Days with an off-schedule extra block (2025-06-18, 2025-06-29, 2026-06-29) are split at gaps longer than G into separate realizations for module A. The end-of-day consolidation tail is kept.
- **Eras.** `regime_cu` is set per agent at its first CONSOLIDATE (the Claude Code agent stays `pre`). `rooms_era` R0 before 2026-02-25, R1 to 03-15, R2 03-16 to 07-05, R3 from 07-06. `schedule_regime` follows the observed schedule blocks. Reference-based statistics are stratified by month or goal, because @-mention rates drift continuously.
- **Rooms.** An agent's room at any time is the room of its latest earlier room-carrying event, and `general` before 2026-03-05. This reproduces 173,486 of 173,493 message rooms using only earlier information.
- **refs.** URLs keep their query string except tracking parameters (SPEC 6.3.2). Paths, Google document ids and GitHub/GitLab repositories are normalised. References the actor produced go in `refs`. References only observed in tool output, errors or search answers go in `refs_obs`.
- **Fine-tuned leaders.** The two Tinker agents share one model and are pooled at the model level. The 32-turn test session on 2026-05-26 does not count as presence.
- **Premoderated human messages** are timed at `created_at`. A sensitivity check uses the approval time.

## 2026-09-30. Module-level consequences of the verification

- **Module A.** In R2, `best` holds 26% of messages with a disjoint agent set, above the 10% threshold of SPEC 5.1. We fit `best` and `rest` as separate populations. Nudges from the bot enter as their own exogenous source, next to humans, so the decomposition reports baseline, human, system, other agents and self.
- **Module B1** uses path S. A generation is a REWRITE row. APPEND rows are inputs to the next rewrite. IDENT rows are dropped. TRUNC rows that equal an earlier row are undos. The 53 fork rows are resolved by prefix search. The Claude Code agent is analysed separately.
- **Module B2 exposure.** Main rule: the reader was in the message's room when it was posted. Sensitivity: the reader was in that room at some time before its own message. A 2 s tolerance applies around ENTER_ROOM. Agents count as present only on days they act.
- **Parent labels (SPEC 5.6-3, 6.4.5).** Tier 1 is single-target reciprocal name references and quotes that match exactly one earlier message, from 2026-02-25 on (about 18k children, precision about 0.9 on a small sample). Earlier name references are tier 2 with undetermined precision. Earlier quotes are excluded (precision about 0.35). Name-reference labels serve the content-term ablation. Quote labels share text with their parent by construction, so they serve only the time kernel.

## 2026-09-30. Hawkes EM stopping rule (deviation from SPEC 5.3)

SPEC 5.3 stops when the relative log-likelihood change falls below 1e-6, within 500 rounds. On simulated data this stops 1 to 59 nats short of the maximum (worst at real window sizes, K = 20 to 30 and about 53k events), with decomposition shares off by up to 0.16 and the spectral radius by up to 0.18, while reporting convergence. The likelihood has a flat ridge between the baseline and the slow kernel component. `fit()` and the bootstrap refits stop only when the relative objective change is at most 1e-8 and one plain EM step moves mu and alpha by at most 1e-5 relative (L2 norm per block), with at most 2000 SQUAREM-accelerated iterations. Each accelerated step is kept only if it does not lower the objective, so the trace stays monotone. Fits then end within 0.05 nats of the maximum, with shares within 0.001. Bootstrap SDs are within 3% of fully converged refits. Plain EM remains available with `accelerate=False`.

## 2026-09-30. Time-rescaling pools days end to end

Restarting the rescaled clock each day and dropping each day's unfinished last gap biases the increments low by about 1/(events per agent per day). The KS test then rejects at the true parameters. `time_rescaling(pool="concat")` joins the days' rescaled axes, which is exact. `pool="day"` keeps the per-day version.

## 2026-09-30. Recovery limits of the per-cell kernel model

On simulated windows of real shape (K = 7 to 13, 5 to 10 days of about 3.5 h, 2k to 4k events) the SPEC 5.2 model with free kernel weights per cell recovers the decomposition shares with MAE 0.07 to 0.12, above the 0.05 bar of SPEC 5.6-1. Self-excitation is credited to other agents. Per-cell kernel shapes are weakly identified (single-edge mean delays off by 3 to 8 times). Unpenalized fits of real windows gave spectral radii of 1.01 to 1.39. `avsd.hawkes.validate.recovery_check` runs the SPEC 5.6-1 protocol for any window and `select_l1` chooses an L1 strength by held-out days. The remedy is pending the owner's choice (see PROGRESS.md).

## 2026-09-30. Owner choices on CHANGELOG categories and Hawkes kernels

- CHANGELOG categories extend the SPEC set with `goal` and `chat`. Every goal entry (goal and kickoff overrides) also carries `prompt`, so module C reports alignment both with goal changes as their own category and pooled with prompt changes. Chat mechanics (Rooms v1, premoderation, auto-nudger, room soft-delete and moves) are `chat` instead of `other`. The owner asked for both goal variants to be tried.
- Module A shares kernel shapes by source class (self, other agent, each exogenous source), with a free branching ratio per cell (`kernel_sharing="class"`). This changes the SPEC 5.2 model to address the small-window recovery failure above. Each real window is still checked with the SPEC 5.6-1 protocol, and windows that fail are merged with a neighbour.

## 2026-09-30. External validation against the AI Village LLM monitor (owner's request)

AI Digest publishes daily findings of an LLM monitor (Claude Opus 4.8) at theaidigest.org/village/monitor. Each finding has a category (conflict, off-goal, emotional-or-erratic, likely-scaffolding-issue, surreptitious-or-deceptive, outside-agent-contact, human-contact, unsolicited-outreach, good-tweet, interesting-content, other), a severity, a confidence, the agents involved and a timestamp. The findings cover 2026-06-16 to 2026-09-28 (plus 2026-04-06), so about three months overlap with the pinned export. `avsd.validate.monitor` fetches the public API once (1.5 s between requests), keeps the raw responses under `data/raw/monitor/`, and writes `data/processed/monitor_findings.parquet`. Finding text stays in `data/`. The page is live, so the fetch time is recorded.

The monitor is a second, independent reading of the same days. We use it to check our measurements, not as ground truth (its precision is unknown).

- **V1, module A, event level.** For conflict findings and other findings that involve two or more agents, compare the Hawkes share of parent probability that comes from other agents for messages by the involved agents within ±30 minutes of the finding against the same agents' messages in the same realization outside any flagged window. Bootstrap the difference by realization.
- **V2, module A, pair level.** Percentile rank of n_ij + n_ji for the flagged agent pairs among all pairs of the same fitting window, and the share of conflicts within versus between the spectral clusters.
- **V3, module C.** Daily monitor counts by category become extra series. Change points inside the monitor period are listed with the findings within ±w run days (category, severity, paraphrased heading). For change points with no CHANGELOG entry this is an annotation only, with no causal claim. An alignment test like the CHANGELOG test uses the dates of likely-scaffolding-issue and emotional-or-erratic findings.

## 2026-09-30. Module C detection and alignment settings

- **Series.** 543 candidates, 387 analysed (45 family-level, 258 per-agent, 84 lexical). A series is sparse when its median daily count is below 10 and is then pooled into 5-run-day bins. Every series needs at least 12 points. Messages and events are counted once, never as duplicate turns. Turns per session counts every turn of a session. The Claude Code agent is left out of family and all-agent series (different scaffold) but keeps its own series.
- **Penalty.** PELT penalty β·log n with β = 2 on series scaled by the MAD of first differences, minimum segment 10 run days. Residuals have lag-1 autocorrelation 0.16 and 2.4 times the robust variance, so plain BIC over-splits. We report a β sweep (0.5 to 8) and a "persistent" subset of change points that survive 4 times the penalty.
- **BOCPD.** Normal-Gamma model, hazard 1/100 run days, change points from backtracking the most probable run lengths. Used as a robustness check (45.5% of l2 change points have a BOCPD change point nearby, against 17.9% by chance).
- **Location intervals.** Block bootstrap with 5-run-day blocks, 200 replicates.
- **Composition check.** Family-level change points are recomputed with agents active on at least half the days on each side within a 20-run-day window; a shift counts when Welch p < 0.05 and the effect ratio is at least 0.5.
- **Alignment nulls.** CHANGELOG entries dated on non-run days move to the next run day. Null 1 shifts all entries together and excludes shifts within 2w of zero (near-zero shifts reproduce the observed alignment); the exact p-value over all allowed offsets is also reported. Null 2 places the 110 distinct entry intervals (186 entries) uniformly over run days. Holm adjustment across category rows.
- **Lexical series.** Rates per 1,000 messages, log-odds with an informative Dirichlet prior (total 1,000). Stop words, proper nouns, viewer-name tokens and key-like strings are excluded. Candidates need 50 uses on 10 run days by 2 agents.
- **Power.** At w = 3 run days, 81% of run days lie near some entry, so the CHANGELOG test has little power. A w sweep (0 to 3) is added, with w = 1 as the headline for scaffolding-only sets.
- **Documented goal transitions.** Village goal changes (`village_goals.start_time`) and per-agent goal changes (`agent_goals`) are documented changes of the environment that the CHANGELOG does not list. They form separate entry sets next to the SPEC's CHANGELOG-only test. A change point is "cause unidentified" only when no documented event of either kind lies within w.

## 2026-10-01. Module C round 2: documented goal changes, window sweep, monitor sets

- **Agent goal changes** are tested over the agent-goal era only (from 2026-07-06, 55 run days). Each change counts for that agent's series and for the family and all-agent series that include it. Entries on the same run day move together. Agents that joined later get their first goal at their join, which coincides with the start of their own series, so this part leans conservative.
- **Null 2** draws distinct start days (matters for dense date sets). This moved some earlier numbers slightly, for example all CHANGELOG entries at w = 3 from p = 0.970 to 0.998.
- **Holm families.** CHANGELOG category rows form one family; goal and monitor rows form another. The "all entries" and "scaffolding" rows are summaries and are not adjusted.
- **Monitor sets.** The coverage window is 2026-06-16 to 2026-09-18 (64 covered run days); the isolated 2026-04-06 is used only in per-change-point annotations. Medium/high likely-scaffolding-issue and emotional-or-erratic findings occur on 55 and 60 of the 64 days, so those entry sets cannot discriminate at w ≥ 1. High-severity variants are reported as well. Monitor findings are annotations, never causes; the change-point × finding link table holds ids, categories, severities, confidences and offsets only.
- **Labels in the change-point table.** `aligned` and `cause` stay CHANGELOG-only at w = 3 (SPEC). `cause_documented` also counts village and agent goal changes. Gap columns allow re-deriving alignment at any w.
- **Weekday confound.** 39 of the 51 village goal transitions start on a Monday, and change points of daily series fall on Mondays about twice as often as on other weekdays. Null 1 (shifts by arbitrary run days) and null 2 (uniform placement) therefore disagree for goal transitions. Round 3 adds week-preserving nulls and a weekday-adjusted detection run before any goal-transition result is reported.

## 2026-10-01. Module C round 3: week-preserving nulls and weekday-adjusted detection

- **Null 1w** shifts all entries together by whole calendar weeks on a circle of the weeks that cover the allowed run days (77 weeks overall, 11 in the agent-goal era) and maps back with the next-run-day rule. Shifts within 2w of zero are excluded, counting a week as 5 run days. With 76 allowed shifts its smallest p-value is 1/77, so Holm values over nine category rows cannot fall below about 0.12.
- **Null 2w** places each entry among the run days that share the weekday of its start run day (weekend run days form their own small classes), with distinct starts.
- **Weekday-adjusted detection.** Weekday effects are the median deviation from a centred 5-point rolling median on each weekday, estimated over the whole series. l2 at the default penalty only. 1,513 of 1,543 original daily change points keep an adjusted one within 1 run day, and the Monday share stays at about 33% (Mondays are 19.5% of run days). So the Monday concentration of change points does not come from Monday levels.
- **Reading.** Under the week-preserving nulls the w = 1 alignment with village goal transitions disappears (null 1w p = 0.33, null 2w p = 0.27); same-day coincidences remain under null 2w (p = 0.005, Holm 0.014). Because 39 of 51 transitions start on a Monday and change points concentrate at week starts, the data cannot separate goal transitions from the start of a week. The write-up reports it this way, without a causal claim.

## 2026-10-01. Module B1 definitions

- **Unit identity.** The context key is part of a fact unit's identity only for numbers, money, percentages and times. URLs, dates, agent names and entities are identified by value alone; their context only serves to detect "modified". Otherwise every rephrasing would count as a drop.
- **Modified.** A loss counts as modified only when the same context now holds a value that the previous consolidation output did not hold.
- **Survival event.** The first loss, dropped or modified (SPEC 6.3.2). Drop-only and modification hazards are reported separately. Restorations (18.4% of lost facts) are an upper bound, since a later unrelated fact can share a unit key.
- **Label pairs** (SPEC 6.3.4) pair a consolidation's input row with its output, because facts in appended text are at risk too. 100 pairs, 5 units each, in `data/labels/memory_pairs.csv`; precision and recall wait for the owner's labels.
- **Extraction.** Each distinct line is processed once; scaffold session labels are removed. Values on credential lines or under credential or account headings are hashed, as are digit runs of 9 or more. Email and phone are hashed anchor types. Context lemmas used by fewer than 3 agents are hashed in outputs. The context key is the dependency-head noun first ("3 days" gives "day"), then the nearest noun chunk.
- **Statistics.** Besides the likelihood-ratio test against a piecewise-constant hazard (g = 1, 2, 3-4, 5-8, 9+), a cluster Wald test (by agent) and a beta-geometric fit are reported, because the naive LR test is anticonservative and the beta-geometric model separates fact-to-fact heterogeneity from a hazard that truly changes with g. A generation is reported with at least 30 units at risk; CIs from fewer than 5 agents are flagged.
- **Reading.** H2 is rejected in every family, regime and memory-change epoch, but the beta-geometric model fits far better than the piecewise model (AIC lower by 61,359): the falling hazard mostly reflects a mix of durable and fragile facts, not facts becoming safer with age.

## 2026-10-01. GRASP node al-l40s-0

`/scratch` is not writable on al-l40s-0, so `scripts/env.sh` cannot unpack the environment there. All sbatch scripts exclude that node, and `env.sh` stops with a clear message on any node where `/scratch/tmp` is not writable.

## 2026-10-01. Module D1: reference implementation and reproduction

- The owner has no code from Wenhao Chai directly, but the blog page ships its own simulator: it loads `assets/data/edgebench-logsigmoid.js` (header: "simulation core of the Predictable Swarm Scaling post") and `assets/swarm-worker.js`. We did not execute or copy it. `avsd.swarmsim` is a Python re-implementation from the blog text and SPEC appendix B; points the text leaves open were settled by reading that code (task-draw clamps, layer rounding, the definition of a sibling, the extra-parent walk, clock normalisation, the 5% + 5% start-and-handover overhead, when communication cost is fixed, slot filling, shuffling in the recursive swarm). Each point is listed in `outputs/qa/swarmsim_d1.md`. The write-up acknowledges the blog's code.
- All 15 required SPEC 8.2 checks pass within 20% over 256 independent 16-task families (seed 20261003, no tuning). The largest gaps are the 64-agent finish time (0.081 T₁ against "about 0.10", −19%) and the speedup at best score 0.8 (18.1 against 16, +13%). The blog's single-family values sit at the 80th to 86th percentile of our families for g50, finish times and λ@64; their cause is unidentified and nothing was changed in response.

## 2026-10-01. Module B1: heterogeneity versus duration dependence (BdW)

- **Model.** Beta-discrete-Weibull (Fader, Hardie, Liu, Davin and Steenburgh 2018): θ ~ Beta(α, β) per fact, S(g | θ) = (1 − θ)^(g^c). c = 1 is the beta-geometric model. Exact maximum likelihood with right-censoring, every g kept individually. The regime split is by cohort: facts that entered before an agent's switch to perma-computer-use are censored at the switch, so neither cohort is left-truncated. CIs for c come from 500 agent-level bootstrap refits. A "from g = 2" variant conditions on surviving the first consolidation. The LR test of c = 1 treats facts as independent and is anticonservative; the CI rule decides.
- **Result.** In the main fits c > 1 (all standard agents 2.56 [1.78, 4.90]), driven by a two-step pruning pattern after the switch: the consolidation right after a session keeps the session's facts and the next one prunes them, so the hazard rises from g = 1 to g = 2. Conditional on surviving the first consolidation, c covers 1 for all standard agents (0.71 [0.45, 1.04]) and for the post-switch cohort (0.89 [0.56, 11.3]): consistent with heterogeneity alone. The pre-switch cohort shows clear duration dependence from g = 2 (c = 0.18 [0.15, 0.44]): under the old memory system, facts that survived longer became safer.
- **Repeated spells.** Second spells of restored facts have slightly lower hazards than first spells at the same g (like-for-like subset of 177,755 facts, all five bins below 0). First spells are selected to end in a loss, so this is reported descriptively.
- **Write-up wording.** Do not say "the decline is pure heterogeneity". Say: in the current memory system, beyond a two-step pruning of session notes, retention is consistent with constant per-fact hazards that differ between facts; under the earlier system, surviving facts also became more durable.

## 2026-10-01. B1 label validation: local pre-labelling (owner's choice)

- **Model.** Qwen/Qwen3-14B (revision 40c0698, Apache-2.0), bf16, inference only, on one GPU (NVIDIA L40). vLLM is pinned to 0.19.0 because most GRASP GPU nodes run driver 535 and later vLLM versions need a newer driver. Thinking disabled, temperature 0, seed 20261003, JSON-schema output. Weights were downloaded anonymously to `~/models/Qwen3-14B`. Prompts and outputs are cached in `data/interim/llm_cache/memory_prelabel/` (SPEC 3.4).
- **Prompt choice.** Four prompt versions were tried; the final one has a step-by-step decision rule and states how often the value occurs in each version. The rule label is never shown to the model, but versions were compared partly by agreement with the rule labels. Rule-versus-model agreement (62.0%, kappa 0.52) is therefore not an independent validation. Only the owner's labels count as ground truth; the model labels are a review aid.
- **Review design.** All 190 disagreements plus a stratified random sample of 60 agreements (seed 20261003) are to be labelled; the remaining agreements are optional. Precision, recall and F1 are estimated with stratum weights and bootstrap CIs.
- **Rule problems found.** For 95 of the 500 units the value's text is present in a version where the B1 rules found no occurrence, and rule "modified" agrees with the model on only 14 of 92 units. A revised rule set (B1 v2: literal-presence fallback, same-line requirement for "modified") is computed next to v1; both are scored against the owner's labels.

## 2026-10-01. File permissions on GRASP

The home directory is world-readable and job outputs were created with mode 644, so other cluster users could read the gated dataset and the personal text under `data/`. `data/` is now mode 700 (files 600), and `scripts/env.sh` sets `umask 077` so new files stay private.

## 2026-10-01. Module B1 rule-set sensitivity (v1, v2, v3)

- **v2** adds a literal-presence fallback (a unit is present if its value occurs literally, for numbers with the context word on the same line) and requires "modified" to replace a value on the aligned line. 31.7% of v1 first losses are kept under v2 (time 52%, entities 30% to 45%, URL 3%); the modification share of first losses falls from 0.233 to 0.052; h1 for all standard agents falls from 0.522 to 0.340.
- **Robust across v1 and v2:** H2 is rejected; the hazard falls with the number of consolidations survived.
- **Rule-dependent:** the BdW reading. From g = 2, c covers 1 for all standard agents and the post-switch cohort under v1, but all three CIs exclude 1 under v2. v2 over-keeps recurring generic values (clock times, numbers), which builds long survival tails and probably biases c low.
- **v3** keeps the v2 entity fallback and requires the context word adjacent to the value for time, number, money and percent.
- **Choice of rule set.** The rule set for the headline is chosen from the owner's labels (weighted precision and recall, SPEC 6.3.4), never from agreement with the LLM labels. The write-up reports which conclusions hold under every rule set and which depend on the presence rule.

## 2026-10-01. Module B1 v3 and a corrected BdW reading (supersedes the "from g = 2" reading above)

- **v3** keeps the v2 entity fallback and requires the context word adjacent to the value for time, number, money and percent. It rescues 11.3% of v1 losses (v2: 31.7%); time 3.3%, number 6.8%. h1 for all standard agents: v1 0.522, v2 0.340, v3 0.463; h9+: 0.045, 0.025, 0.025. Modified share of first losses: 0.233, 0.052, 0.066.
- **Correction.** The "from g = 2" BdW fits still parameterise the first-trial Beta mixing, which they never observe; several end on the edge of the parameter space (α near 1e8 or β near 0), so their c is weakly identified. The earlier statements that c covers 1 for all standard agents and the post-switch cohort (v1) rest on such fits and are withdrawn.
- **Identified alternative.** Survivors of the first consolidation, with the clock restarted (g' = g − 1). Under pure heterogeneity the survivors are again beta-geometric, so c' = 1 still means heterogeneity alone. No fit is at a boundary. c' for all standard agents: v1 0.863 [0.802, 0.934], v2 0.875 [0.818, 0.927], v3 0.860 [0.800, 0.919]; pre-switch and post-switch cohorts 0.80 to 0.91, all CIs below 1.
- **Reading, robust across v1, v2 and v3.** H2 is rejected in every family; the hazard at g ≥ 9 is below the hazard at g = 1; after the perma-computer-use switch the hazard rises from g = 1 to g = 2 (two-step pruning of session notes); most first losses are drops; the beta-geometric beats the geometric; the falling hazard is mostly fact-to-fact heterogeneity plus modest duration dependence within facts (c' ≈ 0.86). Magnitudes (h1, h2, h9+, the modified share) depend on the rule set and are reported for the rule set the owner's labels favour.

## 2026-10-01. Hawkes stopping rule for shared kernels (extends the 2026-09-30 stopping rule)

- Per-cell kernels keep the 2026-09-30 rule, with three changes: the step test is measured on the expected event counts implied by mu and alpha (at most 1e-5, L2 per block), a rejected SQUAREM step is retried, and the L1 penalty acts on n. Cell numbers quoted before 2026-10-01 come from the first version.
- Shared kernels (class, global) have a non-concave likelihood. The EM step test stopped more than 0.05 nats short in 14 of 160 simulated windows and 0.44 nats short on real window R2, and EM cannot revive a collapsed n. Once the objective test passes, projected Newton steps take over. A fit counts as converged only when the reduced Hessian is negative definite and the predicted remaining gain is at most 1e-6 nats. Continuation gains are below 1e-4 nats on 160 simulated windows and on R0, R2 and R3. Bootstrap SDs equal those of tight refits.
- Shared fits start from three points (uniform, a global-sharing fit, a cell fit) and keep the best. The uniform start alone ended up to 2.2 nats lower in 13 of 160 simulated windows, and 0.65 nats lower on R2.

## 2026-10-01. Hawkes recovery metric and window acceptance

- The recovery metric is the MAE over the SPEC 5.5 four-way decomposition (baseline, human, other agents, self), with the exogenous sources (human, system nudges) pooled as human (`mae4`). The five-way MAE averaged in two near-empty categories and understated the error. Outputs still report all five shares.
- On the simulated grid, class sharing misses the 0.05 bar at every K on `mae4`. The grid uses generator settings that do not match the real windows, so its error levels hold only for that regime.
- `recovery_check` (the SPEC 5.6-1 protocol, which simulates from the fitted parameters and refits) is optimistic. On the grid it passes most windows whose error against the true parameters exceeds the bar.
- Window acceptance keeps the owner's 2026-09-30 rule. Each real window is checked with the SPEC 5.6-1 protocol on `mae4` with 20 replicates, and a window that fails is merged with a neighbour. Matched-truth runs (`scripts/hawkes_matched_recovery.py`) are reported for every window as a sensitivity range. The arms are the fitted truth, slower kernels, faster kernels, self n +0.05, self n +0.10 and the grid's kernel shapes. On R0, R2 and R3 the fitted truth gives `mae4` 0.029, 0.033 and 0.036. Slower kernels give 0.061 on R2. Grid shapes give 0.053 on R0 and 0.051 on R3. The owner may tighten the gate to the matched-truth range.
- Exogenous class shapes that rest on fewer than about 50 expected children are not identified (R2 and R3, human and system). They are flagged in the outputs and are not used as interval laws in module B, which uses the empirical interval distribution for those sources. A variant that ties low-count exogenous shapes to the other-agent shape runs as a sensitivity analysis.
- Real-window conventions. The system source is the auto-nudger's nudges only, and bot run markers are excluded. Run markers typed by staff stay in the human source. Each run day is a run_periods realization with t = 0 at its start. Exogenous messages of the same date posted before the start are placed at t = 0.
- Per-cell reruns after the fix: grid `mae` 0.077 to 0.113 and `mae4` 0.096 to 0.139 by K. Spectral radius of the cell model on R0, R2 and R3: 0.84, 0.97 and 1.10.

## 2026-10-01. B1 pre-labels re-checked with stronger local models (owner's request)

- The owner asked that stronger LLMs re-check the Qwen3-14B pre-labels before the owner reviews them. The owner approved two downloads from the official Hugging Face repositories, made anonymously: Qwen3.5-122B-A10B-FP8 (about 127 GB, Apache-2.0) and gpt-oss-120b (about 65 GB, Apache-2.0). The weights are deleted after the run.
- GRASP's GPU driver (535) limits us to vLLM 0.19 (released 2026-04), so models released after April 2026 are out. Larger supported models (Qwen3.5-397B-A17B-FP8 at 406 GB, GLM-4.7-FP8 at 362 GB) do not fit on one node of 8 GPUs with 48 GB each. The only 96 GB-GPU node is not available to our account.
- Each model labels the same 500 units with the same prompts as Qwen3-14B, without seeing the Qwen3-14B or rule labels. The review sheet is redesigned from the result, with recorded inclusion probabilities so that the precision and recall of the rule sets are design-weighted.

## 2026-10-01. Hawkes exposure by presence (supersedes the first real-data run of module A)

- **Rule.**
  - Module A counts target i's baseline and kernel compensator only on realizations where agent i is present.
  - Present means: it has an agent row inside the run block while it is in the group's room. This uses events_unified.agent_room_id; rows that agents.PRESENCE_EXCLUDE drops from the roster do not count. This is roster_daily.active refined to the block and the room.
  - An agent with a message in the room is always present.
  - On realizations where it is absent, an agent has no baseline and no children. This holds in the fits (per-target exposures E (K, bins) and W (K, K+H, M)), in the simulations of the recovery check and matched arms, in time-rescaling and in the expected-children counts.
- **Why.**
  - Without presence, agents absent on many days accrued compensator on those days. The fit set their mu near 0, explained their bursts by self-excitation, and let a single part-time agent set rho.
  - First run: rho > 1 in 17 of 44 goal windows (5 with intervals above 1) and 22 of 92 rolling groups.
  - With presence: 3 of 43 goal windows, none with an interval above 1, and 5 of 92 rolling groups.
  - Over part-time dimensions with at least 21 events, median n_ii falls from .97 to .29 and the median within-agent self share from .85 to .26. Dimensions with n_ii ≥ 1 fall from 18 to 3. Core dimensions are unchanged (median n_ii .39 vs .37).
  - Known-truth check: simulating from the presence-aware fits of g01 and g04 (true rho .92 and .93), the all-present model gave rho > 1 in 16 of 16 replicates (1.04 to 1.15). The presence model gave .89 to .97.
- **Room, not date.**
  - Room and date presence coincide in R0 and R1. They differ in 9 of 43 goal windows (R2 best/rest and g51) and 14 of 92 rolling groups: 4,671 agent-realizations are active, 4,474 of them in the group's room.
  - Examples: g38-39 rest has rho 1.087 with date presence and .917 with room presence; g41-43 rest 1.144 and .842.
- **Sensitivity row.** The `core` variant in hawkes_sensitivity.csv, and rho_core in the window tables, give rho over agents present on at least 80% of a window's realizations (`hawkes.core_presence`).
  - Dimensions with few events can still set rho. In g35-39 best, Claude Haiku 4.5 (11 messages on 2 of 35 realizations) has n_ii 1.76 and rho is 1.76, while core rho is .92.

## 2026-10-01. Hawkes bootstrap: the point estimator in every replicate, resampled by run date

- **Estimator.** Each of the 1,000 replicates per window is fitted from fit()'s three starts (uniform, global, cell) and from the full-data fit, and keeps the highest objective. In effect this is the point estimator plus the full-data optimum as a fourth start.
  - In the first run the warm start alone ended more than 0.1 nats below the multi-start optimum in 34 of 44 windows (24 replicates each, up to 52 nats). It moved interval bounds by up to 0.22.
  - In this run the three starts won by more than 0.1 nats in 5,227 of 43,000 replicates (41 windows). The warm start won in 587 (29 windows).
  - Cost: about ten times a warm refit, roughly 109 core-hours for the boot stage.
- **Resampling unit.** The run date: the two blocks of a date with an off-schedule extra block are drawn together.
- **Intervals.** Percentiles; normal intervals (estimate ± 1.96 SD) are kept in hawkes_decomposition.csv.
  - Replicates of 5-date windows keep 3.36 of 5 dates.
  - Median replicate mean minus estimate: −.051 for self, +.022 for baseline, −.036 for rho.
  - The estimate lies outside its percentile interval for self in 1 window (g46-47 rest), for other agents in 2 (g14 and g30, on the lower bound), and for rho in none.

## 2026-10-01. Hawkes recovery gate: exploded and borderline replicates, reported biases

- **Exploded replicates.** A simulated replicate with more than 10× the window's agent events, or 50× its candidate parent pairs, is a supercritical cascade unlike the data. It is not refit, and the window fails the SPEC 5.6-1 check.
  - g35-37 best (rho 1.80) produced replicates with up to 89× the pairs. One replicate ran for more than 20 minutes, and the smoke run, which had no cap, recorded an OOM kill.
  - Matched arms record such replicates as errors.
- **Borderline windows.** When the mean mae4 over 20 replicates lies within 2 Monte Carlo SE of 0.05, 20 more replicates are run and the decision uses all 40. This happened for 20 windows and changed one decision (g41 rest, .0503 to .0470).
- **Reporting.** The acceptance log and the window table report, per window:
  - the bias of all five shares and of n by cell type, and the SE of mean mae4;
  - exploded replicates and objective decreases.
  - Final windows have a mean self-share bias of −.048, n_ii bias −.055 and exogenous n bias +.099.

## 2026-10-01. Module A on the real data: windows, populations, L1 and acceptance (builder's draft, updated)

- **Realizations and events.**
  - Each run_periods block is one realization, with t = 0 at its start.
  - The events of an agent's dimension are its messages in the group's room.
  - Human messages in that room form the source `human`, with staff-typed run markers kept as human. The auto-nudger's nudges form the source `system`. Bot run markers are left out.
  - An exogenous message goes to the first included block of its Pacific date that ends at or after it, at t = max(0, ts − start). Messages after the last block of their date are dropped: 3 of them; 208 messages were clipped to t = 0.
  - No realization spans a goal boundary.
- **Populations.** Each room with more than 10% of a window's agent messages is its own group.
  - Rooms below 10% are not fitted. On the pinned export this leaves out 4,169 agent messages: focus 3,461, general 290, voted-out 245, showcase-live 143, and 30 in other rooms.
- **Merge rule (SPEC 5.4).** Applied per room as drafted by the builder. The 51 goals give 54 populations.
- **Acceptance.**
  - Round 0 failed 12 of 54 windows. Round 1 failed g35-37 best (exploded) and G40. Round 2 failed only G40 universe-coordination (mae4 .069), which has no adjacent window.
  - 43 final windows; G40 stays in the tables, flagged as failed, and is left out of F1 and F2.
  - Matched-truth arms (6 arms, 8 replicates, with presence) are reported as a range. 19 windows have at least one arm at 0.05 or more, 14 of them under slower kernels.
- **L1 policy: none (l1 = 0).** The grid and probe evidence is unchanged from the builder's draft.
- **Identification.** A class shape with fewer than 50 expected children is flagged as not identified. Expected children now count only source events on days the target is present.
  - Every class of a window that failed acceptance is flagged too.
  - The tied-shape variant moves rho by at most .025 and shares by at most .059 in accepted windows.
- **Sensitivity to G.** Blocks for G = 15 and 60 min are rebuilt with find_blocks. G = 60 leaves every window unchanged; G = 15 changes 4 windows (max |d rho| .070).
- **Validation 3.** The reference-check cluster bootstrap sorts clusters by realization, so a seed gives the same intervals in every process.
- **Outputs for other modules.**
  - hawkes_kernels.parquet: goal and rolling windows of fitted rooms only.
    - R2 best and rest windows overlap in dates, so a lookup must choose the window by room and date together.
    - B2's current date-first lookup sends 66 of 460 fitted room-dates to the empirical kernel. The change belongs in src/avsd/lineage/trees_kernel.py (HawkesKernel: filter windows by group before the date search) and is for the B2 owner.
  - hawkes_rolling.parquet: module C's hook. Its spectral_radius is presence-aware, with the same schema.
  - hawkes_parents.parquet: goal windows only, with window_id and group columns.

## 2026-10-01. Module A reporting choices (defaults set by the orchestrator; the owner may override)

- **Presence.** Use room-level presence (the agent has a row in the run block while in the group's room). It is the exposure that matches a room-level fit.
- **Spectral radius.** rho stays the SPEC 5.5 spectral radius of the full N_AA. rho_core (agents present on at least 80% of realizations) is reported next to it. A window where a dimension with few events sets rho is flagged in the text. Only g35-39 best is affected: rho 1.76 [0.90, 3.82], set by an agent with 11 messages, core rho 0.92.
- **G40** (universe-coordination) fails the recovery check (mae4 0.069) and has no adjacent window. It stays in the tables flagged as failed, is left out of F1 and F2, and is named in the write-up.
- **Recovery gate.** Exploded replicates fail a window. Borderline windows (within 2 Monte Carlo SE of 0.05) get 20 more replicates. The owner's 2026-09-30 gate (SPEC 5.6-1 at the fitted parameters) is kept. Matched-truth arms are reported as a range: 19 of 43 windows have at least one arm at 0.05 or above, 14 of them under slower kernels.
- **Intervals.** Percentile intervals from 1,000 run-date bootstrap replicates. The write-up also states the estimator's bias. Both the recovery check and the bootstrap put the self share about 0.05 too low (recovery: mean self-share bias -0.048, n_ii bias -0.055).
- **Explicit-reference check (SPEC 5.6-3).** The SPEC metric is reported first. The most probable parent, including self and background, matches the tier-1 label for 0.150 [0.140, 0.160] of 16,851 labelled children, against 0.343 [0.321, 0.367] for the most recent message by someone else. Restricted to other speakers' events, the match is 0.386 [0.371, 0.405], 0.025 to 0.059 above the baseline, and most of the gain comes from G51.
- **G51** (55 run days) stays one main window, as SPEC 5.4 defines windows by goal. The rolling windows cover change within it.
- **Kernels for B2.** The window lookup must use room and date together, because the R2 best and rest windows overlap in dates. B2 was asked to rerun with the presence-aware table.

## 2026-10-01. Module C rerun with module A and B1 series

- Module C was rerun (job 598134) after module A wrote `hawkes_rolling.parquet` (presence-aware spectral radius and shares for the general and rest groups, 5-run-day blocks). B1's monthly hazards (rule set v1, the current default) were added in the same run. The round-3 outputs are kept in `data/interim/changepoint_round3_backup/`.
- The external series set grew from 55 monitor series to 85 analysed series. Alignment rows of the series sets all, agent, family and lexical are identical to round 3, so every module C conclusion stands. Change points of the external set are not aligned with the CHANGELOG beyond chance either: 127 of 142 aligned at w = 3 against a null mean of 132.9, p = 0.81.
- The B1 hazard series follow the B1 rule set. If the owner's labels select v2 or v3, module C is rerun with that version.

## 2026-10-01. External validation of module A against the LLM monitor: V1 and V2

- **Command.** `python -m avsd.validate.monitor_hawkes` (`scripts/monitor_validation.sbatch`). Outputs: `tables/monitor_v1.csv`, `monitor_v2.csv`, `monitor_v2_pairs.csv`, `qa/monitor_validation.md`. Per-message probabilities stay in `data/interim/monitor_validation/`. The monitor is a second reading of the same days, not ground truth, and no result is read as a cause.
- **Findings.**
  - Only findings in the export that involve roster agents are used. Other names are counted but never listed.
  - Repeats with the same category, timestamp and roster agents count once (14 repeats).
  - The V1/V2 set is every conflict finding with at least one roster agent, plus every finding of any category with at least two. That gives 1,483 findings, 80 of them conflicts, all on dates of 8 accepted goal windows.
  - 1,948 of 1,951 exact times of labelled findings lie inside the label's reading window.
- **Parent probabilities.**
  - `hawkes_parents.parquet` keeps only parents with prob >= 0.01. That drops 0.03 to 0.13 of the probability mass per message (window means), and more in busy windows.
  - So parent probabilities are recomputed per message from the module A fits. The recomputation matches every stored row exactly. The stored table is kept as a sensitivity row.
- **V1 rule.**
  - Flagged messages are an involved agent's messages within ±30 min of a V1 finding.
  - Control messages are the same agent's messages in the same realization and group, outside the windows of every V1 finding that involves that agent. The plan's "outside any flagged window" is read per agent, because excluding the windows of all V1 findings keeps only 16% of the controls. That stricter version is a sensitivity row.
  - Strata are (window, group, realization, agent). The estimate is the difference of stratum means, weighted by flagged messages, with a percentile bootstrap over realizations.
  - Two measures were added: the share on the agents a message's agent was flagged with (co-involved), and the agent's own and other agents' messages in the preceding 10 min. Strata that also split by hour of the run are a sensitivity row.
- **V1 result.** 1,426 findings enter: 21,184 flagged and 20,824 control messages over 64 realizations.
  - The other-agent share is lower near findings, −0.020 [−0.026, −0.013]. Within the same hour of the run the gap is −0.005 [−0.013, 0.005], so it mostly reflects when in the run findings fall.
  - Self is higher, +0.039 [0.026, 0.052] (same hour +0.028 [0.017, 0.040]). The involved agents post more of their own messages in the preceding 10 min (+1.05 [0.69, 1.40]).
  - Human and system shares move by at most 0.003.
  - Conflicts (78 findings, 1,956 flagged messages, 39 realizations): other agents −0.018 [−0.030, −0.007] (same hour −0.002 [−0.024, 0.020]). The share on the other agents of the conflict rises from 0.041 to 0.050, +0.009 [0.003, 0.014] (same hour +0.015 [0.002, 0.030]), and stays above 0 in every sensitivity row except ±60 min.
- **V2 rule.**
  - Each pair of a finding's roster agents gets the mid-rank percentile of n_ij + n_ji among all pairs of the accepted goal window of its date in which both agents are dimensions (4,811 of 4,819 pairs).
  - Intervals resample the findings' run dates and take n from one module A bootstrap replicate per draw.
  - References are all pairs (0.5) and the pairs of agents active in that group on that date.
- **V2 result.**
  - Conflict pairs: mean percentile 0.620 [0.547, 0.681] (299 pairs, 76 findings, 37 dates), 0.109 [0.035, 0.165] above active pairs.
  - All V1/V2 findings: 0.646 [0.609, 0.656] (4,811 pairs), +0.130 [0.093, 0.139].
  - Counted once per distinct pair, the excess is small: conflict 0.559 [0.499, 0.611] (+0.047 [−0.014, 0.098]), all 0.520 [0.499, 0.547] (+0.005 [−0.020, 0.027]).
  - So the agreement comes from repeatedly flagged pairs. DeepSeek-V3.2 with GPT-5.1 (118 findings, 12 conflicts) sits at the 98th percentile.
- **Clusters.** Module A's eigengap rule finds one cluster in all 8 windows, so the within-versus-between comparison is not informative. Forced partitions into k = 2, 3 and 4 clusters disagree (conflict within-cluster share minus expected: +0.18, +0.02 with an interval covering 0, +0.21). No cluster statement goes into the write-up.
- **Write-up wording.**
  - Report the same-hour V1 estimates next to the plan's estimate.
  - Say that near monitor findings, module A attributes more of the involved agents' messages to their own earlier messages, and for conflicts slightly more to the other agents named in the conflict. Say that pairs the monitor flags often are among the most strongly coupled in N_AA.
  - Do not say the monitor confirms excitation, and give no cause.
- **V3.** Done in module C round 2 (series, annotations, alignment test). The plan's paraphrased headings are not shown, because finding text can name people.

## 2026-10-01. Module B1: BdW convergence flag

- **Finding.** The `converged = False` rows in memory_bdw*.csv were spurious. They were v1 all standard agents, Google, Other and work_of_art; v2 all standard agents, Anthropic and Claude Code; and v3 pre-switch cohort from g = 2. Nelder-Mead tested absolute tolerances of 1e-7. scipy's betaln loses up to about 1e-10 per term for arguments between about 170 and 1e6 α. That puts 1e-6 to 2e-2 nats of rounding error on log-likelihoods of 1e6 to 1e7, so the flag depended on rounding and on the node's CPU.
- **Check.**
  - Risk sets were rebuilt from memory_facts and the live rows. They equal memory_hazard*.csv for g ≤ 20 and every count in memory_bdw*.csv.
  - All 78 table fits and 9 survivor fits were reproduced bit for bit and taken to their exact maxima in 30-digit arithmetic.
  - Interior fits were within 1.8e-5 nats and 9.1e-5 in c. Fits with α or β at the edge of the range were within 2.1e-4 nats. No estimate changed.
- **New flag.**
  - A fit counts as converged when one more Newton step would raise ll by at most 1e-3 nats and move c by at most 1e-3, with no direction of upward curvature.
  - The step comes from the analytic score and a difference Hessian of it. Parameters at the edge of the search range stay fixed. Directions flatter than 1e-6 of the steepest (the ridge of a mixing distribution at its limit) are left out.
  - The tolerance is absolute because likelihood-ratio inference works in nats (1.92 for a 95% profile interval).
  - All rows now pass.
  - memory_bdw*.csv gains a `boundary` column (α or β outside 1e-4 to 1e6). It is true for Claude Code under every rule set and for the starred from-g = 2 rows.
- **Bootstrap.** Replaying 500 refits for 31 scopes reproduces every stored CI. All survivor refits converge. In the main scopes 0 to 16 of 500 refits stop short (by up to 1.7 nats). Re-converging them moves no interior CI endpoint by more than 4e-4 and changes no reported value at three decimals.
- **Conclusions are unchanged.** Main-model c > 1. Survivors' c′ is 0.79 to 0.91, with every CI below 1.

## 2026-10-01. Modules D2 to D4: dependency graph, structure against the generator, continuation (draft; the touch rules wait for the owner)

- **Touches (SPEC 8.3).**
  - A touch is a turn that acts on an artifact. Touches are found in agent_action, in the tool output (events_unified.refs_obs) and in the text parts of agent_messages.
  - There are four modes. Write and read are the usual ones. Observed means the artifact appears only in tool output. Mention means it appears only in text the agent wrote: chat, typed or written content, commit messages, request bodies and the provider response.
  - Only write and read touches make edges. The other two modes enter a sensitivity variant.
  - The rules are listed in avsd.swarmsim.touches.RULES, with counts in outputs/tables/depgraph_rules.csv.
- **Draft rules.** Bash is split into simple commands (heredoc bodies first; quotes may span lines), and the working directory follows cd.
  - Write:
    - redirection and tee targets, and in-place edits;
    - destinations and arguments of file commands;
    - paths and URLs written by inline code;
    - the local repository of git add, commit, pull and similar;
    - the remote of git push, from a directory-to-remote map or from the remote named in the push output;
    - gh and glab write commands, and API calls with a write method;
    - curl and wget with a write method or a body, and download targets;
    - GUI writes on the page in focus: typed text, ctrl+s or ctrl+Enter, and clicks after locating a write button.
  - Read:
    - cd into a project directory, and other paths and URLs in commands;
    - code that opens or fetches a path or URL, and URLs fetched without a body;
    - clone, pull and fetch of a remote, and read-only git and forge commands;
    - scripts that are run, and copy sources;
    - URLs typed into the address bar or opened from bash. These also set the GUI focus.
  - 86% of GUI writes have no focus and are left out.
- **Artifact keys.**
  - Google documents are keyed by id. GitHub and GitLab artifacts are keyed by owner/repo/path, with owner/repo as the container. GitLab project ids are mapped through API output, and Pages URLs are mapped to their repository.
  - Other URLs are keyed without query and fragment. File paths are keyed as paths.
  - Paths, localhost URLs and personal account apps are keyed per agent.
  - Bare domains, search, sign-in, CDN and XML-namespace hosts, and dot directories are not artifacts.
  - A local container is the agent's deepest known repository root, or else the first directory below home or /tmp.
- **Edges.**
  - A -> B when A is the last other session that wrote x before B's first touch of x. Matching works within the container: path-level touches see container-level writes, and container-level touches see any write inside.
  - An edge is labelled write when B also writes x, and read otherwise.
  - Edges whose parent started later are dropped, so each graph is a DAG.
  - Graphs are built per goal. Cross-goal edges are kept only for D4.
- **Structure (SPEC 8.4).**
  - Both sides use the same statistic code, which equals D1's structure_stats on generated DAGs.
  - Parent counts are taken over nodes with a parent. Siblings are parents that share a parent. Out-degree inequality is taken over nodes with a child. Cross-layer edges are edges that span 2 or more layers after relayering.
  - The generator is grow_dag with the blog's parameters and 17 layers, giving 64 DAGs per goal at the goal's session count. Headline values pool all goals.
  - Result: AI Village graphs have more parents per step (2.67 against 1.74), more skipped layers (0.60 against 0.20) and a more even spread of children than the generator. Most statistics sit at quantile 0 or 1.
- **Step cost.** Turns are capped near 40, so cost is also measured in active minutes (gaps of at most G). Relative to each goal's layer-0 sessions, neither measure grows with depth: the slopes are 0.02 and 0.15, against 9 in the blog's model.
- **Continuation (SPEC 8.5).**
  - The rate is taken over consecutive session pairs of one agent in the global graph.
  - The baseline is the hypergeometric chance that the next session's parented containers, drawn at random from those written earlier in the same goal or run day, include the previous session's. Shared containers count when anyone wrote them, local ones only when the agent did. An own-work baseline restricts the pool to the agent's own containers.
  - CIs come from a bootstrap over agents.
  - Result: 0.60 [0.53, 0.67], against 0.06 (goal) and 0.24 (run day).

## 2026-10-01. Module B2: transmission trees between agents (SPEC 6.4)

Code: `src/avsd/lineage/b2_units.py` (units and occurrences), `b2_refs.py` (explicit references), `trees_core.py` (candidates, posterior, forests), `trees_kernel.py` (time term and the module A hook), `trees_stats.py` (H1, H3, attractor), `trees_synth.py` (synthetic validation), `trees_report.py` (tables, F3, F4, QA) and `trees.py` (`avsd lineage trees`). Job: `scripts/lineage_trees.sbatch`. Label sheet: `src/avsd/lineage/prelabel_parents.py` and `scripts/prelabel_parents.sbatch`.

- **Occurrences.** Chat messages of agents and humans (the scaffolding bot is left out), search-history answers that are not "no transcript" placeholders, and memory. A memory occurrence is the first live memory version that holds the unit in that agent's memory (B1 presence spell 0). Summaries are neither occurrences nor parents. schema_notes 4.3 found no evidence that they enter prompts (decision of 2026-09-30). Agents read summary text only through tools, and env_i covers tool output.
- **Typed units.** B1's extractor, salt and unit identity: (type, value), plus B1's displayed context key for time, money, percent and number. Left out: agent names (every agent knows them from its prompt), quantities without a context key, hashed numbers of 9 or more digits, every value on a credential line, anchors that overlap a credential-like span, and dates that name the occurrence's own day plus or minus 1, or its month.
- **4-gram units.** SPEC 6.4.1 asks for 4-grams in fewer than 5 chat messages. A unit is a 4-gram in 2 to 4 chat messages by at least 2 speakers (all humans count as one speaker). Grams with the same message set form one unit. Grams never cross URLs, emails, phone numbers, ids, paths or credential-like spans. A gram made only of stop words, digits and agent-name tokens is dropped. A gram in one chat message is not a unit, so memory and search copies of a single message do not form trees on their own. Deviation from the letter of SPEC 6.4.1, accepted by the coordinator on 2026-10-01 as the default.
- **Selection.** At least one chat occurrence, at least 3 occurrences, at least 2 agents (SPEC 6.4.1) and at most 200 occurrences (`lineage.max_unit_occurrences`). Above 200 a unit is a recurring background anchor (for example a project's own URL), not one spread. 435 typed and 2 gram units are left out by the cap. The cap is a deviation, accepted by the coordinator on 2026-10-01 as the default.
- **env_i.** A turn's observation text is its tool output, its error text and the text, thinking and reasoning parts of the provider response. Tool-call arguments are left out because they hold what the agent typed or sent. Turns that mirror a chat message or an event (`dup_of_uid`) are left out. Main rule (`--env-rule precede`): an observation within L_B counts only when it comes before the agent's first exposure through any other candidate. The env node's time is the earliest such hit. Reason: agents often restate in their own turns what they have just read in chat or in their memory, and a turn mention after an exposure is not an independent observation. The literal SPEC 6.4.2 rule (`any`) is a sensitivity run. This main rule is a deviation from SPEC 6.4.2; the coordinator chose it as the default on 2026-10-01, and the owner may override it.
- **Exposure.** Chat parents lie within L_B = 3 run days. Main rule (decisions "Module B2 exposure"): the reader was in the message's room when it was posted (a 2 s tolerance around room moves) and acted that run day. Sensitivity rules: in that room at some time between the two messages (`ever`), and no room constraint (`all`). Humans see every room. Memory parents: the agent's own memory occurrence while B1 counts the unit as present (first loss under the chosen rule set, plus B1's later presence spells). Search parents: the agent's own answers within L_B. A search answer's parents: chat messages of the village days its query covered, in any room.
- **B1 rule set.** `--rules v1|v2|v3`, default v3, recorded in every output. It changes only the memory presence window (B1's first loss) and the B1 side of H3. The owner's B1 labels will choose. trees_sensitivity.csv reports the other two.
- **Clock.** Positions are run day plus the share of that run day's active time. L_B and every margin are measured on this clock. Intervals are t_active seconds (SPEC 6.1).
- **Time term.** The main time term is module A's kernel (SPEC 6.4.3), through the hook below, for the edges it covers. Module A passed its validation (42 of 43 goal windows; coordinator, 2026-10-01), so the SPEC 11 fallback does not apply to those edges. Every other edge uses a Gaussian KDE of log10 serial intervals per kernel key (channel, child source, same or other agent), fitted on edges whose child has a single candidate (SPEC 6.4.3). A key with fewer than 50 such edges uses its channel's pooled edges, then all edges. K is the density per second, so different keys compare as likelihoods. The KDE alone for every edge is the sensitivity run (`--hawkes off`, trees_sensitivity.csv) and the `_kde_only` rows of the ablation.
- **Module A hook.** `HawkesKernel` reads outputs/tables/hawkes_kernels.parquet in the schema of the module A hand-off (window_kind, window_id, group, date_start, date_end, source_class, w_1m, w_10m, w_1h, L_s, expected_children, identified). A chat-to-chat edge with an agent child in the same run-day realization uses g(tau) = sum_m w_m beta_m exp(-beta_m tau) / (1 - exp(-beta_m L)) when a goal window matches the child's room and PT date together (group = the room's name, date_start <= date <= date_end), the row of the edge's source class (self, other, human) is identified, and 0 < tau <= L. Every other edge uses the KDE: cross-day edges, rooms and dates without a goal window, unidentified rows (all rows of the failed window G40 among them) and tau beyond L. Without the file every edge uses the KDE (`--hawkes auto`, the default; `off` disables the hook; `on` requires the file). The first version looked up the window by date first and room second. Goal windows of different rooms overlap in dates in 2026 (best and rest), so that lookup missed 66 room-dates with 10,310 agent messages (module A's count, confirmed here; 30 of the room-dates in g35-39 best). The lookup now takes room and date together (test `test_hawkes_window_lookup_uses_room_and_date_together`). 42 room-dates with 4,169 of the 173,493 agent messages still have no window, mostly in rooms that module A did not fit (focus, voted-out, showcase-live). The final run read the table that module A rewrote at 11:14 ET on 2026-10-01 after its presence-mask fix (sha256 dfce3c79...). Runs before that used the earlier table and are superseded. trees_time_term.csv counts the chat edges of each goal window and the time term they used, for candidate edges and for MAP edges. The QA report gives the file's time and hash. The ablation and the gamma grid are computed under both time terms (methods ending in _kde_only), and trees_sensitivity.csv has the full run with the hook off.
- **Content term.** S_ij counts the variants that i and j share and the root lacks: quantity values under a context key that the root holds with another value, and rare 4-grams (fewer than 5 chat messages) absent from the root (SPEC 6.4.3). The root is the unit's first occurrence. env_i has S = 0 because the environment is a source, not a copy. Windows: the whole chat message, the line of the first match plus or minus 1 for a search answer, and the lines that carry the unit for memory.
- **Content change rate.** Per generation, the share of a node's non-root values that its parent does not hold. Non-root values are those of SPEC appendix A: a different value under a context key that the root holds. Rare 4-grams change with every rewording, so they enter S but not this rate.
- **gamma.** Grid {0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6}, maximising the mean log posterior of the labelled parent. The provisional value comes from the tier-1 name-reference labels; gamma = 1 (the SPEC default) is a sensitivity run. The final gamma will be chosen on the owner's 50 hand labels with one command, `sbatch scripts/lineage_trees.sbatch trees --gamma hand` (or `avsd lineage trees --gamma hand`), which reads data/labels/parents_review.csv, needs at least 20 labelled rows that match a candidate, and reruns B2 with the chosen gamma (about 1.5 h). `--gamma <number>` fixes gamma. The ablation is cross-fitted over two folds of child messages, and the labelling guide (parents_review_README.md) gives the command.
- **Labels.** `b2_refs` ports the SPEC 2.3-1 verification into the package: name references (@-mentions, addresses, attributions, extended references; aliases from B1) to the named agent's latest message in the room within 50 messages, and quotes that match exactly one earlier message of another speaker within 50 messages. Tier 1: single-target reciprocal name references and unique quotes from 2026-02-25. Tier 2: other single-target name references. Earlier quotes are left out. A label is usable when the labelled message is a candidate parent for a unit both messages carry. data/labels/parents.csv holds them (SPEC appendix C).
- **Trees.** The MAP parent maximises the posterior (ties go to the latest parent). A child of env_i starts a new subtree at generation 0 (SPEC 6.4.3). 200 posterior draws pick each parent independently (SPEC 6.4.4).
- **H1 implementation.** H1 compares the forward serial intervals of transmissions (carrier to acquisition, below) across agent-level generations. Forward intervals: an edge enters only if its parent lies more than L_B before the end of the data. Candidates lie within L_B, so every interval of such an edge could be observed. Strata are kernel keys (channel, child source, same or other agent). A pooled channel such as chat to memory mixes two keys whose share changes with the generation, and on synthetic null trees the pooled test rejected in 94% of replicates on the true trees. Anderson-Darling k-sample statistic (A2_kN) on log intervals per stratum, over generations with at least 30 edges, with p from permuting generation labels within the stratum (499 permutations for the MAP forest, 99 per posterior draw, 199 for sensitivity runs and the occurrence-level reference) and a z-score against the permutation null. T_k is the time from the agent-level tree root to the acquisition at generation k, for trees whose root lies more than 30 run days before the end; weighted least squares on (1, k) and (1, k, k^2). CIs: Poisson cluster bootstrap by agent-level tree root, 500 replicates.
- **Determined paths (H1 headline).** A transmission is on a determined path when every acquisition on its agent-level path from the root had a single candidate parent (a root without candidates, or an env_i child whose only candidate was env_i). Its parent and agent-level generation then do not depend on the parent posterior. This test is the H1 headline (coordinator, 2026-10-01), because the synthetic validation (SPEC 6.4.5) shows that the MAP-forest test does not keep its level; the MAP-forest result is reported next to its synthetic type I error. This follows the SPEC 11 fallback (test H1 where the parent is known), with the exposure structure in place of explicit references.
- **Agent-level trees (main view).** The main view is transmission between agents (coordinator, 2026-10-01). Each actor's first occurrence of a unit is its acquisition (all humans count as one actor). The MAP parent of an acquisition, the carrier, is an occurrence of another actor, and that actor's acquisition is the agent-level parent, one generation up. The carrier can be any occurrence of that actor, so transmission through a later restatement is kept. Later occurrences of an actor are re-mentions: they keep the actor's generation whatever their own MAP parent, and they are reported separately as restatement depth (re-mentions per acquisition, and the kind of their MAP parent). The occurrence-level forest, where every MAP edge adds a generation, is reported for reference only. An earlier sensitivity view dropped every occurrence but each agent's first and inferred the parents again; it lost transmission through later restatements and is no longer run.
- **H3.** c is the share of quantity contexts carried from parent to child (same context key in both windows) whose value changes on the edge, by channel. Inheritance: among the children of a changed node that carry the same context, the share that holds the new value. B1's counterpart is the share of quantity facts whose context stays at a consolidation and whose value changes, from memory_by_anchor{_v2,_v3}.csv (B1 reports no clustered CI for this ratio, so the Wilson interval is given and flagged).
- **Other per-generation measures.** They use acquisitions and agent-level generations. Offspring of an acquisition are the acquisitions it carried through any occurrence of its actor. Expected offspring scales the generation-0 mean by the share of that run day's active agents that do not hold the unit yet (finite population, SPEC 6.2). The independent share by generation uses the agent-level generation an acquisition would have if env_i were not allowed, because env_i children are generation 0 by definition. Attractor test: the 41-token window around the anchor, its type-token ratio and its token Jaccard index with the unit's most common window (an exact window seen twice, else the medoid), with the within-unit slope on agent-level generation.
- **Synthetic validation.** Each replicate simulates 50,000 units from the real run: start times of real units, the agents active that run day, Poisson offspring with the MAP means by generation, the MAP channel mix, the real KDEs as intervals, the real independent share (agents that acquire independently did not see the earlier chat), spurious observations at the real rate, and value changes with the real probability. The same inference runs on it (KDE refitted, the real gamma). 100 null replicates (intervals independent of generation) give the type I error of H1 on the true trees, on the MAP trees and on the determined paths; 25 replicates in which the interval into each new agent's acquisition is scaled by 1.5^(gA-1) at agent-level generation gA give power. Rates are computed for agent-level generations (main) and occurrence-level generations (reference).
- **Domains in outputs.** outputs/tables/trees_units.parquet shows a URL unit by its registrable domain (example.com, example.co.uk), and only when at least 3 units share that domain and it holds no token of a human speaker's name. Other URL units show "other". Hosting platforms (substack.com, netlify.app, workers.dev and others) put account names in subdomains, and B1's masking covers only github.io and gitlab.io owners. Personal sites sit in the long tail: 451 of the 626 registrable domains occur in one unit. The rule keeps a domain for 8,652 of the 9,251 URL units. Keyed ids identify units.
- **Reading (full data; rules v3, env rule precede, main exposure, module A kernel as the time term, gamma 0 provisional; job 599299; outputs/qa/lineage_trees.md).**
  - Scale. 387,996 units (165,522 typed, 222,474 4-gram) with 3,144,784 occurrences and 2,117,354 acquisitions (an actor's first occurrence of a unit). 813,774 acquisitions were transmitted from another actor, 158,569 were independent (env_i) and 1,145,011 had no candidate parent. 280,670 units have at least one transmission (SPEC 6.4.6 asks for 100). The deepest agent-level tree has 7 generations; counting every MAP edge as a generation gives 164.
  - Time term. The module A kernel set the time term of 1,928,522 of the 3,444,217 candidate chat edges (56.0%; 92.9% of the same-day ones) and of 365,756 of the 465,125 chat edges on the MAP forest (78.6%). The KDE served 1,368,346 cross-day candidate edges, 18,490 in rooms or on dates without a goal window, 43,296 of unidentified rows (28,410 in G40, 14,233 in g29) and 85,563 beyond L. Counts by window: trees_time_term.csv.
  - Time term against the labels. With the module A kernel the labelled parents fit worse than with the KDE alone. On the 10,871 tier-1 name cases (5,848 child messages) the mean log posterior is -0.775 against -0.338 and the accuracy 0.861 [0.852, 0.870] against 0.883 [0.876, 0.891]. Tier-2 names: 0.810 [0.801, 0.818] against 0.822 [0.814, 0.830] (14,089 cases). Tier-1 quotes: 0.806 [0.793, 0.821] against 0.838 [0.825, 0.851] (6,806 cases). Cause unidentified.
  - gamma. Both time terms give gamma = 0 on the tier-1 name labels. Content alone reaches 0.712 [0.702, 0.723] and a uniform choice 0.582 [0.574, 0.591]. Content counted only between different agents gives 0.875 [0.867, 0.883]. Name labels always point to another agent's message, so they cannot reward the content term where it prefers the child's own earlier message. The baseline "latest message of another agent" reaches 0.950 [0.944, 0.955], but it nearly restates how name labels are built.
  - H1 headline (determined paths). Chat to chat between agents: 84,857 transmissions in generations 1 and 2, A2 = 145.3, z = 214 against the permutation null, p = 0.002 (499 permutations). The test's synthetic type I error is 7% [3.4%, 13.8%] (100 replicates) and its power 48% [30%, 67%] (25 replicates with intervals growing 1.5-fold per generation). The interval is longer in generation 2: median 2.17 active hours [1.04, 3.82] (407 transmissions) against 0.064 [0.063, 0.065] (84,450). Chat into another agent's memory also rejects (351,863 transmissions, generations 1 to 3, z = 584, p = 0.002; medians 0.142, 0.263 and 0.326 h), but its synthetic type I error, 10% [5.5%, 17.4%], is above the nominal level (power 100% [87%, 100%]). Chat to a search answer rejects as well (26,316 transmissions, p = 0.002); the synthetic model does not cover it. In all 200 posterior draws the determined-path tests of these three strata give p below 0.05.
  - H1 on the MAP forest, for completeness. Chat to chat between agents rejects (p = 0.002, generations 1 to 4) with a synthetic type I error of 64% [54%, 73%]; chat into another agent's memory rejects (p = 0.002, generations 1 to 5) with 26% [18%, 35%]; chat to human does not (p = 0.83, 451 transmissions). These rejections do not show that intervals change with the generation. On the MAP forest the chat-to-chat medians fall with the generation (0.061, 0.038, 0.026 and 0.022 h for generations 1 to 4), the opposite direction from the determined paths.
  - Occurrence-level reference. With every MAP edge counted as a generation, the MAP-forest test rejects in every stratum, with synthetic type I errors up to 100% [96%, 100%]. On determined paths chat to chat between agents keeps its level (6% [2.8%, 12.5%]) and rejects (p = 0.005, 199 permutations).
  - T_k. On the MAP forest the mean time from the root to the acquisition at generation k rises from 45.0 h [44.3, 45.7] at k = 1 (513,119 acquisitions) to 51.6 h [50.2, 53.1], 74.4 h [68.8, 79.6], 127 h [107, 148] and 185 h [116, 262] at k = 2 to 5 (230 acquisitions at k = 5). The linear slope is 11.7 h per generation [9.9, 13.4], and the k^2 term is positive (9.5 [6.8, 12.4]), so T_k grows faster than linearly. The variance rises by 7,822 h^2 per generation [6,558, 8,867], also with a positive k^2 term (5,401 [3,641, 7,217]). Medians are far smaller (0.28 h at k = 1). Consecutive transmission intervals along a path correlate weakly (Spearman 0.177 [0.171, 0.183], 168,478 pairs). The MAP-forest caveat above applies to T_k.
  - Offspring. An acquisition at generation 0 carries 0.485 [0.483, 0.487] acquisitions (1,303,580 acquisitions). At generation 1 it carries 0.245 [0.243, 0.248] against 0.459 expected from the shrinking pool of agents without the unit, and at generation 2 0.126 [0.123, 0.129] against 0.410. Transmission falls faster than the finite population explains. Cause unidentified.
  - Channels. Of the transmissions into generation 1, 76.9% go from chat into another agent's memory, 16.3% from chat to chat and 6.8% from chat into a search answer. Deeper generations shift further to memory (84.8% at generation 2).
  - Independent acquisition. 11.6% [11.6%, 11.7%] of the acquisitions that would be roots without env_i are independent, 1.08% [1.05%, 1.11%] at generation 1 and about 0.6% later. 16.3% of the acquisitions with a parent are independent (19.6% under the literal SPEC rule).
  - Restatement depth. 1,027,430 of the 3,144,784 occurrences (32.7%) are re-mentions by an actor that already holds the unit. Their MAP parent is the actor's own earlier occurrence in 54.2% of cases, another actor's occurrence in 26.4%, env_i in 5.2% and none in 14.2%. 73.8% of the acquisitions are never re-mentioned, 18.2% once, 4.5% twice and 0.46% ten or more times (mean 0.49, maximum 146).
  - H3. Agent-to-agent retelling changes a carried quantity value with c = 0.302 [0.300, 0.304] per edge (882,844 contexts on 931,616 edges): 0.424 [0.419, 0.428] from chat to chat and 0.253 [0.251, 0.254] from chat into another agent's memory. B1's memory consolidation (rules v3) changes 0.033 [0.033, 0.033] of the quantity facts whose context stays (7,386,947 contexts, Wilson interval). Children of a changed node keep the new value in 36.0% of the contexts they carry and go back to the parent's value in 48.5%. The two rates are measured on different units (a context in a message window, a fact in a memory version).
  - Attractor. Within units, the similarity to the most common window rises by 0.052 per agent-level generation [0.051, 0.053] and the type-token ratio rises by 0.0055 [0.0053, 0.0057] (2,529,328 occurrences in 280,670 units). The wording moves toward the common form, and the windows do not become more repetitive.
  - Sensitivity. Every variant keeps 7 generations at most, between 781,918 and 830,358 transmissions, and p = 0.005 (199 permutations) for the determined-path chat-to-chat test and the MAP-forest combined test: the KDE alone, gamma = 1, content between agents only, the literal env_i rule, exposure "ever" and "all", and B1 rule sets v1 and v2. The B1 rule set changes no agent-level number, because memory presence only affects re-mentions.
  - Label sheet. data/labels/parents_review.csv was rebuilt from this MAP forest (job 599300): 50 items, Qwen3-14B agreement with the MAP parent 21 of 50, 33 rows of priority 1.

## 2026-10-01. B2 time term to be chosen on the owner's labels

- In the final B2 run the KDE fits the tier-1 labelled parents better than the module A kernel: accuracy 0.883 [0.876, 0.891] against 0.861 [0.852, 0.870], and mean log P −0.338 against −0.775 (10,871 cases from 5,848 messages). The same holds on tier-2 names and tier-1 quotes. Cause unidentified. The H1 outcome is the same under both time terms.
- The explicit-reference labels are name references and quotes, not a random sample of occurrences. The main time term is therefore chosen together with gamma, by parent accuracy on the owner's 50 hand labels.
- Until those labels exist, the module A kernel stays the main term (SPEC 6.4.3) and the KDE is reported as the sensitivity check.

## 2026-10-01. B1 pre-label re-check: results and second review design (replaces the review design in "B1 label validation: local pre-labelling")

- **Runs.**
  - Qwen3.5-122B-A10B-FP8 (revision a099dee, thinking; temperature 0.6, top_p 0.95, top_k 20) ran on 4 L40 (FP8 W8A8, tensor parallel 4, text only).
  - gpt-oss-120b (revision b5c939d, reasoning effort high; temperature 1) ran on 2 A40 (MXFP4, tensor parallel 2).
  - Both used vLLM 0.19.1 in eager mode, with seed 20261003. CUDA-graph capture ran out of memory, because vLLM 0.19 sizes the KV cache without the graph memory.
  - The JSON schema is enforced after the reasoning, and every answer is validated. An invalid answer is retried once with 32,768 instead of 8,192 tokens.
  - Both models got the same 500 cached requests as Qwen3-14B. Valid answers: 500/500 for both (Qwen3.5: 14 after the retry).
  - Weights were downloaded anonymously from the official repositories and deleted after the runs (2026-10-01 14:36 ET).
- **Agreement.**
  - The strong models agree on 94.2% of units (kappa 0.92 [0.89, 0.95]). Their main disagreement is modified versus dropped.
  - Kappa between Qwen3-14B and the two strong models: 0.74 and 0.78.
  - Kappa with rule sets v1, v2 and v3: Qwen3.5 0.63, 0.61, 0.81; gpt-oss 0.65, 0.59, 0.82; Qwen3-14B 0.52, 0.54, 0.75.
- **Overturns.** Where the strong models agree (471 units), they change Qwen3-14B's label on 73 (15.5%, 95% CI 12.5% to 18.3%): dropped to modified 32, new to restored 20, modified to kept or dropped 11. Qwen3-14B's modified labels are the least stable (13 of 23 changed).
- **Third judge.** The orchestrating agent judged 50 disagreement units blind: 25 of the 27 where the strong models disagree, and 25 of the 69 where they agree against Qwen3-14B. Credential-like units were excluded.
  - Accuracy on disagreements is low for every labeller: Qwen3-14B 0.42 [0.30, 0.53], Qwen3.5 0.41 [0.30, 0.52], gpt-oss 0.37 [0.25, 0.48], and rule sets v1 0.27, v2 0.38, v3 0.26.
  - The consensus was right on 6 of 10 sampled changes from dropped to modified. It was right on only 2 of 10 changes from new to restored, where the earlier excerpt usually showed an unrelated use of the same value.
  - In 17 of the 50 units, the value is present in both versions in a format or wording the rules did not match.
- **Independence.** The LLM prompts include the rule-based occurrence counts, and the LLMs follow them. So agreement between LLMs and rules is not independent evidence for the rules. Format variants that the rules miss would count as losses and bias B1's hazards upward. The owner's labels measure how much.
- **Use of LLM labels.** No LLM label is reliable where the rules disagree, so LLM labels are a review aid only. The sheet does not show the rule or Qwen3-14B labels, because the owner's labels are what evaluates them. The labelling guide warns about unmarked format variants and about unrelated earlier matches.
- **Review design.**
  - Priority 1, inclusion probability 1:
    - stratum A, where the strong models disagree (29 units);
    - stratum B, where they agree and at least one rule version differs (218 units).
  - Every unit on which the rule versions disagree is in A or B, so comparisons between rule sets carry no sampling error from the design.
  - Priority 2: a random sample of 30 of the 253 units on which all five labellers agree, stratified by label (inclusion probability about 0.12).
  - That makes 277 rows to label. Metrics are weighted by 1 / inclusion probability, and they also score Qwen3-14B and both strong models.
- **Caveat.** The prepare stage retrieves an EARLIER excerpt only for units that v1 labels restored, so the models can confirm "restored" only there.

## 2026-10-01. B2 parent sheet re-checked with the same two models

- Both models answered the 50 cached parent requests with the B1 settings. A valid answer names a candidate, ENV or NONE. Valid answers: gpt-oss 50/50, Qwen3.5 49/50 (one item reasoned past 32,768 tokens twice).
- Agreement with the MAP parent: Qwen3-14B 21/50, Qwen3.5 27/49, gpt-oss 30/50. The strong models agree on 37 of 49 items, and their shared choice is the MAP parent on 23. On the 6 items whose MAP parent is ENV, the 3 shared choices are all non-ENV candidates.
- The sheet adds a suggested parent and both models' choices. Rows where the models disagree with each other or with the MAP parent are priority 1 (27 rows). Existing columns are unchanged, so `--gamma hand` and the metrics command still work. The metrics also score both models and the suggestion. The first sheet is kept as parents_review_qwen14b.csv.
- Caveat: candidates are listed by descending posterior with ENV last, so candidate 1 is usually the MAP parent. Part of the agreement with the MAP parent comes from position.

## 2026-10-01. Blind labelling (owner's choice)

- The owner chose to label blind and to label all 277 B1 rows (priorities 1 and 2).
- `scripts/blind_labels.py make` writes the blind copies `data/labels/memory_pairs_blind.csv` (277 rows) and `parents_blind.csv` (50 rows).
  - They drop every model label, posterior, MAP parent and design column.
  - The B2 rows and each row's candidates are shuffled (seed 20261003). Before the shuffle, candidate 1 was the MAP parent in 44 of 50 rows. The mapping back is kept in `parents_blind_map.json`.
- The owner's copies, with a Chinese guide, are in `~/Downloads/avsd_labels/` on the Mac (mode 600). The earlier 250-row sheet is moved to `旧版_不用标/`.
- After labelling:
  1. Copy the owner's two files to `data/labels/`.
  2. Run `scripts/blind_labels.py merge`.
  3. Run `python -m avsd.lineage.prelabel metrics` and `python -m avsd.lineage.prelabel_parents metrics`.
  4. Run `sbatch scripts/lineage_trees.sbatch trees --gamma hand`. The B2 time term is chosen on the same labels.

## 2026-10-01. Gemini free tier as an extra rater for hard label cases (owner's decision)

- **What the owner allowed.** The owner allowed their Gemini API key for the hard label cases: B1 strata A and B, the B2 priority-1 rows, and the remaining rows of both blind sheets if the quota allows. The key project has no billing, so this is the free tier.
- **Risk.** Under Google's terms for unpaid use, submitted content may be used to improve Google's models and may be read by human reviewers. SPEC 0.2 forbids training AI systems on the data without AI Digest's written permission.
- **Conditions.**
  - The owner accepted the risk.
  - Before sending, excerpts are redacted: human names, emails and phone numbers become consistent placeholders, and credentials stay masked.
  - Prompts carry no rule-based hints.
  - Each redacted prompt and its output are cached under `data/interim/llm_cache/gemini_hard/`.
  - The key stays in `~/.config/avsd/gemini_key` (mode 600). It goes only to Google's endpoint, in a header, and is never logged.
- **Role of Gemini.** It is an extra rater only. The owner's blind labels remain the reference and are never shown Gemini's output.
- **GUI-write gap (D2).** The free tier is far too slow for 132,756 writes. The cause of the gap is investigated from the text data first.

## 2026-10-01. D2 GUI focus gap: diagnosis and touch rules v2

- **What the gap is.** Under rules v1, 86% of GUI writes had no focus (132,756 of 153,721).
  - 63% of those are not writes to a persistent document:
    - game moves and other short inputs (32%);
    - shell commands typed into GUI terminal windows (22%). Agents rarely used the bash tool before October 2025, and on 2026-01-12 the tool description started telling them that no GUI terminal is needed;
    - clicks on text boxes, links or menus (3.5%);
    - console or terminal-program input (2.4%);
    - missed navigation (1.6%);
    - searches (1.2%).
  - The other 37% are real writes (messages and posts, form fields, buttons, document text, code) whose page the text never names. 92% of the unattributed writes happen in sessions that never type a URL, and the scaffold logs no page, URL or window title for GUI actions.
- **Focus heuristics fail validation.** Tested on writes with a known focus (focus hidden):
  - carry-over from the previous session is right for 15% (19% within 5 minutes);
  - an artifact the agent named is right for 30% to 49%, at 4% to 12% coverage.
  None of them is used.
- **Rules v2** (`avsd swarmsim calibrate --rules v2`, outputs suffixed `_v2`):
  - Typed text is classified, with spot-check precision of 0.80 to 1.00 per class.
  - Shell commands are parsed as bash.
  - Game moves, short inputs, sign-in values, searches and missed navigations are not GUI writes.
  - An address-bar search clears the focus.
  - A click is a write only on a named button (precision 0.85; excluded clicks 0.95).
  - v1 stays the D2 default and is unchanged.
- **Effect of v2.** GUI writes drop from 153,721 to 66,115, of which 79% still have no focus. Sessions touching an artifact rise from 54,356 to 56,038 and edges from 128,043 to 130,508. D3 statistics and D4 rates move by at most 0.005, so no D2 to D4 conclusion depends on the GUI rules.
- **Recommendation.** Make v2 the main D2 version once the owner confirms the rules. Recovering the remaining GUI targets needs the screenshots (module E: OCR of the address bar or window title).
- **Credentials.** Some plain passwords typed into GUI fields survived the dataset's scrubbing. Their locations, without values, are exported to `data/interim/credential_scan/gui_signin_values.csv` and compared with the report sent to AI Digest.

## 2026-10-01. Typed sign-in values in GUI actions (credential follow-up)

- `scripts/depgraph_gui_signin.py` exports the locations of sign-in values typed into GUI fields to `data/interim/credential_scan/gui_signin_values.csv` (mode 600, 1,807 rows). The file holds no values. The field kind comes from the located-element description just before the typing.
- **Counts.** There are 201 password-like rows (127 distinct values), using the earlier scanner's non-weak cutoff. The dataset's own redaction had already scrubbed 842 sign-in values.
- **New relative to the report sent to AI Digest on 2026-10-01.** That means not on a reported turn and not one of the reported values.
  - 88 rows (63 distinct values) in password fields or typed after a username and Tab, in 66 sessions of 12 agents. These are likely real passwords.
  - 88 rows (59 distinct values) in username or email fields. These are uncertain.
- No credential is used. Whether to send a follow-up to AI Digest is the owner's call.
- **Disclosure.** During a manual spot check, the D2 agent's session output showed about 4 short password-like strings. They are in that agent's local transcript only, and nothing was written to project files or outputs. The scrub helper now masks short tokens too.

## 2026-10-01. Gemini as an extra rater of the hard B1 and B2 cases (owner's free-tier key)

- **Setup.**
  - The owner accepted the data terms of the Gemini API free tier for this use.
  - The key (~/.config/avsd/gemini_key) is read at run time and sent only to generativelanguage.googleapis.com, in the x-goog-api-key header. Redirects are refused, and the key is never printed, logged or cached.
  - The project is on the free tier: the 429 metric is generate_content_free_tier_requests, and gemini-3.5-flash allows 20 requests a day.
  - gemini-3.1-pro-preview labelled all 337 rows without reaching a daily limit: the 277 B1 rows of the blind sheet, 10 more B1 units from the third-judge sample, and the 50 B2 items. 2.5 Pro and 2.5 Flash were fallbacks only. The model of every row is recorded.
  - Settings: temperature 1.0, seed 20261003, default thinking, JSON schema enforced. Every answer validated on the first attempt.
- **Prompts.**
  - b1-gemini-v1 has no rule-based occurrence counts and no ⟦ ⟧ ⟨ ⟩ marks. It gives the fact and the owner's label guide, with two warnings: format or wording variants are the same fact, and an unrelated earlier use of the value means new, not restored.
  - b2-gemini-v1 shows the blind sheet's shuffled candidates, without posteriors or the MAP parent. It keeps ⟦ ⟧, because for low-frequency phrases that is the only pointer to the information.
  - Before sending, human names (spaCy PERSON outside the agent roster), emails and phone numbers become per-unit placeholders, and the unit's own value is pseudonymised the same way. 437 names, 47 emails and 2 phone numbers were replaced. spaCy misses some names (fictional characters, handles), which this rule does not cover.
- **Results (aggregates; held back from the owner until the blind labels are done).**
  - On the 277 B1 rows, Gemini agrees with the strong-model consensus on 71% (kappa 0.58), and with rule sets v1, v2 and v3 on 27%, 61% and 55%.
  - On the 50 blind-judged disagreement units, it matches the third judge on 85% [77%, 94%]. The local LLMs reach 37% to 42% and the rule sets 26% to 38%.
  - This is not a like-for-like model comparison. Gemini's prompt carries the third judge's rules, while the local models used the earlier prompt with rule-based counts.
  - B2: Gemini's parent equals the MAP parent on 26 of 50 items, and the strong models' shared choice on 26 of 37.
- **Use.**
  - Gemini output is never shown to the owner. Its labels are in private files under data/labels/ (memory_pairs_gemini.csv, parents_gemini.csv), and the comparison stays in data/interim/.
  - Once the blind labels exist, compute_label_metrics and the prelabel_parents metrics score Gemini against them, on the rows it labelled.

## 2026-10-01. D2 touch rules v2 confirmed as the main version (owner)

- The owner confirmed rules v2 as the main D2 version. This is the confirmation SPEC 8.3 asks for. v1 stays as a sensitivity version.
- Before anything else, D3 and D4 are recomputed on the subsets where the GUI gap is small: goals with few unattributed GUI writes, the period from 2025-10 on, and all goals without the GUI-heavy early ones. If the conclusions hold there, the gap goes into the write-up as a limitation: GUI-based collaboration before 2025-10 is under-represented in the graphs. Screenshot recovery (module E) is not pursued for now.

## 2026-10-01. D2 to D4: rules v2 as main, and robustness to the GUI focus gap

- **Rules.** The owner confirmed touch rules v2 (SPEC 8.3).
  - They are the main version: `avsd swarmsim calibrate` uses them, set as `swarmsim_calibrate.rules: v2` in configs/default.yaml, and writes the unsuffixed outputs.
  - Rules v1, the first draft, are kept as a sensitivity version (`--rules v1`, outputs with the suffix `_v1`).
- **Gap measure.** Per goal, the gap is unattributed GUI writes / (unattributed GUI writes + turns with a write touch on an artifact). The median is 0.31: 0.85 for goals before 2025-10 and 0.13 for goals from 2025-10.
- **Subsets.** D3 (with generator quantiles), the step-cost slopes and D4 were recomputed on five subsets of goals:
  - gap < 20% (24 goals);
  - gap < 10% (13 goals);
  - touch share ≥ 80% (17 goals);
  - from 2025-10 (36 goals);
  - all goals except the early goals with a gap of at least 80% (40 goals).
- **Result.** All five headline conclusions hold on every subset: 30 of 30 checks under v2, and 30 of 30 under v1.
  - The effects are slightly larger where the gap is smallest. At gap < 10%: mean parents 2.88 against 1.74, layer-skipping edges 0.63 against 0.20, continuation 0.667 [0.592, 0.741].
  - So the unseen GUI writes weaken these patterns rather than create them.
- **No claim on sibling merges.** They are not robust.
- **Limitation for the write-up.** GUI-based collaboration before 2025-10 is under-represented in the dependency graphs.
- **Details.** outputs/tables/depgraph_robustness.csv, and section 8b of outputs/qa/swarmsim_d2_d4.md.

## 2026-10-02. Offline labelling page for the blind sheets

- `scripts/blind_labeler_html.py <dir> <out.html>` builds one self-contained page from the two blind sheets. Rows are embedded as JSON. The page loads nothing from the network, keeps labels in the browser's localStorage, and exports `memory_pairs_labeled.csv` and `parents_labeled.csv` with exactly the blind sheets' columns. It can import an exported file to resume in another browser.
- The owner's copy is `~/Downloads/avsd_labels/标注工具.html` (mode 600). It contains personal data, so it must never be published as an artifact or uploaded.
- When the exports come back, copy them to `data/labels/memory_pairs_blind.csv` and `parents_blind.csv` on GRASP, then run `scripts/blind_labels.py merge`.

## 2026-10-02. Intervals for pooled module A shares in the write-up

- Pooled event-weighted shares over the 43 goal windows use the estimate ± 1.96 bootstrap SD. The replicates of each window are combined by replicate index.
- Percentile intervals of the pooled replicates exclude the estimates for self, baseline, other agents and human. The replicate refits are biased: they average 43.1% for self against the estimate of 47.5%. This is the same estimator bias that the recovery check measures (self about 0.05 too low). The write-up states the bias next to the intervals.
- Per-window intervals stay percentile intervals.
- The D3 values of the observed graphs carry goal-bootstrap intervals, and they still exclude the generator ranges.
- All write-up CIs are in `outputs/tables/writeup_cis.csv` (`scripts/writeup_cis.py`, seed 20261003).

## 2026-10-03. One labelling dashboard for everything the owner checks

- The offline page (`~/Downloads/avsd_labels/标注工具.html`, built by `scripts/blind_labeler_html.py`) now opens on an overview of every owner task with its progress:
  - the B1 blind sheet (277 units);
  - the B2 blind sheet (50 occurrences);
  - the stage-0 time-zone spot check, the 20 live UI links of outputs/qa/build_events.md section 12, pending since 2026-09-30.
- **Spot-check answers.** For each link the owner answers one of: matches, fixed offset (with the offset in the note), mismatch, or cannot tell. The export adds `timezone_check.csv`.
- **Storage.** The file name and storage key are unchanged, so labels saved by the earlier version carry over in the same browser.
- **Not hosted.** The page is not published, because the excerpts carry personal data.
- 2026-10-03 addition: the B1 view can open the full PREV and NEXT texts of each pair (key F; 99 pairs, 5.8 M characters, credentials masked as in the excerpts), so the owner can search for format variants that the excerpts do not show. `scripts/blind_fulltext.py` writes them to `data/labels/memory_pairs_fulltext.json`, and the page embeds them. This raises the page to 6.6 MB. It is still local only.

## 2026-10-03. Labels from Claude, audited by the owner (owner's decision)

- **Design.** Claude blind-labelled all 277 B1 units and all 50 B2 occurrences. Six parallel agents did the work. They read only the blind sheets, the full texts and the guide. They did not see the rule labels, other models' labels or the audit sample.
- **Owner audit.** The owner labelled a stratified random audit sample (seed 20261003, `data/labels/audit_sample.json`):
  - B1: 15 of stratum A, 30 of B and 15 of C, 60 units;
  - B2: 8 priority-1 and 7 priority-2 rows, 15 occurrences;
  - plus 11 earlier B1 labels, which are not random.
- **Agreement on the audit sample.**
  - B1: 75.3% design-weighted (73.3% unweighted, n = 60). By stratum: A 53% (15), B 77% (30), C 87% (15). On the 11 extra rows: 91%.
  - Claude uses modified more often than the owner, so the binary kept-versus-lost agreement is higher, at 80%.
  - B2: 9 of 15.
  - Claude flagged 104 of 277 B1 units as bad_unit (ID-like numbers, date parts, wrong entity types). The owner flagged none, so no human has validated that flag.
- **How the metrics are computed.** The main rule-set metrics are scored against the owner's labels on the 60 audit units, weighted by review inclusion × audit inclusion. Metrics against Claude's labels on all 277 units are the sensitivity check. B2's gamma and time term are chosen on a composite set: the owner's label where it exists, Claude's elsewhere.
- **Time-zone spot check (stage 0, SPEC 4.3).** Claude checked all 20 live UI links in a browser on 2026-10-03, and all 20 match. The page date equals our Pacific date in every case. At each linked moment the named agent does the named action (17 computer turns, 1 Claude Code turn, 1 pause, 1 chat message). The strongest checks:
  - an agent writes "about 4:15 PM PT" at our 16:16 PT;
  - a pause shown as ending at 14:20:18 EDT (11:20:18 PT) follows our 11:19:18 PT pause event.
  Results are in `outputs/tables/timezone_spotcheck.csv`.
- **Masking of the full texts.** One annotator reported a login and password in plain text in one pair's full text. `scripts/blind_fulltext.py` now masks with:
  - B1's heading rule;
  - a stricter pass on credential lines;
  - session IDs;
  - every hit of `scripts/scan_credentials.py`.
  The scanner now finds no unmasked hit in the 99 pairs (1,813 masks). The earlier page had already been sent to the owner. That credential is part of the dataset and is not used.

## 2026-10-03. B1 label validation: results and choice of rule set

- **Data.** The reference is the owner's blind labels on the 60-unit audit sample (A 15, B 30, C 15). Each unit is weighted by 1 / (review inclusion × audit inclusion), so the estimates stand for all 500 units. Intervals come from 2,000 bootstrap replicates resampled within the audit strata, and rule-set differences are paired on the same replicates. The 11 non-random owner rows enter only a sensitivity check.
- **Measure.** The measure is loss detection: dropped or modified (the B1 hazard event) against kept. The owner labelled 16 of the 60 audit units as lost (13 dropped, 3 modified) and none as new or restored.
- **Results (loss-detection F1, 95% CI).**
  - Rule sets: v1 0.67 [0.45, 0.82], v2 0.78 [0.55, 0.93], v3 0.73 [0.52, 0.88]. The intervals overlap.
  - Paired differences: v2 − v1 +0.10 [+0.001, +0.23]; v3 − v1 +0.06 [+0.01, +0.13]; v3 − v2 −0.04 [−0.14, +0.05].
  - v2's gain is precision. Of the 44 audit units the owner labelled kept, v1 calls 18 lost, v3 14 and v2 7. v2 misses 2 of the 16 losses; v1 and v3 miss 1 each.
  - v2 loss precision 0.74 [0.49, 0.94], recall 0.82 [0.55, 1.00]. Five-class accuracy: v1 0.27 [0.14, 0.41], v2 0.65 [0.51, 0.79], v3 0.48 [0.33, 0.62].
  - LLM raters: Qwen3-14B 0.69, Qwen3.5-122B 0.70, gpt-oss-120b 0.71, Gemini 3.1 Pro 0.63, Claude 0.80 [0.57, 0.93].
  - Sensitivity: on all 71 owner rows, v1 0.65, v2 0.74 and v3 0.70. Against Claude's labels on the 277 blind rows, v1 0.60, v2 0.68 and v3 0.66 (v3 − v2 −0.02 [−0.07, +0.03]).
- **Decision.** Rule set v2 is the main B1 rule set, and v1 and v3 are reported as sensitivity variants. The paired difference supports v2 over v1, but only just, and does not separate v2 from v3.
  - The B1 tables keep their file names: unsuffixed for v1, `_v2` and `_v3`. The write-up, the report and module C read the `_v2` files as the main version.
  - Module C now reads `memory_hazard_monthly_v2.parquet`. Its rerun changes only the external series set, which is still not aligned with the CHANGELOG (133 of 148 change points near an entry at w = 3, null-1 p = 0.81).
- **Claude against the owner (60 audit units).**
  - Same label: 73.3% unweighted, 75.3% [62%, 87%] weighted to the 277 blind rows, and 80.5% [69%, 91%] weighted to all 500 units.
  - By stratum: A 8/15, B 23/30, C 13/15.
  - Kept versus lost: 80% unweighted and 87% [77%, 95%] weighted to all units.
  - Claude labels 11 audit units modified where the owner has 3.
  - Claude's bad_unit flag (104 of 277) has not been validated by a human.
- **Gemini.** On the owner's labels its loss F1 is 0.63 [0.38, 0.81] and its accuracy 0.50, well below its 85% agreement with the third judge.

## 2026-10-03. B1: paired test of the post-switch rise

- **Why.** The write-up says that after the switch to continuous computer use, a fact unit is more likely to be lost at its second consolidation than at its first. B1 reports h1 and h2 of the post-switch regime with separate intervals, and these overlap.
- **Method.** `scripts/b1_post_switch_rise.py` rebuilds the post-switch risk counts of trials 1 and 2 from the fact spells and the live memory rows (standard agents, first spells). It computes h2 − h1 on 2,000 agent-bootstrap replicates, with both hazards on the same replicates.
  - The rebuilt counts fall short of the B1 tables by at most 44 of about 3.1 million trials (cause unidentified).
  - The hazards agree with the B1 tables to three decimals.
- **Result** (`outputs/tables/memory_post_switch_rise.csv`, h2 − h1 in percentage points):
  - v1 +6.1 [−1.7, +14.8];
  - v2 +7.3 [+1.5, +13.0];
  - v3 +5.1 [−2.3, +13.1].
  Among agents with at least 30 post-switch trials at both g = 1 and g = 2, the hazard rises for 18 of 34 under v1, 23 of 34 under v2 and 18 of 34 under v3.
- **Reading.** The rise is established only under the main rule set, v2. The write-up now lists five conclusions that hold under all three rule sets and reports the rise separately.
- **Report.** The B1 tab of the report now shows the `_v2` files as its main items, plus the label metrics and this test. The v1 and v3 tables stay under "other files" as sensitivity variants.

## 2026-10-03. Module B2: time term and gamma chosen on the labels, final run with B1 rule set v2

- **Labels.** `python scripts/blind_labels.py merge` copied the owner's 15 audit labels into data/labels/parents_review.csv: 14 name a candidate and 1 says none. The same command merged 71 B1 labels into memory_pairs_review.csv and kept backups of both sheets. `python -m avsd.lineage.prelabel_parents claude` maps Claude's 50 blind labels through parents_blind_map.json into data/labels/parents_claude.csv: 45 name a candidate and 5 say none. Claude and the owner agree on 9 of 15 rows (60%; an ENV candidate counts as env). The composite set takes the owner's label where the owner answered the row and Claude's elsewhere: 45 cases.
- **Label mapping fixed.** A uid in the sheet names a message or memory row, and one row can carry several units (3,144,784 occurrences, 1,904,069 uids). Labels now resolve through the sheet's request file (item to occurrence), and a candidate is the occurrence of its uid in the same unit. The earlier `--gamma hand` path matched by uid alone and could attach a label to the wrong unit. No run had used it. Test: `test_sheet_labels_resolve_shared_uids_through_requests`.
- **Choice (`avsd lineage trees --gamma composite`).** The grid covers 10 values of gamma and 2 time terms (module A kernel plus KDE, or the KDE alone). The rule is parent accuracy on the composite set, with ties between candidates split evenly, and the mean log posterior breaks ties. The two time terms tie on accuracy: 30 of 45 (0.667) for the module A kernel at gamma 0 or 0.25 and for the KDE alone at gamma 0.25. The mean log posterior decides: -0.786 for the KDE alone against -2.116 for the module A kernel (gamma 0.25). Chosen: the KDE alone, gamma = 0.25. The owner's 14 cases alone give the same choice (10 of 14 against 8 of 14). Claude's 45 cases alone choose the module A kernel at gamma 0.25 (33 of 45 against 28 of 45). With 45 labels, one or two labels decide such differences. `--gamma hand` applies the same rule to the owner's labels alone and needs at least 20.
- **Accuracy of the MAP parent with the time term alone (gamma 0).** Module A kernel: owner 8 of 14, Claude 31 of 45, composite 30 of 45. KDE alone: owner 10 of 14, Claude 26 of 45, composite 29 of 45. The baseline "latest candidate" reaches 12 of 14 on the owner's labels (0.857 [0.615, 1]) and 32 of 45 on the composite set (0.711 [0.573, 0.842]), above every grid point. Cause unidentified; n is small. All grid points: outputs/tables/trees_label_selection.csv.
- **Departure from the default of 2026-10-01.** That default made the module A kernel the main time term. The labels choose the KDE alone, so the module A kernel is now the sensitivity run and the `_module_a` rows of the ablation. On the 10,871 tier-1 name references the KDE alone also fits better: accuracy 0.881 [0.874, 0.891] against 0.860 [0.851, 0.868], mean log posterior -0.339 against -0.778.
- **B1 rule set.** The final run uses `--rules v2`, B1's main rule set since 2026-10-03 and now the default of `avsd lineage trees`. The rule set sets the memory presence of re-mentions only. The run with rules v3 and the same choice (job 630039; its outputs are kept in data/interim/b2_v3_composite/) differs in 9 of about 815,600 transmissions, through the KDE fitted on single-candidate edges, and gives the same H1 p values.
- **Reading (job 630077; rules v2, KDE alone, gamma 0.25; outputs/qa/lineage_trees.md).**
  - Scale. 2,117,354 acquisitions: 815,594 transmitted, 156,749 independent and 1,145,011 without a candidate. 280,973 units have a transmission. Agent-level trees have at most 7 generations (152 when every MAP edge counts).
  - H1 headline (determined paths). Chat into another agent's memory: 351,863 transmissions in generations 1 to 3, A2 = 589.8, z = 524 against the permutation null, p = 0.002 (499 permutations). Median intervals are 0.142 active hours [0.141, 0.143] (347,801), 0.263 [0.237, 0.289] (3,993) and 0.326 [0.237, 2.375] (69). The test's synthetic type I error is 7% [3.4%, 13.7%] (100 replicates) and its power 100% [87%, 100%] (25 replicates). Chat to chat between agents also rejects (84,857 transmissions, generations 1 and 2, z = 177, p = 0.002; medians 0.064 h [0.063, 0.065] and 2.17 h [1.04, 3.82], n = 84,450 and 407), but its synthetic type I error is 13% [7.8%, 21.0%] and its power 40% [23%, 59%]. Determined paths do not depend on the time term or gamma, so these p values and medians are the same as on 2026-10-01. The synthetic rates move with the simulation's parameters: the chat-to-chat rate was 7% under the module A kernel with gamma 0.
  - MAP forest, for completeness. Chat to chat: p = 0.002 with a synthetic type I error of 76% [67%, 83%]. Chat into another agent's memory: p = 0.002 with 37% [28%, 47%].
  - T_k (MAP). The mean rises from 44.9 h [44.3, 45.5] at k = 1 (519,843 acquisitions) to 197 h [122, 279] at k = 5 (153). Slope 10.8 h per generation [9.1, 12.5], k^2 term 12.0 [9.0, 15.0].
  - Offspring. 0.235 [0.233, 0.238] at generation 1, against 0.466 expected from the finite population. Cause unidentified.
  - H3. Agent-to-agent retelling changes a carried quantity value with c = 0.301 [0.299, 0.302] (909,623 contexts on 942,606 edges): 0.429 [0.425, 0.433] from chat to chat and 0.247 [0.245, 0.248] from chat into another agent's memory. B1's consolidation counterpart (quantity facts whose context stays; Wilson intervals): v2 0.0095 [0.0095, 0.0096] (19,437,527 contexts), v3 0.0330 [0.0328, 0.0331] (7,386,947), v1 0.130 [0.129, 0.130] (6,550,788).
  - Restatement depth. 1,027,430 of the 3,144,784 occurrences (32.7%) are re-mentions. Their MAP parent is the actor's own earlier occurrence in 53.7% of cases, another actor's occurrence in 27.5%, env_i in 4.7% and none in 14.1%.
  - Sensitivity. Every variant gives at most 7 generations, 786,857 to 832,214 transmissions, and p = 0.005 (199 permutations) for both determined-path strata and the MAP-forest combined test: the module A kernel, gamma 0 and 1, content between agents only, the literal env_i rule, exposure "ever" and "all", and B1 rule sets v1 and v3.

## 2026-10-03. Pre-public check of the repository (SPEC 10.5)

- **Files.** The 343 tracked files of commit 288854b are code, configs, docs, aggregate tables, figures and reports. None is a data file, screenshot or parquet.
- **Credentials.** A pattern scan and `scripts/scan_credentials.py` find no real secret. The only hits are placeholder tokens in tests and two variable names.
- **Human names.** None of the 3,257 human display names of at least four characters from the raw USER_TALK and USER_NAME_CHANGE events appears in a tracked file. The 21 strings that do match are common words, agent names that viewers copied and fixture names in tests.
- **Message text and links.** No table holds message text; the long cells are rule descriptions and notes. Outputs link only to theaidigest.org replays and wenhaochai.com. Google document links appear only as placeholders in tests.
- **Credential locations.** The only recorded location id in a tracked file is the scaffold bot's account id, which the code needs to classify system events.
- **Left to the owner before making the repository public.** SPEC.md contains the owner's cluster login and lab-internal cluster rules. docs/decisions.md, PROGRESS.md, outputs/qa/memory_prelabel.md, reports/index.html and the Gemini scripts record the use of the Gemini free tier. There is no LICENSE file.

## 2026-10-03. Write-up organized around one core question (owner's choice)

- **Why.** The owner found the write-up scattered. It listed 16 results subsections module by module and never posed one question.
- **Core question.** How strongly do agents in the swarm influence each other? The write-up, the one-page summary and the Chinese explainer now pose it first and answer it in the summary.
- **Structure.**
  - Results follow the channels: chat (A), memory (B1), retelling between agents (B2), shared work (D) and scaffolding changes (C). A last section gathers the checks of every measurement.
  - Methods follow the same order. The label validation now sits inside the B1 and B2 subsections, so no section refers to a later one.
- **What did not change.** No number changed. Figures and tables are renumbered in order of appearance, and `docs/writeup_sources.md` follows the new sections.
- **New in the write-up.** The size of the MAP forest, and the synthetic accuracy of parents on determined paths: 95.4% [95.1, 95.7], against 79.2% [78.8, 79.6] for MAP parents of transmissions.

## 2026-10-04. Write-up figures redrawn with the plot skill, tables moved to an appendix, authors

- **Why.** The owner found the figures unattractive and the tables too many, and asked for the writing and plotting skills of wenhaochai/claude-plugins (commit ebc8b08).
- **Figures.** `scripts/writeup_figures.py` draws nine figures with the skill's style module, copied to `scripts/plot_style/` with its fonts and their licence. Each figure reads only aggregate tables in `outputs/tables/`. One small table is new: `changelog_dates.csv` holds the dates and categories of CHANGELOG entries and nothing else. Colours are Penn Blue and Penn Red with their tints, as SPEC 10.3 asks.
- **Tables.** The main text keeps three tables: the data scale, retention under the three rule sets and the commands. The other nine move to an appendix as Tables A1 to A9. Results that had only a table now have a figure: H1 on determined paths, H3, and continuation of the previous session.
- **Text.** Captions state what the figure shows and one reading of it. Twelve ", which" clauses became separate sentences or participles. Two caption readings were checked against the tables: self-excitation leads in 24 of the 42 windows, and both moments of T_k lie above the linear trend from k = 3 on. No number in the text changed.
- **Authors.** Enxin Song and Wenhao Chai. The acknowledgement no longer thanks Wenhao Chai; the write-up still cites the swarm-scaling blog as Chai (2026).

## 2026-10-04. Analyses named by what they measure instead of module letters (owner's request)

- **Why.** The owner does not want the write-up to speak of modules A to D.
- **Names.** The excitation model (module A), memory retention or fact tracking (B1), transmission trees (B2), change points or change-point detection (C), and the simulator reproduction and dependency graphs (D).
- **Other internal labels removed from the write-up.** SPEC section numbers, the hypothesis labels H1 to H3, now stated as the hypotheses themselves, the monitor comparison labels V1 to V3, and "the owner", now "the first author". Window names such as G35-39 are now explained once.
- **Intervals.** The write-up and the one-page summary now say that square brackets give 95% confidence intervals, and that counts, descriptive shares of the full data and p-values carry none. SPEC 10.2 asks for an interval on every estimate, so the brackets stay.
- **Where the letters stay.** Code, file names, QA reports and the section headings of PROGRESS.md. The results browser keeps them inside item descriptions, while its tabs now carry the new names.
- **PDF.** Intervals and equals signs no longer break across lines.

## 2026-10-04. GM2 colours and more figures in the write-up (owner's request)

- **Colours.** The owner asked for the plot skill's own Google GM2 tones instead of Penn Blue and Penn Red, for this and all later figures. SPEC 10.3 now says so, in the repository copy and in the original. Categories take blue, red, yellow and green in that order, bars the 400 tone, points and lines the 600 tone, and references and baselines grey. The PDF's link colour is GM2 blue 700.
- **More figures.** The owner found the write-up short of figures. Every results paragraph that had only text now has a figure, from 9 to 16 figures. Figure 1 now shows the composition of every accepted window in time order next to the pooled shares. The new figures cover the durability of fact units (beta-geometric fit and c′), the hazard around the switch, the spread of units between agents, session cost by depth, weekdays of change points, loss detection against the audit labels, and the simulator checks. Every figure reads aggregate tables in `outputs/tables/` or, for the weekdays, the table in `outputs/qa/changepoint.md`.
- **Corrections found while drawing.** The c′ of all standard agents under rule set v2 is 0.87482, so the write-up and Table 2 now say 0.87 instead of 0.88, a double rounding of 0.875. The smallest of the nine c′ estimates is 0.7946, so their range now starts at 0.79 instead of 0.80. The text now also gives the hazards before the switch, 44.7% [41.8, 48.0] at the first consolidation and 26.8% [23.8, 29.0] at the second.
- **Chinese explainer.** Its figures and page now use GM2 tones too, with near-black text instead of Penn Blue.
- **Not changed.** The module figures F1 to F7 of the results browser still use the Penn colours. The analysis code draws them during each run, so they change only when the analyses run again.

## 2026-10-04. SPEC 10.2 item 7 follows the author decision (owner's request)

- The write-up structure in SPEC no longer asks to thank Wenhao Chai for the simulator. It now names Enxin Song and Wenhao Chai as authors and cites his blog post, as the write-up and the one-page summary already do. The repository copy and the original changed together.

## 2026-10-04. Point estimates in the text, intervals in figures and tables (owner's request)

- **Change.** The owner asked to drop the bracketed intervals such as [28.9, 38.4] from the write-up. The text and the one-page summary now give point estimates, sample sizes and p-values. Figures keep their 95% error bars and the tables keep their intervals in brackets. The opening paragraph says so. SPEC 10.2 now states this rule instead of "every number with an interval and a sample size", in both copies.
- **Wording kept honest.** Where a conclusion rested on an interval, the text now says it in words: the post-switch rise under rule set v2 and the F1 gain of v2 over v1 each have an interval above zero, and the distinct-pair percentiles of the monitor check sit against a chance level of 50. Two sentences on how the pooled chat intervals were built went, because no pooled interval is left in the text; the bias they mentioned stays in Section 5.
- **Also.** Section 2.1 no longer gives the export date, and its screenshot sentence now gives the reason: every analysis uses the logs. Screenshots belonged to the optional module E (SPEC 9, P2), which never started.
- `docs/writeup_sources.md` keeps the intervals in its "Written" column as the record of each estimate.

## 2026-10-04. Write-up rebuilt around five questions with a question tree (owner's request)

- **Why.** The owner wanted the write-up to say first what we used to study which questions, then give one method and its answer per question, instead of a Methods block followed by a Results block. The owner also asked for a tree diagram like the ones on the swarm-scaling blog page and for fewer numbers in the text.
- **Structure.** Figure 1 is the question tree: the core question, five questions, one method each and two findings each, drawn left to right like the blog's task DAGs (`overview` in `scripts/writeup_figures.py`). Sections 3 to 7 cover chat, memory, retelling between agents, shared work and scaffolding changes, each with a Method and a Findings part. The checks of each method now sit in its own section, so the separate reliability section is gone. Section 2 is three short paragraphs, and the dataset table and the command table moved to the appendix as Tables A1 and A11. The main text keeps one table, the comparison of rule sets.
- **Numbers.** The text keeps the headline numbers and leaves the rest to figures and appendix tables. It runs about 4,000 words instead of about 8,000. No number changed.
- **Removed on request.** The sentence that the first credential scan was reported to AI Digest.

## 2026-10-04. Acknowledgements no longer credit the blog's JavaScript simulator (owner's request)

- The owner asked to drop the sentence that the JavaScript simulator on the blog page of Chai (2026) served as the specification for the re-implementation. It went from the acknowledgements of the write-up and from the README. Section 6 still says, as method, that the re-implementation follows that simulator where the blog text leaves points open.

## 2026-10-04. Memory rules renamed, prior-work paragraph dropped, example dependency graph added (owner's requests)

- **Rule names.** The owner asked for names other than v1, v2 and v3, framed as looking at the same question from different angles. The write-up now calls them anchor match (v1: the extractor finds the unit's anchor again), literal match (v2: also its value verbatim in the new text) and context match (v3: as literal match, with a quantity next to its context word). By what counts as present, anchor match is the strictest and literal match the most lenient. Literal match stays the main rule. Code, flags and file suffixes keep v1, v2 and v3; the caption of Table A11 and the README give the mapping. Figures 5, 6, 7 and 11 and Tables 1 and A3 carry the new names. Touch rules v2 in Section 6 were not renamed.
- **Prior-work paragraph.** The owner asked why Section 4 carried a paragraph on prior work instead of our own modelling. It came from the request of 2026-10-01 to present per-fact tracking as a selling point (`docs/writeup_plan.md`), which needed the nearest prior work to back the "to our knowledge" claim. The paragraph is gone, and so are the 19 references cited only there; Perez et al. 2025 stays for Section 5.
- **Citations restored.** The restructure of the same day had dropped the only citations of Binksmith 2026 and Brown et al. 2002. Section 4 again says, without the number, that the scaffold prompts every rewrite at regular steps and above a length cap, and Section 3 cites Brown et al. 2002 for time-rescaling.
- **Opening.** The sentences on the section layout and on point estimates were dropped on request, so the opening no longer says where the intervals are; figure and table captions still do.
- **Example dependency graph (Figure 12).** `scripts/depgraph_example.py` exports goal G43 (307 sessions of 16 agents, 451 edges, 36 layers, GUI focus gap 5%, touch share 89%) and replicate 0 of the generator for that goal from `run_calibration`, as `outputs/tables/depgraph_example_nodes.csv` and `_edges.csv`, without session ids or agent names (job 630810, 14 s). G43 was chosen as a mid-sized goal from the period with traceable writes. In it, 76.9% of edges join sessions of one agent and 40.6% skip a layer, against 18.3% in the generator DAG; the mean number of parents of a session with parents is 1.78 in both, so the figure shows continuation and layer skipping, not the parent count. Later figures moved up by one.

## 2026-10-04. History squashed, demo video added (owner's requests)

- **History.** With the owner's approval the git history was squashed before going public, because old commits still held SPEC section 0.1 (cluster login and lab rules). GRASP and GitHub main start from the single commit 6b92a2b, whose tree equals the old main; the full history stays only on the GRASP branch `backup-full-history`, which is never pushed. The repository stays private until the owner switches it to public and enables Pages.
- **Submission.** The form is the Airtable link in the organizers' email of 2026-10-02 and on swarmchasing.com/logistics. It needs an Airtable sign-in, so the owner submits it.
- **Demo video.** The owner asked for a demo video in the manner of the awesome-opus5-5-videos collection, where the animation is written as code. `scripts/demo_video/scenes.html` draws every frame with `window.render(t)` on a canvas, `render_frames.mjs` captures 30 frames a second in headless Chrome, and `build_video.sh` encodes `reports/demo.mp4` (1920x1080, 114 s, no audio, so on-screen text carries the story). Ten scenes follow the write-up: title, data, the question tree, then chat, memory, retelling, shared work and scaffolding changes, the toolkit and the links. Every number comes from the aggregate tables through `data_prep.py` or from the write-up; the chat timeline, the memory card and the retelling circle are labelled as schematics. The style follows the write-up figures: white ground, GM2 colours, Instrument Sans.
- **README.** Says five analyses instead of four, matching its own table, and points to the video.
