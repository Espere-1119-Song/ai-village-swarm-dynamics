"""Agent roster with model family and presence window (SPEC 4.1 step 5).

The static map `configs/agent_families.csv` gives each agent name its
provider, model family (Anthropic, OpenAI, Google, Other), scaffold and model
group. It was derived from the `agents` table and the CHANGELOG roster
(schema_notes 4.9): agent names and model strings are public. The two Tinker
fine-tuned leaders share one model and form one `model_group`.

Presence comes from activity in the unified event table, never from roster
dates or `created_at`. The temporary leader's test session on 2026-05-26 does
not count as presence (docs/decisions.md).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from avsd.config import REPO_ROOT

FAMILY_MAP = REPO_ROOT / "configs" / "agent_families.csv"
FAMILIES = ("Anthropic", "OpenAI", "Google", "Other")
SCAFFOLDS = ("standard", "claude_code")
# (agent name, PT date) pairs whose rows do not count as presence.
PRESENCE_EXCLUDE: tuple[tuple[str, date], ...] = (
    ("[Temporary] Fine-tuned Leader", date(2026, 5, 26)),
)


def load_agent_meta(tables_dir: Path, family_map: Path = FAMILY_MAP) -> pl.DataFrame:
    """One row per agent id: name, model string and the static family map.

    Raises if an agent is missing from the map or the model strings differ.
    """
    agents = pl.read_parquet(
        Path(tables_dir) / "agents.parquet", columns=["id", "name", "model_string", "created_at"]
    ).rename({"id": "agent_id"})
    fam = pl.read_csv(family_map).rename({"model_string": "map_model_string"})
    bad = set(fam["model_family"].to_list()) - set(FAMILIES)
    if bad:
        raise ValueError(f"unknown model_family values in {family_map}: {sorted(bad)}")
    out = agents.join(fam, on="name", how="left")
    missing = out.filter(pl.col("model_family").is_null())["name"].to_list()
    if missing:
        raise ValueError(f"agents missing from {family_map}: {missing}")
    differ = out.filter(pl.col("model_string") != pl.col("map_model_string"))["name"].to_list()
    if differ:
        raise ValueError(f"model_string differs from {family_map} for: {differ}")
    return out.select(
        "agent_id", "name", "model_string", "provider", "model_family",
        pl.col("scaffold").cast(pl.Enum(SCAFFOLDS)), "model_group", "api_format", "created_at",
    ).sort("created_at", "name")


def presence_excluded(actor: pl.Expr, pt_date: pl.Expr, meta: pl.DataFrame) -> pl.Expr:
    """True for rows that do not count as presence (PRESENCE_EXCLUDE)."""
    ids = dict(meta.select("name", "agent_id").iter_rows())
    expr = pl.lit(False)
    for name, d in PRESENCE_EXCLUDE:
        if name in ids:
            expr = expr | ((actor == ids[name]) & (pt_date == pl.lit(d)))
    return expr


def build_agents(meta: pl.DataFrame, unified: pl.LazyFrame) -> pl.DataFrame:
    """agents.parquet: the meta columns plus the presence window from activity.

    Activity is every `actor_type == "agent"` row of the agent, minus
    PRESENCE_EXCLUDE.
    """
    act = (
        unified.filter(pl.col("actor_type") == "agent")
        .select("actor_id", "ts_utc", pl.col("ts_pt").dt.date().alias("date"))
        .filter(~presence_excluded(pl.col("actor_id"), pl.col("date"), meta))
        .group_by("actor_id")
        .agg(
            pl.col("ts_utc").min().alias("first_active_ts"),
            pl.col("ts_utc").max().alias("last_active_ts"),
            pl.col("date").n_unique().alias("n_active_dates"),
            pl.len().alias("n_rows"),
        )
        .collect()
        .rename({"actor_id": "agent_id"})
    )
    return meta.join(act, on="agent_id", how="left").sort("first_active_ts", "name")
