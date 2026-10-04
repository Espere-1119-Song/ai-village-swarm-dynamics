# QA: parent labelling sheet for module B2 (SPEC 6.4.5)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Items: 50 (by MAP channel: chat_other 14, chat_self 6, chat_to_memory 10, env 6, history 2, memory 8, search 4).
Qwen3-14B pre-labels parsed: 50 of 50; agreement with the MAP parent: 21 of 50.
Priority 1 rows: 27.
Qwen3-14B: Qwen/Qwen3-14B (revision 40c069824f42), prompt b2-parent-v1, greedy decoding, thinking disabled, inference only. The sheet and its guide are private files under data/labels/ and are not copied elsewhere.

## Re-check with two stronger models

The owner asked on 2026-10-01 that two stronger local open-weight models re-check the pre-labels. Each model answered the same 50 cached requests (the prompts of Qwen3-14B) on its own; the prompts show neither the MAP parent, the posteriors nor the Qwen3-14B choice, but the candidates are listed in descending posterior order with ENV last, so candidate 1 is usually the MAP parent. Settings as in B1 (`avsd.lineage.prelabel.MODELS`); a final answer counts when it is one JSON object of the schema whose choice names a candidate, ENV or NONE.

| model | valid answers | attempts used | output tokens per request (mean, max) | runs |
|---|---|---|---|---|
| Qwen3.5-122B-A10B-FP8 (`a099dee70ccf`; enable_thinking=True; temperature 0.6) | 49 / 50 | attempt 1: 49 | 4,132, 32,768 | job 601036 on NVIDIA L40 |
| gpt-oss-120b (`b5c939de8f75`; reasoning_effort=high; temperature 1) | 50 / 50 | attempt 1: 50 | 1,491, 4,804 | job 601010 on NVIDIA A40 |

Agreement between labellers (items where both give a choice; 95% Wilson interval):

| pair | items | same choice | share | 95% CI |
|---|---|---|---|---|
| MAP parent / Qwen3-14B | 50 | 21 | 0.42 | 0.29 to 0.56 |
| MAP parent / Qwen3.5-122B | 49 | 27 | 0.55 | 0.41 to 0.68 |
| MAP parent / gpt-oss-120b | 50 | 30 | 0.60 | 0.46 to 0.72 |
| Qwen3-14B / Qwen3.5-122B | 49 | 26 | 0.53 | 0.39 to 0.66 |
| Qwen3-14B / gpt-oss-120b | 50 | 22 | 0.44 | 0.31 to 0.58 |
| Qwen3.5-122B / gpt-oss-120b | 49 | 37 | 0.76 | 0.62 to 0.85 |

Strong models agree on 37 of 50 items; their shared choice equals the MAP parent on 23. Priority 1 rows (they disagree with each other or with the MAP parent): 27.

Choices by kind (candidate 1 is the highest-posterior candidate that is not ENV):

| labeller | candidate 1 | other candidate | env | none | (none) |
|---|---|---|---|---|---|
| MAP parent | 44 | 0 | 6 | 0 | 0 |
| Qwen3-14B | 22 | 19 | 6 | 3 | 0 |
| Qwen3.5-122B | 29 | 12 | 6 | 2 | 1 |
| gpt-oss-120b | 31 | 11 | 7 | 1 | 0 |

By MAP channel (stratum): items, strong models agree, their choice equals the MAP parent:

| stratum | items | agree | = MAP |
|---|---|---|---|
| chat_other | 14 | 11 | 6 |
| chat_self | 6 | 5 | 4 |
| chat_to_memory | 10 | 6 | 4 |
| env | 6 | 3 | 0 |
| history | 2 | 2 | 1 |
| memory | 8 | 6 | 5 |
| search | 4 | 4 | 3 |
