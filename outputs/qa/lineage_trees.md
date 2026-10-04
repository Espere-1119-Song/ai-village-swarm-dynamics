# QA: module B2, transmission trees between agents (SPEC 6.4)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

All numbers below are aggregates. No anchor values, message text, 4-grams or human names appear in this report or in outputs/tables/trees_*.csv. Units are shown by keyed ids. A URL unit shows its registrable domain only when at least 3 units share it (subdomains hold account names on hosting platforms, and personal sites sit in the long tail); the others show "other".

## 1. Settings

| Setting | Value |
|---|---|
| B1 fact-presence rule set | v2 (B1's main rule set since 2026-10-03; it sets the memory presence of re-mentions, so agent-level numbers change only through the KDE fitted on single-candidate edges) |
| Exposure rule (chat) | main |
| Independent observation rule | precede |
| L_B | 3.0 run days |
| Minimum edges per reported generation | 30 |
| gamma | 0.25 (chosen with the time term on the composite labels: parent accuracy, then mean log posterior) |
| Time term | empirical KDE per kernel key (chosen on the labels) |
| Posterior draws | 200 |
| Cluster-bootstrap replicates | 500 |
| H1 permutations (MAP; draws) | 499; 99 |
| Seed | 20,261,003 |

## 2. Information units and occurrences

We read 181,255 chat messages of agents and humans and 10,156 search-history answers. Typed candidates: 2,171,623; gram message sets: 270,599. Units above the size cap (200 occurrences) were left out: 435 typed and 2 gram units.

We kept 387,996 units with 3,144,784 occurrences: chat 1,167,702, memory 1,727,610, search 249,472. Turn observations (env_i hits): 26,096,608.

| Unit type | Units | Occurrences | Mean agents | Units with edges | Edges | Independent | Units with depth >= 2 | Max generation |
|---|---|---|---|---|---|---|---|---|
| all | 387,996 | 3,144,784 | 5.444 | 280,973 | 815,594 | 156,749 | 70,758 | 7 |
| gram | 222,474 | 1,379,107 | 4.379 | 146,981 | 352,311 | 41,893 | 47,712 | 4 |
| number | 88,342 | 965,797 | 7.374 | 71,738 | 248,432 | 63,912 | 12,671 | 7 |
| time | 18,719 | 182,832 | 6.818 | 11,212 | 27,353 | 2,311 | 1,410 | 5 |
| org | 17,558 | 203,855 | 6.349 | 14,838 | 51,848 | 19,275 | 2,967 | 6 |
| person | 9,830 | 116,487 | 6.710 | 8,171 | 29,357 | 12,188 | 1,525 | 6 |
| url | 9,251 | 77,992 | 5.531 | 9,017 | 37,675 | 1,667 | 1,071 | 5 |
| work_of_art | 8,162 | 75,567 | 5.803 | 7,495 | 30,394 | 4,360 | 1,432 | 6 |
| percent | 5,422 | 40,161 | 4.990 | 4,494 | 12,649 | 1,260 | 518 | 5 |
| gpe | 2,221 | 30,440 | 7.506 | 1,801 | 6,768 | 4,167 | 357 | 5 |
| product | 2,100 | 24,269 | 6.660 | 1,758 | 6,102 | 2,819 | 380 | 5 |
| money | 1,743 | 13,232 | 4.328 | 1,522 | 4,138 | 222 | 193 | 3 |
| date | 1,127 | 25,185 | 10.897 | 983 | 5,575 | 2,224 | 347 | 7 |
| email | 671 | 6,742 | 4.918 | 654 | 2,076 | 201 | 111 | 5 |
| event | 354 | 2,940 | 5.234 | 287 | 846 | 246 | 58 | 6 |
| phone | 22 | 178 | 4.500 | 22 | 70 | 4 | 6 | 2 |

Acceptance (SPEC 6.4.6): 280,973 units have an inferred tree with at least one transmission edge (required: 100).

## 3. Time term

| Kernel key | Single-candidate edges | Fitted on | Edges in fit | Median (active h) | IQR (active h) |
|---|---|---|---|---|---|
| chat>chat:other | 99,671 | own | 99,671 | 0.081 | 0.017 to 0.932 |
| chat>chat:self | 36,020 | own | 36,020 | 0.082 | 0.023 to 0.687 |
| chat>human | 706 | own | 706 | 0.211 | 0.021 to 2.742 |
| chat>memory:other | 366,727 | own | 366,727 | 0.144 | 0.061 to 0.347 |
| chat>memory:self | 77,809 | own | 77,809 | 0.058 | 0.016 to 0.175 |
| memory>chat | 83,897 | own | 83,897 | 10.935 | 0.162 to 147.343 |
| search>chat | 1,070 | own | 1,070 | 0.048 | 0.007 to 2.145 |
| search>memory | 2,440 | own | 2,440 | 0.063 | 0.008 to 0.312 |
| history>search | 101,367 | own | 101,367 | 0.910 | 0.157 to 4.462 |
| env>chat | 60,407 | own | 60,407 | 1.121 | 0.051 to 8.330 |
| env>memory | 122,728 | own | 122,728 | 1.186 | 0.147 to 8.028 |

Candidate rows: 6,461,545. env candidates dropped because an earlier exposure existed: 266,750.

### 3.1 Module A kernels

outputs/tables/hawkes_kernels.parquet as read by this run: modified 2026-10-01 11:14 ET, sha256 dfce3c794672.

The main run uses the KDE alone, chosen on the labels (section 4.1). The counts below show the edges that the module A kernel covers, for the sensitivity run with it.

Time term by candidate edge of the main run (6,461,545 edges): module A kernel for 1,928,522 (29.8%), the KDE for the rest: not chat 3,017,328, cross day 1,368,346, no window 18,490, not identified 43,296, beyond L 85,563.

| Window | Room | Dates | Identified classes | Candidate chat edges | Module A kernel | KDE: cross-day | KDE: no window | KDE: not identified | KDE: tau > L | MAP chat edges | MAP: module A kernel |
|---|---|---|---|---|---|---|---|---|---|---|---|
| g35-39 | best | 2026-03-16 to 2026-05-01 | other,self,system | 54,449 | 24,073 (44.2%) | 29,099 | 0 | 50 | 1,227 | 7,255 | 5,868 (80.9%) |
| g41-44 | best | 2026-05-11 to 2026-05-29 | other,self | 9,232 | 4,398 (47.6%) | 4,723 | 0 | 9 | 102 | 2,183 | 1,773 (81.2%) |
| g45-47 | best | 2026-06-01 to 2026-06-19 | human,other,self | 11,916 | 6,211 (52.1%) | 4,864 | 0 | 0 | 841 | 2,984 | 2,370 (79.4%) |
| g50 | best | 2026-06-29 to 2026-07-03 | other,self | 17,279 | 12,609 (73.0%) | 1,733 | 0 | 5 | 2,932 | 2,815 | 2,637 (93.7%) |
| g01 | general | 2025-04-02 to 2025-05-09 | human,other,self | 63,761 | 40,705 (63.8%) | 23,051 | 0 | 0 | 5 | 8,332 | 7,003 (84.0%) |
| g02-03 | general | 2025-05-10 to 2025-05-14 | human,other,self | 24,245 | 20,656 (85.2%) | 3,589 | 0 | 0 | 0 | 4,343 | 4,056 (93.4%) |
| g04 | general | 2025-05-15 to 2025-06-18 | human,other,self | 120,529 | 66,291 (55.0%) | 54,238 | 0 | 0 | 0 | 11,469 | 9,850 (85.9%) |
| g05-07 | general | 2025-06-19 to 2025-07-17 | human,other,self | 34,308 | 19,013 (55.4%) | 15,295 | 0 | 0 | 0 | 5,488 | 4,637 (84.5%) |
| g08 | general | 2025-07-18 to 2025-08-12 | human,other,self | 43,618 | 20,452 (46.9%) | 23,166 | 0 | 0 | 0 | 6,313 | 5,049 (80.0%) |
| g09 | general | 2025-08-13 to 2025-08-15 | other,self | 9,188 | 5,853 (63.7%) | 3,308 | 0 | 27 | 0 | 1,544 | 1,395 (90.3%) |
| g10 | general | 2025-08-18 to 2025-08-22 | other,self | 34,315 | 13,760 (40.1%) | 20,522 | 0 | 33 | 0 | 2,795 | 2,339 (83.7%) |
| g11 | general | 2025-08-25 to 2025-08-29 | human,other,self | 68,213 | 30,455 (44.6%) | 37,758 | 0 | 0 | 0 | 5,992 | 5,213 (87.0%) |
| g12 | general | 2025-09-01 to 2025-09-05 | human,other,self | 47,750 | 35,425 (74.2%) | 12,325 | 0 | 0 | 0 | 8,060 | 6,949 (86.2%) |
| g13 | general | 2025-09-08 to 2025-09-19 | human,other,self | 62,865 | 42,713 (67.9%) | 20,152 | 0 | 0 | 0 | 7,818 | 6,632 (84.8%) |
| g14 | general | 2025-09-22 to 2025-09-26 | other,self | 20,904 | 10,899 (52.1%) | 10,004 | 0 | 1 | 0 | 2,667 | 2,189 (82.1%) |
| g15 | general | 2025-09-29 to 2025-10-03 | other,self | 24,572 | 14,223 (57.9%) | 10,334 | 0 | 15 | 0 | 4,367 | 3,691 (84.5%) |
| g16 | general | 2025-10-06 to 2025-10-10 | other,self | 14,886 | 9,664 (64.9%) | 5,218 | 0 | 4 | 0 | 2,746 | 2,392 (87.1%) |
| g17 | general | 2025-10-13 to 2025-10-17 | other,self | 15,853 | 8,712 (55.0%) | 7,123 | 0 | 18 | 0 | 2,573 | 2,196 (85.3%) |
| g18 | general | 2025-10-20 to 2025-10-31 | human,other,self | 177,294 | 139,946 (78.9%) | 33,592 | 0 | 0 | 3,756 | 18,581 | 16,669 (89.7%) |
| g19 | general | 2025-11-03 to 2025-11-14 | other,self | 106,298 | 79,062 (74.4%) | 26,579 | 0 | 23 | 634 | 15,111 | 13,267 (87.8%) |
| g20 | general | 2025-11-17 to 2025-11-28 | other,self | 137,380 | 74,817 (54.5%) | 60,915 | 0 | 84 | 1,564 | 15,792 | 13,823 (87.5%) |
| g21 | general | 2025-12-01 to 2025-12-05 | other,self | 91,653 | 64,904 (70.8%) | 26,234 | 0 | 26 | 489 | 9,927 | 8,884 (89.5%) |
| g22 | general | 2025-12-08 to 2025-12-12 | other,self | 55,790 | 31,469 (56.4%) | 23,811 | 0 | 12 | 498 | 6,809 | 5,816 (85.4%) |
| g23 | general | 2025-12-15 to 2025-12-19 | other,self | 106,511 | 34,959 (32.8%) | 70,476 | 0 | 4 | 1,072 | 7,781 | 6,105 (78.5%) |
| g24-25 | general | 2025-12-22 to 2026-01-02 | other,self | 120,946 | 66,932 (55.3%) | 52,962 | 0 | 43 | 1,009 | 16,116 | 13,623 (84.5%) |
| g26 | general | 2026-01-05 to 2026-01-09 | other,self | 41,950 | 30,149 (71.9%) | 11,064 | 0 | 0 | 737 | 7,629 | 6,784 (88.9%) |
| g27 | general | 2026-01-12 to 2026-01-23 | other,self | 132,702 | 62,716 (47.3%) | 68,170 | 0 | 44 | 1,772 | 16,720 | 13,387 (80.1%) |
| g28 | general | 2026-01-26 to 2026-01-30 | other,self | 88,668 | 65,270 (73.6%) | 21,904 | 0 | 29 | 1,465 | 12,171 | 10,768 (88.5%) |
| g29 | general | 2026-02-02 to 2026-02-06 | other | 69,154 | 17,744 (25.7%) | 36,432 | 0 | 14,233 | 745 | 8,065 | 2,717 (33.7%) |
| g30 | general | 2026-02-09 to 2026-02-13 | other,self | 113,588 | 62,623 (55.1%) | 49,362 | 0 | 17 | 1,586 | 12,020 | 10,355 (86.1%) |
| g31 | general | 2026-02-16 to 2026-02-20 | other,self,system | 85,857 | 54,156 (63.1%) | 31,034 | 0 | 59 | 608 | 14,544 | 12,386 (85.2%) |
| g32 | general | 2026-02-23 to 2026-02-27 | other,self | 159,740 | 97,305 (60.9%) | 61,178 | 0 | 16 | 1,241 | 16,215 | 13,779 (85.0%) |
| g33-34 | general | 2026-03-02 to 2026-03-13 | human,other,self | 147,542 | 84,650 (57.4%) | 61,446 | 0 | 0 | 1,446 | 22,699 | 18,859 (83.1%) |
| g48-49 | general | 2026-06-22 to 2026-06-26 | other,self | 9,988 | 7,599 (76.1%) | 2,182 | 0 | 1 | 206 | 1,550 | 1,390 (89.7%) |
| g51 | general | 2026-07-06 to 2026-09-18 | human,other,self,system | 620,072 | 323,616 (52.2%) | 244,731 | 0 | 0 | 51,725 | 103,476 | 84,820 (82.0%) |
| g35 | rest | 2026-03-16 to 2026-03-20 | other,self | 15,920 | 8,926 (56.1%) | 6,859 | 0 | 4 | 131 | 4,508 | 3,373 (74.8%) |
| g36-37 | rest | 2026-03-23 to 2026-04-01 | other,self,system | 32,161 | 16,589 (51.6%) | 15,069 | 0 | 12 | 491 | 5,085 | 4,406 (86.6%) |
| g38-39 | rest | 2026-04-02 to 2026-05-01 | other,self,system | 102,280 | 53,820 (52.6%) | 47,348 | 0 | 11 | 1,101 | 16,437 | 14,193 (86.3%) |
| g41-43 | rest | 2026-05-11 to 2026-05-25 | other,self | 77,735 | 50,494 (65.0%) | 26,555 | 0 | 67 | 619 | 13,264 | 12,018 (90.6%) |
| g44-45 | rest | 2026-05-26 to 2026-06-05 | other,self | 34,806 | 22,111 (63.5%) | 12,109 | 0 | 15 | 571 | 7,041 | 6,223 (88.4%) |
| g46-47 | rest | 2026-06-08 to 2026-06-19 | other,self | 131,455 | 78,298 (59.6%) | 47,642 | 0 | 19 | 5,496 | 17,038 | 15,098 (88.6%) |
| g50 | rest | 2026-06-29 to 2026-07-03 | other,self | 24,085 | 14,255 (59.2%) | 8,331 | 0 | 5 | 1,494 | 4,213 | 3,608 (85.6%) |
| g40 | universe-coordination | 2026-05-04 to 2026-05-08 |  | 52,541 | 0 (0.0%) | 24,131 | 0 | 28,410 | 0 | 7,552 | 0 (0.0%) |
| none | focus |  |  | 22,926 | 0 (0.0%) | 7,093 | 15,833 | 0 | 0 | 7,082 | 0 (0.0%) |
| none | side-room |  |  | 19 | 0 (0.0%) | 0 | 19 | 0 | 0 | 8 | 0 (0.0%) |
| none | general |  |  | 4,398 | 0 (0.0%) | 2,918 | 1,480 | 0 | 0 | 637 | 0 (0.0%) |
| none | rest |  |  | 5 | 0 (0.0%) | 5 | 0 | 0 | 0 | 1 | 0 (0.0%) |
| none | fable-5-onboarding |  |  | 47 | 0 (0.0%) | 23 | 24 | 0 | 0 | 8 | 0 (0.0%) |
| none | showcase-live |  |  | 296 | 0 (0.0%) | 197 | 99 | 0 | 0 | 69 | 0 (0.0%) |
| none | voted-out |  |  | 2,527 | 0 (0.0%) | 1,492 | 1,035 | 0 | 0 | 520 | 0 (0.0%) |
| all | all |  |  | 3,444,217 | 1,928,522 (56.0%) | 1,368,346 | 18,490 | 43,296 | 85,563 | 478,413 | 388,590 (81.2%) |

Chat edges are chat-to-chat candidate edges (an agent child, a chat parent). A window is found by the child's room and PT date together (group = room name, date_start <= date <= date_end). Window "none" counts edges in a room with no goal window on the child's date. The KDE also serves cross-day edges, unidentified source classes (expected_children < 50) and intervals beyond L. MAP columns count the chat edges chosen as MAP parents. Windows without chat edges are left out here; trees_time_term.csv has every window.

## 4. Labels, gamma and ablation (SPEC 6.4.5)

Explicit references: 44,349. Usable cases (the labelled message is a candidate parent for a shared unit): 31,870 (name_tier1 10,871, name_tier2 14,089, quote_tier1 6,806, quote_tier2 0).

| gamma | Tier-1 name cases | Mean log P (KDE only) | Accuracy (KDE only) | Mean log P (module A + KDE) | Accuracy (module A + KDE) |
|---|---|---|---|---|---|
| 0.000 | 10,871 | -0.339 | 0.881 | -0.778 | 0.860 |
| 0.250 | 10,871 | -0.375 | 0.869 | -0.811 | 0.857 |
| 0.500 | 10,871 | -0.457 | 0.859 | -0.886 | 0.851 |
| 0.750 | 10,871 | -0.556 | 0.852 | -0.979 | 0.845 |
| 1 | 10,871 | -0.666 | 0.846 | -1.083 | 0.838 |
| 1.500 | 10,871 | -0.903 | 0.840 | -1.307 | 0.831 |
| 2 | 10,871 | -1.153 | 0.835 | -1.546 | 0.826 |
| 3 | 10,871 | -1.674 | 0.828 | -2.048 | 0.818 |
| 4 | 10,871 | -2.210 | 0.824 | -2.568 | 0.814 |
| 6 | 10,871 | -3.303 | 0.818 | -3.633 | 0.812 |

We use gamma = 0.25 (chosen with the time term on the composite labels: parent accuracy, then mean log posterior).

### 4.1 Time term and gamma chosen on the labels

Label set composite (45 cases that match a candidate). composite takes the owner's label where the owner answered the row (none included) and the blind label from Claude elsewhere; owner and claude are the two sets alone. Claude and the owner agree on 9 of 15 rows (60%; an ENV candidate counts as env). Chosen: KDE only, gamma = 0.250.

Best time term and gamma by label set: owner KDE only, gamma 0.250; claude module A kernel + KDE, gamma 0.250; composite KDE only, gamma 0.250.

| Time term | gamma | Label set | Cases | Accuracy | Mean log P | Best for the set |
|---|---|---|---|---|---|---|
| module A kernel + KDE | 0.000 | owner | 14 | 0.571 | -5.287 |  |
| module A kernel + KDE | 0.000 | claude | 45 | 0.689 | -0.876 |  |
| module A kernel + KDE | 0.000 | composite | 45 | 0.667 | -2.160 |  |
| module A kernel + KDE | 0.250 | owner | 14 | 0.500 | -5.261 |  |
| module A kernel + KDE | 0.250 | claude | 45 | 0.733 | -0.798 | yes |
| module A kernel + KDE | 0.250 | composite | 45 | 0.667 | -2.116 |  |
| KDE only | 0.000 | owner | 14 | 0.714 | -0.807 |  |
| KDE only | 0.000 | claude | 45 | 0.578 | -0.849 |  |
| KDE only | 0.000 | composite | 45 | 0.644 | -0.831 |  |
| KDE only | 0.250 | owner | 14 | 0.714 | -0.783 | yes |
| KDE only | 0.250 | claude | 45 | 0.622 | -0.770 |  |
| KDE only | 0.250 | composite | 45 | 0.667 | -0.786 | yes |

Accuracy is the expected top-1 accuracy of the posterior (ties split evenly), on all rows of a set (no cross-fitting; the choice and its evaluation use the same labels). Every grid point: trees_label_selection.csv.

| Label set | Method | Cases | Child messages | Accuracy [95% CI] | Mean log P | Mean candidates |
|---|---|---|---|---|---|---|
| name_tier1 | time | 10,871 | 5,848 | 0.881 [0.874, 0.891] | -0.339 | 5.750 |
| name_tier1 | content | 10,871 | 5,848 | 0.712 [0.702, 0.723] | -0.860 | 5.750 |
| name_tier1 | time+content | 10,871 | 5,848 | 0.869 [0.861, 0.878] | -0.375 | 5.750 |
| name_tier1 | time+content_other_agents | 10,871 | 5,848 | 0.894 [0.887, 0.902] | -0.312 | 5.750 |
| name_tier1 | uniform | 10,871 | 5,848 | 0.582 [0.574, 0.591] | -0.941 | 5.750 |
| name_tier1 | latest | 10,871 | 5,848 | 0.875 [0.867, 0.884] | n/a | 5.750 |
| name_tier1 | latest_other_agent_message | 10,871 | 5,848 | 0.950 [0.944, 0.955] | n/a | 5.750 |
| name_tier1 | time_module_a | 10,871 | 5,848 | 0.860 [0.851, 0.868] | -0.778 | 5.750 |
| name_tier1 | time+content_module_a | 10,871 | 5,848 | 0.857 [0.849, 0.866] | -0.811 | 5.750 |
| name_tier1 | time+content_other_agents_module_a | 10,871 | 5,848 | 0.869 [0.861, 0.878] | -0.750 | 5.750 |
| name_tier2 | time | 14,089 | 7,782 | 0.822 [0.813, 0.830] | -0.483 | 7.938 |
| name_tier2 | content | 14,089 | 7,782 | 0.656 [0.645, 0.666] | -1.100 | 7.938 |
| name_tier2 | time+content | 14,089 | 7,782 | 0.805 [0.795, 0.813] | -0.612 | 7.938 |
| name_tier2 | time+content_other_agents | 14,089 | 7,782 | 0.830 [0.821, 0.838] | -0.474 | 7.938 |
| name_tier2 | uniform | 14,089 | 7,782 | 0.556 [0.548, 0.565] | -1.078 | 7.938 |
| name_tier2 | latest | 14,089 | 7,782 | 0.800 [0.792, 0.809] | n/a | 7.938 |
| name_tier2 | latest_other_agent_message | 14,089 | 7,782 | 0.874 [0.867, 0.880] | n/a | 7.938 |
| name_tier2 | time_module_a | 14,089 | 7,782 | 0.810 [0.802, 0.818] | -0.790 | 7.938 |
| name_tier2 | time+content_module_a | 14,089 | 7,782 | 0.805 [0.796, 0.813] | -0.912 | 7.938 |
| name_tier2 | time+content_other_agents_module_a | 14,089 | 7,782 | 0.821 [0.812, 0.829] | -0.781 | 7.938 |
| quote_tier1 | time | 6,806 | 2,826 | 0.834 [0.821, 0.846] | -0.372 | 3.509 |
| quote_tier1 | content | 6,806 | 2,826 | 0.843 [0.832, 0.854] | -0.499 | 3.509 |
| quote_tier1 | time+content | 6,806 | 2,826 | 0.855 [0.844, 0.868] | -0.406 | 3.509 |
| quote_tier1 | time+content_other_agents | 6,806 | 2,826 | 0.878 [0.868, 0.888] | -0.278 | 3.509 |
| quote_tier1 | uniform | 6,806 | 2,826 | 0.695 [0.685, 0.704] | -0.605 | 3.509 |
| quote_tier1 | latest | 6,806 | 2,826 | 0.814 [0.801, 0.829] | n/a | 3.509 |
| quote_tier1 | latest_other_agent_message | 6,806 | 2,826 | 0.952 [0.945, 0.959] | n/a | 3.509 |
| quote_tier1 | time_module_a | 6,806 | 2,826 | 0.805 [0.788, 0.819] | -1.252 | 3.509 |
| quote_tier1 | time+content_module_a | 6,806 | 2,826 | 0.822 [0.807, 0.836] | -1.269 | 3.509 |
| quote_tier1 | time+content_other_agents_module_a | 6,806 | 2,826 | 0.836 [0.822, 0.848] | -1.128 | 3.509 |
| hand | time | 14 | 14 | 0.714 [0.464, 0.938] | -0.807 | 4.714 |
| hand | content | 14 | 14 | 0.446 [0.243, 0.673] | -1.149 | 4.714 |
| hand | time+content | 14 | 14 | 0.714 [0.444, 0.936] | -0.783 | 4.714 |
| hand | time+content_other_agents | 14 | 14 | 0.714 [0.449, 0.929] | -0.812 | 4.714 |
| hand | uniform | 14 | 14 | 0.352 [0.255, 0.446] | -1.250 | 4.714 |
| hand | latest | 14 | 14 | 0.857 [0.615, 1] | n/a | 4.714 |
| hand | latest_other_agent_message | 14 | 14 | 0.607 [0.341, 0.833] | n/a | 4.714 |
| hand | time_module_a | 14 | 14 | 0.571 [0.290, 0.833] | -5.287 | 4.714 |
| hand | time+content_module_a | 14 | 14 | 0.500 [0.250, 0.800] | -5.261 | 4.714 |
| hand | time+content_other_agents_module_a | 14 | 14 | 0.500 [0.231, 0.774] | -5.279 | 4.714 |
| claude | time | 45 | 45 | 0.578 [0.427, 0.721] | -0.849 | 5.822 |
| claude | content | 45 | 45 | 0.473 [0.354, 0.587] | -1.088 | 5.822 |
| claude | time+content | 45 | 45 | 0.622 [0.489, 0.776] | -0.770 | 5.822 |
| claude | time+content_other_agents | 45 | 45 | 0.622 [0.474, 0.763] | -0.813 | 5.822 |
| claude | uniform | 45 | 45 | 0.364 [0.314, 0.410] | -1.236 | 5.822 |
| claude | latest | 45 | 45 | 0.622 [0.490, 0.757] | n/a | 5.822 |
| claude | latest_other_agent_message | 45 | 45 | 0.348 [0.212, 0.465] | n/a | 5.822 |
| claude | time_module_a | 45 | 45 | 0.689 [0.538, 0.813] | -0.876 | 5.822 |
| claude | time+content_module_a | 45 | 45 | 0.733 [0.600, 0.868] | -0.798 | 5.822 |
| claude | time+content_other_agents_module_a | 45 | 45 | 0.733 [0.600, 0.854] | -0.830 | 5.822 |
| composite | time | 45 | 45 | 0.644 [0.506, 0.778] | -0.831 | 5.822 |
| composite | content | 45 | 45 | 0.473 [0.368, 0.596] | -1.122 | 5.822 |
| composite | time+content | 45 | 45 | 0.667 [0.522, 0.794] | -0.786 | 5.822 |
| composite | time+content_other_agents | 45 | 45 | 0.667 [0.539, 0.792] | -0.806 | 5.822 |
| composite | uniform | 45 | 45 | 0.364 [0.312, 0.414] | -1.236 | 5.822 |
| composite | latest | 45 | 45 | 0.711 [0.573, 0.842] | n/a | 5.822 |
| composite | latest_other_agent_message | 45 | 45 | 0.414 [0.295, 0.543] | n/a | 5.822 |
| composite | time_module_a | 45 | 45 | 0.667 [0.528, 0.810] | -2.160 | 5.822 |
| composite | time+content_module_a | 45 | 45 | 0.667 [0.543, 0.812] | -2.116 | 5.822 |
| composite | time+content_other_agents_module_a | 45 | 45 | 0.667 [0.513, 0.806] | -2.126 | 5.822 |

Accuracy counts ties as split evenly. gamma is fixed at the value chosen on the labels (section 4.1), so these rows are not cross-fitted. Quote labels share text with their parent by construction, so for them only the time term is informative. Methods ending in _kde_only take the time term from the KDE alone, and methods ending in _module_a from the module A kernels, whichever is not the main time term. hand is the owner's audit labels, claude the blind labels from Claude, and composite the owner's label where it exists and the label from Claude elsewhere. CIs: cluster bootstrap by child message.

## 5. Agent-level forest by generation (SPEC 6.4.4)

The main view counts transmission between agents. Each actor's first occurrence of a unit is its acquisition (all humans count as one actor). The MAP parent of an acquisition (the carrier) is an occurrence of another actor, and that actor's acquisition is one generation up. Later occurrences of an actor are re-mentions: they keep the actor's generation whatever their own MAP parent, and section 5.2 summarises them as restatement depth. Offspring of an acquisition are the acquisitions it carried, through any of its actor's occurrences.

Acquisitions 2,117,354: transmitted 815,594, independent (env) 156,749, roots without a candidate 1,145,011. Transmissions with complete follow-up 781,832. Maximum agent-level generation 7 (occurrence-level 152).

| g | Acquisitions | Trees | Offspring [95% CI] | Expected offspring | Chat to chat | Chat to memory | Chat to search answer | Chat to human | Content change [95% CI] | Independent [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1,301,760 | 1,301,760 | 0.493 [0.491, 0.495] | 0.493 | n/a | n/a | n/a | n/a | n/a [n/a, n/a] | 0.116 [0.116, 0.117] |
| 1 | 645,779 | 314,418 | 0.235 [0.233, 0.238] | 0.466 | 0.163 | 0.768 | 0.069 | 0.000593 | 0.742 [0.737, 0.746] | 0.008 [0.008, 0.008] |
| 2 | 150,985 | 71,714 | 0.112 [0.109, 0.115] | 0.414 | 0.084 | 0.848 | 0.068 | 0.00045 | 0.731 [0.723, 0.739] | 0.005 [0.005, 0.005] |
| 3 | 16,809 | 8,273 | 0.109 [0.099, 0.118] | 0.341 | 0.077 | 0.855 | 0.067 | 0.000773 | 0.748 [0.725, 0.768] | 0.006 [0.004, 0.007] |
| 4 | 1,817 | 918 | 0.097 [0.076, 0.123] | 0.283 | 0.065 | 0.867 | 0.068 | 0.00055 | 0.752 [0.675, 0.809] | 0.007 [0.004, 0.011] |
| 5 | 175 | 94 | 0.149 [0.092, 0.213] | 0.217 | 0.137 | 0.777 | 0.086 | 0.000 | 0.649 [0.487, 0.788] | 0.011 [0.000, 0.028] |
| 6 | 26 | 20 | 0.115 [0.000, 0.278] | 0.171 | 0.077 | 0.885 | 0.038 | 0.000 | 0.500 [0.000, 1] | 0.000 [0.000, 0.000] |
| 7 | 3 | 3 | 0.000 [0.000, 0.000] | 0.098 | 0.333 | 0.667 | 0.000 | 0.000 | n/a [n/a, n/a] | 0.000 [0.000, 0.000] |

Channel shares are of the transmissions into g. Offspring counts only acquisitions at least L_B before the end of the data. Expected offspring scales the generation-0 mean by the share of active agents without the unit yet (finite population, SPEC 6.2). Content change: share of a node's non-root values (quantity values under a context key that the root holds with another value, SPEC appendix A) that its carrier lacks. Independent: share of acquisitions whose MAP parent is env_i, by the agent-level generation they have when env_i is not allowed. CIs: cluster bootstrap by agent-level tree root.

### 5.2 Restatement depth

1,027,430 of the 3,144,784 occurrences are re-mentions by an actor that already holds the unit. Their MAP parent is the actor's own earlier occurrence for 552,226 (53.7%), another actor's occurrence for 282,272 (27.5%), env_i for 48,351 and none for 144,581. Counting every edge as a generation gives a maximum of 152 generations; transmission to new agents reaches 7. Restatement depth (re-mentions per acquisition): mean 0.485, median 0.000, maximum 146 (2,117,354 acquisitions).

| Restatement depth | Acquisitions | Share |
|---|---|---|
| 0 | 1,562,679 | 0.738 |
| 1 | 384,894 | 0.182 |
| 2 | 96,103 | 0.045 |
| 3 | 31,706 | 0.015 |
| 4 | 12,553 | 0.006 |
| 5 | 7,336 | 0.003 |
| 6 | 4,803 | 0.002 |
| 7 | 3,376 | 0.002 |
| 8 | 2,347 | 0.001 |
| 9 | 1,869 | 0.000883 |
| 10+ | 9,688 | 0.005 |

For reference, H1 with occurrence-level generations (every MAP edge counts as a generation), 199 permutations:

| Stratum | Generations | Edges | p (MAP) | Synthetic type I error (MAP) | p (determined) | Synthetic type I error (determined) |
|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 93 | 261,784 | 0.005 | 1 [0.963, 1] | 0.005 | 0.100 [0.055, 0.174] |
| Chat to Chat, Same Agent | 93 | 212,281 | 0.005 | 0.980 [0.930, 0.994] | 0.005 | n/a |
| Chat to Human | 6 | 1,213 | 0.005 | n/a | n/a | n/a |
| Chat to Memory, Other Agent | 32 | 664,434 | 0.005 | 0.470 [0.375, 0.567] | 0.005 | 0.450 [0.356, 0.548] |
| Chat to Memory, Same Agent | 13 | 159,372 | 0.005 | 0.420 [0.328, 0.518] | 0.005 | n/a |
| Own Memory to Chat | 11 | 79,351 | 0.005 | 1 [0.963, 1] | 0.005 | n/a |
| Search Answer to Chat | 22 | 7,919 | 0.005 | n/a | 0.055 | n/a |
| Search Answer to Memory | 11 | 6,058 | 0.005 | n/a | 0.005 | n/a |
| Chat to Search Answer | 56 | 154,009 | 0.005 | n/a | 0.005 | n/a |
| combined | 337 | 1,546,421 | 0.005 | 1 [0.963, 1] | 0.005 | 0.380 [0.291, 0.478] |

## 6. H1: serial intervals and generation (SPEC 6.2)

H1 compares the forward serial intervals of transmissions (carrier to acquisition) across agent-level generations. It is stratified by kernel key (channel, child source); a channel group that pools two keys changes its mix with the generation, and on synthetic trees with intervals independent of the generation such a pooled test rejected in most replicates. p uses permutations of generation labels within a stratum (499 for the MAP forest, smallest attainable p 0.0020; 99 per posterior draw). The permutation null treats edges as exchangeable and ignores dependence within trees, so section 9 measures the error rate of each test on synthetic trees.

### 6.1 Headline: determined paths

Transmissions whose whole agent-level path from the root uses acquisitions with a single candidate parent (463,310 of the transmissions with complete follow-up). Each parent on such a path is the only candidate, so this test does not depend on the parent posterior. On synthetic trees 0.954 [0.951, 0.957] of these parents are correct (100 replicates).

Strata whose test keeps its nominal 5% level on synthetic trees with intervals independent of the generation (the 95% interval of the null rejection rate contains 0.05): on determined paths Chat to Memory, Other Agent; on the MAP forest none. Only these tests bear on H1.

| Stratum | Generations (count) | Edges | A2 | z vs permutation null | p (permutation) | Synthetic type I error [95% CI] | Synthetic power [95% CI] | Posterior draws: median p |
|---|---|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 1, 2 | 84,857 | 145.255 | 176.793 | 0.002 | 0.130 [0.078, 0.210] | 0.400 [0.234, 0.593] | 0.010 |
| Chat to Human | 1 | 250 | n/a | n/a | n/a | n/a | n/a | None |
| Chat to Memory, Other Agent | 1, 2, 3 | 351,863 | 589.808 | 523.984 | 0.002 | 0.070 [0.034, 0.137] | 1 [0.867, 1] | 0.010 |
| Chat to Search Answer | 1, 2 | 26,316 | 12.065 | 14.710 | 0.002 | n/a | n/a | 0.010 |
| combined | n/a | 463,036 | 747.129 | 466.166 | 0.002 | 0.150 [0.093, 0.233] | 1 [0.867, 1] | 0.010 |

Power: synthetic trees whose transmission intervals grow by a factor 1.5 per agent-level generation after the first. Intervals by generation on determined paths: trees_h1_intervals_determined.csv.

T_k on determined paths (time from the tree root to the acquisition at hop k):

| k | Acquisitions | Trees | Mean h [95% CI] | Variance h2 [95% CI] | Median h [95% CI] |
|---|---|---|---|---|---|
| 1 | 375,823 | 220,570 | 37.776 [37.180, 38.370] | 16930.888 [16535.065, 17312.634] | 0.203 [0.201, 0.205] |
| 2 | 5,082 | 3,709 | 235.368 [224.920, 246.604] | 79655.861 [74000.760, 86173.868] | 120.090 [110.559, 130.996] |
| 3 | 83 | 60 | 521.705 [415.270, 611.683] | 116424.741 [79494.694, 148565.814] | 537.757 [393.274, 670.927] |

| Quantity | Model | k values | Slope [95% CI] | k^2 coefficient [95% CI] | p (k^2, bootstrap) |
|---|---|---|---|---|---|
| mean | linear | 3 | 200.331 [190.099, 211.141] |  |  |
| mean | quadratic | 3 | 64.476 | 44.372 [-7.012, 91.336] | 0.120 |
| variance | linear | 3 | 61923.912 [56450.009, 67992.561] |  |  |
| variance | quadratic | 3 | 101659.113 | -12978.046 [-33509.388, 5074.272] | 0.144 |

### 6.2 MAP forest, with its synthetic type I error

The MAP-forest test is shown for completeness. Its synthetic type I error (MAP trees inferred from synthetic data where H1 holds) is far above 5% in most strata, so a rejection here does not show that intervals change with the generation.

| Stratum | Generations (count) | Edges | A2 | z vs permutation null | p (permutation) | Synthetic type I error [95% CI] | Posterior draws: median p | Draws with p < 0.05 |
|---|---|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 1 to 4 (4) | 118,403 | 200.950 | 147.092 | 0.002 | 0.760 [0.668, 0.833] | 0.010 | 1 |
| Chat to Human | 1, 2 | 451 | 0.368 | -0.825 | 0.868 | n/a | 0.715 | 0.000 |
| Chat to Memory, Other Agent | 1 to 5 (5) | 626,208 | 594.123 | 381.849 | 0.002 | 0.370 [0.282, 0.468] | 0.010 | 1 |
| Chat to Search Answer | 1 to 4 (4) | 36,697 | 131.935 | 96.962 | 0.002 | n/a | 0.010 | 1 |
| combined | n/a | 781,759 | 927.376 | 357.722 | 0.002 | 0.770 [0.678, 0.842] | 0.010 | 1 |

### 6.3 Forward intervals by stratum and generation

| Stratum | g | Edges | Trees | Median h [95% CI] | IQR h | Mean h [95% CI] |
|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 1 | 104,410 | 102,714 | 0.063 [0.062, 0.064] | 0.015 to 0.432 | 1.141 [1.126, 1.158] |
| Chat to Chat, Other Agent | 2 | 12,583 | 12,258 | 0.044 [0.043, 0.046] | 0.013 to 0.201 | 0.742 [0.707, 0.781] |
| Chat to Chat, Other Agent | 3 | 1,292 | 1,247 | 0.035 [0.031, 0.040] | 0.010 to 0.149 | 0.576 [0.486, 0.678] |
| Chat to Chat, Other Agent | 4 | 118 | 112 | 0.027 [0.019, 0.031] | 0.009 to 0.076 | 0.404 [0.203, 0.687] |
| Chat to Human | 1 | 383 | 383 | 0.387 [0.230, 0.437] | 0.056 to 2.285 | 1.879 [1.535, 2.246] |
| Chat to Human | 2 | 68 | 68 | 0.264 [0.171, 0.594] | 0.080 to 2.192 | 1.857 [1.134, 2.696] |
| Chat to Memory, Other Agent | 1 | 484,470 | 221,998 | 0.134 [0.134, 0.135] | 0.055 to 0.323 | 0.845 [0.836, 0.855] |
| Chat to Memory, Other Agent | 2 | 125,899 | 59,472 | 0.119 [0.117, 0.119] | 0.049 to 0.275 | 0.608 [0.595, 0.621] |
| Chat to Memory, Other Agent | 3 | 14,148 | 6,987 | 0.115 [0.113, 0.119] | 0.047 to 0.278 | 0.587 [0.548, 0.624] |
| Chat to Memory, Other Agent | 4 | 1,555 | 790 | 0.111 [0.102, 0.122] | 0.046 to 0.287 | 0.557 [0.466, 0.652] |
| Chat to Memory, Other Agent | 5 | 136 | 68 | 0.090 [0.063, 0.121] | 0.036 to 0.237 | 0.796 [0.367, 1.305] |
| Chat to Search Answer | 1 | 30,359 | 27,297 | 0.410 [0.395, 0.423] | 0.079 to 1.940 | 1.838 [1.802, 1.878] |
| Chat to Search Answer | 2 | 5,770 | 5,245 | 0.670 [0.612, 0.727] | 0.126 to 3.087 | 2.559 [2.452, 2.672] |
| Chat to Search Answer | 3 | 519 | 486 | 0.934 [0.744, 1.129] | 0.198 to 3.612 | 2.895 [2.516, 3.273] |
| Chat to Search Answer | 4 | 49 | 44 | 0.944 [0.462, 2.031] | 0.115 to 5.198 | 2.646 [1.760, 3.713] |

MAP forest, transmissions. Only generations with at least 30 edges are reported; this table stops at g = 10 (0 more rows in trees_h1_intervals.csv). Intervals are in active hours. F3 shows the ECDFs of generations 1 to 6 for the strata with at least two (Chat to Chat, Other Agent, Chat to Human, Chat to Memory, Other Agent, Chat to Search Answer).

### 6.4 T_k against k

T_k is the time from the tree root to an acquisition at agent-level generation k (MAP forest).

| k | Acquisitions | Trees | Mean h [95% CI] | Variance h2 [95% CI] | Median h [95% CI] | IQR h |
|---|---|---|---|---|---|---|
| 1 | 519,843 | 266,621 | 44.933 [44.297, 45.518] | 19921.668 [19528.100, 20294.453] | 0.278 [0.276, 0.282] | 0.075 to 4.025 |
| 2 | 123,834 | 62,640 | 49.957 [48.494, 51.416] | 24498.246 [23565.884, 25461.048] | 0.418 [0.406, 0.429] | 0.142 to 4.826 |
| 3 | 13,785 | 7,354 | 76.076 [70.115, 81.872] | 40165.863 [35959.966, 44561.921] | 0.556 [0.515, 0.601] | 0.182 to 9.094 |
| 4 | 1,424 | 806 | 141.366 [116.731, 165.915] | 80342.963 [62121.549, 96755.300] | 1.313 [0.856, 2.066] | 0.242 to 104.280 |
| 5 | 153 | 87 | 196.644 [122.313, 278.979] | 106007.965 [62078.794, 148454.863] | 3.567 [0.494, 34.314] | 0.247 to 329.021 |

| Quantity | Model | k values | Slope [95% CI] | k^2 coefficient [95% CI] | p (k^2, bootstrap) |
|---|---|---|---|---|---|
| mean | linear | 5 | 10.804 [9.081, 12.548] |  |  |
| mean | quadratic | 5 | -31.212 | 11.993 [9.006, 15.036] | 0.000 |
| variance | linear | 5 | 7708.397 [6449.610, 8880.994] |  |  |
| variance | quadratic | 5 | -15321.996 | 6573.793 [4575.786, 8518.915] | 0.000 |

Trees enter if their root lies more than 30 run days before the end of the data. Fits are weighted by the number of acquisitions per k. F4 shows the means and variances with the linear fits.

Consecutive transmission intervals along an agent-level path: Spearman rho 0.180 [0.174, 0.186], n = 161,707 pairs.

## 7. H3: content change per generation

| Channel | Edges | Contexts carried | Contexts changed | c [95% CI] | Inherited by children | Reverted |
|---|---|---|---|---|---|---|
| agent_retelling | 942,606 | 909,623 | 273,400 | 0.301 [0.299, 0.302] | 0.420 | 0.417 |
| chat_to_chat_other | 263,744 | 269,365 | 115,522 | 0.429 [0.425, 0.433] | 0.421 | 0.415 |
| chat_to_memory_other | 678,862 | 640,258 | 157,878 | 0.247 [0.245, 0.248] | 0.403 | 0.477 |
| chat_same_agent | 376,097 | 572,877 | 190,708 | 0.333 [0.329, 0.336] | 0.393 | 0.331 |
| own_memory_to_chat | 122,133 | 74,587 | 28,484 | 0.382 [0.378, 0.386] | 0.487 | 0.450 |
| search_answer_to_agent | 14,946 | 9,923 | 2,910 | 0.293 [0.283, 0.303] | 0.380 | 0.578 |
| chat_to_search_answer | 192,853 | 255,850 | 14,562 | 0.057 [0.055, 0.058] | 0.419 | 0.498 |
| memory_consolidation_b1_number (v2) |  | 10,679,350 | 140,251 | 0.013 [0.013, 0.013] |  |  |
| memory_consolidation_b1_money (v2) |  | 322,346 | 869 | 0.003 [0.003, 0.003] |  |  |
| memory_consolidation_b1_percent (v2) |  | 552,639 | 4,186 | 0.008 [0.007, 0.008] |  |  |
| memory_consolidation_b1_time (v2) |  | 7,883,192 | 40,178 | 0.005 [0.005, 0.005] |  |  |
| memory_consolidation_b1_quantities (v2) |  | 19,437,527 | 185,484 | 0.010 [0.009, 0.010] |  |  |
| memory_consolidation_b1_quantities (v1) |  | 6,550,788 | 848,830 | 0.130 [0.129, 0.130] |  |  |
| memory_consolidation_b1_quantities (v3) |  | 7,386,947 | 243,386 | 0.033 [0.033, 0.033] |  |  |

c is the share of quantity contexts carried from parent to child (same context key in both) whose value changed. For B1 it is the share of quantity facts whose context stays at a consolidation and whose value changed (rule set in brackets; the main rule set is v2, and the quantities row is also given for the other rule sets; Wilson CI, which ignores clustering by agent). B2 CIs: cluster bootstrap by tree root.

## 8. Attractor test

| Measure | g | Nodes | Units | Mean [95% CI] |
|---|---|---|---|---|
| type_token_ratio | 0 | 1,420,596 | 280,964 | 0.900 [0.900, 0.901] |
| type_token_ratio | 1 | 893,588 | 280,388 | 0.903 [0.903, 0.903] |
| type_token_ratio | 2 | 190,546 | 70,565 | 0.905 [0.904, 0.905] |
| type_token_ratio | 3 | 23,222 | 8,216 | 0.901 [0.899, 0.902] |
| type_token_ratio | 4 | 2,683 | 915 | 0.896 [0.891, 0.901] |
| type_token_ratio | 5 | 302 | 94 | 0.903 [0.891, 0.914] |
| type_token_ratio | 6 | 47 | 20 | 0.891 [0.866, 0.911] |
| type_token_ratio_slope | slope | 2,530,986 | 280,973 | 0.006 [0.005, 0.006] |
| similarity_to_modal | 0 | 1,420,596 | 280,964 | 0.284 [0.283, 0.285] |
| similarity_to_modal | 1 | 893,588 | 280,388 | 0.409 [0.408, 0.411] |
| similarity_to_modal | 2 | 190,546 | 70,565 | 0.369 [0.367, 0.372] |
| similarity_to_modal | 3 | 23,222 | 8,216 | 0.294 [0.288, 0.300] |
| similarity_to_modal | 4 | 2,683 | 915 | 0.246 [0.227, 0.267] |
| similarity_to_modal | 5 | 302 | 94 | 0.212 [0.171, 0.253] |
| similarity_to_modal | 6 | 47 | 20 | 0.136 [0.082, 0.232] |
| similarity_to_modal_slope | slope | 2,530,986 | 280,973 | 0.052 [0.051, 0.053] |

Windows are the 41 tokens around the anchor. Similarity is the token Jaccard index with the unit's most common window. g is the agent-level generation of the occurrence. Slope rows give the within-unit slope on generation (cluster bootstrap by unit).

## 9. Synthetic validation

100 null replicates of 50,000 units each, plus power replicates. Parameters from the MAP forest: R by generation 0.518, 0.526, 0.532; independent share 0.111; spurious env share 0.096; content change probability 0.740; gamma 0.250.

| Scenario | Statistic | Replicates | Estimate [95% interval] |
|---|---|---|---|
| null (H1 true) | parent_accuracy | 100 | 0.808 [0.804, 0.812] |
| null (H1 true) | parent_accuracy_transmission | 100 | 0.792 [0.788, 0.796] |
| null (H1 true) | env_recall | 100 | 0.932 [0.926, 0.938] |
| null (H1 true) | generation_accuracy | 100 | 0.873 [0.870, 0.876] |
| null (H1 true) | generation_accuracy_nonroot | 100 | 0.750 [0.744, 0.754] |
| null (H1 true) | agent_generation_accuracy | 100 | 0.891 [0.886, 0.896] |
| null (H1 true) | generation_mae | 100 | 0.162 [0.156, 0.167] |
| null (H1 true) | determined_share | 100 | 0.573 [0.564, 0.580] |
| null (H1 true) | determined_parent_accuracy | 100 | 0.954 [0.951, 0.957] |
| null (H1 true) | determined_agent_generation_accuracy | 100 | 0.952 [0.949, 0.956] |
| null (H1 true) | rejection_rate_true_chat_to_chat_other | 100 | 0.030 [0.010, 0.085] |
| null (H1 true) | rejection_rate_true_chat_to_memory_other | 100 | 0.070 [0.034, 0.137] |
| null (H1 true) | rejection_rate_true_combined | 100 | 0.070 [0.034, 0.137] |
| null (H1 true) | rejection_rate_inferred_chat_to_chat_other | 100 | 0.760 [0.668, 0.833] |
| null (H1 true) | rejection_rate_inferred_chat_to_memory_other | 100 | 0.370 [0.282, 0.468] |
| null (H1 true) | rejection_rate_inferred_combined | 100 | 0.770 [0.678, 0.842] |
| null (H1 true) | rejection_rate_determined_chat_to_chat_other | 100 | 0.130 [0.078, 0.210] |
| null (H1 true) | rejection_rate_determined_chat_to_memory_other | 100 | 0.070 [0.034, 0.137] |
| null (H1 true) | rejection_rate_determined_combined | 100 | 0.150 [0.093, 0.233] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_chat_other | 100 | 0.100 [0.055, 0.174] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_chat_self | 100 | 0.060 [0.028, 0.125] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_memory_other | 100 | 0.040 [0.016, 0.098] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_memory_self | 100 | 0.100 [0.055, 0.174] |
| null (H1 true) | occurrence_rejection_rate_true_memory_to_chat | 100 | 0.080 [0.041, 0.150] |
| null (H1 true) | occurrence_rejection_rate_true_combined | 100 | 0.070 [0.034, 0.137] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_chat_other | 100 | 1 [0.963, 1] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_chat_self | 100 | 0.980 [0.930, 0.994] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_memory_other | 100 | 0.470 [0.375, 0.567] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_memory_self | 100 | 0.420 [0.328, 0.518] |
| null (H1 true) | occurrence_rejection_rate_inferred_memory_to_chat | 100 | 1 [0.963, 1] |
| null (H1 true) | occurrence_rejection_rate_inferred_combined | 100 | 1 [0.963, 1] |
| null (H1 true) | occurrence_rejection_rate_determined_chat_to_chat_other | 100 | 0.100 [0.055, 0.174] |
| null (H1 true) | occurrence_rejection_rate_determined_chat_to_memory_other | 100 | 0.450 [0.356, 0.548] |
| null (H1 true) | occurrence_rejection_rate_determined_combined | 100 | 0.380 [0.291, 0.478] |
| alternative (intervals between agents x 1.5^(g-1)) | parent_accuracy | 25 | 0.807 [0.804, 0.809] |
| alternative (intervals between agents x 1.5^(g-1)) | parent_accuracy_transmission | 25 | 0.790 [0.787, 0.793] |
| alternative (intervals between agents x 1.5^(g-1)) | env_recall | 25 | 0.932 [0.928, 0.939] |
| alternative (intervals between agents x 1.5^(g-1)) | generation_accuracy | 25 | 0.873 [0.869, 0.875] |
| alternative (intervals between agents x 1.5^(g-1)) | generation_accuracy_nonroot | 25 | 0.748 [0.743, 0.752] |
| alternative (intervals between agents x 1.5^(g-1)) | agent_generation_accuracy | 25 | 0.886 [0.882, 0.892] |
| alternative (intervals between agents x 1.5^(g-1)) | generation_mae | 25 | 0.166 [0.161, 0.173] |
| alternative (intervals between agents x 1.5^(g-1)) | determined_share | 25 | 0.573 [0.566, 0.579] |
| alternative (intervals between agents x 1.5^(g-1)) | determined_parent_accuracy | 25 | 0.947 [0.944, 0.952] |
| alternative (intervals between agents x 1.5^(g-1)) | determined_agent_generation_accuracy | 25 | 0.944 [0.941, 0.950] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_true_chat_to_chat_other | 25 | 0.960 [0.805, 0.993] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_true_chat_to_memory_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_true_combined | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_inferred_chat_to_chat_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_inferred_chat_to_memory_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_inferred_combined | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_determined_chat_to_chat_other | 25 | 0.400 [0.234, 0.593] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_determined_chat_to_memory_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_determined_combined | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_chat_other | 25 | 0.720 [0.524, 0.857] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_chat_self | 25 | 0.000 [0.000, 0.133] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_memory_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_memory_self | 25 | 0.000 [0.000, 0.133] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_memory_to_chat | 25 | 0.040 [0.007, 0.195] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_combined | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_chat_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_chat_self | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_memory_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_memory_self | 25 | 0.360 [0.202, 0.555] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_memory_to_chat | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_combined | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_determined_chat_to_chat_other | 25 | 0.200 [0.089, 0.391] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_determined_chat_to_memory_other | 25 | 1 [0.867, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_determined_combined | 25 | 1 [0.867, 1] |

## 10. Sensitivity

| Variant | Value | Transmissions | Independent | Max generation | Max occurrence-level generation | Independent share of acquisitions | H3 c | H1 determined p, chat to chat | H1 MAP combined p |
|---|---|---|---|---|---|---|---|---|---|
| main | rules v2, env precede, exposure main, time term KDE | 815,594 | 156,749 | 7 | 152 | 0.161 | 0.301 | 0.005 | 0.005 |
| time_term | module A kernel + KDE | 813,991 | 158,352 | 7 | 135 | 0.163 | 0.294 | 0.005 | 0.005 |
| gamma | 0 (time only) | 815,397 | 156,946 | 7 | 174 | 0.161 | 0.309 | 0.005 | 0.005 |
| gamma | 1.0 (SPEC default) | 815,814 | 156,529 | 7 | 134 | 0.161 | 0.298 | 0.005 | 0.005 |
| content | other agents only, gamma 0.25 | 815,594 | 156,749 | 7 | 172 | 0.161 | 0.304 | 0.005 | 0.005 |
| env_rule | any | 786,857 | 185,486 | 7 | 148 | 0.191 | 0.295 | 0.005 | 0.005 |
| exposure | ever | 820,651 | 155,500 | 7 | 152 | 0.159 | 0.301 | 0.005 | 0.005 |
| exposure | all | 832,214 | 151,353 | 7 | 152 | 0.154 | 0.302 | 0.005 | 0.005 |
| rules | v1 | 815,594 | 156,749 | 7 | 152 | 0.161 | 0.301 | 0.005 | 0.005 |
| rules | v3 | 815,594 | 156,749 | 7 | 152 | 0.161 | 0.301 | 0.005 | 0.005 |

Permutations: 199; no bootstrap intervals for these runs.

## 11. Posterior draws

| Statistic | Draws | Median | 2.5% | 97.5% |
|---|---|---|---|---|
| n_edges | 200 | 813879.500 | 813773.850 | 814008.100 |
| n_edges_all | 200 | 1,641,003 | 1640720.575 | 1641233.075 |
| n_env | 200 | 158463.500 | 158334.900 | 158569.150 |
| n_roots | 200 | 1,145,011 | 1,145,011 | 1,145,011 |
| max_gen | 200 | 7 | 6 | 7 |
| max_gen_occurrence | 200 | 44 | 39.975 | 54 |
| h3_c | 200 | 0.304 | 0.303 | 0.304 |
| adjacent_rho | 200 | 0.177 | 0.174 | 0.180 |
| nodes_gen0 | 200 | 1303474.500 | 1303345.900 | 1303580.150 |
| nodes_gen1 | 200 | 679,596 | 679205.925 | 679926.250 |
| nodes_gen2 | 200 | 123,455 | 123108.825 | 123842.075 |
| nodes_gen3 | 200 | 9983.500 | 9795.775 | 10137.075 |
| nodes_gen4 | 200 | 783 | 723.950 | 838.025 |
| nodes_gen5 | 200 | 71 | 51.975 | 91.025 |
| nodes_gen6 | 200 | 8 | 3 | 14 |
| nodes_gen7 | 200 | 1 | 0.000 | 3.025 |
| h1_p_chat_to_chat_other | 200 | 0.010 | 0.010 | 0.010 |
| h1_ngen_chat_to_chat_other | 200 | 4 | 4 | 4 |
| h1_ngen_chat_to_chat_self | 200 | 0.000 | 0.000 | 0.000 |
| h1_p_chat_to_human | 200 | 0.715 | 0.190 | 0.961 |
| h1_ngen_chat_to_human | 200 | 2 | 2 | 2 |
| h1_p_chat_to_memory_other | 200 | 0.010 | 0.010 | 0.010 |
| h1_ngen_chat_to_memory_other | 200 | 5 | 5 | 5 |
| h1_ngen_chat_to_memory_self | 200 | 0.000 | 0.000 | 0.000 |
| h1_ngen_memory_to_chat | 200 | 0.000 | 0.000 | 0.000 |
| h1_ngen_search_to_chat | 200 | 0.000 | 0.000 | 0.000 |
| h1_ngen_search_to_memory | 200 | 0.000 | 0.000 | 0.000 |
| h1_p_chat_to_search_answer | 200 | 0.010 | 0.010 | 0.010 |
| h1_ngen_chat_to_search_answer | 200 | 3 | 3 | 4 |
| h1_p_combined | 200 | 0.010 | 0.010 | 0.010 |
| h1_ngen_combined | 200 | 14 | 14 | 15 |
| h1det_p_chat_to_chat_other | 200 | 0.010 | 0.010 | 0.010 |
| h1det_p_chat_to_memory_other | 200 | 0.010 | 0.010 | 0.010 |
| h1det_p_chat_to_search_answer | 200 | 0.010 | 0.010 | 0.010 |
| h1det_p_combined | 200 | 0.010 | 0.010 | 0.010 |
| tk_mean_linear_slope | 200 | 20.723 | 20.079 | 21.299 |
| tk_mean_quadratic_slope | 200 | -55.573 | -62.837 | -47.023 |
| tk_mean_k2 | 200 | 22.659 | 20.007 | 24.871 |
| tk_variance_linear_slope | 200 | 11979.749 | 11615.337 | 12299.224 |
| tk_variance_quadratic_slope | 200 | -25211.404 | -28894.560 | -21560.549 |
| tk_variance_k2 | 200 | 11033.748 | 9855.194 | 12136.953 |
| edges_chat_other | 200 | 118,592 | 118527.875 | 118644.050 |
| edges_chat_self | 200 | 0.000 | 0.000 | 0.000 |
| edges_chat_to_memory | 200 | 638,750 | 638,639 | 638866.025 |
| edges_memory | 200 | 0.000 | 0.000 | 0.000 |
| edges_search | 200 | 0.000 | 0.000 | 0.000 |
| edges_history | 200 | 56,080 | 56,080 | 56,080 |
| edges_human | 200 | 465 | 465 | 465 |
| offspring_gen0 | 200 | 0.518 | 0.518 | 0.519 |
| offspring_gen1 | 200 | 0.183 | 0.182 | 0.184 |
| offspring_gen2 | 200 | 0.081 | 0.080 | 0.083 |
| offspring_gen3 | 200 | 0.079 | 0.073 | 0.085 |
| offspring_gen4 | 200 | 0.091 | 0.068 | 0.118 |
| offspring_gen5 | 200 | 0.107 | 0.045 | 0.206 |

## 12. Runtime

inputs 46 s, candidates 22 s, labels 56 s, map_stats 584 s, draws 298 s, synthetic 36 s, sensitivity 504 s.
