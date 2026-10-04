from datetime import date
from pathlib import Path

import polars as pl
import pytest

from avsd.events.changelog import (
    CATEGORIES,
    categorize,
    parse_changelog,
    parse_roster,
    render_review_table,
    write_changelog,
)

TEXT = (Path(__file__).parent / "fixtures" / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def df():
    return parse_changelog(TEXT)


def _row(df, entry_id):
    return df.filter(pl.col("entry_id") == entry_id).row(0, named=True)


def test_every_dated_heading_and_bullet_parsed(df):
    lines = TEXT.splitlines()
    scaffold = lines[lines.index("## Scaffolding changes"):]
    cl = df.filter(pl.col("source") == "changelog")
    n_headings = sum(ln.startswith("## 20") for ln in lines)
    assert cl.select("date_start", "date_end", "heading_note").unique().height == n_headings
    assert cl.height == sum(ln.startswith("- ") for ln in scaffold)


def test_ids_categories_and_text(df):
    assert df["entry_id"].is_unique().all()
    assert df["categories"].list.len().min() >= 1
    assert all(set(c) <= set(CATEGORIES) for c in df["categories"].to_list())
    assert not df["text"].str.contains(r"\*\*").any()
    assert df["date_start"].is_sorted()
    r = _row(df, "cl-2026-03-11-1")
    assert r["tags"] == ["Tools", "Memory"]
    assert r["text"].startswith("Added a `consolidate` tool")
    assert {"tool", "memory"} <= set(r["categories"])
    assert _row(df, "cl-2026-02-18-1")["categories"] == ["tool"]  # redaction model, not the agents'
    launch =df.filter((pl.col("source") == "changelog") & (pl.col("tags").list.len() == 0))
    assert launch["date_start"].to_list() == [date(2025, 4, 2)]


def test_date_ranges(df):
    assert (df["date_end"] >= df["date_start"]).all()
    r = _row(df, "cl-2025-11-20-1")
    assert (r["date_end"], r["heading_note"]) == (date(2025, 11, 21), None)
    r = _row(df, "cl-2026-01-08-1")
    assert (r["date_end"], r["heading_note"]) == (date(2026, 1, 27), "Claude Code agent buildout")
    r = _row(df, "cl-2026-03-24-1")
    assert (r["date_end"], r["heading_note"]) == (date(2026, 3, 24), "perma-computer-use rollout")


def test_regime_and_schedule_flags(df):
    assert _row(df, "cl-2026-03-24-1")["regime_change"]
    assert not _row(df, "cl-2026-03-24-2")["regime_change"]
    regimes = df.filter(pl.col("regime_change"))["date_start"].to_list()
    assert regimes == [date(2025, 5, 2), date(2026, 1, 8), date(2026, 2, 25), date(2026, 3, 24)]
    sched = df.filter(pl.col("affects_schedule"))
    assert {date(2025, 5, 23), date(2025, 7, 18), date(2025, 8, 18), date(2026, 3, 9),
            date(2026, 6, 7), date(2026, 6, 13), date(2026, 6, 15), date(2026, 6, 29)} <= set(sched["date_start"])
    assert all("other" in c for c in sched["categories"].to_list())
    assert not _row(df, "cl-2026-06-15-3")["affects_schedule"]  # auto-nudger, "event weekend"


def test_roster(df):
    ro = parse_roster(TEXT)
    assert ro.height == 46
    gem = ro.filter(pl.col("agent") == "Gemini 2.5 Pro").row(0, named=True)
    assert gem["left"] is None and gem["joined"] == date(2025, 4, 24)
    assert ro.filter(pl.col("note") == "launch").height == 4
    assert "`" not in "".join(ro["model_string"])
    rows = df.filter(pl.col("source") == "roster")
    assert rows.height == ro.height + ro["left"].is_not_null().sum()
    assert all(t == ["Roster"] for t in rows["tags"].to_list())
    assert all("roster" in c for c in rows["categories"].to_list())
    new_model = rows.filter(pl.col("categories").list.contains("model"))
    assert new_model.height == ro["model_string"].n_unique()
    assert _row(df, "roster-2026-06-01-join-fine-tuned-leader")["categories"] == ["roster"]
    assert _row(df, "roster-2025-04-16-leave-o1")["text"] == "Agent left: o1 (o1-2024-12-17)"


def test_categorize_rules():
    assert categorize(["Memory"], "Handle multiple tool results with Anthropic.") == (["memory"], False)
    assert categorize(["Other"], "Upgraded the model used for PII redaction.") == (["tool"], False)
    assert categorize(["Chat"], "Added basic chat-message premoderation.") == (["chat"], False)
    assert categorize(["Other"], "Updated village start time to 17:59 UTC.") == (["other"], True)
    assert categorize(["Goals"], "Goals shown to each agent in its prompt.") == (["prompt", "goal"], False)
    assert categorize(["Other"], "Added a kickoff override for the #rest room.") == (["prompt", "goal", "chat"], False)
    with pytest.raises(ValueError):
        categorize(["Nope"], "x")


def test_goal_and_chat_entries(df):
    goals = df.filter(pl.col("tags").list.contains("Goals"))
    assert goals.height > 0
    assert all({"goal", "prompt"} <= set(c) for c in goals["categories"].to_list())
    assert "chat" in _row(df, "cl-2026-02-25-1")["categories"]  # Rooms v1
    assert "chat" in _row(df, "cl-2026-02-10-1")["categories"]  # auto-nudger


def test_overrides():
    df = parse_changelog(TEXT, overrides={"cl-2025-04-14-1": ["prompt", "other"]})
    assert _row(df, "cl-2025-04-14-1")["categories"] == ["prompt", "other"]
    with pytest.raises(KeyError):
        parse_changelog(TEXT, overrides={"cl-1999-01-01-1": ["prompt"]})


def test_write_and_review_table(tmp_path, df):
    md = tmp_path / "CHANGELOG.md"
    md.write_text(TEXT, encoding="utf-8")
    out = write_changelog(tmp_path / "processed", md)
    assert pl.read_parquet(tmp_path / "processed" / "changelog.parquet").equals(out)
    lines = render_review_table(df).strip().splitlines()
    assert len(lines) == df.height + 2
    assert all(len(ln.rsplit(" | ", 1)[1].rstrip(" |")) <= 100 for ln in lines[2:])
