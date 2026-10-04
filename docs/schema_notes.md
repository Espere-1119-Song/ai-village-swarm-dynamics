# Schema notes

Source: `README.md`, `SCHEMA.md`, `CHANGELOG.md`, `example.py`, `manifest.json` of
`aidigestorg/ai-village` at revision `838b4150303ca8228e8edb432d8b8ccae353d258`
(last modified 2026-09-20, export `exportedAt` 2026-09-20T13:05:12Z), and
full-table queries on the ingested parquet tables (2026-09-30).
Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

Where the documentation and the data disagree, this file follows the data and
says so.

## 1. Differences between SPEC and the current export

The SPEC numbers come from the dataset card, which describes an older export.
The current export is much larger. All counts below were confirmed by the
ingest (`outputs/qa/ingest.md`). The QA reports compare against the manifest.

| Table | SPEC / README | SCHEMA.md | manifest = ingested |
|---|---:|---:|---:|
| events | ~233k | ~235k | 381,610 |
| chat_messages | ~123k | ~124k | 183,485 |
| computer_use_sessions | ~37k | ~37k | 78,362 |
| computer_use_turns | ~1.14M | ~1.16M | 2,510,487 |
| agent_memories | ~165k | ~166k | 246,151 |
| summaries | ~800 | ~840 | 939 |
| agents | 31 | 31 | 46 |
| chat_rooms | 5 | 5 | 16 |
| village_goals | ~45 | ~46 | 51 |
| agent_goals | n/a | n/a | 33 |
| claude_code_messages | ~245k | ~245k | 244,820 |
| claude_code_sessions | ~300 | ~300 | 303 |

File sizes at this revision: 5.80 GB without screenshots (SPEC says 5.3 GB),
171.1 GB of screenshot tars. The data run from 2025-04-02 to 2026-09-18 (PT).

The dataset is refreshed about weekly. We pin the revision above.

## 2. Conventions

- All ids are UUID strings.
- `created_at`, `updated_at` and `*_time` are naive UTC strings with
  microsecond precision. The ingest parses them as UTC. Parse failures: 0.
- `created_at` is authoritative. `updated_at` moves by up to 14.8 h on 262
  premoderated human chat rows and is not used for timing.
- Scrub markers: `[REDACTED]`, `[BLOB_REMOVED]`, `[IMAGE_REMOVED]`. Scrubbing
  is partial (section 6).
- `agent_messages` (turns) and `output` (events) hold only the provider
  response (Anthropic content blocks, OpenAI Responses items, OpenAI chat
  completions, Gemini candidates). They contain no request parameters, input
  messages or system prompt, contrary to SCHEMA.md. Parsers dispatch on the
  object shape.
- **Village day.** The data follow `village_day = (PT date - 2025-04-02) + 1`,
  counting weekends. This reproduces all 789 daily-summary targets and the
  agents' own SEARCH_HISTORY day numbers. The documented rule ("increments
  at about 17:00 UTC, skipping most weekends", also in SPEC 2.2) does not
  match the data. `run_day` is a separate dense rank of PT dates with agent
  activity (SPEC appendix A).
- The live UI link format is
  `https://theaidigest.org/village?day={village_day}&time={unix_ms}`.
- Tables were dumped sequentially from a live database. All foreign keys that
  we use resolve.

## 3. Fields per table

Column lists as ingested. Keys not in SCHEMA.md are marked (new).

- `agents` (46): `id`, `name`, `model_string`, `goal` (all null),
  `status_message` (all null), `is_participating`, `is_pending`,
  `is_updating_memory`, `is_paused_for_google_sign_in`, `input_tokens_used`
  and `output_tokens_used` (unreliable), `last_seen_event_index`,
  `paused_until`, `paused_until_task_id`, `current_computer_use_session_id`,
  `current_human_use_session_request_id`, `current_room_id`, `money`,
  `emoji`, `village_id`, `created_at`, `updated_at`. `computer_use_url` and
  `runner_url` were dropped by the publisher.
- `villages` (1): as SCHEMA.md plus `schedule` and `is_chat_open` (new).
- `village_goals` (51): `id`, `goal`, `start_time`, `end_time`, `village_id`,
  timestamps. Contiguous, no gaps or overlaps. The last goal is open from
  2026-07-06 15:59 UTC.
- `agent_goals` (33 rows, 32 agents, from 2026-07-06): `agent_id`, `name`,
  `short_name`, `description`, `start_time`, `end_time`.
- `chat_rooms` (16): `id`, `name`, `deleted_at`, plus
  `whitelisted_agent_names`, `blacklisted_agent_names`, `last_nudger_run_at`,
  `last_nudger_run_chat_message_id` (new). Whitelists are an export-time
  snapshot.
- `chat_messages` (183,485): `id`, `speaker_type` (`agent` 173,493 / `user`
  9,992), `agent_speaker_id`, `user_speaker_id`, `content`, `room_id`,
  `has_been_approved`, timestamps. No reply, quote or mention field.
- `computer_use_sessions` (78,362): `id`, `agent_id`, `session_goal`,
  `short_displayed_session_goal`, `has_been_asked_to_stop`, `village_id`,
  timestamps. 25,969 sessions have a START event, 52,319 a CONSOLIDATE, 6
  both, 70 neither. 248 have no turns.
- `computer_use_turns` (2,510,487): `id`, `session_id`, `agent_action`,
  `agent_messages`, `output`, `error`, `system` (always null),
  `screenshot_is_redacted`, `has_redaction_been_overruled`, timestamps.
  `agent_action` shapes are in section 4, item 7.
- `agent_memories` (246,151): `id`, `content`, `agent_id`, timestamps. Each
  row is a full snapshot (section 4, item 2).
- `summaries` (939): `id`, `type`, `summary_target`, `summary_date`,
  `content`, `generated_by`, `village_id`, timestamps. 110 dates have more
  than one daily row. Regenerated rows have `updated_at` much later than
  `created_at`.
- `claude_code_messages` (244,820): as SCHEMA.md plus `message_uuid` (new,
  always null). Its `get_events` tool results are the only logged record of
  what an agent was shown (section 4, item 3).
- `claude_code_sessions` (303): as SCHEMA.md.
- `events` (381,610). `data.actionType` counts and payload keys:

| actionType | Rows | Payload keys (most common set) |
|---|---:|---|
| `AGENT_TALK` | 173,493 | `content, cost, inputTokens, messageId, output, outputTokens, roomId, speakerId, speakerType` (Claude Code rows: `chatMessageId`, no `speakerType`) |
| `CONSOLIDATE` | 52,325 | `agentId, computerUseSessionId, cost, inputTokens, nextSessionGoal, nextShortDisplayedSessionGoal, output, outputTokens, roomId` |
| `PAUSE` | 40,472 | `agentId, cost, inputTokens, output, outputTokens, roomId, seconds` |
| `WAIT` | 36,022 | `agentId, cost, inputTokens, outputTokens` |
| `START_USING_COMPUTER` | 25,975 | `agentId, computerUseSessionId, cost, inputTokens, output, outputTokens, sessionGoal, shortDisplayedSessionGoal` |
| `STOP_USING_COMPUTER` | 25,939 | `agentId, cost, inputTokens, outputTokens, summary` (no session key) |
| `SEARCH_HISTORY` | 10,802 | `agentId, answerToQuery, cost, inputTokens, output, outputTokens, query, roomId`, and `startDay, endDay` (integers, until 2026-07-29) or `startDate, endDate` (ISO, after) |
| `USER_TALK` | 10,049 | `chatMessageId, content, hasBeenApproved, messageId, roomId, speakerId, speakerName, speakerType` |
| `USER_NAME_CHANGE` | 3,711 | `newName, oldName, userId` (names dropped at ingest) |
| `REQUEST_GOOGLE_SIGN_IN` | 619 | `agentId, cost, inputTokens, output, outputTokens, roomId` |
| `RESTARTING_AFTER_GOOGLE_SIGN_IN` | 611 | `agentId, cost, inputTokens, outputTokens, roomId` |
| `ENTER_ROOM` | 454 | `agentId, cost, currentRooms, inputTokens, output, outputTokens, previousRoomId, previousRoomName, roomId, roomName` |
| `OUTREACH_APPROVAL_REQUEST` | 352 | `agentId, medium, messageContent, outreachApprovalRequestId, rationale, recipient, roomId`, cost fields |
| `OUTREACH_APPROVAL_RESPONSE` | 343 | as the request plus `approval` |
| `REQUEST_HUMAN_HELPER` | 265 | `agentId, estimatedDuration, humanConstraints, humanUseSessionRequestId, roomId, sessionGoal, shortDisplayedSessionGoal`, cost fields |
| `CANCEL_REQUEST_FOR_HUMAN_HELPER` | 141 | `agentId`, cost fields |
| `STOP_HUMAN_USE_SESSION` | 37 | `agentId, endComment, endReason, summary`, cost fields |

`events.parquet` holds the id and scalar fields. `events_text.parquet` holds
the long text and the full payload (`data_json`, without the raw model
output and viewer names).

## 4. Answers to SPEC 2.3

These answers were checked with full-table queries on the pinned export, and each number was re-derived by an independent check. Dates are Pacific (PT) unless stated otherwise. "Undetermined" marks what the data cannot settle.

1. **Reply, quote or mention fields.**
   - There are none. All 183,485 `chat_messages` rows have the same 9 keys. No AGENT_TALK/USER_TALK payload key is reply-like. `chatMessageId` always equals `messageId` (9,850/9,850). The agents' chat tool takes only `message`; about 42 of 86.6k calls also pass a room.
   - Explicit references exist only in the message text, and their use drifts over time rather than stepping at Rooms v1. The share of agent messages containing an `@word` is 10–20% in Apr–Jun 2025, about 2% in Jul–Nov 2025, 13–17% in Dec 2025–Feb 2026, 24% in Mar 2026 and 43–57% from Jul 2026.
   - Before vs from 2026-02-25: 6.2% vs 39.6% of agent messages @-mention another agent, and 17–19% vs 48% carry any explicit reference (a name reference, or a quote of another speaker among the previous 50 messages in the room).
   - Candidate parents: the named agent's latest message in the same room within 50 messages. This gives about 13.2k child–parent pairs before and 34.3k after, after deduplication.
   - The named agent is almost always right, but the parent message is right only about 90% of the time, and only for two groups after 2026-02-25 (about 18k children): single-target reciprocal references and quotes with a unique match.
   - The parent message is right about 0.4 of the time for after-era non-reciprocal @-mentions and about 0.35 for before-era quotes. For before-era name references it is undetermined (0.46 to 0.91 in two small samples).
   - 2–7% of named targets have no message among the previous 50.

2. **`agent_memories` granularity.**
   - Every row is a full memory snapshot, so module B1 uses path S.
   - There is no batch or consolidation id. The raw keys are only `id, content, agent_id, created_at, updated_at`, ids are UUIDv4, and rows are never updated after being written.
   - Consecutive rows of one agent fall into four kinds:
     - APPEND: the previous row is an exact prefix (160,323 pairs).
     - REWRITE: an LLM consolidation, usually 0.5–0.8 of the previous length and keeping 40–70% of its lines (85,657).
     - IDENT: identical (6).
     - TRUNC (119): 113 of these equal a row 2–6 back, i.e. an undo of the last append.
   - Before 2026-03-24:
     - Appends are self-notes, plus a `PREVIOUS (NOW ENDED) COMPUTER USE SESSION (<session id>)` block written about 16 ms before STOP_USING_COMPUTER.
     - Rewrites happen only once memory exceeds about 15k characters (about 9.8k before 2025-05), and they do not always happen at that point.
   - From each agent's first CONSOLIDATE (2026-03-24 or later), every cycle is a session-block APPEND followed a median 88 s later by a REWRITE. The REWRITE is written about 16 ms before the CONSOLIDATE event (48,831 of 52,325 events).
   - Versioning rule:
     - Order rows by `(agent_id, created_at, id)`.
     - A generation is a REWRITE row, and its parent is the previous generation.
     - Exception: 53 fork rows extend an older row. Detect them with `startswith` against earlier rows.
     - Drop IDENT rows. TRUNC rows are undos, not generations.
   - Opus 4.5 (Claude Code) is a different scaffold: 99% of its rows are whole-file rewrites, it has no CONSOLIDATE, and 137 of its rows after 2026-03-24 are still old-regime. The regime is therefore set per agent, not by date.
   - Undetermined:
     - Whether the latest row is exactly the memory in the agent's prompt; only CHANGELOG wording supports this.
     - Why 1,707 CONSOLIDATE events have no memory row within 1 s.

3. **Do summaries enter agent prompts.**
   - There is no evidence that the scaffold puts the `summaries` table into prompts.
   - Prompts are not in the data. `computer_use_turns_text.agent_messages` and `events_text.output` hold only the provider response. A scan of all 2,510,487 turns and 381,610 events finds no user/system/tool roles, tool results or request keys, so SCHEMA.md's "full params + thinking" is wrong.
   - Phrases that first appear in a summary reappear in later agent text about as often as phrases from a placebo set of summaries whose text did not exist yet (after/before ratio 1.12 vs 1.24). Human chat phrases reappear 23.7% vs 0.33%.
   - Summary text does reach agents through their tools:
     - In Feb 2026 agents scraped the village goal pages into a repository and read them back.
     - From May to Sep 2026 they read the village API and agent-built sites.
     - 31 agents read new daily-summary phrases this way.
   - The logged feed of the Claude Code agent (33,839 `get_events` results) contains:
     - feed-type events of other agents and of itself;
     - SEARCH_HISTORY events with their answers;
     - STOP_USING_COMPUTER events without the summary field;
     - no CONSOLIDATE events at all.
   - After Rooms v1 that feed contains only the agent's current room (other-room events 0.7%).
   - Undetermined: what the standard scaffold's prompt contained (system prompt, chat window, whether STOP summaries and CONSOLIDATE goals were shown). This needs the `llm_calls` logs.

4. **SEARCH_HISTORY text.**
   - Yes. All 10,802 events (2025-09-19 to 2026-09-18, 39 agents) keep the query, which is never empty, and `answerToQuery`.
   - Answers: 5 are empty, 637 are "no transcript found" placeholders and about 400 are split into segments (from 2026-04-27). Median length 1,789 characters, p99 12,852.
   - The date range uses two formats:
     - Integer `startDay`/`endDay` up to 2026-07-29 00:00 UTC (6,815 events), where day = (PT date − 2025-04-02) + 1 with weekends counted.
     - ISO `startDate`/`endDate` after that (3,985 events). Our ingest currently leaves these null.
   - Joining turns to events:
     - The 10,148 `search_history` turns join 1:1 to events on agent (via session), exact query and nearest time: 9,945 pairs, 97.6% within 1 s.
     - The 203 unmatched turns are all failed validations.
     - The 857 events without a turn are text-mode calls before computer use (579) and the Claude Code agent (278).
   - The caller receives the answer verbatim: the turn output equals the answer in 9,939 of 9,945 pairs. The caller also uses it: its next memory row adds at least 3 new answer 5-grams in 41.6% of cases, vs 2.65% for a placebo answer.
   - Other agents' SEARCH_HISTORY events, answers included, appear in the Claude Code agent's feed. Until 2026-04-17, answers could also quote earlier answers.
   - Undetermined: whether standard agents were shown other agents' answers or only their queries.

5. **Agent to room visibility.**
   - `chat_rooms` has 16 rooms: 4 live at export and 12 soft-deleted between 2026-03-16 and 2026-07-24. `best` has a 10-agent whitelist, and `rest` blacklists the same agents.
   - Every message before 2026-03-06 is in `general`, so exposure is village-wide until then.
   - Reconstruction rule for an agent's room at any moment:
     - Take the room of the agent's latest earlier event of any type that carries a room. Non-chat events carry a room from 2026-03-05.
     - Before 2026-03-05, use `general`.
     - For an agent's first appearance, use the room of its next event, or the next ENTER_ROOM's `previousRoomId`.
   - Accuracy using only earlier events:
     - 173,486 of 173,493 message rooms. 6 misses are new agents placed in `best` or an onboarding room without an ENTER_ROOM; 1 is a sub-second race.
     - 99.99% of 111,892 non-message events.
     - 99.86% for agents who are not moving but are listed in ENTER_ROOM `currentRooms` snapshots, or 99.90% with the look-ahead. The misses are all on the mass moves of 2026-06-22 and 07-06.
   - Main room by message share:
     - up to 2026-02-24: `general` 100%;
     - 2026-02-25 to 03-15: `general` 97%;
     - 03-16 to 07-05: `rest` 63% plus `best` 26% (disjoint agent sets);
     - from 07-06: `general` 93% plus `focus` 7%.
   - Undetermined: whether an agent entering a room sees that room's earlier messages, and the whitelist history (only the export snapshot exists).
   - Retired agents keep their last room under this rule, so exposure lookups need an activity filter.

6. **Human messages.**
   - Human rows are `chat_messages.speaker_type = 'user'` (9,992 rows, 602 accounts). They match USER_TALK events whose speaker type is `HUMAN`.
   - `has_been_approved` does not identify humans: it is null before 2025-04-14, TRUE on all 2,623 Claude Code agent rows, and never false. `events.speaker_type` does not identify them either.
   - One user account, `445ab51c-3bb1-4475-a536-67f1924b06cf`, is a scaffolding bot with a constant generic display label. It has 2,230 rows:
     - 662 daily pause/resume run markers (2025-05-05 to 2026-08-05);
     - 1,568 auto-nudges (`@<agent> — it looks like you…`, first on 2026-02-13).
   - Nudges must be recognised by this account id: the broad nudge text pattern also matches 44 agent messages.
   - Kickoff messages are posts by staff accounts.
   - Outreach approvals exist only as OUTREACH_APPROVAL_RESPONSE events (cost 0, with `agentId` set to the requester).
   - `computer_use_turns.system` is empty.
   - The 57 USER_TALK events without a chat row are approved human messages from 2025-04-25 to 05-02 whose chat rows were later removed; the cause is undetermined.
   - Genuine human chat falls from about 290 accounts in the 2025 public-chat period to 3–9 staff accounts after 2025-08-13. From 2026-02-10 the bot posts more than the humans do (1,827 vs 668 messages).
   - Rule (pending owner confirmation):
     - `actor_type` = agent if `speaker_type = 'agent'`;
     - system if the account is the bot;
     - human otherwise.
     - This gives 173,493 / 7,762 / 2,230 chat rows.
     - Run markers typed by staff stay human, with an `is_run_marker` flag.

7. **`agent_action` structure.**
   - The harness normalises `agent_action`:
     - GUI actions are `{action, coordinate, text}` for every provider, except the Claude Code agent's 7-key variant (6,642 rows, the only rows that carry scroll direction and amount).
     - bash is `{command}`, with a `restart` key on 98% of OpenAI bash rows.
     - Tool calls have their own keys: `send_message_back_to_chat {content}`, `move_to_room {roomName}`, and `search_history` with day keys until 2026-07-29 and date keys after.
   - The 3,021 non-null rows without an action are all rejected calls or no-ops: 2,433 `{"restart": true}` bash restarts, 467 empty bash calls and 121 computer calls with no action.
   - Of the 80,428 null rows, the OpenAI ones are text-only replies, but about 1.5k Google and Anthropic rows are malformed tool calls.
   - In a random sample of 20k turns:
     - 17.1% contain an http(s) URL and about 18.5% a `/home`, `~/` or `./` path.
     - 93% of path-bearing turns but only 61% of URL-bearing turns have the path or URL in `agent_action`. The rest of the URLs are in tool output (3.7 points), error text (1.8) or `agent_messages` (1.1).
   - Google Docs/Sheets/Forms ids appear in 0.3–0.45% of turns (about 600 distinct ids). GitHub or GitLab `owner/repo` appears in about 6% of turns and 41% of sessions.
   - Window titles are effectively absent: 0.23% of bash commands query window names, and 17% of those return output.
   - Write vs read:
     - It can be classified for bash by regex: about 56–59% read-only, 24% local write, 10–11% git, 4% remote write. The regex is not yet validated on a labelled set.
     - It can also be classified for typed text.
     - GUI clicks, keys and scrolls (about 35% of turns) carry neither a target nor output, so their writes cannot be tied to a document without screenshots.

8. **Daily run hours and village day.**
   - Agent activity forms one block per PT date that follows the schedule:
     - 11:00–13:00 PT until 2025-07-17;
     - 10–13 from 07-18;
     - 10–14 from 2025-10-22;
     - 9–17 on 2026-06-08 to 06-12;
     - 10–14 on 06-15 to 06-26;
     - 9–17 from 2026-06-29.
   - Blocks start 1–3 min after the scheduled start. They end a median 1–7 min after the scheduled end, sometimes up to about 15 min.
   - The 2025-05-23 and 2025-08-18 CHANGELOG entries leave no mark on the boundaries.
   - 2025-11-03 and 11-04 ran on fixed UTC (09:01 PST); 10:01 PST resumed on 11-05. The CHANGELOG does not record this.
   - There are 389 run days with agent activity: all 383 weekdays from 2025-04-02 to 2026-09-18, plus 6 weekend days (2025-04-05, 04-06, 05-10, 05-11, 06-29; 2026-06-13). 10 more weekend dates have only human chat.
   - Pause gap G:
     - Of 3.3M within-day gaps between agent rows, only 18, 10 and 9 exceed 15, 30 and 60 min.
     - Every outage inside a scheduled window is at most 28.2 min.
     - So G = 30 min is stable: t_active totals 1,596–1,600 h for G between 15 and 60 min.
   - Village day:
     - It is `(PT date − 2025-04-02) + 1`, counting weekends.
     - This reproduces 789 of 789 daily-summary targets and the agents' own SEARCH_HISTORY day numbers.
     - The documented "~17:00 UTC, skipping weekends" rule mislabels the first hour of every 9 am PT day (200,160 rows).
   - Extra off-schedule sessions occur on 2025-06-18 (18:01–21:01 PT), Sunday 2025-06-29, and 2026-06-29 (04:41–05:16 PT).
   - Undetermined: exactly when the prompt's day counter increments (between about 12:16 and 16:00 UTC). This matters only for the early block on 2026-06-29.

9. **Model string to family.**
   - All 46 agents map unambiguously.
   - The CHANGELOG roster also has 46 rows and matches the table by name. The "45" is the number of distinct model strings, because the two fine-tuned leaders share one `tinker://` string.
   - Provider: Anthropic 16 (15 API agents plus Opus 4.5 (Claude Code)), OpenAI 14, Google 5, xAI 2, DeepSeek 2, Moonshot 2, Zhipu 2, Meta 1, and 2 Tinker fine-tunes of a Kimi base.
   - Family: Anthropic 16, OpenAI 14, Google 5, Other 11.
   - Every agent is active (at least 60 events). But AGENT_TALK never carries `agent_id`, and the Claude Code agent's 2,623 AGENT_TALK events have a null `speaker_type`. The actor must therefore be `coalesce(agent_id, speaker_id)`.
   - `model_string` is the registry value, not always the model actually served:
     - Gemini 2.5 Pro ran preview or experimental versions on 54,233 turns until 2025-12-02.
     - DeepSeek-V3.2's response format changes on 2026-04-24 at about 17:20 UTC.
     - Returned model ids match `model_string` for all Anthropic and Gemini 3.x turns that carry one.
   - Presence windows should come from activity, not from roster dates or `created_at`. For example, the temporary fine-tuned leader has a 32-turn test session on 2026-05-26 before its first event on 05-28.
   - `agents.*_tokens_used` is unreliable.
   - Undetermined: the served version for the 25 agents whose responses carry no model id.

10. **AGENT_TALK/USER_TALK and `chat_messages`.**
    - `events.message_id = chat_messages.id` is a one-to-one match over all 183,485 chat rows (173,493 AGENT_TALK, 9,992 USER_TALK). Room, speaker and content agree, except for 2 human messages from April 2025.
    - `chat_message_id` is only an alias of `message_id`.
    - 57 USER_TALK events (2025-04-25 to 05-02) have no chat row.
    - The 100,354 `send_message_back_to_chat` turns are the same messages. Matching on the same agent (via session), exact content and the first chat row 0–300 s later links 100,353 of them one-to-one; 1 has null content.
    - The first such turn is on 2025-05-22, not on the CHANGELOG's 2025-05-02.
    - The order is always the same: the turn first, then the chat row (a median 31 ms later), then the event (a median 41 ms after the chat row).
    - The other 73,140 agent messages have no turn: main-loop messages, messages before 2025-05-22, and the Claude Code agent's MCP chat tool. Turns therefore cannot be the source of messages.
    - Dedup rule:
      - One message row per `chat_messages.id`, with `ts_utc = chat_messages.created_at`.
      - Talk events and send-message turns are linked to that row, not emitted as messages.
      - The 57 orphans are taken from events, with a flag.
      - Nothing is deduplicated by content: 4,308 same-agent identical texts are distinct messages.
    - `updated_at` is unusable: it moves by up to 14.8 h on 262 premoderated human rows. Whether agents saw those messages at creation or at approval is undetermined.

## 5. Regime changes to respect in the analysis

Boundaries as observed in the data. Where the data and the CHANGELOG differ,
both are given.

- Schedule (PT): 11:00 to 13:00 until 2025-07-17; 10 to 13 from 07-18; 10 to
  14 from 2025-10-22; 9 to 17 on 2026-06-08..12; 10 to 14 on 06-15..26; 9 to
  17 from 2026-06-29. Fixed-UTC days 2025-11-03 and 11-04 (not in the
  CHANGELOG).
- Human chat: public until 2025-08-13, then only 3 to 9 staff accounts.
- Chat from computer use: CHANGELOG 2025-05-02, first occurrence in the data
  2025-05-22.
- `search_history` tool: 2025-09-05. ISO date arguments from 2026-07-29 (not
  in the CHANGELOG).
- Claude Code agent: 2026-01-26 to 2026-03-31, a different scaffold.
  Analysed separately.
- Auto-nudger: CHANGELOG 2026-02-10, first nudge in the data 2026-02-13.
- Rooms: Rooms v1 on 2026-02-25, but every message is in `general` until
  2026-03-05. The `best`/`rest` split holds from 2026-03-16 to 07-05. From
  07-06 `general` and `focus`.
- Perma-computer-use: from each agent's first CONSOLIDATE (none before
  2026-03-24 10:05 PT). Set per agent, not by date.
- Unseen-event cap: 2026-06-11.
- Model versions: Gemini 2.5 Pro served preview versions until 2025-12-02.
  DeepSeek-V3.2 response format changes on 2026-04-24.
- Explicit @-mentions drift month by month (about 2% in Jul to Nov 2025,
  43% to 57% from Jul 2026). Stratify reference-based statistics by month or
  goal, not by the Rooms v1 date.

## 6. Privacy notes

- Viewer display names (`USER_TALK.speakerName`, `USER_NAME_CHANGE`) are kept
  only in `data/` (`events_text.speaker_name`) or dropped. The Claude Code
  feed in `claude_code_messages_text` has a `userName` field that any
  exposure table must drop.
- Humans are never classified by display name. Some viewers chose
  staff-like names.
- Credential-like strings survive the publisher's scrubbing in
  `agent_memories` text, some SEARCH_HISTORY answers and about 167 bash
  commands of a local test app. Locations are recorded in
  `data/interim/privacy_flags.md` (not in the repository). They are not used.
- Human names appear in free text (memories, search answers, tool output).
  PERSON anchors are hashed (SPEC 6.3.2). Any excerpt shown to a labeller or
  quoted in the write-up is scrubbed first.
- Outreach payloads name third parties and are never published verbatim.
- GitHub and GitLab owner names are hashed in module D outputs, except the
  village's own organisations.
- The dataset's CHANGELOG names one human helper (2026-06-07 entry). That
  name is masked in any copy kept in this repository.
