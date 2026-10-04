# QA: memory chains (module B1, SPEC 6.3), rules v2

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Aggregates only. No memory text, names, emails, phone numbers or credentials appear in this report or in outputs/; URLs appear only as domains, PERSON/email/phone values and every value on a credential line are keyed hashes.

Runtime 1214 s (inputs 1, lines + anchors 1 (cache hit), interning 9, chains 774, statistics and outputs 417). Line and anchor extraction when computed: 37 s + 1518 s.

## 0. Rules v2 against v1

Rules v2 (this report): a unit with no anchor in a consolidation output still counts as present if its value occurs literally there (URL, date, time, email, phone, agent name and entity types: a surface form of the value anywhere, case-insensitive, whitespace-normalised, word-bounded; hashed values by hashing candidate strings; number, money and percent: the same value on a line that also holds the unit's context word). A loss is a modification only if the line that replaced the unit's line (patience alignment of lines kept verbatim; inside a changed block the line at the same offset, or the one sharing the most anchor keys) holds the unit's context key with a new value. Restorations stay anchor-based. Units, entries and consolidations are those of v1; v1 outputs are kept unchanged next to these.

v1 first losses that v2 keeps at the same consolidation (standard agents): 1,309,112 of 4,134,752 (31.7%). v1 modifications that v2 calls drops: 445,509 of 962,470.

| type | v1 losses | kept in v2 | share |
|---|---|---|---|
| url | 104,652 | 3,466 | 0.033 |
| email | 5,165 | 0 | 0.000 |
| phone | 207 | 0 | 0.000 |
| date | 24,280 | 1,476 | 0.061 |
| time | 689,299 | 358,913 | 0.521 |
| money | 32,685 | 9,631 | 0.295 |
| percent | 103,826 | 25,513 | 0.246 |
| number | 2,233,691 | 631,838 | 0.283 |
| agent | 2,983 | 472 | 0.158 |
| person | 231,295 | 48,753 | 0.211 |
| org | 470,676 | 139,807 | 0.297 |
| gpe | 45,388 | 20,583 | 0.453 |
| product | 47,942 | 21,620 | 0.451 |
| event | 8,819 | 3,579 | 0.406 |
| work_of_art | 133,844 | 43,461 | 0.325 |

Hazards by g bin and modified share of first losses, v1 -> v2 (point estimates; v2 CIs in section 4 and memory_hazard_v2.csv):

| group | h1 | h2 | h3-4 | h5-8 | h9+ | modified share |
|---|---|---|---|---|---|---|
| All standard | 0.522 -> 0.340 | 0.506 -> 0.353 | 0.302 -> 0.219 | 0.174 -> 0.131 | 0.045 -> 0.025 | 0.233 -> 0.052 |
| Anthropic | 0.541 -> 0.339 | 0.530 -> 0.370 | 0.311 -> 0.221 | 0.181 -> 0.135 | 0.045 -> 0.025 | 0.229 -> 0.050 |
| OpenAI | 0.630 -> 0.448 | 0.436 -> 0.311 | 0.287 -> 0.205 | 0.173 -> 0.124 | 0.043 -> 0.020 | 0.187 -> 0.051 |
| Google | 0.434 -> 0.310 | 0.404 -> 0.313 | 0.236 -> 0.193 | 0.135 -> 0.112 | 0.036 -> 0.018 | 0.203 -> 0.065 |
| Other | 0.419 -> 0.254 | 0.539 -> 0.365 | 0.323 -> 0.233 | 0.183 -> 0.136 | 0.057 -> 0.034 | 0.288 -> 0.050 |
| Claude Code | 0.517 -> 0.436 | 0.278 -> 0.249 | 0.185 -> 0.167 | 0.130 -> 0.126 | 0.103 -> 0.092 | 0.200 -> 0.149 |

BdW shape c from g = 2 (likelihood conditional on surviving the first consolidation), v1 vs v2, with cluster-bootstrap CIs:

| scope | stratum | c v1 [95% CI] | c v2 [95% CI] |
|---|---|---|---|
| family | All standard | 0.714 [0.453, 1.041] | 0.424 [0.139, 0.660] |
| regime_cohort | pre | 0.181 [0.149, 0.440] | 0.431 [0.257, 0.604] |
| regime_cohort | post | 0.893 [0.555, 11.336] | 0.546 [0.174, 0.882] |

Use of the literal fallback by anchor type (standard agents): units kept at least once only by a literal match, and the number of such consolidation trials.

| type | units | units with a fallback keep | fallback trials |
|---|---|---|---|
| url | 105,137 | 3,466 | 77,318 |
| email | 5,247 | 0 | 0 |
| phone | 207 | 0 | 0 |
| date | 24,538 | 1,476 | 26,702 |
| time | 690,897 | 358,913 | 6,981,879 |
| money | 32,806 | 9,631 | 147,285 |
| percent | 104,007 | 25,513 | 231,606 |
| number | 2,239,413 | 631,838 | 5,108,395 |
| agent | 3,151 | 472 | 157,354 |
| person | 232,423 | 48,753 | 1,338,708 |
| org | 471,788 | 139,807 | 4,005,023 |
| gpe | 45,564 | 20,583 | 1,035,855 |
| product | 48,055 | 21,620 | 782,755 |
| event | 8,835 | 3,579 | 124,457 |
| work_of_art | 134,112 | 43,461 | 1,303,008 |

Agreement with the LLM pre-labels (review sheet as of 2026-10-01 07:01 UTC, read only): v1 310/500 (kappa 0.523), v2 341/500 (kappa 0.544). Confusion matrix of rule_label_v2 (rows) against the LLM labels (columns):

| v2 \ LLM | kept | modified | dropped | new | restored | total | agree |
|---|---|---|---|---|---|---|---|
| kept | 180 | 12 | 40 | 30 | 26 | 288 | 0.625 |
| modified | 0 | 6 | 20 | 0 | 0 | 26 | 0.231 |
| dropped | 5 | 5 | 82 | 0 | 0 | 92 | 0.891 |
| new | 2 | 0 | 0 | 54 | 0 | 56 | 0.964 |
| restored | 3 | 1 | 0 | 15 | 19 | 38 | 0.500 |

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
| All standard | 45 | 83,836 | 4,146,180 | 4,142,667 | 37,881,746 |
| Anthropic | 15 | 33,543 | 1,823,793 | 1,822,944 | 15,979,236 |
| OpenAI | 14 | 23,427 | 945,760 | 945,260 | 9,287,126 |
| Google | 5 | 15,904 | 292,828 | 292,680 | 4,103,586 |
| Other | 11 | 10,962 | 1,083,799 | 1,081,783 | 8,511,798 |
| Claude Code | 1 | 1,764 | 9,657 | 9,653 | 49,482 |

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
| unit-trials (sum over consolidations of units at risk) | 37,931,228 |
| kept | 33,806,898 |
| dropped | 3,910,429 |
| modified | 213,901 |
| restorations | 1,694,104 |
| units first seen in a consolidation output | 1,384,660 |
| never-lost units missing from the consolidation input (after a truncation) | 1 |
| undo rows (revert, trunc_other) | 119 |
| fork rows extending an older row | 52 |
| units removed from tracking by an undo | 2,202 |
| first losses: dropped / modified / censored | 3,910,429 / 213,901 / 27,990 |
| unit-trials: per-unit sum vs per-consolidation sum | 37,931,228 vs 37,931,228 (ok) |
| first losses: per-unit vs per-consolidation | 4,124,330 vs 4,124,330 (ok) |

## 4. Hazard of loss by model family (H2)

h_g = P(lost at consolidation g | kept through g - 1). 95% CIs resample agents within the group (2000 replicates, seed 20261003); Claude Code is one agent, so its CIs treat units as independent (Wilson). Generations with fewer than 30 units at risk are not reported.

| group | agents | unit-trials | h1 | h2 | h3-4 | h5-8 | h9+ | geometric h |
|---|---|---|---|---|---|---|---|---|
| All standard | 45 | 37,881,746 | 0.340 [0.289, 0.384] | 0.353 [0.325, 0.377] | 0.219 [0.200, 0.236] | 0.131 [0.119, 0.143] | 0.025 [0.021, 0.030] | 0.109 |
| Anthropic | 15 | 15,979,236 | 0.339 [0.267, 0.390] | 0.370 [0.338, 0.403] | 0.221 [0.199, 0.241] | 0.135 [0.121, 0.148] | 0.025 [0.019, 0.036] | 0.114 |
| OpenAI | 14 | 9,287,126 | 0.448 [0.389, 0.492] | 0.311 [0.281, 0.345] | 0.205 [0.177, 0.223] | 0.124 [0.105, 0.137] | 0.020 [0.017, 0.025] | 0.101 |
| Google | 5 | 4,103,586 | 0.310 [0.156, 0.440] | 0.313 [0.225, 0.377] | 0.193 [0.147, 0.232] | 0.112 [0.086, 0.159] | 0.018 [0.016, 0.025] | 0.071 |
| Other | 11 | 8,511,798 | 0.254 [0.168, 0.330] | 0.365 [0.290, 0.410] | 0.233 [0.178, 0.278] | 0.136 [0.100, 0.167] | 0.034 [0.026, 0.046] | 0.126 |
| Claude Code | 1 | 49,482 | 0.436 [0.427, 0.446] | 0.249 [0.238, 0.261] | 0.167 [0.159, 0.176] | 0.126 [0.119, 0.132] | 0.092 [0.088, 0.096] | 0.194 |

H2 tests: geometric (constant hazard) vs piecewise-constant hazard over g = 1, 2, 3-4, 5-8, 9+. The likelihood-ratio test treats units as independent; the Wald test uses the cluster-bootstrap covariance. The beta-geometric model lets each unit keep a constant hazard drawn from a Beta distribution, which makes the population hazard decrease with g.

| scope | stratum | LR | df | p (LR) | Wald | p (Wald, cluster) | AIC geometric | AIC beta-geometric | AIC piecewise | beta-geom a, b |
|---|---|---|---|---|---|---|---|---|---|---|
| family | All standard | 5529573.0 | 4 | <1e-300 | 966.8 | 5.5e-208 | 26033967 | 19937227 | 20504402 | 1.160, 1.967 |
| family | Anthropic | 2413128.2 | 4 | <1e-300 | 814.8 | 4.7e-175 | 11312317 | 8634850 | 8899197 | 1.231, 2.060 |
| family | OpenAI | 1655138.4 | 4 | <1e-300 | 1479.4 | <1e-300 | 6087027 | 4278482 | 4431896 | 0.914, 1.117 |
| family | Google | 477587.0 | 4 | <1e-300 | 76.4 | 9.9e-16 | 2102423 | 1570201 | 1624844 | 0.965, 1.891 |
| family | Other | 1006556.5 | 4 | <1e-300 | 265.3 | 3.3e-56 | 6431233 | 5392622 | 5424684 | 1.381, 2.951 |
| family | Claude Code | 4791.0 | 4 | <1e-300 | n/a | n/a | 48674 | 44441 | 43891 | 1.150, 1.710 |
| regime:pre | All standard | 1760592.3 | 4 | <1e-300 | 880.2 | 3.3e-189 | 6981852 | n/a | 5221268 | n/a, n/a |
| regime:pre | Anthropic | 997386.4 | 4 | <1e-300 | 2744.2 | <1e-300 | 3941468 | n/a | 2944089 | n/a, n/a |
| regime:pre | OpenAI | 454271.9 | 4 | <1e-300 | 395.1 | 3.2e-84 | 1626761 | n/a | 1172497 | n/a, n/a |
| regime:pre | Google | 163019.1 | 4 | <1e-300 | n/a | n/a | 655184 | n/a | 492173 | n/a, n/a |
| regime:pre | Other | 137818.1 | 4 | <1e-300 | n/a | n/a | 735634 | n/a | 597824 | n/a, n/a |
| regime:post | All standard | 3838087.2 | 4 | <1e-300 | 680.1 | 7.1e-146 | 19002101 | n/a | 15164022 | n/a, n/a |
| regime:post | Anthropic | 1441622.3 | 4 | <1e-300 | 397.7 | 9e-85 | 7326210 | n/a | 5884596 | n/a, n/a |
| regime:post | OpenAI | 1204616.1 | 4 | <1e-300 | 1371.8 | 8.9e-296 | 4459603 | n/a | 3254995 | n/a, n/a |
| regime:post | Google | 317807.0 | 4 | <1e-300 | n/a | n/a | 1437270 | n/a | 1119471 | n/a, n/a |
| regime:post | Other | 834961.3 | 4 | <1e-300 | 318.3 | 1.2e-67 | 5616588 | n/a | 4781634 | n/a, n/a |
| memory_epoch | [2025-04-02, 2025-04-15) | 8222.0 | 4 | <1e-300 | n/a | n/a | 24489 | n/a | 16275 | n/a, n/a |
| memory_epoch | [2025-04-15, 2025-04-16) | 521.0 | 4 | 1.9e-111 | n/a | n/a | 1674 | n/a | 1161 | n/a, n/a |
| memory_epoch | [2025-04-16, 2025-08-20) | 170610.2 | 4 | <1e-300 | 523.4 | 5.8e-112 | 641491 | n/a | 470889 | n/a, n/a |
| memory_epoch | [2025-08-20, 2025-09-05) | 58777.2 | 4 | <1e-300 | 671.6 | 4.9e-144 | 226266 | n/a | 167497 | n/a, n/a |
| memory_epoch | [2025-09-05, 2025-10-14) | 107865.0 | 4 | <1e-300 | 86.7 | 6.5e-18 | 560139 | n/a | 452282 | n/a, n/a |
| memory_epoch | [2025-10-14, 2025-11-25) | 227817.7 | 4 | <1e-300 | 738.0 | 2.1e-158 | 1105988 | n/a | 878178 | n/a, n/a |
| memory_epoch | [2025-11-25, 2026-03-11) | 1022309.2 | 4 | <1e-300 | 3706.8 | <1e-300 | 3949621 | n/a | 2927320 | n/a, n/a |
| memory_epoch | [2026-03-11, 2026-03-12) | 14246.7 | 4 | <1e-300 | 438.7 | 1.2e-93 | 45040 | n/a | 30801 | n/a, n/a |
| memory_epoch | [2026-03-12, 2026-03-16) | 28572.9 | 4 | <1e-300 | 912.2 | 3.9e-196 | 86749 | n/a | 58184 | n/a, n/a |
| memory_epoch | [2026-03-16, 2026-03-24) | 78514.3 | 4 | <1e-300 | 553.0 | 2.3e-118 | 273488 | n/a | 194982 | n/a, n/a |
| memory_epoch | [2026-03-24, 2026-03-26) | 23918.8 | 4 | <1e-300 | 722.4 | 4.9e-155 | 113057 | n/a | 89146 | n/a, n/a |
| memory_epoch | [2026-03-26, 2026-06-01) | 701629.5 | 4 | <1e-300 | 399.2 | 4.1e-85 | 2836532 | n/a | 2134910 | n/a, n/a |
| memory_epoch | [2026-06-01, 2026-06-02) | 11400.4 | 4 | <1e-300 | 434.0 | 1.3e-92 | 53350 | n/a | 41957 | n/a, n/a |
| memory_epoch | [2026-06-02, 2026-06-03) | 11035.4 | 4 | <1e-300 | 203.8 | 5.8e-43 | 56881 | n/a | 45854 | n/a, n/a |
| memory_epoch | [2026-06-03, 2026-06-11) | 128585.8 | 4 | <1e-300 | 217.8 | 5.6e-46 | 639296 | n/a | 510718 | n/a, n/a |
| memory_epoch | [2026-06-11, 2026-07-03) | 362148.3 | 4 | <1e-300 | 532.0 | 7.9e-114 | 1538109 | n/a | 1175968 | n/a, n/a |
| memory_epoch | [2026-07-03, end] | 2612122.0 | 4 | <1e-300 | 598.4 | 3.4e-128 | 13738848 | n/a | 11126734 | n/a, n/a |
| entry_kind | first | 3569.0 | 4 | <1e-300 | 91.1 | 7.6e-19 | 23705 | 18768 | 20144 | 0.396, 2.466 |
| entry_kind | session | 3014866.3 | 4 | <1e-300 | 876.6 | 2e-188 | 15339529 | 12142358 | 12324670 | 1.357, 2.620 |
| entry_kind | note | 588235.4 | 4 | <1e-300 | 456.9 | 1.4e-97 | 1927683 | 1288577 | 1339456 | 0.738, 0.800 |
| entry_kind | rewrite | 2015495.9 | 4 | <1e-300 | 1498.7 | <1e-300 | 8652074 | 6417469 | 6636586 | 0.942, 1.297 |
| entry_kind | fork | 555.0 | 4 | 8.6e-119 | 69.9 | 2.4e-14 | 2257 | 1784 | 1710 | 1.357, 1.918 |

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
| All standard | 1 | 4,142,667 | 0.023 [0.020, 0.026] | 0.067 [0.061, 0.073] |
| All standard | 2 | 2,732,528 | 0.022 [0.019, 0.025] | 0.062 [0.054, 0.070] |
| All standard | 3 | 1,765,956 | 0.011 [0.009, 0.012] | 0.045 [0.040, 0.051] |
| All standard | 5 | 1,084,553 | 0.005 [0.005, 0.006] | 0.034 [0.030, 0.039] |
| All standard | 10 | 566,175 | 0.002 [0.002, 0.003] | 0.027 [0.023, 0.032] |
| Anthropic | 1 | 1,822,944 | 0.024 [0.018, 0.028] | 0.070 [0.061, 0.077] |
| Anthropic | 2 | 1,204,069 | 0.022 [0.016, 0.028] | 0.060 [0.045, 0.075] |
| Anthropic | 3 | 757,775 | 0.010 [0.007, 0.013] | 0.042 [0.031, 0.050] |
| Anthropic | 5 | 463,473 | 0.005 [0.003, 0.006] | 0.029 [0.022, 0.035] |
| Anthropic | 10 | 236,152 | 0.002 [0.002, 0.002] | 0.021 [0.016, 0.026] |
| OpenAI | 1 | 945,260 | 0.024 [0.023, 0.027] | 0.055 [0.049, 0.064] |
| OpenAI | 2 | 521,150 | 0.021 [0.017, 0.027] | 0.067 [0.057, 0.081] |
| OpenAI | 3 | 358,837 | 0.012 [0.010, 0.015] | 0.055 [0.047, 0.061] |
| OpenAI | 5 | 228,311 | 0.007 [0.005, 0.008] | 0.045 [0.038, 0.052] |
| OpenAI | 10 | 123,236 | 0.002 [0.002, 0.003] | 0.029 [0.024, 0.033] |
| Google | 1 | 292,680 | 0.026 [0.016, 0.033] | 0.083 [0.072, 0.109] |
| Google | 2 | 201,851 | 0.024 [0.014, 0.036] | 0.078 [0.054, 0.108] |
| Google | 3 | 138,555 | 0.012 [0.007, 0.016] | 0.056 [0.042, 0.072] |
| Google | 5 | 90,739 | 0.005 [0.004, 0.007] | 0.039 [0.030, 0.047] |
| Google | 10 | 52,618 | 0.003 [0.003, 0.005] | 0.049 [0.046, 0.052] |
| Other | 1 | 1,081,783 | 0.019 [0.015, 0.023] | 0.074 [0.063, 0.099] |
| Other | 2 | 805,458 | 0.021 [0.019, 0.024] | 0.058 [0.052, 0.073] |
| Other | 3 | 510,789 | 0.011 [0.010, 0.012] | 0.042 [0.037, 0.050] |
| Other | 5 | 302,030 | 0.005 [0.005, 0.006] | 0.033 [0.027, 0.043] |
| Other | 10 | 154,169 | 0.003 [0.002, 0.003] | 0.030 [0.022, 0.046] |
| Claude Code | 1 | 9,653 | 0.092 [0.086, 0.098] | 0.210 [0.198, 0.223] |
| Claude Code | 2 | 5,438 | 0.034 [0.030, 0.039] | 0.137 [0.119, 0.156] |
| Claude Code | 3 | 4,074 | 0.020 [0.016, 0.025] | 0.107 [0.087, 0.131] |
| Claude Code | 5 | 2,832 | 0.009 [0.006, 0.013] | 0.068 [0.047, 0.098] |
| Claude Code | 10 | 1,500 | 0.019 [0.013, 0.028] | 0.206 [0.147, 0.280] |

| group | lost | lost with later trials | restored | share restored | reappended | recreated | median gap (consolidations) | share restored at the next consolidation | re-lost after restoration |
|---|---|---|---|---|---|---|---|---|---|
| All standard | 4,114,736 | 4,111,980 | 604,728 | 0.147 | 294,170 | 310,558 | 90.0 | 0.075 | 598,821 |
| Anthropic | 1,815,185 | 1,814,452 | 275,580 | 0.152 | 146,671 | 128,909 | 120.0 | 0.068 | 273,666 |
| OpenAI | 939,863 | 939,334 | 162,249 | 0.173 | 41,529 | 120,720 | 48.0 | 0.100 | 161,148 |
| Google | 291,276 | 291,119 | 34,631 | 0.119 | 20,770 | 13,861 | 96.0 | 0.073 | 34,256 |
| Other | 1,068,412 | 1,067,075 | 132,268 | 0.124 | 85,200 | 47,068 | 90.0 | 0.058 | 129,751 |
| Claude Code | 9,594 | 9,594 | 1,870 | 0.195 | 6 | 1,864 | 21.0 | 0.129 | 1,862 |

A restoration is the same unit key reappearing. For quantities with a generic context key (e.g. a small count of tasks) a later, unrelated fact can share the key, so restoration shares are upper bounds; by anchor type they are in memory_by_anchor.csv.

## 6. Regime (perma-computer-use), entry kind and memory-system epochs

| scope | stratum | agents | unit-trials | h1 | h2 | h3-4 | h5-8 | h9+ | geometric h |
|---|---|---|---|---|---|---|---|---|---|
| regime:pre | All standard | 23 | 11,397,303 | 0.447 [0.418, 0.480] | 0.268 [0.238, 0.290] | 0.174 [0.150, 0.190] | 0.105 [0.089, 0.118] | 0.023 [0.019, 0.029] | 0.092 |
| regime:pre | Anthropic | 9 | 6,360,127 | 0.442 [0.423, 0.483] | 0.281 [0.270, 0.308] | 0.180 [0.165, 0.192] | 0.111 [0.100, 0.123] | 0.022 [0.017, 0.036] | 0.093 |
| regime:pre | OpenAI | 9 | 2,413,185 | 0.491 [0.439, 0.615] | 0.280 [0.239, 0.350] | 0.191 [0.157, 0.240] | 0.113 [0.089, 0.138] | 0.022 [0.018, 0.041] | 0.106 |
| regime:pre | Google | 3 | 1,058,412 | 0.440 [0.344, 0.479] | 0.272 [0.237, 0.301] | 0.178 [0.134, 0.194] | 0.113 [0.089, 0.120] | 0.022 [0.022, 0.027] | 0.093 |
| regime:pre | Other | 2 | 1,565,579 | 0.379 [0.216, 0.487] | 0.171 [0.073, 0.271] | 0.112 [0.064, 0.179] | 0.065 [0.044, 0.103] | 0.024 [0.022, 0.028] | 0.063 |
| regime:post | All standard | 34 | 26,484,443 | 0.303 [0.249, 0.356] | 0.376 [0.343, 0.406] | 0.234 [0.211, 0.256] | 0.141 [0.127, 0.156] | 0.026 [0.021, 0.032] | 0.116 |
| regime:post | Anthropic | 11 | 9,619,109 | 0.289 [0.216, 0.358] | 0.404 [0.353, 0.456] | 0.240 [0.208, 0.280] | 0.148 [0.130, 0.170] | 0.028 [0.019, 0.043] | 0.127 |
| regime:post | OpenAI | 9 | 6,873,941 | 0.432 [0.363, 0.476] | 0.321 [0.285, 0.354] | 0.209 [0.176, 0.229] | 0.129 [0.107, 0.144] | 0.020 [0.016, 0.024] | 0.100 |
| regime:post | Google | 4 | 3,045,174 | 0.244 [0.112, 0.417] | 0.329 [0.220, 0.444] | 0.199 [0.140, 0.265] | 0.112 [0.079, 0.199] | 0.017 [0.015, 0.030] | 0.063 |
| regime:post | Other | 10 | 6,946,219 | 0.241 [0.163, 0.325] | 0.381 [0.317, 0.429] | 0.248 [0.200, 0.300] | 0.149 [0.116, 0.187] | 0.037 [0.027, 0.059] | 0.140 |
| memory_epoch | [2025-04-02, 2025-04-15) | 4 | 18,078 | 0.745 [0.651, 0.872] | 0.435 [0.370, 0.521] | 0.248 [0.204, 0.449] | 0.124 [0.099, 0.277] | 0.036 [0.031, 0.191] | 0.411 |
| memory_epoch | [2025-04-15, 2025-04-16) | 3 | 1,723 | 0.541 [0.423, 0.701] | 0.193 [0.099, 0.500] | 0.096 [0.081, 0.444] | 0.123 [0.121, 0.250] | 0.008 [0.008, 0.008] | 0.189 |
| memory_epoch | [2025-04-16, 2025-08-20) | 10 | 872,400 | 0.505 [0.435, 0.632] | 0.283 [0.252, 0.360] | 0.180 [0.143, 0.254] | 0.112 [0.093, 0.164] | 0.027 [0.022, 0.057] | 0.120 |
| memory_epoch | [2025-08-20, 2025-09-05) | 7 | 359,636 | 0.459 [0.384, 0.508] | 0.274 [0.209, 0.327] | 0.164 [0.141, 0.193] | 0.092 [0.085, 0.106] | 0.022 [0.017, 0.034] | 0.095 |
| memory_epoch | [2025-09-05, 2025-10-14) | 8 | 1,386,570 | 0.357 [0.245, 0.482] | 0.174 [0.100, 0.282] | 0.106 [0.071, 0.171] | 0.062 [0.042, 0.097] | 0.020 [0.018, 0.024] | 0.051 |
| memory_epoch | [2025-10-14, 2025-11-25) | 10 | 2,073,248 | 0.388 [0.346, 0.457] | 0.226 [0.184, 0.275] | 0.147 [0.118, 0.176] | 0.093 [0.075, 0.108] | 0.024 [0.016, 0.036] | 0.075 |
| memory_epoch | [2025-11-25, 2026-03-11) | 15 | 6,036,519 | 0.455 [0.438, 0.475] | 0.286 [0.272, 0.301] | 0.192 [0.177, 0.204] | 0.118 [0.106, 0.129] | 0.023 [0.018, 0.031] | 0.101 |
| memory_epoch | [2026-03-11, 2026-03-12) | 11 | 76,169 | 0.481 [0.430, 0.538] | 0.312 [0.276, 0.351] | 0.178 [0.147, 0.215] | 0.111 [0.094, 0.125] | 0.016 [0.010, 0.027] | 0.087 |
| memory_epoch | [2026-03-12, 2026-03-16) | 11 | 150,557 | 0.499 [0.462, 0.543] | 0.302 [0.280, 0.331] | 0.187 [0.156, 0.208] | 0.108 [0.093, 0.122] | 0.015 [0.010, 0.026] | 0.084 |
| memory_epoch | [2026-03-16, 2026-03-24) | 12 | 422,403 | 0.481 [0.441, 0.519] | 0.299 [0.258, 0.334] | 0.186 [0.153, 0.219] | 0.110 [0.089, 0.135] | 0.021 [0.015, 0.030] | 0.099 |
| memory_epoch | [2026-03-24, 2026-03-26) | 12 | 157,418 | 0.408 [0.357, 0.448] | 0.276 [0.239, 0.301] | 0.195 [0.173, 0.213] | 0.130 [0.108, 0.152] | 0.026 [0.020, 0.034] | 0.116 |
| memory_epoch | [2026-03-26, 2026-06-01) | 18 | 3,533,880 | 0.390 [0.315, 0.447] | 0.427 [0.371, 0.472] | 0.252 [0.217, 0.285] | 0.145 [0.126, 0.162] | 0.024 [0.018, 0.034] | 0.138 |
| memory_epoch | [2026-06-01, 2026-06-02) | 18 | 68,260 | 0.322 [0.271, 0.369] | 0.399 [0.343, 0.458] | 0.239 [0.198, 0.285] | 0.145 [0.115, 0.177] | 0.024 [0.015, 0.038] | 0.132 |
| memory_epoch | [2026-06-02, 2026-06-03) | 18 | 65,961 | 0.331 [0.275, 0.377] | 0.417 [0.358, 0.483] | 0.268 [0.222, 0.322] | 0.146 [0.119, 0.172] | 0.032 [0.018, 0.049] | 0.155 |
| memory_epoch | [2026-06-03, 2026-06-11) | 19 | 909,770 | 0.327 [0.252, 0.396] | 0.351 [0.301, 0.406] | 0.213 [0.179, 0.255] | 0.122 [0.096, 0.152] | 0.025 [0.020, 0.034] | 0.112 |
| memory_epoch | [2026-06-11, 2026-07-03) | 20 | 2,405,301 | 0.362 [0.298, 0.413] | 0.370 [0.320, 0.415] | 0.200 [0.163, 0.238] | 0.114 [0.095, 0.138] | 0.023 [0.020, 0.029] | 0.098 |
| memory_epoch | [2026-07-03, end] | 32 | 19,343,853 | 0.276 [0.224, 0.330] | 0.369 [0.336, 0.398] | 0.235 [0.212, 0.259] | 0.144 [0.129, 0.160] | 0.027 [0.021, 0.034] | 0.114 |
| entry_kind | first | 44 | 272,555 | 0.171 [0.128, 0.216] | 0.100 [0.063, 0.143] | 0.052 [0.032, 0.076] | 0.036 [0.021, 0.055] | 0.004 [0.003, 0.005] | 0.007 |
| entry_kind | session | 45 | 21,403,099 | 0.276 [0.216, 0.334] | 0.392 [0.361, 0.418] | 0.236 [0.214, 0.256] | 0.138 [0.125, 0.150] | 0.027 [0.022, 0.033] | 0.116 |
| entry_kind | note | 27 | 3,429,511 | 0.485 [0.446, 0.533] | 0.284 [0.233, 0.324] | 0.172 [0.134, 0.198] | 0.099 [0.076, 0.118] | 0.017 [0.013, 0.024] | 0.081 |
| entry_kind | rewrite | 45 | 12,774,137 | 0.427 [0.399, 0.447] | 0.278 [0.251, 0.299] | 0.196 [0.176, 0.213] | 0.126 [0.112, 0.138] | 0.025 [0.021, 0.029] | 0.106 |
| entry_kind | fork | 7 | 2,444 | 0.330 [0.137, 0.595] | 0.509 [0.000, 0.645] | 0.323 [0.122, 0.479] | 0.077 [0.011, 0.173] | 0.027 [0.004, 0.116] | 0.173 |

Regime and epoch strata are trial-level: a consolidation counts in the regime (epoch) of its own row, so units that cross a boundary enter the later risk sets at their current g. Epochs run between consecutive dates of memory-category CHANGELOG entries (start date included). Entry kind is the relation of the row where the unit first appeared (session = scaffold session block, note = self-note append, rewrite = new in a consolidation output, first = the agent's first row).

## 7. Heterogeneity versus duration dependence (beta-discrete-Weibull)

BdW (Fader, Hardie, Liu, Davin and Steenburgh 2018): each fact has its own theta ~ Beta(a, b) and S(g | theta) = (1 - theta)^(g^c). c = 1 is the beta-geometric (heterogeneity alone); c < 1 means a fact's own hazard falls with the consolidations it has survived. Maximum likelihood on the same risk sets as section 4 (right-censoring included, every g kept individually); regime cohorts are the facts whose first trial falls before (pre, censored at the agent's switch) or after (post) the agent's switch to perma-computer-use, so neither cohort is left-truncated. The CI of c resamples agents (500 refits); Claude Code (one agent) has only a profile-likelihood CI, which treats facts as independent. The LR test of c = 1 (df 1) treats facts as independent and is anticonservative at these sample sizes; the decision rule uses the CI: if it covers 1 the falling population hazard is consistent with heterogeneity alone, if it lies below 1 there is duration dependence beyond heterogeneity.

| scope | stratum | from g | agents | facts | c [95% CI] | CI | LR (c = 1) | p | AIC BdW - beta-geom | AIC BdW - piecewise | lowest AIC | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| family | All standard | 1 | 45 | 4,142,667 | 1.680 [1.357, 2.174] | bootstrap | 81559.4 | <1e-300 | -81557 | -648732 | bdw | c > 1: a fact's own hazard rises with g |
| family | Anthropic | 1 | 15 | 1,822,944 | 1.796 [1.330, 2.885] | bootstrap | 43996.9 | <1e-300 | -43995 | -308342 | bdw | c > 1: a fact's own hazard rises with g |
| family | OpenAI | 1 | 14 | 945,260 | 1.028 [0.868, 1.480] | bootstrap | 43.0 | 5.4e-11 | -41 | -153455 | bdw | heterogeneity alone (c consistent with 1) |
| family | Google | 1 | 5 | 292,680 | 1.576 [0.987, 3.556] | bootstrap | 4371.5 | <1e-300 | -4369 | -59013 | bdw | heterogeneity alone (c consistent with 1) |
| family | Other | 1 | 11 | 1,081,783 | 2.347 [1.615, 3.190] | bootstrap | 71174.4 | <1e-300 | -71172 | -103235 | bdw | c > 1: a fact's own hazard rises with g |
| family | Claude Code | 1 | 1 | 9,653 | 0.554 [0.543, 0.565] | profile | 569.7 | 6.7e-126 | -568 | -18 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | pre | 1 | 23 | 1,054,178 | 0.735 [0.606, 0.810] | bootstrap | 6441.8 | <1e-300 | -6440 | -174450 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | post | 1 | 34 | 3,088,489 | 2.123 [1.655, 2.797] | bootstrap | 141876.0 | <1e-300 | -141874 | -440557 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | url | 1 | 45 | 105,054 | 1.333 [0.944, 1.807] | bootstrap | 653.2 | 4.4e-144 | -651 | -14086 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | email | 1 | 45 | 5,220 | 0.694 [0.554, 0.919] | bootstrap | 77.8 | 1.2e-18 | -76 | -1577 | bdw | duration dependence: a fact's own hazard falls with g |
| anchor_type | phone | 1 | 26 | 207 | 0.725 [0.469, 1.928] | bootstrap | 2.2 | 0.14 | -0 | -10 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | date | 1 | 45 | 24,522 | 0.591 [0.499, 0.736] | bootstrap | 801.6 | 2.4e-176 | -800 | -2467 | bdw | duration dependence: a fact's own hazard falls with g |
| anchor_type | time | 1 | 45 | 689,941 | 1.652 [1.373, 2.070] | bootstrap | 16406.7 | <1e-300 | -16405 | -185650 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | money | 1 | 42 | 32,770 | 1.043 [0.851, 1.245] | bootstrap | 6.3 | 0.012 | -4 | -3184 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | percent | 1 | 44 | 103,973 | 1.510 [1.206, 1.889] | bootstrap | 1226.1 | 1.3e-268 | -1224 | -6999 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | number | 1 | 45 | 2,237,529 | 1.758 [1.370, 2.341] | bootstrap | 57424.9 | <1e-300 | -57423 | -132048 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | agent | 1 | 45 | 3,151 | 1.245 [0.658, 6.045] | bootstrap | 2.2 | 0.14 | -0 | -1304 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | person | 1 | 45 | 232,313 | 1.479 [1.123, 2.171] | bootstrap | 1737.0 | <1e-300 | -1735 | -36732 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | org | 1 | 45 | 471,556 | 1.094 [0.889, 1.453] | bootstrap | 207.9 | 3.9e-47 | -206 | -80196 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | gpe | 1 | 45 | 45,540 | 1.196 [0.912, 1.689] | bootstrap | 116.9 | 3e-27 | -115 | -14384 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | product | 1 | 45 | 48,029 | 1.107 [0.874, 1.544] | bootstrap | 40.1 | 2.4e-10 | -38 | -10756 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | event | 1 | 42 | 8,832 | 1.061 [0.801, 1.635] | bootstrap | 1.9 | 0.17 | 0 | -1740 | beta_geometric | heterogeneity alone (c consistent with 1) |
| anchor_type | work_of_art | 1 | 45 | 134,030 | 1.560 [1.151, 2.198] | bootstrap | 1991.9 | <1e-300 | -1990 | -27086 | bdw | c > 1: a fact's own hazard rises with g |
| family | All standard | 2 | 45 | 2,732,528 | 0.424 [0.139, 0.660] | bootstrap | 5821.9 | <1e-300 | -5820 | -663236 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | pre | 2 | 23 | 581,849 | 0.431 [0.257, 0.604] | bootstrap | 4075.3 | <1e-300 | -4073 | -176160 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | post | 2 | 34 | 2,150,478 | 0.546 [0.174, 0.882] | bootstrap | 1954.9 | <1e-300 | -1953 | -449264 | bdw | duration dependence: a fact's own hazard falls with g |

From g = 2 rows use the likelihood conditional on surviving the first consolidation (the same model, with the g = 1 term dropped). After the switch to perma-computer-use the hazard rises from g = 1 to g = 2 (section 6: the consolidation right after a session keeps that session's facts, the next one prunes them); a BdW can only produce that rise with c > 1, so c > 1 in scopes dominated by post-switch facts reflects this two-step pattern rather than facts that wear out.

Observed and fitted hazards at g = 1, 2, 5, 10 (families and regime cohorts):

| scope | stratum | from g | g = 1 obs / BdW / BG | g = 2 | g = 5 | g = 10 |
|---|---|---|---|---|---|---|
| family | All standard | 1 | 0.340 / 0.341 / 0.371 | 0.353 / 0.340 / 0.281 | 0.154 / 0.166 / 0.163 | 0.087 / 0.086 / 0.096 |
| family | Anthropic | 1 | 0.339 / 0.341 / 0.374 | 0.370 / 0.355 / 0.287 | 0.156 / 0.172 / 0.169 | 0.093 / 0.088 / 0.100 |
| family | OpenAI | 1 | 0.448 / 0.449 / 0.450 | 0.311 / 0.304 / 0.302 | 0.147 / 0.152 / 0.152 | 0.079 / 0.082 / 0.083 |
| family | Google | 1 | 0.310 / 0.312 / 0.338 | 0.313 / 0.299 / 0.250 | 0.137 / 0.146 / 0.141 | 0.069 / 0.076 / 0.081 |
| family | Other | 1 | 0.254 / 0.256 / 0.319 | 0.365 / 0.356 / 0.259 | 0.162 / 0.173 / 0.166 | 0.088 / 0.087 / 0.104 |
| family | Claude Code | 1 | 0.436 / 0.434 / 0.402 | 0.249 / 0.234 / 0.298 | 0.134 / 0.149 / 0.168 | 0.094 / 0.109 / 0.097 |
| regime_cohort | pre | 1 | 0.447 / 0.449 / 0.439 | 0.268 / 0.252 / 0.283 | 0.125 / 0.132 / 0.137 | 0.071 / 0.077 / 0.074 |
| regime_cohort | post | 1 | 0.303 / 0.304 / 0.354 | 0.376 / 0.367 / 0.279 | 0.165 / 0.175 / 0.171 | 0.094 / 0.089 / 0.104 |
| family | All standard | 2 | n/a | 0.353 / 0.352 / 0.345 | 0.154 / 0.157 / 0.163 | 0.087 / 0.086 / 0.087 |
| regime_cohort | pre | 2 | n/a | 0.268 / 0.266 / 0.254 | 0.125 / 0.127 / 0.137 | 0.071 / 0.074 / 0.078 |
| regime_cohort | post | 2 | n/a | 0.376 / 0.374 / 0.370 | 0.165 / 0.168 / 0.172 | 0.094 / 0.091 / 0.091 |

Identification: in single-spell data heterogeneity and duration dependence trade off (a falling population hazard can come from either), so c rests on the functional form of the Beta mixing distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed (section 8).

## 8. Repeated spells of restored facts

Facts that were lost and later restored, with at least one consolidation after the restoration. Spell 1 runs from entry to the first loss, spell 2 from the restoring consolidation to the next loss (or the agent's last consolidation); trial g counts consolidations from the start of each spell, so both hazards come from the same facts at the same g. `like for like` keeps facts whose first spell also began as new content of a consolidation output and whose restoration was recreated by a consolidation, so both spells start the same way. CIs and the paired difference (spell 2 - spell 1) resample agents. These are descriptions: spell 1 is selected to end in a loss, and early losses leave more time for a restoration, so spell-1 hazards of restored facts are biased upward and a negative difference is expected even if nothing about the fact changed; and a restoration can be a key collision rather than the same fact (restoration shares in section 5 are upper bounds).

| check | value |
|---|---|
| restored facts | 606,598 |
| with >= 1 trial in spell 2 | 606,106 |
| spell 2 ended in a loss | 600,683 |
| re-lost facts in the chain (n_reloss > 0) | 600,683 |
| facts where chain and row-level spells disagree (expected 0) | n/a (v2 presence is not row-level) |
| restored facts absent from the restoring output (expected 0) | n/a |

| group | subset | facts | g | spell 1: n, h [95% CI] | spell 2: n, h [95% CI] | spell 2 - spell 1 [95% CI] | all facts, spell 1 |
|---|---|---|---|---|---|---|---|
| All standard | all restored | 604,236 | 1 | 604,236, 0.340 [0.294, 0.379] | 604,236, 0.363 [0.340, 0.381] | 0.023 [-0.011, 0.064] | 0.340 |
| All standard | all restored | 604,236 | 2 | 398,642, 0.300 [0.281, 0.320] | 384,318, 0.244 [0.218, 0.262] | -0.056 [-0.076, -0.040] | 0.353 |
| All standard | all restored | 604,236 | 3-4 | 498,556, 0.192 [0.178, 0.205] | 525,833, 0.172 [0.155, 0.187] | -0.020 [-0.027, -0.014] | 0.219 |
| All standard | all restored | 604,236 | 5-8 | 604,996, 0.118 [0.109, 0.126] | 660,765, 0.114 [0.102, 0.124] | -0.004 [-0.009, 0.000] | 0.131 |
| All standard | all restored | 604,236 | 9+ | 4,700,073, 0.024 [0.020, 0.030] | 4,953,997, 0.024 [0.021, 0.029] | 0.000 [-0.003, 0.004] | 0.025 |
| All standard | like for like | 132,375 | 1 | 132,375, 0.401 [0.375, 0.424] | 132,375, 0.387 [0.364, 0.406] | -0.014 [-0.026, 0.002] | 0.340 |
| All standard | like for like | 132,375 | 2 | 79,310, 0.268 [0.244, 0.287] | 81,081, 0.262 [0.231, 0.279] | -0.007 [-0.020, 0.007] | 0.353 |
| All standard | like for like | 132,375 | 3-4 | 104,239, 0.186 [0.165, 0.203] | 107,148, 0.185 [0.162, 0.200] | -0.001 [-0.010, 0.010] | 0.219 |
| All standard | like for like | 132,375 | 5-8 | 126,670, 0.120 [0.106, 0.130] | 129,534, 0.121 [0.103, 0.132] | 0.001 [-0.004, 0.005] | 0.131 |
| All standard | like for like | 132,375 | 9+ | 1,018,185, 0.023 [0.018, 0.031] | 943,339, 0.024 [0.020, 0.029] | 0.001 [-0.006, 0.006] | 0.025 |
| Anthropic | all restored | 275,420 | 1 | 275,420, 0.333 [0.265, 0.378] | 275,420, 0.372 [0.331, 0.397] | 0.038 [0.003, 0.090] | 0.339 |
| Anthropic | all restored | 275,420 | 2 | 183,616, 0.301 [0.276, 0.325] | 172,958, 0.243 [0.204, 0.269] | -0.058 [-0.093, -0.033] | 0.370 |
| Anthropic | all restored | 275,420 | 3-4 | 229,726, 0.188 [0.171, 0.202] | 236,867, 0.173 [0.148, 0.193] | -0.015 [-0.028, -0.006] | 0.221 |
| Anthropic | all restored | 275,420 | 5-8 | 281,820, 0.117 [0.105, 0.127] | 296,265, 0.118 [0.102, 0.131] | 0.001 [-0.006, 0.007] | 0.135 |
| Anthropic | all restored | 275,420 | 9+ | 2,228,023, 0.023 [0.017, 0.037] | 2,052,016, 0.026 [0.020, 0.037] | 0.003 [-0.003, 0.006] | 0.025 |
| OpenAI | all restored | 162,176 | 1 | 162,176, 0.425 [0.373, 0.458] | 162,176, 0.362 [0.337, 0.383] | -0.063 [-0.096, -0.016] | 0.448 |
| OpenAI | all restored | 162,176 | 2 | 93,191, 0.284 [0.263, 0.311] | 103,392, 0.250 [0.204, 0.272] | -0.034 [-0.088, -0.014] | 0.311 |
| OpenAI | all restored | 162,176 | 3-4 | 119,201, 0.193 [0.168, 0.207] | 140,580, 0.173 [0.139, 0.192] | -0.020 [-0.036, -0.013] | 0.205 |
| OpenAI | all restored | 162,176 | 5-8 | 143,254, 0.120 [0.103, 0.131] | 176,163, 0.114 [0.088, 0.128] | -0.007 [-0.017, -0.001] | 0.124 |
| OpenAI | all restored | 162,176 | 9+ | 1,219,506, 0.022 [0.018, 0.026] | 1,469,790, 0.022 [0.016, 0.027] | 0.000 [-0.005, 0.007] | 0.020 |
| Google | all restored | 34,609 | 1 | 34,609, 0.289 [0.165, 0.406] | 34,609, 0.334 [0.241, 0.387] | 0.045 [-0.054, 0.140] | 0.310 |
| Google | all restored | 34,609 | 2 | 24,598, 0.284 [0.222, 0.333] | 23,044, 0.196 [0.141, 0.239] | -0.087 [-0.098, -0.076] | 0.313 |
| Google | all restored | 34,609 | 3-4 | 31,923, 0.169 [0.138, 0.199] | 34,234, 0.141 [0.111, 0.174] | -0.028 [-0.042, -0.014] | 0.193 |
| Google | all restored | 34,609 | 5-8 | 41,572, 0.099 [0.080, 0.124] | 46,898, 0.092 [0.072, 0.117] | -0.007 [-0.012, -0.000] | 0.112 |
| Google | all restored | 34,609 | 9+ | 473,580, 0.017 [0.014, 0.028] | 614,798, 0.015 [0.012, 0.024] | -0.002 [-0.010, 0.005] | 0.018 |
| Other | all restored | 132,031 | 1 | 132,031, 0.264 [0.170, 0.330] | 132,031, 0.356 [0.279, 0.404] | 0.093 [0.018, 0.175] | 0.254 |
| Other | all restored | 132,031 | 2 | 97,237, 0.317 [0.254, 0.364] | 84,924, 0.250 [0.186, 0.299] | -0.067 [-0.081, -0.057] | 0.365 |
| Other | all restored | 132,031 | 3-4 | 117,706, 0.204 [0.161, 0.246] | 114,152, 0.179 [0.134, 0.222] | -0.025 [-0.037, -0.017] | 0.233 |
| Other | all restored | 132,031 | 5-8 | 138,350, 0.122 [0.099, 0.150] | 141,439, 0.112 [0.085, 0.143] | -0.010 [-0.018, -0.003] | 0.136 |
| Other | all restored | 132,031 | 9+ | 778,964, 0.033 [0.027, 0.043] | 817,393, 0.031 [0.023, 0.044] | -0.002 [-0.007, 0.005] | 0.034 |
| Claude Code | all restored | 1,870 | 1 | 1,870, 0.419 [0.397, 0.441] | 1,870, 0.416 [0.393, 0.438] | -0.003 [n/a, n/a] | 0.436 |
| Claude Code | all restored | 1,870 | 2 | 1,087, 0.259 [0.233, 0.285] | 1,091, 0.247 [0.222, 0.273] | -0.012 [n/a, n/a] | 0.249 |
| Claude Code | all restored | 1,870 | 3-4 | 1,458, 0.179 [0.160, 0.200] | 1,471, 0.190 [0.171, 0.211] | 0.011 [n/a, n/a] | 0.167 |
| Claude Code | all restored | 1,870 | 5-8 | 1,714, 0.144 [0.128, 0.162] | 1,791, 0.120 [0.106, 0.136] | -0.024 [n/a, n/a] | 0.126 |
| Claude Code | all restored | 1,870 | 9+ | 3,805, 0.078 [0.070, 0.087] | 4,500, 0.071 [0.064, 0.079] | -0.007 [n/a, n/a] | 0.092 |

Monthly hazards for module C: `outputs/tables/memory_hazard_monthly.parquet` (and .csv), 90 rows, 18 PT calendar months (2025-04-01 to 2026-09-01) x 5 groups, columns date, group, h1, h2, h3_4 (hazards of the consolidations in that month, null below 30 facts at risk; 5 null h1) and n_at_risk (all unit-trials of the month).

## 9. Memory-category CHANGELOG entries (+/- 5 run days, standard agents)

Consolidations whose run day falls in the window before the entry's first day or after its last day. Hazards need at least the reporting threshold of unit-trials; the difference (after - before) gets a paired agent-bootstrap CI only when at least 3 agents carry trials on each side.

| entry | date | cons before | cons after | h(g=1) before | h(g=1) after | diff [95% CI] | h(g>=2) before | h(g>=2) after | diff [95% CI] |
|---|---|---|---|---|---|---|---|---|---|
| cl-2025-04-02-2 | 2025-04-02 | 0 | 113 | n/a | 0.744 | n/a [n/a, n/a] | n/a | 0.178 | n/a [n/a, n/a] |
| cl-2025-04-15-1 | 2025-04-15 | 57 | 89 | 0.762 | 0.601 | -0.161 [-0.288, -0.052] | 0.122 | 0.085 | -0.037 [-0.451, 0.063] |
| cl-2025-04-16-1 | 2025-04-16 | 48 | 99 | 0.728 | 0.650 | -0.078 [-0.184, 0.048] | 0.103 | 0.084 | -0.019 [-0.363, 0.208] |
| cl-2025-08-20-1 | 2025-08-20 | 229 | 338 | 0.513 | 0.526 | 0.014 [-0.071, 0.069] | 0.068 | 0.078 | 0.010 [-0.092, 0.028] |
| cl-2025-09-05-2 | 2025-09-05 | 661 | 362 | 0.411 | 0.319 | -0.093 [-0.270, 0.057] | 0.049 | 0.033 | -0.016 [-0.053, 0.019] |
| cl-2025-10-14-1 | 2025-10-14 | 485 | 753 | 0.338 | 0.347 | 0.009 [-0.076, 0.082] | 0.035 | 0.039 | 0.003 [-0.017, 0.022] |
| cl-2025-11-25-1 | 2025-11-25 | 1,019 | 1,210 | 0.444 | 0.430 | -0.013 [-0.039, 0.018] | 0.054 | 0.060 | 0.006 [-0.005, 0.022] |
| cl-2026-03-11-1 | 2026-03-11 | 1,270 | 1,140 | 0.461 | 0.501 | 0.040 [0.009, 0.060] | 0.066 | 0.052 | -0.014 [-0.024, -0.007] |
| cl-2026-03-12-3 | 2026-03-12 | 1,131 | 1,167 | 0.469 | 0.499 | 0.030 [0.002, 0.051] | 0.062 | 0.052 | -0.010 [-0.024, 0.000] |
| cl-2026-03-16-1 | 2026-03-16 | 1,067 | 1,225 | 0.476 | 0.477 | 0.001 [-0.024, 0.024] | 0.055 | 0.055 | 0.000 [-0.013, 0.012] |
| cl-2026-03-24-1 | 2026-03-24 | 1,225 | 928 | 0.477 | 0.411 | -0.066 [-0.123, -0.020] | 0.055 | 0.071 | 0.017 [0.002, 0.033] |
| cl-2026-03-26-1 | 2026-03-26 | 1,152 | 890 | 0.437 | 0.403 | -0.034 [-0.078, 0.003] | 0.064 | 0.071 | 0.007 [-0.008, 0.024] |
| cl-2026-03-26-3 | 2026-03-26 | 1,152 | 890 | 0.437 | 0.403 | -0.034 [-0.078, 0.003] | 0.064 | 0.071 | 0.007 [-0.008, 0.024] |
| cl-2026-06-01-3 | 2026-06-01 | 1,030 | 1,231 | 0.322 | 0.329 | 0.007 [-0.024, 0.039] | 0.105 | 0.119 | 0.013 [-0.012, 0.036] |
| cl-2026-06-02-1 | 2026-06-02 | 948 | 1,461 | 0.316 | 0.325 | 0.009 [-0.026, 0.043] | 0.099 | 0.107 | 0.008 [-0.025, 0.037] |
| cl-2026-06-03-2 | 2026-06-03 | 951 | 1,795 | 0.318 | 0.326 | 0.009 [-0.033, 0.052] | 0.103 | 0.081 | -0.022 [-0.059, 0.018] |
| cl-2026-06-11-1 | 2026-06-11 | 1,795 | 1,471 | 0.326 | 0.350 | 0.024 [-0.011, 0.055] | 0.081 | 0.069 | -0.012 [-0.023, 0.001] |
| cl-2026-07-03-2 | 2026-07-03 | 2,399 | 3,211 | 0.372 | 0.322 | -0.050 [-0.114, 0.019] | 0.074 | 0.082 | 0.008 [-0.019, 0.032] |

## 10. By anchor type (standard agents pooled)

| type | units | unit-trials | h1 | h2 | h9+ | geometric h | modification rate | restored share of lost |
|---|---|---|---|---|---|---|---|---|
| url | 105,054 | 1,053,640 | 0.356 [0.271, 0.426] | 0.314 [0.283, 0.346] | 0.024 [0.020, 0.031] | 0.099 | 0.003 | 0.123 |
| email | 5,220 | 105,187 | 0.344 [0.302, 0.386] | 0.210 [0.175, 0.252] | 0.016 [0.011, 0.025] | 0.049 | 0.001 | 0.240 |
| phone | 207 | 1,485 | 0.377 [0.181, 0.518] | 0.271 [0.192, 0.358] | 0.052 [0.031, 0.090] | 0.139 | 0.001 | 0.130 |
| date | 24,522 | 388,095 | 0.317 [0.269, 0.359] | 0.217 [0.187, 0.246] | 0.026 [0.021, 0.032] | 0.062 | 0.006 | 0.442 |
| time | 689,941 | 8,524,928 | 0.301 [0.273, 0.336] | 0.328 [0.294, 0.363] | 0.018 [0.013, 0.027] | 0.080 | 0.005 | 0.132 |
| money | 32,770 | 354,089 | 0.322 [0.267, 0.379] | 0.270 [0.239, 0.305] | 0.028 [0.021, 0.043] | 0.092 | 0.002 | 0.102 |
| percent | 103,973 | 652,157 | 0.382 [0.332, 0.422] | 0.372 [0.335, 0.400] | 0.038 [0.031, 0.052] | 0.159 | 0.006 | 0.121 |
| number | 2,237,529 | 12,767,224 | 0.340 [0.276, 0.401] | 0.388 [0.355, 0.417] | 0.046 [0.038, 0.055] | 0.175 | 0.011 | 0.157 |
| agent | 3,151 | 487,639 | 0.269 [0.224, 0.313] | 0.168 [0.140, 0.198] | 0.002 [0.002, 0.003] | 0.006 | 0.000 | 0.867 |
| person | 232,313 | 2,781,977 | 0.382 [0.329, 0.426] | 0.328 [0.302, 0.353] | 0.019 [0.015, 0.025] | 0.083 | 0.002 | 0.162 |
| org | 471,556 | 6,351,781 | 0.391 [0.331, 0.433] | 0.294 [0.269, 0.319] | 0.018 [0.015, 0.021] | 0.074 | 0.002 | 0.127 |
| gpe | 45,540 | 1,369,730 | 0.239 [0.207, 0.268] | 0.229 [0.206, 0.252] | 0.012 [0.010, 0.014] | 0.033 | 0.000 | 0.195 |
| product | 48,029 | 1,006,336 | 0.284 [0.238, 0.325] | 0.247 [0.224, 0.271] | 0.015 [0.012, 0.019] | 0.047 | 0.000 | 0.141 |
| event | 8,832 | 152,541 | 0.350 [0.293, 0.397] | 0.276 [0.241, 0.311] | 0.016 [0.013, 0.019] | 0.057 | 0.000 | 0.078 |
| work_of_art | 134,030 | 1,884,937 | 0.297 [0.241, 0.340] | 0.308 [0.275, 0.341] | 0.019 [0.016, 0.023] | 0.071 | 0.001 | 0.079 |

## 11. Labelling file and memory_facts

- `/home/enxinson/ai-village-swarm-dynamics/data/labels/memory_pairs_rule_v2.csv` (mode 600): rule_label_v2 for the 500 units of memory_pairs.csv (100 pairs), labels {'kept': 288, 'dropped': 92, 'new': 56, 'restored': 38, 'modified': 26}; checks {'unit_not_found': 0, 'v1_label_differs': 0} (all expected 0).
- `/home/enxinson/ai-village-swarm-dynamics/data/interim/memory_facts_v2.parquet`: 7,692,996 presence spells of 4,157,421 (agent, unit) pairs; rows without a survival record (units seen only in undone rows): 1,599.

## 12. Outputs

- hazard: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_hazard_v2.csv`
- retention: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_retention_v2.csv`
- modification: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_modification_v2.csv`
- by_anchor: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_by_anchor_v2.csv`
- h2: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_h2_v2.csv`
- changelog: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_changelog_v2.csv`
- bdw: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_bdw_v2.csv`
- repeat_spells: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_repeat_spells_v2.csv`
- hazard_monthly: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_hazard_monthly_v2.parquet (+ .csv)`
- figure: `/home/enxinson/ai-village-swarm-dynamics/outputs/figures/F6_memory_retention_v2.{pdf,png}`

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
- All standard: H2 (constant hazard) is rejected at 5% (cluster Wald p = 5.5e-208; naive LR = 5529573.0, df 4). The hazard decreases from 0.340 at g = 1 to 0.025 at g >= 9; lowest AIC: beta-geometric.
- Anthropic: H2 (constant hazard) is rejected at 5% (cluster Wald p = 4.7e-175; naive LR = 2413128.2, df 4). The hazard decreases from 0.339 at g = 1 to 0.025 at g >= 9; lowest AIC: beta-geometric.
- OpenAI: H2 (constant hazard) is rejected at 5% (cluster Wald p = <1e-300; naive LR = 1655138.4, df 4). The hazard decreases from 0.448 at g = 1 to 0.020 at g >= 9; lowest AIC: beta-geometric.
- Google: H2 (constant hazard) is rejected at 5% (cluster Wald p = 9.9e-16; naive LR = 477587.0, df 4). The hazard decreases from 0.310 at g = 1 to 0.018 at g >= 9; lowest AIC: beta-geometric.
- Other: H2 (constant hazard) is rejected at 5% (cluster Wald p = 3.3e-56; naive LR = 1006556.5, df 4). The hazard decreases from 0.254 at g = 1 to 0.034 at g >= 9; lowest AIC: beta-geometric.
- Claude Code: H2 (constant hazard) is rejected at 5% (LR p = <1e-300; naive LR = 4791.0, df 4). The hazard decreases from 0.436 at g = 1 to 0.092 at g >= 9; lowest AIC: piecewise.
- Heterogeneity: for all standard agents the beta-geometric model (2 parameters) lowers AIC by 6,096,740 against the geometric model and by 567,175 against the 5-bin piecewise hazard. Most of the decline of h_g is therefore what a mix of units with different but constant hazards produces (fitted mean hazard a / (a + b) = 0.371): units that survive early consolidations are the durable ones. H2 fails at the population level, not necessarily for a single unit.
- Expectation (schema_notes 4.2): a rewrite keeps 40-70% of its input lines, so units already in consolidated memory should face a first-consolidation hazard of roughly 0.3-0.6, and units that arrive in appended session logs a higher one, because a consolidation compresses those logs. Observed by entry kind: first h1 = 0.171; session h1 = 0.276; note h1 = 0.485; rewrite h1 = 0.427; fork h1 = 0.330.
- Verbatim line retention, standard agents (schema_notes 4.2: a rewrite keeps 40-70% of its lines): median share of input lines kept unchanged per consolidation, pre 0.407 (IQR 0.242-0.585); post 0.503 (IQR 0.295-0.697). Unit-level retention is higher than line-level retention wherever rewrites rephrase lines but keep their values.
- Regime: before perma-computer-use h1 = 0.447 [0.418, 0.480], h9+ = 0.023 [0.019, 0.029]; after it h1 = 0.303 [0.249, 0.356], h2 = 0.376 [0.343, 0.406], h9+ = 0.026 [0.021, 0.032]. After the switch a consolidation follows every session, so one consolidation is a shorter time step, and the consolidation right after a session keeps more of it than the next one does (the hazard rises from g = 1 to g = 2), which no constant or monotone hazard model reproduces.
- CHANGELOG memory entries: 34 before/after hazard differences have a CI; 6 exclude zero: cl-2025-04-15-1 (g = 1: -0.161 [-0.288, -0.052]); cl-2026-03-11-1 (g = 1: 0.040 [0.009, 0.060]); cl-2026-03-11-1 (g >= 2: -0.014 [-0.024, -0.007]); cl-2026-03-12-3 (g = 1: 0.030 [0.002, 0.051]); cl-2026-03-24-1 (g = 1: -0.066 [-0.123, -0.020]); cl-2026-03-24-1 (g >= 2: 0.017 [0.002, 0.033]). Windows are short and other changes overlap, so these are associations.
- Modifications are 5.2% of first losses (213,901 of 4,124,330); the rest are drops.
- Restoration: 14.7% of lost units with later consolidations come back (294,170 re-appended, 310,558 recreated by a consolidation).
- Heterogeneity vs duration dependence (BdW): All standard c = 1.680 [1.357, 2.174]; Anthropic c = 1.796 [1.330, 2.885]; OpenAI c = 1.028 [0.868, 1.480]; Google c = 1.576 [0.987, 3.556]; Other c = 2.347 [1.615, 3.190]; Claude Code c = 0.554 [0.543, 0.565]; pre cohort c = 0.735 [0.606, 0.810]; post cohort c = 2.123 [1.655, 2.797]; All standard from g = 2 c = 0.424 [0.139, 0.660]; pre cohort from g = 2 c = 0.431 [0.257, 0.604]; post cohort from g = 2 c = 0.546 [0.174, 0.882]. Of 23 main scopes, c lies below 1 in 4, covers 1 in 10 and lies above 1 in 9; for all standard agents the BdW improves AIC by 81,557 over the beta-geometric (LR 81559, p <1e-300) and the lowest AIC is bdw. Identification: in single-spell data heterogeneity and duration dependence trade off (a falling population hazard can come from either), so c rests on the functional form of the Beta mixing distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed (section 8).
- Repeated spells (standard agents): 604,236 restored facts with a second spell; g = 1: spell 1 0.340, spell 2 0.363, difference 0.023 [-0.011, 0.064]; g = 2: spell 1 0.300, spell 2 0.244, difference -0.056 [-0.076, -0.040]; g = 9+: spell 1 0.024, spell 2 0.024, difference 0.000 [-0.003, 0.004]. Like-for-like subset (132,375 facts): g = 1: spell 1 0.401, spell 2 0.387, difference -0.014 [-0.026, 0.002]; g = 2: spell 1 0.268, spell 2 0.262, difference -0.007 [-0.020, 0.007]; g = 9+: spell 1 0.023, spell 2 0.024, difference 0.001 [-0.006, 0.006]. Descriptive only: spell 1 is selected to end in a loss, which biases its hazards upward (a negative difference is expected even with no change), and some restorations are key collisions.
- Missing values: rows without run_day 0, rows without regime 0, consolidations without run_day 0.
