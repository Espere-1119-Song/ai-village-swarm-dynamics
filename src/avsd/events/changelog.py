"""Parse CHANGELOG.md into a dated, categorised change table (SPEC 4.1 step 7).

One row per bullet under "## Scaffolding changes", plus one row per agent join
and leave from the "## Agent roster" table. Categories are the SPEC set
(prompt, tool, memory, model, roster, other) plus goal and chat, which the
owner added on 2026-09-30. They are multi-label and assigned by
the transparent rules in TAG_CATEGORIES, KEYWORD_RULES, SCHEDULE_PATTERNS and
REGIME_CHANGES. The rule output is shown to the user for confirmation;
confirmed corrections go into CATEGORY_OVERRIDES, keyed by entry_id.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import polars as pl

from avsd.config import load_config

CATEGORIES = ("prompt", "tool", "memory", "model", "roster", "goal", "chat", "other")

# Bold tag prefix -> categories. Other maps to nothing: those bullets get
# categories from KEYWORD_RULES, and "other" if nothing matches. Every goal
# entry is also a prompt entry (goals and kickoffs are shown in the prompt),
# so module C can test goal changes alone or pooled with prompt changes.
TAG_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Prompt": ("prompt",),
    "Tools": ("tool",),
    "Memory": ("memory",),
    "Computer-use": ("tool",),
    "Human-use": ("tool",),
    "Chat": ("chat",),
    "Goals": ("goal", "prompt"),
    "Other": (),
    "Roster": ("roster",),
}

# Keyword hits on the bullet text (case-insensitive) add categories on top of
# the tag mapping. "tool call/result/use" describes API mechanics rather than
# the tool set, so it does not count as a tool hit. Redaction of what the
# agents see is part of the computer-use pipeline, hence "tool". "model" is
# reserved for changes to which model, or which model mode (thinking,
# chain-of-thought), runs the agents; auxiliary models (e.g. for redaction)
# do not count.
KEYWORD_RULES: dict[str, tuple[str, ...]] = {
    "prompt": (
        r"\bprompts?\b",
        r"\binstruct(?:ed|ion|ions|s)?\b",
        r"\b(?:told|reminded|asked|cautioned|encouraged)\b",
    ),
    "tool": (
        r"\btools?\b(?![- ](?:calls?|results?|use)\b)",
        r"\bsearch_history\b",
        r"\bhistory search\b",
        r"`pause`",
        r"\bredact(?:s|ed|ing|ion)?\b",
    ),
    "goal": (
        r"\bkickoff\b",
        r"\bgoal overrides?\b",
    ),
    "chat": (
        r"\bchat\b",
        r"\bchat ?rooms?\b",
        r"\brooms?\b",
        r"\bnudger\b",
        r"\bpremoderation\b",
    ),
    "memory": (
        r"\bmemory\b",
        r"\bconsolidat(?:e|es|ed|ion|ions)\b",
    ),
    "model": (
        r"\bchain-of-thought\b",
        r"\bthinking\b",
        r"\breasoning\b",
        r"\bfine-tuned models?\b",
        r"\bsupport for text-only models\b",
    ),
}

# Changes to when the village runs. A hit adds "other" and sets
# affects_schedule, since run-time changes shift every per-run-day series.
SCHEDULE_PATTERNS: tuple[str, ...] = (
    r"\bvillage hours\b",
    r"\bstart time\b",
    r"\btiming\b",
    r"\bdaily runs?\b",
    r"\bdaylight[- ]saving\b",
    r"\b\d{1,2}(?:am|pm)?\s*[–-]\s*\d{1,2}\s*(?:am|pm)\s*PT\b",
)

# Structural changes that split the data into regimes: (heading start date,
# pattern the bullet text must match) -> label.
REGIME_CHANGES: dict[tuple[date, str], str] = {
    (date(2025, 5, 2), r"chatting while on computer"): "chatting-while-on-computer",
    (date(2026, 1, 8), r"Claude Code agent"): "Claude Code agent buildout",
    (date(2026, 2, 25), r"\bRooms v1\b"): "Rooms v1",
    (date(2026, 3, 24), r"permanently_? in computer-use mode"): "perma-computer-use",
}

# User-confirmed corrections: entry_id -> categories. Replaces the rule output.
CATEGORY_OVERRIDES: dict[str, list[str]] = {}

SCHEMA = {
    "entry_id": pl.String,
    "source": pl.String,
    "date_start": pl.Date,
    "date_end": pl.Date,
    "heading_note": pl.String,
    "tags": pl.List(pl.String),
    "categories": pl.List(pl.String),
    "text": pl.String,
    "regime_change": pl.Boolean,
    "affects_schedule": pl.Boolean,
}
ROSTER_SCHEMA = {
    "agent": pl.String,
    "model_string": pl.String,
    "joined": pl.Date,
    "left": pl.Date,
    "note": pl.String,
}

_DATE = r"\d{4}-\d{2}-\d{2}"
_HEADING = re.compile(
    rf"^##\s+(?P<start>{_DATE})(?:\s+to\s+(?P<end>{_DATE}))?(?:\s+[—–-]+\s+(?P<note>.+?))?\s*$"
)
_TAGGED = re.compile(r"^\*\*\[(?P<tags>[^\]]+)\]\*\*\s*(?P<text>.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_JOINED = re.compile(rf"^(?P<date>{_DATE})(?:\s*\((?P<note>[^)]*)\))?$")


def _section(text: str, title: str) -> list[str]:
    """Lines after `## <title>` up to the next undated `## ` heading."""
    lines = text.splitlines()
    try:
        i = next(k for k, ln in enumerate(lines) if ln.strip() == f"## {title}")
    except StopIteration:
        return []
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("## ") and not _HEADING.match(ln) and not ln.startswith("## 20"):
            break
        out.append(ln)
    return out


def categorize(tags: list[str], text: str) -> tuple[list[str], bool]:
    """Rule-based categories and the affects_schedule flag for one entry."""
    cats: set[str] = set()
    for t in tags:
        if t not in TAG_CATEGORIES:
            raise ValueError(f"unknown CHANGELOG tag [{t}]")
        cats.update(TAG_CATEGORIES[t])
    for cat, patterns in KEYWORD_RULES.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            cats.add(cat)
    if "goal" in cats:
        cats.add("prompt")
    schedule = any(re.search(p, text, re.IGNORECASE) for p in SCHEDULE_PATTERNS)
    if schedule or not cats:
        cats.add("other")
    return [c for c in CATEGORIES if c in cats], schedule


def _is_regime(start: date, text: str) -> bool:
    return any(d == start and re.search(p, text) for d, p in REGIME_CHANGES)


def _bullets(lines: list[str]) -> list[tuple[re.Match, str]]:
    """(heading match, raw bullet text) pairs; indented lines continue a bullet."""
    out: list[list] = []
    head = None
    for ln in lines:
        if ln.startswith("## "):
            head = _HEADING.match(ln)
            if head is None:
                raise ValueError(f"unparsed CHANGELOG heading: {ln!r}")
        elif head is not None and re.match(r"^[-*]\s+", ln):
            out.append([head, re.sub(r"^[-*]\s+", "", ln).strip()])
        elif out and out[-1][0] is head and ln[:1].isspace() and ln.strip():
            out[-1][1] += " " + ln.strip()
    return [(h, t) for h, t in out]


def parse_roster(text: str) -> pl.DataFrame:
    """The "## Agent roster" table: agent, model_string, joined, left, note."""
    rows = [ln.strip() for ln in _section(text, "Agent roster") if ln.strip().startswith("|")]
    if len(rows) < 3:
        return pl.DataFrame(schema=ROSTER_SCHEMA)
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    header = [h.lower() for h in cells[0]]
    col = {k: header.index(k) for k in ("agent", "model string", "joined", "left")}
    out = []
    for c in cells[2:]:
        joined = _JOINED.match(c[col["joined"]])
        left = c[col["left"]]
        if joined is None or not (left == "active" or re.fullmatch(_DATE, left)):
            raise ValueError(f"unparsed roster row: {c}")
        out.append({
            "agent": c[col["agent"]],
            "model_string": c[col["model string"]].strip("`"),
            "joined": date.fromisoformat(joined["date"]),
            "left": None if left == "active" else date.fromisoformat(left),
            "note": joined["note"],
        })
    return pl.DataFrame(out, schema=ROSTER_SCHEMA)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def roster_changes(roster: pl.DataFrame) -> pl.DataFrame:
    """One changelog row per join and per leave. A join whose model_string is
    new to the village is also tagged "model"."""
    seen: set[str] = set()
    out = []
    for r in roster.sort("joined", maintain_order=True).iter_rows(named=True):
        label = f"{r['agent']} ({r['model_string']})"
        new_model = r["model_string"] not in seen
        seen.add(r["model_string"])
        events = [("join", r["joined"], "Agent joined", ["roster", "model"] if new_model else ["roster"])]
        if r["left"] is not None:
            events.append(("leave", r["left"], "Agent left", ["roster"]))
        for kind, d, verb, cats in events:
            out.append({
                "entry_id": f"roster-{d}-{kind}-{_slug(r['agent'])}",
                "source": "roster",
                "date_start": d,
                "date_end": d,
                "heading_note": r["note"] if kind == "join" else None,
                "tags": ["Roster"],
                "categories": [c for c in CATEGORIES if c in cats],
                "text": f"{verb}: {label}",
                "regime_change": False,
                "affects_schedule": False,
            })
    return pl.DataFrame(out, schema=SCHEMA)


def parse_changelog(
    text: str, roster: bool = True, overrides: dict[str, list[str]] | None = None
) -> pl.DataFrame:
    """Scaffolding bullets (and roster joins/leaves) as one row each, sorted
    by date. entry_id is `cl-<date_start>-<n>`, n counting bullets per start
    date in file order."""
    overrides = CATEGORY_OVERRIDES if overrides is None else overrides
    counter: dict[date, int] = {}
    out = []
    for head, raw in _bullets(_section(text, "Scaffolding changes")):
        start = date.fromisoformat(head["start"])
        end = date.fromisoformat(head["end"]) if head["end"] else start
        if end < start:
            raise ValueError(f"date range ends before it starts: {head.group(0)!r}")
        counter[start] = counter.get(start, 0) + 1
        m = _TAGGED.match(raw)
        tags = [t.strip() for t in m["tags"].split("/")] if m else []
        body = _BOLD.sub(r"\1", m["text"] if m else raw).strip()
        cats, schedule = categorize(tags, body)
        out.append({
            "entry_id": f"cl-{start}-{counter[start]}",
            "source": "changelog",
            "date_start": start,
            "date_end": end,
            "heading_note": head["note"],
            "tags": tags,
            "categories": cats,
            "text": body,
            "regime_change": _is_regime(start, body),
            "affects_schedule": schedule,
        })
    df = pl.DataFrame(out, schema=SCHEMA)
    if roster:
        df = pl.concat([df, roster_changes(parse_roster(text))])
    if overrides:
        unknown = set(overrides) - set(df["entry_id"])
        bad = {c for cats in overrides.values() for c in cats} - set(CATEGORIES)
        if unknown or bad:
            raise KeyError(f"bad category overrides: ids {sorted(unknown)}, categories {sorted(bad)}")
        cats = [overrides.get(e, c) for e, c in zip(df["entry_id"], df["categories"].to_list())]
        df = df.with_columns(pl.Series("categories", cats, dtype=pl.List(pl.String)))
    return df.sort("date_start", maintain_order=True)


def write_changelog(processed: Path, changelog_md: Path | None = None) -> pl.DataFrame:
    """Parse CHANGELOG.md (default: <paths.raw>/CHANGELOG.md) and write
    <processed>/changelog.parquet."""
    if changelog_md is None:
        changelog_md = load_config()["paths"]["raw"] / "CHANGELOG.md"
    df = parse_changelog(Path(changelog_md).read_text(encoding="utf-8"))
    processed = Path(processed)
    processed.mkdir(parents=True, exist_ok=True)
    df.write_parquet(processed / "changelog.parquet")
    return df


def render_review_table(df: pl.DataFrame, max_text: int = 100) -> str:
    """Markdown table of every entry for the user to confirm categories."""
    def cell(s: str) -> str:
        s = s.replace("|", "\\|").replace("\n", " ")
        return s if len(s) <= max_text else s[: max_text - 1].rstrip() + "…"

    lines = [
        "| entry_id | date | tags | categories | flags | text |",
        "|---|---|---|---|---|---|",
    ]
    for r in df.iter_rows(named=True):
        d = str(r["date_start"])
        if r["date_end"] != r["date_start"]:
            d += f" to {r['date_end']}"
        flags = [f for f in ("regime_change", "affects_schedule") if r[f]]
        lines.append(
            f"| {r['entry_id']} | {d} | {'/'.join(r['tags'])} | {', '.join(r['categories'])} "
            f"| {', '.join(flags)} | {cell(r['text'])} |"
        )
    return "\n".join(lines) + "\n"
