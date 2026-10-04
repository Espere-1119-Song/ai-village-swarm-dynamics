# Module B1 validation set: LLM pre-labels (SPEC 6.3.4)

Generated 2026-10-03T21:30:20Z. Aggregates only: no memory text, values, names or credentials. The review sheet `data/labels/memory_pairs_review.csv` and the prompt/output cache `data/interim/llm_cache/memory_prelabel/` stay in `data/` (gitignored).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

## 1. Model and run

| item | value |
|---|---|
| model | Qwen/Qwen3-14B (revision `40c069824f42`, Apache-2.0, bf16, inference only) |
| serving | vLLM 0.19.0 (torch 2.10.0+cu128), offline batch, JSON-schema structured output, thinking disabled |
| decoding | temperature 0 (greedy), seed 20261003, max 256 new tokens |
| GPU | NVIDIA L40, 46068 MiB (one GPU), node dj-l40-0.grasp.maas, Slurm job 579742 |
| requests | 500 (500 generated over 1 run(s); the rest from the cache) |
| tokens | 576,603 prompt, 24,825 output |
| runtime | prepare 68.0 s (anchors 56.3 s); inference 127 s (model load 19.6 s, generation 107.7 s) |
| prompt version | b1-prelabel-v4 |
| input | `data/labels/memory_pairs.csv` sha256 `0a05580c2e7311b4` |

## 2. Unit recovery and excerpts

Each unit is re-matched by re-running the B1 extractor on the full PREV and NEXT texts. "Consistent" means the presence of the unit in PREV and NEXT agrees with its rule label (kept: both; modified, dropped: PREV only; new, restored: NEXT only).

| item | count |
|---|---|
| units | 500 |
| pairs | 100 |
| agents | 24 |
| memory texts read | 303 (9,609,891 chars) |
| pairs whose rows are not adjacent live rows | 0 |
| units consistent with the rule label | 500 / 500 |
| unit found in PREV / NEXT by the rules | 296 / 305 |
| literal value match used (PREV / NEXT) | 55 / 40 |
| other value in the unit's context shown (PREV / NEXT) | 230 / 226 |
| no window at all (PREV / NEXT) | 35 / 24 |
| value not recovered | 0 |
| hashed context not recovered | 0 |
| restored units with an earlier window | 103 / 103 (spells 103, scan 0) |
| values masked as credential-like | 5 |

Consistent units by rule label: kept 101/101, modified 92/92, dropped 103/103, new 101/101, restored 103/103

## 3. Model output

| item | count |
|---|---|
| valid label | 500 / 500 |
| errors | none |
| rationales cut to 25 words | 2 |
| finish reasons | stop 500 |
| credential-scanner hits left in the sheet (scripts/scan_credentials.py) | 0 |

## 4. Rule labels (v1) against Qwen3-14B labels

Agreement 310/500 (0.620); Cohen's kappa 0.523 (95% CI 0.481 to 0.565, bootstrap over pairs). Disagreements: 190 (the priority-1 rows of the first review design, which section 11 replaces).

Confusion matrix (rows: rule label, columns: LLM label):

| rule \ LLM | kept | modified | dropped | new | restored | total | agree |
|---|---|---|---|---|---|---|---|
| kept | 98 | 2 | 1 | 0 | 0 | 101 | 0.97 |
| modified | 14 | 14 | 64 | 0 | 0 | 92 | 0.15 |
| dropped | 24 | 4 | 75 | 0 | 0 | 103 | 0.73 |
| new | 21 | 0 | 0 | 79 | 1 | 101 | 0.78 |
| restored | 33 | 4 | 2 | 20 | 44 | 103 | 0.43 |

LLM confidence:

| confidence | units | agree with rule | disagree |
|---|---|---|---|
| high | 500 | 310 | 190 |

By what the excerpts show (a literal match is the value's text found where the B1 rules found no occurrence; these rows are the most likely rule errors):

| evidence | units | LLM disagrees | LLM labels when disagreeing |
|---|---|---|---|
| rule modified/dropped; value text still in NEXT (literal match, missed by the rules) | 40 | 39 | kept 37, modified 2 |
| rule modified/dropped; another value in the unit's context in NEXT | 83 | 64 | dropped 64 |
| rule modified/dropped; neither value text nor context value in NEXT | 72 | 3 | modified 2, kept 1 |
| rule new/restored; value text already in PREV (literal match, missed by the rules) | 55 | 55 | kept 51, dropped 2 |
| rule new/restored; value text not in PREV | 149 | 26 | new 20, kept 3 |
| rule kept | 101 | 3 | modified 2, dropped 1 |

By anchor type:

| type | units | agree | disagree |
|---|---|---|---|
| number | 220 | 141 | 79 |
| time | 92 | 69 | 23 |
| org | 72 | 36 | 36 |
| person | 35 | 17 | 18 |
| work_of_art | 15 | 6 | 9 |
| agent | 14 | 11 | 3 |
| gpe | 13 | 5 | 8 |
| url | 11 | 9 | 2 |
| date | 9 | 6 | 3 |
| product | 7 | 2 | 5 |
| percent | 7 | 4 | 3 |
| email | 2 | 2 | 0 |
| event | 2 | 1 | 1 |
| money | 1 | 1 | 0 |

## 5. Re-check with two stronger models

The owner asked on 2026-10-01 that two stronger local open-weight models re-check the Qwen3-14B pre-labels before the owner's review. Each model labels the same 500 cached requests (`requests.jsonl`, prompt version b1-prelabel-v4: the same prompts and excerpts as Qwen3-14B) on its own. The prompts contain no rule label and no Qwen3-14B label, and neither model sees the other's answer. The prompt design has one link to rule v1: the EARLIER excerpt is retrieved only for units that v1 labels restored, so a model can only support "restored" where v1 says so. Weights came from the official Hugging Face repositories without a token and were deleted after the run.

| item | Qwen3.5-122B-A10B-FP8 | gpt-oss-120b |
|---|---|---|
| model | `Qwen/Qwen3.5-122B-A10B-FP8` (revision `a099dee70ccf`, Apache-2.0, 127 GB) | `openai/gpt-oss-120b` (revision `b5c939de8f75`, Apache-2.0, 65 GB) |
| precision | FP8 block-quantized weights (128x128), FP8 activations (W8A8, sm_89) | MXFP4 MoE weights as released, bf16 activations |
| serving | vLLM 0.19.1 (torch 2.10.0+cu128), offline batch, tensor parallel 4, language model only, eager | vLLM 0.19.1 (torch 2.10.0+cu128), offline batch, tensor parallel 2, eager |
| reasoning | chat template enable_thinking=True; vLLM reasoning parser `qwen3`, JSON-schema structured output after the reasoning; the answer is validated against the schema | chat template reasoning_effort=high; vLLM reasoning parser `openai_gptoss`, JSON-schema structured output after the reasoning; the answer is validated against the schema |
| decoding | temperature 0.6, top_p 0.95, top_k 20, seed 20261003; at most 8,192 new tokens; answers that do not validate are retried once with 32,768 tokens and seed + 1 | temperature 1, seed 20261003; at most 8,192 new tokens; answers that do not validate are retried once with 32,768 tokens and seed + 1 |
| GPU | 4x NVIDIA L40, 46068 MiB; node dj-l40-0.grasp.maas, Slurm job(s) 599292 | 2x NVIDIA A40, 46068 MiB; node dj-a40-1.grasp.maas, Slurm job(s) 599293 |
| generated | attempt 1: 500, attempt 2: 14 | attempt 1: 500, attempt 2: 14 |
| valid answers | 500 / 500 (attempt 1: 486, attempt 2: 14); no valid answer: 0 | 500 / 500 (attempt 1: 500); no valid answer: 0 |
| finish reasons (answer used) | stop 500 | stop 500 |
| output tokens per request (with reasoning) | mean 2,921, median 2,658, max 8,722 | mean 1,420, median 1,084, max 7,920 |
| tokens | 600,856 prompt, 1,575,256 output | 622,837 prompt, 725,895 output |
| runtime | model load 86 s, generation 4461 s, total 4547 s | model load 50 s, generation 858 s, total 908 s |
| cache | `memory_prelabel/cache_qwen35_122b.jsonl`, runs in `runs_qwen35_122b.jsonl` | `memory_prelabel/cache_gptoss_120b.jsonl`, runs in `runs_gptoss_120b.jsonl` |

## 6. Agreement between labellers

Six labellers on the same 500 units: the three LLMs and rule sets v1, v2 and v3 (rule_v2: 500 of 500 units joined from memory_pairs_rule_v2.csv; rule_v3: 500 of 500 units joined from memory_pairs_rule_v3.csv). Upper triangle: share of units with the same label; lower triangle: Cohen's kappa. Units without a valid label on either side are skipped.

|  | Qwen3-14B | Qwen3.5-122B | gpt-oss-120b | rules v1 | rules v2 | rules v3 |
|---|---|---|---|---|---|---|
| Qwen3-14B | - | 0.81 | 0.84 | 0.62 | 0.68 | 0.81 |
| Qwen3.5-122B | 0.74 | - | 0.94 | 0.71 | 0.73 | 0.86 |
| gpt-oss-120b | 0.78 | 0.92 | - | 0.72 | 0.71 | 0.87 |
| rules v1 | 0.52 | 0.63 | 0.65 | - | 0.56 | 0.73 |
| rules v2 | 0.54 | 0.61 | 0.59 | 0.45 | - | 0.80 |
| rules v3 | 0.74 | 0.81 | 0.82 | 0.66 | 0.72 | - |

Cohen's kappa with 95% intervals (2,000 bootstrap replicates over the 100 pairs):

| pair | units | same label | agreement | kappa | 95% CI |
|---|---|---|---|---|---|
| Qwen3-14B / Qwen3.5-122B | 500 | 405 | 0.810 | 0.744 | 0.706 to 0.786 |
| Qwen3-14B / gpt-oss-120b | 500 | 420 | 0.840 | 0.784 | 0.748 to 0.822 |
| Qwen3-14B / rules v1 | 500 | 310 | 0.620 | 0.523 | 0.481 to 0.565 |
| Qwen3-14B / rules v2 | 500 | 341 | 0.682 | 0.544 | 0.491 to 0.599 |
| Qwen3-14B / rules v3 | 500 | 406 | 0.812 | 0.745 | 0.700 to 0.789 |
| Qwen3.5-122B / gpt-oss-120b | 500 | 471 | 0.942 | 0.922 | 0.894 to 0.949 |
| Qwen3.5-122B / rules v1 | 500 | 354 | 0.708 | 0.634 | 0.589 to 0.682 |
| Qwen3.5-122B / rules v2 | 500 | 365 | 0.730 | 0.613 | 0.557 to 0.668 |
| Qwen3.5-122B / rules v3 | 500 | 430 | 0.860 | 0.813 | 0.777 to 0.852 |
| gpt-oss-120b / rules v1 | 500 | 362 | 0.724 | 0.654 | 0.606 to 0.700 |
| gpt-oss-120b / rules v2 | 500 | 357 | 0.714 | 0.592 | 0.532 to 0.647 |
| gpt-oss-120b / rules v3 | 500 | 434 | 0.868 | 0.823 | 0.786 to 0.860 |
| rules v1 / rules v2 | 500 | 281 | 0.562 | 0.451 | 0.401 to 0.504 |
| rules v1 / rules v3 | 500 | 363 | 0.726 | 0.656 | 0.611 to 0.699 |
| rules v2 / rules v3 | 500 | 400 | 0.800 | 0.716 | 0.659 to 0.774 |

## 7. Confusion matrices

Qwen3.5-122B (rows) against gpt-oss-120b (columns), all 500 units:

| Qwen3.5 \ gpt-oss | kept | modified | dropped | new | restored | total | same |
|---|---|---|---|---|---|---|---|
| kept | 196 | 0 | 4 | 2 | 0 | 202 | 0.97 |
| modified | 0 | 42 | 14 | 0 | 0 | 56 | 0.75 |
| dropped | 0 | 6 | 89 | 0 | 0 | 95 | 0.94 |
| new | 0 | 0 | 1 | 79 | 0 | 80 | 0.99 |
| restored | 0 | 0 | 0 | 2 | 65 | 67 | 0.97 |

Qwen3-14B (rows) against the strong-model consensus (columns), on the 471 units where the two strong models agree:

| Qwen3-14B \ consensus | kept | modified | dropped | new | restored | total | same |
|---|---|---|---|---|---|---|---|
| kept | 186 | 0 | 1 | 3 | 0 | 190 | 0.98 |
| modified | 7 | 10 | 4 | 0 | 2 | 23 | 0.43 |
| dropped | 3 | 32 | 84 | 0 | 0 | 119 | 0.71 |
| new | 0 | 0 | 0 | 75 | 20 | 95 | 0.79 |
| restored | 0 | 0 | 0 | 1 | 43 | 44 | 0.98 |

rules v1 (rows) against the consensus (columns), same 471 units:

| rules v1 \ consensus | kept | modified | dropped | new | restored | total | same |
|---|---|---|---|---|---|---|---|
| kept | 101 | 0 | 0 | 0 | 0 | 101 | 1.00 |
| modified | 15 | 37 | 27 | 0 | 0 | 79 | 0.47 |
| dropped | 25 | 5 | 62 | 0 | 0 | 92 | 0.67 |
| new | 18 | 0 | 0 | 79 | 0 | 97 | 0.81 |
| restored | 37 | 0 | 0 | 0 | 65 | 102 | 0.64 |

rules v2 (rows) against the consensus (columns), same 471 units:

| rules v2 \ consensus | kept | modified | dropped | new | restored | total | same |
|---|---|---|---|---|---|---|---|
| kept | 186 | 10 | 21 | 27 | 31 | 275 | 0.68 |
| modified | 0 | 16 | 5 | 0 | 0 | 21 | 0.76 |
| dropped | 5 | 16 | 63 | 0 | 0 | 84 | 0.75 |
| new | 2 | 0 | 0 | 52 | 0 | 54 | 0.96 |
| restored | 3 | 0 | 0 | 0 | 34 | 37 | 0.92 |

rules v3 (rows) against the consensus (columns), same 471 units:

| rules v3 \ consensus | kept | modified | dropped | new | restored | total | same |
|---|---|---|---|---|---|---|---|
| kept | 180 | 1 | 1 | 3 | 2 | 187 | 0.96 |
| modified | 0 | 18 | 7 | 0 | 0 | 25 | 0.72 |
| dropped | 6 | 23 | 81 | 0 | 0 | 110 | 0.74 |
| new | 4 | 0 | 0 | 76 | 0 | 80 | 0.95 |
| restored | 6 | 0 | 0 | 0 | 63 | 69 | 0.91 |

## 8. By anchor type

Units per anchor type; how often the two strong models agree; on the consensus units, how often Qwen3-14B and each rule set give the consensus label; the most common Qwen3-14B → consensus changes.

| type | units | strong models agree | consensus units | = Qwen3-14B | = rules v1 | = rules v2 | = rules v3 | Qwen3-14B → consensus |
|---|---|---|---|---|---|---|---|---|
| number | 220 | 206 | 206 | 164 | 170 | 142 | 178 | dropped→modified 19, new→restored 16 |
| time | 92 | 84 | 84 | 68 | 70 | 42 | 71 | dropped→modified 8, modified→dropped 3 |
| org | 72 | 70 | 70 | 64 | 38 | 70 | 70 | new→restored 2, modified→kept 2 |
| person | 35 | 35 | 35 | 32 | 19 | 32 | 32 | dropped→modified 2, modified→kept 1 |
| work_of_art | 15 | 13 | 13 | 13 | 6 | 11 | 11 | - |
| agent | 14 | 13 | 13 | 11 | 10 | 12 | 12 | modified→kept 1, dropped→modified 1 |
| gpe | 13 | 12 | 12 | 11 | 4 | 12 | 12 | dropped→kept 1 |
| url | 11 | 11 | 11 | 10 | 10 | 9 | 9 | dropped→modified 1 |
| date | 9 | 8 | 8 | 8 | 5 | 5 | 5 | - |
| percent | 7 | 7 | 7 | 6 | 5 | 4 | 6 | modified→dropped 1 |
| product | 7 | 7 | 7 | 6 | 3 | 7 | 7 | new→restored 1 |
| email | 2 | 2 | 2 | 2 | 2 | 2 | 2 | - |
| event | 2 | 2 | 2 | 2 | 1 | 2 | 2 | - |
| money | 1 | 1 | 1 | 1 | 1 | 1 | 1 | - |

## 9. Overturns of Qwen3-14B by the strong-model consensus

The two strong models agree on 471 of 500 units (0.942). Their label differs from Qwen3-14B's on 73 of these (0.155; 95% CI 0.125 to 0.183, bootstrap over pairs).

By Qwen3-14B label:

| Qwen3-14B label | consensus units | overturned | rate | consensus label when overturned |
|---|---|---|---|---|
| kept | 190 | 4 | 0.02 | new 3, dropped 1 |
| modified | 23 | 13 | 0.57 | kept 7, dropped 4, restored 2 |
| dropped | 119 | 35 | 0.29 | modified 32, kept 3 |
| new | 95 | 20 | 0.21 | restored 20 |
| restored | 44 | 1 | 0.02 | new 1 |

By what the excerpt headers say (where the value occurs: rule match or literal match; whether NEXT holds another value in the unit's context; whether an EARLIER excerpt is shown):

| evidence | units | consensus units | overturned | rate | Qwen3-14B → consensus |
|---|---|---|---|---|---|
| value in PREV and NEXT | 196 | 196 | 10 | 0.05 | modified→kept 7, dropped→kept 3 |
| value in PREV only; another value in its context in NEXT | 83 | 67 | 34 | 0.51 | dropped→modified 31, modified→dropped 3 |
| value in PREV only; nothing else in its context in NEXT | 72 | 64 | 3 | 0.05 | dropped→modified 1, kept→dropped 1, modified→dropped 1 |
| value in NEXT only; earlier version shown | 66 | 65 | 22 | 0.34 | new→restored 20, modified→restored 2 |
| value in NEXT only; no earlier version shown | 83 | 79 | 4 | 0.05 | kept→new 3, restored→new 1 |
| value in neither | 0 | 0 | 0 | n/a | - |

By anchor type:

| type | consensus units | overturned | rate |
|---|---|---|---|
| number | 206 | 42 | 0.20 |
| time | 84 | 16 | 0.19 |
| org | 70 | 6 | 0.09 |
| person | 35 | 3 | 0.09 |
| work_of_art | 13 | 0 | 0.00 |
| agent | 13 | 2 | 0.15 |
| gpe | 12 | 1 | 0.08 |
| url | 11 | 1 | 0.09 |
| date | 8 | 0 | 0.00 |
| percent | 7 | 1 | 0.14 |
| product | 7 | 1 | 0.14 |
| email | 2 | 0 | 0.00 |
| event | 2 | 0 | 0.00 |
| money | 1 | 0 | 0.00 |

## 10. Third-judge check of disagreements

Frame: D1, the strong models disagree (27 units); D2, they agree and Qwen3-14B differs (69 units). Credential-like units are left out (D1 2, D2 4). A random sample of up to 25 units per stratum (permanent random numbers, seed 20261003) was judged from the same excerpts, blind to every model and rule label, with the definitions of the owner's guide: a value counts as present when an excerpt shows the same fact even where no match is marked (another format or wording); modified needs the same item to hold a new value in NEXT; restored needs the earlier excerpt to show the same fact, and an unrelated earlier use of the same value counts as new. The judgments are in `data/labels/memory_pairs_adjudication.csv` (private).

Judged: D1 25, D2 25; left undecided: none; judge confidence: high 24, low 5, medium 21.

Accuracy against the third judge (D1 and D2 are the units each stratum stands for; overall weights the strata by their frame sizes):

| labeller | D1 correct | D2 correct | all disagreements (95% CI) |
|---|---|---|---|
| Qwen3-14B | 9/25 (0.36) | 11/25 (0.44) | 0.42 [0.30, 0.53] |
| Qwen3.5-122B | 11/25 (0.44) | 10/25 (0.40) | 0.41 [0.30, 0.52] |
| gpt-oss-120b | 7/25 (0.28) | 10/25 (0.40) | 0.37 [0.25, 0.48] |
| rules v1 | 6/25 (0.24) | 7/25 (0.28) | 0.27 [0.16, 0.37] |
| rules v2 | 13/25 (0.52) | 8/25 (0.32) | 0.38 [0.27, 0.48] |
| rules v3 | 8/25 (0.32) | 6/25 (0.24) | 0.26 [0.16, 0.36] |
| Gemini 3.1 Pro (new prompt) | 22/25 (0.88) | 21/25 (0.84) | 0.85 [0.77, 0.94] |
| Claude (blind) | 19/25 (0.76) | 10/25 (0.40) | 0.50 [0.39, 0.61] |

## 11. Review design

Priority 1-必标 (inclusion probability 1): stratum A, the strong models disagree or one has no valid answer (29); stratum B, they agree and at least one rule version (v1, v2, v3) says otherwise (218). Every unit on which two rule versions disagree is in A or B, so the paired rule-set comparisons have no sampling error from the design. Stratum C (both models and all rule versions agree, 253 units): a random sample of 30 units (target 250 rows to label, at least 30 sampled), allocated to the labels in proportion (seed 20261003, permanent random numbers) is priority 2-抽样; the other 223 are 3-可选. Rows to label: 277. The sheet records each row's design_stratum and inclusion_prob; `compute_label_metrics` weights labelled rows by 1 / inclusion probability (adjusted within a stratum for rows left unlabelled).

| stratum | units | priority | sampled | inclusion probability |
|---|---|---|---|---|
| A | 29 | 1-必标 | 29 | 1 |
| B | 218 | 1-必标 | 218 | 1 |
| C:kept | 101 | 2-抽样 / 3-可选 | 12 | 0.119 |
| C:modified | 16 | 2-抽样 / 3-可选 | 2 | 0.125 |
| C:dropped | 50 | 2-抽样 / 3-可选 | 6 | 0.120 |
| C:new | 52 | 2-抽样 / 3-可选 | 6 | 0.115 |
| C:restored | 34 | 2-抽样 / 3-可选 | 4 | 0.118 |

## 12. Validation against the owner's labels

Owner's design of 2026-10-03: a stratified random audit of the blind sheet (seed 20261003), 15 of the 29 rows of stratum A, 30 of the 218 rows of B and 15 of the 30 sampled rows of C, all labelled by the owner without seeing any model or rule label; 11 more rows the owner labelled (the first rows of the sheet, not random) enter only the sensitivity check (a). Each audit row is weighted by 1 / (review inclusion probability x audit inclusion probability), so the estimates stand for all 500 units; intervals come from 2,000 bootstrap replicates that resample rows within the audit strata. 'Loss' is loss detection, the event of the B1 hazards: dropped or modified (positive) against kept (negative), on rows the owner labelled kept, dropped or modified; 'loss, all rows' also counts rows labelled new or restored as negatives. The owner flagged no unit as mis-extracted (bad_unit).

Scheme notes: Audit design: 60 of 60 audit rows labelled (A 15/15, B 30/30, C 15/15); weight 1 / (review inclusion probability x p_audit), stratified bootstrap within the audit strata. 71 of 71 labelled rows have a gemini answer. 71 of 71 labelled rows have a claude answer. rule (v1) joined from memory_pairs.csv: 500 of 500 sheet rows matched. rule_v2 joined from memory_pairs_rule_v2.csv: 500 of 500 sheet rows matched, 0 file rows unmatched. rule_v3 joined from memory_pairs_rule_v3.csv: 500 of 500 sheet rows matched, 0 file rows unmatched. llm joined from memory_pairs_llm_labels.csv: 500 of 500 sheet rows matched. gemini joined from memory_pairs_gemini.csv: 287 of 500 sheet rows have a Gemini answer; Gemini is scored on those rows only. claude joined from memory_pairs_claude.csv: 277 of 500 sheet rows have a Claude label; Claude is scored on those rows only.

Main estimates (audit rows, design-weighted, 95% CI):

| rater | loss precision | loss recall | loss F1 | loss F1, all rows | macro F1 | accuracy |
|---|---|---|---|---|---|---|
| rules v1 | 0.55 [0.33, 0.73] | 0.87 [0.61, 1.00] | 0.67 [0.45, 0.82] | 0.67 [0.45, 0.82] | 0.22 [0.11, 0.30] | 0.27 [0.14, 0.41] |
| rules v2 | 0.74 [0.49, 0.94] | 0.82 [0.55, 1.00] | 0.78 [0.55, 0.93] | 0.78 [0.55, 0.93] | 0.37 [0.24, 0.48] | 0.65 [0.51, 0.79] |
| rules v3 | 0.63 [0.40, 0.82] | 0.87 [0.61, 1.00] | 0.73 [0.52, 0.88] | 0.73 [0.52, 0.88] | 0.32 [0.19, 0.43] | 0.48 [0.33, 0.62] |
| Qwen3-14B | 0.60 [0.37, 0.79] | 0.82 [0.54, 1.00] | 0.69 [0.46, 0.85] | 0.69 [0.46, 0.85] | 0.25 [0.18, 0.30] | 0.47 [0.32, 0.62] |
| Qwen3.5-122B | 0.62 [0.36, 0.81] | 0.80 [0.52, 1.00] | 0.70 [0.46, 0.86] | 0.70 [0.46, 0.86] | 0.27 [0.15, 0.37] | 0.43 [0.28, 0.58] |
| gpt-oss-120b | 0.62 [0.38, 0.82] | 0.82 [0.54, 1.00] | 0.71 [0.48, 0.86] | 0.71 [0.48, 0.86] | 0.28 [0.16, 0.38] | 0.44 [0.29, 0.59] |
| Gemini 3.1 Pro | 0.54 [0.29, 0.77] | 0.75 [0.45, 0.98] | 0.63 [0.38, 0.81] | 0.63 [0.38, 0.81] | 0.26 [0.16, 0.36] | 0.50 [0.35, 0.64] |
| Claude (blind) | 0.75 [0.46, 0.94] | 0.86 [0.67, 0.99] | 0.80 [0.57, 0.93] | 0.80 [0.57, 0.93] | 0.51 [0.35, 0.63] | 0.80 [0.69, 0.91] |

F1 per class (audit rows, design-weighted, 95% CI; the owner gave no audit row new or restored, so those classes can only collect false positives):

| rater | kept | modified | dropped | new | restored |
|---|---|---|---|---|---|
| rules v1 | 0.31 [0.09, 0.50] | 0.27 [0.00, 0.54] | 0.50 [0.10, 0.76] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| rules v2 | 0.78 [0.65, 0.89] | 0.40 [0.00, 0.85] | 0.66 [0.34, 0.87] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| rules v3 | 0.58 [0.38, 0.73] | 0.40 [0.00, 0.85] | 0.62 [0.33, 0.82] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| Qwen3-14B | 0.55 [0.35, 0.71] | 0.00 [0.00, 0.00] | 0.70 [0.45, 0.86] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| Qwen3.5-122B | 0.57 [0.38, 0.73] | 0.27 [0.00, 0.63] | 0.51 [0.12, 0.76] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| gpt-oss-120b | 0.57 [0.37, 0.72] | 0.30 [0.00, 0.69] | 0.53 [0.20, 0.76] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| Gemini 3.1 Pro | 0.68 [0.52, 0.81] | 0.23 [0.00, 0.61] | 0.39 [0.09, 0.65] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| Claude (blind) | 0.91 [0.83, 0.97] | 0.49 [0.00, 0.81] | 0.66 [0.25, 0.88] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

Paired differences in loss-detection F1 between the rule sets (same bootstrap replicates):

| difference | estimate | 95% CI |
|---|---|---|
| v2 - v1 | +0.104 | +0.001 to +0.227 |
| v3 - v1 | +0.061 | +0.014 to +0.127 |
| v3 - v2 | -0.044 | -0.141 to +0.050 |

Sensitivity checks (loss-detection F1 and accuracy, 95% CI): (a) all rows the owner labelled, the 11 extra rows treated as random; (b) Claude's blind labels as the truth on all 277 rows of the blind sheet, weighted by the review design; for reference, the 60 audit rows unweighted.

| rater | (a) loss F1 | (a) accuracy | (b) loss F1 | (b) accuracy | audit unweighted loss F1 |
|---|---|---|---|---|---|
| rules v1 | 0.65 [0.43, 0.79] | 0.26 [0.13, 0.39] | 0.60 [0.49, 0.69] | 0.35 [0.30, 0.40] | 0.61 |
| rules v2 | 0.74 [0.50, 0.90] | 0.61 [0.47, 0.75] | 0.68 [0.54, 0.80] | 0.66 [0.60, 0.71] | 0.76 |
| rules v3 | 0.70 [0.48, 0.85] | 0.44 [0.29, 0.58] | 0.66 [0.55, 0.77] | 0.51 [0.45, 0.57] | 0.67 |
| Qwen3-14B | 0.68 [0.46, 0.83] | 0.45 [0.31, 0.59] | 0.65 [0.53, 0.75] | 0.50 [0.44, 0.56] | 0.62 |
| Qwen3.5-122B | 0.68 [0.46, 0.83] | 0.42 [0.28, 0.56] | 0.66 [0.54, 0.77] | 0.56 [0.51, 0.63] | 0.60 |
| gpt-oss-120b | 0.69 [0.47, 0.84] | 0.43 [0.29, 0.57] | 0.66 [0.54, 0.77] | 0.55 [0.49, 0.61] | 0.64 |
| Gemini 3.1 Pro | 0.65 [0.41, 0.82] | 0.51 [0.37, 0.66] | 0.74 [0.61, 0.84] | 0.68 [0.61, 0.75] | 0.59 |
| Claude (blind) | 0.83 [0.64, 0.94] | 0.82 [0.70, 0.92] | - | - | 0.69 |

## 13. Claude's blind labels against the owner's

On the 60 audit rows Claude gives the owner's label on 0.805 of all units (weighted to the 500 units; 95% CI 0.69 to 0.91), 0.753 of the blind sheet (weighted to its 277 rows; 0.62 to 0.87) and 0.733 of the audit rows unweighted. By audit stratum: A 8/15 (0.53), B 23/30 (0.77), C 13/15 (0.87). On kept / lost / entry the agreement is 0.869 (weighted to all units; 0.77 to 0.95).

Confusion matrix on the audit rows (rows: owner, columns: Claude; counts, unweighted):

| owner \ Claude | kept | modified | dropped | new | total |
|---|---|---|---|---|---|
| kept | 36 | 5 | 2 | 1 | 44 |
| modified | 1 | 2 | 0 | 0 | 3 |
| dropped | 3 | 4 | 6 | 0 | 13 |
| new | 0 | 0 | 0 | 0 | 0 |

Claude's label counts on all 277 rows: kept 216, modified 30, dropped 26, new 4, restored 1. Claude flagged 104 of 277 rows (0.375) as mis-extracted units (bad_unit); no human has validated that flag, and the owner flagged none in the 71 rows labelled.

## 14. Rule-set recommendation

Rule set v2 has the best loss-detection F1 against the owner's audit labels: v1 0.67 [0.45, 0.82]; v2 0.78 [0.55, 0.93]; v3 0.73 [0.52, 0.88]. Its 95% interval overlaps those of v1 and v3, so the intervals alone do not separate the rule sets. Loss precision: v1 0.55; v2 0.74; v3 0.63; loss recall: v1 0.87; v2 0.82; v3 0.87. So v2 gains by flagging fewer kept units as lost, at a small cost in caught losses. Paired differences in loss F1 (same bootstrap replicates): v2 - v1 +0.10 (95% CI +0.001 to +0.227, excludes 0); v3 - v1 +0.06 (95% CI +0.014 to +0.127, excludes 0); v3 - v2 -0.04 (95% CI -0.141 to +0.050, includes 0). Against Claude's blind labels on all 277 rows the best rule set is v2 (v1 0.60; v2 0.68; v3 0.66), which agrees.

## 15. Gemini as an extra rater (before the owner's labels)

Aggregates only. Gemini (owner's free-tier key, data terms accepted by the owner) labelled the rows the owner labels blind, from redacted prompts (b1-gemini-v1, b2-gemini-v1: no rule-based occurrence counts, no B1 marks, B2 candidates in the blind order without posteriors; human names, emails and phone numbers replaced by placeholders). Gemini output is never shown to the owner. Models: hard: gemini-3.1-pro-preview then gemini-2.5-pro, main: gemini-3.1-pro-preview then gemini-2.5-flash.

Rows by group and model:

| group | model | rows |
|---|---|---|
| A | gemini-3.1-pro-preview | 29 |
| B | gemini-3.1-pro-preview | 218 |
| B2-P1 | gemini-3.1-pro-preview | 27 |
| B2-P2 | gemini-3.1-pro-preview | 23 |
| C | gemini-3.1-pro-preview | 30 |
| adj | gemini-3.1-pro-preview | 10 |

Valid answers: 337 of 337 answered rows.

B1 agreement of Gemini with the other raters (rows where both have a label):

| rater | group | rows | same label | share | kappa |
|---|---|---|---|---|---|
| Qwen3.5-122B | A | 29 | 13 | 0.45 | 0.29 |
| Qwen3.5-122B | B | 218 | 152 | 0.70 | 0.56 |
| Qwen3.5-122B | C sample | 30 | 25 | 0.83 | 0.77 |
| Qwen3.5-122B | A+B+C | 277 | 190 | 0.69 | 0.55 |
| gpt-oss-120b | A | 29 | 8 | 0.28 | -0.02 |
| gpt-oss-120b | B | 218 | 152 | 0.70 | 0.56 |
| gpt-oss-120b | C sample | 30 | 25 | 0.83 | 0.77 |
| gpt-oss-120b | A+B+C | 277 | 185 | 0.67 | 0.53 |
| strong consensus | A | 0 | 0 | nan | nan |
| strong consensus | B | 218 | 152 | 0.70 | 0.56 |
| strong consensus | C sample | 30 | 25 | 0.83 | 0.77 |
| strong consensus | A+B+C | 248 | 177 | 0.71 | 0.58 |
| Qwen3-14B | A | 29 | 12 | 0.41 | 0.12 |
| Qwen3-14B | B | 218 | 148 | 0.68 | 0.53 |
| Qwen3-14B | C sample | 30 | 24 | 0.80 | 0.72 |
| Qwen3-14B | A+B+C | 277 | 184 | 0.66 | 0.52 |
| rules v1 | A | 29 | 4 | 0.14 | -0.07 |
| rules v1 | B | 218 | 46 | 0.21 | 0.13 |
| rules v1 | C sample | 30 | 25 | 0.83 | 0.77 |
| rules v1 | A+B+C | 277 | 75 | 0.27 | 0.17 |
| rules v2 | A | 29 | 14 | 0.48 | 0.21 |
| rules v2 | B | 218 | 129 | 0.59 | 0.18 |
| rules v2 | C sample | 30 | 25 | 0.83 | 0.77 |
| rules v2 | A+B+C | 277 | 168 | 0.61 | 0.29 |
| rules v3 | A | 29 | 9 | 0.31 | 0.04 |
| rules v3 | B | 218 | 119 | 0.55 | 0.35 |
| rules v3 | C sample | 30 | 25 | 0.83 | 0.77 |
| rules v3 | A+B+C | 277 | 153 | 0.55 | 0.37 |

Accuracy on the third-judge sample of B1 disagreements (50 of 50 units have a Gemini label; frame and weights as in section 10):

| rater | D1 correct | D2 correct | all disagreements (95% CI) |
|---|---|---|---|
| gemini | 22/25 | 21/25 | 0.85 [0.77, 0.94] |
| Qwen3-14B | 9/25 | 11/25 | 0.42 [0.30, 0.53] |
| Qwen3.5-122B | 11/25 | 10/25 | 0.41 [0.30, 0.52] |
| gpt-oss-120b | 7/25 | 10/25 | 0.37 [0.25, 0.48] |
| rules v1 | 6/25 | 7/25 | 0.27 [0.16, 0.37] |
| rules v2 | 13/25 | 8/25 | 0.38 [0.27, 0.48] |
| rules v3 | 8/25 | 6/25 | 0.26 [0.16, 0.36] |

B2 agreement of Gemini's parent with the other raters (items where both give a choice):

| rater | items | same parent |
|---|---|---|
| MAP parent | 50 | 26 |
| Qwen3-14B | 50 | 17 |
| Qwen3.5-122B | 49 | 31 |
| gpt-oss-120b | 50 | 32 |
| strong models' shared choice | 37 | 26 |

Gemini's B2 choices: candidate 34, env 8, none 8.
