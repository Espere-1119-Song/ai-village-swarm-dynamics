"""External labels from the AI Village LLM monitor (theaidigest.org/village/monitor).

The monitor is run by AI Digest with Claude Opus 4.8. For each village day it
lists findings with a category (conflict, off-goal, emotional-or-erratic,
likely-scaffolding-issue, ...), a severity, a confidence, the agents involved
and a timestamp. We use these findings only as an independent check on our
own measurements (module A excitation, module C change points). The monitor is
a live page: we record the fetch time and keep the raw responses.

Raw responses and finding text stay under data/ (gitignored). Outputs hold
aggregates only.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

API = "https://theaidigest.org/village/api/monitor"
MODEL_NAME_RE = r"^(?:Claude|GPT|Gemini|Grok|Kimi|GLM|DeepSeek|Muse|o\d)\b"
EXPORT_LAST_PT_DATE = date(2026, 9, 18)  # last PT date in the pinned export


def _get(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "avsd-research (AI Swarm Dynamics Hackathon)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_monitor(raw_dir: Path, pause_s: float = 1.5, refresh: bool = False) -> list[str]:
    """Save one JSON per monitor date to raw_dir. Returns the dates fetched."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    first = _get(API)
    dates = sorted(set(first.get("availableDates", [])))
    fetched = []
    for d in dates:
        out = raw_dir / f"{d}.json"
        if out.exists() and not refresh:
            continue
        payload = _get(f"{API}?date={d}")
        payload["_fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
        out.write_text(json.dumps(payload))
        fetched.append(d)
        time.sleep(pause_s)
    return fetched


def _match_names(names: list[str], roster: dict[str, str]) -> tuple[list[str], list[str]]:
    """Map monitor agent names to (agent_ids, unmatched names). Exact match first,
    then a unique prefix match for short forms such as "Muse"."""
    ids, missing = [], []
    keys = list(roster)
    for n in names:
        if n in roster:
            ids.append(roster[n])
            continue
        cand = [k for k in keys if k.lower().startswith(n.lower())]
        if len(cand) == 1:
            ids.append(roster[cand[0]])
        else:
            missing.append(n)
    return ids, missing


def parse_monitor(raw_dir: Path, agents_path: Path) -> pl.DataFrame:
    """One row per finding with parsed times and matched agent ids."""
    agents = pl.read_parquet(agents_path, columns=["agent_id", "name"])
    roster = dict(zip(agents["name"].to_list(), agents["agent_id"].to_list()))
    rows = []
    for f in sorted(raw_dir.glob("*.json")):
        payload = json.loads(f.read_text())
        for x in payload.get("findings", []):
            names = list(x.get("agentsInvolved") or [])
            ids, missing = _match_names(names, roster)
            rows.append({
                "finding_id": x.get("id"),
                "date": payload.get("date"),
                "timestamp_raw": x.get("timestamp"),
                "window_label": x.get("windowLabel"),
                "severity": x.get("severity"),
                "category": x.get("category"),
                "confidence": x.get("confidence"),
                "agents": names,
                "agent_ids": ids,
                "unmatched_agents": missing,
                "model": x.get("model"),
                "heading": x.get("heading"),
                "summary": x.get("summary"),
                "why_flagged": x.get("whyFlagged"),
                "evidence": x.get("evidence"),
                "generated_by": ",".join(payload.get("generatedBy") or []),
                "fetched_at_utc": payload.get("_fetched_at_utc"),
            })
    df = pl.DataFrame(rows, infer_schema_length=None)
    # Timestamp formats: "YYYY-MM-DD HH:MM:SS PT" (optionally in brackets), or a bare
    # "HH:MM:SS" (optionally in brackets). Bare times are UTC: as UTC, 1,672 of 1,682
    # fall inside the day's run blocks, against 293 as PT. A bare UTC time after
    # midnight belongs to the evening of the finding's PT date.
    raw = pl.col("timestamp_raw").str.strip_chars("[] ")
    full_pt = (
        raw.str.replace(r"\s*PT$", "").str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False)
        .dt.replace_time_zone("America/Los_Angeles", ambiguous="earliest", non_existent="null")
        .dt.convert_time_zone("UTC")
    )
    bare_utc = (
        (pl.col("date") + " " + raw).str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False)
        .dt.replace_time_zone("UTC")
    )
    df = df.with_columns(
        ts_utc=pl.when(raw.str.contains(r"^\d{4}-\d{2}-\d{2} ")).then(full_pt)
        .when(raw.str.contains(r"^\d{2}:\d{2}:\d{2}$")).then(bare_utc)
        .otherwise(None),
        ts_format=pl.when(raw.str.contains(r"^\d{4}-\d{2}-\d{2} ")).then(pl.lit("pt_datetime"))
        .when(raw.str.contains(r"^\d{2}:\d{2}:\d{2}$")).then(pl.lit("utc_time"))
        .otherwise(pl.lit("other")),
        date=pl.col("date").str.to_date(),
    )
    df = df.with_columns(
        ts_utc=pl.when(
            (pl.col("ts_format") == "utc_time")
            & (pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date() < pl.col("date"))
        ).then(pl.col("ts_utc") + pl.duration(days=1)).otherwise(pl.col("ts_utc"))
    )
    return (
        df.with_columns(
            ts_pt=pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles"),
            n_agents=pl.col("agents").list.len(),
            in_export=pl.col("date") <= pl.lit(EXPORT_LAST_PT_DATE),
        )
        .unique("finding_id", keep="first", maintain_order=True)
        .sort("ts_utc", nulls_last=True)
    )


def qa_report(df: pl.DataFrame, path: Path) -> None:
    """Aggregate QA for the monitor findings (no finding text)."""
    lines = [
        "# QA report: LLM monitor findings",
        "",
        "Source: theaidigest.org/village/api/monitor (live page, fetched "
        f"{df['fetched_at_utc'].min()} to {df['fetched_at_utc'].max()}). Generated by {df['generated_by'].unique().to_list()}.",
        "Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village",
        "",
        f"- Findings: {df.height:,} on {df['date'].n_unique()} dates ({df['date'].min()} to {df['date'].max()}).",
        f"- Within the pinned export (up to 2026-09-18 PT): {df['in_export'].sum():,} findings on "
        f"{df.filter(pl.col('in_export'))['date'].n_unique()} dates.",
        f"- Timestamp formats: {dict(df.group_by('ts_format').len().iter_rows())}. Unparsed: {df['ts_utc'].null_count()}. "
        "Bare HH:MM:SS times are UTC (checked against the run blocks).",
        f"- Findings with a window label instead of an exact moment: {df['window_label'].is_not_null().sum():,}.",
        "",
    ]
    by = df.group_by("category").agg(
        n=pl.len(), in_export=pl.col("in_export").sum(),
        high=(pl.col("severity") == "high").sum(), medium=(pl.col("severity") == "medium").sum(),
        low=(pl.col("severity") == "low").sum(), multi_agent=(pl.col("n_agents") >= 2).sum(),
    ).sort("n", descending=True)
    lines += ["| Category | Findings | In export | High | Medium | Low | 2+ agents |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in by.iter_rows(named=True):
        lines.append(f"| {r['category']} | {r['n']} | {r['in_export']} | {r['high']} | {r['medium']} | {r['low']} | {r['multi_agent']} |")
    # Names outside the export's roster mix post-export AI agents with humans and
    # external accounts. Only AI model names are listed; everything else is counted.
    unmatched = df.select(pl.col("unmatched_agents").explode().drop_nulls().value_counts(sort=True)).unnest("unmatched_agents")
    model_like = unmatched.filter(pl.col("unmatched_agents").str.contains(MODEL_NAME_RE))
    other = unmatched.filter(~pl.col("unmatched_agents").str.contains(MODEL_NAME_RE))
    lines += ["", "Participants named in findings but absent from the export's roster:", ""]
    lines += [f"- AI agents added after the export or from other villages: "
              + (", ".join(f"{r[0]} ({r[1]})" for r in model_like.iter_rows()) or "none")]
    lines += [f"- Humans and external accounts (names withheld): {other.height} distinct names, "
              f"{int(other['count'].sum()) if other.height else 0} mentions"]
    lines += [f"- Findings that involve at least one roster agent: {int((df['agent_ids'].list.len() > 0).sum()):,}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def run_monitor_ingest(cfg: dict) -> dict:
    raw_dir = cfg["paths"]["raw"].parent / "monitor"
    fetched = fetch_monitor(raw_dir)
    df = parse_monitor(raw_dir, cfg["paths"]["processed"] / "agents.parquet")
    df.write_parquet(cfg["paths"]["processed"] / "monitor_findings.parquet")
    qa_report(df, cfg["paths"]["outputs"] / "qa" / "monitor.md")
    return {"fetched": len(fetched), "findings": df.height}
