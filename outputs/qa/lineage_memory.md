# QA: memory chains (module B1, SPEC 6.3)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Aggregates only. No memory text, names, emails, phone numbers or credentials appear in this report or in outputs/; URLs appear only as domains, PERSON/email/phone values and every value on a credential line are keyed hashes.

Runtime 687 s (inputs 1, lines + anchors 1 (cache hit), interning 8, chains 269, statistics and outputs 408). Line and anchor extraction when computed: 37 s + 1518 s.

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
| All standard | 45 | 83,836 | 4,146,180 | 4,142,667 | 14,220,326 |
| Anthropic | 15 | 33,543 | 1,823,793 | 1,822,944 | 5,780,180 |
| OpenAI | 14 | 23,427 | 945,760 | 945,260 | 3,057,536 |
| Google | 5 | 15,904 | 292,828 | 292,680 | 1,736,051 |
| Other | 11 | 10,962 | 1,083,799 | 1,081,783 | 3,646,559 |
| Claude Code | 1 | 1,764 | 9,657 | 9,653 | 39,791 |

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
| unit-trials (sum over consolidations of units at risk) | 14,260,117 |
| kept | 10,115,763 |
| dropped | 3,179,967 |
| modified | 964,387 |
| restorations | 2,292,507 |
| units first seen in a consolidation output | 1,384,660 |
| never-lost units missing from the consolidation input (after a truncation) | 1 |
| undo rows (revert, trunc_other) | 119 |
| fork rows extending an older row | 52 |
| units removed from tracking by an undo | 2,202 |
| first losses: dropped / modified / censored | 3,179,967 / 964,387 / 7,966 |
| unit-trials: per-unit sum vs per-consolidation sum | 14,260,117 vs 14,260,117 (ok) |
| first losses: per-unit vs per-consolidation | 4,144,354 vs 4,144,354 (ok) |

## 4. Hazard of loss by model family (H2)

h_g = P(lost at consolidation g | kept through g - 1). 95% CIs resample agents within the group (2000 replicates, seed 20261003); Claude Code is one agent, so its CIs treat units as independent (Wilson). Generations with fewer than 30 units at risk are not reported.

| group | agents | unit-trials | h1 | h2 | h3-4 | h5-8 | h9+ | geometric h |
|---|---|---|---|---|---|---|---|---|
| All standard | 45 | 14,220,326 | 0.522 [0.450, 0.581] | 0.506 [0.467, 0.537] | 0.302 [0.276, 0.325] | 0.174 [0.157, 0.191] | 0.045 [0.039, 0.054] | 0.291 |
| Anthropic | 15 | 5,780,180 | 0.541 [0.437, 0.617] | 0.530 [0.494, 0.556] | 0.311 [0.284, 0.339] | 0.181 [0.163, 0.202] | 0.045 [0.034, 0.064] | 0.315 |
| OpenAI | 14 | 3,057,536 | 0.630 [0.553, 0.681] | 0.436 [0.379, 0.471] | 0.287 [0.236, 0.324] | 0.173 [0.141, 0.203] | 0.043 [0.033, 0.058] | 0.309 |
| Google | 5 | 1,736,051 | 0.434 [0.224, 0.606] | 0.404 [0.304, 0.490] | 0.236 [0.179, 0.292] | 0.135 [0.104, 0.196] | 0.036 [0.033, 0.041] | 0.168 |
| Other | 11 | 3,646,559 | 0.419 [0.300, 0.528] | 0.539 [0.445, 0.594] | 0.323 [0.263, 0.383] | 0.183 [0.149, 0.225] | 0.057 [0.045, 0.079] | 0.296 |
| Claude Code | 1 | 39,791 | 0.517 [0.507, 0.527] | 0.278 [0.266, 0.291] | 0.185 [0.176, 0.195] | 0.130 [0.122, 0.137] | 0.103 [0.098, 0.109] | 0.241 |

H2 tests: geometric (constant hazard) vs piecewise-constant hazard over g = 1, 2, 3-4, 5-8, 9+. The likelihood-ratio test treats units as independent; the Wald test uses the cluster-bootstrap covariance. The beta-geometric model lets each unit keep a constant hazard drawn from a Beta distribution, which makes the population hazard decrease with g.

| scope | stratum | LR | df | p (LR) | Wald | p (Wald, cluster) | AIC geometric | AIC beta-geometric | AIC piecewise | beta-geom a, b |
|---|---|---|---|---|---|---|---|---|---|---|
| family | All standard | 3477420.3 | 4 | <1e-300 | 1502.9 | <1e-300 | 17144991 | 13606185 | 13667579 | 1.621, 1.351 |
| family | Anthropic | 1488360.9 | 4 | <1e-300 | 1213.9 | 1.6e-261 | 7201850 | 5688225 | 5713497 | 1.722, 1.327 |
| family | OpenAI | 979250.2 | 4 | <1e-300 | 3818.5 | <1e-300 | 3779260 | 2765579 | 2800018 | 1.249, 0.727 |
| family | Google | 332113.8 | 4 | <1e-300 | 74.5 | 2.5e-15 | 1573457 | 1227876 | 1241351 | 1.189, 1.427 |
| family | Other | 650530.9 | 4 | <1e-300 | 502.9 | 1.6e-107 | 4428716 | 3830024 | 3778193 | 2.131, 2.348 |
| family | Claude Code | 5615.6 | 4 | <1e-300 | n/a | n/a | 43978 | 38919 | 38370 | 1.066, 1.098 |
| regime:pre | All standard | 1259331.8 | 4 | <1e-300 | 3481.3 | <1e-300 | 4178545 | n/a | 2919221 | n/a, n/a |
| regime:pre | Anthropic | 743176.5 | 4 | <1e-300 | 5341.9 | <1e-300 | 2353629 | n/a | 1610461 | n/a, n/a |
| regime:pre | OpenAI | 228031.4 | 4 | <1e-300 | 650.2 | 2.2e-139 | 879089 | n/a | 651065 | n/a, n/a |
| regime:pre | Google | 137811.6 | 4 | <1e-300 | n/a | n/a | 447748 | n/a | 309945 | n/a, n/a |
| regime:pre | Other | 123792.4 | 4 | <1e-300 | n/a | n/a | 463968 | n/a | 340184 | n/a, n/a |
| regime:post | All standard | 2385211.8 | 4 | <1e-300 | 1147.3 | 4.2e-247 | 12956023 | n/a | 10570819 | n/a, n/a |
| regime:post | Anthropic | 848890.5 | 4 | <1e-300 | 502.3 | 2.1e-107 | 4848222 | n/a | 3999339 | n/a, n/a |
| regime:post | OpenAI | 733996.6 | 4 | <1e-300 | 15990.9 | <1e-300 | 2875419 | n/a | 2141430 | n/a, n/a |
| regime:post | Google | 200877.5 | 4 | <1e-300 | n/a | n/a | 1104436 | n/a | 903566 | n/a, n/a |
| regime:post | Other | 559397.4 | 4 | <1e-300 | 584.3 | 3.8e-125 | 3959557 | n/a | 3400168 | n/a, n/a |
| memory_epoch | [2025-04-02, 2025-04-15) | 5312.3 | 4 | <1e-300 | n/a | n/a | 15231 | n/a | 9927 | n/a, n/a |
| memory_epoch | [2025-04-15, 2025-04-16) | 407.2 | 4 | 7.8e-87 | n/a | n/a | 1298 | n/a | 899 | n/a, n/a |
| memory_epoch | [2025-04-16, 2025-08-20) | 146417.6 | 4 | <1e-300 | 1412.7 | <1e-300 | 417095 | n/a | 270686 | n/a, n/a |
| memory_epoch | [2025-08-20, 2025-09-05) | 46690.4 | 4 | <1e-300 | 1579.4 | <1e-300 | 141988 | n/a | 95305 | n/a, n/a |
| memory_epoch | [2025-09-05, 2025-10-14) | 110353.4 | 4 | <1e-300 | 824.6 | 3.6e-177 | 361482 | n/a | 251136 | n/a, n/a |
| memory_epoch | [2025-10-14, 2025-11-25) | 201848.7 | 4 | <1e-300 | 1680.5 | <1e-300 | 643496 | n/a | 441655 | n/a, n/a |
| memory_epoch | [2025-11-25, 2026-03-11) | 654899.6 | 4 | <1e-300 | 4919.5 | <1e-300 | 2326651 | n/a | 1671759 | n/a, n/a |
| memory_epoch | [2026-03-11, 2026-03-12) | 8289.0 | 4 | <1e-300 | 804.4 | 8.6e-173 | 27318 | n/a | 19037 | n/a, n/a |
| memory_epoch | [2026-03-12, 2026-03-16) | 16485.4 | 4 | <1e-300 | 2048.6 | <1e-300 | 49896 | n/a | 33419 | n/a, n/a |
| memory_epoch | [2026-03-16, 2026-03-24) | 47140.4 | 4 | <1e-300 | 1581.5 | <1e-300 | 165202 | n/a | 118070 | n/a, n/a |
| memory_epoch | [2026-03-24, 2026-03-26) | 14408.7 | 4 | <1e-300 | 361.1 | 7e-77 | 75988 | n/a | 61588 | n/a, n/a |
| memory_epoch | [2026-03-26, 2026-06-01) | 331596.5 | 4 | <1e-300 | 766.7 | 1.3e-164 | 1832039 | n/a | 1500451 | n/a, n/a |
| memory_epoch | [2026-06-01, 2026-06-02) | 6275.7 | 4 | <1e-300 | 547.0 | 4.5e-117 | 37328 | n/a | 31060 | n/a, n/a |
| memory_epoch | [2026-06-02, 2026-06-03) | 6292.1 | 4 | <1e-300 | 292.5 | 4.5e-62 | 39592 | n/a | 33308 | n/a, n/a |
| memory_epoch | [2026-06-03, 2026-06-11) | 92069.3 | 4 | <1e-300 | 366.7 | 4.3e-78 | 455956 | n/a | 363895 | n/a, n/a |
| memory_epoch | [2026-06-11, 2026-07-03) | 247945.0 | 4 | <1e-300 | 825.1 | 2.9e-177 | 1037641 | n/a | 789704 | n/a, n/a |
| memory_epoch | [2026-07-03, end] | 1684192.4 | 4 | <1e-300 | 870.6 | 3.9e-187 | 9448039 | n/a | 7763855 | n/a, n/a |
| entry_kind | first | 5343.7 | 4 | <1e-300 | 223.5 | 3.4e-47 | 22443 | 16161 | 17108 | 0.418, 1.069 |
| entry_kind | session | 1894708.1 | 4 | <1e-300 | 1345.9 | 3.8e-290 | 10403061 | 8599082 | 8508360 | 2.014, 2.050 |
| entry_kind | note | 388175.6 | 4 | <1e-300 | 6574.4 | <1e-300 | 898719 | 505719 | 510551 | 0.967, 0.221 |
| entry_kind | rewrite | 1318633.1 | 4 | <1e-300 | 2535.4 | <1e-300 | 5678900 | 4314932 | 4360275 | 1.176, 0.766 |
| entry_kind | fork | 103.1 | 4 | 2.2e-21 | 99.8 | 1.1e-20 | 1184 | 1154 | 1089 | 5.787, 4.432 |

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
| All standard | 1 | 4,142,667 | 0.110 [0.099, 0.120] | 0.210 [0.193, 0.230] |
| All standard | 2 | 1,979,050 | 0.149 [0.121, 0.184] | 0.295 [0.253, 0.348] |
| All standard | 3 | 977,354 | 0.084 [0.070, 0.099] | 0.252 [0.222, 0.289] |
| All standard | 5 | 484,669 | 0.045 [0.037, 0.054] | 0.219 [0.193, 0.249] |
| All standard | 10 | 203,255 | 0.020 [0.016, 0.025] | 0.186 [0.162, 0.212] |
| Anthropic | 1 | 1,822,944 | 0.116 [0.097, 0.130] | 0.215 [0.199, 0.237] |
| Anthropic | 2 | 836,129 | 0.148 [0.130, 0.163] | 0.280 [0.254, 0.300] |
| Anthropic | 3 | 392,869 | 0.081 [0.070, 0.092] | 0.236 [0.214, 0.261] |
| Anthropic | 5 | 190,088 | 0.042 [0.035, 0.050] | 0.200 [0.177, 0.223] |
| Anthropic | 10 | 76,093 | 0.020 [0.016, 0.027] | 0.174 [0.151, 0.200] |
| OpenAI | 1 | 945,260 | 0.112 [0.100, 0.118] | 0.178 [0.157, 0.201] |
| OpenAI | 2 | 349,505 | 0.096 [0.079, 0.112] | 0.221 [0.194, 0.251] |
| OpenAI | 3 | 197,134 | 0.066 [0.052, 0.076] | 0.211 [0.190, 0.232] |
| OpenAI | 5 | 101,777 | 0.040 [0.029, 0.049] | 0.196 [0.171, 0.218] |
| OpenAI | 10 | 42,860 | 0.017 [0.013, 0.021] | 0.160 [0.135, 0.178] |
| Google | 1 | 292,680 | 0.075 [0.048, 0.096] | 0.174 [0.154, 0.228] |
| Google | 2 | 165,718 | 0.099 [0.068, 0.132] | 0.244 [0.194, 0.314] |
| Google | 3 | 98,772 | 0.061 [0.037, 0.101] | 0.236 [0.175, 0.342] |
| Google | 5 | 58,099 | 0.036 [0.019, 0.081] | 0.222 [0.141, 0.342] |
| Google | 10 | 30,126 | 0.016 [0.010, 0.036] | 0.186 [0.135, 0.292] |
| Other | 1 | 1,081,783 | 0.106 [0.089, 0.132] | 0.252 [0.203, 0.340] |
| Other | 2 | 627,698 | 0.193 [0.122, 0.260] | 0.357 [0.257, 0.455] |
| Other | 3 | 288,579 | 0.107 [0.071, 0.141] | 0.299 [0.222, 0.382] |
| Other | 5 | 134,705 | 0.057 [0.037, 0.077] | 0.261 [0.193, 0.333] |
| Other | 10 | 54,176 | 0.025 [0.015, 0.040] | 0.222 [0.152, 0.298] |
| Claude Code | 1 | 9,653 | 0.124 [0.118, 0.131] | 0.240 [0.229, 0.252] |
| Claude Code | 2 | 4,663 | 0.054 [0.048, 0.061] | 0.194 [0.174, 0.217] |
| Claude Code | 3 | 3,355 | 0.036 [0.030, 0.043] | 0.176 [0.150, 0.207] |
| Claude Code | 5 | 2,232 | 0.013 [0.009, 0.019] | 0.096 [0.068, 0.134] |
| Claude Code | 10 | 1,138 | 0.021 [0.014, 0.031] | 0.194 [0.134, 0.272] |

| group | lost | lost with later trials | restored | share restored | reappended | recreated | median gap (consolidations) | share restored at the next consolidation | re-lost after restoration |
|---|---|---|---|---|---|---|---|---|---|
| All standard | 4,134,752 | 4,131,554 | 758,165 | 0.184 | 342,590 | 415,575 | 27.0 | 0.154 | 754,797 |
| Anthropic | 1,820,272 | 1,819,390 | 340,029 | 0.187 | 170,269 | 169,760 | 38.0 | 0.146 | 338,943 |
| OpenAI | 943,736 | 943,174 | 207,820 | 0.220 | 46,087 | 161,733 | 12.0 | 0.186 | 207,259 |
| Google | 292,167 | 292,016 | 42,436 | 0.145 | 23,880 | 18,556 | 40.0 | 0.128 | 42,158 |
| Other | 1,078,577 | 1,076,974 | 167,880 | 0.156 | 102,354 | 65,526 | 32.0 | 0.138 | 166,437 |
| Claude Code | 9,602 | 9,602 | 2,025 | 0.211 | 7 | 2,018 | 15.0 | 0.158 | 2,018 |

A restoration is the same unit key reappearing. For quantities with a generic context key (e.g. a small count of tasks) a later, unrelated fact can share the key, so restoration shares are upper bounds; by anchor type they are in memory_by_anchor.csv.

## 6. Regime (perma-computer-use), entry kind and memory-system epochs

| scope | stratum | agents | unit-trials | h1 | h2 | h3-4 | h5-8 | h9+ | geometric h |
|---|---|---|---|---|---|---|---|---|---|
| regime:pre | All standard | 23 | 3,361,892 | 0.684 [0.662, 0.705] | 0.397 [0.361, 0.425] | 0.258 [0.230, 0.286] | 0.151 [0.135, 0.170] | 0.045 [0.040, 0.054] | 0.313 |
| regime:pre | Anthropic | 9 | 1,889,606 | 0.693 [0.669, 0.711] | 0.408 [0.378, 0.435] | 0.257 [0.224, 0.293] | 0.151 [0.133, 0.180] | 0.042 [0.036, 0.056] | 0.315 |
| regime:pre | OpenAI | 9 | 657,600 | 0.696 [0.649, 0.798] | 0.433 [0.367, 0.489] | 0.302 [0.236, 0.347] | 0.175 [0.128, 0.209] | 0.055 [0.043, 0.070] | 0.389 |
| regime:pre | Google | 3 | 400,816 | 0.646 [0.521, 0.697] | 0.368 [0.334, 0.401] | 0.237 [0.201, 0.249] | 0.147 [0.147, 0.148] | 0.037 [0.034, 0.044] | 0.247 |
| regime:pre | Other | 2 | 413,870 | 0.643 [0.566, 0.693] | 0.293 [0.215, 0.367] | 0.207 [0.173, 0.249] | 0.122 [0.107, 0.143] | 0.055 [0.051, 0.058] | 0.248 |
| regime:post | All standard | 34 | 10,858,434 | 0.466 [0.394, 0.534] | 0.528 [0.484, 0.563] | 0.314 [0.284, 0.344] | 0.181 [0.161, 0.203] | 0.045 [0.037, 0.057] | 0.284 |
| regime:post | Anthropic | 11 | 3,890,574 | 0.467 [0.366, 0.558] | 0.564 [0.522, 0.601] | 0.333 [0.304, 0.372] | 0.196 [0.177, 0.220] | 0.047 [0.029, 0.078] | 0.315 |
| regime:post | OpenAI | 9 | 2,399,936 | 0.606 [0.518, 0.660] | 0.436 [0.373, 0.473] | 0.282 [0.231, 0.321] | 0.172 [0.141, 0.205] | 0.040 [0.032, 0.056] | 0.287 |
| regime:post | Google | 4 | 1,335,235 | 0.325 [0.162, 0.529] | 0.413 [0.292, 0.550] | 0.236 [0.168, 0.325] | 0.131 [0.098, 0.240] | 0.035 [0.032, 0.044] | 0.145 |
| regime:post | Other | 10 | 3,232,689 | 0.396 [0.282, 0.517] | 0.555 [0.464, 0.611] | 0.336 [0.272, 0.410] | 0.192 [0.156, 0.253] | 0.057 [0.043, 0.102] | 0.302 |
| memory_epoch | [2025-04-02, 2025-04-15) | 4 | 11,743 | 0.862 [0.783, 0.936] | 0.495 [0.463, 0.633] | 0.291 [0.171, 0.557] | 0.153 [0.133, 0.400] | 0.058 [0.046, 0.200] | 0.648 |
| memory_epoch | [2025-04-15, 2025-04-16) | 3 | 959 | 0.726 [0.569, 0.848] | 0.235 [0.114, 0.588] | 0.092 [0.079, 0.667] | 0.246 [0.246, 0.246] | 0.025 [0.025, 0.025] | 0.407 |
| memory_epoch | [2025-04-16, 2025-08-20) | 10 | 334,139 | 0.724 [0.663, 0.821] | 0.391 [0.342, 0.514] | 0.241 [0.196, 0.375] | 0.144 [0.121, 0.244] | 0.041 [0.032, 0.093] | 0.316 |
| memory_epoch | [2025-08-20, 2025-09-05) | 7 | 115,193 | 0.709 [0.635, 0.760] | 0.376 [0.317, 0.429] | 0.228 [0.207, 0.252] | 0.138 [0.129, 0.155] | 0.045 [0.038, 0.061] | 0.307 |
| memory_epoch | [2025-09-05, 2025-10-14) | 8 | 352,354 | 0.644 [0.567, 0.731] | 0.292 [0.225, 0.397] | 0.182 [0.151, 0.244] | 0.104 [0.088, 0.138] | 0.043 [0.031, 0.050] | 0.209 |
| memory_epoch | [2025-10-14, 2025-11-25) | 10 | 527,439 | 0.686 [0.654, 0.717] | 0.386 [0.343, 0.420] | 0.256 [0.228, 0.287] | 0.156 [0.138, 0.177] | 0.042 [0.029, 0.068] | 0.299 |
| memory_epoch | [2025-11-25, 2026-03-11) | 15 | 1,826,117 | 0.679 [0.655, 0.695] | 0.414 [0.384, 0.440] | 0.276 [0.246, 0.305] | 0.162 [0.144, 0.183] | 0.048 [0.041, 0.059] | 0.334 |
| memory_epoch | [2026-03-11, 2026-03-12) | 11 | 22,255 | 0.670 [0.618, 0.712] | 0.411 [0.364, 0.474] | 0.269 [0.224, 0.322] | 0.160 [0.130, 0.198] | 0.038 [0.029, 0.059] | 0.303 |
| memory_epoch | [2026-03-12, 2026-03-16) | 11 | 39,661 | 0.709 [0.680, 0.733] | 0.421 [0.379, 0.455] | 0.260 [0.207, 0.316] | 0.149 [0.126, 0.177] | 0.042 [0.033, 0.065] | 0.323 |
| memory_epoch | [2026-03-16, 2026-03-24) | 12 | 132,032 | 0.671 [0.626, 0.709] | 0.407 [0.353, 0.456] | 0.248 [0.208, 0.297] | 0.150 [0.128, 0.186] | 0.046 [0.040, 0.057] | 0.318 |
| memory_epoch | [2026-03-24, 2026-03-26) | 12 | 62,245 | 0.582 [0.506, 0.640] | 0.387 [0.324, 0.438] | 0.261 [0.224, 0.302] | 0.167 [0.137, 0.203] | 0.059 [0.050, 0.075] | 0.299 |
| memory_epoch | [2026-03-26, 2026-06-01) | 18 | 1,425,479 | 0.541 [0.439, 0.614] | 0.543 [0.479, 0.596] | 0.320 [0.277, 0.366] | 0.184 [0.160, 0.209] | 0.055 [0.047, 0.068] | 0.342 |
| memory_epoch | [2026-06-01, 2026-06-02) | 18 | 30,666 | 0.463 [0.387, 0.529] | 0.515 [0.452, 0.581] | 0.297 [0.247, 0.357] | 0.173 [0.136, 0.222] | 0.041 [0.030, 0.056] | 0.297 |
| memory_epoch | [2026-06-02, 2026-06-03) | 18 | 30,795 | 0.504 [0.413, 0.579] | 0.563 [0.486, 0.637] | 0.330 [0.277, 0.391] | 0.191 [0.150, 0.234] | 0.064 [0.044, 0.085] | 0.343 |
| memory_epoch | [2026-06-03, 2026-06-11) | 19 | 394,605 | 0.501 [0.411, 0.582] | 0.487 [0.423, 0.552] | 0.282 [0.245, 0.331] | 0.156 [0.131, 0.188] | 0.044 [0.036, 0.056] | 0.265 |
| memory_epoch | [2026-06-11, 2026-07-03) | 20 | 909,097 | 0.530 [0.445, 0.597] | 0.508 [0.446, 0.565] | 0.271 [0.226, 0.328] | 0.151 [0.130, 0.183] | 0.040 [0.035, 0.049] | 0.258 |
| memory_epoch | [2026-07-03, end] | 32 | 8,005,547 | 0.441 [0.370, 0.509] | 0.529 [0.481, 0.566] | 0.318 [0.287, 0.349] | 0.186 [0.163, 0.209] | 0.045 [0.034, 0.059] | 0.277 |
| entry_kind | first | 44 | 152,486 | 0.306 [0.252, 0.361] | 0.149 [0.097, 0.204] | 0.071 [0.045, 0.104] | 0.051 [0.032, 0.075] | 0.006 [0.004, 0.009] | 0.014 |
| entry_kind | session | 45 | 8,690,963 | 0.442 [0.360, 0.518] | 0.554 [0.514, 0.583] | 0.321 [0.293, 0.348] | 0.181 [0.163, 0.199] | 0.046 [0.037, 0.058] | 0.286 |
| entry_kind | note | 27 | 659,116 | 0.814 [0.778, 0.847] | 0.450 [0.414, 0.477] | 0.263 [0.241, 0.288] | 0.142 [0.130, 0.159] | 0.038 [0.033, 0.042] | 0.425 |
| entry_kind | rewrite | 45 | 4,716,908 | 0.608 [0.566, 0.636] | 0.388 [0.342, 0.424] | 0.270 [0.238, 0.300] | 0.167 [0.148, 0.188] | 0.049 [0.043, 0.057] | 0.290 |
| entry_kind | fork | 7 | 853 | 0.494 [0.231, 0.908] | 0.742 [0.077, 0.837] | 0.417 [0.208, 0.609] | 0.151 [0.063, 0.500] | 0.196 [0.196, 0.196] | 0.512 |

Regime and epoch strata are trial-level: a consolidation counts in the regime (epoch) of its own row, so units that cross a boundary enter the later risk sets at their current g. Epochs run between consecutive dates of memory-category CHANGELOG entries (start date included). Entry kind is the relation of the row where the unit first appeared (session = scaffold session block, note = self-note append, rewrite = new in a consolidation output, first = the agent's first row).

## 7. Heterogeneity versus duration dependence (beta-discrete-Weibull)

BdW (Fader, Hardie, Liu, Davin and Steenburgh 2018): each fact has its own theta ~ Beta(a, b) and S(g | theta) = (1 - theta)^(g^c). c = 1 is the beta-geometric (heterogeneity alone); c < 1 means a fact's own hazard falls with the consolidations it has survived. Maximum likelihood on the same risk sets as section 4 (right-censoring included, every g kept individually); regime cohorts are the facts whose first trial falls before (pre, censored at the agent's switch) or after (post) the agent's switch to perma-computer-use, so neither cohort is left-truncated. The CI of c resamples agents (500 refits); Claude Code (one agent) has only a profile-likelihood CI, which treats facts as independent. The LR test of c = 1 (df 1) treats facts as independent and is anticonservative at these sample sizes; the decision rule uses the CI: if it covers 1 the falling population hazard is consistent with heterogeneity alone, if it lies below 1 there is duration dependence beyond heterogeneity.

| scope | stratum | from g | agents | facts | c [95% CI] | CI | LR (c = 1) | p | AIC BdW - beta-geom | AIC BdW - piecewise | lowest AIC | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| family | All standard | 1 | 45 | 4,142,667 | 2.555 [1.782, 4.896] | bootstrap | 100859.9 | <1e-300 | -100858 | -162252 | bdw | c > 1: a fact's own hazard rises with g |
| family | Anthropic | 1 | 15 | 1,822,944 | 2.998 [1.712, 9.770] | bootstrap | 48956.7 | <1e-300 | -48955 | -74227 | bdw | c > 1: a fact's own hazard rises with g |
| family | OpenAI | 1 | 14 | 945,260 | 1.133 [0.909, 1.552] | bootstrap | 393.9 | 1.2e-87 | -392 | -34831 | bdw | heterogeneity alone (c consistent with 1) |
| family | Google | 1 | 5 | 292,680 | 1.774 [0.939, 7.764] | bootstrap | 3899.1 | <1e-300 | -3897 | -17373 | bdw | heterogeneity alone (c consistent with 1) |
| family | Other | 1 | 11 | 1,081,783 | 4.194 [2.148, 14.478] | bootstrap | 83201.2 | <1e-300 | -83199 | -31369 | bdw | c > 1: a fact's own hazard rises with g |
| family | Claude Code | 1 | 1 | 9,653 | 0.513 [0.502, 0.524] | profile | 513.3 | 1.2e-113 | -511 | 37 | piecewise | duration dependence: a fact's own hazard falls with g |
| regime_cohort | pre | 1 | 23 | 1,054,178 | 0.773 [0.611, 0.891] | bootstrap | 1321.6 | 2.3e-289 | -1320 | -34553 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | post | 1 | 34 | 3,088,489 | 3.562 [2.226, 10.167] | bootstrap | 156350.4 | <1e-300 | -156348 | -126581 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | url | 1 | 45 | 105,054 | 1.357 [0.974, 1.820] | bootstrap | 713.2 | 4e-157 | -711 | -10450 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | email | 1 | 45 | 5,220 | 0.694 [0.554, 0.919] | bootstrap | 77.8 | 1.2e-18 | -76 | -1577 | bdw | duration dependence: a fact's own hazard falls with g |
| anchor_type | phone | 1 | 26 | 207 | 0.725 [0.469, 1.928] | bootstrap | 2.2 | 0.14 | -0 | -10 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | date | 1 | 45 | 24,522 | 0.608 [0.507, 0.770] | bootstrap | 642.3 | 1.1e-141 | -640 | -2025 | bdw | duration dependence: a fact's own hazard falls with g |
| anchor_type | time | 1 | 45 | 689,941 | 2.616 [1.709, 11.081] | bootstrap | 7296.5 | <1e-300 | -7295 | -6362 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | money | 1 | 42 | 32,770 | 1.287 [0.962, 1.630] | bootstrap | 108.9 | 1.7e-25 | -107 | -1571 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | percent | 1 | 44 | 103,973 | 1.707 [1.348, 2.189] | bootstrap | 1078.2 | 1.8e-236 | -1076 | -3701 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | number | 1 | 45 | 2,237,529 | 2.903 [1.866, 8.652] | bootstrap | 85270.5 | <1e-300 | -85269 | -52347 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | agent | 1 | 45 | 3,151 | 1.258 [0.680, 2.853] | bootstrap | 3.5 | 0.06 | -2 | -826 | bdw | heterogeneity alone (c consistent with 1) |
| anchor_type | person | 1 | 45 | 232,313 | 1.975 [1.419, 3.218] | bootstrap | 3916.7 | <1e-300 | -3915 | -19581 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | org | 1 | 45 | 471,556 | 1.541 [1.228, 2.145] | bootstrap | 2831.5 | <1e-300 | -2830 | -20162 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | gpe | 1 | 45 | 45,540 | 2.063 [1.506, 3.268] | bootstrap | 905.0 | 8e-199 | -903 | -2967 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | product | 1 | 45 | 48,029 | 2.004 [1.510, 2.841] | bootstrap | 779.1 | 1.9e-171 | -777 | -1850 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | event | 1 | 42 | 8,832 | 2.031 [1.502, 3.332] | bootstrap | 102.0 | 5.7e-24 | -100 | -169 | bdw | c > 1: a fact's own hazard rises with g |
| anchor_type | work_of_art | 1 | 45 | 134,030 | 1.963 [1.447, 2.834] | bootstrap | 3086.5 | <1e-300 | -3084 | -3907 | bdw | c > 1: a fact's own hazard rises with g |
| family | All standard | 2 | 45 | 1,979,050 | 0.714 [0.453, 1.041] | bootstrap | 836.8 | 5.3e-184 | -835 | -164487 | bdw | heterogeneity alone (c consistent with 1) |
| regime_cohort | pre | 2 | 23 | 332,368 | 0.181 [0.149, 0.440] | bootstrap | 1329.8 | 3.8e-291 | -1328 | -35436 | bdw | duration dependence: a fact's own hazard falls with g |
| regime_cohort | post | 2 | 34 | 1,646,533 | 0.893 [0.555, 11.336] | bootstrap | 126.2 | 2.8e-29 | -124 | -127251 | bdw | heterogeneity alone (c consistent with 1) |

From g = 2 rows use the likelihood conditional on surviving the first consolidation (the same model, with the g = 1 term dropped). After the switch to perma-computer-use the hazard rises from g = 1 to g = 2 (section 6: the consolidation right after a session keeps that session's facts, the next one prunes them); a BdW can only produce that rise with c > 1, so c > 1 in scopes dominated by post-switch facts reflects this two-step pattern rather than facts that wear out.

Observed and fitted hazards at g = 1, 2, 5, 10 (families and regime cohorts):

| scope | stratum | from g | g = 1 obs / BdW / BG | g = 2 | g = 5 | g = 10 |
|---|---|---|---|---|---|---|
| family | All standard | 1 | 0.522 / 0.522 / 0.545 | 0.506 / 0.503 / 0.408 | 0.206 / 0.212 / 0.233 | 0.109 / 0.106 / 0.135 |
| family | Anthropic | 1 | 0.541 / 0.541 / 0.565 | 0.530 / 0.529 / 0.425 | 0.212 / 0.217 / 0.244 | 0.117 / 0.109 / 0.143 |
| family | OpenAI | 1 | 0.630 / 0.630 / 0.632 | 0.436 / 0.432 / 0.420 | 0.203 / 0.207 / 0.209 | 0.106 / 0.110 / 0.114 |
| family | Google | 1 | 0.434 / 0.434 / 0.454 | 0.404 / 0.392 / 0.329 | 0.164 / 0.176 / 0.180 | 0.083 / 0.089 / 0.102 |
| family | Other | 1 | 0.419 / 0.419 / 0.476 | 0.539 / 0.539 / 0.389 | 0.218 / 0.223 / 0.251 | 0.115 / 0.113 / 0.158 |
| family | Claude Code | 1 | 0.517 / 0.514 / 0.493 | 0.278 / 0.265 / 0.337 | 0.140 / 0.163 / 0.173 | 0.109 / 0.116 / 0.095 |
| regime_cohort | pre | 1 | 0.684 / 0.685 / 0.683 | 0.397 / 0.388 / 0.411 | 0.181 / 0.190 / 0.187 | 0.098 / 0.105 / 0.098 |
| regime_cohort | post | 1 | 0.466 / 0.466 / 0.507 | 0.528 / 0.527 / 0.399 | 0.213 / 0.217 / 0.243 | 0.113 / 0.109 / 0.147 |
| family | All standard | 2 | n/a | 0.506 / 0.499 / 0.501 | 0.206 / 0.214 / 0.213 | 0.109 / 0.111 / 0.109 |
| regime_cohort | pre | 2 | n/a | 0.397 / 0.399 / 0.390 | 0.181 / 0.181 / 0.191 | 0.098 / 0.102 / 0.103 |
| regime_cohort | post | 2 | n/a | 0.528 / 0.522 / 0.524 | 0.213 / 0.220 / 0.219 | 0.113 / 0.112 / 0.111 |

Identification: in single-spell data heterogeneity and duration dependence trade off (a falling population hazard can come from either), so c rests on the functional form of the Beta mixing distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed (section 8).

## 8. Repeated spells of restored facts

Facts that were lost and later restored, with at least one consolidation after the restoration. Spell 1 runs from entry to the first loss, spell 2 from the restoring consolidation to the next loss (or the agent's last consolidation); trial g counts consolidations from the start of each spell, so both hazards come from the same facts at the same g. `like for like` keeps facts whose first spell also began as new content of a consolidation output and whose restoration was recreated by a consolidation, so both spells start the same way. CIs and the paired difference (spell 2 - spell 1) resample agents. These are descriptions: spell 1 is selected to end in a loss, and early losses leave more time for a restoration, so spell-1 hazards of restored facts are biased upward and a negative difference is expected even if nothing about the fact changed; and a restoration can be a key collision rather than the same fact (restoration shares in section 5 are upper bounds).

| check | value |
|---|---|
| restored facts | 760,190 |
| with >= 1 trial in spell 2 | 759,651 |
| spell 2 ended in a loss | 756,815 |
| re-lost facts in the chain (n_reloss > 0) | 756,815 |
| facts where the two disagree (expected 0) | 0 |
| restored facts absent from the restoring output (expected 0) | 0 |

| group | subset | facts | g | spell 1: n, h [95% CI] | spell 2: n, h [95% CI] | spell 2 - spell 1 [95% CI] | all facts, spell 1 |
|---|---|---|---|---|---|---|---|
| All standard | all restored | 757,626 | 1 | 757,626, 0.521 [0.456, 0.568] | 757,626, 0.501 [0.464, 0.527] | -0.020 [-0.057, 0.030] | 0.522 |
| All standard | all restored | 757,626 | 2 | 362,899, 0.439 [0.415, 0.461] | 377,922, 0.324 [0.289, 0.353] | -0.115 [-0.143, -0.088] | 0.506 |
| All standard | all restored | 757,626 | 3-4 | 345,025, 0.276 [0.256, 0.295] | 446,070, 0.229 [0.205, 0.253] | -0.047 [-0.057, -0.038] | 0.302 |
| All standard | all restored | 757,626 | 5-8 | 330,748, 0.163 [0.148, 0.177] | 478,541, 0.147 [0.131, 0.163] | -0.016 [-0.021, -0.012] | 0.174 |
| All standard | all restored | 757,626 | 9+ | 1,279,560, 0.042 [0.036, 0.051] | 1,951,689, 0.041 [0.035, 0.048] | -0.001 [-0.005, 0.002] | 0.045 |
| All standard | like for like | 177,755 | 1 | 177,755, 0.569 [0.526, 0.593] | 177,755, 0.528 [0.479, 0.556] | -0.041 [-0.051, -0.033] | 0.522 |
| All standard | like for like | 177,755 | 2 | 76,591, 0.386 [0.335, 0.416] | 83,771, 0.348 [0.288, 0.384] | -0.038 [-0.051, -0.028] | 0.506 |
| All standard | like for like | 177,755 | 3-4 | 80,372, 0.270 [0.229, 0.299] | 93,860, 0.249 [0.206, 0.281] | -0.021 [-0.031, -0.011] | 0.302 |
| All standard | like for like | 177,755 | 5-8 | 76,616, 0.169 [0.142, 0.192] | 94,336, 0.159 [0.130, 0.182] | -0.011 [-0.017, -0.004] | 0.174 |
| All standard | like for like | 177,755 | 9+ | 228,938, 0.054 [0.043, 0.067] | 334,249, 0.046 [0.036, 0.058] | -0.008 [-0.014, -0.004] | 0.045 |
| Anthropic | all restored | 339,844 | 1 | 339,844, 0.537 [0.434, 0.603] | 339,844, 0.516 [0.463, 0.550] | -0.021 [-0.067, 0.046] | 0.541 |
| Anthropic | all restored | 339,844 | 2 | 157,330, 0.451 [0.432, 0.466] | 164,362, 0.326 [0.282, 0.365] | -0.125 [-0.162, -0.095] | 0.530 |
| Anthropic | all restored | 339,844 | 3-4 | 145,810, 0.282 [0.262, 0.302] | 193,000, 0.234 [0.205, 0.262] | -0.048 [-0.061, -0.038] | 0.311 |
| Anthropic | all restored | 339,844 | 5-8 | 137,964, 0.167 [0.149, 0.185] | 203,841, 0.153 [0.133, 0.175] | -0.013 [-0.021, -0.006] | 0.181 |
| Anthropic | all restored | 339,844 | 9+ | 510,823, 0.044 [0.034, 0.061] | 741,032, 0.045 [0.038, 0.058] | 0.002 [-0.006, 0.006] | 0.045 |
| OpenAI | all restored | 207,728 | 1 | 207,728, 0.591 [0.518, 0.623] | 207,728, 0.500 [0.422, 0.535] | -0.091 [-0.138, -0.057] | 0.630 |
| OpenAI | all restored | 207,728 | 2 | 84,965, 0.404 [0.360, 0.425] | 103,783, 0.343 [0.251, 0.387] | -0.061 [-0.121, -0.033] | 0.436 |
| OpenAI | all restored | 207,728 | 3-4 | 86,027, 0.278 [0.230, 0.302] | 118,811, 0.238 [0.175, 0.279] | -0.039 [-0.058, -0.024] | 0.287 |
| OpenAI | all restored | 207,728 | 5-8 | 80,724, 0.171 [0.138, 0.193] | 123,859, 0.152 [0.114, 0.184] | -0.019 [-0.026, -0.009] | 0.173 |
| OpenAI | all restored | 207,728 | 9+ | 266,464, 0.049 [0.039, 0.058] | 491,999, 0.042 [0.030, 0.061] | -0.007 [-0.011, 0.003] | 0.043 |
| Google | all restored | 42,416 | 1 | 42,416, 0.417 [0.237, 0.581] | 42,416, 0.426 [0.318, 0.486] | 0.008 [-0.117, 0.127] | 0.434 |
| Google | all restored | 42,416 | 2 | 24,708, 0.371 [0.292, 0.440] | 24,358, 0.243 [0.176, 0.295] | -0.128 [-0.147, -0.106] | 0.404 |
| Google | all restored | 42,416 | 3-4 | 27,406, 0.212 [0.168, 0.259] | 33,388, 0.172 [0.133, 0.220] | -0.040 [-0.062, -0.027] | 0.236 |
| Google | all restored | 42,416 | 5-8 | 31,690, 0.123 [0.099, 0.162] | 42,152, 0.109 [0.084, 0.143] | -0.013 [-0.024, -0.007] | 0.135 |
| Google | all restored | 42,416 | 9+ | 250,310, 0.023 [0.019, 0.033] | 327,116, 0.024 [0.020, 0.035] | 0.001 [-0.003, 0.009] | 0.036 |
| Other | all restored | 167,638 | 1 | 167,638, 0.428 [0.309, 0.520] | 167,638, 0.490 [0.401, 0.550] | 0.062 [-0.045, 0.178] | 0.419 |
| Other | all restored | 167,638 | 2 | 95,896, 0.469 [0.396, 0.525] | 85,419, 0.321 [0.251, 0.384] | -0.147 [-0.178, -0.124] | 0.539 |
| Other | all restored | 167,638 | 3-4 | 85,782, 0.286 [0.234, 0.343] | 100,871, 0.228 [0.180, 0.286] | -0.058 [-0.070, -0.046] | 0.323 |
| Other | all restored | 167,638 | 5-8 | 80,370, 0.164 [0.136, 0.203] | 108,689, 0.142 [0.116, 0.181] | -0.022 [-0.030, -0.013] | 0.183 |
| Other | all restored | 167,638 | 9+ | 251,963, 0.052 [0.042, 0.067] | 391,542, 0.047 [0.038, 0.065] | -0.005 [-0.010, 0.003] | 0.057 |
| Claude Code | all restored | 2,025 | 1 | 2,025, 0.506 [0.484, 0.527] | 2,025, 0.495 [0.473, 0.517] | -0.011 [n/a, n/a] | 0.517 |
| Claude Code | all restored | 2,025 | 2 | 1,001, 0.307 [0.279, 0.336] | 1,021, 0.315 [0.288, 0.345] | 0.009 [n/a, n/a] | 0.278 |
| Claude Code | all restored | 2,025 | 3-4 | 1,243, 0.205 [0.184, 0.228] | 1,233, 0.200 [0.179, 0.224] | -0.005 [n/a, n/a] | 0.185 |
| Claude Code | all restored | 2,025 | 5-8 | 1,341, 0.161 [0.142, 0.182] | 1,462, 0.132 [0.116, 0.150] | -0.029 [n/a, n/a] | 0.130 |
| Claude Code | all restored | 2,025 | 9+ | 2,253, 0.099 [0.087, 0.112] | 2,937, 0.086 [0.077, 0.097] | -0.012 [n/a, n/a] | 0.103 |

Monthly hazards for module C: `outputs/tables/memory_hazard_monthly.parquet` (and .csv), 90 rows, 18 PT calendar months (2025-04-01 to 2026-09-01) x 5 groups, columns date, group, h1, h2, h3_4 (hazards of the consolidations in that month, null below 30 facts at risk; 5 null h1) and n_at_risk (all unit-trials of the month).

## 9. Memory-category CHANGELOG entries (+/- 5 run days, standard agents)

Consolidations whose run day falls in the window before the entry's first day or after its last day. Hazards need at least the reporting threshold of unit-trials; the difference (after - before) gets a paired agent-bootstrap CI only when at least 3 agents carry trials on each side.

| entry | date | cons before | cons after | h(g=1) before | h(g=1) after | diff [95% CI] | h(g>=2) before | h(g>=2) after | diff [95% CI] |
|---|---|---|---|---|---|---|---|---|---|
| cl-2025-04-02-2 | 2025-04-02 | 0 | 113 | n/a | 0.865 | n/a [n/a, n/a] | n/a | 0.264 | n/a [n/a, n/a] |
| cl-2025-04-15-1 | 2025-04-15 | 57 | 89 | 0.863 | 0.780 | -0.083 [-0.231, -0.002] | 0.183 | 0.148 | -0.035 [-0.361, 0.197] |
| cl-2025-04-16-1 | 2025-04-16 | 48 | 99 | 0.843 | 0.809 | -0.034 [-0.122, 0.045] | 0.165 | 0.147 | -0.017 [-0.364, 0.235] |
| cl-2025-08-20-1 | 2025-08-20 | 229 | 338 | 0.742 | 0.740 | -0.002 [-0.049, 0.036] | 0.151 | 0.163 | 0.012 [-0.123, 0.069] |
| cl-2025-09-05-2 | 2025-09-05 | 661 | 362 | 0.687 | 0.607 | -0.081 [-0.219, 0.030] | 0.118 | 0.103 | -0.015 [-0.084, 0.033] |
| cl-2025-10-14-1 | 2025-10-14 | 485 | 753 | 0.627 | 0.678 | 0.052 [0.016, 0.098] | 0.095 | 0.102 | 0.007 [-0.029, 0.056] |
| cl-2025-11-25-1 | 2025-11-25 | 1,019 | 1,210 | 0.673 | 0.666 | -0.006 [-0.025, 0.019] | 0.153 | 0.159 | 0.006 [-0.022, 0.037] |
| cl-2026-03-11-1 | 2026-03-11 | 1,270 | 1,140 | 0.666 | 0.704 | 0.038 [0.008, 0.061] | 0.179 | 0.147 | -0.033 [-0.056, -0.014] |
| cl-2026-03-12-3 | 2026-03-12 | 1,131 | 1,167 | 0.668 | 0.701 | 0.033 [0.002, 0.058] | 0.172 | 0.143 | -0.029 [-0.059, 0.008] |
| cl-2026-03-16-1 | 2026-03-16 | 1,067 | 1,225 | 0.680 | 0.665 | -0.015 [-0.042, 0.007] | 0.161 | 0.148 | -0.013 [-0.052, 0.028] |
| cl-2026-03-24-1 | 2026-03-24 | 1,225 | 928 | 0.665 | 0.575 | -0.090 [-0.153, -0.046] | 0.148 | 0.170 | 0.022 [-0.013, 0.063] |
| cl-2026-03-26-1 | 2026-03-26 | 1,152 | 890 | 0.616 | 0.564 | -0.051 [-0.096, -0.017] | 0.163 | 0.185 | 0.023 [-0.006, 0.055] |
| cl-2026-03-26-3 | 2026-03-26 | 1,152 | 890 | 0.616 | 0.564 | -0.051 [-0.096, -0.017] | 0.163 | 0.185 | 0.023 [-0.006, 0.055] |
| cl-2026-06-01-3 | 2026-06-01 | 1,030 | 1,231 | 0.482 | 0.499 | 0.017 [-0.014, 0.051] | 0.233 | 0.234 | 0.000 [-0.030, 0.032] |
| cl-2026-06-02-1 | 2026-06-02 | 948 | 1,461 | 0.473 | 0.490 | 0.017 [-0.020, 0.054] | 0.230 | 0.214 | -0.016 [-0.055, 0.020] |
| cl-2026-06-03-2 | 2026-06-03 | 951 | 1,795 | 0.480 | 0.500 | 0.020 [-0.019, 0.059] | 0.233 | 0.173 | -0.060 [-0.112, -0.011] |
| cl-2026-06-11-1 | 2026-06-11 | 1,795 | 1,471 | 0.500 | 0.527 | 0.028 [-0.011, 0.061] | 0.173 | 0.161 | -0.013 [-0.031, 0.017] |
| cl-2026-07-03-2 | 2026-07-03 | 2,399 | 3,211 | 0.523 | 0.508 | -0.015 [-0.079, 0.056] | 0.174 | 0.175 | 0.001 [-0.053, 0.045] |

## 10. By anchor type (standard agents pooled)

| type | units | unit-trials | h1 | h2 | h9+ | geometric h | modification rate | restored share of lost |
|---|---|---|---|---|---|---|---|---|
| url | 105,054 | 908,571 | 0.367 [0.280, 0.439] | 0.327 [0.295, 0.360] | 0.028 [0.023, 0.035] | 0.115 | 0.014 | 0.132 |
| email | 5,220 | 105,187 | 0.344 [0.302, 0.386] | 0.210 [0.175, 0.252] | 0.016 [0.011, 0.025] | 0.049 | 0.003 | 0.240 |
| phone | 207 | 1,485 | 0.377 [0.181, 0.518] | 0.271 [0.192, 0.358] | 0.052 [0.031, 0.090] | 0.139 | 0.001 | 0.130 |
| date | 24,522 | 337,733 | 0.333 [0.285, 0.376] | 0.230 [0.202, 0.259] | 0.028 [0.023, 0.034] | 0.072 | 0.015 | 0.460 |
| time | 689,941 | 1,383,726 | 0.670 [0.606, 0.718] | 0.587 [0.535, 0.629] | 0.083 [0.075, 0.094] | 0.498 | 0.113 | 0.161 |
| money | 32,770 | 174,090 | 0.473 [0.417, 0.529] | 0.383 [0.335, 0.424] | 0.037 [0.029, 0.055] | 0.188 | 0.020 | 0.158 |
| percent | 103,973 | 369,244 | 0.528 [0.459, 0.581] | 0.464 [0.420, 0.497] | 0.050 [0.039, 0.069] | 0.281 | 0.041 | 0.161 |
| number | 2,237,529 | 6,834,399 | 0.489 [0.412, 0.558] | 0.531 [0.488, 0.566] | 0.061 [0.052, 0.072] | 0.327 | 0.099 | 0.192 |
| agent | 3,151 | 200,594 | 0.307 [0.261, 0.353] | 0.211 [0.178, 0.245] | 0.005 [0.004, 0.007] | 0.015 | 0.003 | 0.872 |
| person | 232,313 | 1,221,581 | 0.488 [0.420, 0.544] | 0.437 [0.406, 0.463] | 0.029 [0.017, 0.050] | 0.189 | 0.015 | 0.199 |
| org | 471,556 | 1,792,518 | 0.548 [0.477, 0.598] | 0.447 [0.414, 0.474] | 0.043 [0.037, 0.052] | 0.263 | 0.034 | 0.177 |
| gpe | 45,540 | 211,789 | 0.473 [0.410, 0.529] | 0.448 [0.421, 0.471] | 0.037 [0.029, 0.047] | 0.214 | 0.010 | 0.267 |
| product | 48,029 | 163,509 | 0.530 [0.450, 0.598] | 0.488 [0.451, 0.517] | 0.047 [0.039, 0.059] | 0.293 | 0.015 | 0.213 |
| event | 8,832 | 23,808 | 0.600 [0.509, 0.666] | 0.517 [0.478, 0.550] | 0.056 [0.047, 0.069] | 0.370 | 0.010 | 0.131 |
| work_of_art | 134,030 | 492,092 | 0.460 [0.380, 0.526] | 0.468 [0.430, 0.501] | 0.056 [0.046, 0.071] | 0.272 | 0.023 | 0.124 |

## 11. Labelling file and memory_facts

- `/home/enxinson/ai-village-swarm-dynamics/data/labels/memory_pairs.csv`: 100 consolidation pairs (prev_uid = the consolidation's input row, next_uid = its output), 500 units, rule labels {'modified': 92, 'restored': 103, 'dropped': 103, 'new': 101, 'kept': 101}. human_label and notes are empty for the owner.
- `/home/enxinson/ai-village-swarm-dynamics/data/interim/memory_facts.parquet`: 7,692,996 presence spells of 4,157,421 (agent, unit) pairs; rows without a survival record (units seen only in undone rows): 1,599.

## 12. Outputs

- hazard: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_hazard.csv`
- retention: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_retention.csv`
- modification: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_modification.csv`
- by_anchor: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_by_anchor.csv`
- h2: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_h2.csv`
- changelog: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_changelog.csv`
- bdw: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_bdw.csv`
- repeat_spells: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_repeat_spells.csv`
- hazard_monthly: `/home/enxinson/ai-village-swarm-dynamics/outputs/tables/memory_hazard_monthly.parquet (+ .csv)`
- figure: `/home/enxinson/ai-village-swarm-dynamics/outputs/figures/F6_memory_retention.{pdf,png}`

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
- All standard: H2 (constant hazard) is rejected at 5% (cluster Wald p = <1e-300; naive LR = 3477420.3, df 4). The hazard decreases from 0.522 at g = 1 to 0.045 at g >= 9; lowest AIC: beta-geometric.
- Anthropic: H2 (constant hazard) is rejected at 5% (cluster Wald p = 1.6e-261; naive LR = 1488360.9, df 4). The hazard decreases from 0.541 at g = 1 to 0.045 at g >= 9; lowest AIC: beta-geometric.
- OpenAI: H2 (constant hazard) is rejected at 5% (cluster Wald p = <1e-300; naive LR = 979250.2, df 4). The hazard decreases from 0.630 at g = 1 to 0.043 at g >= 9; lowest AIC: beta-geometric.
- Google: H2 (constant hazard) is rejected at 5% (cluster Wald p = 2.5e-15; naive LR = 332113.8, df 4). The hazard decreases from 0.434 at g = 1 to 0.036 at g >= 9; lowest AIC: beta-geometric.
- Other: H2 (constant hazard) is rejected at 5% (cluster Wald p = 1.6e-107; naive LR = 650530.9, df 4). The hazard decreases from 0.419 at g = 1 to 0.057 at g >= 9; lowest AIC: piecewise.
- Claude Code: H2 (constant hazard) is rejected at 5% (LR p = <1e-300; naive LR = 5615.6, df 4). The hazard decreases from 0.517 at g = 1 to 0.103 at g >= 9; lowest AIC: piecewise.
- Heterogeneity: for all standard agents the beta-geometric model (2 parameters) lowers AIC by 3,538,806 against the geometric model and by 61,394 against the 5-bin piecewise hazard. Most of the decline of h_g is therefore what a mix of units with different but constant hazards produces (fitted mean hazard a / (a + b) = 0.545): units that survive early consolidations are the durable ones. H2 fails at the population level, not necessarily for a single unit.
- Expectation (schema_notes 4.2): a rewrite keeps 40-70% of its input lines, so units already in consolidated memory should face a first-consolidation hazard of roughly 0.3-0.6, and units that arrive in appended session logs a higher one, because a consolidation compresses those logs. Observed by entry kind: first h1 = 0.306; session h1 = 0.442; note h1 = 0.814; rewrite h1 = 0.608; fork h1 = 0.494.
- Verbatim line retention, standard agents (schema_notes 4.2: a rewrite keeps 40-70% of its lines): median share of input lines kept unchanged per consolidation, pre 0.407 (IQR 0.242-0.585); post 0.503 (IQR 0.295-0.697). Unit-level retention is higher than line-level retention wherever rewrites rephrase lines but keep their values.
- Regime: before perma-computer-use h1 = 0.684 [0.662, 0.705], h9+ = 0.045 [0.040, 0.054]; after it h1 = 0.466 [0.394, 0.534], h2 = 0.528 [0.484, 0.563], h9+ = 0.045 [0.037, 0.057]. After the switch a consolidation follows every session, so one consolidation is a shorter time step, and the consolidation right after a session keeps more of it than the next one does (the hazard rises from g = 1 to g = 2), which no constant or monotone hazard model reproduces.
- CHANGELOG memory entries: 34 before/after hazard differences have a CI; 9 exclude zero: cl-2025-04-15-1 (g = 1: -0.083 [-0.231, -0.002]); cl-2025-10-14-1 (g = 1: 0.052 [0.016, 0.098]); cl-2026-03-11-1 (g = 1: 0.038 [0.008, 0.061]); cl-2026-03-11-1 (g >= 2: -0.033 [-0.056, -0.014]); cl-2026-03-12-3 (g = 1: 0.033 [0.002, 0.058]); cl-2026-03-24-1 (g = 1: -0.090 [-0.153, -0.046]); cl-2026-03-26-1 (g = 1: -0.051 [-0.096, -0.017]); cl-2026-03-26-3 (g = 1: -0.051 [-0.096, -0.017]); cl-2026-06-03-2 (g >= 2: -0.060 [-0.112, -0.011]). Windows are short and other changes overlap, so these are associations.
- Modifications are 23.3% of first losses (964,387 of 4,144,354); the rest are drops.
- Restoration: 18.4% of lost units with later consolidations come back (342,590 re-appended, 415,575 recreated by a consolidation).
- Heterogeneity vs duration dependence (BdW): All standard c = 2.555 [1.782, 4.896]; Anthropic c = 2.998 [1.712, 9.770]; OpenAI c = 1.133 [0.909, 1.552]; Google c = 1.774 [0.939, 7.764]; Other c = 4.194 [2.148, 14.478]; Claude Code c = 0.513 [0.502, 0.524]; pre cohort c = 0.773 [0.611, 0.891]; post cohort c = 3.562 [2.226, 10.167]; All standard from g = 2 c = 0.714 [0.453, 1.041]; pre cohort from g = 2 c = 0.181 [0.149, 0.440]; post cohort from g = 2 c = 0.893 [0.555, 11.336]. Of 23 main scopes, c lies below 1 in 4, covers 1 in 6 and lies above 1 in 13; for all standard agents the BdW improves AIC by 100,858 over the beta-geometric (LR 100860, p <1e-300) and the lowest AIC is bdw. Identification: in single-spell data heterogeneity and duration dependence trade off (a falling population hazard can come from either), so c rests on the functional form of the Beta mixing distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed (section 8).
- Repeated spells (standard agents): 757,626 restored facts with a second spell; g = 1: spell 1 0.521, spell 2 0.501, difference -0.020 [-0.057, 0.030]; g = 2: spell 1 0.439, spell 2 0.324, difference -0.115 [-0.143, -0.088]; g = 9+: spell 1 0.042, spell 2 0.041, difference -0.001 [-0.005, 0.002]. Like-for-like subset (177,755 facts): g = 1: spell 1 0.569, spell 2 0.528, difference -0.041 [-0.051, -0.033]; g = 2: spell 1 0.386, spell 2 0.348, difference -0.038 [-0.051, -0.028]; g = 9+: spell 1 0.054, spell 2 0.046, difference -0.008 [-0.014, -0.004]. Descriptive only: spell 1 is selected to end in a loss, which biases its hazards upward (a negative difference is expected even with no change), and some restorations are key collisions.
- Missing values: rows without run_day 0, rows without regime 0, consolidations without run_day 0.
