# QA report: ingest

Dataset `aidigestorg/ai-village` revision `838b4150303ca8228e8edb432d8b8ccae353d258`, exported 2026-09-20T13:05:12.097Z.
Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

### agents

- Rows read 46, rows written 46, unparseable lines 0.
- Manifest rows 46, difference +0.
- SPEC rows about 31.
- Duplicate ids 0.
- `created_at` range 2025-04-02 17:45:08.421915+00:00 to 2026-09-04 19:13:29.589109+00:00 (UTC), parse failures 0.
- `updated_at` range 2026-02-25 10:23:20.034000+00:00 to 2026-09-19 00:06:57.117000+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `name` | 0 | 0.000 |
| `model_string` | 0 | 0.000 |
| `goal` | 46 | 1.000 |
| `status_message` | 46 | 1.000 |
| `is_participating` | 0 | 0.000 |
| `is_pending` | 0 | 0.000 |
| `is_updating_memory` | 0 | 0.000 |
| `is_paused_for_google_sign_in` | 0 | 0.000 |
| `input_tokens_used` | 0 | 0.000 |
| `output_tokens_used` | 0 | 0.000 |
| `last_seen_event_index` | 0 | 0.000 |
| `paused_until` | 39 | 0.848 |
| `paused_until_task_id` | 46 | 1.000 |
| `current_computer_use_session_id` | 7 | 0.152 |
| `current_human_use_session_request_id` | 46 | 1.000 |
| `current_room_id` | 0 | 0.000 |
| `money` | 0 | 0.000 |
| `emoji` | 0 | 0.000 |
| `village_id` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### villages

- Rows read 1, rows written 1, unparseable lines 0.
- Manifest rows 1, difference +0.
- SPEC rows about 1.
- Duplicate ids 0.
- `created_at` range 2025-04-02 17:45:08.318136+00:00 to 2025-04-02 17:45:08.318136+00:00 (UTC), parse failures 0.
- `updated_at` range 2026-09-19 00:00:16.707000+00:00 to 2026-09-19 00:00:16.707000+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `name` | 0 | 0.000 |
| `slug` | 0 | 0.000 |
| `village_goal` | 0 | 0.000 |
| `active_agent_id` | 0 | 0.000 |
| `turn_id` | 1 | 1.000 |
| `schedule` | 0 | 0.000 |
| `is_chat_open` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### village_goals

- Rows read 51, rows written 51, unparseable lines 0.
- Manifest rows 51, difference +0.
- SPEC rows about 45.
- Duplicate ids 0.
- `start_time` range 2025-04-02 12:00:00+00:00 to 2026-07-06 15:59:00+00:00 (UTC), parse failures 0.
- `end_time` range 2025-05-10 17:00:00+00:00 to 2026-07-06 15:59:00+00:00 (UTC), parse failures 0.
- `created_at` range 2025-04-02 17:45:08.318000+00:00 to 2026-07-06 09:56:43.862414+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-05-12 11:57:56.728000+00:00 to 2026-07-06 12:00:45.965000+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `goal` | 0 | 0.000 |
| `start_time` | 0 | 0.000 |
| `end_time` | 1 | 0.020 |
| `village_id` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### agent_goals

- Rows read 33, rows written 33, unparseable lines 0.
- Manifest rows 33, difference +0.
- Duplicate ids 0.
- `start_time` range 2026-07-06 15:59:00+00:00 to 2026-09-04 19:47:39.357000+00:00 (UTC), parse failures 0.
- `end_time` range 2026-09-01 23:42:37.070000+00:00 to 2026-09-01 23:42:37.070000+00:00 (UTC), parse failures 0.
- `created_at` range 2026-07-03 13:56:18.946920+00:00 to 2026-09-04 19:47:39.612732+00:00 (UTC), parse failures 0.
- `updated_at` range 2026-07-03 14:37:49.366905+00:00 to 2026-09-11 10:29:32.283000+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `agent_id` | 0 | 0.000 |
| `name` | 0 | 0.000 |
| `short_name` | 0 | 0.000 |
| `description` | 28 | 0.848 |
| `start_time` | 0 | 0.000 |
| `end_time` | 32 | 0.970 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### chat_rooms

- Rows read 16, rows written 16, unparseable lines 0.
- Manifest rows 16, difference +0.
- SPEC rows about 5.
- Duplicate ids 0.
- `deleted_at` range 2026-03-16 12:08:11.533000+00:00 to 2026-07-25 00:52:34.652000+00:00 (UTC), parse failures 0.
- `last_nudger_run_at` range 2026-03-13 20:46:39.720000+00:00 to 2026-08-20 17:45:23.527000+00:00 (UTC), parse failures 0.
- `created_at` range 2025-04-02 17:45:08.369652+00:00 to 2026-08-05 16:36:36.040933+00:00 (UTC), parse failures 0.
- `updated_at` range 2026-03-16 12:08:11.534000+00:00 to 2026-09-01 20:46:54.864000+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `name` | 0 | 0.000 |
| `deleted_at` | 4 | 0.250 |
| `village_id` | 0 | 0.000 |
| `whitelisted_agent_names` | 6 | 0.375 |
| `blacklisted_agent_names` | 15 | 0.938 |
| `last_nudger_run_at` | 5 | 0.312 |
| `last_nudger_run_chat_message_id` | 5 | 0.312 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### chat_messages

- Rows read 183,485, rows written 183,485, unparseable lines 0.
- Manifest rows 183,485, difference +0.
- SPEC rows about 123,000.
- Duplicate ids 0.
- `created_at` range 2025-04-02 17:47:10.664358+00:00 to 2026-09-18 23:58:11.188784+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-04-02 17:47:10.664361+00:00 to 2026-09-18 23:58:11.188786+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `speaker_type` | 0 | 0.000 |
| `agent_speaker_id` | 9,992 | 0.054 |
| `user_speaker_id` | 173,493 | 0.946 |
| `content` | 0 | 0.000 |
| `room_id` | 0 | 0.000 |
| `has_been_approved` | 173,692 | 0.947 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### computer_use_sessions

- Rows read 78,362, rows written 78,362, unparseable lines 0.
- Manifest rows 78,362, difference +0.
- SPEC rows about 37,000.
- Duplicate ids 0.
- `created_at` range 2025-04-02 18:00:17.539001+00:00 to 2026-09-19 00:03:19.890476+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-04-02 18:00:17.539004+00:00 to 2026-09-19 00:03:19.890479+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `agent_id` | 0 | 0.000 |
| `session_goal` | 1 | 0.000 |
| `short_displayed_session_goal` | 412 | 0.005 |
| `has_been_asked_to_stop` | 0 | 0.000 |
| `village_id` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### summaries

- Rows read 939, rows written 939, unparseable lines 0.
- Manifest rows 939, difference +0.
- SPEC rows about 800.
- Duplicate ids 0.
- `created_at` range 2025-05-13 14:51:35.254459+00:00 to 2026-09-18 16:02:17.097242+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-05-15 10:22:29.519000+00:00 to 2026-09-20 01:02:21.683000+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `type` | 0 | 0.000 |
| `summary_target` | 16 | 0.017 |
| `summary_date` | 131 | 0.140 |
| `content` | 0 | 0.000 |
| `generated_by` | 0 | 0.000 |
| `village_id` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### claude_code_sessions

- Rows read 303, rows written 303, unparseable lines 0.
- Manifest rows 303, difference +0.
- SPEC rows about 300.
- Duplicate ids 0.
- `created_at` range 2026-01-26 19:05:50.054775+00:00 to 2026-03-31 17:01:06.019488+00:00 (UTC), parse failures 0.
- `updated_at` range 2026-01-26 19:05:50.054777+00:00 to 2026-03-31 17:01:06.019490+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `agent_id` | 0 | 0.000 |
| `sdk_session_id` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### events

- Rows read 381,610, rows written 381,610, unparseable lines 0.
- Manifest rows 381,610, difference +0.
- SPEC rows about 233,000.
- Duplicate ids 0.
- `created_at` range 2025-04-02 17:47:10.816356+00:00 to 2026-09-19 00:03:19.868512+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-04-02 17:47:10.816359+00:00 to 2026-09-19 00:03:19.868514+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `event_index` | 0 | 0.000 |
| `village_id` | 0 | 0.000 |
| `action_type` | 0 | 0.000 |
| `data_keys` | 0 | 0.000 |
| `speaker_id` | 198,068 | 0.519 |
| `agent_id` | 187,253 | 0.491 |
| `room_id` | 85,722 | 0.225 |
| `message_id` | 198,068 | 0.519 |
| `cu_session_id` | 303,310 | 0.795 |
| `start_day` | 374,795 | 0.982 |
| `end_day` | 374,795 | 0.982 |
| `seconds` | 341,138 | 0.894 |
| `cost` | 13,760 | 0.036 |
| `input_tokens` | 13,760 | 0.036 |
| `output_tokens` | 13,760 | 0.036 |
| `content_len` | 198,070 | 0.519 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

| actionType | Rows | Most common key set |
|---|---:|---|
| `AGENT_TALK` | 173,493 | `actionType,content,cost,inputTokens,messageId,output,outputTokens,roomId,speakerId,speakerType` |
| `CONSOLIDATE` | 52,325 | `actionType,agentId,computerUseSessionId,cost,inputTokens,nextSessionGoal,nextShortDisplayedSessionGoal,output,outputTokens,roomId` |
| `PAUSE` | 40,472 | `actionType,agentId,cost,inputTokens,output,outputTokens,roomId,seconds` |
| `WAIT` | 36,022 | `actionType,agentId,cost,inputTokens,outputTokens` |
| `START_USING_COMPUTER` | 25,975 | `actionType,agentId,computerUseSessionId,cost,inputTokens,output,outputTokens,sessionGoal,shortDisplayedSessionGoal` |
| `STOP_USING_COMPUTER` | 25,939 | `actionType,agentId,cost,inputTokens,outputTokens,summary` |
| `SEARCH_HISTORY` | 10,802 | `actionType,agentId,answerToQuery,cost,endDay,inputTokens,output,outputTokens,query,roomId,startDay` |
| `USER_TALK` | 10,049 | `actionType,chatMessageId,content,hasBeenApproved,messageId,roomId,speakerId,speakerName,speakerType` |
| `USER_NAME_CHANGE` | 3,711 | `actionType,newName,oldName,userId` |
| `REQUEST_GOOGLE_SIGN_IN` | 619 | `actionType,agentId,cost,inputTokens,output,outputTokens,roomId` |
| `RESTARTING_AFTER_GOOGLE_SIGN_IN` | 611 | `actionType,agentId,cost,inputTokens,outputTokens,roomId` |
| `ENTER_ROOM` | 454 | `actionType,agentId,cost,currentRooms,inputTokens,output,outputTokens,previousRoomId,previousRoomName,roomId,roomName` |
| `OUTREACH_APPROVAL_REQUEST` | 352 | `actionType,agentId,cost,inputTokens,medium,messageContent,output,outputTokens,outreachApprovalRequestId,rationale,recipient,roomId` |
| `OUTREACH_APPROVAL_RESPONSE` | 343 | `actionType,agentId,approval,cost,inputTokens,medium,messageContent,outputTokens,outreachApprovalRequestId,rationale,recipient,roomId` |
| `REQUEST_HUMAN_HELPER` | 265 | `actionType,agentId,cost,estimatedDuration,humanConstraints,humanUseSessionRequestId,inputTokens,output,outputTokens,roomId,sessionGoal,shortDisplayedSessionGoal` |
| `CANCEL_REQUEST_FOR_HUMAN_HELPER` | 141 | `actionType,agentId,cost,inputTokens,output,outputTokens` |
| `STOP_HUMAN_USE_SESSION` | 37 | `actionType,agentId,cost,endComment,endReason,inputTokens,outputTokens,summary` |

### computer_use_turns

- Rows read 2,510,487, rows written 2,510,487, unparseable lines 0.
- Manifest rows 2,510,487, difference +0.
- SPEC rows about 1,140,000.
- Duplicate ids 0.
- `created_at` range 2025-04-02 18:00:35.529327+00:00 to 2026-09-19 00:02:36.111690+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-04-02 18:00:35.529330+00:00 to 2026-09-19 00:02:36.111691+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `session_id` | 0 | 0.000 |
| `action_name` | 83,449 | 0.033 |
| `action_keys` | 80,428 | 0.032 |
| `agent_action` | 80,428 | 0.032 |
| `output_len` | 1,389,075 | 0.553 |
| `error_len` | 2,357,242 | 0.939 |
| `system` | 2,510,487 | 1.000 |
| `screenshot_is_redacted` | 0 | 0.000 |
| `has_redaction_been_overruled` | 1,423,242 | 0.567 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

| action | Rows | Most common key set |
|---|---:|---|
| `bash` | 979,076 | `command` |
| `left_click` | 368,447 | `action,coordinate,text` |
| `key` | 236,938 | `action,coordinate,text` |
| `scroll` | 171,247 | `action,coordinate,text` |
| `type` | 161,483 | `action,coordinate,text` |
| `get_pixel_coords_of_element` | 150,503 | `action,description` |
| `send_message_back_to_chat` | 100,354 | `action,content` |
| `None` | 83,449 | `None` |
| `mouse_move` | 74,236 | `action,coordinate,text` |
| `screenshot` | 57,885 | `action,coordinate,text` |
| `wait` | 48,211 | `action,coordinate,text` |
| `pause` | 39,838 | `action,seconds` |
| `search_history` | 10,148 | `action,endDay,query,startDay` |
| `triple_click` | 7,029 | `action,coordinate,text` |
| `double_click` | 6,977 | `action,coordinate,text` |
| `left_click_drag` | 4,193 | `action,coordinate,text` |
| `right_click` | 3,278 | `action,coordinate,text` |
| `middle_click` | 2,054 | `action,coordinate,text` |
| `view_clipboard` | 1,727 | `action` |
| `move_to_room` | 1,006 | `action,roomName` |
| `hold_key` | 937 | `action,coordinate,text` |
| `request_Google_sign_in` | 619 | `action` |
| `request_approval_for_unsolicited_outreach` | 353 | `action,medium,recipient` |
| `left_mouse_down` | 142 | `action,coordinate,text` |
| `request_human_helper` | 136 | `action,sessionGoal,shortDisplayedSessionGoal` |
| `cursor_position` | 121 | `action,coordinate,text` |
| `left_mouse_up` | 63 | `action,coordinate,text` |
| `cancel_request_for_human_helper` | 37 | `action` |

### agent_memories

- Rows read 246,151, rows written 246,151, unparseable lines 0.
- Manifest rows 246,151, difference +0.
- SPEC rows about 165,000.
- Duplicate ids 0.
- `created_at` range 2025-04-02 18:00:22.121581+00:00 to 2026-09-19 00:03:19.849295+00:00 (UTC), parse failures 0.
- `updated_at` range 2025-04-02 18:00:22.121585+00:00 to 2026-09-19 00:03:19.849297+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `agent_id` | 0 | 0.000 |
| `content_len` | 0 | 0.000 |
| `created_at` | 0 | 0.000 |
| `updated_at` | 0 | 0.000 |

### claude_code_messages

- Rows read 244,820, rows written 244,820, unparseable lines 0.
- Manifest rows 244,820, difference +0.
- SPEC rows about 245,000.
- Duplicate ids 0.
- `created_at` range 2026-01-26 19:05:50.026214+00:00 to 2026-03-31 17:01:05.990115+00:00 (UTC), parse failures 0.

| Column | Nulls | Share |
|---|---:|---:|
| `id` | 0 | 0.000 |
| `agent_id` | 0 | 0.000 |
| `sdk_session_id` | 0 | 0.000 |
| `message_type` | 0 | 0.000 |
| `message_subtype` | 241,419 | 0.986 |
| `message_uuid` | 244,820 | 1.000 |
| `created_at` | 0 | 0.000 |
