# Sources of the numbers in reports/writeup.md

One row per numeric claim of `reports/writeup.md`, in the order they appear. "Written" is the value as the write-up states it. "Source value" is the value as the source states it. Shares that the sources give as decimals are written as percentages with one decimal (0.463 becomes 46.3%), and their intervals are converted the same way. Rows marked **derived** were computed by the drafter from the named source; the computation is given.

Rule sets v1, v2 and v3 below are called anchor match, literal match and context match in the write-up since 2026-10-04, and figures from the continuation plot on carry numbers one higher than the rows say. On 2026-10-04 the write-up was rebuilt around five questions (Sections 3 to 7) and keeps far fewer numbers in its text. Rows keep their old section headings and figure and table labels, and numbers that left the text stay as the record of each estimate. Since 2026-10-04 the text of the write-up gives point estimates only (owner's request). The intervals in the "Written" column stay as the record of each estimate; the figures and tables show most of them.

Source keys:

- **R** = the HTML report `~/Downloads/avsd_report/index.html` (build of 2026-10-02 00:14). "R QA x.md §n" is the rendered QA report `outputs/qa/x.md`, section n. "R table x.csv" is the embedded copy of `outputs/tables/x.csv`.
- **D** = `docs/decisions.md`, cited by entry title. **P** = `docs/writeup_plan.md`. **G** = `PROGRESS.md`. **S** = `docs/schema_notes.md`. **SPEC** = `SPEC.md`. **CFG** = `configs/default.yaml`.
- The GRASP copies of the QA reports were not read (the read was blocked in this session). All QA values come from the HTML report.
- **Q** = a QA report or table on GRASP (`outputs/qa/x.md`, `outputs/tables/x.csv`), read directly on 2026-10-03 after the B1 label validation and the final B2 run (job 630077, rule set v2, kernel density, γ = 0.25). Rows that cite Q were updated on 2026-10-03, and the report rebuilt that day shows the same files.

## Summary

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 1 | Influence weaker than self-continuation in chat and work | qualitative claim | self 0.475 against other agents 0.238; continuation 0.602 against at most 0.250 | **derived** from the rows below |
| 2 | Self share of agent messages, event-weighted over 43 windows | 47.5% [45.7, 49.2] | self 0.475 | R QA hawkes.md §4, line under the window table; P Results, Module A; CI from Q writeup_cis.csv |
| 3 | Agent messages in fitted goal windows | 169,324 | 169,324 | R QA hawkes.md §2 |
| 4 | Other-agent share | 23.8% [22.4, 25.2] | other_agents 0.238 | R QA hawkes.md §4; CI from Q writeup_cis.csv |
| 5 | Windows with ρ below 1 | 39 of 42 | ρ > 1 in 3 of 42 accepted windows | R QA hawkes.md §4; **derived** 42 − 3 = 39 |
| 6 | Continuation rate | 60.2% [53.4, 67.4] | 0.602 [0.534, 0.674] | R QA swarmsim_d2_d4.md §8, goal with_parents all |
| 7 | Highest chance baseline of continuation | 25.0% [21.8, 29.0] | 0.25 [0.218, 0.29], day with_parents | R QA swarmsim_d2_d4.md §8 |
| 8 | Times a unit acquired from another agent is passed on | 0.235 [0.233, 0.238] against 0.466 | 0.235 [0.233, 0.238], expected 0.466 | Q lineage_trees.md §5 |
| 9 | H1 test on determined paths | p = 0.002 | p = 0.002 in every stratum between agents, 499 permutations | Q lineage_trees.md §6.1 |
| 10 | Content change between agents, H3 | 30.1% [29.9, 30.2] | c = 0.301 [0.299, 0.302] | Q lineage_trees.md §7, agent_retelling |
| 11 | First-consolidation loss under v2 | 34.0% [28.9, 38.4] | h1 0.340 [0.289, 0.384] | Q lineage_memory_v2.md §4 |
| 12 | Alignment with the CHANGELOG at w = 3 | p = 0.695 | null1_p 0.695, all entries | R QA changepoint.md §8 |

## 2. Data and preprocessing

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 13 | Pinned revision and export date | 838b4150, 2026-09-20 | 838b4150303c..., exported 2026-09-20T13:05:12.097Z | R QA ingest.md header; D "Pin the dataset revision" |
| 14 | Period covered, Pacific time | 2025-04-02 to 2026-09-18 | first PT date 2025-04-02, last 2026-09-18 | R QA build_events.md §1; S §1 |
| 15 | Agents, export against card | 46 against 31 | agents rows 46, SPEC rows about 31 | R QA ingest.md, agents; S §1 table |
| 16 | Size without screenshots | 5.80 GB | 5.80 GB without screenshots | S §1 |
| 17 | Screenshot size, not downloaded | 171.1 GB | 171.1 GB of screenshot tars | S §1 |
| 18 | Table 1, events | 381,610 against ≈233,000 | 381,610; SPEC about 233,000 | R QA ingest.md, events; S §1 |
| 19 | Table 1, chat_messages | 183,485 against ≈123,000 | 183,485; about 123,000 | R QA ingest.md; S §1 |
| 20 | Table 1, computer_use_sessions | 78,362 against ≈37,000 | 78,362; about 37,000 | R QA ingest.md; S §1 |
| 21 | Table 1, computer_use_turns | 2,510,487 against ≈1,140,000 | 2,510,487; about 1,140,000 | R QA ingest.md; S §1 |
| 22 | Table 1, agent_memories | 246,151 against ≈165,000 | 246,151; about 165,000 | R QA ingest.md; S §1 |
| 23 | Table 1, summaries | 939 against ≈800 | 939; about 800 | R QA ingest.md; S §1 |
| 24 | Table 1, claude_code_messages | 244,820 against ≈245,000 | 244,820; about 245,000 | R QA ingest.md; S §1 |
| 25 | Table 1, claude_code_sessions | 303 against ≈300 | 303; about 300 | R QA ingest.md; S §1 |
| 26 | Table 1, chat_rooms | 16 against 5 | 16; SPEC about 5 | R QA ingest.md; S §1 |
| 27 | Table 1, village_goals | 51 against ≈45 | 51; about 45 | R QA ingest.md; S §1 |
| 28 | Table 1, agent_goals | 33, not listed | 33; card n/a | R QA ingest.md; S §1 |
| 29 | Table 1, villages | 1 against 1 | 1; SPEC 1 | R QA ingest.md; SPEC §2.1 |
| 30 | Table 1 caption, manifest match, duplicates, parse failures | difference 0, no duplicate id, no unparsed timestamp | difference +0, duplicate ids 0, parse failures 0 for every table | R QA ingest.md, every table |
| 31 | Run days | 389 | 389 | R QA build_events.md §9; G 4.1-4 |
| 32 | Weekdays and weekend days among run days | 383 and 6 | all 383 weekdays plus 6 weekend days | S §4.8 |
| 33 | Run blocks | 392 | Realizations (blocks): 392 | R QA build_events.md §9 |
| 34 | Pause gap | G = 30 minutes | G = 30 min | R QA build_events.md header; CFG time.pause_gap_minutes |
| 35 | Active time at G = 30 and G = 15 minutes | 1,598.3 h; 1,595.5 h | 1,598.3 h; 1,595.5 h | R QA build_events.md §9 |
| 36 | Daily-summary targets reproduced by the village-day rule | 789 | 789 of 789 | R QA build_events.md §5; D "Unified event table conventions" |
| 37 | Rows of the unified event table, reconciliation | 3,187,863, zero difference | 3,187,863, difference 0 | R QA build_events.md §1 |
| 38 | Bot run markers and nudges | 662 and 1,568 | 662 daily run markers, 1,568 auto-nudges | S §4.6; R QA build_events.md §3 |
| 39 | Summaries | 939 | 939 | R QA build_events.md §2 |
| 40 | Chat rooms | 16 | 16 | R QA ingest.md; S §4.5 |
| 41 | All messages in general before | 2026-03-06 | every message before 2026-03-06 is in general | S §4.5 |
| 42 | Room shares 2026-03-16 to 2026-07-05 | rest 63%, best 26% | rest 63% plus best 26% | S §4.5 |
| 43 | Room shares from 2026-07-06 | general 93%, focus 7% | general 93% plus focus 7% | S §4.5 |
| 44 | Message rooms reproduced | 173,486 of 173,493 | 173,486 of 173,493 | R QA build_events.md §6; D "Unified event table conventions" |
| 45 | Agents by family | 46; Anthropic 16, OpenAI 14, Google 5, Other 11 | same | R QA build_events.md §11; S §4.9 |
| 46 | CHANGELOG entries | 186; 126 scaffolding; 60 roster | 186 rows, changelog 126, roster 60 | R QA build_events.md §13; R QA changepoint.md §1 |
| 47 | Owner confirmed categories | 2026-09-30, goal and chat added | owner confirmed 2026-09-30, added goal and chat | D "Owner choices on CHANGELOG categories"; G 4.1-7 |
| 48 | Entries per category | prompt 55, roster 60, tool 54, model 51, chat 29, memory 18, goal 16, other 12 | n_entries: prompt (goal pooled) 55, roster only 60, tool 54, model 51, chat 29, memory 18, goal 16, other 12 | R QA changepoint.md §8, first table |
| 49 | First credential report to AI Digest | 2026-10-01 | report email sent by the owner on 2026-10-01, from the first scan | D "Typed sign-in values in GUI actions" ("the report sent to AI Digest on 2026-10-01") |

## 3. Methods

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 50 | Baseline bins | eight hourly bins | 8 hourly baseline bins | R QA hawkes.md §1; CFG hawkes.baseline_hour_bins |
| 51 | Kernel time scales and maximum lag | 1 min, 10 min, 1 h; L = 3 h | betas 1/60, 1/600, 1/3600 per s; L = 3 h | R QA hawkes.md §1; CFG |
| 52 | Per-cell kernels missed the recovery bar | no number in text | MAE 0.07 to 0.12 against the 0.05 bar | D "Recovery limits of the per-cell kernel model" |
| 53 | Starts per fit | three | three starts (uniform, global, cell) | R QA hawkes.md §1 |
| 54 | Village goals | 51 | 51 | R QA ingest.md, village_goals |
| 55 | Group threshold and merge threshold | 10%; 500 agent messages | rooms with more than 10%; fewer than 500 agent messages merged | R QA hawkes.md §1 |
| 56 | Recovery replicates and bar | 20; 0.05 | 20 replicates (40 near the bar); mean mae4 < 0.05 | R QA hawkes.md §1 |
| 57 | Final windows, messages, passing | 43; 169,324; 42 | 43 final windows, 169,324 messages, 42 pass | R QA hawkes.md §2, §3 |
| 58 | G40 recovery error | 0.069 | mae4 0.069 | R QA hawkes.md §3 round 2; D "Module A on the real data" |
| 59 | Bootstrap refits | 1,000 | 1000 replicates per goal window | R QA hawkes.md §1 |
| 60 | Tier-1 references start | 2026-02-25 | from 2026-02-25 | D "Module-level consequences of the verification", Parent labels |
| 61 | B1 consolidations and agents | 85,600; 46 | 85,600; 46 | R QA lineage_memory_v3.md §1 |
| 62 | B1 bootstrap draws | 2,000 | 2000 replicates, agents resampled | R QA lineage_memory_v3.md §4 |
| 63 | c′ = 1 under heterogeneity alone | 1 | c′ = 1 still means heterogeneity alone | D "Module B1 v3 and a corrected BdW reading" |
| 64 | Main B1 rule set | v2 | v2 chosen on the owner's audit labels | D "B1 label validation: results and choice of rule set" |
| 65 | B1 blind sheet | 277; 247; 30 of 253 | 277 rows; stratum A 29 + B 218 = 247; 30 of 253 | D "B1 pre-label re-check: results and second review design"; R QA memory_prelabel.md §11 |
| 66 | B1 validation set | 500 units, 100 random consolidation pairs, five per pair | 100 pairs, up to 5 units each, picked in the order modified, restored, dropped, new, kept | src/avsd/lineage/memory.py write_labels; Q memory_prelabel.md §2 |
| 67 | Owner audit | 60 B1 units; 15 B2 occurrences | A 15, B 30, C 15; B2 8 priority-1 and 7 priority-2 rows | D "Labels from Claude, audited by the owner"; Q memory_prelabel.md §12 |
| 68 | Bootstrap of the label metrics | 2,000 replicates within the audit strata | 2,000 bootstrap replicates that resample rows within the audit strata | Q memory_prelabel.md §12 |
| 69 | B2 unit size limits | 3 to 200 occurrences, at least 2 agents | at least 3 occurrences, at least 2 agents, at most 200 | D "Module B2", Selection; CFG lineage |
| 70 | Exposure window | L_B = 3 run days | L_B 3.0 run days | R QA lineage_trees.md §1; D "Module B2", Exposure |
| 71 | B2 blind sheet | 50 | 50 rows | D "Blind labelling" |
| 72 | Time term and γ chosen on the labels | kernel density, γ = 0.25; 66.7% [52.2, 79.4] of 45, tied with the module A kernel; owner's 14: 71.4% [44.4, 93.6] against 50.0% [25.0, 80.0] | KDE only, γ 0.25, composite 0.667 [0.522, 0.794], tied with module A + KDE at γ 0 and 0.25; mean log P −0.786 against −2.116; owner 0.714 against 0.500 | Q lineage_trees.md §4.1; trees_label_selection.csv |
| 73 | γ grid | 0 to 6 | 0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6 | Q trees_label_selection.csv |
| 74 | Tier-1 accuracy at γ = 0 and γ = 0.25 | 88.1% [87.4, 89.1] against 86.9% [86.1, 87.8] | 0.881 [0.874, 0.891]; 0.869 [0.861, 0.878] (kernel density) | Q lineage_trees.md §4 |
| 75 | B2 sheet labels matching a candidate | 45 | composite 45 cases; owner 14 | Q lineage_trees.md §4.1 |
| 76 | Posterior forests | 200 | 200 posterior draws | R QA lineage_trees.md §1 |
| 77 | H1 permutations | 499 | 499 (MAP) | R QA lineage_trees.md §1, §6 |
| 78 | Synthetic datasets and units | 100 null, 25 power, 50,000 units | 100 null replicates of 50,000 units, 25 power replicates | R QA lineage_trees.md §9; D "Module B2", Synthetic validation |
| 79 | D1 families, tasks, checks, tolerance | 256 families of 16 tasks; 15 checks; 20% | 256 families of 16 tasks; 15 of 15; 20% | R QA swarmsim_d1.md Summary |
| 80 | Sessions | 78,362 | 78,362 | R QA swarmsim_d2_d4.md Summary |
| 81 | Touch rules v2 confirmed | 2026-10-01 | confirmed by the owner on 2026-10-01 | D "D2 touch rules v2 confirmed as the main version" |
| 82 | Generator graphs per goal | 64 | 64 DAGs per goal | R QA swarmsim_d2_d4.md §6 |
| 83 | Series by level | 387 of 543; 45, 258, 84 | 543 candidates, 387 analysed (45 family, 258 per-agent, 84 lexical) | D "Module C detection and alignment settings"; R table changepoint_series.csv **derived** counts |
| 84 | Minimum segment and penalty | 10 run days; 2 log n | minimum segment 10 run days; β log n with β = 2 | D "Module C detection and alignment settings"; R QA changepoint.md §3 |
| 85 | Alignment window | w = 3 | w = 3 run days | R QA changepoint.md §1; SPEC 7.3 |
| 86 | Null draws | 10,000 | null reps 10,000 | R QA changepoint.md §1 |
| 87 | Monitor model | Claude Opus 4.8 | generated by claude-opus-4-8 (some later rows list claude-opus-5-5 as well) | R QA monitor.md header; D "External validation against the AI Village LLM monitor" |
| 88 | Monitor fetch date | 2026-10-01 | fetched 2026-10-01T02:50:46 to 03:12:16 UTC | R QA monitor.md header |
| 89 | V1 and V2 findings | 1,483 | 1,483 (80 conflicts) | R QA monitor_validation.md §1 |
| 90 | V1 window | 30 minutes | ±30 min | R QA monitor_validation.md §3 |

## 4. Results

### 4.1 Chat

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 91 | Event-weighted shares | 47.5% [45.7, 49.2] self, 25.9% [24.5, 27.2] baseline, 23.8% [22.4, 25.2] other agents, 1.8% [1.5, 2.1] human, 1.0% [0.7, 1.4] system | baseline 0.259, human 0.018, system 0.010, other_agents 0.238, self 0.475 | R QA hawkes.md §4 |
| 92 | Windows where self, baseline, other agents lead | 24, 13 and 5 of 42 | per-window shares | R table hawkes_windows.csv, **derived** largest of self, baseline, other agents, human + system per accepted window |
| 93 | Windows with baseline above 50%, and their dates | 7; 6 between 2025-12-15 and 2026-03-20 | g05-07 0.5176, g23 0.5779, g27 0.5373, g29 0.6103, g30 0.5592, g31 0.534, g35 rest 0.5697 | R table hawkes_windows.csv, **derived** |
| 94 | Baseline peak in G29 | 61.0% [42.8, 63.1] | 0.6103 [0.4275, 0.6306] | R table hawkes_windows.csv; R QA hawkes.md §4 shows 0.61 [0.43, 0.63] |
| 95 | Human share in the five windows before 2025-08-13 | between 3.6% and 8.0% | g01 0.0586, g02-03 0.0359, g04 0.0798, g05-07 0.0793, g08 0.0392 | R table hawkes_windows.csv, **derived** |
| 96 | Chat public until | 2025-08-13 | human chat public until 2025-08-13 | S §5 |
| 97 | Later windows with human share at most 4.0% | 37 of 38 | largest later values g09 0.0404, g13 0.0396, g41-44 0.0394, then g45-47 best 0.1322 | R table hawkes_windows.csv, **derived**; 0.0404 rounds to 4.0% |
| 98 | Human share in G45-47, best | 13.2% [5.1, 22.2] | 0.1322 [0.0511, 0.2219] | R table hawkes_windows.csv |
| 99 | ρ below 1, no interval wholly above 1 | 39 of 42 | ρ > 1 in 3 of 42; interval above 1 in 0 | R QA hawkes.md §4 |
| 100 | G51 agents and ρ | 32; 0.963 [0.933, 1.012] | K 32; 0.963 [0.933, 1.012] | R QA hawkes.md §4 |
| 101 | G08 ρ | 1.065 [0.709, 1.118] | 1.065 [0.709, 1.118] | R QA hawkes.md §4 |
| 102 | G36-37 rest ρ | 1.023 [0.818, 1.094] | 1.023 [0.818, 1.094] | R QA hawkes.md §4 |
| 103 | G35-39 best ρ | 1.756 [0.903, 3.817] | 1.756 [0.903, 3.817] | R QA hawkes.md §4 |
| 104 | Agent setting ρ in G35-39 | 11 messages on 2 of 35 realizations | Claude Haiku 4.5, 11 messages on 2 of 35 realizations, n_ii 1.76 | D "Hawkes exposure by presence"; R QA hawkes.md §4 part-time table, presence 0.06, events 11 |
| 105 | Core ρ in G35-39 and the presence threshold | 0.922 [0.826, 0.971]; 80% | rho core 0.922; core = present on at least 80% | R QA hawkes.md §4; CFG hawkes.core_presence |
| 106 | Figures 1 and 2, windows | 42 | 42 of 43 final windows shown | R QA hawkes.md §12 |

### 4.2 Memory

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 107 | Consolidate step | every 40 actions | consolidate tool every 40 actions; Binksmith 2026 | P Wording rules |
| 108 | Fact units, standard agents, consolidations | 4,146,180; 45; 83,836 | All standard: 45 agents, 83,836 consolidations, 4,146,180 units | R QA lineage_memory_v3.md §1 |
| 109 | Claude Code consolidations | 1,764 | 1,764 | R QA lineage_memory_v3.md §1 |
| 110 | Late hazard below first in every family | every family | holds in v1, v2, v3 | R QA lineage_memory_v3.md §0, conclusions table |
| 111 | H2 rejected, largest p | p at most 2.5 × 10⁻¹⁵ | largest p is Google under v1, 2.5e-15; others smaller | R QA lineage_memory_v3.md §0, H2 outcome table |
| 112 | h1 range over rule sets | between 34.0% and 52.2% | 0.522 / 0.340 / 0.463 | R QA lineage_memory_v3.md §0, hazard table |
| 113 | h9+ range over rule sets | between 2.5% and 4.5% | 0.045 / 0.025 / 0.025 | R QA lineage_memory_v3.md §0 |
| 114 | h1 and h9+ under v2 | 34.0% [28.9, 38.4]; 2.5% [2.1, 3.0] | 0.340 [0.289, 0.384]; 0.025 [0.021, 0.030] | Q lineage_memory_v2.md §4 |
| 115 | Beta-geometric AIC gain against geometric | at least 3.5 million | v1 3,538,806; v2 6,096,740; v3 6,420,936 | R QA lineage_memory.md §14; lineage_memory_v2.md §14; lineage_memory_v3.md §14 |
| 116 | Beta-geometric beats piecewise for all standard agents | every rule set | AIC lower by 61,394 (v1), 567,175 (v2), 292,167 (v3) | same three QA reports §14 |
| 117 | Survivors' c′, all standard agents | 0.87 [0.82, 0.93] under v2 | 0.87482 [0.81795, 0.92693] | Q memory_v1_v2_v3.csv, BdW c among survivors of g = 1 (clock restarted); corrected 2026-10-04 from 0.88, a double rounding of 0.875 |
| 118 | Nine c′ estimates | between 0.79 and 0.91, intervals below 1 | 0.8634, 0.8748, 0.8602; pre 0.8565, 0.8208, 0.7946; post 0.8793, 0.9052, 0.9050; all CIs below 1; corrected 2026-10-04 from 0.80 | R QA lineage_memory_v3.md §0; D "Module B1 v3 and a corrected BdW reading" |
| 119 | Post-switch hazards, v2 | 30.3% [24.9, 35.6]; 37.6% [34.3, 40.6] | 0.303 [0.249, 0.356]; 0.376 [0.343, 0.406] | Q lineage_memory_v2.md §6, regime:post |
| 120 | Paired post-switch rise, v2 | 7.3 points [1.5, 13.0] | +0.073 [+0.015, +0.130], 2,000 agent-bootstrap replicates | Q memory_post_switch_rise.csv |
| 121 | Paired post-switch rise, v1 and v3 | positive, interval includes zero | v1 +0.061 [−0.017, +0.148]; v3 +0.051 [−0.023, +0.131] | Q memory_post_switch_rise.csv |
| 122 | Modified share of first losses | 23.3% [20.8, 26.6], 5.2% [4.7, 5.6], 6.6% [6.0, 7.1] | 0.233 / 0.052 / 0.066 | R QA lineage_memory_v3.md §0 |
| 123 | Restored share of lost units | 18.4% [16.5, 20.2], 14.7% [13.1, 16.2], 16.6% [14.9, 18.2] | v1 18.4%, v2 14.7%, v3 16.6% | R QA lineage_memory.md §14; lineage_memory_v2.md §14; lineage_memory_v3.md §14 |
| 124 | Selling-point claim | exact text | claim paragraph | P Contribution claims 1 |

### 4.3 Retelling between agents

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 125 | MAP forest scale | 815,594 transmissions over 280,973 units | transmitted 815,594; units with an edge 280,973 | Q lineage_trees.md §2 and §5 |
| 126 | Offspring, generation 1 | 0.235 [0.233, 0.238] against 0.466 | 0.235 [0.233, 0.238], expected 0.466 | Q lineage_trees.md §5 |
| 127 | Offspring, generation 2 | 0.112 [0.109, 0.115] against 0.414 | 0.112 [0.109, 0.115], expected 0.414 | Q lineage_trees.md §5 |
| 128 | Memory share of transmissions into generations 1 and 2 | 76.8% [76.6, 76.9] of 645,779; 84.8% [84.6, 85.0] of 150,985 | 0.767645 [0.766415, 0.768860]; 0.848111 [0.846060, 0.850132] | Q writeup_cis.csv (rerun of 2026-10-03 on the final summary) |
| 129 | Determined-path tests between agents | p = 0.002 in both strata; z = 524 and z = 177 | chat to memory p 0.002, z 523.984; chat to chat p 0.002, z 176.793; 499 permutations | Q lineage_trees.md §6.1 |
| 130 | Chat into another agent's memory, transmissions | 351,863 | 351,863 edges, generations 1 to 3 | Q lineage_trees.md §6.1 |
| 131 | Table A1, chat to memory, generation 1 | 347,801; 0.142 [0.141, 0.143] | 347,801; 0.141849 [0.140865, 0.142852] | Q trees_h1_intervals_determined.csv |
| 132 | Table A1, chat to memory, generation 2 | 3,993; 0.263 [0.237, 0.289] | 3,993; 0.262742 [0.237107, 0.288926] | same |
| 133 | Table A1, chat to memory, generation 3 | 69; 0.326 [0.237, 2.375] | 69; 0.325994 [0.237128, 2.374921] | same |
| 134 | Chat to chat between agents, transmissions | 84,857 | 84,857 edges, generations 1 and 2 | Q lineage_trees.md §6.1 |
| 135 | Table A1, chat to chat, generation 1 | 84,450; 0.064 [0.063, 0.065] | 84,450; 0.06398 [0.062696, 0.065016] | Q trees_h1_intervals_determined.csv |
| 136 | Table A1, chat to chat, generation 2 | 407; 2.17 [1.04, 3.82] | 407; 2.174497 [1.036539, 3.815538] | same |
| 137 | Synthetic type I error, memory and chat to chat | 7.0% [3.4, 13.7]; 13.0% [7.8, 21.0] | 0.070 [0.034, 0.137]; 0.130 [0.078, 0.210] | Q lineage_trees.md §6.1, §9 |
| 138 | Synthetic type I error of the earlier run | 10.0% [5.5, 17.4]; 7.0% [3.4, 13.7] | memory 0.100 [0.055, 0.174]; chat to chat 0.070 [0.034, 0.137] | R QA lineage_trees.md §6.1 (report build of 2026-10-02) |
| 139 | Synthetic power, memory and chat to chat | 100% [87, 100]; 40% [23, 59] | 1 [0.867, 1]; 0.400 [0.234, 0.593] | Q lineage_trees.md §6.1, §9 |
| 140 | Sensitivity runs keep the chat-to-chat test | p = 0.005, 199 permutations | 0.005 in every variant | Q lineage_trees.md §10 |
| 141 | Search stratum | p = 0.002, not simulated | p 0.002; type I error n/a | Q lineage_trees.md §6.1 |
| 142 | Table A1, chat to search answer, generation 1 | 25,558; 0.340 [0.331, 0.365] | 25,558; 0.340291 [0.331336, 0.3646] | Q trees_h1_intervals_determined.csv |
| 143 | Table A1, chat to search answer, generation 2 | 758; 0.582 [0.464, 0.687] | 758; 0.582485 [0.464115, 0.686608] | same |
| 144 | MAP-forest type I error | 37% to 77% | memory 0.370, chat to chat 0.760, combined 0.770 | Q lineage_trees.md §6.2, §9 |
| 145 | MAP medians, chat to chat, generations 1 and 4 | 0.063 h [0.062, 0.064]; 0.027 h [0.019, 0.031] | same | Q lineage_trees.md §6.3 |
| 146 | MAP T_k at k = 1 | 44.9 h [44.3, 45.5], 519,843 | 44.933 [44.297, 45.518], 519,843 | Q lineage_trees.md §6.4 |
| 147 | MAP T_k at k = 5 | 197 h [122, 279], 153 | 196.644 [122.313, 278.979], 153 | Q lineage_trees.md §6.4 |
| 148 | MAP slope and quadratic term of the mean | 10.8 [9.1, 12.5]; 12.0 [9.0, 15.0] | 10.804 [9.081, 12.548]; 11.993 [9.006, 15.036] | Q lineage_trees.md §6.4 |
| 149 | MAP quadratic term of the variance | 6,574 h² [4,576, 8,519] | 6573.793 [4575.786, 8518.915] | Q lineage_trees.md §6.4 |
| 150 | Spearman of consecutive intervals | 0.180 [0.174, 0.186], 161,707 pairs | 0.180 [0.174, 0.186], n = 161,707 | Q lineage_trees.md §6.4 |
| 151 | Determined-path quadratic term of the mean | 44.4 [−7.0, 91.3], p = 0.120, three generations | 44.372 [−7.012, 91.336], p 0.120, k values 3 | Q lineage_trees.md §6.1, T_k table |
| 152 | c between agents, contexts | 30.1% [29.9, 30.2] of 909,623 | 0.300564 [0.299030, 0.302299], 909,623 | Q trees_h3.csv, agent_retelling |
| 153 | B1 consolidation counterpart, v2 | 0.95% [0.95, 0.96] of 19,437,527 | 0.009543 [0.009499, 0.009586], 185,484 of 19,437,527 | Q trees_h3.csv |
| 154 | B1 consolidation counterpart, v1 and v3 | 13.0% [12.9, 13.0]; 3.3% [3.3, 3.3] | 0.129577 [0.129320, 0.129834], 6,550,788; 0.032948 [0.032820, 0.033077], 7,386,947 | Q trees_h3.csv |
| 155 | Audit units the owner labelled modified | 3 of 60 | modified 3 of 60 | Q memory_prelabel.md §13, confusion matrix |
| 156 | c chat to chat between agents | 42.9% [42.5, 43.3], 269,365 contexts | 0.428868 [0.424793, 0.432795], 269,365 | Q trees_h3.csv |
| 157 | c chat to another agent's memory | 24.7% [24.5, 24.8], 640,258 contexts | 0.246585 [0.244985, 0.248051], 640,258 | Q trees_h3.csv |
| 158 | c chat to search answer | 5.7% [5.5, 5.8], 255,850 contexts | 0.056916 [0.055293, 0.058344], 255,850 | Q trees_h3.csv |
| 159 | c over sensitivity runs | between 29.4% and 30.9% over nine runs | 0.294, 0.309, 0.298, 0.304, 0.295, 0.301, 0.302, 0.301, 0.301 | Q lineage_trees.md §10 |
| 160 | Inheritance and reversion | 42.0% [41.6, 42.5]; 41.7% [41.2, 42.2] of 83,218 | 0.420186 [0.415555, 0.424878]; 0.417278 [0.412268, 0.422361], 83,218 contexts | Q writeup_cis.csv |
| 161 | Inheritance and reversion in the earlier run | 36.0% [35.5, 36.5]; 48.5% [47.9, 49.0] of 76,865 | 0.359891 [0.355329, 0.364569]; 0.484746 [0.479158, 0.490253], 76,865 | data/interim/writeup_cis_before_b2final.csv (the table before the rerun) |
| 162 | Similarity to the most common window | +0.052 [0.051, 0.053], 2,530,986 occurrences | 0.051932 [0.051063, 0.052878], 2,530,986 | Q trees_attractor.csv |
| 163 | Type-token ratio slope | 0.0056 [0.0054, 0.0058] | 0.005583 [0.005399, 0.005790] | Q trees_attractor.csv |

### 4.4 Shared work

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 164 | Continuation pairs and agents | 50,251; 45 | 50,251 pairs, 45 agents | R QA swarmsim_d2_d4.md §8 |
| 165 | Same-goal baseline | 6.3% [5.1, 7.7] | 0.0632 [0.0512, 0.0765] | R QA swarmsim_d2_d4.md §8 |
| 166 | Same-day baseline | 25.0% [21.8, 29.0] | 0.25 [0.218, 0.29] | R QA swarmsim_d2_d4.md §8 |
| 167 | Table A3, same-day row | 60.2% [53.6, 67.3] | 0.602 [0.536, 0.673] | R QA swarmsim_d2_d4.md §8 |
| 168 | Table A3, before the switch | 43.2% [34.7, 51.6] against 9.6% [7.9, 11.3], 12,733 pairs | 0.432 [0.347, 0.516]; 0.0961 [0.0792, 0.113]; 12,733 | R QA swarmsim_d2_d4.md §8, regime_pre |
| 169 | Table A3, after the switch | 66.0% [59.1, 73.4] against 5.2% [3.9, 6.6], 37,516 pairs | 0.66 [0.591, 0.734]; 0.0521 [0.0393, 0.0664]; 37,516 | R QA swarmsim_d2_d4.md §8, regime_post |
| 170 | Mean parents per step | 2.67 [1.95, 2.97] against 1.74 [1.73, 1.75] | 2.67; generator 1.74 [1.73, 1.75] | R QA swarmsim_d2_d4.md §6 |
| 171 | Layer-skipping edges | 60.0% [45.4, 64.1] against 19.8% [18.9, 20.4] | 0.6; 0.198 [0.189, 0.204] | R QA swarmsim_d2_d4.md §6 |
| 172 | Out-degree Gini | 0.496 [0.438, 0.508] against 0.534 [0.527, 0.542] | 0.496; 0.534 [0.527, 0.542] | R QA swarmsim_d2_d4.md §6 |
| 173 | Generator quantiles | 0 or 1 | quantiles 1, 1, 0 | R QA swarmsim_d2_d4.md §6 |
| 174 | Edges and same-agent share | 130,508 over 51 goals; 65.2% | 130,508 edges; 65.2% join two sessions of the same agent | R QA swarmsim_d2_d4.md Summary |
| 175 | Sibling merges | inside the range for all edges, below for write edges | all 0.439 (range 0.401 to 0.443, quantile 0.953); write 0.221 (quantile 0) | R QA swarmsim_d2_d4.md §6 |
| 176 | Slope of relative turns | 0.029 [−0.092, 0.074] against 9 | 0.0294 [−0.0918, 0.0742]; blog 9 | R QA swarmsim_d2_d4.md §7 |
| 177 | Slope of relative active minutes | 0.151 [−0.122, 0.255] | 0.151 [−0.122, 0.255] | R QA swarmsim_d2_d4.md §7 |
| 178 | Turn cap and median | near 40; 41 | quantiles 9, 41, 41, 45; capped near 40 | R QA swarmsim_d2_d4.md §1 |
| 179 | Table A3, sessions and goals of the slope fits | 77,725 sessions; 49 goals | 77,725; 49 | R QA swarmsim_d2_d4.md §7 |

### 4.5 Scaffolding changes

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 180 | Aligned change points at w = 3 | 1,929 of 2,314 | 1,929 of 2,314 | R QA changepoint.md §8 |
| 181 | Null-1 mean and p | 1,969.5; p = 0.695 | 1969.530; 0.695 | R QA changepoint.md §8 |
| 182 | 95% null range | 1,835 to 2,085 | q025 1835, q975 2085 | R QA changepoint.md §8 |
| 183 | Null 2 p | 0.998 | 0.998 | R QA changepoint.md §8 |
| 184 | Coverage of run days | 81.2% | 0.812 | R QA changepoint.md §8 |
| 185 | Scaffolding, persistent and external sets | p above 0.4 | 0.774; 0.432; 0.809 | R QA changepoint.md §8 |
| 186 | BOCPD agreement | 45.5% against 17.9% | 0.455; chance 0.179 | R QA changepoint.md §5 |
| 187 | Change points on goal-transition days | 877 of 2,314 | 877 | R QA changepoint.md §9, village goal transitions w = 0 |
| 188 | Coverage of transition days | 13.1% | 0.131 | R QA changepoint.md §9 |
| 189 | Null 2w p and Holm, w = 0 | 0.005; 0.014 | 0.005; 0.014 | R QA changepoint.md §9 |
| 190 | CHANGELOG goal category, Holm under null 2w | 0.021 | 0.021 (null2w_p 0.002) | R QA changepoint.md §8, week-preserving table, goal w = 0; G module C row |
| 191 | w = 1, null 1w and null 2w | p = 0.325; p = 0.269 | 0.325; 0.269 | R QA changepoint.md §9 |
| 192 | Monday share of daily change points | 32.9% of 1,543 | 1543 change points, 32.9% on Mondays | R QA changepoint.md §11 |
| 193 | Mondays among run days | 19.5% | 19.5% | R QA changepoint.md §11; 76 of 389 run days in §9 |
| 194 | Goal transitions on Mondays | 39 of 51 | Monday 39 | R QA changepoint.md §9 weekday table; D "Module C round 2" |
| 195 | Weekday adjustment | 1,513 of 1,543 kept; 32.6% of 1,572 | 1513 of 1543; 1572, 32.6% | R QA changepoint.md §11 |
| 196 | Table A4, village goal transitions | w = 0: 877, < 0.001, 0.005; w = 1: 1,240, 0.003, 0.269 | null2_p 0.000 and 0.003; null2w_p 0.005 and 0.269 | R QA changepoint.md §9 |
| 197 | Table A4, CHANGELOG goal category | w = 0: 315, 0.001, 0.002; w = 1: 474, 0.031, 0.039 | same | R QA changepoint.md §8, week-preserving table |
| 198 | Table A4, all CHANGELOG entries | w = 0: 1,235, 0.055, 0.081; w = 3: 1,929, 0.998, 0.998 | same | R QA changepoint.md §8, week-preserving table |
| 199 | Change points without CHANGELOG entry | 385, 56 run days | 385 of 2314, on 56 run days | R QA changepoint.md §13 |
| 200 | Without documented event | 208, 72 persistent, 28 run days | 208 (72 persistent), 28 run days | R QA changepoint.md §13 |
| 201 | Clusters of the 208 | 173 on 18 run days, 2026-07-30 to 2026-08-24; 30 on 9 run days, 2025-05-29 to 2025-06-13; 5 on 2026-04-08 | run-day table of 28 rows | R QA changepoint.md §13, **derived** sums by date range |
| 202 | Table A5 by level | agent 1,105, 238, 147; family 584, 79, 33; lexical 625, 68, 28 | same | R QA changepoint.md §13 |

### 4.6 Reliability of the measurements

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 203 | Time-rescaling | 267 of 393, 68% | 267 dimensions (0.68) of 393 | R QA hawkes.md §7 |
| 204 | Most probable parent equals tier-1 label | 15.0% [14.0, 16.0] of 16,851 | 0.150 [0.140, 0.160], 16,851 labels | R QA hawkes.md §8 |
| 205 | Latest message by someone else | 34.3% [32.1, 36.7] | 0.343 [0.321, 0.367] | R QA hawkes.md §8 |
| 206 | Most probable parent among other speakers | 38.6% [37.1, 40.5] | 0.386 [0.371, 0.405] | R QA hawkes.md §8 |
| 207 | Gain mostly from G51 | no number | most of the gain comes from G51 | D "Module A reporting choices", Explicit-reference check |
| 208 | Opportunity model, median Spearman | 0.128 [0.072, 0.187] over 43 windows, negative in 8 | median 0.128, range −0.532 to 0.422, negative in 8 of 43 | R QA hawkes.md §9 |
| 209 | Largest share change and ρ change, L and G | 7.1%; 0.198 | L1 max abs d other 0.071, d rho 0.198; L6 max share change 0.066, d rho 0.043; G15 max share 0.059, d rho 0.070 | R QA hawkes.md §10 |
| 210 | Table A6, KS test | 68% of 393 dimensions | 0.68 of 393 | R QA hawkes.md §7 |
| 211 | Rolling windows with ρ above 1, with masks | 5 of 92 | 5 of 92 rolling groups | D "Hawkes exposure by presence"; R QA hawkes.md §6 (1 + 0 + 1 + 2 + 1) |
| 212 | Without masks, goal windows above 1 | 17 of 44, 5 with intervals above 1 | 17 of 44 (5 with intervals above 1) | D "Hawkes exposure by presence"; P Results, Module A |
| 213 | Without masks, rolling windows above 1 | 22 of 92 | 22 of 92 | D "Hawkes exposure by presence" |
| 214 | Median self branching ratio of part-time agents with at least 21 events | 0.97 [0.90, 1.01] without, 0.29 [0.00, 0.49] with masks | falls from .97 to .29 | D "Hawkes exposure by presence" |
| 215 | Known-truth check | true ρ 0.92 or 0.93; 1.04 to 1.15 in 16 of 16; 0.89 to 0.97 | true rho .92 and .93; 16 of 16 replicates 1.04 to 1.15; presence model .89 to .97 | D "Hawkes exposure by presence" |
| 216 | V1 self share difference | +3.9% [2.6, 5.2] | 0.039 [0.026, 0.052] | R QA monitor_validation.md §3, §9 |
| 217 | V1 flagged and control messages | 21,184 and 20,824 | 21,184 flagged, 20,824 control, 64 realizations | R QA monitor_validation.md §3 |
| 218 | V1 self share, same hour | +2.8% [1.7, 4.0], 10,383 flagged | 0.028 [0.017, 0.040], 10,383 flagged | R QA monitor_validation.md §4 |
| 219 | V1 other-agent share | 2.0% [1.3, 2.6] lower; table −2.0% [−2.6, −1.3] | −0.020 [−0.026, −0.013] | R QA monitor_validation.md §3 |
| 220 | V1 other-agent share, same hour | −0.5% [−1.3, 0.5] | −0.005 [−0.013, 0.005] | R QA monitor_validation.md §4 |
| 221 | V1 conflicts, share on agents named in the conflict | +0.9% [0.3, 1.4], 1,956 flagged | co-involved 0.009 [0.003, 0.014], 1,956 flagged | R QA monitor_validation.md §3 |
| 222 | V2 conflict pairs | 62.0 [54.7, 68.1], 299 pairs | 0.620 [0.547, 0.681], 299 pairs | R QA monitor_validation.md §5 |
| 223 | V2 all flagged pairs | 64.6 [60.9, 65.6], 4,811 pairs | 0.646 [0.609, 0.656], 4,811 | R QA monitor_validation.md §5 |
| 224 | V2 once per distinct pair, conflicts | 55.9 [49.9, 61.1], 121 pairs | 0.559 [0.499, 0.611], 121 | R QA monitor_validation.md §5 |
| 225 | V2 once per distinct pair, all | 52.0 [49.9, 54.7], 595 pairs | 0.520 [0.499, 0.547], 595 | R QA monitor_validation.md §5 |
| 226 | Chance percentile | 50 | uniformly drawn pair has mean 0.5 | R QA monitor_validation.md §5 |
| 227 | Conclusions robust to the rule set | five; the rise separated from zero only under v2 | H2, late hazard, drops, beta-geometric and c′ hold in all; the rise is positive in all | R QA lineage_memory_v3.md §0; Q memory_post_switch_rise.csv |
| 228 | v1 first losses kept by v2 and v3 | 31.7%; 11.3% | 1,309,112 of 4,134,752 (31.7%); 467,255 (11.3%) | R QA lineage_memory_v3.md §0 |
| 229 | v1 time losses kept by v2 | 52.1% | time 358,913 (0.521) | R QA lineage_memory_v3.md §0 |
| 230 | Loss-detection F1 of v1, v2, v3 | 0.67 [0.45, 0.82]; 0.78 [0.55, 0.93]; 0.73 [0.52, 0.88] | same | Q memory_prelabel.md §12, §14 |
| 231 | Owner-kept audit units called lost | v2 7, v1 18, v3 14 of 44 | 7, 18, 14 of 44 | **derived** count from data/labels (audit_sample.json, memory_pairs_review.csv and the three rule label files), checked 2026-10-03; D "B1 label validation: results and choice of rule set" |
| 232 | Paired F1 differences | v2 − v1 +0.10 [+0.001, +0.23]; v3 − v2 −0.04 [−0.14, +0.05] | +0.104 [+0.001, +0.227]; −0.044 [−0.141, +0.050] | Q memory_prelabel.md §12 |
| 233 | Table 2, h1 | 52.2% [45.0, 58.1]; 34.0% [28.9, 38.4]; 46.3% [39.9, 51.4] | 0.522 [0.450, 0.581]; 0.340 [0.289, 0.384]; 0.463 [0.399, 0.514] | R QA lineage_memory.md §4; lineage_memory_v2.md §4; lineage_memory_v3.md §4 |
| 234 | Table 2, h2 | 50.6% [46.7, 53.7]; 35.3% [32.5, 37.7]; 43.9% [40.4, 47.0] | 0.506 [0.467, 0.537]; 0.353 [0.325, 0.377]; 0.439 [0.404, 0.470] | same |
| 235 | Table 2, h9+ | 4.5% [3.9, 5.4]; 2.5% [2.1, 3.0]; 2.5% [2.2, 2.9] | 0.045 [0.039, 0.054]; 0.025 [0.021, 0.030]; 0.025 [0.022, 0.029] | same |
| 236 | Table 2, h1 after the switch | 46.6% [39.4, 53.4]; 30.3% [24.9, 35.6]; 41.6% [35.2, 47.6] | 0.466 [0.394, 0.534]; 0.303 [0.249, 0.356]; 0.416 [0.352, 0.476] | same reports, regime:post |
| 237 | Table 2, h2 after the switch | 52.8% [48.4, 56.3]; 37.6% [34.3, 40.6]; 46.7% [42.8, 50.0] | 0.528 [0.484, 0.563]; 0.376 [0.343, 0.406]; 0.467 [0.428, 0.500] | same reports, regime:post |
| 238 | Table 2, paired h2 − h1 after the switch | +6.1 [−1.7, +14.8]; +7.3 [+1.5, +13.0]; +5.1 [−2.3, +13.1] | +0.061 [−0.017, +0.148]; +0.073 [+0.015, +0.130]; +0.051 [−0.023, +0.131] | Q memory_post_switch_rise.csv |
| 239 | Table 2, modified share | 23.3%; 5.2%; 6.6% | 0.233; 0.052; 0.066 | R QA lineage_memory_v3.md §0 |
| 240 | Table 2, c′ | 0.86 [0.80, 0.93]; 0.87 [0.82, 0.93]; 0.86 [0.80, 0.92] | 0.8634 [0.8016, 0.9335]; 0.8748 [0.8180, 0.9269]; 0.8602 [0.7995, 0.9187] (Q memory_v1_v2_v3.csv) | R QA lineage_memory_v3.md §0 |
| 241 | Table 2, unit-trials | 14,220,326; 37,881,746; 25,785,525 | same | R QA lineage_memory.md §4; lineage_memory_v2.md §4; lineage_memory_v3.md §4 |
| 242 | v2 loss precision and recall | 74% [49, 94]; 82% [55, 100] | 0.74 [0.49, 0.94]; 0.82 [0.55, 1.00] | Q memory_prelabel.md §12, rules v2 |
| 243 | Loss F1 of the comparison raters and Claude | 0.63 to 0.71; 0.80 [0.57, 0.93] | Qwen3-14B 0.69, Qwen3.5-122B 0.70, gpt-oss-120b 0.71, Gemini 3.1 Pro 0.63; Claude 0.80 [0.57, 0.93] | Q memory_prelabel.md §12 |
| 244 | Claude against the owner, B1 | 75.3% [62, 87] | 0.753 (0.62 to 0.87), weighted to the 277 rows of the blind sheet | Q memory_prelabel.md §13 |
| 245 | Determined-path parent accuracy on synthetic trees | 95.4% [95.1, 95.7] against 79.2% [78.8, 79.6], 100 replicates | determined_parent_accuracy 0.954 [0.951, 0.957]; parent_accuracy_transmission 0.792 [0.788, 0.796] | Q lineage_trees.md §6.1, §9 |
| 246 | Claude against the owner, B2 | 9 of 15 | 9 of 15 rows (60%) | Q lineage_trees.md §4.1 |
| 247 | Comparison raters on the B2 audit | 7 to 12 of 15 | Qwen3-14B 7, Gemini 3.1 Pro 8, Qwen3.5-122B 10, gpt-oss-120b 12 of 15 | Q trees_parent_label_metrics.csv |
| 248 | Required checks passing | 15 over 256 families of 16 tasks | 15 of 15; 256 families | R QA swarmsim_d1.md Summary |
| 249 | Speedup to half coverage at 64 agents | 31.7 [31.5, 31.9] against 33 | 31.7 (31.5 to 31.9); blog 33 | R QA swarmsim_d1.md Summary |
| 250 | Finish time at 64 agents | 0.081 T₁ [0.079, 0.084] against about 0.10 | 0.0812 (0.0787 to 0.0836) | R QA swarmsim_d1.md Summary |
| 251 | Speedup to best score 0.8 | 18.1 [17.8, 18.4] against 16 | 18.1 (17.8 to 18.4) | R QA swarmsim_d1.md Summary |
| 252 | Percentile of the blog family | 80th to 86th | g50 82%, finish 32 83%, finish 64 86%, λ at 64 80% | R QA swarmsim_d1.md Deviations; D "Module D1" |
| 253 | Table A8, coverage check | 256 of 256 families | ours 1, n 256 | R QA swarmsim_d1.md reproduction table |
| 254 | Table A8, deviations | 3.9%, 13.1%, 14.4%, 18.8%, 5.6%, at most 0.1%, 1.1%, at most 0.1% | 0.0391, 0.131, 0.144, 0.188, 0.0562, max 0.00113, 0.0108, max 0.000611 | R QA swarmsim_d1.md reproduction table |
| 255 | Table A8, finish time at 32 agents | 0.086 [0.083, 0.088] | 0.0856 [0.0834, 0.0879] | same |
| 256 | Table A8, finish ratio | 0.944 [0.936, 0.951] | 0.944 [0.936, 0.951] | same |
| 257 | Table A8, λ standard at 4 to 16 agents | 0.889 to 0.914 against 0.89 to 0.92 | 0.889, 0.914, 0.913 | same |
| 258 | Table A8, λ standard at 64 agents | 0.831 [0.830, 0.832] against 0.84 | 0.831 [0.83, 0.832] | same |
| 259 | Table A8, λ recursive | 0.885 to 0.931 against 0.88 to 0.93 | 0.886, 0.917, 0.931, 0.926, 0.885 | same |
| 260 | GUI writes without focus, rules v2 | 52,392 of 66,115, 79.2% | 52,392 (79.2%) of 66,115 | R QA swarmsim_d2_d4.md §2; R QA swarmsim_gui_gap.md |
| 261 | Median gap per goal | 30.9%; 84.7% before 2025-10; 13.2% from 2025-10 | 0.309; 0.847; 0.132 | R QA swarmsim_d2_d4.md §8b |
| 262 | Checks passing on the subsets | 30 of 30, v2 and v1 | 30 of 30 under v2 and under v1 | D "D2 to D4: rules v2 as main"; G work log 10/2 00:04 |
| 263 | Gap below 10% | 13 goals; 2.88 parents; continuation 66.7% [59.2, 74.1] | 13; 2.88; 0.667 [0.592, 0.741] | R QA swarmsim_d2_d4.md §8b |
| 264 | Change from v1 to v2 | at most 0.005 | D3 statistics and D4 rates move by at most 0.005 | D "D2 GUI focus gap: diagnosis and touch rules v2" |
| 265 | Table A9, all goals | 51; 2.67, 1.74; 60.0%, 19.8%; 60.2% [53.5, 67.2] | 2.67, 1.74; 0.6, 0.198; 0.602 [0.535, 0.672] | R QA swarmsim_d2_d4.md §8b (§8 gives [0.534, 0.674] from another bootstrap run) |
| 266 | Table A9, gap below 20% | 24; 2.74, 1.74; 60.9%, 20.1%; 62.7% [55.7, 69.7] | 2.74, 1.74; 0.609, 0.201; 0.627 [0.557, 0.697] | R QA swarmsim_d2_d4.md §8b |
| 267 | Table A9, gap below 10% | 13; 2.88, 1.74; 62.7%, 20.3%; 66.7% [59.2, 74.1] | 2.88, 1.74; 0.627, 0.203; 0.667 [0.592, 0.741] | same |
| 268 | Table A9, touch share at least 80% | 17; 2.07, 1.73; 48.1%, 19.2%; 58.3% [52.1, 65.8] | 2.07, 1.73; 0.481, 0.192; 0.583 [0.521, 0.658] | same |
| 269 | Table A9, goals from 2025-10 | 36; 2.68, 1.74; 60.2%, 19.9%; 60.9% [54.4, 68.1] | 2.68, 1.74; 0.602, 0.199; 0.609 [0.544, 0.681] | same |
| 270 | Table A9, without GUI-heavy early goals | 40; 2.68, 1.74; 60.1%, 19.9%; 60.7% [54.0, 67.5] | 2.68, 1.74; 0.601, 0.199; 0.607 [0.540, 0.675] | same |
| 271 | Table A9 caption, above the 97.5th percentile | every observed value | quantile 1 in every subset for both statistics | same |

## 5. Limitations

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 272 | Time-rescaling rejection | 68% of 393 | 0.68 of 393 | R QA hawkes.md §7 |
| 273 | Self-share bias | about 0.05; −0.048 and −0.051 | mean self-share bias −0.048 of final windows; median bootstrap mean minus estimate −0.051 for self | R QA hawkes.md §3 and §4; D "Module A reporting choices" |
| 274 | Explicit-reference check | 15.0% against 34.3% | 0.150 against 0.343 | R QA hawkes.md §8 |
| 275 | Format variants on blind-judged units | 17 of 50 | in 17 of the 50 units | D "B1 pre-label re-check", Third judge |
| 276 | Labels behind the B2 choice | 45; owner 14, Claude 31 | composite 45, owner 14 | Q lineage_trees.md §4.1, **derived** 45 − 14 = 31 |
| 277 | Recency rules against the posterior | 71.1% [57.3, 84.2] against 66.7% [52.2, 79.4]; 95.0% [94.4, 95.5] against 86.9% [86.1, 87.8] | composite latest 0.711 [0.573, 0.842], time+content 0.667 [0.522, 0.794]; name_tier1 latest_other_agent_message 0.950 [0.944, 0.955], time+content 0.869 [0.861, 0.878] | Q lineage_trees.md §4 |
| 278 | GUI writes reaching no artifact | 79.2% | 79.2% | R QA swarmsim_d2_d4.md §2 |
| 279 | Bash use before October 2025 | no number | agents rarely used the bash tool before October 2025 | D "D2 GUI focus gap: diagnosis and touch rules v2" |
| 280 | Median focus gap before 2025-10 | 84.7% | 0.847 | R QA swarmsim_d2_d4.md §8b |

## 6. Reproducibility

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 281 | Revision and seed | 838b4150303ca8228e8edb432d8b8ccae353d258; 20261003 | same | CFG; D "Random seed", "Pin the dataset revision" |
| 282 | Python and vLLM versions | 3.11; vLLM 0.19 | Python 3.11 (pyproject); vLLM pinned to 0.19.0, re-check runs on 0.19.1 | pyproject.toml; D "B1 label validation: local pre-labelling", "B1 pre-label re-check" |
| 283 | Ingest | about 5 min, 8 CPUs | Slurm job 575852 about 5 minutes; cpus-per-task 8 | G 4.1-2; scripts/ingest.sbatch (the ingest QA report records no runtime) |
| 284 | Build-events | 55 s, 8.7 GB | Runtime 55 s, peak RSS 8.7 GB | R QA build_events.md header |
| 285 | Module A stages | acceptance 224 s; bootstrap shards 605 to 2,368 s; matched 1,055 s and 1,066 s; 16 workers | accept 224 s; boot shards 605 to 2368 s; matched 1055 and 1066 s; workers 16 | R QA hawkes.md §13 |
| 286 | Monitor fetch and validation | about 22 min; 14 s | fetched 02:50:46 to 03:12:16 UTC; monitor_hawkes in 14 s | R QA monitor.md header; R QA monitor_validation.md header |
| 287 | B1 runtimes | 687 s, 1,214 s, 1,900 s; 1,555 s first extraction; about 1 min for the paired test | 687 s (v1), 1214 s (v2), 1900 s (v3); extraction 37 s + 1518 s; paired test about 1 min (srun of 2026-10-03) | R QA lineage_memory.md, lineage_memory_v2.md, lineage_memory_v3.md headers |
| 288 | B2 units | 24 min on 48 CPUs | 全量 24 分钟（作业 587322，48 CPU） | G B2 units row |
| 289 | B2 trees | 1,577 s | done in 1577 s (46 + 22 + 56 + 584 + 298 + 36 + 504 s) | logs/avsd_lineage_trees-630077.out; Q lineage_trees.md §12 |
| 290 | Module C | 144 s, 16 processes | 144 s on 16 processes | R QA changepoint.md header |
| 291 | Module D1 | 77 s, 32 processes | 77 s wall on 32 processes | R QA swarmsim_d1.md Summary (G gives 78 s) |
| 292 | Modules D2 to D4 | 109 s and 108 s, 48 processes, about 2 min of extraction | 109 s (v2), 108 s (v1), 48 processes, about 2 minutes more | R QA swarmsim_d2_d4.md and swarmsim_d2_d4_v1.md Summary |
| 293 | γ for a run without the label sheets | γ = 0.25 | gamma 0.25 | Q lineage_trees.md §1 |

## 7. Acknowledgements and citation

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 294 | Dataset citation | AI Digest, "AI Village dataset", 2026 | same | SPEC 0.2 |
| 295 | Blog date | 2026-09-27 | 2026-09-27 | SPEC 8.1 |
| 296 | References of the related work | as listed | verified list of 2026-10-01 | P Literature check and Related work to cite; method references from SPEC appendix D |

## Figure captions

Rows for numbers that only the figure captions state. Numbers that a caption repeats from the text are in the rows above.

| # | Claim | Written | Source value | Source |
|---|---|---|---|---|
| 297 | Figure 1, windows in which self-excitation is the largest source | 24 of the 42 | share_self is the largest of the five shares in 24 of 42 accepted windows | Q hawkes_windows.csv, **derived** |
| 298 | Figure 2, windows with ρ below 1 | 39 of the 42 | rho < 1 in 39 of 42 accepted windows | Q hawkes_windows.csv; row 5 |
| 299 | Figure 3, agents behind the lines | 45 standard agents, four families, one Claude Code agent | 46 agents; Anthropic 16, OpenAI 14, Google 5, Other 11 | R QA build_events.md §11; **derived** 46 − 1 |
| 300 | Figure 7, test in each channel | p = 0.002 in all three | chat to memory, chat to chat and chat to search answer p 0.002 | Q lineage_trees.md §6.1; rows 129 and 141 |
| 301 | Figure 8, T_k above the linear trend | from k = 3 on, with whole intervals | lower bounds of the mean 70.1, 116.7, 122.3 against the trend 65.8, 76.6, 87.4; of the variance 35,960, 62,122, 62,079 against 34,944, 42,653, 50,361 | Q trees_h1_tk.csv, **derived** from the k rows and the linear fit |
| 302 | Figure 11, generator replicates and goals | 64; 51 | gen_n 64, n_goals 51 | Q depgraph_structure.csv, scope pooled, edges all |
| 303 | Figure 1, windows where the baseline exceeds half | six, between December 2025 and March 2026 | share_baseline > 0.5 in 7 accepted windows, 6 of them from g23 (2025-12-15) to g35 rest (2026-03-20) | Q hawkes_windows.csv |
| 304 | Hazards before the switch, rule set v2 | 44.7% [41.8, 48.0]; 26.8% [23.8, 29.0] | h1 0.447418 [0.418286, 0.479736]; h2 0.267728 [0.238215, 0.290128] | Q memory_h2_v2.csv, scope regime:pre, All standard |
| 305 | Figure 6, observed over expected further acquisitions | between a quarter and a half from generation 1 on | 0.505, 0.270, 0.318, 0.344 for generations 1 to 4 | Q trees_generations.csv, **derived** offspring_mean / offspring_expected |
| 306 | Figure 12, rise of the blog's cost model | about ninefold | blog_vs_layer0 9.0722 in the deepest bin (0.8, 1] | Q depgraph_cost_by_layer.csv, edges all, relative_depth |
| 307 | Figure 14, set sizes | 389 run days; 1,543 change points; 51 transitions | column totals 389, 1543, 51 | Q changepoint.md §9, weekday table |
| 308 | Figure 15, v2 against v1 | more precision at a similar recall | precision 0.7409 [0.4853, 0.9377] against 0.5487 [0.3259, 0.7304]; recall 0.8190 against 0.8725 | Q memory_label_metrics.csv, weighted, label loss |
| 309 | Figure 16, quantitative checks | 14 of the 15 | 15 required checks, one of them qualitative (coverage earlier at every larger swarm, 256 of 256 families) | Q swarmsim_reproduction.csv, required rows |
