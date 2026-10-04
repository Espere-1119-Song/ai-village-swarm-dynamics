"""QA report for the ingest step. Aggregates only, safe to commit."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from avsd.io.tables import SPECS, TS, IngestStats

# Row counts quoted in SPEC 2.1 (from the dataset card).
SPEC_ROWS = {
    "events": 233_000, "chat_messages": 123_000, "computer_use_sessions": 37_000,
    "computer_use_turns": 1_140_000, "agent_memories": 165_000, "summaries": 800,
    "agents": 31, "chat_rooms": 5, "village_goals": 45, "villages": 1,
    "claude_code_messages": 245_000, "claude_code_sessions": 300,
}


def _table_section(name: str, stats: IngestStats, tables_dir: Path, manifest: dict) -> list[str]:
    spec = SPECS[name]
    lf = pl.scan_parquet(tables_dir / f"{name}.parquet")
    n = lf.select(pl.len()).collect().item()
    exp = manifest.get("rowCounts", {}).get(name)
    lines = [f"### {name}", ""]
    lines.append(f"- Rows read {stats.rows:,}, rows written {n:,}, unparseable lines {stats.bad_json}.")
    lines.append(
        f"- Manifest rows {exp:,}, difference {n - exp:+,}." if exp is not None else "- Not in manifest."
    )
    if name in SPEC_ROWS:
        lines.append(f"- SPEC rows about {SPEC_ROWS[name]:,}.")
    n_unique = lf.select(pl.col("id").n_unique()).collect().item()
    lines.append(f"- Duplicate ids {n - n_unique:,}.")
    ts_cols = [c for c, t in spec.columns.items() if t == TS]
    if ts_cols:
        agg = lf.select(
            [pl.col(c).min().alias(f"{c}_min") for c in ts_cols]
            + [pl.col(c).max().alias(f"{c}_max") for c in ts_cols]
            + [pl.col(c).is_not_null().sum().alias(f"{c}_ok") for c in ts_cols]
        ).collect().row(0, named=True)
        for c in ts_cols:
            fails = stats.raw_ts_nonnull[c] - agg[f"{c}_ok"]
            lines.append(
                f"- `{c}` range {agg[f'{c}_min']} to {agg[f'{c}_max']} (UTC), parse failures {fails:,}."
            )
    nulls = lf.select(pl.all().null_count()).collect().row(0, named=True)
    lines += ["", "| Column | Nulls | Share |", "|---|---:|---:|"]
    for c, v in nulls.items():
        lines.append(f"| `{c}` | {v:,} | {v / max(n, 1):.3f} |")
    if stats.unknown_keys:
        lines += ["", "Top-level keys not in SCHEMA.md: " + ", ".join(
            f"`{k}` ({v:,})" for k, v in stats.unknown_keys.most_common())]
    if stats.keys_by_type:
        label = "actionType" if name == "events" else "action"
        lines += ["", f"| {label} | Rows | Most common key set |", "|---|---:|---|"]
        for t, keysets in sorted(stats.keys_by_type.items(), key=lambda kv: -sum(kv[1].values())):
            top, _ = keysets.most_common(1)[0]
            lines.append(f"| `{t}` | {sum(keysets.values()):,} | `{top}` |")
    lines.append("")
    return lines


def write_ingest_report(all_stats: dict[str, IngestStats], cfg: dict, path: Path) -> None:
    tables_dir = cfg["paths"]["tables"]
    manifest = json.loads((cfg["paths"]["raw"] / "manifest.json").read_text())
    lines = [
        "# QA report: ingest",
        "",
        f"Dataset `{cfg['dataset']['repo_id']}` revision `{cfg['dataset']['revision']}`, "
        f"exported {manifest.get('exportedAt')}.",
        "Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village",
        "",
    ]
    for name, stats in all_stats.items():
        lines += _table_section(name, stats, tables_dir, manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
