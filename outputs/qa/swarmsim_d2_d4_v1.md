# QA: AI Village dependency graph, structure and continuation (modules D2 to D4, touch rules v1 (sensitivity version))

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village. Generator: Wenhao Chai, "Predictable Swarm Scaling", 2026, https://wenhaochai.com/blogs/predictable-swarm-scaling.html, re-implemented in module D1 (`avsd.swarmsim.dag`).

This report uses touch rules v1, the first draft, kept as a sensitivity version. The main version is rules v2, confirmed by the owner on 2026-10-01 (outputs/qa/swarmsim_d2_d4.md).

## Summary

- Graph. 78,362 computer-use sessions in 51 village-goal graphs. 54,356 sessions touch at least one artifact. The goal graphs hold 128,043 edges (70,590 write, 57,453 read), and 47,888 sessions have at least one parent. 64.8% of the edges join two sessions of the same agent.
- Structure against the generator (pooled over goals; the generator distribution pools one generated DAG per goal with that goal's session count, 64 replicates):
  - Steps with 2+ parents: all edges 0.700, write edges 0.551; generator 0.423 (95% range 0.415 to 0.430); quantile 1.000 (all) and 1.000 (write).
  - Mean parents per step: all edges 2.674, write edges 1.906; generator 1.739 (95% range 1.725 to 1.753); quantile 1.000 (all) and 1.000 (write).
  - Merges between siblings: all edges 0.443, write edges 0.222; generator 0.417 (95% range 0.401 to 0.443); quantile 0.969 (all) and 0.000 (write).
  - Out-degree Gini: all edges 0.494, write edges 0.350; generator 0.534 (95% range 0.527 to 0.542); quantile 0.000 (all) and 0.000 (write).
  - Children of top 10% parents: all edges 0.401, write edges 0.290; generator 0.445 (95% range 0.437 to 0.455); quantile 0.000 (all) and 0.000 (write).
  - Edges skipping 2+ layers: all edges 0.601, write edges 0.450; generator 0.198 (95% range 0.189 to 0.204); quantile 1.000 (all) and 1.000 (write).
- Step cost. Session turn counts do not grow with depth: the within-goal slope of turns relative to the goal's layer-0 sessions on relative depth is 0.0208 (95% CI -0.0994 to 0.0645), against 9 in the blog's c_d = 1 + 9 d / (D - 1). For active minutes it is 0.151 (95% CI -0.118 to 0.254).
- Continuation. Among next sessions with at least one parent, 0.599 (95% CI 0.529 to 0.673; 49,112 pairs, 45 agents) have the agent's previous session among their parents. A random choice among the artifacts written earlier in the same goal gives 0.0615 (95% CI 0.0488 to 0.075); among those written earlier on the same run day 0.243 (95% CI 0.21 to 0.283).
- Runtime 108 s on 48 processes (dj-l40-0.grasp.maas); the touch extraction is cached and takes about 2 minutes more when it runs.

## 1. Sessions

- Sessions 78,362, of which 78,114 have turns. Nodes are all sessions of a goal, including those without any artifact touch (isolated nodes).
- Turns per session (10%, 50%, 90%, 99% quantiles): 9, 41, 41, 45. The scaffold ends most sessions near 40 turns, so turn counts are capped.
- Active minutes per session (gaps between turns of at most G = 30 minutes, SPEC 4.2): 2.6, 9.52, 22.1, 69.5. Wall minutes from start to last turn: 2.72, 9.98, 27.6, 1,327.

## 2. Touches and the classification rules

A touch is a turn that acts on an artifact. `write` and `read` touches make edges. `observed` (the identifier is only in the tool output) and `mention` (only in text the agent wrote: chat, typed or written content, commit messages, the provider response) are counted and enter only the sensitivity variant `with observed mentions`. `edges_first_touch` counts main-graph edges for which the rule produced the child's first touch of the shared artifact (GUI writes follow a navigation, so they never come first).

| Rule | Mode | Description | Touches | Sessions | Share of sessions | On artifacts | Edges (first touch) |
|---|---|---|---|---|---|---|---|
| B-redirect | write | target of a shell redirection (> or >>) or of tee | 207,778 | 27,991 | 0.358 | 207,105 | 17,230 |
| B-inplace | write | file edited in place (sed -i, perl -i) | 23,649 | 4,761 | 0.0609 | 23,616 | 2,155 |
| B-fileop | write | destination or argument of cp, mv, rsync, scp, install, ln, touch, mkdir, rm, rmdir, chmod, truncate, unzip -d, tar -C or tar -f with c | 58,418 | 14,903 | 0.191 | 58,062 | 10,483 |
| B-fileop-src | read | source of cp, rsync, scp, install, ln, or an archive that is unpacked | 18,965 | 6,072 | 0.0777 | 18,294 | 2,795 |
| B-code-write | write | path or URL written by code in a heredoc or -c string (open with w, a or x, write_text, to_csv, savefig, writeFile, requests post, put, patch or delete, fetch with a write method) | 25,638 | 5,820 | 0.0745 | 25,323 | 2,736 |
| B-code-read | read | path or URL that code in a heredoc or -c string opens, reads, lists, runs or fetches (directly or through a variable) | 95,392 | 12,636 | 0.162 | 90,534 | 9,451 |
| B-git-local | write | local repository directory of git add, commit, rm, mv, merge, rebase, reset, checkout, switch, stash, tag, init, apply, am, cherry-pick, restore or pull | 324,191 | 25,756 | 0.33 | 323,988 | 15,053 |
| B-git-push | write | remote repository of git push (directory map, or the remote named in the push output) | 80,027 | 20,726 | 0.265 | 79,896 | 9,547 |
| B-git-clone-dir | write | local directory created by git clone, gh repo clone, glab repo clone | 7,689 | 4,144 | 0.0531 | 7,657 | 977 |
| B-git-remote-read | read | remote repository of git clone, pull or fetch | 65,596 | 17,702 | 0.227 | 65,479 | 14,630 |
| B-git-read | read | local repository directory of git log, status, diff, show, branch and other read-only git commands | 216,176 | 27,389 | 0.351 | 216,176 | 9,082 |
| B-forge-write | write | repository, issue or merge request named by gh or glab create, edit, comment, merge, close, reopen, review, delete, upload, fork, or api with a write method or fields | 20,961 | 6,320 | 0.0809 | 20,903 | 2,765 |
| B-forge-read | read | repository named by other gh or glab commands (view, list, api GET) | 75,919 | 13,655 | 0.175 | 75,226 | 10,585 |
| B-http-write | write | URL of curl, wget or httpie with a write method or a request body | 13,132 | 2,288 | 0.0293 | 12,511 | 2,758 |
| B-http-read | read | URL fetched by curl, wget or httpie without a body | 142,332 | 15,757 | 0.202 | 127,338 | 13,502 |
| B-download | write | local file written by curl -o, wget -O or similar | 24,207 | 4,291 | 0.0549 | 24,185 | 2,792 |
| B-upload-src | read | local file sent as a request body (-d @file, -F x=@file, -T file) | 1,804 | 381 | 0.00488 | 1,804 | 104 |
| B-open | read | URL or file opened in a browser or viewer (xdg-open, firefox, chrome); a URL becomes the GUI focus | 1,566 | 990 | 0.0127 | 1,488 | 486 |
| B-cd | read | project directory entered with cd or pushd (container level) | 471,990 | 34,389 | 0.44 | 471,975 | 25,894 |
| B-run | read | script that is executed (python x.py, node x.js, bash x.sh, ./x) | 117,861 | 20,278 | 0.26 | 117,781 | 15,414 |
| B-other | read | any other path or URL in a command (cat, grep, ls, head, find, ...) | 246,799 | 25,878 | 0.331 | 230,693 | 26,325 |
| B-content | mention | path or URL inside text the command writes or sends as content (echo, printf, heredoc file bodies, commit messages, --body, --title and API fields, request bodies, string templates in code) | 247,688 | 22,486 | 0.288 | 192,049 | 0 |
| B-xdotool | write | xdotool type or key ctrl+s / ctrl+Return from bash, applied to the GUI focus | 126 | 65 | 0.000832 | 100 | 1 |
| G-nav | read | URL typed as the whole text of a type action (address bar); becomes the GUI focus | 29,388 | 15,243 | 0.195 | 24,239 | 10,011 |
| G-type | write | other text typed while a page is in focus, written to the focused artifact | 18,016 | 6,182 | 0.0791 | 11,242 | 0 |
| G-key | write | ctrl+s or ctrl+Enter while a page is in focus | 300 | 198 | 0.00253 | 230 | 0 |
| G-click | write | click right after locating an element whose description names a write (save, submit, send, post, publish, commit, create, upload, share, reply, comment, confirm, update, apply) while a page is in focus | 2,523 | 1,309 | 0.0168 | 1,768 | 0 |
| G-content | mention | path or URL inside typed text | 26,241 | 5,939 | 0.076 | 23,898 | 0 |
| G-search | mention | rules v2: text typed into the address bar or a located search box that is a search query, not a document write (refs inside it are mentions) | 0 | 0 | 0 | 0 | 0 |
| G-input | mention | rules v2: a typed sign-in value or a short input (one or two characters, or a one-word game or menu command), not a document write | 0 | 0 | 0 | 0 | 0 |
| T-chat | mention | path or URL in a chat message sent from the computer | 24,931 | 11,725 | 0.15 | 21,347 | 0 |
| T-search | mention | path or URL in a search_history query | 24 | 19 | 0.000243 | 21 | 0 |
| T-other | mention | path or URL in other tool arguments (element descriptions, helper requests) | 1,699 | 1,163 | 0.0149 | 1,381 | 0 |
| O-output | observed | path or URL in the tool output or error text | 984,844 | 36,878 | 0.472 | 665,484 | 0 |
| M-message | mention | path or URL in the provider response (text, thinking, reasoning) | 67,703 | 20,288 | 0.26 | 57,494 | 0 |

Touch rows by mode: mention 368,286, observed 984,844, read 1,483,788, write 806,655.

GUI writes (typed text, ctrl+s or ctrl+Enter, clicks on located write buttons, xdotool input): 153,721, of which 132,756 (86.4%) happen without a GUI focus (no URL was navigated to earlier in the session) and are tied to no artifact. 21,112 of the 27,928 sessions with GUI writes have only such writes. As the SPEC 2.3-7 verification found, these writes cannot reach an artifact without the screenshots (module E).

## 3. Artifact keys

Keys follow SPEC 8.3 on top of `avsd.events.refs`: Google documents by id (document, sheet, slides, form and Drive file URLs of one id share a key), GitHub and GitLab by owner/repo/path, GitLab API project ids mapped to the project path when the API output names exactly one project (59 ids), GitHub and GitLab Pages URLs mapped to their repository (882 unique GitLab Pages project names resolvable), other URLs without query and fragment, and file paths. Paths, localhost URLs and personal account apps (mail, calendar, Drive home, studio pages) are local to the agent's computer or account, so their key includes the agent. Bare domains, search engines, sign-in, CDN and XML-namespace hosts are not artifacts. Dot directories under home (configuration) are not artifacts. Containers are the repository, the document, the URL itself, or the project directory (the deepest known repository root of the agent, else the first directory below home or /tmp, one level deeper under generic parents such as ~/work).

Keyed touch rows 3,199,287; distinct keys 429,867; containers 223,825. URL domains are shown as registrable domains only.

| Kind | Domain | Keys | Containers | Written keys | Read and write touches | Sessions | Edges (main) |
|---|---|---|---|---|---|---|---|
| gdoc |  | 1,039 | 1,039 | 218 | 4,137 | 4,418 | 920 |
| github |  | 12,453 | 3,802 | 850 | 134,741 | 22,262 | 22,559 |
| gitlab |  | 14,653 | 1,726 | 3,919 | 162,068 | 19,739 | 22,591 |
| local |  | 311,008 | 126,544 | 186,872 | 1,778,801 | 50,054 | 76,504 |
| url |  | 90,714 | 90,714 | 4,081 | 157,866 | 31,040 | 17,096 |
| url (top written domains) | manifold.markets |  |  | 518 |  | 514 |  |
| url (top written domains) | thecolony.cc |  |  | 582 |  | 415 |  |
| url (top written domains) | indexnow.org |  |  | 2 |  | 403 |  |
| url (top written domains) | substack.com |  |  | 195 |  | 336 |  |
| url (top written domains) | gitlab.io |  |  | 189 |  | 293 |  |
| url (top written domains) | 4claw.org |  |  | 515 |  | 257 |  |
| url (top written domains) | lichess.org |  |  | 320 |  | 236 |  |
| url (top written domains) | clawprint.org |  |  | 236 |  | 190 |  |
| url (top written domains) | youtube.com |  |  | 54 |  | 169 |  |
| url (top written domains) | fourthwall.com |  |  | 52 |  | 160 |  |
| url (top written domains) | google.com |  |  | 37 |  | 106 |  |
| url (top written domains) | github.com |  |  | 23 |  | 103 |  |
| url (top written domains) | mycelnet.ai |  |  | 17 |  | 99 |  |
| url (top written domains) | onrender.com |  |  | 39 |  | 63 |  |
| url (top written domains) | memoryvault.link |  |  | 22 |  | 62 |  |

## 4. Edges

Session B gets the edge A -> B when B touches artifact x and A was the last other session to write x before B's first touch of x. Matching is hierarchical within a container (a touch of a path sees writes to that path and to the container as a whole; a touch of the container sees any write inside it). An edge is `write` when B also writes x, `read` otherwise; one pair of sessions linked through several artifacts is one edge, `write` if any link is. Edges must follow session start order, so the graph is a DAG.

| Variant | Edges | Write | Read | Dropped (parent started later) | First touches | With an earlier writer |
|---|---|---|---|---|---|---|
| main | 134,301 | 72,461 | 61,840 | 11,109 | 565,538 | 349,682 |
| exact keys | 153,034 | 75,417 | 77,617 | 4,740 | 565,538 | 226,493 |
| with observed mentions | 220,588 | 72,568 | 148,020 | 22,922 | 1,110,961 | 627,512 |
| structured only | 118,317 | 68,878 | 49,439 | 10,878 | 481,766 | 330,288 |

Edges between sessions of different goals (6,258 in the main variant) are dropped from the per-goal graphs; module D4 uses the global graph. Who builds on whom:

| Edges | Scope | Edges | Same agent | Only through local artifacts |
|---|---|---|---|---|
| all | global | 134,301 | 0.654 | 0.531 |
| all | within_goal | 128,043 | 0.648 | 0.523 |
| write | global | 72,461 | 0.726 | 0.612 |
| write | within_goal | 70,590 | 0.722 | 0.607 |
| read | global | 61,840 | 0.57 | 0.436 |
| read | within_goal | 57,453 | 0.558 | 0.418 |

## 5. Graph size per goal

| Goal | Start | End | Sessions | Agents | Touching | Edges | Write | Read | Cross-goal dropped | Layers | Layers (write) | Root share | Isolated share | 2+ parents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G01 | 2025-04-02 | 2025-05-10 | 1,081 | 7 | 208 | 112 | 48 | 64 | 0 | 13 | 13 | 0.906 | 0.884 | 0.0882 | 0.894 | 0.192 |
| G02 | 2025-05-10 | 2025-05-12 | 43 | 4 | 7 | 2 | 0 | 2 | 3 | 2 | 1 | 0.953 | 0.93 | 0 | 0.936 | 0.163 |
| G03 | 2025-05-12 | 2025-05-15 | 56 | 4 | 19 | 4 | 3 | 1 | 12 | 4 | 3 | 0.929 | 0.893 | 0 | 0.705 | 0.339 |
| G04 | 2025-05-15 | 2025-06-19 | 845 | 6 | 215 | 113 | 57 | 56 | 19 | 12 | 10 | 0.879 | 0.85 | 0.108 | 0.844 | 0.254 |
| G05 | 2025-06-19 | 2025-06-26 | 199 | 4 | 32 | 6 | 6 | 0 | 11 | 3 | 3 | 0.97 | 0.945 | 0 | 0.854 | 0.161 |
| G06 | 2025-06-26 | 2025-07-16 | 601 | 4 | 158 | 88 | 43 | 45 | 15 | 14 | 10 | 0.857 | 0.832 | 0.0233 | 0.798 | 0.263 |
| G07 | 2025-07-16 | 2025-07-18 | 88 | 4 | 11 | 0 | 0 | 0 | 7 | 1 | 1 | 1 | 1 |  | 0.876 | 0.125 |
| G08 | 2025-07-18 | 2025-08-13 | 1,060 | 4 | 186 | 104 | 88 | 16 | 23 | 28 | 28 | 0.905 | 0.889 | 0.0297 | 0.797 | 0.175 |
| G09 | 2025-08-13 | 2025-08-18 | 141 | 4 | 55 | 10 | 5 | 5 | 11 | 3 | 3 | 0.929 | 0.894 | 0 | 0.776 | 0.39 |
| G10 | 2025-08-18 | 2025-08-25 | 301 | 7 | 3 | 0 | 0 | 0 | 2 | 1 | 1 | 1 | 1 |  | 0.949 | 0.00997 |
| G11 | 2025-08-25 | 2025-09-01 | 362 | 7 | 52 | 13 | 6 | 7 | 9 | 4 | 3 | 0.967 | 0.948 | 0.0833 | 0.921 | 0.144 |
| G12 | 2025-09-01 | 2025-09-08 | 335 | 7 | 92 | 38 | 17 | 21 | 16 | 7 | 5 | 0.899 | 0.872 | 0.0882 | 0.833 | 0.275 |
| G13 | 2025-09-08 | 2025-09-22 | 656 | 6 | 156 | 61 | 30 | 31 | 38 | 9 | 7 | 0.925 | 0.892 | 0.245 | 0.881 | 0.238 |
| G14 | 2025-09-22 | 2025-09-29 | 330 | 6 | 42 | 10 | 3 | 7 | 9 | 3 | 3 | 0.97 | 0.961 | 0 | 0.906 | 0.127 |
| G15 | 2025-09-29 | 2025-10-06 | 252 | 7 | 46 | 15 | 6 | 9 | 15 | 3 | 3 | 0.94 | 0.909 | 0 | 0.866 | 0.183 |
| G16 | 2025-10-06 | 2025-10-13 | 351 | 7 | 90 | 42 | 17 | 25 | 12 | 10 | 7 | 0.892 | 0.863 | 0.105 | 0.823 | 0.256 |
| G17 | 2025-10-13 | 2025-10-20 | 280 | 7 | 123 | 85 | 34 | 51 | 19 | 13 | 13 | 0.771 | 0.718 | 0.281 | 0.74 | 0.439 |
| G18 | 2025-10-20 | 2025-11-03 | 827 | 8 | 382 | 308 | 103 | 205 | 40 | 19 | 13 | 0.709 | 0.658 | 0.216 | 0.753 | 0.462 |
| G19 | 2025-11-03 | 2025-11-17 | 898 | 8 | 400 | 344 | 155 | 189 | 50 | 57 | 48 | 0.686 | 0.659 | 0.181 | 0.722 | 0.445 |
| G20 | 2025-11-17 | 2025-12-01 | 1,435 | 10 | 605 | 714 | 333 | 381 | 54 | 103 | 62 | 0.714 | 0.691 | 0.462 | 0.705 | 0.422 |
| G21 | 2025-12-01 | 2025-12-08 | 535 | 9 | 236 | 310 | 82 | 228 | 27 | 26 | 14 | 0.753 | 0.69 | 0.394 | 0.756 | 0.441 |
| G22 | 2025-12-08 | 2025-12-15 | 617 | 10 | 282 | 366 | 152 | 214 | 31 | 59 | 26 | 0.72 | 0.661 | 0.514 | 0.623 | 0.457 |
| G23 | 2025-12-15 | 2025-12-22 | 821 | 10 | 467 | 717 | 272 | 445 | 34 | 50 | 24 | 0.618 | 0.557 | 0.548 | 0.517 | 0.569 |
| G24 | 2025-12-22 | 2025-12-29 | 922 | 10 | 321 | 320 | 160 | 160 | 45 | 52 | 14 | 0.809 | 0.777 | 0.438 | 0.726 | 0.348 |
| G25 | 2025-12-29 | 2026-01-05 | 648 | 10 | 431 | 465 | 117 | 348 | 31 | 22 | 15 | 0.568 | 0.523 | 0.357 | 0.651 | 0.665 |
| G26 | 2026-01-05 | 2026-01-12 | 493 | 10 | 316 | 309 | 127 | 182 | 50 | 28 | 12 | 0.6 | 0.531 | 0.371 | 0.444 | 0.641 |
| G27 | 2026-01-12 | 2026-01-26 | 1,750 | 10 | 1,358 | 2,485 | 1,278 | 1,207 | 107 | 143 | 130 | 0.317 | 0.287 | 0.568 | 0.413 | 0.776 |
| G28 | 2026-01-26 | 2026-02-02 | 781 | 11 | 595 | 869 | 425 | 444 | 38 | 112 | 92 | 0.318 | 0.297 | 0.463 | 0.315 | 0.762 |
| G29 | 2026-02-02 | 2026-02-09 | 939 | 12 | 808 | 1,305 | 642 | 663 | 49 | 64 | 62 | 0.286 | 0.249 | 0.507 | 0.331 | 0.86 |
| G30 | 2026-02-09 | 2026-02-16 | 1,265 | 12 | 1,002 | 1,676 | 807 | 869 | 59 | 178 | 130 | 0.297 | 0.279 | 0.534 | 0.21 | 0.792 |
| G31 | 2026-02-16 | 2026-02-23 | 1,292 | 13 | 1,065 | 2,202 | 1,161 | 1,041 | 207 | 181 | 147 | 0.248 | 0.222 | 0.612 | 0.221 | 0.824 |
| G32 | 2026-02-23 | 2026-03-02 | 1,371 | 12 | 1,174 | 2,364 | 1,297 | 1,067 | 158 | 209 | 157 | 0.194 | 0.172 | 0.699 | 0.236 | 0.856 |
| G33 | 2026-03-02 | 2026-03-05 | 797 | 12 | 704 | 1,229 | 862 | 367 | 55 | 162 | 130 | 0.193 | 0.156 | 0.711 | 0.194 | 0.883 |
| G34 | 2026-03-05 | 2026-03-16 | 1,834 | 13 | 1,650 | 3,012 | 1,834 | 1,178 | 44 | 305 | 271 | 0.131 | 0.122 | 0.741 | 0.14 | 0.9 |
| G35 | 2026-03-16 | 2026-03-23 | 1,357 | 13 | 944 | 1,470 | 931 | 539 | 59 | 144 | 128 | 0.338 | 0.324 | 0.558 | 0.289 | 0.696 |
| G36 | 2026-03-23 | 2026-03-30 | 1,227 | 13 | 1,051 | 2,817 | 1,374 | 1,443 | 86 | 196 | 165 | 0.263 | 0.231 | 0.692 | 0.13 | 0.857 |
| G37 | 2026-03-30 | 2026-04-02 | 551 | 12 | 448 | 826 | 343 | 483 | 226 | 59 | 49 | 0.29 | 0.252 | 0.542 | 0.21 | 0.813 |
| G38 | 2026-04-02 | 2026-04-27 | 3,182 | 14 | 2,293 | 7,672 | 3,400 | 4,272 | 502 | 366 | 299 | 0.34 | 0.317 | 0.761 | 0.166 | 0.721 |
| G39 | 2026-04-27 | 2026-05-04 | 990 | 15 | 913 | 1,368 | 991 | 377 | 76 | 98 | 88 | 0.116 | 0.0949 | 0.367 | 0.105 | 0.922 |
| G40 | 2026-05-04 | 2026-05-11 | 1,110 | 15 | 963 | 1,683 | 1,379 | 304 | 68 | 190 | 186 | 0.187 | 0.173 | 0.715 | 0.0467 | 0.868 |
| G41 | 2026-05-11 | 2026-05-18 | 1,014 | 15 | 897 | 1,798 | 1,182 | 616 | 165 | 123 | 105 | 0.166 | 0.145 | 0.681 | 0.106 | 0.885 |
| G42 | 2026-05-18 | 2026-05-25 | 1,221 | 16 | 997 | 1,610 | 1,074 | 536 | 111 | 117 | 111 | 0.283 | 0.258 | 0.462 | 0.248 | 0.817 |
| G43 | 2026-05-25 | 2026-05-26 | 307 | 16 | 270 | 447 | 285 | 162 | 47 | 36 | 32 | 0.182 | 0.137 | 0.462 | 0.0971 | 0.879 |
| G44 | 2026-05-26 | 2026-06-01 | 774 | 18 | 658 | 1,465 | 847 | 618 | 230 | 88 | 77 | 0.202 | 0.177 | 0.707 | 0.11 | 0.85 |
| G45 | 2026-06-01 | 2026-06-08 | 1,063 | 18 | 926 | 2,016 | 1,111 | 905 | 273 | 98 | 92 | 0.168 | 0.15 | 0.744 | 0.118 | 0.871 |
| G46 | 2026-06-08 | 2026-06-15 | 2,836 | 18 | 2,101 | 4,731 | 1,876 | 2,855 | 473 | 272 | 260 | 0.304 | 0.292 | 0.713 | 0.196 | 0.741 |
| G47 | 2026-06-15 | 2026-06-22 | 1,361 | 17 | 877 | 1,733 | 735 | 998 | 337 | 92 | 82 | 0.464 | 0.444 | 0.698 | 0.506 | 0.644 |
| G48 | 2026-06-22 | 2026-06-23 | 260 | 17 | 144 | 152 | 83 | 69 | 201 | 12 | 11 | 0.638 | 0.565 | 0.436 | 0.24 | 0.554 |
| G49 | 2026-06-23 | 2026-06-29 | 1,057 | 17 | 242 | 191 | 95 | 96 | 156 | 33 | 29 | 0.863 | 0.847 | 0.221 | 0.893 | 0.229 |
| G50 | 2026-06-29 | 2026-07-06 | 2,975 | 21 | 1,509 | 2,039 | 1,346 | 693 | 550 | 278 | 253 | 0.668 | 0.653 | 0.672 | 0.73 | 0.507 |
| G51 | 2026-07-06 | open | 32,871 | 32 | 25,832 | 76,327 | 43,368 | 32,959 | 1,398 | 3,712 | 3,258 | 0.271 | 0.259 | 0.797 | 0.163 | 0.786 |

Goals before about 2025-10 have few touching sessions: most of their work was GUI work without a focus (section 2). The open goal G51 (from 2026-07-06) holds most sessions and edges, so pooled statistics lean on it; the median over goals weights goals equally.

## 6. Structure against the generator (D3)

Generator: `grow_dag` with the blog's parameters (17 layers, layer peak at 28% depth, merge probability 0.46, no task variation, seed 20261003), 64 DAGs per goal with the goal's session count. Statistics are computed the same way on both sides (`avsd.swarmsim.depgraph`): parent counts over nodes with at least one parent, the sibling share over nodes with at least two parents (two parents are siblings when they share a parent), out-degree inequality over nodes with at least one child, and the cross-layer share over edges spanning two or more layers after relayering (each node one below its deepest parent). Pooled rows join the counts of all goal graphs; the generator side pools one DAG per goal per replicate. The quantile is the share of generator values below the observed value (ties count half). The generator has one root by construction, while 30,474 AI Village sessions have no parent.

| Edges | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | Nodes with parents | Nodes with 2+ parents |
|---|---|---|---|---|---|---|---|---|
| all | multi_parent_share | 0.7 | 0.423 | 0.415 | 0.43 | 1 | 47,888 | 33,511 |
| all | mean_parents | 2.67 | 1.74 | 1.73 | 1.75 | 1 | 47,888 | 33,511 |
| all | sibling_merge_share | 0.443 | 0.417 | 0.401 | 0.443 | 0.969 | 47,888 | 33,511 |
| all | outdeg_gini | 0.494 | 0.534 | 0.527 | 0.542 | 0 | 47,888 | 33,511 |
| all | top10_child_share | 0.401 | 0.445 | 0.437 | 0.455 | 0 | 47,888 | 33,511 |
| all | cross_layer_share | 0.601 | 0.198 | 0.189 | 0.204 | 1 | 47,888 | 33,511 |
| write | multi_parent_share | 0.551 | 0.423 | 0.415 | 0.43 | 1 | 37,033 | 20,413 |
| write | mean_parents | 1.91 | 1.74 | 1.73 | 1.75 | 1 | 37,033 | 20,413 |
| write | sibling_merge_share | 0.222 | 0.417 | 0.401 | 0.443 | 0 | 37,033 | 20,413 |
| write | outdeg_gini | 0.35 | 0.534 | 0.527 | 0.542 | 0 | 37,033 | 20,413 |
| write | top10_child_share | 0.29 | 0.445 | 0.437 | 0.455 | 0 | 37,033 | 20,413 |
| write | cross_layer_share | 0.45 | 0.198 | 0.189 | 0.204 | 1 | 37,033 | 20,413 |
| read | multi_parent_share | 0.467 | 0.423 | 0.415 | 0.43 | 1 | 30,358 | 14,168 |
| read | mean_parents | 1.89 | 1.74 | 1.73 | 1.75 | 1 | 30,358 | 14,168 |
| read | sibling_merge_share | 0.161 | 0.417 | 0.401 | 0.443 | 0 | 30,358 | 14,168 |
| read | outdeg_gini | 0.56 | 0.534 | 0.527 | 0.542 | 1 | 30,358 | 14,168 |
| read | top10_child_share | 0.504 | 0.445 | 0.437 | 0.455 | 1 | 30,358 | 14,168 |
| read | cross_layer_share | 0.418 | 0.198 | 0.189 | 0.204 | 1 | 30,358 | 14,168 |

Parent-count distribution (share of nodes with at least one parent):

| Edges | Parents | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | Nodes with parents |
|---|---|---|---|---|---|---|---|
| all | 1 | 0.3 | 0.577 | 0.57 | 0.585 | 0 | 47,888 |
| all | 2 | 0.299 | 0.3 | 0.294 | 0.305 | 0.344 | 47,888 |
| all | 3 | 0.164 | 0.0607 | 0.0587 | 0.063 | 1 | 47,888 |
| all | 4+ | 0.237 | 0.0621 | 0.0599 | 0.0637 | 1 | 47,888 |
| write | 1 | 0.449 | 0.577 | 0.57 | 0.585 | 0 | 37,033 |
| write | 2 | 0.351 | 0.3 | 0.294 | 0.305 | 1 | 37,033 |
| write | 3 | 0.12 | 0.0607 | 0.0587 | 0.063 | 1 | 37,033 |
| write | 4+ | 0.0803 | 0.0621 | 0.0599 | 0.0637 | 1 | 37,033 |
| read | 1 | 0.533 | 0.577 | 0.57 | 0.585 | 0 | 30,358 |
| read | 2 | 0.244 | 0.3 | 0.294 | 0.305 | 0 | 30,358 |
| read | 3 | 0.116 | 0.0607 | 0.0587 | 0.063 | 1 | 30,358 |
| read | 4+ | 0.107 | 0.0621 | 0.0599 | 0.0637 | 1 | 30,358 |

Median over goals (each goal weighted equally; the generator value of a replicate is the median over goals of that replicate's DAGs):

| Edges | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | Goals |
|---|---|---|---|---|---|---|---|
| all | multi_parent_share | 0.462 | 0.423 | 0.415 | 0.427 | 1 | 49 |
| all | mean_parents | 1.74 | 1.73 | 1.72 | 1.74 | 0.875 | 49 |
| all | sibling_merge_share | 0.315 | 0.441 | 0.429 | 0.454 | 0 | 43 |
| all | outdeg_gini | 0.4 | 0.511 | 0.505 | 0.517 | 0 | 49 |
| all | top10_child_share | 0.341 | 0.42 | 0.412 | 0.427 | 0 | 49 |
| all | cross_layer_share | 0.4 | 0.189 | 0.184 | 0.194 | 1 | 49 |
| write | multi_parent_share | 0.263 | 0.423 | 0.415 | 0.428 | 0 | 48 |
| write | mean_parents | 1.35 | 1.73 | 1.72 | 1.74 | 0 | 48 |
| write | sibling_merge_share | 0.169 | 0.439 | 0.425 | 0.454 | 0 | 39 |
| write | outdeg_gini | 0.257 | 0.511 | 0.506 | 0.517 | 0 | 48 |
| write | top10_child_share | 0.236 | 0.421 | 0.413 | 0.428 | 0 | 48 |
| write | cross_layer_share | 0.23 | 0.189 | 0.185 | 0.194 | 1 | 48 |
| read | multi_parent_share | 0.28 | 0.423 | 0.415 | 0.427 | 0 | 48 |
| read | mean_parents | 1.37 | 1.73 | 1.72 | 1.74 | 0 | 48 |
| read | sibling_merge_share | 0.0687 | 0.44 | 0.425 | 0.455 | 0 | 39 |
| read | outdeg_gini | 0.404 | 0.511 | 0.506 | 0.517 | 0 | 48 |
| read | top10_child_share | 0.368 | 0.421 | 0.413 | 0.427 | 0 | 48 |
| read | cross_layer_share | 0.201 | 0.189 | 0.184 | 0.194 | 1 | 48 |

Single goals: number of goal graphs whose value lies below the generator's 2.5% point or above its 97.5% point (undefined where the goal graph has no qualifying node or edge):

| Edges | Statistic | Below 2.5% | Above 97.5% | Inside | Undefined |
|---|---|---|---|---|---|
| all | cross_layer_share | 14 | 34 | 3 | 2 |
| all | mean_parents | 21 | 24 | 6 | 2 |
| all | multi_parent_share | 21 | 26 | 4 | 2 |
| all | outdeg_gini | 44 | 5 | 2 | 2 |
| all | sibling_merge_share | 27 | 16 | 8 | 8 |
| all | top10_child_share | 27 | 6 | 18 | 2 |
| read | cross_layer_share | 22 | 25 | 4 | 3 |
| read | mean_parents | 36 | 11 | 4 | 3 |
| read | multi_parent_share | 36 | 10 | 5 | 3 |
| read | outdeg_gini | 35 | 6 | 10 | 3 |
| read | sibling_merge_share | 36 | 12 | 3 | 12 |
| read | top10_child_share | 24 | 12 | 15 | 3 |
| write | cross_layer_share | 17 | 29 | 5 | 3 |
| write | mean_parents | 41 | 6 | 4 | 3 |
| write | multi_parent_share | 33 | 14 | 4 | 3 |
| write | outdeg_gini | 48 | 3 | 0 | 3 |
| write | sibling_merge_share | 38 | 12 | 1 | 12 |
| write | top10_child_share | 45 | 3 | 3 | 3 |

Sensitivity (pooled): other generator sizes (connected sessions only; depth matched to the goal graph's layer count), exact-key matching, observed and mentioned identifiers counted as reads, and structured artifacts only (no plain URLs).

| Variant | Edges | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile |
|---|---|---|---|---|---|---|---|
| generator at connected-node count | all | multi_parent_share | 0.7 | 0.424 | 0.409 | 0.433 | 1 |
| generator at connected-node count | all | mean_parents | 2.67 | 1.74 | 1.71 | 1.76 | 1 |
| generator at connected-node count | all | sibling_merge_share | 0.443 | 0.42 | 0.397 | 0.444 | 0.953 |
| generator at connected-node count | all | outdeg_gini | 0.494 | 0.531 | 0.523 | 0.544 | 0 |
| generator at connected-node count | all | top10_child_share | 0.401 | 0.442 | 0.432 | 0.457 | 0 |
| generator at connected-node count | all | cross_layer_share | 0.601 | 0.197 | 0.188 | 0.207 | 1 |
| generator at connected-node count | write | multi_parent_share | 0.551 | 0.424 | 0.409 | 0.433 | 1 |
| generator at connected-node count | write | mean_parents | 1.91 | 1.74 | 1.71 | 1.76 | 1 |
| generator at connected-node count | write | sibling_merge_share | 0.222 | 0.42 | 0.397 | 0.444 | 0 |
| generator at connected-node count | write | outdeg_gini | 0.35 | 0.531 | 0.523 | 0.544 | 0 |
| generator at connected-node count | write | top10_child_share | 0.29 | 0.442 | 0.432 | 0.457 | 0 |
| generator at connected-node count | write | cross_layer_share | 0.45 | 0.197 | 0.188 | 0.207 | 1 |
| generator with depth matched to the goal graph | all | multi_parent_share | 0.7 | 0.437 | 0.434 | 0.44 | 1 |
| generator with depth matched to the goal graph | all | mean_parents | 2.67 | 1.73 | 1.72 | 1.74 | 1 |
| generator with depth matched to the goal graph | all | sibling_merge_share | 0.443 | 0.441 | 0.435 | 0.449 | 0.656 |
| generator with depth matched to the goal graph | all | outdeg_gini | 0.494 | 0.425 | 0.423 | 0.427 | 1 |
| generator with depth matched to the goal graph | all | top10_child_share | 0.401 | 0.328 | 0.326 | 0.33 | 1 |
| generator with depth matched to the goal graph | all | cross_layer_share | 0.601 | 0.23 | 0.227 | 0.233 | 1 |
| generator with depth matched to the goal graph | write | multi_parent_share | 0.551 | 0.437 | 0.434 | 0.44 | 1 |
| generator with depth matched to the goal graph | write | mean_parents | 1.91 | 1.73 | 1.72 | 1.74 | 1 |
| generator with depth matched to the goal graph | write | sibling_merge_share | 0.222 | 0.441 | 0.435 | 0.449 | 0 |
| generator with depth matched to the goal graph | write | outdeg_gini | 0.35 | 0.425 | 0.423 | 0.427 | 0 |
| generator with depth matched to the goal graph | write | top10_child_share | 0.29 | 0.328 | 0.326 | 0.33 | 0 |
| generator with depth matched to the goal graph | write | cross_layer_share | 0.45 | 0.23 | 0.227 | 0.233 | 1 |
| exact keys | all | multi_parent_share | 0.72 | 0.423 | 0.415 | 0.43 | 1 |
| exact keys | all | mean_parents | 3.08 | 1.74 | 1.73 | 1.75 | 1 |
| exact keys | all | sibling_merge_share | 0.531 | 0.417 | 0.401 | 0.443 | 1 |
| exact keys | all | outdeg_gini | 0.527 | 0.534 | 0.527 | 0.542 | 0.0469 |
| exact keys | all | top10_child_share | 0.435 | 0.445 | 0.437 | 0.455 | 0 |
| exact keys | all | cross_layer_share | 0.655 | 0.198 | 0.189 | 0.204 | 1 |
| exact keys | write | multi_parent_share | 0.577 | 0.423 | 0.415 | 0.43 | 1 |
| exact keys | write | mean_parents | 2.11 | 1.74 | 1.73 | 1.75 | 1 |
| exact keys | write | sibling_merge_share | 0.284 | 0.417 | 0.401 | 0.443 | 0 |
| exact keys | write | outdeg_gini | 0.349 | 0.534 | 0.527 | 0.542 | 0 |
| exact keys | write | top10_child_share | 0.269 | 0.445 | 0.437 | 0.455 | 0 |
| exact keys | write | cross_layer_share | 0.503 | 0.198 | 0.189 | 0.204 | 1 |
| with observed mentions | all | multi_parent_share | 0.74 | 0.423 | 0.415 | 0.43 | 1 |
| with observed mentions | all | mean_parents | 3.63 | 1.74 | 1.73 | 1.75 | 1 |
| with observed mentions | all | sibling_merge_share | 0.581 | 0.417 | 0.401 | 0.443 | 1 |
| with observed mentions | all | outdeg_gini | 0.569 | 0.534 | 0.527 | 0.542 | 1 |
| with observed mentions | all | top10_child_share | 0.47 | 0.445 | 0.437 | 0.455 | 1 |
| with observed mentions | all | cross_layer_share | 0.704 | 0.198 | 0.189 | 0.204 | 1 |
| with observed mentions | write | multi_parent_share | 0.552 | 0.423 | 0.415 | 0.43 | 1 |
| with observed mentions | write | mean_parents | 1.91 | 1.74 | 1.73 | 1.75 | 1 |
| with observed mentions | write | sibling_merge_share | 0.223 | 0.417 | 0.401 | 0.443 | 0 |
| with observed mentions | write | outdeg_gini | 0.351 | 0.534 | 0.527 | 0.542 | 0 |
| with observed mentions | write | top10_child_share | 0.29 | 0.445 | 0.437 | 0.455 | 0 |
| with observed mentions | write | cross_layer_share | 0.451 | 0.198 | 0.189 | 0.204 | 1 |
| structured only | all | multi_parent_share | 0.691 | 0.423 | 0.415 | 0.43 | 1 |
| structured only | all | mean_parents | 2.46 | 1.74 | 1.73 | 1.75 | 1 |
| structured only | all | sibling_merge_share | 0.397 | 0.417 | 0.401 | 0.443 | 0.0156 |
| structured only | all | outdeg_gini | 0.462 | 0.534 | 0.527 | 0.542 | 0 |
| structured only | all | top10_child_share | 0.367 | 0.445 | 0.437 | 0.455 | 0 |
| structured only | all | cross_layer_share | 0.566 | 0.198 | 0.189 | 0.204 | 1 |
| structured only | write | multi_parent_share | 0.547 | 0.423 | 0.415 | 0.43 | 1 |
| structured only | write | mean_parents | 1.87 | 1.74 | 1.73 | 1.75 | 1 |
| structured only | write | sibling_merge_share | 0.208 | 0.417 | 0.401 | 0.443 | 0 |
| structured only | write | outdeg_gini | 0.345 | 0.534 | 0.527 | 0.542 | 0 |
| structured only | write | top10_child_share | 0.289 | 0.445 | 0.437 | 0.455 | 0 |
| structured only | write | cross_layer_share | 0.439 | 0.198 | 0.189 | 0.204 | 1 |

## 7. Step cost by layer

Each session's turns and active minutes are divided by the mean of the layer-0 sessions of its goal. The blog sets the cost of a step at depth d to c_d = 1 + 9 d / (D - 1), ten times the root's at the deepest layer; `blog` gives that ratio for the sessions in each bin. CIs come from a bootstrap over goals.

| Axis | Bin | Sessions | Goals | Turns | Turns vs layer 0 | CI low | CI high | Active min | Active vs layer 0 | CI low | CI high | Blog |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| layer | 0 | 30,226 | 51 | 31.9 | 1 | 1 | 1 | 12 | 1 | 1 | 1 | 1 |
| layer | 1 | 1,610 | 49 | 32.4 | 1.03 | 0.967 | 1.08 | 11.1 | 0.967 | 0.913 | 1.04 | 1.34 |
| layer | 2 | 818 | 48 | 33.2 | 1.06 | 0.989 | 1.11 | 11.6 | 1.05 | 0.921 | 1.23 | 1.55 |
| layer | 3-4 | 1,168 | 44 | 33.4 | 1.06 | 0.999 | 1.12 | 12 | 1.06 | 0.976 | 1.16 | 1.7 |
| layer | 5-8 | 1,475 | 42 | 33.1 | 1.04 | 0.983 | 1.09 | 11.7 | 1.05 | 0.94 | 1.15 | 2.19 |
| layer | 9-16 | 1,987 | 40 | 31.8 | 0.997 | 0.947 | 1.05 | 11 | 0.976 | 0.884 | 1.06 | 2.65 |
| layer | 17-32 | 3,022 | 34 | 31.8 | 1.01 | 0.95 | 1.08 | 11.3 | 0.995 | 0.881 | 1.09 | 3.16 |
| layer | 33-64 | 4,821 | 28 | 31.6 | 0.992 | 0.932 | 1.05 | 11.1 | 0.955 | 0.886 | 1.02 | 4.39 |
| layer | 65+ | 32,987 | 21 | 32.4 | 1.04 | 0.936 | 1.07 | 13.5 | 0.958 | 0.888 | 1.03 | 6.01 |
| relative_depth | 0 | 30,226 | 51 | 31.9 | 1 | 1 | 1 | 12 | 1 | 1 | 1 | 1 |
| relative_depth | (0, 0.2] | 12,777 | 42 | 32.7 | 1.05 | 0.967 | 1.09 | 11.3 | 0.908 | 0.815 | 1.09 | 1.77 |
| relative_depth | (0.2, 0.4] | 9,775 | 44 | 31.3 | 1 | 0.938 | 1.03 | 11.8 | 0.907 | 0.842 | 1.06 | 3.68 |
| relative_depth | (0.4, 0.6] | 8,670 | 46 | 32.4 | 1.03 | 0.938 | 1.07 | 12.9 | 0.976 | 0.909 | 1.11 | 5.49 |
| relative_depth | (0.6, 0.8] | 8,227 | 44 | 33 | 1.05 | 0.944 | 1.1 | 12.6 | 0.937 | 0.853 | 0.981 | 7.31 |
| relative_depth | (0.8, 1] | 8,439 | 49 | 32.1 | 1.03 | 0.906 | 1.07 | 16.3 | 1.15 | 0.856 | 1.25 | 9.06 |

Within-goal least-squares slope of relative cost on relative depth d / (D - 1) (the blog's slope is 9):

| Edges | Cost | Slope | CI low | CI high | Sessions | Goals |
|---|---|---|---|---|---|---|
| all | turns | 0.0208 | -0.0994 | 0.0645 | 77,725 | 49 |
| all | active_min | 0.151 | -0.118 | 0.254 | 77,725 | 49 |
| write | turns | 0.157 | 0.0636 | 0.234 | 77,682 | 48 |
| write | active_min | 0.258 | -0.029 | 0.34 | 77,682 | 48 |

The write-edge table is in depgraph_cost_by_layer.csv.

## 8. Continuation (D4)

For each pair of consecutive sessions (p, n) of one agent, the indicator is 1 when p is among n's parents in the global graph. `with_parents` keeps pairs whose n has a parent; `all_pairs` keeps every pair. The baseline draws n's parented containers at random from the containers written before n started in the same goal (`goal`) or run day (`day`), shared ones by anyone and local ones by the agent itself; `own_work` restricts the pool to containers last written by the agent and the draws to n's containers with an own parent. 95% CIs from 2,000 bootstrap replicates over agents. Strata: all pairs and the two computer-use regimes (`regime_cu`, before and after the switch to continuous computer use).

| Window | Measure | Stratum | Rate | CI low | CI high | Baseline | CI low | CI high | Ratio | CI low | CI high | Pairs | Agents | Median pool |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| goal | with_parents | all | 0.599 | 0.529 | 0.673 | 0.0615 | 0.0488 | 0.075 | 9.75 | 7.75 | 12.5 | 49,112 | 45 | 345 |
| goal | all_pairs | all | 0.376 | 0.3 | 0.479 | 0.0385 | 0.0292 | 0.0499 | 9.75 | 6.87 | 14.2 | 78,316 | 46 | 136 |
| goal | own_work | all | 0.658 | 0.599 | 0.722 | 0.104 | 0.0865 | 0.122 | 6.35 | 5.27 | 7.77 | 44,714 | 45 | 128 |
| day | with_parents | all | 0.599 | 0.531 | 0.672 | 0.243 | 0.21 | 0.283 | 2.47 | 2.03 | 2.98 | 49,112 | 45 | 25 |
| day | all_pairs | all | 0.376 | 0.297 | 0.476 | 0.152 | 0.121 | 0.197 | 2.47 | 1.75 | 3.42 | 78,316 | 46 | 18 |
| day | own_work | all | 0.658 | 0.598 | 0.724 | 0.391 | 0.36 | 0.427 | 1.68 | 1.47 | 1.91 | 44,714 | 45 | 9 |
| goal | with_parents | regime_pre | 0.42 | 0.322 | 0.514 | 0.0927 | 0.0736 | 0.11 | 4.53 | 3.29 | 6.21 | 12,086 | 23 | 35 |
| goal | all_pairs | regime_pre | 0.196 | 0.117 | 0.299 | 0.0432 | 0.0271 | 0.0646 | 4.53 | 2.39 | 8.55 | 25,957 | 24 | 25 |
| goal | own_work | regime_pre | 0.501 | 0.403 | 0.587 | 0.133 | 0.114 | 0.15 | 3.77 | 2.93 | 4.75 | 10,146 | 23 | 19 |
| day | with_parents | regime_pre | 0.42 | 0.323 | 0.513 | 0.225 | 0.182 | 0.269 | 1.87 | 1.37 | 2.49 | 12,086 | 23 | 8 |
| day | all_pairs | regime_pre | 0.196 | 0.124 | 0.303 | 0.105 | 0.0684 | 0.156 | 1.87 | 1.03 | 3.49 | 25,957 | 24 | 5 |
| day | own_work | regime_pre | 0.501 | 0.405 | 0.589 | 0.316 | 0.272 | 0.357 | 1.59 | 1.24 | 2.01 | 10,146 | 23 | 4 |
| goal | with_parents | regime_post | 0.657 | 0.588 | 0.731 | 0.0513 | 0.0384 | 0.0655 | 12.8 | 9.75 | 17.4 | 37,024 | 34 | 909 |
| goal | all_pairs | regime_post | 0.465 | 0.379 | 0.571 | 0.0362 | 0.0272 | 0.0478 | 12.8 | 9.12 | 18 | 52,352 | 34 | 811 |
| goal | own_work | regime_post | 0.704 | 0.634 | 0.772 | 0.0951 | 0.0763 | 0.117 | 7.4 | 5.86 | 9.39 | 34,567 | 34 | 250 |
| day | with_parents | regime_post | 0.657 | 0.584 | 0.734 | 0.248 | 0.207 | 0.301 | 2.65 | 2.14 | 3.27 | 37,024 | 34 | 33 |
| day | all_pairs | regime_post | 0.465 | 0.38 | 0.568 | 0.176 | 0.138 | 0.225 | 2.65 | 1.9 | 3.71 | 52,352 | 34 | 29 |
| day | own_work | regime_post | 0.704 | 0.635 | 0.773 | 0.413 | 0.373 | 0.456 | 1.71 | 1.48 | 1.95 | 34,567 | 34 | 11 |

With write edges only (the parent link must come through an artifact the next session also writes):

| Window | Measure | Rate | CI low | CI high | Baseline | CI low | CI high | Pairs | Agents |
|---|---|---|---|---|---|---|---|---|---|
| goal | with_parents | 0.654 | 0.59 | 0.723 | 0.0541 | 0.0423 | 0.067 | 37,766 | 45 |
| goal | all_pairs | 0.315 | 0.248 | 0.403 | 0.0261 | 0.0192 | 0.0343 | 78,316 | 46 |
| goal | own_work | 0.694 | 0.635 | 0.757 | 0.098 | 0.0795 | 0.117 | 35,568 | 45 |
| day | with_parents | 0.654 | 0.59 | 0.721 | 0.223 | 0.194 | 0.26 | 37,766 | 45 |
| day | all_pairs | 0.315 | 0.246 | 0.403 | 0.108 | 0.0814 | 0.144 | 78,316 | 46 |
| day | own_work | 0.694 | 0.637 | 0.754 | 0.382 | 0.352 | 0.414 | 35,568 | 45 |

## 8b. Robustness to the GUI focus gap

GUI writes without a focus are actions the graph cannot see. Per goal, `gap` is the share of write actions that are GUI writes without a focus (unattributed GUI writes over those plus turns with a write touch on an artifact), and `touch share` the share of sessions that touch an artifact. The pooled D3 statistics with their generator quantiles (the generator pools the same goals' DAGs), the within-goal step-cost slopes and the D4 rates with their baselines are recomputed on each subset of goals (D4: pairs whose next session belongs to the subset). CIs: goal bootstrap for slopes, agent bootstrap for D4; n is nodes with a parent (D3), sessions (cost) or pairs (D4).

| Subset | Definition | Goals | Sessions |
|---|---|---|---|
| full | all goals | 51 | 78,362 |
| gap < 20% | goals whose unattributed GUI writes are under 20% of write actions | 12 | 48,005 |
| gap < 10% | goals whose unattributed GUI writes are under 10% of write actions | 2 | 1,417 |
| touch share >= 80% | goals where at least 80% of sessions touch an artifact | 14 | 14,490 |
| from 2025-10 | goals starting on or after 2025-10-01 | 36 | 72,012 |
| no GUI-heavy early goals | all goals except those before 2025-10 with a gap of at least 80% | 40 | 73,870 |

Gap by goal: median 0.623 (goals before 2025-10: median 0.866; from 2025-10: median 0.269); touch share: median 0.554.

D3, all edges (AI Village value, generator mean and 95% range, quantile):

| Subset | Statistic | AI Village | Generator mean | Generator 2.5% | Generator 97.5% | Quantile | n |
|---|---|---|---|---|---|---|---|
| full | multi_parent_share | 0.7 | 0.423 | 0.415 | 0.43 | 1 | 47,888 |
| full | mean_parents | 2.67 | 1.74 | 1.73 | 1.75 | 1 | 47,888 |
| full | sibling_merge_share | 0.443 | 0.417 | 0.401 | 0.443 | 0.969 | 47,888 |
| full | outdeg_gini | 0.494 | 0.534 | 0.527 | 0.542 | 0 | 47,888 |
| full | top10_child_share | 0.401 | 0.445 | 0.437 | 0.455 | 0 | 47,888 |
| full | cross_layer_share | 0.601 | 0.198 | 0.189 | 0.204 | 1 | 47,888 |
| gap < 20% | multi_parent_share | 0.763 | 0.423 | 0.41 | 0.435 | 1 | 35,564 |
| gap < 20% | mean_parents | 2.94 | 1.74 | 1.72 | 1.77 | 1 | 35,564 |
| gap < 20% | sibling_merge_share | 0.464 | 0.399 | 0.373 | 0.439 | 1 | 35,564 |
| gap < 20% | outdeg_gini | 0.502 | 0.545 | 0.536 | 0.556 | 0 | 35,564 |
| gap < 20% | top10_child_share | 0.409 | 0.458 | 0.448 | 0.472 | 0 | 35,564 |
| gap < 20% | cross_layer_share | 0.634 | 0.203 | 0.19 | 0.213 | 1 | 35,564 |
| gap < 10% | multi_parent_share | 0.66 | 0.426 | 0.39 | 0.455 | 1 | 1,153 |
| gap < 10% | mean_parents | 1.85 | 1.73 | 1.63 | 1.8 | 1 | 1,153 |
| gap < 10% | sibling_merge_share | 0.267 | 0.452 | 0.385 | 0.504 | 0 | 1,153 |
| gap < 10% | outdeg_gini | 0.37 | 0.509 | 0.481 | 0.54 | 0 | 1,153 |
| gap < 10% | top10_child_share | 0.304 | 0.417 | 0.383 | 0.447 | 0 | 1,153 |
| gap < 10% | cross_layer_share | 0.403 | 0.187 | 0.167 | 0.211 | 1 | 1,153 |
| touch share >= 80% | multi_parent_share | 0.637 | 0.423 | 0.414 | 0.433 | 1 | 11,528 |
| touch share >= 80% | mean_parents | 2.09 | 1.73 | 1.71 | 1.76 | 1 | 11,528 |
| touch share >= 80% | sibling_merge_share | 0.353 | 0.438 | 0.42 | 0.455 | 0 | 11,528 |
| touch share >= 80% | outdeg_gini | 0.427 | 0.52 | 0.512 | 0.527 | 0 | 11,528 |
| touch share >= 80% | top10_child_share | 0.338 | 0.428 | 0.418 | 0.437 | 0 | 11,528 |
| touch share >= 80% | cross_layer_share | 0.485 | 0.192 | 0.186 | 0.198 | 1 | 11,528 |
| from 2025-10 | multi_parent_share | 0.707 | 0.423 | 0.415 | 0.431 | 1 | 47,355 |
| from 2025-10 | mean_parents | 2.69 | 1.74 | 1.73 | 1.76 | 1 | 47,355 |
| from 2025-10 | sibling_merge_share | 0.443 | 0.412 | 0.395 | 0.44 | 0.969 | 47,355 |
| from 2025-10 | outdeg_gini | 0.494 | 0.537 | 0.53 | 0.545 | 0 | 47,355 |
| from 2025-10 | top10_child_share | 0.401 | 0.448 | 0.44 | 0.459 | 0 | 47,355 |
| from 2025-10 | cross_layer_share | 0.603 | 0.199 | 0.189 | 0.206 | 1 | 47,355 |
| no GUI-heavy early goals | multi_parent_share | 0.704 | 0.423 | 0.415 | 0.43 | 1 | 47,556 |
| no GUI-heavy early goals | mean_parents | 2.68 | 1.74 | 1.73 | 1.76 | 1 | 47,556 |
| no GUI-heavy early goals | sibling_merge_share | 0.443 | 0.413 | 0.396 | 0.441 | 0.969 | 47,556 |
| no GUI-heavy early goals | outdeg_gini | 0.494 | 0.536 | 0.529 | 0.544 | 0 | 47,556 |
| no GUI-heavy early goals | top10_child_share | 0.401 | 0.447 | 0.439 | 0.458 | 0 | 47,556 |
| no GUI-heavy early goals | cross_layer_share | 0.602 | 0.199 | 0.189 | 0.206 | 1 | 47,556 |

Step cost, within-goal slope of relative cost on relative depth (blog: 9):

| Subset | Cost | Slope | CI low | CI high | Sessions |
|---|---|---|---|---|---|
| full | slope of turns | 0.0208 | -0.103 | 0.0641 | 77,725 |
| full | slope of active_min | 0.151 | -0.13 | 0.251 | 77,725 |
| gap < 20% | slope of turns | 0.0477 | -0.0975 | 0.0797 | 47,900 |
| gap < 20% | slope of active_min | 0.21 | -0.15 | 0.286 | 47,900 |
| gap < 10% | slope of turns | 0.00847 | -0.141 | 0.0438 | 1,417 |
| gap < 10% | slope of active_min | -0.222 | -0.346 | -0.193 | 1,417 |
| touch share >= 80% | slope of turns | -0.0156 | -0.107 | 0.0646 | 14,404 |
| touch share >= 80% | slope of active_min | -0.134 | -0.234 | -0.0357 | 14,404 |
| from 2025-10 | slope of turns | 0.02 | -0.112 | 0.0639 | 71,769 |
| from 2025-10 | slope of active_min | 0.149 | -0.147 | 0.255 | 71,769 |
| no GUI-heavy early goals | slope of turns | 0.0204 | -0.106 | 0.064 | 73,627 |
| no GUI-heavy early goals | slope of active_min | 0.151 | -0.135 | 0.255 | 73,627 |

D4, continuation (all edges):

| Subset | Measure | Window | Rate | CI low | CI high | Baseline | CI low | CI high | Pairs | Agents |
|---|---|---|---|---|---|---|---|---|---|---|
| full | with_parents | goal | 0.599 | 0.53 | 0.671 | 0.0615 | 0.0494 | 0.0745 | 49,112 | 45 |
| full | all_pairs | goal | 0.376 | 0.301 | 0.47 | 0.0385 | 0.0284 | 0.0493 | 78,316 | 46 |
| full | with_parents | day | 0.599 | 0.533 | 0.67 | 0.243 | 0.208 | 0.283 | 49,112 | 45 |
| full | all_pairs | day | 0.376 | 0.298 | 0.469 | 0.152 | 0.12 | 0.199 | 78,316 | 46 |
| gap < 20% | with_parents | goal | 0.659 | 0.58 | 0.737 | 0.0497 | 0.0372 | 0.0658 | 35,917 | 36 |
| gap < 20% | all_pairs | goal | 0.494 | 0.403 | 0.606 | 0.0372 | 0.0275 | 0.0483 | 47,986 | 36 |
| gap < 20% | with_parents | day | 0.659 | 0.582 | 0.733 | 0.252 | 0.214 | 0.304 | 35,917 | 36 |
| gap < 20% | all_pairs | day | 0.494 | 0.406 | 0.6 | 0.189 | 0.15 | 0.242 | 47,986 | 36 |
| gap < 10% | with_parents | goal | 0.792 | 0.651 | 0.899 | 0.162 | 0.136 | 0.191 | 1,184 | 16 |
| gap < 10% | all_pairs | goal | 0.662 | 0.482 | 0.817 | 0.135 | 0.103 | 0.169 | 1,417 | 16 |
| gap < 10% | with_parents | day | 0.792 | 0.639 | 0.901 | 0.289 | 0.234 | 0.337 | 1,184 | 16 |
| gap < 10% | all_pairs | day | 0.662 | 0.489 | 0.829 | 0.242 | 0.183 | 0.306 | 1,417 | 16 |
| touch share >= 80% | with_parents | goal | 0.626 | 0.556 | 0.694 | 0.132 | 0.113 | 0.15 | 11,777 | 22 |
| touch share >= 80% | all_pairs | goal | 0.509 | 0.419 | 0.602 | 0.108 | 0.0855 | 0.129 | 14,482 | 22 |
| touch share >= 80% | with_parents | day | 0.626 | 0.554 | 0.693 | 0.259 | 0.223 | 0.295 | 11,777 | 22 |
| touch share >= 80% | all_pairs | day | 0.509 | 0.417 | 0.604 | 0.211 | 0.172 | 0.253 | 14,482 | 22 |
| from 2025-10 | with_parents | goal | 0.606 | 0.54 | 0.681 | 0.0618 | 0.0494 | 0.0753 | 48,421 | 40 |
| from 2025-10 | all_pairs | goal | 0.408 | 0.328 | 0.504 | 0.0416 | 0.0321 | 0.0519 | 71,979 | 40 |
| from 2025-10 | with_parents | day | 0.606 | 0.538 | 0.682 | 0.244 | 0.21 | 0.285 | 48,421 | 40 |
| from 2025-10 | all_pairs | day | 0.408 | 0.331 | 0.507 | 0.164 | 0.131 | 0.209 | 71,979 | 40 |
| no GUI-heavy early goals | with_parents | goal | 0.604 | 0.534 | 0.675 | 0.0617 | 0.0488 | 0.0754 | 48,676 | 42 |
| no GUI-heavy early goals | all_pairs | goal | 0.398 | 0.323 | 0.503 | 0.0407 | 0.0313 | 0.0527 | 73,837 | 42 |
| no GUI-heavy early goals | with_parents | day | 0.604 | 0.538 | 0.677 | 0.244 | 0.21 | 0.286 | 48,676 | 42 |
| no GUI-heavy early goals | all_pairs | day | 0.398 | 0.321 | 0.49 | 0.161 | 0.126 | 0.205 | 73,837 | 42 |

Do the conclusions hold on each subset? (Write edges and all D4 rows are in outputs/tables/depgraph_robustness.csv.)

- More parents per step than the generator: holds on every subset. Full data: mean parents 2.67 (quantile 1); steps with 2+ parents 0.7 (quantile 1).
- More layer-skipping edges than the generator: holds on every subset. Full data: edges skipping 2+ layers 0.601 (quantile 1).
- A more even spread of children than the generator: holds on every subset. Full data: out-degree Gini 0.494 (quantile 0); top-10% share 0.401 (quantile 0).
- Step cost does not grow with depth as the blog assumes: holds on every subset. Full data: slope of turns 0.0208 [-0.103, 0.0641], of active minutes 0.151 [-0.13, 0.251] (blog: 9).
- Continuation far above chance: holds on every subset. Full data: rate 0.599 [0.53, 0.671] against 0.0615 (goal) and 0.243 (run day), 49,112 pairs.

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

- `outputs/tables/depgraph_goals_v1.csv`
- `outputs/tables/depgraph_structure_v1.csv`
- `outputs/tables/depgraph_parent_counts_v1.csv`
- `outputs/tables/depgraph_sensitivity_v1.csv`
- `outputs/tables/depgraph_cost_by_layer_v1.csv`
- `outputs/tables/depgraph_continuation_v1.csv`
- `outputs/tables/depgraph_rules_v1.csv`
- `outputs/tables/depgraph_artifacts_v1.csv`
- `outputs/tables/depgraph_robustness_v1.csv`
- `outputs/figures/F7_depgraph_generator_v1.pdf`
- `outputs/qa/swarmsim_d2_d4_v1.md`
- `outputs/figures/F7_depgraph_generator_v1.png`
- Private, under `data/interim/depgraph/`: touches, keyed session-artifact table, edges, continuation pairs, provider-response refs.

Command: `avsd swarmsim calibrate` (Slurm: `sbatch scripts/depgraph_calibrate.sbatch`; `--force-extract` re-extracts the touches). Library: `avsd.swarmsim.calibrate.run_calibration(cfg)`.
Python 3.11.16, numpy 2.4.6, polars 1.44.2.
