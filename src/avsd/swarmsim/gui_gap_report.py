"""QA report of the GUI focus-gap diagnosis (outputs/qa/swarmsim_gui_gap.md). Aggregates only: no typed
text, URL, path or document id reaches the report; examples are paraphrased by hand in `EXAMPLES`.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl

from avsd.swarmsim.calibrate_report import md_table
from avsd.swarmsim.touches import RULE_SETS

DATA_CITE = 'AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village'

# Paraphrased examples per target class, written after a scrubbed spot check (no raw text).
EXAMPLES: dict[str, str] = {
    "terminal command": "listing a directory, entering a project folder, printing the tail of a log, or a "
                        "multi-line script typed into a terminal window and run with Enter",
    "short input": "single letters, compass directions, chess moves or short verb-object commands entered "
                   "into a text adventure or a roguelike game; digits and punctuation keys",
    "search query": "mail-search operators (a sender filter, a date window) typed into a mailbox search box; "
                    "a short query typed after the address-bar shortcut",
    "navigation missed": "a local web app's address with a port, a local image file or a view-source address "
                         "typed into the address bar",
    "sign-in value": "a scrubbed password or token typed into a sign-in field",
    "terminal or program input": "browser-console statements that read or set page storage, commands typed "
                                 "into a terminal-based game",
    "click on a box, link or menu": "a click on a reply text box, a comment field, an upload menu item, a "
                                    "link to an issue, a reply icon",
    "message or post": "an email body or recipient list, a reply to a post on a social site, a forum comment",
    "form field": "a title, a name, a number or a date typed into a short field",
    "write button": "a click on Send, Comment, Commit changes, Publish or Save",
    "document text": "headings and paragraphs of reports and plans, answers in a questionnaire",
    "code": "HTML or script source typed into an editor, and browser-console snippets",
    "save or submit key": "ctrl+s in a text editor, ctrl+Enter to post a reply",
}
# class -> (correct, checked), from reading scrubbed random samples (seeded) of the unattributed writes
SPOT_CHECK: dict[str, tuple[int, int]] = {
    "terminal command": (15, 15),
    "short input": (14, 15),
    "search query": (15, 15),
    "navigation missed": (15, 15),
    "sign-in value": (14, 15),
    "terminal or program input": (12, 15),
    "click on a box, link or menu (not a write)": (19, 20),
    "write button (a real write)": (17, 20),
}
SCAFFOLD_NOTES: list[str] = [
    "- From the launch (2025-04-02) the computer tool logs each GUI action as `{action, coordinate, text}`: a "
    "click position, the typed text or the key name. GUI actions have no tool output, and no page, URL or "
    "window title is logged; only the screenshot shows the page (schema_notes 2.3-7).",
    "- A bash tool existed from the launch, but until September 2025 agents used it in under 1% of turns (2% "
    "to 5% of sessions) and typed commands into GUI terminal windows instead. After a prompt change on "
    "2025-10-09 (coding-assistant instructions added) bash rose to 5% to 15% of turns (25% to 39% of sessions "
    "in October to December 2025). On 2026-01-12 the bash tool description started telling agents they need "
    "not open a GUI terminal window; bash has been 33% to 55% of turns (67% to 84% of sessions) since.",
    "- The locate-element tool (`get_pixel_coords_of_element`, a text description of the element before a "
    "click) existed from the launch; prompts told Gemini (2025-04-24, 2025-07-10) and GPT-5.2 (2025-12-15) to "
    "use it. Its descriptions are the only text record of what a click targeted.",
    "- GPT-5.4 used native computer-use calls from 2026-03-10; the Claude Code agent's GUI actions use a "
    "seven-key variant (2026-01 to 2026-03). A 100-turn session cap holds from 2026-02-20. xdotool key names "
    "are normalized from 2026-04-27, with the agent's text kept in the logs.",
    "- Perma-computer-use (2026-03-24; ported to the other scaffolds on 2026-03-13): sessions run back to back "
    "and the computer, its windows and the browser persist, so a session often starts on whatever the "
    "previous one left open.",
]


def _pct(x: float) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f}%"


def _compare_versions(out: Path) -> list[str]:
    """v1 (sensitivity, `_v1` files) against v2 (main, unsuffixed files): coverage, D3, D4."""
    t = out / "tables"
    need = ["depgraph_structure.csv", "depgraph_structure_v1.csv", "depgraph_continuation.csv",
            "depgraph_continuation_v1.csv", "depgraph_goals.csv", "depgraph_goals_v1.csv"]
    if not all((t / f).exists() for f in need):
        return ["The v1 sensitivity run has not been written yet (outputs/tables/depgraph_*_v1.csv)."]
    lines = []
    g1, g2 = pl.read_csv(t / "depgraph_goals_v1.csv"), pl.read_csv(t / "depgraph_goals.csv")
    cov = pl.DataFrame([
        {"measure": "sessions touching an artifact", "v1": int(g1["sessions_with_touches"].sum()),
         "v2": int(g2["sessions_with_touches"].sum())},
        {"measure": "edges within goals (all)", "v1": int(g1["edges_all"].sum()), "v2": int(g2["edges_all"].sum())},
        {"measure": "edges within goals (write)", "v1": int(g1["edges_write"].sum()),
         "v2": int(g2["edges_write"].sum())},
        {"measure": "edges within goals (read)", "v1": int(g1["edges_read"].sum()), "v2": int(g2["edges_read"].sum())},
    ])
    lines += [md_table(cov, header=["Measure", "v1", "v2"]), ""]
    s1, s2 = pl.read_csv(t / "depgraph_structure_v1.csv"), pl.read_csv(t / "depgraph_structure.csv")
    key = ["scope", "edges", "statistic"]
    j = (s1.filter(pl.col("scope") == "pooled").select(*key, pl.col("observed").alias("v1"),
                                                         pl.col("quantile").alias("q_v1"), "gen_mean")
         .join(s2.filter(pl.col("scope") == "pooled").select(*key, pl.col("observed").alias("v2"),
                                                               pl.col("quantile").alias("q_v2")), on=key)
         .filter(pl.col("edges") != "read").sort("edges", "statistic"))
    lines += ["D3, pooled over goals (generator mean unchanged):", "",
              md_table(j, ["edges", "statistic", "v1", "q_v1", "v2", "q_v2", "gen_mean"],
                       ["Edges", "Statistic", "v1", "Quantile v1", "v2", "Quantile v2", "Generator mean"]), ""]
    c1, c2 = pl.read_csv(t / "depgraph_continuation_v1.csv"), pl.read_csv(t / "depgraph_continuation.csv")
    key = ["variant", "window", "measure", "stratum"]
    cj = (c1.select(*key, pl.col("rate").alias("rate_v1"), pl.col("baseline").alias("base_v1"),
                    pl.col("n_pairs").alias("pairs_v1"))
          .join(c2.select(*key, pl.col("rate").alias("rate_v2"), pl.col("rate_ci_low").alias("lo_v2"),
                          pl.col("rate_ci_high").alias("hi_v2"), pl.col("baseline").alias("base_v2"),
                          pl.col("n_pairs").alias("pairs_v2")), on=key)
          .filter(pl.col("stratum") == "all").sort("variant", "window", "measure"))
    lines += ["D4, all strata:", "",
              md_table(cj, ["variant", "window", "measure", "rate_v1", "base_v1", "pairs_v1", "rate_v2", "lo_v2",
                            "hi_v2", "base_v2", "pairs_v2"],
                       ["Edges", "Window", "Measure", "Rate v1", "Baseline v1", "Pairs v1", "Rate v2", "CI low",
                        "CI high", "Baseline v2", "Pairs v2"]), ""]
    return lines


def write_gap_report(path: Path, cfg: dict, w: pl.DataFrame, tables: dict[str, pl.DataFrame],
                     signals: pl.DataFrame, heur: pl.DataFrame, gap: pl.DataFrame, months: pl.DataFrame,
                     first: pl.DataFrame) -> None:
    n_all = w.height
    u = w.filter(~pl.col("attributed"))
    n_u = u.height
    tgt = (u.group_by("target", "not_document").len().sort("len", descending=True)
           .with_columns((pl.col("len") / n_u).alias("share")))
    nd = int(u["not_document"].sum())
    real = u.filter(~pl.col("not_document"))
    ses_u = u["session_id"].n_unique()
    cause_lines = [f"  - {r['target']}: {r['len']:,} ({_pct(r['share'])})"
                   f"{'; not a document write' if r['not_document'] else ''}." for r in tgt.iter_rows(named=True)]
    hv = {r["heuristic"]: r for r in heur.iter_rows(named=True)}
    v2 = RULE_SETS.get("v2")
    nav = tables["navigates"].filter(~pl.col("session_navigates"))
    no_nav = int(nav["unattributed"].sum()) if nav.height else 0
    best = heur.sort("accuracy_key", descending=True, nulls_last=True).row(0, named=True)
    v2_line = ""
    from avsd.swarmsim.depgraph_data import paths as data_paths

    g2 = data_paths(cfg, "v2")["gui"]
    if g2.exists():
        c2 = pl.read_parquet(g2)
        w2, u2 = int(c2["gui_writes"].sum()), int(c2["gui_writes_unattributed"].sum())
        v2_line = (f"- Rules v2 (the main version since the owner confirmed them on 2026-10-01) apply the validated "
                   f"reclassification: {n_all - w2:,} of the {n_all:,} v1 GUI writes "
                   f"are no longer GUI writes (typed shell commands are parsed as bash instead). {w2:,} GUI writes "
                   f"remain, {u2:,} ({_pct(u2 / w2 if w2 else math.nan)}) without a focus. Coverage, D3 and D4 "
                   "barely change (section 6).")
    lines = [
        "# QA: why most GUI writes have no focus (module D2 follow-up)",
        "",
        f"Data: {DATA_CITE}. Text data only: no screenshots and no external model. Every number counts GUI "
        "writes as the D2 rules v1 define them (typed text, ctrl+s or ctrl+Enter, a click right after locating a "
        "write button, xdotool input).",
        "",
        "## Main causes",
        "",
        f"- {n_all:,} GUI writes, {n_u:,} ({_pct(n_u / n_all)}) without a focus in {ses_u:,} sessions.",
        f"- {nd:,} of the unattributed writes ({_pct(nd / n_u)}) are not writes to a persistent document at all "
        "and should be reclassified, not counted as a gap. The remaining "
        f"{real.height:,} ({_pct(real.height / n_u)}) are real writes whose target the text data does not name.",
        f"- Structural cause of the remaining gap: {no_nav:,} unattributed writes ({_pct(no_nav / n_u)}) happen in "
        "sessions that never type a URL. Agents reach pages by clicking links, bookmarks, tabs and results, or keep "
        "working in windows an earlier session left open, and the scaffold logs no page, URL or window title for "
        "GUI actions (section 5).",
        f"- No focus heuristic recovers the page. On writes whose focus is known, the best one ({best['heuristic']}) "
        f"names the right artifact for {_pct(best['accuracy_key'])} of its predictions; the focus carried over from "
        f"the previous session is right for {_pct(hv['carry']['accuracy_key'])} (section 4). None goes into rules "
        "v2.",
        *([v2_line] if v2_line else []),
        "- Unattributed writes by most likely target:",
        *cause_lines,
        "",
        "## 1. Breakdown of the unattributed GUI writes",
        "",
        "`Unattributed rate` is the share of a group's GUI writes without a focus; `share of unattributed` is the "
        "group's part of all unattributed writes.",
        "",
    ]
    for name, title in (("kind", "Action kind"), ("regime", "Computer-use regime"), ("scaffold", "Scaffold"),
                        ("bash", "Session also uses the bash tool"), ("regime_bash", "Regime and bash use"),
                        ("locate", "Session uses the locate-element tool"),
                        ("navigates", "Session navigates by URL at some point"),
                        ("position", "Position in the session"), ("family", "Model family"),
                        ("month", "Month (Pacific time)")):
        lines += [f"### {title}", "", md_table(tables[name]), ""]
    top_models = tables["model"].sort("unattributed", descending=True).head(15)
    lines += ["### Models with the most unattributed GUI writes", "", md_table(top_models), ""]
    lines += [
        "## 2. What the typed text is",
        "",
        "Typed text (and the text of `xdotool type`) is classified with `avsd.swarmsim.touches.classify_typed`, first "
        "match wins: a shell command line (as typed into a terminal window); a sign-in value (a scrubbed value or a "
        "located password field); a URL, host, local address or file:, view-source: or javascript: address that v1 "
        "misses; code (two or more code markers); a search (a short query after an address-bar key or into a "
        "located search box, or mail-search operators); a short input (one or two characters, one lower-case word, "
        "chess moves, or short lower-case commands entered with a newline, or with Return right after while the "
        "agent's words name a game or a terminal); a form field (a short single-line value); prose (a sentence or "
        "longer text); other. A click is a write only on a named button with no box, field, link, menu, tab or "
        "icon named before the word button (`is_write_button`). Targets add context: other short text typed while "
        "a terminal was opened, clicked or named in the ten turns before is `terminal or program input`; prose is "
        "a `message or post` or `document text` when the agent named mail, chat, a post, a document or an editor "
        "in this turn or the three before; a list of email addresses is part of a message.",
        "",
        md_table(tables["text_class"].rename({"text_class": "text class (type writes)"})),
        "",
        md_table(tables["target"]),
        "",
    ]
    if SPOT_CHECK:
        lines += ["Spot check of the classes (scrubbed samples read by hand; correct of checked):", "",
                  md_table(pl.DataFrame([{"class": k, "correct": c, "checked": n, "precision": c / n}
                                         for k, (c, n) in SPOT_CHECK.items()])), ""]
    if EXAMPLES:
        lines += ["Paraphrased examples:", ""] + [f"- {k}: {v}" for k, v in EXAMPLES.items()] + [""]
    lines += [
        "## 3. Focus signals the v1 rules miss",
        "",
        "Share of unattributed and attributed GUI writes that show each signal (a write can show several).",
        "",
        md_table(signals, header=["Signal", "Writes", "n", "With signal", "Share"]),
        "",
        "## 4. Validation of the focus heuristics",
        "",
        "Each heuristic names a focus without looking at the in-session navigation. On the "
        f"{hv['carry']['known_writes']:,} GUI writes whose v1 focus is known, we hide that focus and check whether "
        "the heuristic names the same artifact key (or at least the same container). Coverage is the share of "
        "unattributed writes for which the heuristic names anything.",
        "",
        md_table(heur, header=["Heuristic", "Known writes", "Predicted", "Accuracy (key)", "Accuracy (container)",
                               "Unattributed", "Covered", "Coverage"]),
        "",
        "Carry-over accuracy by the gap between the end of the previous session and the start of this one:",
        "",
        md_table(gap, header=["Gap from (min)", "Gap to (min)", "Known writes", "Accuracy (key)",
                              "Accuracy (container)", "Unattributed writes"]),
        "",
        "## 5. What the scaffold logged in each era",
        "",
        *SCAFFOLD_NOTES,
        "",
        md_table(months, header=["Month", "Turns", "Bash share of turns", "GUI share of turns", "Type share",
                                 "Locate-element share", "Seven-key GUI share", "Sessions", "Sessions with bash",
                                 "Sessions with GUI"]),
        "",
        "First and last day of each action name:",
        "",
        md_table(first, header=["Action", "First", "Last", "Turns"]),
        "",
        "## 6. Rules v2 and the rerun",
        "",
        f"Rules v2 (`RULE_SETS['v2']`): reclassify typed text {v2.reclassify if v2 else ''}; typed shell commands "
        f"parsed as bash {v2.shell_as_bash if v2 else ''}; an address-bar search clears the focus "
        f"{v2.search_clears_focus if v2 else ''}; focus carried over from the previous session within "
        f"{v2.carry_gap_min if v2 else ''} minutes; focus named in the agent's words within "
        f"{v2.narrative_window if v2 else ''} turns. The owner confirmed rules v2 on 2026-10-01: they are the main "
        "version (unsuffixed outputs), and v1 is kept as a sensitivity version (outputs with the suffix `_v1`).",
        "",
        *_compare_versions(Path(cfg["paths"]["outputs"])),
        "Command: `python scripts/depgraph_gui_gap.py` (diagnosis); `avsd swarmsim calibrate` (main, rules v2) and "
        "`avsd swarmsim calibrate --rules v1` (sensitivity).",
        "",
    ]
    path.write_text("\n".join(lines))
