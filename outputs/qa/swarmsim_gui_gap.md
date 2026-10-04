# QA: why most GUI writes have no focus (module D2 follow-up)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village. Text data only: no screenshots and no external model. Every number counts GUI writes as the D2 rules v1 define them (typed text, ctrl+s or ctrl+Enter, a click right after locating a write button, xdotool input).

## Main causes

- 153,721 GUI writes, 132,756 (86.4%) without a focus in 23,006 sessions.
- 83,446 of the unattributed writes (62.9%) are not writes to a persistent document at all and should be reclassified, not counted as a gap. The remaining 49,310 (37.1%) are real writes whose target the text data does not name.
- Structural cause of the remaining gap: 122,015 unattributed writes (91.9%) happen in sessions that never type a URL. Agents reach pages by clicking links, bookmarks, tabs and results, or keep working in windows an earlier session left open, and the scaffold logs no page, URL or window title for GUI actions (section 5).
- No focus heuristic recovers the page. On writes whose focus is known, the best one (narr_session) names the right artifact for 49.3% of its predictions; the focus carried over from the previous session is right for 14.7% (section 4). None goes into rules v2.
- Rules v2 (the main version since the owner confirmed them on 2026-10-01) apply the validated reclassification: 87,606 of the 153,721 v1 GUI writes are no longer GUI writes (typed shell commands are parsed as bash instead). 66,115 GUI writes remain, 52,392 (79.2%) without a focus. Coverage, D3 and D4 barely change (section 6).
- Unattributed writes by most likely target:
  - short input: 42,218 (31.8%); not a document write.
  - terminal command: 29,536 (22.2%); not a document write.
  - message or post: 11,913 (9.0%).
  - form field: 11,424 (8.6%).
  - write button: 6,938 (5.2%).
  - prose, target unnamed: 6,809 (5.1%).
  - click on a box, link or menu: 4,645 (3.5%); not a document write.
  - code: 4,425 (3.3%).
  - document text: 3,970 (3.0%).
  - terminal or program input: 3,218 (2.4%); not a document write.
  - save or submit key: 2,648 (2.0%).
  - navigation missed: 2,148 (1.6%); not a document write.
  - search query: 1,649 (1.2%); not a document write.
  - other text: 1,183 (0.9%).
  - sign-in value: 32 (0.0%); not a document write.

## 1. Breakdown of the unattributed GUI writes

`Unattributed rate` is the share of a group's GUI writes without a focus; `share of unattributed` is the group's part of all unattributed writes.

### Action kind

| kind | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| click | 14,106 | 11,583 | 0.821 | 0.0873 |
| key | 2,457 | 2,157 | 0.878 | 0.0162 |
| type | 131,274 | 113,258 | 0.863 | 0.853 |
| xdotool | 5,884 | 5,758 | 0.979 | 0.0434 |

### Computer-use regime

| regime_cu | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| post | 100,883 | 90,476 | 0.897 | 0.682 |
| pre | 52,838 | 42,280 | 0.8 | 0.318 |

### Scaffold

| scaffold | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| claude_code | 391 | 279 | 0.714 | 0.0021 |
| standard | 153,330 | 132,477 | 0.864 | 0.998 |

### Session also uses the bash tool

| session_has_bash | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| no | 95,826 | 83,081 | 0.867 | 0.626 |
| yes | 57,895 | 49,675 | 0.858 | 0.374 |

### Regime and bash use

| regime_cu | session_has_bash | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|---|
| post | no | 53,319 | 49,059 | 0.92 | 0.37 |
| post | yes | 47,564 | 41,417 | 0.871 | 0.312 |
| pre | no | 42,507 | 34,022 | 0.8 | 0.256 |
| pre | yes | 10,331 | 8,258 | 0.799 | 0.0622 |

### Session uses the locate-element tool

| session_locates | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| no | 96,365 | 84,116 | 0.873 | 0.634 |
| yes | 57,356 | 48,640 | 0.848 | 0.366 |

### Session navigates by URL at some point

| session_navigates | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| no | 122,015 | 122,015 | 1 | 0.919 |
| yes | 31,706 | 10,741 | 0.339 | 0.0809 |

### Position in the session

| pos_bin | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| turns 0-2 | 4,825 | 4,823 | 1 | 0.0363 |
| turns 10-24 | 62,680 | 54,196 | 0.865 | 0.408 |
| turns 25+ | 56,750 | 45,672 | 0.805 | 0.344 |
| turns 3-9 | 29,466 | 28,065 | 0.952 | 0.211 |

### Model family

| model_family | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| Anthropic | 54,284 | 46,657 | 0.859 | 0.351 |
| Google | 50,095 | 45,338 | 0.905 | 0.342 |
| OpenAI | 44,825 | 36,653 | 0.818 | 0.276 |
| Other | 4,517 | 4,108 | 0.909 | 0.0309 |

### Month (Pacific time)

| month | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| 2025-04 | 2,608 | 2,183 | 0.837 | 0.0164 |
| 2025-05 | 1,679 | 1,294 | 0.771 | 0.00975 |
| 2025-06 | 2,245 | 1,723 | 0.767 | 0.013 |
| 2025-07 | 3,371 | 2,552 | 0.757 | 0.0192 |
| 2025-08 | 3,199 | 2,587 | 0.809 | 0.0195 |
| 2025-09 | 3,664 | 3,050 | 0.832 | 0.023 |
| 2025-10 | 4,379 | 3,513 | 0.802 | 0.0265 |
| 2025-11 | 5,535 | 4,146 | 0.749 | 0.0312 |
| 2025-12 | 8,541 | 6,773 | 0.793 | 0.051 |
| 2026-01 | 7,440 | 5,944 | 0.799 | 0.0448 |
| 2026-02 | 6,181 | 5,047 | 0.817 | 0.038 |
| 2026-03 | 4,767 | 4,065 | 0.853 | 0.0306 |
| 2026-04 | 4,515 | 3,540 | 0.784 | 0.0267 |
| 2026-05 | 5,407 | 4,453 | 0.824 | 0.0335 |
| 2026-06 | 33,465 | 31,099 | 0.929 | 0.234 |
| 2026-07 | 30,798 | 27,203 | 0.883 | 0.205 |
| 2026-08 | 17,833 | 16,284 | 0.913 | 0.123 |
| 2026-09 | 8,094 | 7,300 | 0.902 | 0.055 |

### Models with the most unattributed GUI writes

| model_family | model | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|---|
| Google | gemini-3.1-pro-preview | 18,411 | 17,211 | 0.935 | 0.13 |
| Google | gemini-2.5-pro | 19,733 | 17,077 | 0.865 | 0.129 |
| OpenAI | gpt-5-2025-08-07 | 15,000 | 12,087 | 0.806 | 0.091 |
| Anthropic | claude-haiku-4-5-20251001 | 12,362 | 11,270 | 0.912 | 0.0849 |
| Google | gemini-3.5-flash | 9,730 | 9,248 | 0.95 | 0.0697 |
| Anthropic | claude-3-7-sonnet-20250219 | 9,393 | 8,268 | 0.88 | 0.0623 |
| OpenAI | gpt-5.2-2025-12-11 | 8,890 | 6,590 | 0.741 | 0.0496 |
| Anthropic | claude-sonnet-4-6 | 6,700 | 6,585 | 0.983 | 0.0496 |
| Anthropic | claude-sonnet-4-5-20250929 | 6,910 | 6,185 | 0.895 | 0.0466 |
| OpenAI | gpt-5.1-2025-11-13 | 6,452 | 5,660 | 0.877 | 0.0426 |
| Anthropic | claude-opus-4-5-20251101 | 6,392 | 5,477 | 0.857 | 0.0413 |
| OpenAI | gpt-5.4-2026-03-05 | 4,353 | 3,962 | 0.91 | 0.0298 |
| Other | kimi-k2.6 | 3,835 | 3,478 | 0.907 | 0.0262 |
| OpenAI | o3-2025-04-16 | 4,549 | 3,327 | 0.731 | 0.0251 |
| OpenAI | gpt-5.5 | 3,147 | 2,983 | 0.948 | 0.0225 |

## 2. What the typed text is

Typed text (and the text of `xdotool type`) is classified with `avsd.swarmsim.touches.classify_typed`, first match wins: a shell command line (as typed into a terminal window); a sign-in value (a scrubbed value or a located password field); a URL, host, local address or file:, view-source: or javascript: address that v1 misses; code (two or more code markers); a search (a short query after an address-bar key or into a located search box, or mail-search operators); a short input (one or two characters, one lower-case word, chess moves, or short lower-case commands entered with a newline, or with Return right after while the agent's words name a game or a terminal); a form field (a short single-line value); prose (a sentence or longer text); other. A click is a write only on a named button with no box, field, link, menu, tab or icon named before the word button (`is_write_button`). Targets add context: other short text typed while a terminal was opened, clicked or named in the ten turns before is `terminal or program input`; prose is a `message or post` or `document text` when the agent named mail, chat, a post, a document or an editor in this turn or the three before; a list of email addresses is part of a message.

| text class (type writes) | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|
| code | 5,235 | 4,404 | 0.841 | 0.0389 |
| credential | 71 | 32 | 0.451 | 0.000283 |
| form_field | 20,200 | 15,452 | 0.765 | 0.136 |
| other | 2,511 | 2,034 | 0.81 | 0.018 |
| prose | 25,606 | 20,140 | 0.787 | 0.178 |
| search | 2,200 | 1,641 | 0.746 | 0.0145 |
| shell | 31,195 | 29,430 | 0.943 | 0.26 |
| short_input | 41,830 | 38,164 | 0.912 | 0.337 |
| url | 2,426 | 1,961 | 0.808 | 0.0173 |

| target | not_document | gui_writes | unattributed | unattributed_rate | share_of_unattributed |
|---|---|---|---|---|---|
| click on a box, link or menu | yes | 5,494 | 4,645 | 0.845 | 0.035 |
| code | no | 5,256 | 4,425 | 0.842 | 0.0333 |
| document text | no | 5,063 | 3,970 | 0.784 | 0.0299 |
| form field | no | 14,878 | 11,424 | 0.768 | 0.0861 |
| message or post | no | 14,856 | 11,913 | 0.802 | 0.0897 |
| navigation missed | yes | 2,639 | 2,148 | 0.814 | 0.0162 |
| other text | no | 1,494 | 1,183 | 0.792 | 0.00891 |
| prose, target unnamed | no | 8,961 | 6,809 | 0.76 | 0.0513 |
| save or submit key | no | 2,965 | 2,648 | 0.893 | 0.0199 |
| search query | yes | 2,209 | 1,649 | 0.746 | 0.0124 |
| short input | yes | 45,892 | 42,218 | 0.92 | 0.318 |
| sign-in value | yes | 71 | 32 | 0.451 | 0.000241 |
| terminal command | yes | 31,301 | 29,536 | 0.944 | 0.222 |
| terminal or program input | yes | 4,030 | 3,218 | 0.799 | 0.0242 |
| write button | no | 8,612 | 6,938 | 0.806 | 0.0523 |

Spot check of the classes (scrubbed samples read by hand; correct of checked):

| class | correct | checked | precision |
|---|---|---|---|
| terminal command | 15 | 15 | 1 |
| short input | 14 | 15 | 0.933 |
| search query | 15 | 15 | 1 |
| navigation missed | 15 | 15 | 1 |
| sign-in value | 14 | 15 | 0.933 |
| terminal or program input | 12 | 15 | 0.8 |
| click on a box, link or menu (not a write) | 19 | 20 | 0.95 |
| write button (a real write) | 17 | 20 | 0.85 |

Paraphrased examples:

- terminal command: listing a directory, entering a project folder, printing the tail of a log, or a multi-line script typed into a terminal window and run with Enter
- short input: single letters, compass directions, chess moves or short verb-object commands entered into a text adventure or a roguelike game; digits and punctuation keys
- search query: mail-search operators (a sender filter, a date window) typed into a mailbox search box; a short query typed after the address-bar shortcut
- navigation missed: a local web app's address with a port, a local image file or a view-source address typed into the address bar
- sign-in value: a scrubbed password or token typed into a sign-in field
- terminal or program input: browser-console statements that read or set page storage, commands typed into a terminal-based game
- click on a box, link or menu: a click on a reply text box, a comment field, an upload menu item, a link to an issue, a reply icon
- message or post: an email body or recipient list, a reply to a post on a social site, a forum comment
- form field: a title, a name, a number or a date typed into a short field
- write button: a click on Send, Comment, Commit changes, Publish or Save
- document text: headings and paragraphs of reports and plans, answers in a questionnaire
- code: HTML or script source typed into an editor, and browser-console snippets
- save or submit key: ctrl+s in a text editor, ctrl+Enter to post a reply

## 3. Focus signals the v1 rules miss

Share of unattributed and attributed GUI writes that show each signal (a write can show several).

| Signal | Writes | n | With signal | Share |
|---|---|---|---|---|
| address-bar key in the 3 turns before (ctrl+l, F6, alt+d) | unattributed | 132,756 | 1,535 | 0.0116 |
| address-bar key in the 3 turns before (ctrl+l, F6, alt+d) | attributed | 20,965 | 719 | 0.0343 |
| typed text is a URL or host that v1 misses (local host, URL plus a word) | unattributed | 132,756 | 2,148 | 0.0162 |
| typed text is a URL or host that v1 misses (local host, URL plus a word) | attributed | 20,965 | 491 | 0.0234 |
| located link, tab, bookmark, result or item clicked earlier in the session | unattributed | 132,756 | 25,563 | 0.193 |
| located link, tab, bookmark, result or item clicked earlier in the session | attributed | 20,965 | 4,282 | 0.204 |
| focus carried from the previous session is a Drive, Gmail, Docs or forge home page | unattributed | 132,756 | 10,932 | 0.0823 |
| focus carried from the previous session is a Drive, Gmail, Docs or forge home page | attributed | 20,965 | 2,407 | 0.115 |
| window switch or new-window key in the 10 turns before | unattributed | 132,756 | 5,178 | 0.039 |
| window switch or new-window key in the 10 turns before | attributed | 20,965 | 1,919 | 0.0915 |
| app launched from bash earlier in the session | unattributed | 132,756 | 6,458 | 0.0486 |
| app launched from bash earlier in the session | attributed | 20,965 | 1,259 | 0.0601 |
| terminal named, opened or clicked in the 10 turns before | unattributed | 132,756 | 55,745 | 0.42 |
| terminal named, opened or clicked in the 10 turns before | attributed | 20,965 | 4,563 | 0.218 |
| agent named a URL or document in this turn or the 3 before | unattributed | 132,756 | 5,263 | 0.0396 |
| agent named a URL or document in this turn or the 3 before | attributed | 20,965 | 1,143 | 0.0545 |
| agent named a document, mail, chat, post, editor or terminal in its words | unattributed | 132,756 | 70,442 | 0.531 |
| agent named a document, mail, chat, post, editor or terminal in its words | attributed | 20,965 | 10,345 | 0.493 |
| previous session of the agent ended with a focus | unattributed | 132,756 | 132,618 | 0.999 |
| previous session of the agent ended with a focus | attributed | 20,965 | 20,923 | 0.998 |
| previous session ended at most 30 minutes before | unattributed | 132,756 | 38,314 | 0.289 |
| previous session ended at most 30 minutes before | attributed | 20,965 | 14,386 | 0.686 |

## 4. Validation of the focus heuristics

Each heuristic names a focus without looking at the in-session navigation. On the 20,965 GUI writes whose v1 focus is known, we hide that focus and check whether the heuristic names the same artifact key (or at least the same container). Coverage is the share of unattributed writes for which the heuristic names anything.

| Heuristic | Known writes | Predicted | Accuracy (key) | Accuracy (container) | Unattributed | Covered | Coverage |
|---|---|---|---|---|---|---|---|
| carry | 20,965 | 20,923 | 0.147 | 0.179 | 132,756 | 132,618 | 0.999 |
| carry_30m | 20,965 | 14,386 | 0.163 | 0.2 | 132,756 | 38,314 | 0.289 |
| narr_near | 20,965 | 1,143 | 0.304 | 0.369 | 132,756 | 5,263 | 0.0396 |
| narr_near_after_focus | 20,965 | 965 | 0.223 | 0.296 | 132,756 | 5,263 | 0.0396 |
| narr_session | 20,965 | 7,276 | 0.493 | 0.534 | 132,756 | 15,309 | 0.115 |

Carry-over accuracy by the gap between the end of the previous session and the start of this one:

| Gap from (min) | Gap to (min) | Known writes | Accuracy (key) | Accuracy (container) | Unattributed writes |
|---|---|---|---|---|---|
| 0 | 5 | 7,761 | 0.194 | 0.222 | 17,685 |
| 5 | 30 | 6,625 | 0.127 | 0.173 | 20,629 |
| 30 | 120 | 3,029 | 0.114 | 0.152 | 23,639 |
| 120 | 1,440 | 2,189 | 0.119 | 0.136 | 25,007 |
| 1,440 |  | 1,319 | 0.0895 | 0.0948 | 45,658 |

## 5. What the scaffold logged in each era

- From the launch (2025-04-02) the computer tool logs each GUI action as `{action, coordinate, text}`: a click position, the typed text or the key name. GUI actions have no tool output, and no page, URL or window title is logged; only the screenshot shows the page (schema_notes 2.3-7).
- A bash tool existed from the launch, but until September 2025 agents used it in under 1% of turns (2% to 5% of sessions) and typed commands into GUI terminal windows instead. After a prompt change on 2025-10-09 (coding-assistant instructions added) bash rose to 5% to 15% of turns (25% to 39% of sessions in October to December 2025). On 2026-01-12 the bash tool description started telling agents they need not open a GUI terminal window; bash has been 33% to 55% of turns (67% to 84% of sessions) since.
- The locate-element tool (`get_pixel_coords_of_element`, a text description of the element before a click) existed from the launch; prompts told Gemini (2025-04-24, 2025-07-10) and GPT-5.2 (2025-12-15) to use it. Its descriptions are the only text record of what a click targeted.
- GPT-5.4 used native computer-use calls from 2026-03-10; the Claude Code agent's GUI actions use a seven-key variant (2026-01 to 2026-03). A 100-turn session cap holds from 2026-02-20. xdotool key names are normalized from 2026-04-27, with the agent's text kept in the logs.
- Perma-computer-use (2026-03-24; ported to the other scaffolds on 2026-03-13): sessions run back to back and the computer, its windows and the browser persist, so a session often starts on whatever the previous one left open.

| Month | Turns | Bash share of turns | GUI share of turns | Type share | Locate-element share | Seven-key GUI share | Sessions | Sessions with bash | Sessions with GUI |
|---|---|---|---|---|---|---|---|---|---|
| 2025-04 | 23,724 | 0.00175 | 0.968 | 0.12 | 0.124 | 0 | 891 | 0.0224 | 1 |
| 2025-05 | 19,855 | 0.00397 | 0.923 | 0.0875 | 0.194 | 0 | 649 | 0.0308 | 1 |
| 2025-06 | 25,933 | 0.00221 | 0.871 | 0.0924 | 0.131 | 0 | 859 | 0.0268 | 1 |
| 2025-07 | 34,162 | 0.0111 | 0.925 | 0.105 | 0.163 | 0 | 1,091 | 0.0449 | 1 |
| 2025-08 | 41,556 | 0.00534 | 0.914 | 0.0858 | 0.163 | 0 | 1,282 | 0.0382 | 0.997 |
| 2025-09 | 48,144 | 0.00778 | 0.871 | 0.0848 | 0.148 | 0 | 1,442 | 0.0513 | 0.999 |
| 2025-10 | 47,890 | 0.052 | 0.861 | 0.107 | 0.124 | 0 | 1,588 | 0.254 | 0.997 |
| 2025-11 | 67,779 | 0.0597 | 0.895 | 0.094 | 0.119 | 0 | 2,334 | 0.229 | 0.934 |
| 2025-12 | 103,201 | 0.151 | 0.806 | 0.0951 | 0.0906 | 0 | 3,272 | 0.385 | 0.874 |
| 2026-01 | 94,111 | 0.33 | 0.623 | 0.0929 | 0.0617 | 0.000839 | 3,287 | 0.671 | 0.823 |
| 2026-02 | 124,611 | 0.483 | 0.474 | 0.0675 | 0.036 | 0.0189 | 4,743 | 0.771 | 0.767 |
| 2026-03 | 162,261 | 0.526 | 0.423 | 0.0378 | 0.0378 | 0.0259 | 5,559 | 0.806 | 0.822 |
| 2026-04 | 152,617 | 0.393 | 0.538 | 0.0388 | 0.0546 | 0 | 4,120 | 0.711 | 0.924 |
| 2026-05 | 164,951 | 0.533 | 0.39 | 0.0378 | 0.0402 | 0 | 4,648 | 0.84 | 0.941 |
| 2026-06 | 254,373 | 0.382 | 0.528 | 0.132 | 0.0412 | 0 | 7,754 | 0.675 | 0.929 |
| 2026-07 | 502,630 | 0.47 | 0.433 | 0.0655 | 0.0515 | 0 | 15,441 | 0.778 | 0.853 |
| 2026-08 | 409,475 | 0.503 | 0.388 | 0.0425 | 0.0585 | 0 | 12,152 | 0.816 | 0.846 |
| 2026-09 | 233,214 | 0.546 | 0.35 | 0.0356 | 0.0457 | 0 | 7,002 | 0.839 | 0.881 |

First and last day of each action name:

| Action | First | Last | Turns |
|---|---|---|---|
| screenshot | 2025-04-02 | 2026-09-19 | 57,885 |
| left_click | 2025-04-02 | 2026-09-19 | 368,447 |
| type | 2025-04-02 | 2026-09-19 | 161,483 |
| mouse_move | 2025-04-02 | 2026-09-19 | 74,236 |
| get_pixel_coords_of_element | 2025-04-02 | 2026-09-19 | 150,503 |
| left_click_drag | 2025-04-02 | 2026-09-18 | 4,193 |
| bash | 2025-04-02 | 2026-09-19 | 979,076 |
| double_click | 2025-04-02 | 2026-09-18 | 6,977 |
| cursor_position | 2025-04-02 | 2026-09-18 | 121 |
| wait | 2025-04-02 | 2026-09-18 | 48,211 |
|  | 2025-04-02 | 2026-09-19 | 83,449 |
| triple_click | 2025-04-02 | 2026-09-18 | 7,029 |
| key | 2025-04-02 | 2026-09-19 | 236,938 |
| scroll | 2025-04-02 | 2026-09-19 | 171,247 |
| right_click | 2025-04-03 | 2026-09-16 | 3,278 |
| left_mouse_up | 2025-04-06 | 2026-09-14 | 63 |
| left_mouse_down | 2025-04-06 | 2026-09-14 | 142 |
| hold_key | 2025-04-23 | 2026-09-10 | 937 |
| middle_click | 2025-05-07 | 2026-09-19 | 2,054 |
| send_message_back_to_chat | 2025-05-22 | 2026-09-18 | 100,354 |
| request_Google_sign_in | 2025-10-06 | 2026-09-18 | 619 |
| view_clipboard | 2025-12-15 | 2026-09-18 | 1,727 |
| move_to_room | 2026-03-06 | 2026-09-18 | 1,006 |
| pause | 2026-03-24 | 2026-09-18 | 39,838 |
| search_history | 2026-03-24 | 2026-09-18 | 10,148 |
| request_human_helper | 2026-03-24 | 2026-09-01 | 136 |
| cancel_request_for_human_helper | 2026-03-26 | 2026-08-24 | 37 |
| request_approval_for_unsolicited_outreach | 2026-04-14 | 2026-09-18 | 353 |

## 6. Rules v2 and the rerun

Rules v2 (`RULE_SETS['v2']`): reclassify typed text True; typed shell commands parsed as bash True; an address-bar search clears the focus True; focus carried over from the previous session within None minutes; focus named in the agent's words within None turns. The owner confirmed rules v2 on 2026-10-01: they are the main version (unsuffixed outputs), and v1 is kept as a sensitivity version (outputs with the suffix `_v1`).

| Measure | v1 | v2 |
|---|---|---|
| sessions touching an artifact | 54,356 | 56,038 |
| edges within goals (all) | 128,043 | 130,508 |
| edges within goals (write) | 70,590 | 71,748 |
| edges within goals (read) | 57,453 | 58,760 |

D3, pooled over goals (generator mean unchanged):

| Edges | Statistic | v1 | Quantile v1 | v2 | Quantile v2 | Generator mean |
|---|---|---|---|---|---|---|
| all | cross_layer_share | 0.601 | 1 | 0.6 | 1 | 0.198 |
| all | mean_parents | 2.67 | 1 | 2.67 | 1 | 1.74 |
| all | multi_parent_share | 0.7 | 1 | 0.7 | 1 | 0.423 |
| all | outdeg_gini | 0.494 | 0 | 0.496 | 0 | 0.534 |
| all | parents_1 | 0.3 | 0 | 0.3 | 0 | 0.577 |
| all | parents_2 | 0.299 | 0.344 | 0.3 | 0.547 | 0.3 |
| all | parents_3 | 0.164 | 1 | 0.164 | 1 | 0.0607 |
| all | parents_4+ | 0.237 | 1 | 0.235 | 1 | 0.0621 |
| all | sibling_merge_share | 0.443 | 0.969 | 0.439 | 0.953 | 0.417 |
| all | top10_child_share | 0.401 | 0 | 0.403 | 0 | 0.445 |
| write | cross_layer_share | 0.45 | 1 | 0.449 | 1 | 0.198 |
| write | mean_parents | 1.91 | 1 | 1.9 | 1 | 1.74 |
| write | multi_parent_share | 0.551 | 1 | 0.551 | 1 | 0.423 |
| write | outdeg_gini | 0.35 | 0 | 0.35 | 0 | 0.534 |
| write | parents_1 | 0.449 | 0 | 0.449 | 0 | 0.577 |
| write | parents_2 | 0.351 | 1 | 0.352 | 1 | 0.3 |
| write | parents_3 | 0.12 | 1 | 0.119 | 1 | 0.0607 |
| write | parents_4+ | 0.0803 | 1 | 0.0802 | 1 | 0.0621 |
| write | sibling_merge_share | 0.222 | 0 | 0.221 | 0 | 0.417 |
| write | top10_child_share | 0.29 | 0 | 0.29 | 0 | 0.445 |

D4, all strata:

| Edges | Window | Measure | Rate v1 | Baseline v1 | Pairs v1 | Rate v2 | CI low | CI high | Baseline v2 | Pairs v2 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | day | all_pairs | 0.376 | 0.152 | 78,316 | 0.386 | 0.31 | 0.483 | 0.161 | 78,316 |
| all | day | own_work | 0.658 | 0.391 | 44,714 | 0.66 | 0.601 | 0.725 | 0.391 | 45,825 |
| all | day | with_parents | 0.599 | 0.243 | 49,112 | 0.602 | 0.536 | 0.673 | 0.25 | 50,251 |
| all | goal | all_pairs | 0.376 | 0.0385 | 78,316 | 0.386 | 0.314 | 0.488 | 0.0406 | 78,316 |
| all | goal | own_work | 0.658 | 0.104 | 44,714 | 0.66 | 0.604 | 0.724 | 0.104 | 45,825 |
| all | goal | with_parents | 0.599 | 0.0615 | 49,112 | 0.602 | 0.534 | 0.674 | 0.0632 | 50,251 |
| write | day | all_pairs | 0.315 | 0.108 | 78,316 | 0.323 | 0.255 | 0.41 | 0.113 | 78,316 |
| write | day | own_work | 0.694 | 0.382 | 35,568 | 0.697 | 0.642 | 0.757 | 0.383 | 36,318 |
| write | day | with_parents | 0.654 | 0.223 | 37,766 | 0.659 | 0.596 | 0.725 | 0.231 | 38,421 |
| write | goal | all_pairs | 0.315 | 0.0261 | 78,316 | 0.323 | 0.256 | 0.409 | 0.0272 | 78,316 |
| write | goal | own_work | 0.694 | 0.098 | 35,568 | 0.697 | 0.639 | 0.757 | 0.0981 | 36,318 |
| write | goal | with_parents | 0.654 | 0.0541 | 37,766 | 0.659 | 0.596 | 0.726 | 0.0554 | 38,421 |

Command: `python scripts/depgraph_gui_gap.py` (diagnosis); `avsd swarmsim calibrate` (main, rules v2) and `avsd swarmsim calibrate --rules v1` (sensitivity).
