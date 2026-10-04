# QA report: build-events

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Dataset revision `838b4150303ca8228e8edb432d8b8ccae353d258`. Pause gap G = 30 min. Runtime 55 s, peak RSS 8.7 GB.

Step timings (s): inputs 0, chat 4, events 1, sessions 0, turns 22, memory 17, concat 2, attributes 3, runs 1, agents_roster 1, write 3.

## 1. Row accounting (SPEC 4.3)

Each source table must equal emitted + linked (carried by another row) + not emitted, all measured on the output. Events linked: chat rows that carry their talk event and session rows that carry their START_USING_COMPUTER event (`src_event_id`). Not emitted: USER_NAME_CHANGE. `ids not matched` counts table ids that are not accounted for exactly once (missing, repeated or unexpected; for events also a chat or session row carrying the wrong event).

| table | source | table rows | manifest | emitted | linked | not emitted | difference | ids not matched |
|---|---|---|---|---|---|---|---|---|
| chat_messages | chat | 183,485 | 183,485 | 183,485 | 0 | 0 | 0 | 0 |
| events | event | 381,610 | 381,610 | 168,439 | 209,460 | 3,711 | 0 | 0 |
| computer_use_sessions | session | 78,362 | 78,362 | 78,362 | 0 | 0 | 0 | 0 |
| computer_use_turns | turn | 2,510,487 | 2,510,487 | 2,510,487 | 0 | 0 | 0 | 0 |
| agent_memories | memory | 246,151 | 246,151 | 246,151 | 0 | 0 | 0 | 0 |
| summaries | summary | 939 | 939 | 939 | 0 | 0 | 0 | 0 |

- Reconciles exactly: **True**. Unified rows: 3,187,863.
- Chat rows carrying a talk event: 183,485; talk events with a chat row: 183,485; not matched one-to-one: 0.
- Session rows carrying a START event: 25,975; START events: 25,975; not matched one-to-one: 0.

Time range per source (`ts_utc`; summaries are timed by `updated_at`) and the raw table's `created_at` range:

| source | timed by | rows | first ts_utc | last ts_utc | first PT date | last PT date | raw table created_at |
|---|---|---|---|---|---|---|---|
| chat | created_at | 183,485 | 2025-04-02 17:47:10 | 2026-09-18 23:58:11 | 2025-04-02 | 2026-09-18 | chat_messages: 2025-04-02 17:47:10 to 2026-09-18 23:58:11 |
| event | created_at | 168,439 | 2025-04-02 18:03:34 | 2026-09-19 00:03:19 | 2025-04-02 | 2026-09-18 | events: 2025-04-02 17:47:10 to 2026-09-19 00:03:19 |
| session | created_at | 78,362 | 2025-04-02 18:00:17 | 2026-09-19 00:03:19 | 2025-04-02 | 2026-09-18 | computer_use_sessions: 2025-04-02 18:00:17 to 2026-09-19 00:03:19 |
| turn | created_at | 2,510,487 | 2025-04-02 18:00:35 | 2026-09-19 00:02:36 | 2025-04-02 | 2026-09-18 | computer_use_turns: 2025-04-02 18:00:35 to 2026-09-19 00:02:36 |
| memory | created_at | 246,151 | 2025-04-02 18:00:22 | 2026-09-19 00:03:19 | 2025-04-02 | 2026-09-18 | agent_memories: 2025-04-02 18:00:22 to 2026-09-19 00:03:19 |
| summary | updated_at | 939 | 2025-05-15 10:22:29 | 2026-09-20 01:02:21 | 2025-05-15 | 2026-09-19 | summaries: 2025-05-13 14:51:35 to 2026-09-18 16:02:17 |

Chat and talk events:

| check | value | expected |
|---|---|---|
| talk events (AGENT_TALK + USER_TALK) | 183,542 | 183,542 |
| linked to a chat row | 183,485 | 183,485 |
| distinct chat rows linked | 183,485 | 183,485 |
| chat rows without a talk event | 0 | 0 |
| talk events without a chat row (emitted, chat_row_missing) | 57 | 57 |
| linked pairs whose room differs | 0 | 0 |
| USER_NAME_CHANGE (not emitted) | 3,711 | 3,711 |

## 2. Actors

| source | agent | human | system | null |
|---|---|---|---|---|
| chat | 173,493 | 7,762 | 2,230 | 0 |
| event | 167,405 | 401 | 633 | 0 |
| session | 78,355 | 0 | 7 | 0 |
| turn | 2,510,487 | 0 | 0 | 0 |
| memory | 246,151 | 0 | 0 | 0 |
| summary | 0 | 0 | 939 | 0 |

Chat rows by actor_type vs schema_notes 4.6: agent 173,493 (expected 173,493, ok), human 7,762 (expected 7,762, ok), system 2,230 (expected 2,230, ok).

By rooms era (R0 < 2026-02-25, R1 to 03-15, R2 to 07-05, R3 from 07-06), rows as agent / human / system:

| source | R0 | R1 | R2 | R3 |
|---|---|---|---|---|
| chat | 86,839 / 7,114 / 477 | 8,618 / 18 / 109 | 30,428 / 517 / 871 | 47,608 / 113 / 773 |
| event | 57,213 / 58 / 151 | 4,627 / 0 / 10 | 34,080 / 27 / 140 | 71,485 / 316 / 332 |
| session | 20,670 / 0 / 0 | 3,536 / 0 / 0 | 21,278 / 0 / 7 | 32,871 / 0 / 0 |
| turn | 611,402 / 0 / 0 | 85,060 / 0 / 0 | 734,512 / 0 / 0 | 1,079,513 / 0 / 0 |
| memory | 125,809 / 0 / 0 | 12,527 / 0 / 0 | 43,332 / 0 / 0 | 64,483 / 0 / 0 |
| summary | 0 / 0 / 687 | 0 / 0 / 17 | 0 / 0 / 80 | 0 / 0 / 155 |

Event rows that are not agent rows, by raw action type: ENTER_ROOM 12, OUTREACH_APPROVAL_RESPONSE 343, RESTARTING_AFTER_GOOGLE_SIGN_IN 611, STOP_HUMAN_USE_SESSION 11, USER_TALK 57.

Non-agent actor ids: `human` 8,163, `system:nudger` 2,230, `system:summarizer` 939, `system:scaffold` 640.

Auto-nudges with a leading `@<agent name>` of a known agent (`target_agent_id`): 1,567 of 1,568 (schema_notes 4.6: 1,567 of 1,568 name a known agent). Non-agent rows with `target_agent_id` by actor: `human` 344 of 8,163, `system:nudger` 1,567 of 2,230, `system:scaffold` 640 of 640, `system:summarizer` 48 of 939.

## 3. kind and subkind

| kind | subkind | rows |
|---|---|---|
| agent_msg | None | 173,493 |
| human_msg | None | 7,745 |
| human_msg | user_talk | 57 |
| human_msg | run_marker | 17 |
| memory_write | rewrite | 85,603 |
| memory_write | append_note | 82,622 |
| memory_write | append_session | 77,701 |
| memory_write | revert | 113 |
| memory_write | fork_append | 54 |
| memory_write | first | 46 |
| memory_write | ident | 6 |
| memory_write | trunc_other | 6 |
| other | daily | 805 |
| other | request_google_sign_in | 619 |
| other | restarting_after_google_sign_in | 611 |
| other | enter_room | 454 |
| other | outreach_approval_request | 352 |
| other | outreach_approval_response | 343 |
| other | request_human_helper | 265 |
| other | cancel_request_for_human_helper | 141 |
| other | goal | 83 |
| other | agent | 43 |
| other | stop_human_use_session | 37 |
| other | goal-checkpoint | 3 |
| other | agent_daily | 2 |
| other | watch_narrative_v2 | 2 |
| other | watch_narrative | 1 |
| pause | pause | 40,472 |
| search_history | search_history | 10,802 |
| session_end | consolidate | 52,325 |
| session_end | stop | 25,939 |
| session_start | consolidate_only | 52,317 |
| session_start | start_only | 25,969 |
| session_start | neither | 70 |
| session_start | both | 6 |
| system_msg | nudge | 1,568 |
| system_msg | run_marker | 662 |
| turn | bash | 979,076 |
| turn | left_click | 368,447 |
| turn | key | 236,938 |
| turn | scroll | 171,247 |
| turn | type | 161,483 |
| turn | get_pixel_coords_of_element | 150,503 |
| turn | send_message_back_to_chat | 100,354 |
| turn | None | 83,449 |
| turn | mouse_move | 74,236 |
| turn | screenshot | 57,885 |
| turn | wait | 48,211 |
| turn | pause | 39,838 |
| turn | search_history | 10,148 |
| turn | triple_click | 7,029 |
| turn | double_click | 6,977 |
| turn | left_click_drag | 4,193 |
| turn | right_click | 3,278 |
| turn | middle_click | 2,054 |
| turn | view_clipboard | 1,727 |
| turn | move_to_room | 1,006 |
| turn | hold_key | 937 |
| turn | request_Google_sign_in | 619 |
| turn | request_approval_for_unsolicited_outreach | 353 |
| turn | left_mouse_down | 142 |
| turn | request_human_helper | 136 |
| turn | cursor_position | 121 |
| turn | left_mouse_up | 63 |
| turn | cancel_request_for_human_helper | 37 |
| wait | wait | 36,022 |

turn_kind: tool_action 2,427,038, talk_only 78,914, bash_restart 2,433, malformed_call 2,102.

Run markers flagged (`is_run_marker`): 679, of which bot rows 662.

## 4. Null checks (SPEC 4.3)

| check | rows | expected |
|---|---|---|
| ts_utc null | 0 | 0 |
| actor_type null | 0 | 0 |
| actor_id null | 0 | 0 |
| agent rows without model_family | 0 | 0 |
| agent rows whose actor is not in agents | 0 | 0 |
| agent rows without agent_room_id | 0 | 0 |
| village_day null | 0 | 0 |
| rows without goal_id (before the first goal) | 0 | n/a |
| duplicate event_uid | 0 | 0 |
| text_ref null | 0 | 0 |
| inline text longer than 2,000 chars | 0 | 0 |

Rows whose inline text is cut to 2,000 chars (full text by `text_ref`; memory snapshots, summaries and outreach payloads have no inline text): chat 1,966, event 23,897, session 8,803, turn 105,258.

Agent rows by model_family: Anthropic 1,185,771, OpenAI 847,265, Google 699,668, Other 443,187. Agents with rows: 46 of 46.

session_id coverage of agent rows:

| source | kind | rows | with session_id |
|---|---|---|---|
| chat | agent_msg | 173,493 | 118,892 |
| event | other | 1,845 | 1,632 |
| event | pause | 40,472 | 39,950 |
| event | search_history | 10,802 | 10,024 |
| event | session_end | 78,264 | 78,264 |
| event | wait | 36,022 | 135 |
| memory | memory_write | 246,151 | 246,113 |
| session | session_start | 78,355 | 78,355 |
| turn | turn | 2,510,487 | 2,510,487 |

## 5. village_day vs daily summaries

- Daily summary rows 805, with a numeric day target 789 (the other 16 have no target).
- Target equals `(summary_date - 2025-04-02) + 1`: 789 of 789 (expected 789/789).
- Target equals the village_day of this table's rows on the summary's PT date: 782 of 782 (summary dates with rows). Each PT date has one village_day; range 1 to 536.

## 6. Room reconstruction (agent messages)

The agent's room is the room of its latest earlier room-carrying event (event_index order). Strict uses only earlier events (`general` if none); `agent_room_id` adds `general` before 2026-03-05 and a look-ahead to the next event for an agent's first appearance (an ENTER_ROOM row itself is in the room it left).

| rule | correct | of | expected |
|---|---|---|---|
| strict | 173,486 | 173,493 | 173,486 |
| agent_room_id (look-ahead) | 173,492 | 173,493 | 173,492 |

`agent_room_intervals.parquet`: 512 room spells for 46 agents. Opened by a room-carrying event: 466 (expected 466: each agent's first room plus 420 changes; ok). Opened by the rule before an agent's first room-carrying event (`general` before 2026-03-05 PT, then that event's room, or the room an ENTER_ROOM left): 46. Spells ending before they start (event_index and time disagree): 0.
- Agent rows whose `agent_room_id` equals the spell room at their time (latest spell start strictly before the row): 3,175,891 of 3,175,891. The rules are the same; the lookup goes by time, `agent_room_id` by event_index where a row has one, so a difference means the two orders disagree near a room event.
- Retired agents stay in their last room; exposure lookups also need `roster_daily.active`.

## 7. Duplicate turns and links

Turns that mirror a chat row or an event keep `dup_of_uid`; greedy one-to-one matching by time difference (send_message: same agent and exact content, chat row 0-300 s later; search_history: same agent, exact query, |dt| <= 120 s, errored turns dropped; others: same agent, first event of the type 0-120 s later).

| turn action | turns | linked | expected | check |
|---|---|---|---|---|
| send_message_back_to_chat | 100,353 | 100,353 | 100,353 | ok |
| search_history | 10,148 | 9,945 | 9,945 | ok |
| pause | 39,838 | 39,276 | 39,277 | differs by -1 |
| move_to_room | 1,006 | 392 | 392 | ok |
| request_Google_sign_in | 619 | 619 | 619 | ok |
| request_approval_for_unsolicited_outreach | 353 | 352 | 352 | ok |
| request_human_helper | 136 | 130 | 130 | ok |
| cancel_request_for_human_helper | 37 | 33 | 33 | ok |

- The documented pause count (39,277) is a many-to-one forward join (39,180 distinct PAUSE events); the one-to-one match pairs each event with at most one turn.
- Turns with dup_of_uid: 151,100. Rows with linked_uid by source: chat 100,353, event 50,747, memory 75,142.

- Memory rows with a STOP/CONSOLIDATE event 0-1 s later: 75,142 of 246,151 (75,142 distinct events). Memory session_id from the label UUID 25,162 (label UUIDs 25,238, of which a session of the same agent 25,162), from the linked end event 50,634, from the latest session 170,317.

- Memory relations: append_note 82,622, append_session 77,701, first 46, fork_append 54, ident 6, revert 113, rewrite 85,603, trunc_other 6.

## 8. Sessions

| category | sessions | expected | check |
|---|---|---|---|
| start_only | 25,969 | 25,969 | ok |
| consolidate_only | 52,317 | 52,319 | differs by -2 |
| both | 6 | 6 | ok |
| neither | 70 | 70 | ok |

- The documented categories sum to 78,364, not 78,362: 2 sessions have two CONSOLIDATE events and were counted twice there. Here each session counts once.

- STOP_USING_COMPUTER mapped to the agent's latest session: 25,939 of 25,939, distinct sessions 25,939 (expected 25,939 one-to-one).
- Sessions without a STOP or CONSOLIDATE: 100 (end = last turn); without turns: 248.

## 9. Run periods and active time (SPEC 4.2)

- Run days (PT dates with agent rows): 389 (expected 389). Dates with rows but no agent row (null run_day): 22, 48 rows: summary / system 48 rows on 22 dates. All dates with rows: 411. schema_notes 4.8 counts 10 weekend dates with only human rows; those were viewer renames (USER_NAME_CHANGE), which this table does not emit, so no date here has human rows without agent rows.
- Interval rows: agent rows except memory snapshots (scaffold writes).
- Realizations (blocks): 392. Pause segments (gaps > G within a date): 3, total 21.7 h. Main block (block 0) of a date: most overlap with the scheduled window, else the longest.
- Rows outside their block (`in_run` false): 1,854, by actor_type agent 450, human 240, system 1,164.
- Total active time 1,598.3 h; max t_active 1,598.3 h; t_active non-decreasing in row order: True.

Daily run length (hours, first to last agent row of the date) by schedule regime:

| regime | days | min | p10 | median | p90 | max | active h |
|---|---|---|---|---|---|---|---|
| 2h | 82 | 0.90 | 1.85 | 2.00 | 2.51 | 15.91 | 172.40 |
| 3h | 68 | 2.12 | 2.99 | 3.00 | 3.01 | 3.07 | 203.10 |
| 4h | 173 | 1.17 | 3.99 | 4.02 | 4.06 | 4.11 | 690.50 |
| 8h_event | 6 | 5.38 | 8.01 | 8.05 | 8.14 | 8.14 | 45.70 |
| 8h | 60 | 8.03 | 8.06 | 8.10 | 8.14 | 12.39 | 486.60 |

Dates with more than one block (block 0 = main):

| date | block | realization_id | start PT | end PT | minutes | agent rows |
|---|---|---|---|---|---|---|
| 2025-06-18 | 0 | 59 | 11:01 | 13:01 | 119.50 | 1,292 |
| 2025-06-18 | 1 | 60 | 18:01 | 21:01 | 179.60 | 1,672 |
| 2025-06-29 | 1 | 68 | 00:36 | 00:37 | 0.60 | 10 |
| 2025-06-29 | 0 | 69 | 13:31 | 16:31 | 179.60 | 2,238 |
| 2026-06-29 | 1 | 331 | 04:41 | 05:16 | 35.00 | 1,567 |
| 2026-06-29 | 0 | 332 | 09:01 | 17:04 | 483.70 | 22,615 |

Pause segments:

| date | from PT | to PT | minutes |
|---|---|---|---|
| 2025-06-18 | 13:01 | 18:01 | 300.50 |
| 2025-06-29 | 00:37 | 13:31 | 774.50 |
| 2026-06-29 | 05:16 | 09:01 | 224.50 |

Total active time by G: G=15 min 1,595.5 h, G=30 min 1,598.3 h, G=60 min 1,598.3 h (schema_notes 4.8: 1,596-1,600 h for G between 15 and 60 min).

## 10. refs

`refs`: references in text the actor produced; `refs_obs`: references seen only in tool output, errors and search answers (minus those already in `refs`).

| source | rows | rows with refs | refs | rows with refs_obs | refs_obs |
|---|---|---|---|---|---|
| chat | 183,485 | 24,486 | 31,478 | 0 | 0 |
| event | 168,439 | 24,571 | 99,194 | 3,165 | 5,844 |
| memory | 246,151 | 0 | 0 | 0 | 0 |
| session | 78,362 | 12,285 | 46,020 | 0 | 0 |
| summary | 939 | 0 | 0 | 0 | 0 |
| turn | 2,510,487 | 854,996 | 1,426,164 | 232,202 | 1,026,881 |

Top `refs` types (owners hashed): path:~ 485,694, path:/tmp 455,650, github 79,511, gitlab 42,769, gitlab-pid 41,143, url:ai-village-agents.github.io 35,456, url:api.manifold.markets 28,874, url:grok-ai-village-news-496089.gitlab.io 26,401, url:wellbeing-compass-409cf0.gitlab.io 24,782, path:. 22,223, url:echoes-of-the-real-20f058.gitlab.io 19,985, path:.. 15,856, url:localhost 14,998, url:sites.google.com 13,177, url:ai-village-news-cb5c4b.gitlab.io 10,429.

Top `refs_obs` types (owners hashed): path:~ 199,842, path:. 157,336, path:/tmp 95,826, github 87,723, gitlab 81,898, path:.. 58,957, url:wellbeing-compass-409cf0.gitlab.io 30,927, url:ai-village-agents.github.io 25,678, url:daily-signal-garden-gpt55-7f8271.gitlab.io 14,828, url:gpt-5-2-memory-improvement-45419d.gitlab.io 12,419, url:manifold.markets 7,553, url:quiet-rooms-gallery-83555a.gitlab.io 7,482, url:cheatsheetseries.owasp.org 7,379, url:arxiv.org 6,946, url:theaidigest.org 6,218.

## 11. Agents

| agent | provider | family | scaffold | model group | first active (UTC) | last active (UTC) | active run days |
|---|---|---|---|---|---|---|---|
| Claude 3.5 Sonnet | Anthropic | Anthropic | standard | Claude 3.5 Sonnet | 2025-04-02 18:00 | 2025-04-23 20:02 | 18 |
| GPT-4o | OpenAI | OpenAI | standard | GPT-4o | 2025-04-02 18:00 | 2025-04-14 19:07 | 11 |
| Claude 3.7 Sonnet | Anthropic | Anthropic | standard | Claude 3.7 Sonnet | 2025-04-02 18:00 | 2026-02-18 22:01 | 236 |
| o1 | OpenAI | OpenAI | standard | o1 | 2025-04-02 18:00 | 2025-04-15 19:31 | 12 |
| GPT-4.1 | OpenAI | OpenAI | standard | GPT-4.1 | 2025-04-15 18:01 | 2025-05-21 20:01 | 28 |
| o3 | OpenAI | OpenAI | standard | o3 | 2025-04-16 18:01 | 2025-11-28 22:00 | 166 |
| Gemini 2.5 Pro | Google | Google | standard | Gemini 2.5 Pro | 2025-04-24 18:01 | 2026-09-19 00:00 | 368 |
| o4-mini | OpenAI | OpenAI | standard | o4-mini | 2025-05-22 18:01 | 2025-05-22 20:01 | 1 |
| Claude Opus 4 | Anthropic | Anthropic | standard | Claude Opus 4 | 2025-05-23 18:04 | 2025-09-05 20:01 | 77 |
| Claude Opus 4.1 | Anthropic | Anthropic | standard | Claude Opus 4.1 | 2025-08-18 17:01 | 2025-11-28 22:00 | 75 |
| Grok 4 | xAI | Other | standard | Grok 4 | 2025-08-18 17:01 | 2025-10-28 21:00 | 52 |
| GPT-5 | OpenAI | OpenAI | standard | GPT-5 | 2025-08-18 17:02 | 2026-09-19 00:00 | 286 |
| Claude Sonnet 4.5 | Anthropic | Anthropic | standard | Claude Sonnet 4.5 | 2025-09-30 17:01 | 2026-09-18 23:59 | 255 |
| Claude Haiku 4.5 | Anthropic | Anthropic | standard | Claude Haiku 4.5 | 2025-10-22 17:01 | 2026-09-19 00:00 | 239 |
| GPT-5.1 | OpenAI | OpenAI | standard | GPT-5.1 | 2025-11-14 18:01 | 2026-09-19 00:02 | 222 |
| Gemini 3 Pro | Google | Google | standard | Gemini 3 Pro | 2025-11-19 18:01 | 2026-03-06 22:00 | 78 |
| Claude Opus 4.5 | Anthropic | Anthropic | standard | Claude Opus 4.5 | 2025-11-25 18:01 | 2026-09-19 00:00 | 215 |
| DeepSeek-V3.2 | DeepSeek | Other | standard | DeepSeek-V3.2 | 2025-12-04 18:08 | 2026-09-19 00:00 | 207 |
| GPT-5.2 | OpenAI | OpenAI | standard | GPT-5.2 | 2025-12-12 18:01 | 2026-09-19 00:00 | 202 |
| Opus 4.5 (Claude Code) | Anthropic | Anthropic | claude_code | Opus 4.5 (Claude Code) | 2026-01-26 19:11 | 2026-03-27 19:30 | 45 |
| Claude Opus 4.6 | Anthropic | Anthropic | standard | Claude Opus 4.6 | 2026-02-06 18:01 | 2026-09-18 23:55 | 162 |
| Claude Sonnet 4.6 | Anthropic | Anthropic | standard | Claude Sonnet 4.6 | 2026-02-18 18:02 | 2026-09-19 00:02 | 154 |
| Gemini 3.1 Pro | Google | Google | standard | Gemini 3.1 Pro | 2026-03-09 17:02 | 2026-09-19 00:00 | 141 |
| GPT-5.4 | OpenAI | OpenAI | standard | GPT-5.4 | 2026-03-16 17:01 | 2026-09-19 00:00 | 135 |
| Claude Opus 4.7 | Anthropic | Anthropic | standard | Claude Opus 4.7 | 2026-04-17 17:00 | 2026-09-18 23:42 | 112 |
| Kimi K2.6 | Moonshot | Other | standard | Kimi K2.6 | 2026-04-22 17:01 | 2026-09-19 00:00 | 109 |
| GPT-5.5 | OpenAI | OpenAI | standard | GPT-5.5 | 2026-04-27 17:01 | 2026-09-19 00:00 | 106 |
| Gemini 3.5 Flash | Google | Google | standard | Gemini 3.5 Flash | 2026-05-20 17:01 | 2026-09-19 00:00 | 89 |
| [Temporary] Fine-tuned Leader | Tinker | Other | standard | Fine-Tuned Leader | 2026-05-28 17:01 | 2026-05-29 20:40 | 2 |
| Claude Opus 4.8 | Anthropic | Anthropic | standard | Claude Opus 4.8 | 2026-05-28 18:19 | 2026-09-18 23:49 | 83 |
| Fine-Tuned Leader | Tinker | Other | standard | Fine-Tuned Leader | 2026-06-01 17:00 | 2026-06-05 21:03 | 5 |
| Claude Fable 5 | Anthropic | Anthropic | standard | Claude Fable 5 | 2026-06-09 17:45 | 2026-09-19 00:02 | 63 |
| Claude Sonnet 5 | Anthropic | Anthropic | standard | Claude Sonnet 5 | 2026-06-30 18:26 | 2026-09-19 00:00 | 59 |
| DeepSeek-V4-Pro | DeepSeek | Other | standard | DeepSeek-V4-Pro | 2026-07-02 16:00 | 2026-09-19 00:01 | 57 |
| GLM-5.2 | Zhipu | Other | standard | GLM-5.2 | 2026-07-03 16:00 | 2026-09-19 00:00 | 56 |
| GPT-5.6 Terra | OpenAI | OpenAI | standard | GPT-5.6 Terra | 2026-07-09 20:33 | 2026-09-18 23:57 | 52 |
| GPT-5.6 Sol | OpenAI | OpenAI | standard | GPT-5.6 Sol | 2026-07-09 20:33 | 2026-09-19 00:02 | 51 |
| GPT-5.6 Luna | OpenAI | OpenAI | standard | GPT-5.6 Luna | 2026-07-09 20:33 | 2026-09-19 00:00 | 52 |
| Grok 4.5 | xAI | Other | standard | Grok 4.5 | 2026-07-10 16:00 | 2026-09-18 23:59 | 51 |
| Kimi K3 | Moonshot | Other | standard | Kimi K3 | 2026-07-17 19:31 | 2026-09-19 00:00 | 45 |
| Claude Opus 5 | Anthropic | Anthropic | standard | Claude Opus 5 | 2026-07-24 18:51 | 2026-09-18 22:07 | 41 |
| GLM-5.3 Flash | Zhipu | Other | standard | GLM-5.3 Flash | 2026-08-28 20:28 | 2026-09-19 00:03 | 16 |
| Claude Fable 5.1 | Anthropic | Anthropic | standard | Claude Fable 5.1 | 2026-09-01 22:40 | 2026-09-18 23:46 | 14 |
| Muse Spark 1.3 | Meta | Other | standard | Muse Spark 1.3 | 2026-09-03 19:39 | 2026-09-18 23:59 | 12 |
| Gemini 3.8 Flash | Google | Google | standard | Gemini 3.8 Flash | 2026-09-03 19:47 | 2026-09-19 00:00 | 12 |
| GPT-6 Astra | OpenAI | OpenAI | standard | GPT-6 Astra | 2026-09-04 19:54 | 2026-09-18 23:56 | 11 |

Agents by family: Anthropic 16, Google 5, OpenAI 14, Other 11 (expected Anthropic 16, Google 5, OpenAI 14, Other 11).

## 12. Spot check: 20 random agent rows with live UI links

Seed 20261003. Agent rows only, no text.

| ts_pt | village_day | agent | kind | live UI |
|---|---|---|---|---|
| 2025-04-04 12:17:00 PDT | 3 | Claude 3.7 Sonnet | turn | https://theaidigest.org/village?day=3&time=1743794220089 |
| 2025-11-11 13:03:37 PST | 224 | Claude 3.7 Sonnet | turn | https://theaidigest.org/village?day=224&time=1762895017679 |
| 2025-11-20 13:30:22 PST | 233 | GPT-5 | turn | https://theaidigest.org/village?day=233&time=1763674222029 |
| 2026-01-23 10:51:35 PST | 297 | DeepSeek-V3.2 | turn | https://theaidigest.org/village?day=297&time=1769194295279 |
| 2026-02-03 10:55:23 PST | 308 | Opus 4.5 (Claude Code) | turn | https://theaidigest.org/village?day=308&time=1770144923265 |
| 2026-02-20 11:35:12 PST | 325 | DeepSeek-V3.2 | turn | https://theaidigest.org/village?day=325&time=1771616112946 |
| 2026-05-22 10:02:51 PDT | 416 | Gemini 2.5 Pro | turn | https://theaidigest.org/village?day=416&time=1779469371986 |
| 2026-06-05 10:34:09 PDT | 430 | Gemini 2.5 Pro | turn | https://theaidigest.org/village?day=430&time=1780680849306 |
| 2026-06-17 12:42:17 PDT | 442 | DeepSeek-V3.2 | turn | https://theaidigest.org/village?day=442&time=1781725337579 |
| 2026-06-23 12:57:58 PDT | 448 | GPT-5.4 | turn | https://theaidigest.org/village?day=448&time=1782244678957 |
| 2026-07-01 11:19:18 PDT | 456 | Claude Sonnet 5 | pause | https://theaidigest.org/village?day=456&time=1782929958022 |
| 2026-07-01 14:22:55 PDT | 456 | GPT-5.4 | turn | https://theaidigest.org/village?day=456&time=1782940975509 |
| 2026-07-13 13:28:39 PDT | 468 | Claude Sonnet 4.6 | agent_msg | https://theaidigest.org/village?day=468&time=1783974519142 |
| 2026-08-03 09:55:56 PDT | 489 | DeepSeek-V3.2 | turn | https://theaidigest.org/village?day=489&time=1785776156503 |
| 2026-08-24 13:05:26 PDT | 510 | Claude Sonnet 5 | turn | https://theaidigest.org/village?day=510&time=1787601926361 |
| 2026-08-25 13:00:18 PDT | 511 | DeepSeek-V3.2 | turn | https://theaidigest.org/village?day=511&time=1787688018051 |
| 2026-08-28 09:20:55 PDT | 514 | Gemini 3.5 Flash | turn | https://theaidigest.org/village?day=514&time=1787934055765 |
| 2026-08-28 16:16:13 PDT | 514 | Claude Opus 4.6 | turn | https://theaidigest.org/village?day=514&time=1787958973332 |
| 2026-09-03 10:19:53 PDT | 520 | Claude Sonnet 5 | turn | https://theaidigest.org/village?day=520&time=1788455993682 |
| 2026-09-10 15:34:34 PDT | 527 | GPT-5.2 | turn | https://theaidigest.org/village?day=527&time=1789079674285 |

## 13. CHANGELOG table (SPEC 4.1 step 7)

`changelog.parquet`: 186 rows, changelog 126, roster 60 (categories from the changelog.py rules and CATEGORY_OVERRIDES).
