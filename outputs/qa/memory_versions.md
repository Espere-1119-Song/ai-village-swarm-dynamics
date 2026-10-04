# QA: memory versions (module B1, path S)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Rows 246,151 (manifest 246,151), agents 46, created_at 2025-04-02 18:00 to 2026-09-19 00:03 UTC. Runtime 16 s.

## Previous-row classes vs schema_notes 4.2

| pair_kind | rows | expected |
|---|---|---|
| append | 160,323 | 160,323 |
| rewrite | 85,657 | 85,657 |
| ident | 6 | 6 |
| trunc | 119 | 119 |

## Relations

| rel | rows | pre | post | standard | claude_code |
|---|---|---|---|---|---|
| first | 46 | 25 | 21 | 45 | 1 |
| append_session | 77,701 | 24,895 | 52,806 | 77,701 | 0 |
| append_note | 82,622 | 82,605 | 17 | 82,604 | 18 |
| rewrite | 85,603 | 35,848 | 49,755 | 83,839 | 1,764 |
| ident | 6 | 2 | 4 | 6 | 0 |
| revert | 113 | 96 | 17 | 113 | 0 |
| trunc_other | 6 | 4 | 2 | 6 | 0 |
| fork_append | 54 | 35 | 19 | 34 | 20 |

| check | rows | expected |
|---|---|---|
| append_session + append_note | 160,323 | 160,323 |
| revert | 113 | 113 |
| fork_append | 54 | 53 |
| rewrite + fork_append | 85,657 | 85,657 |

- Reverts by previous-row class: {'append': 0, 'rewrite': 0, 'ident': 0, 'trunc': 113}. Rows back: {2: 110, 3: 2, 5: 1}.
- Forks by rows back to their base: {2: 26, 3: 15, 4: 6, 5: 2, 6: 2, 8: 1, 16: 1, 17: 1}. With a session block: 16.
- append_session rows whose label carries a session UUID: 25,238 (later labels give a day/time range only).
- Rewrites whose input row is itself a generation: 2,534.
- Generations whose lineage parent is not the previous generation in time: 3.

## Per agent

| agent | scaffold | rows | generations | max version | append | rewrite | revert+trunc | fork | ident |
|---|---|---|---|---|---|---|---|---|---|
| Claude 3.5 Sonnet | standard | 832 | 63 | 62 | 769 | 62 | 0 | 0 | 0 |
| GPT-4o | standard | 604 | 44 | 43 | 560 | 43 | 0 | 0 | 0 |
| o1 | standard | 1,044 | 42 | 41 | 1,002 | 41 | 0 | 0 | 0 |
| Claude 3.7 Sonnet | standard | 17,269 | 4,070 | 4,069 | 13,189 | 4,069 | 10 | 0 | 0 |
| GPT-4.1 | standard | 2,376 | 352 | 351 | 2,024 | 351 | 0 | 0 | 0 |
| o3 | standard | 8,172 | 534 | 533 | 7,638 | 533 | 0 | 0 | 0 |
| Gemini 2.5 Pro | standard | 34,491 | 6,864 | 6,863 | 27,615 | 6,863 | 7 | 5 | 0 |
| o4-mini | standard | 69 | 4 | 3 | 65 | 3 | 0 | 0 | 0 |
| Claude Opus 4 | standard | 4,894 | 913 | 912 | 3,980 | 912 | 0 | 0 | 1 |
| Claude Opus 4.1 | standard | 7,579 | 1,315 | 1,314 | 6,264 | 1,314 | 0 | 0 | 0 |
| Grok 4 | standard | 1,876 | 486 | 485 | 1,329 | 485 | 60 | 1 | 0 |
| GPT-5 | standard | 9,621 | 4,187 | 4,186 | 5,434 | 4,186 | 0 | 0 | 0 |
| Claude Sonnet 4.5 | standard | 18,202 | 6,104 | 6,103 | 12,098 | 6,103 | 0 | 0 | 0 |
| Claude Haiku 4.5 | standard | 16,375 | 6,070 | 6,069 | 10,305 | 6,069 | 0 | 0 | 0 |
| GPT-5.1 | standard | 16,731 | 7,574 | 7,573 | 9,157 | 7,573 | 0 | 0 | 0 |
| Gemini 3 Pro | standard | 5,396 | 1,940 | 1,939 | 3,447 | 1,939 | 9 | 0 | 0 |
| Claude Opus 4.5 | standard | 14,424 | 4,629 | 4,628 | 9,795 | 4,628 | 0 | 0 | 0 |
| DeepSeek-V3.2 | standard | 11,274 | 4,761 | 4,760 | 6,486 | 4,760 | 16 | 11 | 0 |
| GPT-5.2 | standard | 9,496 | 4,086 | 4,085 | 5,410 | 4,085 | 0 | 0 | 0 |
| Opus 4.5 (Claude Code) | claude_code | 1,803 | 1,765 | 1,764 | 18 | 1,764 | 0 | 20 | 0 |
| Claude Opus 4.6 | standard | 5,613 | 2,036 | 2,035 | 3,577 | 2,035 | 0 | 0 | 0 |
| Claude Sonnet 4.6 | standard | 5,088 | 2,125 | 2,124 | 2,963 | 2,124 | 0 | 0 | 0 |
| Gemini 3.1 Pro | standard | 8,139 | 3,972 | 3,971 | 4,166 | 3,971 | 0 | 1 | 0 |
| GPT-5.4 | standard | 7,141 | 3,504 | 3,503 | 3,637 | 3,503 | 0 | 0 | 0 |
| Claude Opus 4.7 | standard | 2,104 | 1,037 | 1,036 | 1,067 | 1,036 | 0 | 0 | 0 |
| Kimi K2.6 | standard | 3,952 | 1,644 | 1,643 | 2,308 | 1,643 | 0 | 0 | 0 |
| GPT-5.5 | standard | 3,391 | 1,694 | 1,693 | 1,695 | 1,693 | 1 | 1 | 0 |
| Gemini 3.5 Flash | standard | 5,582 | 2,728 | 2,727 | 2,844 | 2,727 | 10 | 0 | 0 |
| [Temporary] Fine-tuned Leader | standard | 21 | 5 | 4 | 10 | 4 | 1 | 0 | 5 |
| Claude Opus 4.8 | standard | 3,291 | 1,657 | 1,656 | 1,634 | 1,656 | 0 | 0 | 0 |
| Fine-Tuned Leader | standard | 78 | 34 | 33 | 41 | 33 | 3 | 0 | 0 |
| Claude Fable 5 | standard | 1,971 | 967 | 966 | 1,004 | 966 | 0 | 0 | 0 |
| Claude Sonnet 5 | standard | 3,471 | 1,746 | 1,745 | 1,725 | 1,745 | 0 | 0 | 0 |
| DeepSeek-V4-Pro | standard | 2,618 | 1,313 | 1,311 | 1,303 | 1,312 | 1 | 1 | 0 |
| GLM-5.2 | standard | 3,151 | 1,546 | 1,545 | 1,605 | 1,545 | 0 | 0 | 0 |
| GPT-5.6 Luna | standard | 452 | 227 | 226 | 225 | 226 | 0 | 0 | 0 |
| GPT-5.6 Terra | standard | 565 | 284 | 283 | 281 | 283 | 0 | 0 | 0 |
| GPT-5.6 Sol | standard | 1,688 | 852 | 851 | 835 | 851 | 0 | 1 | 0 |
| Grok 4.5 | standard | 1,552 | 717 | 715 | 832 | 716 | 0 | 3 | 0 |
| Kimi K3 | standard | 611 | 222 | 221 | 388 | 221 | 1 | 0 | 0 |
| Claude Opus 5 | standard | 1,357 | 678 | 677 | 679 | 677 | 0 | 0 | 0 |
| GLM-5.3 Flash | standard | 381 | 191 | 190 | 190 | 190 | 0 | 0 | 0 |
| Claude Fable 5.1 | standard | 277 | 148 | 147 | 129 | 147 | 0 | 0 | 0 |
| Muse Spark 1.3 | standard | 103 | 56 | 55 | 47 | 55 | 0 | 0 | 0 |
| Gemini 3.8 Flash | standard | 752 | 405 | 404 | 347 | 404 | 0 | 0 | 0 |
| GPT-6 Astra | standard | 274 | 58 | 56 | 206 | 57 | 0 | 10 | 0 |
