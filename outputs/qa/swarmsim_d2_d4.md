# QA: AI Village dependency graph, structure and continuation (modules D2 to D4)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village. Generator: Wenhao Chai, "Predictable Swarm Scaling", 2026, https://wenhaochai.com/blogs/predictable-swarm-scaling.html, re-implemented in module D1 (`avsd.swarmsim.dag`).

The touch rules (section 2) are rules v2, confirmed by the owner on 2026-10-01 (SPEC 8.3). Rules v1, the first draft, are kept as a sensitivity version (the same outputs with the suffix `_v1`); the GUI follow-up that led to v2 is in outputs/qa/swarmsim_gui_gap.md.

## Summary

- Graph. 78,362 computer-use sessions in 51 village-goal graphs. 56,038 sessions touch at least one artifact. The goal graphs hold 130,508 edges (71,748 write, 58,760 read), and 48,954 sessions have at least one parent. 65.2% of the edges join two sessions of the same agent.
- Structure against the generator (pooled over goals; the generator distribution pools one generated DAG per goal with that goal's session count, 64 replicates):
  - Steps with 2+ parents: all edges 0.700, write edges 0.551; generator 0.423 (95% range 0.415 to 0.430); quantile 1.000 (all) and 1.000 (write).
  - Mean parents per step: all edges 2.666, write edges 1.903; generator 1.739 (95% range 1.725 to 1.753); quantile 1.000 (all) and 1.000 (write).
  - Merges between siblings: all edges 0.439, write edges 0.221; generator 0.417 (95% range 0.401 to 0.443); quantile 0.953 (all) and 0.000 (write).
  - Out-degree Gini: all edges 0.496, write edges 0.350; generator 0.534 (95% range 0.527 to 0.542); quantile 0.000 (all) and 0.000 (write).
  - Children of top 10% parents: all edges 0.403, write edges 0.290; generator 0.445 (95% range 0.437 to 0.455); quantile 0.000 (all) and 0.000 (write).
  - Edges skipping 2+ layers: all edges 0.600, write edges 0.449; generator 0.198 (95% range 0.189 to 0.204); quantile 1.000 (all) and 1.000 (write).
- Step cost. Session turn counts do not grow with depth: the within-goal slope of turns relative to the goal's layer-0 sessions on relative depth is 0.0294 (95% CI -0.0918 to 0.0742), against 9 in the blog's c_d = 1 + 9 d / (D - 1). For active minutes it is 0.151 (95% CI -0.122 to 0.255).
- Continuation. Among next sessions with at least one parent, 0.602 (95% CI 0.534 to 0.674; 50,251 pairs, 45 agents) have the agent's previous session among their parents. A random choice among the artifacts written earlier in the same goal gives 0.0632 (95% CI 0.0512 to 0.0765); among those written earlier on the same run day 0.25 (95% CI 0.218 to 0.29).
- Runtime 109 s on 48 processes (dj-l40-0.grasp.maas); the touch extraction is cached and takes about 2 minutes more when it runs.

## 1. Sessions

- Sessions 78,362, of which 78,114 have turns. Nodes are all sessions of a goal, including those without any artifact touch (isolated nodes).
- Turns per session (10%, 50%, 90%, 99% quantiles): 9, 41, 41, 45. The scaffold ends most sessions near 40 turns, so turn counts are capped.
- Active minutes per session (gaps between turns of at most G = 30 minutes, SPEC 4.2): 2.6, 9.52, 22.1, 69.5. Wall minutes from start to last turn: 2.72, 9.98, 27.6, 1,327.

## 2. Touches and the classification rules

A touch is a turn that acts on an artifact. `write` and `read` touches make edges. `observed` (the identifier is only in the tool output) and `mention` (only in text the agent wrote: chat, typed or written content, commit messages, the provider response) are counted and enter only the sensitivity variant `with observed mentions`. `edges_first_touch` counts main-graph edges for which the rule produced the child's first touch of the shared artifact (GUI writes follow a navigation, so they never come first).

| Rule | Mode | Description | Touches | Sessions | Share of sessions | On artifacts | Edges (first touch) |
|---|---|---|---|---|---|---|---|
| B-redirect | write | target of a shell redirection (> or >>) or of tee | 214,295 | 28,852 | 0.369 | 213,280 | 17,948 |
| B-inplace | write | file edited in place (sed -i, perl -i) | 23,982 | 4,844 | 0.062 | 23,938 | 2,212 |
| B-fileop | write | destination or argument of cp, mv, rsync, scp, install, ln, touch, mkdir, rm, rmdir, chmod, truncate, unzip -d, tar -C or tar -f with c | 60,349 | 15,399 | 0.197 | 59,932 | 10,855 |
| B-fileop-src | read | source of cp, rsync, scp, install, ln, or an archive that is unpacked | 19,275 | 6,194 | 0.0793 | 18,599 | 2,800 |
| B-code-write | write | path or URL written by code in a heredoc or -c string (open with w, a or x, write_text, to_csv, savefig, writeFile, requests post, put, patch or delete, fetch with a write method) | 25,889 | 5,877 | 0.0752 | 25,570 | 2,732 |
| B-code-read | read | path or URL that code in a heredoc or -c string opens, reads, lists, runs or fetches (directly or through a variable) | 96,827 | 12,785 | 0.164 | 91,903 | 9,528 |
| B-git-local | write | local repository directory of git add, commit, rm, mv, merge, rebase, reset, checkout, switch, stash, tag, init, apply, am, cherry-pick, restore or pull | 329,778 | 26,338 | 0.337 | 329,455 | 15,339 |
| B-git-push | write | remote repository of git push (directory map, or the remote named in the push output) | 81,246 | 21,040 | 0.269 | 81,105 | 9,643 |
| B-git-clone-dir | write | local directory created by git clone, gh repo clone, glab repo clone | 7,933 | 4,310 | 0.0552 | 7,899 | 1,049 |
| B-git-remote-read | read | remote repository of git clone, pull or fetch | 66,758 | 18,151 | 0.232 | 66,636 | 14,991 |
| B-git-read | read | local repository directory of git log, status, diff, show, branch and other read-only git commands | 219,590 | 27,904 | 0.357 | 219,590 | 9,198 |
| B-forge-write | write | repository, issue or merge request named by gh or glab create, edit, comment, merge, close, reopen, review, delete, upload, fork, or api with a write method or fields | 21,335 | 6,444 | 0.0825 | 21,276 | 2,803 |
| B-forge-read | read | repository named by other gh or glab commands (view, list, api GET) | 76,861 | 13,883 | 0.178 | 76,165 | 10,692 |
| B-http-write | write | URL of curl, wget or httpie with a write method or a request body | 13,465 | 2,400 | 0.0307 | 12,835 | 2,904 |
| B-http-read | read | URL fetched by curl, wget or httpie without a body | 144,372 | 16,179 | 0.207 | 129,257 | 13,446 |
| B-download | write | local file written by curl -o, wget -O or similar | 25,358 | 4,435 | 0.0568 | 25,306 | 2,928 |
| B-upload-src | read | local file sent as a request body (-d @file, -F x=@file, -T file) | 1,837 | 402 | 0.00515 | 1,837 | 111 |
| B-open | read | URL or file opened in a browser or viewer (xdg-open, firefox, chrome); a URL becomes the GUI focus | 2,423 | 1,381 | 0.0177 | 2,330 | 537 |
| B-cd | read | project directory entered with cd or pushd (container level) | 474,529 | 35,245 | 0.451 | 474,511 | 26,721 |
| B-run | read | script that is executed (python x.py, node x.js, bash x.sh, ./x) | 119,747 | 20,853 | 0.267 | 119,633 | 15,821 |
| B-other | read | any other path or URL in a command (cat, grep, ls, head, find, ...) | 252,628 | 26,537 | 0.34 | 236,179 | 26,996 |
| B-content | mention | path or URL inside text the command writes or sends as content (echo, printf, heredoc file bodies, commit messages, --body, --title and API fields, request bodies, string templates in code) | 249,867 | 22,793 | 0.292 | 193,978 | 0 |
| B-xdotool | write | xdotool type or key ctrl+s / ctrl+Return from bash, applied to the GUI focus | 91 | 43 | 0.00055 | 74 | 1 |
| G-nav | read | URL typed as the whole text of a type action (address bar); becomes the GUI focus | 29,925 | 15,524 | 0.199 | 24,727 | 9,444 |
| G-type | write | other text typed while a page is in focus, written to the focused artifact | 11,658 | 4,850 | 0.0621 | 8,122 | 0 |
| G-key | write | ctrl+s or ctrl+Enter while a page is in focus | 299 | 197 | 0.00252 | 229 | 0 |
| G-click | write | click right after locating an element whose description names a write (save, submit, send, post, publish, commit, create, upload, share, reply, comment, confirm, update, apply) while a page is in focus | 1,675 | 1,071 | 0.0137 | 1,106 | 0 |
| G-content | mention | path or URL inside typed text | 8,471 | 2,828 | 0.0362 | 7,460 | 0 |
| G-search | mention | rules v2: text typed into the address bar or a located search box that is a search query, not a document write (refs inside it are mentions) | 18 | 17 | 0.000218 | 16 | 0 |
| G-input | mention | rules v2: a typed sign-in value or a short input (one or two characters, or a one-word game or menu command), not a document write | 0 | 0 | 0 | 0 | 0 |
| T-chat | mention | path or URL in a chat message sent from the computer | 24,931 | 11,725 | 0.15 | 21,347 | 0 |
| T-search | mention | path or URL in a search_history query | 24 | 19 | 0.000243 | 21 | 0 |
| T-other | mention | path or URL in other tool arguments (element descriptions, helper requests) | 1,699 | 1,163 | 0.0149 | 1,381 | 0 |
| O-output | observed | path or URL in the tool output or error text | 984,802 | 36,864 | 0.472 | 665,442 | 0 |
| M-message | mention | path or URL in the provider response (text, thinking, reasoning) | 68,494 | 20,502 | 0.262 | 58,151 | 0 |

Touch rows by mode: mention 353,504, observed 984,802, read 1,504,772, write 817,353.

GUI writes (typed text, ctrl+s or ctrl+Enter, clicks on located write buttons, xdotool input): 66,115, of which 52,392 (79.2%) happen without a GUI focus (no URL was navigated to earlier in the session) and are tied to no artifact. 15,495 of the 20,924 sessions with GUI writes have only such writes. As the SPEC 2.3-7 verification found, these writes cannot reach an artifact without the screenshots (module E). Rules v2 do not count as GUI writes 31,195 typed shell commands (parsed as bash instead), 48,180 sign-in values and short inputs (game moves, single keys), 2,200 searches, 537 navigations v1 missed and 5,494 clicks on text boxes, links or menus (see outputs/qa/swarmsim_gui_gap.md).

## 3. Artifact keys

Keys follow SPEC 8.3 on top of `avsd.events.refs`: Google documents by id (document, sheet, slides, form and Drive file URLs of one id share a key), GitHub and GitLab by owner/repo/path, GitLab API project ids mapped to the project path when the API output names exactly one project (59 ids), GitHub and GitLab Pages URLs mapped to their repository (882 unique GitLab Pages project names resolvable), other URLs without query and fragment, and file paths. Paths, localhost URLs and personal account apps (mail, calendar, Drive home, studio pages) are local to the agent's computer or account, so their key includes the agent. Bare domains, search engines, sign-in, CDN and XML-namespace hosts are not artifacts. Dot directories under home (configuration) are not artifacts. Containers are the repository, the document, the URL itself, or the project directory (the deepest known repository root of the agent, else the first directory below home or /tmp, one level deeper under generic parents such as ~/work).

Keyed touch rows 3,219,290; distinct keys 432,224; containers 224,675. URL domains are shown as registrable domains only.

| Kind | Domain | Keys | Containers | Written keys | Read and write touches | Sessions | Edges (main) |
|---|---|---|---|---|---|---|---|
| gdoc |  | 1,039 | 1,039 | 192 | 4,031 | 4,418 | 861 |
| github |  | 12,455 | 3,804 | 826 | 135,486 | 22,458 | 22,921 |
| gitlab |  | 14,658 | 1,727 | 3,907 | 165,057 | 19,818 | 22,888 |
| local |  | 313,362 | 127,395 | 190,076 | 1,808,818 | 50,724 | 79,288 |
| url |  | 90,710 | 90,710 | 3,768 | 158,102 | 31,000 | 16,304 |
| url (top written domains) | manifold.markets |  |  | 408 |  | 419 |  |
| url (top written domains) | thecolony.cc |  |  | 580 |  | 417 |  |
| url (top written domains) | indexnow.org |  |  | 2 |  | 403 |  |
| url (top written domains) | substack.com |  |  | 184 |  | 317 |  |
| url (top written domains) | 4claw.org |  |  | 515 |  | 256 |  |
| url (top written domains) | gitlab.io |  |  | 149 |  | 239 |  |
| url (top written domains) | clawprint.org |  |  | 236 |  | 190 |  |
| url (top written domains) | youtube.com |  |  | 48 |  | 143 |  |
| url (top written domains) | fourthwall.com |  |  | 45 |  | 108 |  |
| url (top written domains) | mycelnet.ai |  |  | 16 |  | 99 |  |
| url (top written domains) | google.com |  |  | 37 |  | 96 |  |
| url (top written domains) | github.com |  |  | 20 |  | 88 |  |
| url (top written domains) | lichess.org |  |  | 259 |  | 84 |  |
| url (top written domains) | onrender.com |  |  | 39 |  | 63 |  |
| url (top written domains) | memoryvault.link |  |  | 22 |  | 62 |  |

## 4. Edges

Session B gets the edge A -> B when B touches artifact x and A was the last other session to write x before B's first touch of x. Matching is hierarchical within a container (a touch of a path sees writes to that path and to the container as a whole; a touch of the container sees any write inside it). An edge is `write` when B also writes x, `read` otherwise; one pair of sessions linked through several artifacts is one edge, `write` if any link is. Edges must follow session start order, so the graph is a DAG.

| Variant | Edges | Write | Read | Dropped (parent started later) | First touches | With an earlier writer |
|---|---|---|---|---|---|---|
| main | 136,868 | 73,623 | 63,245 | 11,228 | 576,698 | 356,366 |
| exact keys | 155,679 | 76,599 | 79,080 | 4,830 | 576,698 | 230,343 |
| with observed mentions | 219,427 | 73,738 | 145,689 | 22,915 | 1,116,276 | 634,070 |
| structured only | 121,654 | 70,352 | 51,302 | 11,002 | 492,184 | 337,781 |

Edges between sessions of different goals (6,360 in the main variant) are dropped from the per-goal graphs; module D4 uses the global graph. Who builds on whom:

| Edges | Scope | Edges | Same agent | Only through local artifacts |
|---|---|---|---|---|
| all | global | 136,868 | 0.658 | 0.541 |
| all | within_goal | 130,508 | 0.652 | 0.532 |
| write | global | 73,623 | 0.73 | 0.622 |
| write | within_goal | 71,748 | 0.726 | 0.617 |
| read | global | 63,245 | 0.575 | 0.448 |
| read | within_goal | 58,760 | 0.561 | 0.429 |

## 5. Graph size per goal

| Goal | Start | End | Sessions | Agents | Touching | Edges | Write | Read | Cross-goal dropped | Layers | Layers (write) | Root share | Isolated share | 2+ parents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G01 | 2025-04-02 | 2025-05-10 | 1,081 | 7 | 211 | 115 | 45 | 70 | 0 | 13 | 13 | 0.904 | 0.882 | 0.0962 | 0.893 | 0.195 |
| G02 | 2025-05-10 | 2025-05-12 | 43 | 4 | 7 | 2 | 0 | 2 | 4 | 2 | 1 | 0.953 | 0.93 | 0 | 0.966 | 0.163 |
| G03 | 2025-05-12 | 2025-05-15 | 56 | 4 | 20 | 4 | 2 | 2 | 12 | 4 | 2 | 0.929 | 0.893 | 0 | 0.714 | 0.357 |
| G04 | 2025-05-15 | 2025-06-19 | 845 | 6 | 219 | 108 | 46 | 62 | 18 | 10 | 8 | 0.884 | 0.852 | 0.102 | 0.845 | 0.259 |
| G05 | 2025-06-19 | 2025-06-26 | 199 | 4 | 38 | 8 | 7 | 1 | 10 | 3 | 3 | 0.96 | 0.93 | 0 | 0.821 | 0.191 |
| G06 | 2025-06-26 | 2025-07-16 | 601 | 4 | 163 | 92 | 41 | 51 | 15 | 13 | 9 | 0.85 | 0.825 | 0.0222 | 0.787 | 0.271 |
| G07 | 2025-07-16 | 2025-07-18 | 88 | 4 | 12 | 0 | 0 | 0 | 7 | 1 | 1 | 1 | 1 |  | 0.887 | 0.136 |
| G08 | 2025-07-18 | 2025-08-13 | 1,060 | 4 | 217 | 116 | 92 | 24 | 29 | 28 | 28 | 0.893 | 0.872 | 0.0265 | 0.729 | 0.205 |
| G09 | 2025-08-13 | 2025-08-18 | 141 | 4 | 55 | 10 | 5 | 5 | 12 | 3 | 3 | 0.929 | 0.894 | 0 | 0.763 | 0.39 |
| G10 | 2025-08-18 | 2025-08-25 | 301 | 7 | 3 | 0 | 0 | 0 | 2 | 1 | 1 | 1 | 1 |  | 0.94 | 0.00997 |
| G11 | 2025-08-25 | 2025-09-01 | 362 | 7 | 52 | 13 | 6 | 7 | 14 | 4 | 3 | 0.967 | 0.948 | 0.0833 | 0.891 | 0.144 |
| G12 | 2025-09-01 | 2025-09-08 | 335 | 7 | 96 | 39 | 17 | 22 | 24 | 7 | 5 | 0.896 | 0.872 | 0.0857 | 0.815 | 0.287 |
| G13 | 2025-09-08 | 2025-09-22 | 656 | 6 | 160 | 62 | 29 | 33 | 40 | 9 | 6 | 0.924 | 0.892 | 0.24 | 0.878 | 0.244 |
| G14 | 2025-09-22 | 2025-09-29 | 330 | 6 | 46 | 9 | 2 | 7 | 10 | 2 | 2 | 0.973 | 0.964 | 0 | 0.882 | 0.139 |
| G15 | 2025-09-29 | 2025-10-06 | 252 | 7 | 46 | 15 | 6 | 9 | 15 | 3 | 3 | 0.94 | 0.909 | 0 | 0.847 | 0.183 |
| G16 | 2025-10-06 | 2025-10-13 | 351 | 7 | 103 | 46 | 20 | 26 | 12 | 10 | 8 | 0.883 | 0.852 | 0.122 | 0.754 | 0.293 |
| G17 | 2025-10-13 | 2025-10-20 | 280 | 7 | 136 | 98 | 34 | 64 | 20 | 12 | 12 | 0.746 | 0.686 | 0.31 | 0.607 | 0.486 |
| G18 | 2025-10-20 | 2025-11-03 | 827 | 8 | 447 | 355 | 126 | 229 | 47 | 22 | 19 | 0.66 | 0.603 | 0.221 | 0.634 | 0.541 |
| G19 | 2025-11-03 | 2025-11-17 | 898 | 8 | 425 | 371 | 144 | 227 | 53 | 56 | 46 | 0.67 | 0.643 | 0.22 | 0.657 | 0.473 |
| G20 | 2025-11-17 | 2025-12-01 | 1,435 | 10 | 656 | 761 | 340 | 421 | 65 | 105 | 64 | 0.69 | 0.661 | 0.447 | 0.615 | 0.457 |
| G21 | 2025-12-01 | 2025-12-08 | 535 | 9 | 258 | 320 | 90 | 230 | 28 | 26 | 14 | 0.736 | 0.671 | 0.39 | 0.689 | 0.482 |
| G22 | 2025-12-08 | 2025-12-15 | 617 | 10 | 329 | 396 | 170 | 226 | 43 | 59 | 26 | 0.677 | 0.609 | 0.457 | 0.462 | 0.533 |
| G23 | 2025-12-15 | 2025-12-22 | 821 | 10 | 468 | 440 | 120 | 320 | 36 | 50 | 24 | 0.782 | 0.748 | 0.52 | 0.356 | 0.57 |
| G24 | 2025-12-22 | 2025-12-29 | 922 | 10 | 339 | 337 | 158 | 179 | 44 | 52 | 14 | 0.794 | 0.76 | 0.421 | 0.682 | 0.368 |
| G25 | 2025-12-29 | 2026-01-05 | 648 | 10 | 454 | 476 | 110 | 366 | 31 | 21 | 11 | 0.557 | 0.512 | 0.352 | 0.589 | 0.701 |
| G26 | 2026-01-05 | 2026-01-12 | 493 | 10 | 338 | 338 | 144 | 194 | 65 | 28 | 12 | 0.556 | 0.491 | 0.356 | 0.282 | 0.686 |
| G27 | 2026-01-12 | 2026-01-26 | 1,750 | 10 | 1,556 | 3,081 | 1,542 | 1,539 | 121 | 162 | 145 | 0.202 | 0.167 | 0.613 | 0.193 | 0.889 |
| G28 | 2026-01-26 | 2026-02-02 | 781 | 11 | 630 | 899 | 435 | 464 | 41 | 104 | 80 | 0.282 | 0.261 | 0.455 | 0.132 | 0.807 |
| G29 | 2026-02-02 | 2026-02-09 | 939 | 12 | 855 | 1,387 | 682 | 705 | 51 | 64 | 62 | 0.243 | 0.204 | 0.515 | 0.104 | 0.911 |
| G30 | 2026-02-09 | 2026-02-16 | 1,265 | 12 | 1,016 | 1,699 | 804 | 895 | 65 | 172 | 128 | 0.288 | 0.268 | 0.539 | 0.121 | 0.803 |
| G31 | 2026-02-16 | 2026-02-23 | 1,292 | 13 | 1,114 | 2,325 | 1,209 | 1,116 | 197 | 185 | 148 | 0.208 | 0.183 | 0.62 | 0.0867 | 0.862 |
| G32 | 2026-02-23 | 2026-03-02 | 1,371 | 12 | 1,237 | 2,507 | 1,359 | 1,148 | 162 | 206 | 155 | 0.146 | 0.126 | 0.705 | 0.0244 | 0.902 |
| G33 | 2026-03-02 | 2026-03-05 | 797 | 12 | 741 | 1,319 | 912 | 407 | 55 | 162 | 130 | 0.137 | 0.0979 | 0.719 | 0.0525 | 0.93 |
| G34 | 2026-03-05 | 2026-03-16 | 1,834 | 13 | 1,696 | 3,107 | 1,902 | 1,205 | 45 | 307 | 275 | 0.109 | 0.1 | 0.751 | 0.0211 | 0.925 |
| G35 | 2026-03-16 | 2026-03-23 | 1,357 | 13 | 981 | 1,550 | 969 | 581 | 65 | 145 | 129 | 0.31 | 0.296 | 0.578 | 0.187 | 0.723 |
| G36 | 2026-03-23 | 2026-03-30 | 1,227 | 13 | 1,075 | 2,851 | 1,381 | 1,470 | 103 | 196 | 165 | 0.244 | 0.212 | 0.681 | 0.0616 | 0.876 |
| G37 | 2026-03-30 | 2026-04-02 | 551 | 12 | 452 | 828 | 337 | 491 | 227 | 59 | 48 | 0.287 | 0.249 | 0.539 | 0.162 | 0.82 |
| G38 | 2026-04-02 | 2026-04-27 | 3,182 | 14 | 2,324 | 7,664 | 3,394 | 4,270 | 501 | 370 | 301 | 0.337 | 0.313 | 0.759 | 0.131 | 0.73 |
| G39 | 2026-04-27 | 2026-05-04 | 990 | 15 | 917 | 1,358 | 980 | 378 | 83 | 98 | 88 | 0.115 | 0.0929 | 0.357 | 0.0775 | 0.926 |
| G40 | 2026-05-04 | 2026-05-11 | 1,110 | 15 | 974 | 1,700 | 1,382 | 318 | 69 | 190 | 187 | 0.178 | 0.164 | 0.715 | 0.0279 | 0.877 |
| G41 | 2026-05-11 | 2026-05-18 | 1,014 | 15 | 914 | 1,841 | 1,197 | 644 | 166 | 124 | 105 | 0.149 | 0.127 | 0.681 | 0.0446 | 0.901 |
| G42 | 2026-05-18 | 2026-05-25 | 1,221 | 16 | 1,011 | 1,590 | 1,084 | 506 | 137 | 117 | 111 | 0.274 | 0.248 | 0.439 | 0.162 | 0.828 |
| G43 | 2026-05-25 | 2026-05-26 | 307 | 16 | 273 | 451 | 288 | 163 | 46 | 36 | 32 | 0.173 | 0.121 | 0.461 | 0.0539 | 0.889 |
| G44 | 2026-05-26 | 2026-06-01 | 774 | 18 | 666 | 1,457 | 841 | 616 | 231 | 89 | 71 | 0.196 | 0.172 | 0.699 | 0.08 | 0.86 |
| G45 | 2026-06-01 | 2026-06-08 | 1,063 | 18 | 942 | 2,040 | 1,128 | 912 | 266 | 101 | 94 | 0.154 | 0.136 | 0.742 | 0.0662 | 0.886 |
| G46 | 2026-06-08 | 2026-06-15 | 2,836 | 18 | 2,127 | 4,681 | 1,899 | 2,782 | 490 | 273 | 261 | 0.298 | 0.287 | 0.705 | 0.133 | 0.75 |
| G47 | 2026-06-15 | 2026-06-22 | 1,361 | 17 | 952 | 1,794 | 737 | 1,057 | 340 | 86 | 76 | 0.431 | 0.408 | 0.676 | 0.107 | 0.699 |
| G48 | 2026-06-22 | 2026-06-23 | 260 | 17 | 146 | 152 | 83 | 69 | 205 | 12 | 11 | 0.642 | 0.573 | 0.441 | 0.0767 | 0.562 |
| G49 | 2026-06-23 | 2026-06-29 | 1,057 | 17 | 299 | 194 | 97 | 97 | 162 | 33 | 29 | 0.862 | 0.846 | 0.233 | 0.309 | 0.283 |
| G50 | 2026-06-29 | 2026-07-06 | 2,975 | 21 | 1,607 | 2,070 | 1,372 | 698 | 558 | 277 | 252 | 0.662 | 0.644 | 0.665 | 0.197 | 0.54 |
| G51 | 2026-07-06 | open | 32,871 | 32 | 26,235 | 77,432 | 43,980 | 33,452 | 1,318 | 3,701 | 3,242 | 0.261 | 0.249 | 0.799 | 0.075 | 0.798 |

Goals before about 2025-10 have few touching sessions: most of their work was GUI work without a focus (section 2). The open goal G51 (from 2026-07-06) holds most sessions and edges, so pooled statistics lean on it; the median over goals weights goals equally.

## 6. Structure against the generator (D3)

Generator: `grow_dag` with the blog's parameters (17 layers, layer peak at 28% depth, merge probability 0.46, no task variation, seed 20261003), 64 DAGs per goal with the goal's session count. Statistics are computed the same way on both sides (`avsd.swarmsim.depgraph`): parent counts over nodes with at least one parent, the sibling share over nodes with at least two parents (two parents are siblings when they share a parent), out-degree inequality over nodes with at least one child, and the cross-layer share over edges spanning two or more layers after relayering (each node one below its deepest parent). Pooled rows join the counts of all goal graphs; the generator side pools one DAG per goal per replicate. The quantile is the share of generator values below the observed value (ties count half). The generator has one root by construction, while 29,408 AI Village sessions have no parent.

| Edges | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | Nodes with parents | Nodes with 2+ parents |
|---|---|---|---|---|---|---|---|---|
| all | multi_parent_share | 0.7 | 0.423 | 0.415 | 0.43 | 1 | 48,954 | 34,245 |
| all | mean_parents | 2.67 | 1.74 | 1.73 | 1.75 | 1 | 48,954 | 34,245 |
| all | sibling_merge_share | 0.439 | 0.417 | 0.401 | 0.443 | 0.953 | 48,954 | 34,245 |
| all | outdeg_gini | 0.496 | 0.534 | 0.527 | 0.542 | 0 | 48,954 | 34,245 |
| all | top10_child_share | 0.403 | 0.445 | 0.437 | 0.455 | 0 | 48,954 | 34,245 |
| all | cross_layer_share | 0.6 | 0.198 | 0.189 | 0.204 | 1 | 48,954 | 34,245 |
| write | multi_parent_share | 0.551 | 0.423 | 0.415 | 0.43 | 1 | 37,693 | 20,755 |
| write | mean_parents | 1.9 | 1.74 | 1.73 | 1.75 | 1 | 37,693 | 20,755 |
| write | sibling_merge_share | 0.221 | 0.417 | 0.401 | 0.443 | 0 | 37,693 | 20,755 |
| write | outdeg_gini | 0.35 | 0.534 | 0.527 | 0.542 | 0 | 37,693 | 20,755 |
| write | top10_child_share | 0.29 | 0.445 | 0.437 | 0.455 | 0 | 37,693 | 20,755 |
| write | cross_layer_share | 0.449 | 0.198 | 0.189 | 0.204 | 1 | 37,693 | 20,755 |
| read | multi_parent_share | 0.463 | 0.423 | 0.415 | 0.43 | 1 | 31,181 | 14,443 |
| read | mean_parents | 1.88 | 1.74 | 1.73 | 1.75 | 1 | 31,181 | 14,443 |
| read | sibling_merge_share | 0.167 | 0.417 | 0.401 | 0.443 | 0 | 31,181 | 14,443 |
| read | outdeg_gini | 0.562 | 0.534 | 0.527 | 0.542 | 1 | 31,181 | 14,443 |
| read | top10_child_share | 0.506 | 0.445 | 0.437 | 0.455 | 1 | 31,181 | 14,443 |
| read | cross_layer_share | 0.415 | 0.198 | 0.189 | 0.204 | 1 | 31,181 | 14,443 |

Parent-count distribution (share of nodes with at least one parent):

| Edges | Parents | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | Nodes with parents |
|---|---|---|---|---|---|---|---|
| all | 1 | 0.3 | 0.577 | 0.57 | 0.585 | 0 | 48,954 |
| all | 2 | 0.3 | 0.3 | 0.294 | 0.305 | 0.547 | 48,954 |
| all | 3 | 0.164 | 0.0607 | 0.0587 | 0.063 | 1 | 48,954 |
| all | 4+ | 0.235 | 0.0621 | 0.0599 | 0.0637 | 1 | 48,954 |
| write | 1 | 0.449 | 0.577 | 0.57 | 0.585 | 0 | 37,693 |
| write | 2 | 0.352 | 0.3 | 0.294 | 0.305 | 1 | 37,693 |
| write | 3 | 0.119 | 0.0607 | 0.0587 | 0.063 | 1 | 37,693 |
| write | 4+ | 0.0802 | 0.0621 | 0.0599 | 0.0637 | 1 | 37,693 |
| read | 1 | 0.537 | 0.577 | 0.57 | 0.585 | 0 | 31,181 |
| read | 2 | 0.243 | 0.3 | 0.294 | 0.305 | 0 | 31,181 |
| read | 3 | 0.115 | 0.0607 | 0.0587 | 0.063 | 1 | 31,181 |
| read | 4+ | 0.105 | 0.0621 | 0.0599 | 0.0637 | 1 | 31,181 |

Median over goals (each goal weighted equally; the generator value of a replicate is the median over goals of that replicate's DAGs):

| Edges | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | Goals |
|---|---|---|---|---|---|---|---|
| all | multi_parent_share | 0.441 | 0.423 | 0.415 | 0.427 | 1 | 49 |
| all | mean_parents | 1.71 | 1.73 | 1.72 | 1.74 | 0 | 49 |
| all | sibling_merge_share | 0.3 | 0.441 | 0.429 | 0.454 | 0 | 43 |
| all | outdeg_gini | 0.397 | 0.511 | 0.505 | 0.517 | 0 | 49 |
| all | top10_child_share | 0.335 | 0.42 | 0.412 | 0.427 | 0 | 49 |
| all | cross_layer_share | 0.403 | 0.189 | 0.184 | 0.194 | 1 | 49 |
| write | multi_parent_share | 0.255 | 0.423 | 0.415 | 0.428 | 0 | 48 |
| write | mean_parents | 1.34 | 1.73 | 1.72 | 1.74 | 0 | 48 |
| write | sibling_merge_share | 0.167 | 0.439 | 0.425 | 0.454 | 0 | 39 |
| write | outdeg_gini | 0.263 | 0.511 | 0.506 | 0.517 | 0 | 48 |
| write | top10_child_share | 0.235 | 0.421 | 0.413 | 0.428 | 0 | 48 |
| write | cross_layer_share | 0.243 | 0.189 | 0.185 | 0.194 | 1 | 48 |
| read | multi_parent_share | 0.271 | 0.423 | 0.415 | 0.427 | 0 | 49 |
| read | mean_parents | 1.35 | 1.73 | 1.72 | 1.74 | 0 | 49 |
| read | sibling_merge_share | 0.0693 | 0.44 | 0.425 | 0.455 | 0 | 39 |
| read | outdeg_gini | 0.4 | 0.511 | 0.505 | 0.517 | 0 | 49 |
| read | top10_child_share | 0.36 | 0.42 | 0.412 | 0.427 | 0 | 49 |
| read | cross_layer_share | 0.155 | 0.189 | 0.184 | 0.194 | 0 | 49 |

Single goals: number of goal graphs whose value lies below the generator's 2.5% point or above its 97.5% point (undefined where the goal graph has no qualifying node or edge):

| Edges | Statistic | Below 2.5% | Above 97.5% | Inside | Undefined |
|---|---|---|---|---|---|
| all | cross_layer_share | 14 | 35 | 2 | 2 |
| all | mean_parents | 21 | 23 | 7 | 2 |
| all | multi_parent_share | 21 | 23 | 7 | 2 |
| all | outdeg_gini | 42 | 5 | 4 | 2 |
| all | sibling_merge_share | 27 | 16 | 8 | 8 |
| all | top10_child_share | 28 | 7 | 16 | 2 |
| read | cross_layer_share | 25 | 24 | 2 | 2 |
| read | mean_parents | 37 | 9 | 5 | 2 |
| read | multi_parent_share | 37 | 7 | 7 | 2 |
| read | outdeg_gini | 36 | 8 | 7 | 2 |
| read | sibling_merge_share | 36 | 12 | 3 | 12 |
| read | top10_child_share | 26 | 15 | 10 | 2 |
| write | cross_layer_share | 17 | 29 | 5 | 3 |
| write | mean_parents | 41 | 6 | 4 | 3 |
| write | multi_parent_share | 32 | 13 | 6 | 3 |
| write | outdeg_gini | 48 | 3 | 0 | 3 |
| write | sibling_merge_share | 38 | 12 | 1 | 12 |
| write | top10_child_share | 43 | 5 | 3 | 3 |

Sensitivity (pooled): other generator sizes (connected sessions only; depth matched to the goal graph's layer count), exact-key matching, observed and mentioned identifiers counted as reads, and structured artifacts only (no plain URLs).

| Variant | Edges | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile |
|---|---|---|---|---|---|---|---|
| generator at connected-node count | all | multi_parent_share | 0.7 | 0.424 | 0.408 | 0.433 | 1 |
| generator at connected-node count | all | mean_parents | 2.67 | 1.74 | 1.71 | 1.76 | 1 |
| generator at connected-node count | all | sibling_merge_share | 0.439 | 0.42 | 0.399 | 0.445 | 0.922 |
| generator at connected-node count | all | outdeg_gini | 0.496 | 0.531 | 0.523 | 0.544 | 0 |
| generator at connected-node count | all | top10_child_share | 0.403 | 0.443 | 0.432 | 0.457 | 0 |
| generator at connected-node count | all | cross_layer_share | 0.6 | 0.197 | 0.188 | 0.206 | 1 |
| generator at connected-node count | write | multi_parent_share | 0.551 | 0.424 | 0.408 | 0.433 | 1 |
| generator at connected-node count | write | mean_parents | 1.9 | 1.74 | 1.71 | 1.76 | 1 |
| generator at connected-node count | write | sibling_merge_share | 0.221 | 0.42 | 0.399 | 0.445 | 0 |
| generator at connected-node count | write | outdeg_gini | 0.35 | 0.531 | 0.523 | 0.544 | 0 |
| generator at connected-node count | write | top10_child_share | 0.29 | 0.443 | 0.432 | 0.457 | 0 |
| generator at connected-node count | write | cross_layer_share | 0.449 | 0.197 | 0.188 | 0.206 | 1 |
| generator with depth matched to the goal graph | all | multi_parent_share | 0.7 | 0.437 | 0.434 | 0.44 | 1 |
| generator with depth matched to the goal graph | all | mean_parents | 2.67 | 1.73 | 1.73 | 1.74 | 1 |
| generator with depth matched to the goal graph | all | sibling_merge_share | 0.439 | 0.442 | 0.434 | 0.448 | 0.266 |
| generator with depth matched to the goal graph | all | outdeg_gini | 0.496 | 0.425 | 0.423 | 0.427 | 1 |
| generator with depth matched to the goal graph | all | top10_child_share | 0.403 | 0.328 | 0.326 | 0.331 | 1 |
| generator with depth matched to the goal graph | all | cross_layer_share | 0.6 | 0.23 | 0.227 | 0.232 | 1 |
| generator with depth matched to the goal graph | write | multi_parent_share | 0.551 | 0.437 | 0.434 | 0.44 | 1 |
| generator with depth matched to the goal graph | write | mean_parents | 1.9 | 1.73 | 1.73 | 1.74 | 1 |
| generator with depth matched to the goal graph | write | sibling_merge_share | 0.221 | 0.442 | 0.434 | 0.448 | 0 |
| generator with depth matched to the goal graph | write | outdeg_gini | 0.35 | 0.425 | 0.423 | 0.427 | 0 |
| generator with depth matched to the goal graph | write | top10_child_share | 0.29 | 0.328 | 0.326 | 0.331 | 0 |
| generator with depth matched to the goal graph | write | cross_layer_share | 0.449 | 0.23 | 0.227 | 0.232 | 1 |
| exact keys | all | multi_parent_share | 0.719 | 0.423 | 0.415 | 0.43 | 1 |
| exact keys | all | mean_parents | 3.06 | 1.74 | 1.73 | 1.75 | 1 |
| exact keys | all | sibling_merge_share | 0.527 | 0.417 | 0.401 | 0.443 | 1 |
| exact keys | all | outdeg_gini | 0.529 | 0.534 | 0.527 | 0.542 | 0.0625 |
| exact keys | all | top10_child_share | 0.436 | 0.445 | 0.437 | 0.455 | 0.0156 |
| exact keys | all | cross_layer_share | 0.654 | 0.198 | 0.189 | 0.204 | 1 |
| exact keys | write | multi_parent_share | 0.578 | 0.423 | 0.415 | 0.43 | 1 |
| exact keys | write | mean_parents | 2.11 | 1.74 | 1.73 | 1.75 | 1 |
| exact keys | write | sibling_merge_share | 0.284 | 0.417 | 0.401 | 0.443 | 0 |
| exact keys | write | outdeg_gini | 0.348 | 0.534 | 0.527 | 0.542 | 0 |
| exact keys | write | top10_child_share | 0.269 | 0.445 | 0.437 | 0.455 | 0 |
| exact keys | write | cross_layer_share | 0.502 | 0.198 | 0.189 | 0.204 | 1 |
| with observed mentions | all | multi_parent_share | 0.742 | 0.423 | 0.415 | 0.43 | 1 |
| with observed mentions | all | mean_parents | 3.6 | 1.74 | 1.73 | 1.75 | 1 |
| with observed mentions | all | sibling_merge_share | 0.576 | 0.417 | 0.401 | 0.443 | 1 |
| with observed mentions | all | outdeg_gini | 0.566 | 0.534 | 0.527 | 0.542 | 1 |
| with observed mentions | all | top10_child_share | 0.468 | 0.445 | 0.437 | 0.455 | 1 |
| with observed mentions | all | cross_layer_share | 0.701 | 0.198 | 0.189 | 0.204 | 1 |
| with observed mentions | write | multi_parent_share | 0.552 | 0.423 | 0.415 | 0.43 | 1 |
| with observed mentions | write | mean_parents | 1.91 | 1.74 | 1.73 | 1.75 | 1 |
| with observed mentions | write | sibling_merge_share | 0.222 | 0.417 | 0.401 | 0.443 | 0 |
| with observed mentions | write | outdeg_gini | 0.351 | 0.534 | 0.527 | 0.542 | 0 |
| with observed mentions | write | top10_child_share | 0.29 | 0.445 | 0.437 | 0.455 | 0 |
| with observed mentions | write | cross_layer_share | 0.45 | 0.198 | 0.189 | 0.204 | 1 |
| structured only | all | multi_parent_share | 0.691 | 0.423 | 0.415 | 0.43 | 1 |
| structured only | all | mean_parents | 2.46 | 1.74 | 1.73 | 1.75 | 1 |
| structured only | all | sibling_merge_share | 0.396 | 0.417 | 0.401 | 0.443 | 0 |
| structured only | all | outdeg_gini | 0.465 | 0.534 | 0.527 | 0.542 | 0 |
| structured only | all | top10_child_share | 0.37 | 0.445 | 0.437 | 0.455 | 0 |
| structured only | all | cross_layer_share | 0.566 | 0.198 | 0.189 | 0.204 | 1 |
| structured only | write | multi_parent_share | 0.545 | 0.423 | 0.415 | 0.43 | 1 |
| structured only | write | mean_parents | 1.86 | 1.74 | 1.73 | 1.75 | 1 |
| structured only | write | sibling_merge_share | 0.207 | 0.417 | 0.401 | 0.443 | 0 |
| structured only | write | outdeg_gini | 0.345 | 0.534 | 0.527 | 0.542 | 0 |
| structured only | write | top10_child_share | 0.289 | 0.445 | 0.437 | 0.455 | 0 |
| structured only | write | cross_layer_share | 0.437 | 0.198 | 0.189 | 0.204 | 1 |

## 7. Step cost by layer

Each session's turns and active minutes are divided by the mean of the layer-0 sessions of its goal. The blog sets the cost of a step at depth d to c_d = 1 + 9 d / (D - 1), ten times the root's at the deepest layer; `blog` gives that ratio for the sessions in each bin. CIs come from a bootstrap over goals.

| Axis | Bin | Sessions | Goals | Turns | Turns vs layer 0 | CI low | CI high | Active min | Active vs layer 0 | CI low | CI high | Blog |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| layer | 0 | 29,160 | 51 | 31.8 | 1 | 1 | 1 | 12 | 1 | 1 | 1 | 1 |
| layer | 1 | 1,705 | 49 | 33 | 1.06 | 0.992 | 1.11 | 11.2 | 0.983 | 0.925 | 1.06 | 1.37 |
| layer | 2 | 873 | 47 | 33.5 | 1.09 | 1.02 | 1.14 | 11.6 | 1.07 | 0.933 | 1.24 | 1.55 |
| layer | 3-4 | 1,187 | 44 | 33.9 | 1.1 | 1.04 | 1.15 | 12.3 | 1.1 | 1.01 | 1.2 | 1.76 |
| layer | 5-8 | 1,476 | 42 | 33.1 | 1.06 | 1 | 1.11 | 11.7 | 1.05 | 0.947 | 1.15 | 2.22 |
| layer | 9-16 | 1,920 | 40 | 32 | 1.03 | 0.969 | 1.09 | 11.1 | 0.995 | 0.886 | 1.09 | 2.54 |
| layer | 17-32 | 3,113 | 34 | 31.9 | 1.04 | 0.974 | 1.11 | 11.2 | 1.01 | 0.889 | 1.11 | 3.15 |
| layer | 33-64 | 5,107 | 28 | 31.4 | 1.01 | 0.949 | 1.07 | 11 | 0.96 | 0.883 | 1.03 | 4.36 |
| layer | 65+ | 33,573 | 21 | 32.4 | 1.06 | 0.956 | 1.08 | 13.5 | 0.961 | 0.898 | 1.03 | 6.02 |
| relative_depth | 0 | 29,160 | 51 | 31.8 | 1 | 1 | 1 | 12 | 1 | 1 | 1 | 1 |
| relative_depth | (0, 0.2] | 13,050 | 42 | 33 | 1.08 | 0.999 | 1.12 | 11.4 | 0.926 | 0.824 | 1.11 | 1.76 |
| relative_depth | (0.2, 0.4] | 10,070 | 44 | 31.1 | 1.02 | 0.957 | 1.05 | 11.6 | 0.907 | 0.842 | 1.05 | 3.68 |
| relative_depth | (0.4, 0.6] | 8,823 | 45 | 32.4 | 1.05 | 0.961 | 1.1 | 12.8 | 0.978 | 0.913 | 1.12 | 5.49 |
| relative_depth | (0.6, 0.8] | 8,392 | 44 | 33.1 | 1.07 | 0.959 | 1.12 | 12.7 | 0.944 | 0.864 | 0.979 | 7.32 |
| relative_depth | (0.8, 1] | 8,619 | 49 | 32.2 | 1.05 | 0.934 | 1.09 | 16.2 | 1.15 | 0.861 | 1.24 | 9.07 |

Within-goal least-squares slope of relative cost on relative depth d / (D - 1) (the blog's slope is 9):

| Edges | Cost | Slope | CI low | CI high | Sessions | Goals |
|---|---|---|---|---|---|---|
| all | turns | 0.0294 | -0.0918 | 0.0742 | 77,725 | 49 |
| all | active_min | 0.151 | -0.122 | 0.255 | 77,725 | 49 |
| write | turns | 0.165 | 0.0683 | 0.251 | 77,682 | 48 |
| write | active_min | 0.259 | -0.0371 | 0.344 | 77,682 | 48 |

The write-edge table is in depgraph_cost_by_layer.csv.

## 8. Continuation (D4)

For each pair of consecutive sessions (p, n) of one agent, the indicator is 1 when p is among n's parents in the global graph. `with_parents` keeps pairs whose n has a parent; `all_pairs` keeps every pair. The baseline draws n's parented containers at random from the containers written before n started in the same goal (`goal`) or run day (`day`), shared ones by anyone and local ones by the agent itself; `own_work` restricts the pool to containers last written by the agent and the draws to n's containers with an own parent. 95% CIs from 2,000 bootstrap replicates over agents. Strata: all pairs and the two computer-use regimes (`regime_cu`, before and after the switch to continuous computer use).

| Window | Measure | Stratum | Rate | CI low | CI high | Baseline | CI low | CI high | Ratio | CI low | CI high | Pairs | Agents | Median pool |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| goal | with_parents | all | 0.602 | 0.534 | 0.674 | 0.0632 | 0.0512 | 0.0765 | 9.52 | 7.64 | 12.1 | 50,251 | 45 | 312 |
| goal | all_pairs | all | 0.386 | 0.314 | 0.488 | 0.0406 | 0.0317 | 0.0516 | 9.52 | 6.86 | 13.3 | 78,316 | 46 | 135 |
| goal | own_work | all | 0.66 | 0.604 | 0.724 | 0.104 | 0.0873 | 0.122 | 6.34 | 5.3 | 7.72 | 45,825 | 45 | 125 |
| day | with_parents | all | 0.602 | 0.536 | 0.673 | 0.25 | 0.218 | 0.29 | 2.41 | 1.99 | 2.88 | 50,251 | 45 | 23 |
| day | all_pairs | all | 0.386 | 0.31 | 0.483 | 0.161 | 0.129 | 0.205 | 2.41 | 1.74 | 3.27 | 78,316 | 46 | 17 |
| day | own_work | all | 0.66 | 0.601 | 0.725 | 0.391 | 0.362 | 0.427 | 1.69 | 1.48 | 1.91 | 45,825 | 45 | 9 |
| goal | with_parents | regime_pre | 0.432 | 0.347 | 0.516 | 0.0961 | 0.0792 | 0.113 | 4.49 | 3.38 | 5.91 | 12,733 | 23 | 34 |
| goal | all_pairs | regime_pre | 0.212 | 0.14 | 0.309 | 0.0472 | 0.0317 | 0.068 | 4.49 | 2.56 | 7.79 | 25,957 | 24 | 24 |
| goal | own_work | regime_pre | 0.51 | 0.424 | 0.589 | 0.134 | 0.116 | 0.151 | 3.81 | 3.05 | 4.7 | 10,785 | 23 | 20 |
| day | with_parents | regime_pre | 0.432 | 0.346 | 0.517 | 0.234 | 0.196 | 0.277 | 1.84 | 1.41 | 2.36 | 12,733 | 23 | 8 |
| day | all_pairs | regime_pre | 0.212 | 0.143 | 0.313 | 0.115 | 0.0793 | 0.164 | 1.84 | 1.09 | 3.14 | 25,957 | 24 | 4 |
| day | own_work | regime_pre | 0.51 | 0.426 | 0.591 | 0.318 | 0.279 | 0.356 | 1.6 | 1.29 | 1.98 | 10,785 | 23 | 5 |
| goal | with_parents | regime_post | 0.66 | 0.591 | 0.734 | 0.0521 | 0.0393 | 0.0664 | 12.7 | 9.67 | 17.1 | 37,516 | 34 | 850 |
| goal | all_pairs | regime_post | 0.473 | 0.389 | 0.578 | 0.0373 | 0.0284 | 0.049 | 12.7 | 9.02 | 17.6 | 52,352 | 34 | 741 |
| goal | own_work | regime_post | 0.706 | 0.637 | 0.774 | 0.0949 | 0.0762 | 0.117 | 7.44 | 5.88 | 9.43 | 35,039 | 34 | 254 |
| day | with_parents | regime_post | 0.66 | 0.586 | 0.735 | 0.256 | 0.214 | 0.307 | 2.58 | 2.09 | 3.18 | 37,516 | 34 | 31 |
| day | all_pairs | regime_post | 0.473 | 0.388 | 0.576 | 0.183 | 0.145 | 0.232 | 2.58 | 1.87 | 3.56 | 52,352 | 34 | 27 |
| day | own_work | regime_post | 0.706 | 0.64 | 0.775 | 0.414 | 0.374 | 0.458 | 1.71 | 1.48 | 1.95 | 35,039 | 34 | 11 |

With write edges only (the parent link must come through an artifact the next session also writes):

| Window | Measure | Rate | CI low | CI high | Baseline | CI low | CI high | Pairs | Agents |
|---|---|---|---|---|---|---|---|---|---|
| goal | with_parents | 0.659 | 0.596 | 0.726 | 0.0555 | 0.0441 | 0.0681 | 38,421 | 45 |
| goal | all_pairs | 0.323 | 0.256 | 0.409 | 0.0272 | 0.0205 | 0.0353 | 78,316 | 46 |
| goal | own_work | 0.697 | 0.639 | 0.757 | 0.0981 | 0.0803 | 0.116 | 36,318 | 45 |
| day | with_parents | 0.659 | 0.596 | 0.725 | 0.231 | 0.203 | 0.267 | 38,421 | 45 |
| day | all_pairs | 0.323 | 0.255 | 0.41 | 0.113 | 0.0869 | 0.149 | 78,316 | 46 |
| day | own_work | 0.697 | 0.642 | 0.757 | 0.383 | 0.353 | 0.415 | 36,318 | 45 |

## 8b. Robustness to the GUI focus gap

GUI writes without a focus are actions the graph cannot see. Per goal, `gap` is the share of write actions that are GUI writes without a focus (unattributed GUI writes over those plus turns with a write touch on an artifact), and `touch share` the share of sessions that touch an artifact. The pooled D3 statistics with their generator quantiles (the generator pools the same goals' DAGs), the within-goal step-cost slopes and the D4 rates with their baselines are recomputed on each subset of goals (D4: pairs whose next session belongs to the subset). CIs: goal bootstrap for slopes, agent bootstrap for D4; n is nodes with a parent (D3), sessions (cost) or pairs (D4).

| Subset | Definition | Goals | Sessions |
|---|---|---|---|
| full | all goals | 51 | 78,362 |
| gap < 20% | goals whose unattributed GUI writes are under 20% of write actions | 24 | 63,128 |
| gap < 10% | goals whose unattributed GUI writes are under 10% of write actions | 13 | 44,910 |
| touch share >= 80% | goals where at least 80% of sessions touch an artifact | 17 | 18,286 |
| from 2025-10 | goals starting on or after 2025-10-01 | 36 | 72,012 |
| no GUI-heavy early goals | all goals except those before 2025-10 with a gap of at least 80% | 40 | 73,870 |

Gap by goal: median 0.309 (goals before 2025-10: median 0.847; from 2025-10: median 0.132); touch share: median 0.562.

D3, all edges (AI Village value, generator mean and 95% range, quantile):

| Subset | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | n |
|---|---|---|---|---|---|---|---|
| full | multi_parent_share | 0.7 | 0.423 | 0.415 | 0.43 | 1 | 48,954 |
| full | mean_parents | 2.67 | 1.74 | 1.73 | 1.75 | 1 | 48,954 |
| full | sibling_merge_share | 0.439 | 0.417 | 0.401 | 0.443 | 0.953 | 48,954 |
| full | outdeg_gini | 0.496 | 0.534 | 0.527 | 0.542 | 0 | 48,954 |
| full | top10_child_share | 0.403 | 0.445 | 0.437 | 0.455 | 0 | 48,954 |
| full | cross_layer_share | 0.6 | 0.198 | 0.189 | 0.204 | 1 | 48,954 |
| gap < 20% | multi_parent_share | 0.726 | 0.423 | 0.414 | 0.431 | 1 | 45,909 |
| gap < 20% | mean_parents | 2.74 | 1.74 | 1.73 | 1.76 | 1 | 45,909 |
| gap < 20% | sibling_merge_share | 0.44 | 0.407 | 0.387 | 0.437 | 0.969 | 45,909 |
| gap < 20% | outdeg_gini | 0.495 | 0.54 | 0.533 | 0.55 | 0 | 45,909 |
| gap < 20% | top10_child_share | 0.403 | 0.452 | 0.444 | 0.464 | 0 | 45,909 |
| gap < 20% | cross_layer_share | 0.609 | 0.201 | 0.19 | 0.208 | 1 | 45,909 |
| gap < 10% | multi_parent_share | 0.76 | 0.423 | 0.408 | 0.435 | 1 | 34,241 |
| gap < 10% | mean_parents | 2.88 | 1.74 | 1.72 | 1.77 | 1 | 34,241 |
| gap < 10% | sibling_merge_share | 0.444 | 0.4 | 0.373 | 0.444 | 0.969 | 34,241 |
| gap < 10% | outdeg_gini | 0.491 | 0.544 | 0.534 | 0.555 | 0 | 34,241 |
| gap < 10% | top10_child_share | 0.397 | 0.457 | 0.447 | 0.472 | 0 | 34,241 |
| gap < 10% | cross_layer_share | 0.627 | 0.203 | 0.189 | 0.213 | 1 | 34,241 |
| touch share >= 80% | multi_parent_share | 0.622 | 0.423 | 0.413 | 0.43 | 1 | 14,720 |
| touch share >= 80% | mean_parents | 2.07 | 1.73 | 1.71 | 1.75 | 1 | 14,720 |
| touch share >= 80% | sibling_merge_share | 0.347 | 0.437 | 0.422 | 0.452 | 0 | 14,720 |
| touch share >= 80% | outdeg_gini | 0.439 | 0.521 | 0.515 | 0.527 | 0 | 14,720 |
| touch share >= 80% | top10_child_share | 0.349 | 0.429 | 0.421 | 0.438 | 0 | 14,720 |
| touch share >= 80% | cross_layer_share | 0.481 | 0.192 | 0.187 | 0.198 | 1 | 14,720 |
| from 2025-10 | multi_parent_share | 0.707 | 0.423 | 0.415 | 0.431 | 1 | 48,404 |
| from 2025-10 | mean_parents | 2.68 | 1.74 | 1.73 | 1.76 | 1 | 48,404 |
| from 2025-10 | sibling_merge_share | 0.44 | 0.412 | 0.395 | 0.44 | 0.969 | 48,404 |
| from 2025-10 | outdeg_gini | 0.496 | 0.537 | 0.53 | 0.545 | 0 | 48,404 |
| from 2025-10 | top10_child_share | 0.403 | 0.448 | 0.44 | 0.459 | 0 | 48,404 |
| from 2025-10 | cross_layer_share | 0.602 | 0.199 | 0.189 | 0.206 | 1 | 48,404 |
| no GUI-heavy early goals | multi_parent_share | 0.704 | 0.423 | 0.415 | 0.43 | 1 | 48,621 |
| no GUI-heavy early goals | mean_parents | 2.68 | 1.74 | 1.73 | 1.76 | 1 | 48,621 |
| no GUI-heavy early goals | sibling_merge_share | 0.439 | 0.413 | 0.396 | 0.441 | 0.969 | 48,621 |
| no GUI-heavy early goals | outdeg_gini | 0.496 | 0.536 | 0.529 | 0.544 | 0 | 48,621 |
| no GUI-heavy early goals | top10_child_share | 0.403 | 0.447 | 0.439 | 0.458 | 0 | 48,621 |
| no GUI-heavy early goals | cross_layer_share | 0.601 | 0.199 | 0.189 | 0.206 | 1 | 48,621 |

Step cost, within-goal slope of relative cost on relative depth (blog: 9):

| Subset | Cost | Slope | CI low | CI high | Sessions |
|---|---|---|---|---|---|
| full | slope of turns | 0.0294 | -0.0965 | 0.0731 | 77,725 |
| full | slope of active_min | 0.151 | -0.134 | 0.253 | 77,725 |
| gap < 20% | slope of turns | 0.0378 | -0.0845 | 0.076 | 62,886 |
| gap < 20% | slope of active_min | 0.168 | -0.124 | 0.266 | 62,886 |
| gap < 10% | slope of turns | 0.0795 | -0.0307 | 0.1 | 44,744 |
| gap < 10% | slope of active_min | 0.218 | -0.198 | 0.289 | 44,744 |
| touch share >= 80% | slope of turns | -0.00355 | -0.0886 | 0.0796 | 18,136 |
| touch share >= 80% | slope of active_min | -0.13 | -0.222 | -0.0419 | 18,136 |
| from 2025-10 | slope of turns | 0.0287 | -0.101 | 0.0736 | 71,769 |
| from 2025-10 | slope of active_min | 0.149 | -0.14 | 0.258 | 71,769 |
| no GUI-heavy early goals | slope of turns | 0.029 | -0.0934 | 0.0743 | 73,627 |
| no GUI-heavy early goals | slope of active_min | 0.151 | -0.134 | 0.25 | 73,627 |

D4, continuation (all edges):

| Subset | Measure | Window | Rate | CI low | CI high | Baseline | CI low | CI high | Pairs | Agents |
|---|---|---|---|---|---|---|---|---|---|---|
| full | with_parents | goal | 0.602 | 0.535 | 0.672 | 0.0632 | 0.0518 | 0.0761 | 50,251 | 45 |
| full | all_pairs | goal | 0.386 | 0.314 | 0.479 | 0.0406 | 0.0311 | 0.051 | 78,316 | 46 |
| full | with_parents | day | 0.602 | 0.538 | 0.67 | 0.25 | 0.218 | 0.29 | 50,251 | 45 |
| full | all_pairs | day | 0.386 | 0.311 | 0.478 | 0.161 | 0.129 | 0.207 | 78,316 | 46 |
| gap < 20% | with_parents | goal | 0.627 | 0.557 | 0.697 | 0.0631 | 0.051 | 0.0776 | 46,750 | 37 |
| gap < 20% | all_pairs | goal | 0.465 | 0.391 | 0.558 | 0.0468 | 0.0374 | 0.0577 | 63,101 | 37 |
| gap < 20% | with_parents | day | 0.627 | 0.561 | 0.696 | 0.256 | 0.222 | 0.297 | 46,750 | 37 |
| gap < 20% | all_pairs | day | 0.465 | 0.39 | 0.56 | 0.19 | 0.155 | 0.237 | 63,101 | 37 |
| gap < 10% | with_parents | goal | 0.667 | 0.592 | 0.741 | 0.054 | 0.0417 | 0.0683 | 34,555 | 37 |
| gap < 10% | all_pairs | goal | 0.513 | 0.42 | 0.624 | 0.0416 | 0.0319 | 0.0533 | 44,893 | 37 |
| gap < 10% | with_parents | day | 0.667 | 0.588 | 0.746 | 0.267 | 0.227 | 0.313 | 34,555 | 37 |
| gap < 10% | all_pairs | day | 0.513 | 0.42 | 0.624 | 0.205 | 0.163 | 0.263 | 44,893 | 37 |
| touch share >= 80% | with_parents | goal | 0.583 | 0.521 | 0.658 | 0.125 | 0.109 | 0.143 | 15,010 | 22 |
| touch share >= 80% | all_pairs | goal | 0.479 | 0.407 | 0.568 | 0.103 | 0.0853 | 0.123 | 18,277 | 22 |
| touch share >= 80% | with_parents | day | 0.583 | 0.523 | 0.655 | 0.262 | 0.23 | 0.294 | 15,010 | 22 |
| touch share >= 80% | all_pairs | day | 0.479 | 0.401 | 0.566 | 0.215 | 0.181 | 0.253 | 18,277 | 22 |
| from 2025-10 | with_parents | goal | 0.609 | 0.544 | 0.681 | 0.0636 | 0.0511 | 0.0763 | 49,533 | 40 |
| from 2025-10 | all_pairs | goal | 0.419 | 0.343 | 0.513 | 0.0438 | 0.0344 | 0.0547 | 71,979 | 40 |
| from 2025-10 | with_parents | day | 0.609 | 0.545 | 0.684 | 0.252 | 0.22 | 0.294 | 49,533 | 40 |
| from 2025-10 | all_pairs | day | 0.419 | 0.344 | 0.513 | 0.173 | 0.14 | 0.218 | 71,979 | 40 |
| no GUI-heavy early goals | with_parents | goal | 0.607 | 0.54 | 0.675 | 0.0635 | 0.0515 | 0.0767 | 49,808 | 42 |
| no GUI-heavy early goals | all_pairs | goal | 0.409 | 0.334 | 0.506 | 0.0428 | 0.0336 | 0.0538 | 73,837 | 42 |
| no GUI-heavy early goals | with_parents | day | 0.607 | 0.54 | 0.676 | 0.252 | 0.218 | 0.291 | 49,808 | 42 |
| no GUI-heavy early goals | all_pairs | day | 0.409 | 0.339 | 0.504 | 0.17 | 0.136 | 0.214 | 73,837 | 42 |

Do the conclusions hold on each subset? (Write edges and all D4 rows are in outputs/tables/depgraph_robustness.csv.)

- More parents per step than the generator: holds on every subset. Full data: mean parents 2.67 (quantile 1); steps with 2+ parents 0.7 (quantile 1).
- More layer-skipping edges than the generator: holds on every subset. Full data: edges skipping 2+ layers 0.6 (quantile 1).
- A more even spread of children than the generator: holds on every subset. Full data: out-degree Gini 0.496 (quantile 0); top-10% share 0.403 (quantile 0).
- Step cost does not grow with depth as the blog assumes: holds on every subset. Full data: slope of turns 0.0294 [-0.0965, 0.0731], of active minutes 0.151 [-0.134, 0.253] (blog: 9).
- Continuation far above chance: holds on every subset. Full data: rate 0.602 [0.535, 0.672] against 0.0632 (goal) and 0.25 (run day), 50,251 pairs.

## 9. Choices beyond the SPEC text

- Touch modes `observed` and `mention` are kept apart from `read`; only write and read touches make edges in the main graph (sensitivity variant above).
- Matching within containers (repository, project directory) on top of the SPEC 8.3 keys, so that a push or a clone links to the files inside the repository; exact-key matching is a sensitivity variant.
- Local artifacts (paths, localhost, personal account apps) are keyed per agent because every agent has its own computer and accounts.
- Edges from a session that started after the child are dropped to keep a DAG; edges across goals are dropped from the per-goal graphs.
- The generator uses the goal's session count (isolated sessions included) and the blog's 17 layers; connected-session counts and matched depth are sensitivity variants.
- Parent-count statistics are taken over nodes with at least one parent, because the generator has one root and the AI Village graphs have many.
- D4 counts artifacts at the container level, takes the parents from the global graph, and uses two periods (goal, run day) for the reachable pool.
- Step cost uses active minutes (pauses longer than G removed) and costs relative to the goal's layer-0 sessions.

## 10. Outputs and command

- `outputs/tables/depgraph_goals.csv`
- `outputs/tables/depgraph_structure.csv`
- `outputs/tables/depgraph_parent_counts.csv`
- `outputs/tables/depgraph_sensitivity.csv`
- `outputs/tables/depgraph_cost_by_layer.csv`
- `outputs/tables/depgraph_continuation.csv`
- `outputs/tables/depgraph_rules.csv`
- `outputs/tables/depgraph_artifacts.csv`
- `outputs/tables/depgraph_robustness.csv`
- `outputs/figures/F7_depgraph_generator.pdf`
- `outputs/qa/swarmsim_d2_d4.md`
- `outputs/figures/F7_depgraph_generator.png`
- Private, under `data/interim/depgraph/`: touches, keyed session-artifact table, edges, continuation pairs, provider-response refs.

Command: `avsd swarmsim calibrate` (Slurm: `sbatch scripts/depgraph_calibrate.sbatch`; `--force-extract` re-extracts the touches). Library: `avsd.swarmsim.calibrate.run_calibration(cfg)`.
Python 3.11.16, numpy 2.4.6, polars 1.44.2.
