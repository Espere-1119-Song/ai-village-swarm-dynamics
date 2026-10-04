# QA: memory chains (module B1, SPEC 6.3), rules v3

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Aggregates only. No memory text, names, emails, phone numbers or credentials appear in this report or in outputs/; URLs appear only as domains, PERSON/email/phone values and every value on a credential line are keyed hashes.

Runtime 1900 s (inputs 1, lines + anchors 1 (cache hit), interning 9, chains 1209, statistics and outputs 671). Line and anchor extraction when computed: 37 s + 1518 s.

## 0. Rules v3 against v1 and v2

Rules v2: a unit with no anchor in a consolidation output still counts as present if its value occurs literally there (URL, date, time, email, phone, agent name and entity types: a surface form of the value anywhere, case-insensitive, whitespace-normalised, word-bounded; hashed values by hashing candidate strings; number, money and percent: the same value on a line that also holds the unit's context word). A loss is a modification only if the line that replaced the unit's line (patience alignment of lines kept verbatim; inside a changed block the line at the same offset, or the one sharing the most anchor keys) holds the unit's context key with a new value. Restorations stay anchor-based. Units, entries and consolidations are those of v1; v1 outputs are kept unchanged next to these.
Rules v3: as v2, except that a time, number, money or percent unit counts as present through the fallback only if a line of the consolidation output holds the value (as the regex anchors normalise it) with the unit's context word adjacent to it: right after the value with up to two words between ("56 new donors"), or right before it with only punctuation between ("Donors: 56"), the rule of the pre-labelling evidence. Entity, agent, URL, date, email and phone units use the v2 fallback; modifications use the v2 line alignment; restorations stay anchor-based. v1, v2 and v3 are computed in one pass from the same entries, so per-unit comparisons are exact.

v1 first losses that a later rule set keeps at the same consolidation (standard agents): v2 1,309,112 of 4,134,752 (31.7%); v3 467,255 of 4,134,752 (11.3%). v1 modifications that become drops: v2 445,509 of 962,470; v3 628,415 of 962,470.

| type | v1 losses | kept in v2 (share) | kept in v3 (share) |
|---|---|---|---|
| url | 104,652 | 3,466 (0.033) | 3,466 (0.033) |
| email | 5,165 | 0 (0.000) | 0 (0.000) |
| phone | 207 | 0 (0.000) | 0 (0.000) |
| date | 24,280 | 1,476 (0.061) | 1,476 (0.061) |
| time | 689,299 | 358,913 (0.521) | 22,701 (0.033) |
| money | 32,685 | 9,631 (0.295) | 2,414 (0.074) |
| percent | 103,826 | 25,513 (0.246) | 6,420 (0.062) |
| number | 2,233,691 | 631,838 (0.283) | 152,503 (0.068) |
| agent | 2,983 | 472 (0.158) | 472 (0.158) |
| person | 231,295 | 48,753 (0.211) | 48,753 (0.211) |
| org | 470,676 | 139,807 (0.297) | 139,807 (0.297) |
| gpe | 45,388 | 20,583 (0.453) | 20,583 (0.453) |
| product | 47,942 | 21,620 (0.451) | 21,620 (0.451) |
| event | 8,819 | 3,579 (0.406) | 3,579 (0.406) |
| work_of_art | 133,844 | 43,461 (0.325) | 43,461 (0.325) |

Units that v3 loses at a consolidation where v2 still kept them: 886,286 (time 347,247, money 7,602, percent 20,142, number 511,295).

Hazards by g bin and modified share of first losses (v1 / v2 / v3; point estimates, CIs in section 4 and memory_hazard_v3.csv):

| group | h1 | h2 | h3-4 | h5-8 | h9+ | modified share |
|---|---|---|---|---|---|---|
| All standard | 0.522 / 0.340 / 0.463 | 0.506 / 0.353 / 0.439 | 0.302 / 0.219 / 0.251 | 0.174 / 0.131 / 0.141 | 0.045 / 0.025 / 0.025 | 0.233 / 0.052 / 0.066 |
| Anthropic | 0.541 / 0.339 / 0.480 | 0.530 / 0.370 / 0.461 | 0.311 / 0.221 / 0.256 | 0.181 / 0.135 / 0.144 | 0.045 / 0.025 / 0.027 | 0.229 / 0.050 / 0.064 |
| OpenAI | 0.630 / 0.448 / 0.555 | 0.436 / 0.311 / 0.361 | 0.287 / 0.205 / 0.226 | 0.173 / 0.124 / 0.131 | 0.043 / 0.020 / 0.022 | 0.187 / 0.051 / 0.059 |
| Google | 0.434 / 0.310 / 0.379 | 0.404 / 0.313 / 0.351 | 0.236 / 0.193 / 0.202 | 0.135 / 0.112 / 0.113 | 0.036 / 0.018 / 0.018 | 0.203 / 0.065 / 0.075 |
| Other | 0.419 / 0.254 / 0.376 | 0.539 / 0.365 / 0.481 | 0.323 / 0.233 / 0.281 | 0.183 / 0.136 / 0.157 | 0.057 / 0.034 / 0.035 | 0.288 / 0.050 / 0.071 |
| Claude Code | 0.517 / 0.436 / 0.473 | 0.278 / 0.249 / 0.258 | 0.185 / 0.167 / 0.176 | 0.130 / 0.126 / 0.125 | 0.103 / 0.092 / 0.092 | 0.200 / 0.149 / 0.157 |

BdW shape c from g = 2 (likelihood conditional on surviving the first consolidation), 95% cluster-bootstrap CIs; * marks a fit whose Beta parameters sit at the edge of the search range (the conditional likelihood leaves the mixing of the unobserved first trial free, so c is weakly identified there):

| scope | stratum | c v1 [95% CI] | c v2 [95% CI] | c v3 [95% CI] |
|---|---|---|---|---|
| family | All standard | 0.714 [0.453, 1.041]* | 0.424 [0.139, 0.660] | 0.045 [0.042, 0.081]* |
| regime_cohort | pre | 0.181 [0.149, 0.440] | 0.431 [0.257, 0.604] | 0.175 [0.155, 0.206]* |
| regime_cohort | post | 0.893 [0.555, 11.336]* | 0.546 [0.174, 0.882] | 0.828 [0.536, 11.608]* |

BdW shape c' among the survivors of the first consolidation with the clock restarted (g' = g - 1; fitted in this pass for every rule set, so the rows are directly comparable). The beta-geometric is closed under conditioning on survival, so c' = 1 still means heterogeneity alone, and no unobserved first-trial mixing is left to fit. 95% cluster-bootstrap CIs; * as above:

| scope | c' v1 [95% CI] | c' v2 [95% CI] | c' v3 [95% CI] |
|---|---|---|---|
| All standard | 0.863 [0.802, 0.934] | 0.875 [0.818, 0.927] | 0.860 [0.800, 0.919] |
| pre cohort | 0.857 [0.776, 0.936] | 0.821 [0.724, 0.877] | 0.795 [0.743, 0.841] |
| post cohort | 0.879 [0.807, 0.969] | 0.905 [0.842, 0.973] | 0.905 [0.834, 0.987] |

H2 outcome by family: p of the constant-hazard test (cluster Wald, or LR for one agent), the hazard at g = 1 and at g >= 9, and the model with the lowest AIC:

| group | v1: p; h1 -> h9+; best AIC | v2: p; h1 -> h9+; best AIC | v3: p; h1 -> h9+; best AIC |
|---|---|---|---|
| All standard | <1e-300 (Wald); 0.522 -> 0.045; beta-geometric | 5.5e-208 (Wald); 0.340 -> 0.025; beta-geometric | <1e-300 (Wald); 0.463 -> 0.025; beta-geometric |
| Anthropic | 1.6e-261 (Wald); 0.541 -> 0.045; beta-geometric | 4.7e-175 (Wald); 0.339 -> 0.025; beta-geometric | <1e-300 (Wald); 0.480 -> 0.027; beta-geometric |
| OpenAI | <1e-300 (Wald); 0.630 -> 0.043; beta-geometric | <1e-300 (Wald); 0.448 -> 0.020; beta-geometric | <1e-300 (Wald); 0.555 -> 0.022; beta-geometric |
| Google | 2.5e-15 (Wald); 0.434 -> 0.036; beta-geometric | 9.9e-16 (Wald); 0.310 -> 0.018; beta-geometric | 9.1e-22 (Wald); 0.379 -> 0.018; beta-geometric |
| Other | 1.6e-107 (Wald); 0.419 -> 0.057; piecewise | 3.3e-56 (Wald); 0.254 -> 0.034; beta-geometric | 8.1e-123 (Wald); 0.376 -> 0.035; piecewise |
| Claude Code | <1e-300 (LR); 0.517 -> 0.103; piecewise | <1e-300 (LR); 0.436 -> 0.092; piecewise | <1e-300 (LR); 0.473 -> 0.092; piecewise |

Conclusions across rule sets:

| conclusion | v1 | v2 | v3 | status |
|---|---|---|---|---|
| H2 (constant hazard) rejected at 5% for all standard agents and every family | yes | yes | yes | holds in all |
| Hazard lower at g >= 9 than at g = 1 in every family | yes | yes | yes | holds in all |
| After the switch to perma-computer-use the hazard rises from g = 1 to g = 2 | yes | yes | yes | holds in all |
| Most first losses are drops (modified share below one half) | yes | yes | yes | holds in all |
| Beta-geometric fits better than geometric for all standard agents (AIC) | yes | yes | yes | holds in all |
| BdW c from g = 2 below 1 (All standard: duration dependence beyond heterogeneity) | no | yes | yes | flips |
| BdW c from g = 2 below 1 (pre cohort: duration dependence beyond heterogeneity) | yes | yes | yes | holds in all |
| BdW c from g = 2 below 1 (post cohort: duration dependence beyond heterogeneity) | no | yes | no | flips |
| BdW c' among survivors of g = 1 below 1 (All standard, clock restarted) | yes | yes | yes | holds in all |
| BdW c' among survivors of g = 1 below 1 (pre cohort, clock restarted) | yes | yes | yes | holds in all |
| BdW c' among survivors of g = 1 below 1 (post cohort, clock restarted) | yes | yes | yes | holds in all |
| OpenAI has the highest first-consolidation hazard among families (per version: {'v1': 'OpenAI', 'v2': 'OpenAI', 'v3': 'OpenAI'}) | yes | yes | yes | holds in all |

Reproducibility: hazards of the earlier rule sets recomputed in this pass against their own tables: v1 max |diff| 0.000000 over 30 values; v2 max |diff| 0.000000 over 30 values.

Use of the literal fallback by anchor type under v3 (standard agents): units kept at least once only by a literal match, and the number of such consolidation trials.

| type | units | units with a fallback keep | fallback trials |
|---|---|---|---|
| url | 105,137 | 3,466 | 77,318 |
| email | 5,247 | 0 | 0 |
| phone | 207 | 0 | 0 |
| date | 24,538 | 1,476 | 26,702 |
| time | 690,897 | 22,701 | 85,567 |
| money | 32,806 | 2,414 | 29,780 |
| percent | 104,007 | 6,420 | 48,049 |
| number | 2,239,413 | 152,503 | 968,366 |
| agent | 3,151 | 472 | 157,354 |
| person | 232,423 | 48,753 | 1,338,708 |
| org | 471,788 | 139,807 | 4,005,023 |
| gpe | 45,564 | 20,583 | 1,035,855 |
| product | 48,055 | 21,620 | 782,755 |
| event | 8,835 | 3,579 | 124,457 |
| work_of_art | 134,112 | 43,461 | 1,303,008 |

For information only (rule sets are chosen from the owner's labels, not from these): agreement with the LLM pre-labels on 500 units (review sheet as of 2026-10-01 07:01 UTC, read only): v1 310 (kappa 0.523); v2 341 (kappa 0.544); v3 406 (kappa 0.745). Confusion matrix of the v3 labels (rows) against the LLM labels (columns):

| v3 \ LLM | kept | modified | dropped | new | restored | total | agree |
|---|---|---|---|---|---|---|---|
| kept | 170 | 7 | 6 | 4 | 1 | 188 | 0.904 |
| modified | 0 | 6 | 25 | 0 | 0 | 31 | 0.194 |
| dropped | 7 | 9 | 111 | 0 | 0 | 127 | 0.874 |
| new | 7 | 0 | 0 | 76 | 1 | 84 | 0.905 |
| restored | 6 | 2 | 0 | 19 | 43 | 70 | 0.614 |

## 1. Inputs and coverage

| item | value | expected |
|---|---|---|
| memory rows | 246,151 | 246,151 (manifest) |
| IDENT rows dropped (no-ops) | 6 | 6 |
| rows on abandoned lineage branches | 3 | few (3 generations off the time order) |
| dead generations | 3 | <= 3 |
| live rows analysed | 246,142 |  |
| consolidations (live REWRITE rows) | 85,600 | 85,603 rewrites minus dead |
| agents with memory | 46 | 46 (all) |
| rows with empty text (no anchors; kept in the chains) | 2 | a few (memory_versions treats null content as empty) |

Time range of live rows: 2025-04-02 18:00 to 2026-09-19 00:03 UTC.

| group | agents | consolidations | units | units with >= 1 trial | unit-trials |
|---|---|---|---|---|---|
| All standard | 45 | 83,836 | 4,146,180 | 4,142,667 | 25,785,525 |
| Anthropic | 15 | 33,543 | 1,823,793 | 1,822,944 | 10,172,256 |
| OpenAI | 14 | 23,427 | 945,760 | 945,260 | 6,552,156 |
| Google | 5 | 15,904 | 292,828 | 292,680 | 3,567,721 |
| Other | 11 | 10,962 | 1,083,799 | 1,081,783 | 5,493,392 |
| Claude Code | 1 | 1,764 | 9,657 | 9,653 | 45,908 |

## 2. Lines, anchors and fact units

| item | value |
|---|---|
| segment characters read | 3,204,579,431 |
| segment lines | 41,531,166 |
| distinct lines extracted | 13,768,711 |
| distinct line characters | 1,475,567,340 |
| distinct lines with >= 1 anchor | 8,657,294 |
| distinct occurrences (type, value, context) | 4,243,111 |
| distinct unit keys | 2,368,602 |
| unit keys with a hashed value | 353,137 |
| context lemmas shown in clear (>= 3 agents as a common noun) | 12,711 of 50,318 |
| (agent, unit) pairs tracked | 4,155,837 |
| (agent, unit) pairs with >= 1 consolidation trial | 4,152,320 |

Units per anchor type ((agent, unit) pairs), distinct occurrences, and the share of occurrences without a context key (missing values; such units can be kept or dropped but never modified):

| type | units | occurrences | no context key |
|---|---|---|---|
| url | 105,321 | 198,920 | 0.174 |
| email | 5,268 | 20,277 | 0.071 |
| phone | 210 | 496 | 0.081 |
| date | 24,815 | 181,255 | 0.012 |
| time | 692,077 | 362,033 | 0.006 |
| money | 32,853 | 23,893 | 0.055 |
| percent | 104,150 | 65,814 | 0.038 |
| number | 2,244,447 | 1,240,689 | 0.043 |
| agent | 3,202 | 150,799 | 0.001 |
| person | 233,196 | 528,167 | 0.089 |
| org | 473,251 | 994,633 | 0.111 |
| gpe | 45,755 | 134,850 | 0.047 |
| product | 48,165 | 109,963 | 0.067 |
| event | 8,852 | 13,268 | 0.126 |
| work_of_art | 134,275 | 218,054 | 0.113 |

Entry kind of units (row where the unit first appeared): first 2,274, fork 512, note 280,751, rewrite 1,384,655, session 2,487,645.

## 3. Chain checks

| check | value |
|---|---|
| unit-trials (sum over consolidations of units at risk) | 25,831,433 |
| kept | 21,694,841 |
| dropped | 3,864,707 |
| modified | 271,885 |
| restorations | 1,928,780 |
| units first seen in a consolidation output | 1,384,660 |
| never-lost units missing from the consolidation input (after a truncation) | 1 |
| undo rows (revert, trunc_other) | 119 |
| fork rows extending an older row | 52 |
| units removed from tracking by an undo | 2,202 |
| first losses: dropped / modified / censored | 3,864,707 / 271,885 / 15,728 |
| unit-trials: per-unit sum vs per-consolidation sum | 25,831,433 vs 25,831,433 (ok) |
| first losses: per-unit vs per-consolidation | 4,136,592 vs 4,136,592 (ok) |

## 4. Hazard of loss by model family (H2)

h_g = P(lost at consolidation g | kept through g - 1). 95% CIs resample agents within the group (2000 replicates, seed 20261003); Claude Code is one agent, so its CIs treat units as independent (Wilson). Generations with fewer than 30 units at risk are not reported.

| group | agents | unit-trials | h1 | h2 | h3-4 | h5-8 | h9+ | geometric h |
|---|---|---|---|---|---|---|---|---|
| All standard | 45 | 25,785,525 | 0.463 [0.399, 0.514] | 0.439 [0.404, 0.470] | 0.251 [0.231, 0.271] | 0.141 [0.129, 0.153] | 0.025 [0.022, 0.029] | 0.160 |
| Anthropic | 15 | 10,172,256 | 0.480 [0.385, 0.548] | 0.461 [0.431, 0.484] | 0.256 [0.233, 0.278] | 0.144 [0.129, 0.161] | 0.027 [0.022, 0.035] | 0.179 |
| OpenAI | 14 | 6,552,156 | 0.555 [0.496, 0.597] | 0.361 [0.322, 0.397] | 0.226 [0.195, 0.246] | 0.131 [0.112, 0.144] | 0.022 [0.016, 0.028] | 0.144 |
| Google | 5 | 3,567,721 | 0.379 [0.192, 0.535] | 0.351 [0.264, 0.422] | 0.202 [0.157, 0.253] | 0.113 [0.090, 0.161] | 0.018 [0.016, 0.022] | 0.082 |
| Other | 11 | 5,493,392 | 0.376 [0.271, 0.474] | 0.481 [0.396, 0.532] | 0.281 [0.229, 0.327] | 0.157 [0.127, 0.189] | 0.035 [0.028, 0.045] | 0.196 |
| Claude Code | 1 | 45,908 | 0.473 [0.463, 0.483] | 0.258 [0.246, 0.270] | 0.176 [0.167, 0.185] | 0.125 [0.119, 0.133] | 0.092 [0.088, 0.096] | 0.209 |

H2 tests: geometric (constant hazard) vs piecewise-constant hazard over g = 1, 2, 3-4, 5-8, 9+. The likelihood-ratio test treats units as independent; the Wald test uses the cluster-bootstrap covariance. The beta-geometric model lets each unit keep a constant hazard drawn from a Beta distribution, which makes the population hazard decrease with g.

| scope | stratum | LR | df | p (LR) | Wald | p (Wald, cluster) | AIC geometric | AIC beta-geometric | AIC piecewise | beta-geom a, b |
|---|---|---|---|---|---|---|---|---|---|---|
| family | All standard | 6128776.6 | 4 | <1e-300 | 1830.6 | <1e-300 | 22678593 | 16257658 | 16549825 | 1.195, 1.253 |
| family | Anthropic | 2579270.1 | 4 | <1e-300 | 2402.5 | <1e-300 | 9549285 | 6864227 | 6970023 | 1.246, 1.218 |
| family | OpenAI | 1764359.6 | 4 | <1e-300 | 2793.0 | <1e-300 | 5395164 | 3533322 | 3630813 | 0.915, 0.727 |
| family | Google | 541063.7 | 4 | <1e-300 | 104.9 | 9.1e-22 | 2018575 | 1430652 | 1477519 | 0.935, 1.393 |
| family | Other | 1092406.9 | 4 | <1e-300 | 573.6 | 8.1e-123 | 5434736 | 4351098 | 4342337 | 1.591, 2.078 |
| family | Claude Code | 5443.2 | 4 | <1e-300 | n/a | n/a | 47070 | 42147 | 41635 | 1.081, 1.355 |
| regime:pre | All standard | 1943199.6 | 4 | <1e-300 | 3215.2 | <1e-300 | 5871340 | n/a | 3928148 | n/a, n/a |
| regime:pre | Anthropic | 1110637.9 | 4 | <1e-300 | 3899.8 | <1e-300 | 3257095 | n/a | 2146465 | n/a, n/a |
| regime:pre | OpenAI | 431710.4 | 4 | <1e-300 | 816.4 | 2.1e-175 | 1384646 | n/a | 952944 | n/a, n/a |
| regime:pre | Google | 212753.6 | 4 | <1e-300 | n/a | n/a | 630848 | n/a | 418103 | n/a, n/a |
| regime:pre | Other | 171047.5 | 4 | <1e-300 | n/a | n/a | 576586 | n/a | 405547 | n/a, n/a |
| regime:post | All standard | 4334414.3 | 4 | <1e-300 | 1226.2 | 3.3e-264 | 16803828 | n/a | 12469421 | n/a, n/a |
| regime:post | Anthropic | 1546698.6 | 4 | <1e-300 | 1464.1 | <1e-300 | 6279412 | n/a | 4732722 | n/a, n/a |
| regime:post | OpenAI | 1331676.7 | 4 | <1e-300 | 7773.2 | <1e-300 | 4003130 | n/a | 2671461 | n/a, n/a |
| regime:post | Google | 340965.9 | 4 | <1e-300 | n/a | n/a | 1379121 | n/a | 1038163 | n/a, n/a |
| regime:post | Other | 946380.7 | 4 | <1e-300 | 639.0 | 5.5e-137 | 4847220 | n/a | 3900847 | n/a, n/a |
| memory_epoch | [2025-04-02, 2025-04-15) | 8721.5 | 4 | <1e-300 | n/a | n/a | 23331 | n/a | 14618 | n/a, n/a |
| memory_epoch | [2025-04-15, 2025-04-16) | 574.1 | 4 | 6.3e-123 | n/a | n/a | 1665 | n/a | 1099 | n/a, n/a |
| memory_epoch | [2025-04-16, 2025-08-20) | 214616.3 | 4 | <1e-300 | 1135.9 | 1.3e-244 | 592326 | n/a | 377718 | n/a, n/a |
| memory_epoch | [2025-08-20, 2025-09-05) | 68382.5 | 4 | <1e-300 | 7281.1 | <1e-300 | 188370 | n/a | 119996 | n/a, n/a |
| memory_epoch | [2025-09-05, 2025-10-14) | 147203.0 | 4 | <1e-300 | 2522.1 | <1e-300 | 455862 | n/a | 308667 | n/a, n/a |
| memory_epoch | [2025-10-14, 2025-11-25) | 326920.6 | 4 | <1e-300 | 1848.5 | <1e-300 | 910305 | n/a | 583392 | n/a, n/a |
| memory_epoch | [2025-11-25, 2026-03-11) | 1054281.3 | 4 | <1e-300 | 3191.2 | <1e-300 | 3332165 | n/a | 2277891 | n/a, n/a |
| memory_epoch | [2026-03-11, 2026-03-12) | 12520.8 | 4 | <1e-300 | 794.1 | 1.4e-170 | 37829 | n/a | 25316 | n/a, n/a |
| memory_epoch | [2026-03-12, 2026-03-16) | 25532.6 | 4 | <1e-300 | 1316.7 | 7.8e-284 | 72238 | n/a | 46714 | n/a, n/a |
| memory_epoch | [2026-03-16, 2026-03-24) | 70367.3 | 4 | <1e-300 | 782.1 | 5.8e-168 | 236741 | n/a | 166381 | n/a, n/a |
| memory_epoch | [2026-03-24, 2026-03-26) | 21930.3 | 4 | <1e-300 | 378.9 | 1e-80 | 99202 | n/a | 77280 | n/a, n/a |
| memory_epoch | [2026-03-26, 2026-06-01) | 612678.4 | 4 | <1e-300 | 720.8 | 1.1e-154 | 2427716 | n/a | 1815046 | n/a, n/a |
| memory_epoch | [2026-06-01, 2026-06-02) | 10694.2 | 4 | <1e-300 | 754.3 | 6.1e-162 | 47906 | n/a | 37220 | n/a, n/a |
| memory_epoch | [2026-06-02, 2026-06-03) | 10953.1 | 4 | <1e-300 | 301.4 | 5.4e-64 | 51593 | n/a | 40648 | n/a, n/a |
| memory_epoch | [2026-06-03, 2026-06-11) | 138326.7 | 4 | <1e-300 | 358.4 | 2.6e-76 | 566596 | n/a | 428277 | n/a, n/a |
| memory_epoch | [2026-06-11, 2026-07-03) | 396424.9 | 4 | <1e-300 | 1031.6 | 4.9e-222 | 1369697 | n/a | 973280 | n/a, n/a |
| memory_epoch | [2026-07-03, end] | 3129100.2 | 4 | <1e-300 | 913.9 | 1.6e-196 | 12202528 | n/a | 9073436 | n/a, n/a |
| entry_kind | first | 4337.7 | 4 | <1e-300 | 125.4 | 3.7e-26 | 23700 | 18154 | 19370 | 0.361, 1.592 |
| entry_kind | session | 3471411.7 | 4 | <1e-300 | 1592.5 | <1e-300 | 13693099 | 10180889 | 10221695 | 1.408, 1.781 |
| entry_kind | note | 680112.2 | 4 | <1e-300 | 4002.6 | <1e-300 | 1468852 | 773006 | 788748 | 0.696, 0.261 |
| entry_kind | rewrite | 2141053.1 | 4 | <1e-300 | 2149.9 | <1e-300 | 7411347 | 5144825 | 5270302 | 0.950, 0.783 |
| entry_kind | fork | 387.5 | 4 | 1.4e-82 | 55.4 | 2.7e-11 | 1636 | 1336 | 1257 | 2.168, 1.802 |

CIs and the Wald test resample agents. With fewer than 5 agents carrying trials (column `agents`) the bootstrap CIs are unstable; with fewer than 5 the Wald test is not computed. The naive LR test is anticonservative because units of one agent are dependent.

Verbatim line retention per consolidation, from the cached line hashes (a cross-check that needs no anchors): share of the input lines that were already in the previous version (old) or arrived in appended text since then (new) and appear unchanged in the output.

| group | regime | consolidations | old lines kept | new lines kept | share of input lines kept: median [IQR] | median units in the input |
|---|---|---|---|---|---|---|
| All standard | post | 49,752 | 0.602 | 0.250 | 0.503 [0.295, 0.697] | 357 |
| All standard | pre | 34,084 | 0.502 | 0.065 | 0.407 [0.242, 0.585] | 209 |
| Anthropic | post | 15,840 | 0.500 | 0.271 | 0.425 [0.248, 0.613] | 422 |
| Anthropic | pre | 17,703 | 0.594 | 0.061 | 0.423 [0.258, 0.583] | 226 |
| Claude Code | pre | 1,764 | 0.672 | 0.216 | 0.630 [0.208, 0.955] | 31 |
| Google | post | 9,251 | 0.823 | 0.467 | 0.716 [0.546, 0.867] | 203 |
| Google | pre | 6,653 | 0.704 | 0.091 | 0.523 [0.353, 0.688] | 109 |
| OpenAI | post | 15,598 | 0.620 | 0.134 | 0.474 [0.294, 0.683] | 345 |
| OpenAI | pre | 7,829 | 0.374 | 0.063 | 0.293 [0.171, 0.444] | 212 |
| Other | post | 9,063 | 0.528 | 0.425 | 0.459 [0.245, 0.633] | 489 |
| Other | pre | 1,899 | 0.617 | 0.065 | 0.402 [0.229, 0.667] | 316 |

## 5. Modification and restoration

| group | g | units at risk | modification rate | modified share of losses |
|---|---|---|---|---|
| All standard | 1 | 4,142,667 | 0.031 [0.028, 0.035] | 0.067 [0.061, 0.074] |
| All standard | 2 | 2,223,673 | 0.034 [0.029, 0.039] | 0.077 [0.066, 0.090] |
| All standard | 3 | 1,245,762 | 0.019 [0.016, 0.021] | 0.067 [0.059, 0.075] |
| All standard | 5 | 706,441 | 0.009 [0.008, 0.011] | 0.056 [0.049, 0.063] |
| All standard | 10 | 353,210 | 0.004 [0.003, 0.005] | 0.047 [0.040, 0.056] |
| Anthropic | 1 | 1,822,944 | 0.033 [0.026, 0.038] | 0.069 [0.062, 0.074] |
| Anthropic | 2 | 947,904 | 0.034 [0.025, 0.045] | 0.075 [0.054, 0.097] |
| Anthropic | 3 | 510,510 | 0.018 [0.013, 0.023] | 0.063 [0.046, 0.078] |
| Anthropic | 5 | 286,084 | 0.008 [0.006, 0.010] | 0.048 [0.036, 0.059] |
| Anthropic | 10 | 140,407 | 0.003 [0.003, 0.004] | 0.037 [0.029, 0.045] |
| OpenAI | 1 | 945,260 | 0.029 [0.027, 0.033] | 0.053 [0.047, 0.062] |
| OpenAI | 2 | 420,016 | 0.031 [0.026, 0.039] | 0.086 [0.074, 0.101] |
| OpenAI | 3 | 268,230 | 0.019 [0.015, 0.022] | 0.075 [0.069, 0.081] |
| OpenAI | 5 | 162,027 | 0.010 [0.007, 0.012] | 0.063 [0.054, 0.070] |
| OpenAI | 10 | 84,832 | 0.003 [0.002, 0.003] | 0.039 [0.035, 0.042] |
| Google | 1 | 292,680 | 0.031 [0.020, 0.040] | 0.082 [0.070, 0.110] |
| Google | 2 | 181,729 | 0.032 [0.017, 0.049] | 0.091 [0.059, 0.138] |
| Google | 3 | 117,967 | 0.016 [0.009, 0.024] | 0.070 [0.048, 0.099] |
| Google | 5 | 75,654 | 0.007 [0.005, 0.009] | 0.051 [0.040, 0.065] |
| Google | 10 | 43,891 | 0.004 [0.004, 0.007] | 0.066 [0.063, 0.070] |
| Other | 1 | 1,081,783 | 0.030 [0.026, 0.037] | 0.079 [0.064, 0.108] |
| Other | 2 | 674,024 | 0.035 [0.031, 0.042] | 0.073 [0.063, 0.096] |
| Other | 3 | 349,055 | 0.021 [0.018, 0.026] | 0.067 [0.059, 0.086] |
| Other | 5 | 182,676 | 0.012 [0.009, 0.016] | 0.062 [0.050, 0.088] |
| Other | 10 | 84,080 | 0.006 [0.004, 0.010] | 0.062 [0.044, 0.103] |
| Claude Code | 1 | 9,653 | 0.097 [0.091, 0.103] | 0.205 [0.194, 0.217] |
| Claude Code | 2 | 5,083 | 0.039 [0.034, 0.044] | 0.150 [0.132, 0.171] |
| Claude Code | 3 | 3,762 | 0.023 [0.019, 0.028] | 0.116 [0.095, 0.141] |
| Claude Code | 5 | 2,562 | 0.011 [0.007, 0.015] | 0.078 [0.054, 0.111] |
| Claude Code | 10 | 1,352 | 0.021 [0.014, 0.030] | 0.209 [0.149, 0.285] |

| group | lost | lost with later trials | restored | share restored | reappended | recreated | median gap (consolidations) | share restored at the next consolidation | re-lost after restoration |
|---|---|---|---|---|---|---|---|---|---|
| All standard | 4,126,997 | 4,123,882 | 684,369 | 0.166 | 318,277 | 366,092 | 48.0 | 0.122 | 679,836 |
| Anthropic | 1,817,531 | 1,816,695 | 309,876 | 0.171 | 158,274 | 151,602 | 67.0 | 0.115 | 308,352 |
| OpenAI | 941,858 | 941,316 | 183,956 | 0.195 | 43,063 | 140,893 | 23.0 | 0.148 | 183,028 |
| Google | 291,471 | 291,318 | 36,938 | 0.127 | 21,657 | 15,281 | 74.0 | 0.094 | 36,609 |
| Other | 1,076,137 | 1,074,553 | 153,599 | 0.143 | 95,283 | 58,316 | 50.0 | 0.110 | 151,847 |
| Claude Code | 9,595 | 9,595 | 1,931 | 0.201 | 6 | 1,925 | 18.0 | 0.139 | 1,923 |

A restoration is the same unit key reappearing. For quantities with a generic context key (e.g. a small count of tasks) a later, unrelated fact can share the key, so restoration shares are upper bounds; by anchor type they are in memory_by_anchor.csv.

## 6. Regime (perma-computer-use), entry kind and memory-system epochs

| scope | stratum | agents | unit-trials | h1 | h2 | h3-4 | h5-8 | h9+ | geometric h |
|---|---|---|---|---|---|---|---|---|---|
| regime:pre | All standard | 23 | 6,859,471 | 0.599 [0.577, 0.621] | 0.320 [0.296, 0.338] | 0.199 [0.182, 0.215] | 0.114 [0.105, 0.125] | 0.026 [0.023, 0.031] | 0.153 |
| regime:pre | Anthropic | 9 | 3,692,909 | 0.612 [0.588, 0.632] | 0.336 [0.313, 0.354] | 0.202 [0.177, 0.227] | 0.116 [0.103, 0.134] | 0.026 [0.022, 0.035] | 0.161 |
| regime:pre | OpenAI | 9 | 1,544,417 | 0.592 [0.550, 0.706] | 0.320 [0.275, 0.371] | 0.208 [0.172, 0.234] | 0.118 [0.095, 0.134] | 0.029 [0.023, 0.040] | 0.165 |
| regime:pre | Google | 3 | 940,587 | 0.557 [0.410, 0.616] | 0.293 [0.260, 0.324] | 0.178 [0.146, 0.186] | 0.106 [0.095, 0.109] | 0.020 [0.019, 0.028] | 0.105 |
| regime:pre | Other | 2 | 681,558 | 0.588 [0.536, 0.623] | 0.258 [0.200, 0.305] | 0.179 [0.156, 0.202] | 0.104 [0.096, 0.113] | 0.032 [0.028, 0.037] | 0.150 |
| regime:post | All standard | 34 | 18,926,054 | 0.416 [0.352, 0.476] | 0.467 [0.428, 0.500] | 0.267 [0.243, 0.292] | 0.151 [0.135, 0.167] | 0.025 [0.021, 0.031] | 0.163 |
| regime:post | Anthropic | 11 | 6,479,347 | 0.416 [0.323, 0.499] | 0.501 [0.464, 0.536] | 0.280 [0.255, 0.315] | 0.159 [0.141, 0.182] | 0.028 [0.020, 0.041] | 0.189 |
| regime:post | OpenAI | 9 | 5,007,739 | 0.542 [0.469, 0.584] | 0.375 [0.328, 0.412] | 0.232 [0.196, 0.256] | 0.137 [0.115, 0.153] | 0.020 [0.015, 0.025] | 0.137 |
| regime:post | Google | 4 | 2,627,134 | 0.288 [0.142, 0.473] | 0.369 [0.264, 0.478] | 0.210 [0.150, 0.279] | 0.115 [0.086, 0.206] | 0.017 [0.015, 0.029] | 0.073 |
| regime:post | Other | 10 | 4,811,834 | 0.354 [0.254, 0.463] | 0.496 [0.413, 0.549] | 0.292 [0.236, 0.350] | 0.165 [0.132, 0.210] | 0.036 [0.027, 0.056] | 0.202 |
| memory_epoch | [2025-04-02, 2025-04-15) | 4 | 17,007 | 0.784 [0.684, 0.884] | 0.410 [0.376, 0.530] | 0.253 [0.197, 0.470] | 0.123 [0.102, 0.269] | 0.035 [0.028, 0.191] | 0.440 |
| memory_epoch | [2025-04-15, 2025-04-16) | 3 | 1,594 | 0.598 [0.467, 0.750] | 0.199 [0.106, 0.538] | 0.088 [0.079, 0.500] | 0.135 [0.000, 0.136] | 0.008 [0.008, 0.008] | 0.216 |
| memory_epoch | [2025-04-16, 2025-08-20) | 10 | 697,535 | 0.633 [0.573, 0.712] | 0.308 [0.264, 0.367] | 0.181 [0.149, 0.242] | 0.109 [0.091, 0.158] | 0.025 [0.018, 0.054] | 0.151 |
| memory_epoch | [2025-08-20, 2025-09-05) | 7 | 206,880 | 0.646 [0.572, 0.695] | 0.324 [0.270, 0.370] | 0.183 [0.166, 0.202] | 0.104 [0.102, 0.109] | 0.027 [0.022, 0.037] | 0.170 |
| memory_epoch | [2025-09-05, 2025-10-14) | 8 | 641,532 | 0.579 [0.517, 0.650] | 0.251 [0.205, 0.324] | 0.149 [0.132, 0.182] | 0.085 [0.078, 0.098] | 0.025 [0.018, 0.031] | 0.114 |
| memory_epoch | [2025-10-14, 2025-11-25) | 10 | 1,124,082 | 0.610 [0.578, 0.642] | 0.319 [0.293, 0.339] | 0.201 [0.183, 0.217] | 0.116 [0.105, 0.128] | 0.022 [0.016, 0.034] | 0.140 |
| memory_epoch | [2025-11-25, 2026-03-11) | 15 | 3,756,720 | 0.590 [0.565, 0.610] | 0.330 [0.307, 0.350] | 0.210 [0.190, 0.227] | 0.121 [0.109, 0.133] | 0.028 [0.024, 0.034] | 0.162 |
| memory_epoch | [2026-03-11, 2026-03-12) | 11 | 44,920 | 0.586 [0.531, 0.624] | 0.336 [0.299, 0.372] | 0.192 [0.158, 0.226] | 0.117 [0.102, 0.131] | 0.024 [0.018, 0.035] | 0.149 |
| memory_epoch | [2026-03-12, 2026-03-16) | 11 | 87,563 | 0.607 [0.574, 0.641] | 0.322 [0.297, 0.344] | 0.194 [0.162, 0.221] | 0.109 [0.096, 0.122] | 0.022 [0.016, 0.033] | 0.144 |
| memory_epoch | [2026-03-16, 2026-03-24) | 12 | 281,638 | 0.563 [0.517, 0.599] | 0.314 [0.269, 0.351] | 0.184 [0.155, 0.217] | 0.107 [0.090, 0.130] | 0.029 [0.025, 0.036] | 0.149 |
| memory_epoch | [2026-03-24, 2026-03-26) | 12 | 109,348 | 0.499 [0.429, 0.552] | 0.313 [0.262, 0.352] | 0.203 [0.179, 0.228] | 0.129 [0.107, 0.151] | 0.036 [0.030, 0.044] | 0.169 |
| memory_epoch | [2026-03-26, 2026-06-01) | 18 | 2,409,066 | 0.481 [0.388, 0.549] | 0.479 [0.418, 0.530] | 0.269 [0.233, 0.308] | 0.148 [0.130, 0.166] | 0.031 [0.027, 0.039] | 0.203 |
| memory_epoch | [2026-06-01, 2026-06-02) | 18 | 51,546 | 0.405 [0.340, 0.461] | 0.443 [0.388, 0.502] | 0.245 [0.204, 0.293] | 0.135 [0.109, 0.167] | 0.028 [0.020, 0.040] | 0.176 |
| memory_epoch | [2026-06-02, 2026-06-03) | 18 | 50,011 | 0.438 [0.358, 0.505] | 0.488 [0.421, 0.556] | 0.279 [0.236, 0.331] | 0.157 [0.127, 0.186] | 0.040 [0.026, 0.056] | 0.211 |
| memory_epoch | [2026-06-03, 2026-06-11) | 19 | 639,687 | 0.443 [0.360, 0.519] | 0.421 [0.368, 0.477] | 0.240 [0.210, 0.280] | 0.132 [0.110, 0.159] | 0.028 [0.022, 0.035] | 0.162 |
| memory_epoch | [2026-06-11, 2026-07-03) | 20 | 1,725,112 | 0.465 [0.388, 0.525] | 0.436 [0.382, 0.485] | 0.223 [0.186, 0.266] | 0.122 [0.106, 0.144] | 0.023 [0.020, 0.028] | 0.136 |
| memory_epoch | [2026-07-03, end] | 32 | 13,941,284 | 0.395 [0.332, 0.456] | 0.471 [0.428, 0.505] | 0.274 [0.248, 0.299] | 0.156 [0.138, 0.173] | 0.024 [0.019, 0.031] | 0.159 |
| entry_kind | first | 44 | 261,283 | 0.218 [0.170, 0.269] | 0.109 [0.066, 0.158] | 0.049 [0.030, 0.073] | 0.039 [0.024, 0.057] | 0.004 [0.003, 0.005] | 0.008 |
| entry_kind | session | 45 | 15,673,282 | 0.385 [0.313, 0.452] | 0.486 [0.448, 0.514] | 0.268 [0.244, 0.290] | 0.146 [0.132, 0.160] | 0.025 [0.021, 0.030] | 0.158 |
| entry_kind | note | 27 | 1,564,633 | 0.728 [0.694, 0.761] | 0.348 [0.318, 0.365] | 0.191 [0.177, 0.204] | 0.102 [0.096, 0.111] | 0.021 [0.019, 0.024] | 0.179 |
| entry_kind | rewrite | 45 | 8,285,053 | 0.551 [0.517, 0.576] | 0.336 [0.303, 0.363] | 0.228 [0.206, 0.247] | 0.137 [0.125, 0.150] | 0.027 [0.024, 0.032] | 0.165 |
| entry_kind | fork | 7 | 1,274 | 0.471 [0.216, 0.876] | 0.684 [0.056, 0.789] | 0.366 [0.176, 0.520] | 0.096 [0.029, 0.278] | 0.041 [0.022, 0.162] | 0.341 |

Regime and epoch strata are trial-level: a consolidation counts in the regime (epoch) of its own row, so units that cross a boundary enter the later risk sets at their current g. Epochs run between consecutive dates of memory-category CHANGELOG entries (start date included). Entry kind is the relation of the row where the unit first appeared (session = scaffold session block, note = self-note append, rewrite = new in a consolidation output, first = the agent's first row).

## 7. Heterogeneity versus duration dependence (beta-discrete-Weibull)

BdW (Fader, Hardie, Liu, Davin and Steenburgh 2018): each fact has its own theta ~ Beta(a, b) and S(g | theta) = (1 - theta)^(g^c). c = 1 is the beta-geometric (heterogeneity alone); c < 1 means a fact's own hazard falls with the consolidations it has survived. Maximum likelihood on the same risk sets as section 4 (right-censoring included, every g kept individually); regime cohorts are the facts whose first trial falls before (pre, censored at the agent's switch) or after (post) the agent's switch to perma-computer-use, so neither cohort is left-truncated. The CI of c resamples agents (500 refits); Claude Code (one agent) has only a profile-likelihood CI, which treats facts as independent. The LR test of c = 1 (df 1) treats facts as independent and is anticonservative at these sample sizes; the decision rule uses the CI: if it covers 1 the falling population hazard is consistent with heterogeneity alone, if it lies below 1 there is duration dependence beyond heterogeneity.

| scope | stratum | from g | agents | facts | c [95% CI] | CI | LR (c = 1) | p | AIC BdW - beta-geom | AIC BdW - piecewise | lowest AIC | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| family | All standard | 1 | 45 | 4,142,667 | 2.604 [1.775, 6.627] | bootstrap | 105332.1 | <1e-300 | -105330 | -397497 | bdw | c > 1: a fact's own hazard rises with g |
| family | Anthropic | 1 | 15 | 1,822,944 | 3.307 [1.757, 10.647] | bootstrap | 52366.4 | <1e-300 | -52364 | -158160 | bdw | c > 1: a fact's own hazard rises with g |
| family | OpenAI | 1 | 14 | 945,260 | 1.099 [0.875, 1.793] | bootstrap | 254.4 | 2.9e-57 | -252 | -97743 | bdw | heterogeneity alone (c consistent with 1) |
| family | Google | 1 | 5 | 292,680 | 1.785 [0.924, 8.067] | bootstrap | 4225.7 | <1e-300 | -4224 | -51091 | bdw | heterogeneity alone (c consistent with 1) |
| family | Other | 1 | 11 | 1,081,783 | 4.048 [2.154, 13.974] | bootstrap | 82541.6 | <1e-300 | -82540 | -73779 | bdw | c > 1: a fact's own hazard rises with g |
| family | Claude Code | 1 | 1 | 9,653 | 0.528 [0.517, 0.539] | profile | 541.4 | 9.4e-120 | -539 | -27 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | pre | 1 | 23 | 1,054,178 | 0.669 [0.572, 0.745] | bootstrap | 4570.4 | <1e-300 | -4568 | -85323 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | post | 1 | 34 | 3,088,489 | 3.857 [2.332, 10.271] | bootstrap | 166141.8 | <1e-300 | -166140 | -302712 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | url | 1 | 45 | 105,054 | 1.333 [0.944, 1.807] | bootstrap | 653.2 | 4.4e-144 | -651 | -14086 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | email | 1 | 45 | 5,220 | 0.694 [0.554, 0.919] | bootstrap | 77.8 | 1.2e-18 | -76 | -1577 | bdw | duration dependence: a fact's own hazard falls with g |
| anchor_type | phone | 1 | 26 | 207 | 0.725 [0.469, 1.928] | bootstrap | 2.2 | 0.14 | -0 | -10 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | date | 1 | 45 | 24,522 | 0.591 [0.499, 0.736] | bootstrap | 801.6 | 2.4e-176 | -800 | -2467 | bdw | duration dependence: a fact's own hazard falls with g |
| anchor_type | time | 1 | 45 | 689,941 | 2.362 [1.627, 7.885] | bootstrap | 7164.6 | <1e-300 | -7163 | -8477 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | money | 1 | 42 | 32,770 | 1.217 [0.950, 1.482] | bootstrap | 74.2 | 7.1e-18 | -72 | -1926 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | percent | 1 | 44 | 103,973 | 1.655 [1.305, 2.110] | bootstrap | 1094.1 | 6.4e-240 | -1092 | -4527 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | number | 1 | 45 | 2,237,529 | 2.571 [1.741, 4.538] | bootstrap | 81203.5 | <1e-300 | -81202 | -72598 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | agent | 1 | 45 | 3,151 | 1.245 [0.658, 6.045] | bootstrap | 2.2 | 0.14 | -0 | -1304 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | person | 1 | 45 | 232,313 | 1.479 [1.123, 2.171] | bootstrap | 1737.0 | <1e-300 | -1735 | -36732 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | org | 1 | 45 | 471,556 | 1.094 [0.889, 1.453] | bootstrap | 207.9 | 3.9e-47 | -206 | -80196 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | gpe | 1 | 45 | 45,540 | 1.196 [0.912, 1.689] | bootstrap | 116.9 | 3e-27 | -115 | -14384 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | product | 1 | 45 | 48,029 | 1.107 [0.874, 1.544] | bootstrap | 40.1 | 2.4e-10 | -38 | -10756 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | event | 1 | 42 | 8,832 | 1.061 [0.801, 1.635] | bootstrap | 1.9 | 0.17 | 0 | -1740 | beta_geometric | heterogeneity alone (c consistent with 1) |
| anchor_type | work_of_art | 1 | 45 | 134,030 | 1.560 [1.151, 2.198] | bootstrap | 1991.9 | <1e-300 | -1990 | -27086 | bdw | c > 1: a fact's own hazard rises with g |
| family | All standard | 2 | 45 | 2,223,673 | 0.045 [0.042, 0.081] | bootstrap | 2872.9 | <1e-300 | -2871 | -401562 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | pre | 2 | 23 | 422,042 | 0.175 [0.155, 0.206] | bootstrap | 3905.2 | <1e-300 | -3903 | -87536 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | post | 2 | 34 | 1,801,457 | 0.828 [0.536, 11.608] | bootstrap | 138.7 | 5.2e-32 | -137 | -302906 | bdw | heterogeneity alone (c consistent with 1) |

From g = 2 rows use the likelihood conditional on surviving the first consolidation (the same model, with the g = 1 term dropped). After the switch to perma-computer-use the hazard rises from g = 1 to g = 2 (section 6: the consolidation right after a session keeps that session's facts, the next one prunes them); a BdW can only produce that rise with c > 1, so c > 1 in scopes dominated by post-switch facts reflects this two-step pattern rather than facts that wear out.

Observed and fitted hazards at g = 1, 2, 5, 10 (families and regime cohorts):

| scope | stratum | from g | g = 1 obs / BdW / BG | g = 2 | g = 5 | g = 10 |
|---|---|---|---|---|---|---|
| family | All standard | 1 | 0.463 / 0.463 / 0.488 | 0.439 / 0.437 / 0.347 | 0.169 / 0.175 / 0.185 | 0.088 / 0.087 / 0.104 |
| family | Anthropic | 1 | 0.480 / 0.480 / 0.506 | 0.461 / 0.461 / 0.360 | 0.170 / 0.178 / 0.193 | 0.092 / 0.088 / 0.109 |
| family | OpenAI | 1 | 0.555 / 0.556 / 0.557 | 0.361 / 0.355 / 0.346 | 0.157 / 0.162 / 0.162 | 0.080 / 0.084 / 0.086 |
| family | Google | 1 | 0.379 / 0.380 / 0.401 | 0.351 / 0.340 / 0.281 | 0.140 / 0.148 / 0.148 | 0.068 / 0.074 / 0.083 |
| family | Other | 1 | 0.376 / 0.376 / 0.434 | 0.481 / 0.481 / 0.341 | 0.189 / 0.193 / 0.207 | 0.098 / 0.096 / 0.126 |
| family | Claude Code | 1 | 0.473 / 0.471 / 0.444 | 0.258 / 0.245 / 0.315 | 0.135 / 0.153 / 0.168 | 0.099 / 0.110 / 0.095 |
| regime_cohort | pre | 1 | 0.599 / 0.600 / 0.595 | 0.320 / 0.303 / 0.339 | 0.139 / 0.147 / 0.148 | 0.074 / 0.082 / 0.076 |
| regime_cohort | post | 1 | 0.416 / 0.416 / 0.459 | 0.467 / 0.467 / 0.344 | 0.180 / 0.182 / 0.196 | 0.093 / 0.091 / 0.114 |
| family | All standard | 2 | n/a | 0.439 / 0.432 / 0.434 | 0.169 / 0.174 / 0.176 | 0.088 / 0.089 / 0.088 |
| regime_cohort | pre | 2 | n/a | 0.320 / 0.318 / 0.308 | 0.139 / 0.140 / 0.151 | 0.074 / 0.078 / 0.082 |
| regime_cohort | post | 2 | n/a | 0.467 / 0.463 / 0.464 | 0.180 / 0.184 / 0.184 | 0.093 / 0.092 / 0.092 |

Identification: in single-spell data heterogeneity and duration dependence trade off (a falling population hazard can come from either), so c rests on the functional form of the Beta mixing distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed (section 8).

## 8. Repeated spells of restored facts

Facts that were lost and later restored, with at least one consolidation after the restoration. Spell 1 runs from entry to the first loss, spell 2 from the restoring consolidation to the next loss (or the agent's last consolidation); trial g counts consolidations from the start of each spell, so both hazards come from the same facts at the same g. `like for like` keeps facts whose first spell also began as new content of a consolidation output and whose restoration was recreated by a consolidation, so both spells start the same way. CIs and the paired difference (spell 2 - spell 1) resample agents. These are descriptions: spell 1 is selected to end in a loss, and early losses leave more time for a restoration, so spell-1 hazards of restored facts are biased upward and a negative difference is expected even if nothing about the fact changed; and a restoration can be a key collision rather than the same fact (restoration shares in section 5 are upper bounds).

| check | value |
|---|---|
| restored facts | 686,300 |
| with >= 1 trial in spell 2 | 685,792 |
| spell 2 ended in a loss | 681,759 |
| re-lost facts in the chain (n_reloss > 0) | 681,759 |
| facts where chain and row-level spells disagree (expected 0) | n/a (v2 presence is not row-level) |
| restored facts absent from the restoring output (expected 0) | n/a |

| group | subset | facts | g | spell 1: n, h [95% CI] | spell 2: n, h [95% CI] | spell 2 - spell 1 [95% CI] | all facts, spell 1 |
|---|---|---|---|---|---|---|---|
| All standard | all restored | 683,861 | 1 | 683,861, 0.465 [0.408, 0.508] | 683,861, 0.461 [0.429, 0.484] | -0.004 [-0.040, 0.043] | 0.463 |
| All standard | all restored | 683,861 | 2 | 365,930, 0.378 [0.357, 0.400] | 368,482, 0.288 [0.260, 0.310] | -0.090 [-0.116, -0.066] | 0.439 |
| All standard | all restored | 683,861 | 3-4 | 397,156, 0.228 [0.213, 0.242] | 466,672, 0.199 [0.181, 0.215] | -0.029 [-0.037, -0.021] | 0.251 |
| All standard | all restored | 683,861 | 5-8 | 441,771, 0.130 [0.121, 0.140] | 548,750, 0.125 [0.113, 0.137] | -0.005 [-0.010, -0.001] | 0.141 |
| All standard | all restored | 683,861 | 9+ | 3,048,152, 0.026 [0.023, 0.030] | 3,735,094, 0.026 [0.022, 0.031] | -0.000 [-0.003, 0.003] | 0.025 |
| All standard | like for like | 157,543 | 1 | 157,543, 0.521 [0.490, 0.544] | 157,543, 0.489 [0.452, 0.518] | -0.032 [-0.042, -0.022] | 0.463 |
| All standard | like for like | 157,543 | 2 | 75,394, 0.335 [0.303, 0.353] | 80,343, 0.309 [0.267, 0.332] | -0.026 [-0.040, -0.016] | 0.439 |
| All standard | like for like | 157,543 | 3-4 | 87,885, 0.226 [0.202, 0.242] | 97,412, 0.216 [0.189, 0.234] | -0.010 [-0.018, -0.003] | 0.251 |
| All standard | like for like | 157,543 | 5-8 | 96,452, 0.137 [0.123, 0.147] | 108,894, 0.134 [0.116, 0.146] | -0.003 [-0.009, 0.001] | 0.141 |
| All standard | like for like | 157,543 | 9+ | 547,574, 0.031 [0.027, 0.036] | 651,191, 0.029 [0.024, 0.034] | -0.002 [-0.007, 0.001] | 0.025 |
| Anthropic | all restored | 309,702 | 1 | 309,702, 0.481 [0.387, 0.540] | 309,702, 0.479 [0.430, 0.509] | -0.002 [-0.043, 0.058] | 0.480 |
| Anthropic | all restored | 309,702 | 2 | 160,845, 0.387 [0.374, 0.399] | 161,292, 0.291 [0.255, 0.322] | -0.096 [-0.130, -0.069] | 0.461 |
| Anthropic | all restored | 309,702 | 3-4 | 171,722, 0.229 [0.213, 0.244] | 202,741, 0.203 [0.179, 0.225] | -0.026 [-0.037, -0.017] | 0.256 |
| Anthropic | all restored | 309,702 | 5-8 | 190,820, 0.131 [0.118, 0.146] | 235,653, 0.130 [0.112, 0.149] | -0.002 [-0.009, 0.005] | 0.144 |
| Anthropic | all restored | 309,702 | 9+ | 1,296,300, 0.026 [0.021, 0.036] | 1,408,075, 0.029 [0.024, 0.038] | 0.003 [-0.002, 0.007] | 0.027 |
| OpenAI | all restored | 183,868 | 1 | 183,868, 0.525 [0.464, 0.551] | 183,868, 0.447 [0.393, 0.472] | -0.078 [-0.120, -0.041] | 0.555 |
| OpenAI | all restored | 183,868 | 2 | 87,339, 0.335 [0.310, 0.357] | 101,688, 0.292 [0.225, 0.322] | -0.043 [-0.105, -0.017] | 0.361 |
| OpenAI | all restored | 183,868 | 3-4 | 101,993, 0.219 [0.190, 0.231] | 128,422, 0.198 [0.153, 0.221] | -0.021 [-0.040, -0.009] | 0.226 |
| OpenAI | all restored | 183,868 | 5-8 | 115,111, 0.129 [0.112, 0.139] | 151,644, 0.123 [0.097, 0.139] | -0.006 [-0.016, 0.001] | 0.131 |
| OpenAI | all restored | 183,868 | 9+ | 806,606, 0.026 [0.021, 0.029] | 1,189,226, 0.023 [0.017, 0.029] | -0.003 [-0.005, 0.000] | 0.022 |
| Google | all restored | 36,918 | 1 | 36,918, 0.360 [0.204, 0.508] | 36,918, 0.387 [0.288, 0.446] | 0.028 [-0.087, 0.135] | 0.379 |
| Google | all restored | 36,918 | 2 | 23,631, 0.322 [0.260, 0.373] | 22,609, 0.215 [0.159, 0.260] | -0.108 [-0.116, -0.096] | 0.351 |
| Google | all restored | 36,918 | 3-4 | 28,807, 0.180 [0.148, 0.220] | 32,598, 0.150 [0.118, 0.193] | -0.031 [-0.049, -0.016] | 0.202 |
| Google | all restored | 36,918 | 5-8 | 36,464, 0.103 [0.087, 0.131] | 43,841, 0.095 [0.077, 0.120] | -0.008 [-0.014, -0.001] | 0.113 |
| Google | all restored | 36,918 | 9+ | 423,738, 0.017 [0.014, 0.027] | 541,797, 0.016 [0.013, 0.023] | -0.001 [-0.008, 0.006] | 0.018 |
| Other | all restored | 153,373 | 1 | 153,373, 0.386 [0.281, 0.469] | 153,373, 0.459 [0.380, 0.513] | 0.073 [-0.027, 0.182] | 0.376 |
| Other | all restored | 153,373 | 2 | 94,115, 0.416 [0.353, 0.467] | 82,893, 0.296 [0.238, 0.348] | -0.121 [-0.148, -0.100] | 0.481 |
| Other | all restored | 153,373 | 3-4 | 94,634, 0.249 [0.206, 0.292] | 102,911, 0.208 [0.166, 0.254] | -0.041 [-0.052, -0.032] | 0.281 |
| Other | all restored | 153,373 | 5-8 | 99,376, 0.141 [0.118, 0.169] | 117,612, 0.130 [0.106, 0.161] | -0.011 [-0.017, -0.004] | 0.157 |
| Other | all restored | 153,373 | 9+ | 521,508, 0.033 [0.028, 0.046] | 595,996, 0.034 [0.028, 0.046] | 0.001 [-0.004, 0.006] | 0.035 |
| Claude Code | all restored | 1,931 | 1 | 1,931, 0.444 [0.422, 0.467] | 1,931, 0.438 [0.416, 0.460] | -0.006 [n/a, n/a] | 0.473 |
| Claude Code | all restored | 1,931 | 2 | 1,073, 0.263 [0.237, 0.290] | 1,083, 0.270 [0.244, 0.297] | 0.007 [n/a, n/a] | 0.258 |
| Claude Code | all restored | 1,931 | 3-4 | 1,424, 0.188 [0.169, 0.209] | 1,410, 0.196 [0.176, 0.217] | 0.008 [n/a, n/a] | 0.176 |
| Claude Code | all restored | 1,931 | 5-8 | 1,626, 0.149 [0.133, 0.168] | 1,688, 0.122 [0.107, 0.139] | -0.027 [n/a, n/a] | 0.125 |
| Claude Code | all restored | 1,931 | 9+ | 3,529, 0.079 [0.071, 0.089] | 4,200, 0.072 [0.065, 0.080] | -0.007 [n/a, n/a] | 0.092 |

Monthly hazards for module C: `outputs/tables/memory_hazard_monthly.parquet` (and .csv), 90 rows, 18 PT calendar months (2025-04-01 to 2026-09-01) x 5 groups, columns date, group, h1, h2, h3_4 (hazards of the consolidations in that month, null below 30 facts at risk; 5 null h1) and n_at_risk (all unit-trials of the month).

## 9. Memory-category CHANGELOG entries (+/- 5 run days, standard agents)

Consolidations whose run day falls in the window before the entry's first day or after its last day. Hazards need at least the reporting threshold of unit-trials; the difference (after - before) gets a paired agent-bootstrap CI only when at least 3 agents carry trials on each side.

| entry | date | cons before | cons after | h(g=1) before | h(g=1) after | diff [95% CI] | h(g>=2) before | h(g>=2) after | diff [95% CI] |
|---|---|---|---|---|---|---|---|---|---|
| cl-2025-04-02-2 | 2025-04-02 | 0 | 113 | n/a | 0.787 | n/a [n/a, n/a] | n/a | 0.162 | n/a [n/a, n/a] |
| cl-2025-04-15-1 | 2025-04-15 | 57 | 89 | 0.795 | 0.650 | -0.145 [-0.262, -0.035] | 0.120 | 0.081 | -0.039 [-0.495, 0.058] |
| cl-2025-04-16-1 | 2025-04-16 | 48 | 99 | 0.768 | 0.699 | -0.069 [-0.145, 0.034] | 0.103 | 0.079 | -0.024 [-0.442, 0.162] |
| cl-2025-08-20-1 | 2025-08-20 | 229 | 338 | 0.656 | 0.680 | 0.025 [-0.022, 0.063] | 0.079 | 0.097 | 0.018 [-0.070, 0.039] |
| cl-2025-09-05-2 | 2025-09-05 | 661 | 362 | 0.623 | 0.548 | -0.075 [-0.196, 0.018] | 0.062 | 0.065 | 0.003 [-0.024, 0.011] |
| cl-2025-10-14-1 | 2025-10-14 | 485 | 753 | 0.559 | 0.610 | 0.052 [0.028, 0.081] | 0.050 | 0.048 | -0.002 [-0.019, 0.032] |
| cl-2025-11-25-1 | 2025-11-25 | 1,019 | 1,210 | 0.577 | 0.584 | 0.007 [-0.014, 0.034] | 0.071 | 0.078 | 0.007 [-0.008, 0.017] |
| cl-2026-03-11-1 | 2026-03-11 | 1,270 | 1,140 | 0.567 | 0.594 | 0.028 [-0.005, 0.052] | 0.090 | 0.071 | -0.019 [-0.032, -0.007] |
| cl-2026-03-12-3 | 2026-03-12 | 1,131 | 1,167 | 0.575 | 0.590 | 0.015 [-0.017, 0.042] | 0.088 | 0.069 | -0.018 [-0.033, -0.003] |
| cl-2026-03-16-1 | 2026-03-16 | 1,067 | 1,225 | 0.586 | 0.561 | -0.025 [-0.055, -0.001] | 0.078 | 0.073 | -0.006 [-0.022, 0.013] |
| cl-2026-03-24-1 | 2026-03-24 | 1,225 | 928 | 0.561 | 0.496 | -0.065 [-0.121, -0.025] | 0.073 | 0.091 | 0.019 [0.002, 0.041] |
| cl-2026-03-26-1 | 2026-03-26 | 1,152 | 890 | 0.522 | 0.487 | -0.035 [-0.074, -0.005] | 0.085 | 0.096 | 0.011 [-0.003, 0.029] |
| cl-2026-03-26-3 | 2026-03-26 | 1,152 | 890 | 0.522 | 0.487 | -0.035 [-0.074, -0.005] | 0.085 | 0.096 | 0.011 [-0.003, 0.029] |
| cl-2026-06-01-3 | 2026-06-01 | 1,030 | 1,231 | 0.406 | 0.441 | 0.035 [0.006, 0.067] | 0.130 | 0.141 | 0.011 [-0.017, 0.034] |
| cl-2026-06-02-1 | 2026-06-02 | 948 | 1,461 | 0.400 | 0.432 | 0.032 [-0.005, 0.070] | 0.126 | 0.131 | 0.005 [-0.026, 0.030] |
| cl-2026-06-03-2 | 2026-06-03 | 951 | 1,795 | 0.410 | 0.442 | 0.032 [-0.008, 0.072] | 0.130 | 0.103 | -0.027 [-0.065, 0.009] |
| cl-2026-06-11-1 | 2026-06-11 | 1,795 | 1,471 | 0.442 | 0.470 | 0.028 [-0.008, 0.060] | 0.103 | 0.090 | -0.013 [-0.022, 0.001] |
| cl-2026-07-03-2 | 2026-07-03 | 2,399 | 3,211 | 0.460 | 0.442 | -0.018 [-0.079, 0.052] | 0.083 | 0.093 | 0.011 [-0.018, 0.036] |

## 10. By anchor type (standard agents pooled)

| type | units | unit-trials | h1 | h2 | h9+ | geometric h | modification rate | restored share of lost |
|---|---|---|---|---|---|---|---|---|
| url | 105,054 | 1,053,640 | 0.356 [0.271, 0.426] | 0.314 [0.283, 0.346] | 0.024 [0.020, 0.031] | 0.099 | 0.003 | 0.123 |
| email | 5,220 | 105,187 | 0.344 [0.302, 0.386] | 0.210 [0.175, 0.252] | 0.016 [0.011, 0.025] | 0.049 | 0.001 | 0.240 |
| phone | 207 | 1,485 | 0.377 [0.181, 0.518] | 0.271 [0.192, 0.358] | 0.052 [0.031, 0.090] | 0.139 | 0.001 | 0.130 |
| date | 24,522 | 388,095 | 0.317 [0.269, 0.359] | 0.217 [0.187, 0.246] | 0.026 [0.021, 0.032] | 0.062 | 0.006 | 0.442 |
| time | 689,941 | 1,488,360 | 0.648 [0.588, 0.694] | 0.568 [0.519, 0.608] | 0.078 [0.070, 0.088] | 0.463 | 0.042 | 0.157 |
| money | 32,770 | 212,707 | 0.438 [0.387, 0.490] | 0.354 [0.312, 0.390] | 0.033 [0.026, 0.049] | 0.154 | 0.005 | 0.142 |
| percent | 103,973 | 433,913 | 0.493 [0.429, 0.542] | 0.438 [0.397, 0.470] | 0.045 [0.036, 0.061] | 0.239 | 0.011 | 0.149 |
| number | 2,237,529 | 8,067,197 | 0.454 [0.382, 0.518] | 0.496 [0.456, 0.527] | 0.054 [0.046, 0.064] | 0.277 | 0.022 | 0.182 |
| agent | 3,151 | 487,639 | 0.269 [0.224, 0.313] | 0.168 [0.140, 0.198] | 0.002 [0.002, 0.003] | 0.006 | 0.000 | 0.867 |
| person | 232,313 | 2,781,977 | 0.382 [0.329, 0.426] | 0.328 [0.302, 0.353] | 0.019 [0.015, 0.025] | 0.083 | 0.002 | 0.162 |
| org | 471,556 | 6,351,781 | 0.391 [0.331, 0.433] | 0.294 [0.269, 0.319] | 0.018 [0.015, 0.021] | 0.074 | 0.002 | 0.127 |
| gpe | 45,540 | 1,369,730 | 0.239 [0.207, 0.268] | 0.229 [0.206, 0.252] | 0.012 [0.010, 0.014] | 0.033 | 0.000 | 0.195 |
| product | 48,029 | 1,006,336 | 0.284 [0.238, 0.325] | 0.247 [0.224, 0.271] | 0.015 [0.012, 0.019] | 0.047 | 0.000 | 0.141 |
| event | 8,832 | 152,541 | 0.350 [0.293, 0.397] | 0.276 [0.241, 0.311] | 0.016 [0.013, 0.019] | 0.057 | 0.000 | 0.078 |
| work_of_art | 134,030 | 1,884,937 | 0.297 [0.241, 0.340] | 0.308 [0.275, 0.341] | 0.019 [0.016, 0.023] | 0.071 | 0.001 | 0.079 |

## 11. Labelling file and memory_facts

- `/home/enxinson/ai-village-swarm-dynamics/data/labels/memory_pairs_rule_v3.csv` (mode 600): rule_label_v3 for the 500 units of memory_pairs.csv (100 pairs), labels {'dropped': 127, 'restored': 70, 'new': 84, 'kept': 188, 'modified': 31}; checks {'unit_not_found': 0, 'v1_label_differs': 0} (all expected 0).
- `/home/enxinson/ai-village-swarm-dynamics/data/interim/memory_facts_v3.parquet`: 7,692,996 presence spells of 4,157,421 (agent, unit) pairs; rows without a survival record (units seen only in undone rows): 1,599.

## 12. Outputs

- hazard: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_hazard_v3.csv`
- retention: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_retention_v3.csv`
- modification: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_modification_v3.csv`
- by_anchor: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_by_anchor_v3.csv`
- h2: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_h2_v3.csv`
- changelog: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_changelog_v3.csv`
- bdw: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_bdw_v3.csv`
- repeat_spells: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_repeat_spells_v3.csv`
- hazard_monthly: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_hazard_monthly_v3.parquet (+ .csv)`
- figure: `/home/enxinson/ai-village-swarm-dynamics/outputs/figures/F6_memory_retention_v3.{pdf,png}`

## 13. Per agent

| agent | group | consolidations | units |
|---|---|---|---|
| Claude 3.5 Sonnet | Anthropic | 62 | 3,078 |
| Claude 3.7 Sonnet | Anthropic | 4,069 | 85,019 |
| Claude Fable 5 | Anthropic | 966 | 80,073 |
| Claude Fable 5.1 | Anthropic | 147 | 31,763 |
| Claude Haiku 4.5 | Anthropic | 6,069 | 345,621 |
| Claude Opus 4 | Anthropic | 912 | 39,023 |
| Claude Opus 4.1 | Anthropic | 1,314 | 48,873 |
| Claude Opus 4.5 | Anthropic | 4,628 | 153,141 |
| Claude Opus 4.6 | Anthropic | 2,035 | 89,156 |
| Claude Opus 4.7 | Anthropic | 1,036 | 85,463 |
| Claude Opus 4.8 | Anthropic | 1,656 | 168,110 |
| Claude Opus 5 | Anthropic | 677 | 127,963 |
| Claude Sonnet 4.5 | Anthropic | 6,103 | 333,041 |
| Claude Sonnet 4.6 | Anthropic | 2,124 | 121,792 |
| Claude Sonnet 5 | Anthropic | 1,745 | 111,677 |
| DeepSeek-V3.2 | Other | 4,760 | 225,302 |
| DeepSeek-V4-Pro | Other | 1,311 | 198,262 |
| Fine-Tuned Leader | Other | 33 | 2,061 |
| GLM-5.2 | Other | 1,545 | 163,239 |
| GLM-5.3 Flash | Other | 190 | 64,692 |
| GPT-4.1 | OpenAI | 351 | 8,999 |
| GPT-4o | OpenAI | 43 | 461 |
| GPT-5 | OpenAI | 4,186 | 180,286 |
| GPT-5.1 | OpenAI | 7,573 | 333,182 |
| GPT-5.2 | OpenAI | 4,085 | 83,235 |
| GPT-5.4 | OpenAI | 3,503 | 100,486 |
| GPT-5.5 | OpenAI | 1,693 | 96,979 |
| GPT-5.6 Luna | OpenAI | 226 | 6,897 |
| GPT-5.6 Sol | OpenAI | 851 | 80,362 |
| GPT-5.6 Terra | OpenAI | 283 | 5,185 |
| GPT-6 Astra | OpenAI | 56 | 10,375 |
| Gemini 2.5 Pro | Google | 6,863 | 95,976 |
| Gemini 3 Pro | Google | 1,939 | 36,348 |
| Gemini 3.1 Pro | Google | 3,971 | 76,537 |
| Gemini 3.5 Flash | Google | 2,727 | 50,310 |
| Gemini 3.8 Flash | Google | 404 | 33,657 |
| Grok 4 | Other | 485 | 42,230 |
| Grok 4.5 | Other | 715 | 220,407 |
| Kimi K2.6 | Other | 1,643 | 95,944 |
| Kimi K3 | Other | 221 | 58,002 |
| Muse Spark 1.3 | Other | 55 | 13,326 |
| Opus 4.5 (Claude Code) | Claude Code | 1,764 | 9,657 |
| [Temporary] Fine-tuned Leader | Other | 4 | 334 |
| o1 | OpenAI | 41 | 2,120 |
| o3 | OpenAI | 533 | 36,901 |
| o4-mini | OpenAI | 3 | 292 |

## 14. Comparison with expectations and verdict

- Consolidations: 85,600 live REWRITE rows; memory_versions has 85,603 rewrites, so 3 sit on 3 abandoned lineage branches (memory_versions QA: 3 generations whose parent is not the previous one in time). Agents covered: 46 of 46.
- All standard: H2 (constant hazard) is rejected at 5% (cluster Wald p = <1e-300; naive LR = 6128776.6, df 4). The hazard decreases from 0.463 at g = 1 to 0.025 at g >= 9; lowest AIC: beta-geometric.
- Anthropic: H2 (constant hazard) is rejected at 5% (cluster Wald p = <1e-300; naive LR = 2579270.1, df 4). The hazard decreases from 0.480 at g = 1 to 0.027 at g >= 9; lowest AIC: beta-geometric.
- OpenAI: H2 (constant hazard) is rejected at 5% (cluster Wald p = <1e-300; naive LR = 1764359.6, df 4). The hazard decreases from 0.555 at g = 1 to 0.022 at g >= 9; lowest AIC: beta-geometric.
- Google: H2 (constant hazard) is rejected at 5% (cluster Wald p = 9.1e-22; naive LR = 541063.7, df 4). The hazard decreases from 0.379 at g = 1 to 0.018 at g >= 9; lowest AIC: beta-geometric.
- Other: H2 (constant hazard) is rejected at 5% (cluster Wald p = 8.1e-123; naive LR = 1092406.9, df 4). The hazard decreases from 0.376 at g = 1 to 0.035 at g >= 9; lowest AIC: piecewise.
- Claude Code: H2 (constant hazard) is rejected at 5% (LR p = <1e-300; naive LR = 5443.2, df 4). The hazard decreases from 0.473 at g = 1 to 0.092 at g >= 9; lowest AIC: piecewise.
- Heterogeneity: for all standard agents the beta-geometric model (2 parameters) lowers AIC by 6,420,936 against the geometric model and by 292,167 against the 5-bin piecewise hazard. Most of the decline of h_g is therefore what a mix of units with different but constant hazards produces (fitted mean hazard a / (a + b) = 0.488): units that survive early consolidations are the durable ones. H2 fails at the population level, not necessarily for a single unit.
- Expectation (schema_notes 4.2): a rewrite keeps 40-70% of its input lines, so units already in consolidated memory should face a first-consolidation hazard of roughly 0.3-0.6, and units that arrive in appended session logs a higher one, because a consolidation compresses those logs. Observed by entry kind: first h1 = 0.218; session h1 = 0.385; note h1 = 0.728; rewrite h1 = 0.551; fork h1 = 0.471.
- Verbatim line retention, standard agents (schema_notes 4.2: a rewrite keeps 40-70% of its lines): median share of input lines kept unchanged per consolidation, pre 0.407 (IQR 0.242-0.585); post 0.503 (IQR 0.295-0.697). Unit-level retention is higher than line-level retention wherever rewrites rephrase lines but keep their values.
- Regime: before perma-computer-use h1 = 0.599 [0.577, 0.621], h9+ = 0.026 [0.023, 0.031]; after it h1 = 0.416 [0.352, 0.476], h2 = 0.467 [0.428, 0.500], h9+ = 0.025 [0.021, 0.031]. After the switch a consolidation follows every session, so one consolidation is a shorter time step, and the consolidation right after a session keeps more of it than the next one does (the hazard rises from g = 1 to g = 2), which no constant or monotone hazard model reproduces.
- CHANGELOG memory entries: 34 before/after hazard differences have a CI; 10 exclude zero: cl-2025-04-15-1 (g = 1: -0.145 [-0.262, -0.035]); cl-2025-10-14-1 (g = 1: 0.052 [0.028, 0.081]); cl-2026-03-11-1 (g >= 2: -0.019 [-0.032, -0.007]); cl-2026-03-12-3 (g >= 2: -0.018 [-0.033, -0.003]); cl-2026-03-16-1 (g = 1: -0.025 [-0.055, -0.001]); cl-2026-03-24-1 (g = 1: -0.065 [-0.121, -0.025]); cl-2026-03-24-1 (g >= 2: 0.019 [0.002, 0.041]); cl-2026-03-26-1 (g = 1: -0.035 [-0.074, -0.005]); cl-2026-03-26-3 (g = 1: -0.035 [-0.074, -0.005]); cl-2026-06-01-3 (g = 1: 0.035 [0.006, 0.067]). Windows are short and other changes overlap, so these are associations.
- Modifications are 6.6% of first losses (271,885 of 4,136,592); the rest are drops.
- Restoration: 16.6% of lost units with later consolidations come back (318,277 re-appended, 366,092 recreated by a consolidation).
- Heterogeneity vs duration dependence (BdW): All standard c = 2.604 [1.775, 6.627]; Anthropic c = 3.307 [1.757, 10.647]; OpenAI c = 1.099 [0.875, 1.793]; Google c = 1.785 [0.924, 8.067]; Other c = 4.048 [2.154, 13.974]; Claude Code c = 0.528 [0.517, 0.539]; pre cohort c = 0.669 [0.572, 0.745]; post cohort c = 3.857 [2.332, 10.271]; All standard from g = 2 c = 0.045 [0.042, 0.081]; pre cohort from g = 2 c = 0.175 [0.155, 0.206]; post cohort from g = 2 c = 0.828 [0.536, 11.608]. Of 23 main scopes, c lies below 1 in 4, covers 1 in 10 and lies above 1 in 9; for all standard agents the BdW improves AIC by 105,330 over the beta-geometric (LR 105332, p <1e-300) and the lowest AIC is bdw. Identification: in single-spell data heterogeneity and duration dependence trade off (a falling population hazard can come from either), so c rests on the functional form of the Beta mixing distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed (section 8).
- Repeated spells (standard agents): 683,861 restored facts with a second spell; g = 1: spell 1 0.465, spell 2 0.461, difference -0.004 [-0.040, 0.043]; g = 2: spell 1 0.378, spell 2 0.288, difference -0.090 [-0.116, -0.066]; g = 9+: spell 1 0.026, spell 2 0.026, difference -0.000 [-0.003, 0.003]. Like-for-like subset (157,543 facts): g = 1: spell 1 0.521, spell 2 0.489, difference -0.032 [-0.042, -0.022]; g = 2: spell 1 0.335, spell 2 0.309, difference -0.026 [-0.040, -0.016]; g = 9+: spell 1 0.031, spell 2 0.029, difference -0.002 [-0.007, 0.001]. Descriptive only: spell 1 is selected to end in a loss, which biases its hazards upward (a negative difference is expected even with no change), and some restorations are key collisions.
- Missing values: rows without run_day 0, rows without regime 0, consolidations without run_day 0.
