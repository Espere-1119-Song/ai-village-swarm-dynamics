# QA: external validation of module A against the LLM monitor (V1, V2)

Generated 2026-10-01 16:03 UTC by `python -m avsd.validate.monitor_hawkes` in 14 s. Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village; monitor findings from theaidigest.org/village/monitor (fetched 2026-10-01T02:50:46.329235+00:00 to 2026-10-01T03:12:16.032243+00:00).

The monitor is a second reading of the same days by an LLM, not ground truth; its precision is unknown. Agreement or disagreement below says how module A's fit and that reading relate. Nothing here identifies a cause. Only aggregates, AI agent names, categories, severities and dates appear; finding and message text, human names and parent probabilities stay in `data/`.

## 1. Inputs

- Findings in the pinned export: 4,773; repeats dropped (same category, timestamp and roster agents): 14; kept 4,759. V1/V2 set (conflict with at least one roster agent, or any category with at least two): 1,483, of which conflict 80.
- Roster agents only: names that are not roster agents (humans, outside accounts, AI agents added after the export) are counted, never listed; 49 V1/V2 findings name at least one.
- Timestamps: findings that carry a reading-window label also carry an exact time; the share of those times inside the label's UTC window is pt_datetime 1,128 of 1,129; utc_time 820 of 822.
- Hawkes windows (accepted goal windows of module A whose dates hold findings): 8. Per-message parent-class probabilities are recomputed from the module A fits (`data/interim/hawkes_fit/fits`).

| Window | Group | Dates | K | Messages | Realizations | Other-agent share | Mass below 0.01 (mean) | Stored rows matched | Max abs diff to stored |
|---|---|---|---|---|---|---|---|---|---|
| g35-39 | best | 2026-03-16 to 2026-05-01 | 10 | 3,587 | 35 | 0.198 | 0.067 | 61,674 of 61,674 | 1.1e-16 |
| g38-39 | rest | 2026-04-02 to 2026-05-01 | 11 | 3,337 | 22 | 0.134 | 0.030 | 52,502 of 52,502 | 1.1e-16 |
| g45-47 | best | 2026-06-01 to 2026-06-19 | 7 | 1,758 | 16 | 0.473 | 0.066 | 29,454 of 29,454 | 1.1e-16 |
| g46-47 | rest | 2026-06-08 to 2026-06-19 | 13 | 5,812 | 11 | 0.169 | 0.125 | 101,910 of 101,910 | 2.2e-16 |
| g48-49 | general | 2026-06-22 to 2026-06-26 | 17 | 915 | 5 | 0.291 | 0.049 | 10,586 of 10,586 | 1.1e-16 |
| g50 | best | 2026-06-29 to 2026-07-03 | 6 | 1,204 | 5 | 0.388 | 0.094 | 15,105 of 15,105 | 1.1e-16 |
| g50 | rest | 2026-06-29 to 2026-07-03 | 15 | 1,969 | 5 | 0.181 | 0.069 | 23,701 of 23,701 | 1.1e-16 |
| g51 | general | 2026-07-06 to 2026-09-18 | 32 | 44,132 | 55 | 0.174 | 0.096 | 715,604 of 715,604 | 2.2e-16 |

Window shares recomputed from the messages agree with `hawkes_windows.csv` to 4.9e-05 (largest absolute difference over the five classes; the CSV has four decimals). Messages of a window missing from `hawkes_parents.parquet`: 1. Rows only in the recomputation (probabilities next to 0.01): 0.

## 2. Coverage

Per category of the V1/V2 set: findings, those naming a non-roster participant, those on a date of an accepted fitted window, those with a roster agent that is a dimension of such a window, those with at least one message of an involved agent within +-30 min in a fitted group, those that enter V1 (a flagged message in a stratum with controls), and the agent pairs of V2 with how many lie in one fitted group.

| Category | Findings | Non-roster names | Date in fitted window | Agent is a dimension | Flagged messages | Used in V1 | Pairs | Pairs covered |
|---|---|---|---|---|---|---|---|---|
| all | 1483 | 49 | 1483 | 1483 | 1430 | 1426 | 4819 | 4811 |
| conflict | 80 | 5 | 80 | 80 | 79 | 78 | 299 | 299 |
| off-goal | 159 | 9 | 159 | 159 | 151 | 151 | 782 | 782 |
| emotional-or-erratic | 47 | 0 | 47 | 47 | 42 | 41 | 183 | 183 |
| likely-scaffolding-issue | 65 | 0 | 65 | 65 | 56 | 56 | 175 | 175 |
| surreptitious-or-deceptive | 96 | 1 | 96 | 96 | 96 | 96 | 321 | 313 |
| outside-agent-contact | 45 | 6 | 45 | 45 | 44 | 44 | 229 | 229 |
| human-contact | 147 | 10 | 147 | 147 | 145 | 145 | 277 | 277 |
| unsolicited-outreach | 32 | 2 | 32 | 32 | 32 | 32 | 136 | 136 |
| good-tweet | 97 | 1 | 97 | 97 | 92 | 92 | 179 | 179 |
| interesting-content | 457 | 14 | 457 | 457 | 438 | 438 | 1465 | 1465 |
| other | 258 | 1 | 258 | 258 | 255 | 253 | 773 | 773 |

Pairs not covered: agent not a dimension 8.

## 3. V1: parent classes of the involved agents' messages near a finding

Flagged: messages of an involved agent within +-30 min of a finding. Control: the same agent's messages in the same realization and group outside the +-30 min window of every V1 finding that involves it. Values are mean posterior shares of each parent class (module A, exact); the control mean is weighted by the stratum's flagged messages; differences are flagged minus control with 95% percentile intervals from 2,000 draws of realizations. Co-involved: the share on messages of the agents it was flagged with (the other roster agents of the findings that flag the agent in that stratum), for flagged and control messages alike; it is part of the other-agent share. It is specific within one category (a conflict finding names a median of 2 roster agents); in the pooled rows a stratum's partner set is the union over many findings and grows toward all other agents. Other and own msgs: other agents' and the agent's own messages in the group in the 10 min before a message (context for the candidate parents).

| Subset | Findings used | Flagged msgs | Control msgs | Strata | Realizations | Other agents: flagged / control | Other agents diff | Co-involved diff | Human diff | System diff | Self diff | Baseline diff | Other msgs (10 min) diff | Own msgs (10 min) diff |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 1426 of 1483 | 21,184 | 20,824 | 961 | 64 | 0.167 / 0.187 | -0.020 [-0.026, -0.013] | -0.008 [-0.013, -0.002] | -0.002 [-0.005, -0.000] | -0.003 [-0.005, -0.001] | 0.039 [0.026, 0.052] | -0.014 [-0.022, -0.005] | 1.070 [0.412, 1.670] | 1.051 [0.692, 1.398] |
| category: conflict | 78 of 80 | 1,956 | 3,541 | 152 | 39 | 0.150 / 0.168 | -0.018 [-0.030, -0.007] | 0.009 [0.003, 0.014] | -0.001 [-0.007, 0.003] | -0.001 [-0.004, 0.002] | 0.044 [0.012, 0.074] | -0.024 [-0.049, 0.007] | 1.914 [0.363, 3.586] | 2.072 [1.181, 2.912] |
| category: off-goal | 151 of 159 | 4,772 | 8,107 | 324 | 53 | 0.152 / 0.172 | -0.021 [-0.033, -0.009] | -0.007 [-0.015, 0.001] | -0.003 [-0.007, -0.000] | -0.002 [-0.005, 0.000] | 0.032 [0.006, 0.058] | -0.006 [-0.025, 0.012] | 2.076 [1.012, 2.980] | 2.047 [1.342, 2.679] |
| category: emotional-or-erratic | 41 of 47 | 1,031 | 2,465 | 103 | 30 | 0.161 / 0.182 | -0.021 [-0.048, 0.004] | -0.004 [-0.018, 0.009] | -0.000 [-0.004, 0.002] | -0.001 [-0.007, 0.004] | 0.038 [-0.007, 0.079] | -0.015 [-0.048, 0.024] | 0.768 [-1.096, 2.415] | 0.830 [0.123, 1.450] |
| category: likely-scaffolding-issue | 56 of 65 | 979 | 2,411 | 101 | 34 | 0.192 / 0.192 | -0.000 [-0.033, 0.041] | 0.004 [-0.005, 0.012] | -0.001 [-0.007, 0.004] | -0.005 [-0.010, -0.001] | -0.028 [-0.084, 0.027] | 0.035 [-0.001, 0.077] | 1.991 [-0.754, 5.491] | 0.862 [0.127, 1.486] |
| category: surreptitious-or-deceptive | 96 of 96 | 2,614 | 4,502 | 180 | 41 | 0.157 / 0.188 | -0.031 [-0.049, -0.014] | -0.001 [-0.010, 0.007] | -0.004 [-0.012, 0.002] | -0.002 [-0.004, 0.001] | 0.065 [0.021, 0.102] | -0.028 [-0.055, 0.004] | 0.710 [-0.220, 1.775] | 0.927 [0.211, 1.515] |
| category: outside-agent-contact | 44 of 45 | 1,057 | 1,872 | 95 | 27 | 0.141 / 0.177 | -0.036 [-0.057, -0.018] | 0.004 [-0.018, 0.022] | -0.000 [-0.002, 0.002] | 0.001 [-0.005, 0.008] | 0.092 [0.054, 0.128] | -0.057 [-0.092, -0.022] | 0.720 [-1.729, 3.226] | 1.286 [0.283, 2.289] |
| category: human-contact | 145 of 147 | 2,188 | 4,027 | 201 | 42 | 0.169 / 0.199 | -0.030 [-0.045, -0.014] | -0.003 [-0.015, 0.010] | -0.004 [-0.011, 0.001] | -0.009 [-0.017, -0.003] | 0.047 [0.017, 0.076] | -0.004 [-0.028, 0.022] | 1.945 [0.847, 2.932] | 1.504 [0.647, 2.431] |
| category: unsolicited-outreach | 32 of 32 | 1,048 | 2,210 | 80 | 21 | 0.140 / 0.170 | -0.030 [-0.043, -0.017] | 0.004 [-0.008, 0.017] | -0.004 [-0.009, -0.000] | -0.003 [-0.009, 0.002] | 0.065 [0.025, 0.102] | -0.029 [-0.061, 0.008] | -0.941 [-5.296, 2.519] | 0.806 [-0.172, 1.974] |
| category: good-tweet | 92 of 97 | 1,730 | 4,317 | 176 | 40 | 0.160 / 0.196 | -0.036 [-0.051, -0.021] | -0.007 [-0.016, 0.001] | -0.002 [-0.004, -0.000] | -0.005 [-0.010, -0.001] | 0.065 [0.044, 0.086] | -0.022 [-0.041, -0.003] | 0.537 [-2.019, 2.505] | 1.029 [0.438, 1.844] |
| category: interesting-content | 438 of 457 | 7,860 | 13,437 | 582 | 61 | 0.183 / 0.198 | -0.015 [-0.024, -0.004] | 0.002 [-0.006, 0.009] | -0.001 [-0.004, 0.001] | -0.004 [-0.007, -0.001] | 0.035 [0.017, 0.051] | -0.015 [-0.026, -0.003] | 0.879 [-0.052, 1.768] | 0.928 [0.528, 1.317] |
| category: other | 253 of 258 | 5,176 | 10,535 | 415 | 58 | 0.161 / 0.180 | -0.018 [-0.030, -0.004] | -0.003 [-0.009, 0.004] | -0.002 [-0.005, 0.002] | -0.004 [-0.008, -0.001] | 0.037 [0.008, 0.063] | -0.013 [-0.030, 0.007] | 1.425 [-0.053, 2.836] | 0.839 [0.093, 1.585] |
| severity: low | 943 of 980 | 16,284 | 19,347 | 872 | 64 | 0.164 / 0.187 | -0.023 [-0.029, -0.016] | -0.008 [-0.013, -0.002] | -0.003 [-0.005, -0.000] | -0.003 [-0.006, -0.002] | 0.044 [0.030, 0.057] | -0.015 [-0.025, -0.005] | 1.277 [0.627, 1.951] | 1.236 [0.791, 1.667] |
| severity: medium/high | 483 of 503 | 9,119 | 13,532 | 581 | 59 | 0.172 / 0.188 | -0.016 [-0.026, -0.005] | -0.000 [-0.007, 0.007] | -0.001 [-0.004, 0.001] | -0.003 [-0.006, -0.001] | 0.033 [0.013, 0.053] | -0.013 [-0.026, 0.002] | 0.933 [0.008, 1.883] | 0.861 [0.519, 1.194] |

Intervals are not adjusted for the number of subsets. Severity rows pool categories.

## 4. V1 sensitivity

| Analysis | Subset | Flagged msgs | Control msgs | Strata | Clusters | Other agents diff | Co-involved diff | Self diff | Human diff | System diff |
|---|---|---|---|---|---|---|---|---|---|---|
| main | all | 21,184 | 20,824 | 961 | 64 | -0.020 [-0.026, -0.013] | -0.008 [-0.013, -0.002] | 0.039 [0.026, 0.052] | -0.002 [-0.005, -0.000] | -0.003 [-0.005, -0.001] |
| main | category: conflict | 1,956 | 3,541 | 152 | 39 | -0.018 [-0.030, -0.007] | 0.009 [0.003, 0.014] | 0.044 [0.012, 0.074] | -0.001 [-0.007, 0.003] | -0.001 [-0.004, 0.002] |
| strata also by hour of the run | all | 10,383 | 6,836 | 1521 | 64 | -0.005 [-0.013, 0.005] | 0.002 [-0.004, 0.008] | 0.028 [0.017, 0.040] | -0.003 [-0.006, -0.001] | -0.001 [-0.002, 0.001] |
| strata also by hour of the run | category: conflict | 798 | 440 | 94 | 33 | -0.002 [-0.024, 0.020] | 0.015 [0.002, 0.030] | 0.014 [-0.011, 0.039] | 0.003 [0.000, 0.009] | -0.003 [-0.009, 0.000] |
| controls outside every V1 finding window | all | 13,336 | 3,395 | 483 | 54 | -0.020 [-0.041, 0.001] | -0.012 [-0.025, 0.002] | 0.039 [-0.007, 0.095] | -0.006 [-0.015, 0.000] | -0.004 [-0.008, -0.001] |
| controls outside every V1 finding window | category: conflict | 1,235 | 432 | 69 | 29 | -0.007 [-0.055, 0.035] | 0.014 [0.007, 0.024] | 0.037 [-0.037, 0.120] | -0.007 [-0.023, 0.002] | -0.004 [-0.009, -0.001] |
| controls outside every finding of the agent | all | 21,089 | 15,135 | 944 | 64 | -0.021 [-0.029, -0.012] | -0.009 [-0.016, -0.001] | 0.040 [0.024, 0.056] | -0.002 [-0.005, -0.000] | -0.003 [-0.005, -0.002] |
| controls outside every finding of the agent | category: conflict | 1,956 | 2,468 | 152 | 39 | -0.020 [-0.034, -0.005] | 0.009 [0.003, 0.015] | 0.045 [0.010, 0.082] | -0.001 [-0.007, 0.003] | -0.002 [-0.005, 0.001] |
| half width 15 min | all | 13,926 | 27,877 | 943 | 64 | -0.008 [-0.014, -0.003] | 0.000 [-0.005, 0.005] | 0.016 [0.005, 0.026] | -0.001 [-0.003, 0.001] | -0.002 [-0.003, -0.000] |
| half width 15 min | category: conflict | 1,182 | 5,311 | 145 | 39 | -0.010 [-0.023, 0.002] | 0.013 [0.007, 0.020] | 0.025 [-0.006, 0.052] | -0.001 [-0.006, 0.004] | -0.001 [-0.005, 0.002] |
| half width 60 min | all | 25,774 | 12,513 | 899 | 64 | -0.038 [-0.050, -0.025] | -0.017 [-0.026, -0.008] | 0.066 [0.042, 0.089] | -0.002 [-0.004, 0.001] | -0.004 [-0.006, -0.002] |
| half width 60 min | category: conflict | 3,015 | 1,675 | 134 | 39 | -0.054 [-0.095, -0.018] | -0.007 [-0.022, 0.006] | 0.099 [0.034, 0.168] | -0.002 [-0.007, 0.001] | -0.004 [-0.008, -0.001] |
| clusters = run dates | all | 21,184 | 20,824 | 961 | 64 | -0.020 [-0.026, -0.014] | -0.008 [-0.013, -0.002] | 0.039 [0.027, 0.051] | -0.002 [-0.005, -0.000] | -0.003 [-0.005, -0.001] |
| clusters = run dates | category: conflict | 1,956 | 3,541 | 152 | 39 | -0.018 [-0.030, -0.007] | 0.009 [0.003, 0.014] | 0.044 [0.011, 0.073] | -0.001 [-0.006, 0.003] | -0.001 [-0.004, 0.001] |
| parents table (prob >= 0.01) | all | 21,184 | 20,824 | 961 | 64 | -0.021 [-0.027, -0.014] | -0.008 [-0.013, -0.003] | 0.039 [0.028, 0.050] | -0.002 [-0.005, -0.000] | -0.003 [-0.005, -0.001] |
| parents table (prob >= 0.01) | category: conflict | 1,956 | 3,541 | 152 | 39 | -0.020 [-0.031, -0.009] | 0.007 [0.003, 0.013] | 0.042 [0.009, 0.070] | -0.001 [-0.006, 0.003] | -0.001 [-0.004, 0.001] |

Strata also by hour of the run compare a flagged message only with the agent's control messages of the same hour since the realization's start (time of day). Controls outside every V1 finding window drop the agent's messages near any V1 finding, whoever it involves; controls outside every finding of the agent drop its messages near any finding at all (all categories, also single-agent ones). The parents-table row uses `hawkes_parents.parquet` as stored (parents with prob >= 0.01, not renormalised).

## 5. V2: rank of the flagged pairs in N_AA

Percentile rank of n_ij + n_ji of each pair of a finding's roster agents among all K(K-1)/2 pairs of its fitting window (mid-ranks; a uniformly drawn pair has mean 0.5 and a top-quartile share near 0.25). Active pairs: pairs of the agents with a message in that group on the finding's date. Interval: 2,000 draws that resample the findings' run dates and take n from one module A bootstrap replicate each; 'point n' resamples dates only. Unique pairs count each (window, pair) once and are resampled as units.

| Subset | Unit | Statistic | n | Dates | Value [95% CI] | CI, point n | All pairs | Active pairs | Minus active pairs |
|---|---|---|---|---|---|---|---|---|---|
| all | finding pair | mean_percentile | 4811 | 64 | 0.646 [0.609, 0.656] | [0.630, 0.661] | 0.500 | 0.516 | 0.130 [0.093, 0.139] |
| all | finding pair | top_quartile_share | 4811 | 64 | 0.435 [0.365, 0.457] | [0.412, 0.459] | 0.250 | 0.244 | 0.191 [0.127, 0.216] |
| all | unique pair | mean_percentile | 595 | 64 | 0.520 [0.499, 0.547] | [0.498, 0.541] | 0.500 | 0.515 | 0.005 [-0.020, 0.027] |
| category: conflict | finding pair | mean_percentile | 299 | 37 | 0.620 [0.547, 0.681] | [0.575, 0.672] | 0.500 | 0.512 | 0.109 [0.035, 0.165] |
| category: conflict | finding pair | top_quartile_share | 299 | 37 | 0.361 [0.266, 0.495] | [0.298, 0.435] | 0.250 | 0.239 | 0.122 [0.033, 0.260] |
| category: conflict | unique pair | mean_percentile | 121 | 37 | 0.559 [0.499, 0.611] | [0.511, 0.604] | 0.500 | 0.511 | 0.047 [-0.014, 0.098] |
| category: off-goal | finding pair | mean_percentile | 782 | 55 | 0.639 [0.583, 0.669] | [0.600, 0.688] | 0.500 | 0.515 | 0.124 [0.065, 0.151] |
| category: off-goal | finding pair | top_quartile_share | 782 | 55 | 0.423 [0.322, 0.471] | [0.363, 0.495] | 0.250 | 0.240 | 0.183 [0.075, 0.230] |
| category: off-goal | unique pair | mean_percentile | 329 | 55 | 0.555 [0.518, 0.581] | [0.525, 0.584] | 0.500 | 0.516 | 0.039 [-0.002, 0.061] |
| category: emotional-or-erratic | finding pair | mean_percentile | 183 | 33 | 0.659 [0.593, 0.706] | [0.620, 0.707] | 0.500 | 0.521 | 0.138 [0.073, 0.186] |
| category: emotional-or-erratic | finding pair | top_quartile_share | 183 | 33 | 0.443 [0.324, 0.549] | [0.369, 0.529] | 0.250 | 0.247 | 0.195 [0.082, 0.311] |
| category: emotional-or-erratic | unique pair | mean_percentile | 97 | 33 | 0.620 [0.540, 0.659] | [0.572, 0.670] | 0.500 | 0.521 | 0.099 [0.022, 0.141] |
| category: likely-scaffolding-issue | finding pair | mean_percentile | 175 | 38 | 0.619 [0.548, 0.687] | [0.577, 0.693] | 0.500 | 0.521 | 0.098 [0.027, 0.164] |
| category: likely-scaffolding-issue | finding pair | top_quartile_share | 175 | 38 | 0.371 [0.265, 0.508] | [0.302, 0.500] | 0.250 | 0.243 | 0.128 [0.028, 0.259] |
| category: likely-scaffolding-issue | unique pair | mean_percentile | 99 | 38 | 0.555 [0.491, 0.608] | [0.505, 0.605] | 0.500 | 0.518 | 0.036 [-0.029, 0.085] |
| category: surreptitious-or-deceptive | finding pair | mean_percentile | 313 | 41 | 0.666 [0.608, 0.706] | [0.629, 0.707] | 0.500 | 0.517 | 0.149 [0.091, 0.190] |
| category: surreptitious-or-deceptive | finding pair | top_quartile_share | 313 | 41 | 0.492 [0.367, 0.548] | [0.422, 0.572] | 0.250 | 0.247 | 0.245 [0.120, 0.303] |
| category: surreptitious-or-deceptive | unique pair | mean_percentile | 165 | 41 | 0.581 [0.530, 0.628] | [0.539, 0.620] | 0.500 | 0.518 | 0.063 [0.013, 0.104] |
| category: outside-agent-contact | finding pair | mean_percentile | 229 | 27 | 0.672 [0.588, 0.766] | [0.592, 0.792] | 0.500 | 0.521 | 0.152 [0.066, 0.250] |
| category: outside-agent-contact | finding pair | top_quartile_share | 229 | 27 | 0.541 [0.356, 0.654] | [0.423, 0.727] | 0.250 | 0.255 | 0.286 [0.101, 0.414] |
| category: outside-agent-contact | unique pair | mean_percentile | 149 | 27 | 0.585 [0.529, 0.631] | [0.539, 0.630] | 0.500 | 0.522 | 0.063 [0.010, 0.109] |
| category: human-contact | finding pair | mean_percentile | 277 | 43 | 0.674 [0.597, 0.706] | [0.633, 0.721] | 0.500 | 0.516 | 0.158 [0.080, 0.190] |
| category: human-contact | finding pair | top_quartile_share | 277 | 43 | 0.458 [0.332, 0.531] | [0.373, 0.559] | 0.250 | 0.240 | 0.218 [0.095, 0.293] |
| category: human-contact | unique pair | mean_percentile | 93 | 43 | 0.605 [0.526, 0.643] | [0.555, 0.655] | 0.500 | 0.515 | 0.090 [0.010, 0.128] |
| category: unsolicited-outreach | finding pair | mean_percentile | 136 | 21 | 0.675 [0.566, 0.795] | [0.584, 0.818] | 0.500 | 0.522 | 0.153 [0.045, 0.276] |
| category: unsolicited-outreach | finding pair | top_quartile_share | 136 | 21 | 0.537 [0.318, 0.708] | [0.360, 0.805] | 0.250 | 0.252 | 0.285 [0.070, 0.470] |
| category: unsolicited-outreach | unique pair | mean_percentile | 86 | 21 | 0.575 [0.499, 0.635] | [0.517, 0.635] | 0.500 | 0.522 | 0.053 [-0.020, 0.113] |
| category: good-tweet | finding pair | mean_percentile | 179 | 42 | 0.652 [0.589, 0.701] | [0.605, 0.703] | 0.500 | 0.517 | 0.135 [0.074, 0.182] |
| category: good-tweet | finding pair | top_quartile_share | 179 | 42 | 0.447 [0.335, 0.540] | [0.364, 0.541] | 0.250 | 0.246 | 0.201 [0.095, 0.298] |
| category: good-tweet | unique pair | mean_percentile | 99 | 42 | 0.584 [0.513, 0.638] | [0.531, 0.636] | 0.500 | 0.516 | 0.068 [-0.003, 0.121] |
| category: interesting-content | finding pair | mean_percentile | 1465 | 61 | 0.644 [0.600, 0.667] | [0.620, 0.671] | 0.500 | 0.514 | 0.130 [0.085, 0.152] |
| category: interesting-content | finding pair | top_quartile_share | 1465 | 61 | 0.427 [0.352, 0.479] | [0.386, 0.471] | 0.250 | 0.241 | 0.185 [0.114, 0.239] |
| category: interesting-content | unique pair | mean_percentile | 317 | 61 | 0.557 [0.519, 0.582] | [0.529, 0.583] | 0.500 | 0.511 | 0.046 [0.003, 0.068] |
| category: other | finding pair | mean_percentile | 773 | 58 | 0.637 [0.582, 0.662] | [0.610, 0.669] | 0.500 | 0.519 | 0.118 [0.066, 0.142] |
| category: other | finding pair | top_quartile_share | 773 | 58 | 0.423 [0.327, 0.467] | [0.376, 0.480] | 0.250 | 0.249 | 0.174 [0.089, 0.226] |
| category: other | unique pair | mean_percentile | 261 | 58 | 0.547 [0.504, 0.577] | [0.515, 0.577] | 0.500 | 0.519 | 0.027 [-0.014, 0.058] |

## 6. V2: conflicts within versus between spectral clusters

Module A's eigengap rule (SPEC 5.5, `hawkes_blocks.csv`) gives more than one cluster in 0 of the 8 windows used here, so with its clusters the within share of conflict pairs and the share expected from cluster sizes are both 1 wherever a single cluster was found: the comparison is not informative there. Partitions forced to k clusters with module A's procedure (a sensitivity, not module A's choice) give: forced k = 2 8 windows with more than one cluster, forced k = 3 8 windows with more than one cluster, forced k = 4 8 windows with more than one cluster.
Forced clusters are built from N_AA itself, so a pair inside one cluster tends to have a high n_ij + n_ji; these rows restate the rank result in cluster terms.

| Subset | Clusters | Pairs | Dates | Windows with >1 cluster | Within share [95% CI] | Expected from sizes | Minus expected | Active pairs | Minus active pairs |
|---|---|---|---|---|---|---|---|---|---|
| category: conflict | module A (eigengap) | 299 | 37 | 0 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 1.000 | 0.000 [0.000, 0.000] |
| category: conflict | forced k = 2 | 299 | 37 | 3 | 0.712 [0.626, 0.802] | 0.535 | 0.177 [0.092, 0.268] | 0.552 | 0.161 [0.080, 0.248] |
| category: conflict | forced k = 3 | 299 | 37 | 3 | 0.468 [0.397, 0.539] | 0.444 | 0.024 [-0.047, 0.094] | 0.497 | -0.029 [-0.107, 0.046] |
| category: conflict | forced k = 4 | 299 | 37 | 3 | 0.742 [0.652, 0.837] | 0.529 | 0.214 [0.123, 0.309] | 0.592 | 0.150 [0.066, 0.232] |
| all | module A (eigengap) | 4811 | 64 | 0 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 1.000 | 0.000 [0.000, 0.000] |
| all | forced k = 2 | 4811 | 64 | 7 | 0.593 [0.565, 0.623] | 0.534 | 0.058 [0.031, 0.087] | 0.546 | 0.047 [0.022, 0.073] |
| all | forced k = 3 | 4811 | 64 | 7 | 0.416 [0.398, 0.435] | 0.439 | -0.023 [-0.041, -0.005] | 0.492 | -0.076 [-0.093, -0.057] |
| all | forced k = 4 | 4811 | 64 | 7 | 0.647 [0.606, 0.686] | 0.508 | 0.139 [0.109, 0.168] | 0.576 | 0.071 [0.045, 0.100] |

## 7. Flagged pairs

The 15 pairs with the most conflict findings, then the most findings (`tables/monitor_v2_pairs.csv` lists all). n_a_from_b is the expected number of a's messages triggered by one message of b. The percentile range is over module A's bootstrap replicates.

| Window | Group | Agent a | Agent b | n_a_from_b | n_b_from_a | Percentile [range] | Conflict findings | All findings | Dates |
|---|---|---|---|---|---|---|---|---|---|
| g51 | general | DeepSeek-V3.2 | GPT-5.1 | 0.149 | 0.030 | 0.98 [0.95, 0.99] | 12 | 118 | 2026-07-06 to 2026-09-18 |
| g51 | general | GPT-5.1 | GPT-5.6 Luna | 0.023 | 0.000 | 0.74 [0.15, 0.94] | 11 | 50 | 2026-07-10 to 2026-09-18 |
| g51 | general | DeepSeek-V3.2 | GPT-5.6 Terra | 0.004 | 0.001 | 0.45 [0.15, 0.94] | 11 | 31 | 2026-07-09 to 2026-09-18 |
| g51 | general | GLM-5.2 | GPT-5.1 | 0.014 | 0.020 | 0.82 [0.55, 0.90] | 10 | 110 | 2026-07-06 to 2026-09-10 |
| g51 | general | DeepSeek-V3.2 | GLM-5.2 | 0.065 | 0.023 | 0.95 [0.86, 0.96] | 9 | 141 | 2026-07-06 to 2026-09-11 |
| g51 | general | GLM-5.2 | GPT-5.6 Luna | 0.021 | 0.001 | 0.72 [0.15, 0.96] | 9 | 41 | 2026-08-04 to 2026-08-20 |
| g51 | general | Claude Haiku 4.5 | GPT-5.6 Terra | 0.006 | 0.001 | 0.47 [0.15, 0.82] | 9 | 23 | 2026-07-24 to 2026-09-14 |
| g51 | general | GPT-5.1 | GPT-5.6 Terra | 0.006 | 0.001 | 0.46 [0.15, 0.84] | 8 | 40 | 2026-08-06 to 2026-09-18 |
| g51 | general | GPT-5.1 | GPT-5.2 | 0.024 | 0.028 | 0.90 [0.67, 0.93] | 7 | 68 | 2026-07-06 to 2026-09-18 |
| g51 | general | GPT-5.6 Luna | GPT-5.6 Terra | 0.032 | 0.016 | 0.88 [0.53, 0.95] | 7 | 41 | 2026-07-09 to 2026-09-18 |
| g51 | general | GLM-5.2 | GPT-5.6 Terra | 0.001 | 0.001 | 0.35 [0.15, 0.89] | 7 | 34 | 2026-07-09 to 2026-09-10 |
| g51 | general | DeepSeek-V3.2 | GPT-5.2 | 0.033 | 0.004 | 0.82 [0.34, 0.93] | 6 | 83 | 2026-07-06 to 2026-09-18 |
| g51 | general | Claude Haiku 4.5 | DeepSeek-V3.2 | 0.005 | 0.010 | 0.63 [0.34, 0.83] | 6 | 65 | 2026-07-09 to 2026-09-14 |
| g51 | general | DeepSeek-V3.2 | GPT-5.6 Luna | 0.134 | 0.001 | 0.97 [0.77, 0.98] | 6 | 28 | 2026-07-09 to 2026-09-15 |
| g51 | general | DeepSeek-V4-Pro | GPT-5.6 Terra | 0.000 | 0.005 | 0.44 [0.15, 0.78] | 6 | 19 | 2026-07-09 to 2026-09-03 |

## 8. V3 (module C): status

V3 lives in module C (`avsd.changepoint.monitor`, round 2 "monitor sets", docs/decisions.md); this command does not run or change it. Current module C outputs:

- Series: 55 monitor count series (category by all agents and by model family), 55 analysed (`changepoint_series.csv`, level `external`).
- Annotations: 871 PELT l2 change points have a monitor-covered run day within w (778 on module C's own series); `changepoints.csv` carries counts by category and severity, `changepoint_monitor_findings.parquet` the change point and finding id pairs.
- Alignment test: entry sets monitor emotional-or-erratic (high), monitor emotional-or-erratic (medium/high), monitor likely-scaffolding-issue (high), monitor likely-scaffolding-issue (medium/high) in `changepoint_alignment.csv`.
- Not done as planned: the plan listed a paraphrased heading per finding next to each change point. Module C keeps ids, categories, severities, confidences and offsets only (finding text can name people), so headings are not shown.
- Added beyond the plan: high-severity-only entry sets, because medium/high findings fall on almost every covered run day and cannot discriminate at w >= 1; monitor sets are annotations, never causes (`cause` stays CHANGELOG-only).

## 9. Reading

- V1, all: other-agent share near a finding minus the same agents' other messages of the realization -0.020 [-0.026, -0.013] (below 0; 21,184 flagged and 20,824 control messages in 64 realizations); within the same hour of the run -0.005 [-0.013, 0.005]. Co-involved agents -0.008 [-0.013, -0.002], self 0.039 [0.026, 0.052], baseline -0.014 [-0.022, -0.005], human -0.002 [-0.005, -0.000], system -0.003 [-0.005, -0.001]. In the 10 min before a message: other agents' messages 1.070 [0.412, 1.670], the agent's own 1.051 [0.692, 1.398].
- V1, category: conflict: other-agent share near a finding minus the same agents' other messages of the realization -0.018 [-0.030, -0.007] (below 0; 1,956 flagged and 3,541 control messages in 39 realizations); within the same hour of the run -0.002 [-0.024, 0.020]. Co-involved agents 0.009 [0.003, 0.014], self 0.044 [0.012, 0.074], baseline -0.024 [-0.049, 0.007], human -0.001 [-0.007, 0.003], system -0.001 [-0.004, 0.002]. In the 10 min before a message: other agents' messages 1.914 [0.363, 3.586], the agent's own 2.072 [1.181, 2.912].
- V2, category: conflict: mean percentile of the flagged pairs 0.620 [0.547, 0.681] (n = 299 pairs of 76 findings on 37 dates); minus the active-pair reference 0.109 [0.035, 0.165] (above 0).
- V2, all: mean percentile of the flagged pairs 0.646 [0.609, 0.656] (n = 4,811 pairs of 1,479 findings on 64 dates); minus the active-pair reference 0.130 [0.093, 0.139] (above 0).
- V2, conflicts within one of module A's clusters: 1.000 against 1.000 expected from the cluster sizes, with 0 of the 3 windows holding the conflict pairs split into more than one cluster.
- A share is a posterior attribution under module A's fit, so it moves with the candidate parents around a message (the 10-min counts) as well as with n. A difference between flagged and control messages says how module A reads the stretches the monitor flags, checked against an independent reading; it does not say what caused the episodes, and why the flagged stretches differ is a cause unidentified. An interval that covers 0 means the fit does not separate them.

## 10. Outputs

- `outputs/tables/monitor_v1.csv`: V1 by analysis, subset and measure (flagged and control means, difference and interval, counts).
- `outputs/tables/monitor_v2.csv`: V2 rank statistics and within-cluster shares with references and intervals.
- `outputs/tables/monitor_v2_pairs.csv`: one row per flagged (window, pair).
- `data/interim/monitor_validation/` (private): per-message parent-class probabilities and flags, per-finding coverage, pair instances.

