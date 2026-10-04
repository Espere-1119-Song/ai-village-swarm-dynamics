"""Behavioural and lexical time series per run day for module C (SPEC 7.1).

Every series is a ratio of sums, value = scale * sum(num) / sum(den), over the agents of one group
(one agent, one model family, or all agents) and the run days of one point. The sums come from
per-agent daily components (`Components.daily`), so a family series can be recomputed for any
subset of agents, as the composition check needs (SPEC 7.2). Components per agent and run day on
which the agent is active (`roster_daily.active`):

- `n_msg`, `len_sum`, `n_question`: agent chat messages (`kind == agent_msg`, one row per
  `chat_messages` id), the sum of their full lengths (`text_len`, characters) and the number that
  contain a question (lexical.QUESTION);
- `n_wait`, `n_pause`, `n_search`: WAIT, PAUSE and SEARCH_HISTORY events;
- `n_session`, `n_session_turns`: computer-use sessions started that day and the turns of those
  sessions (every turn, also one that mirrors a chat message or an event, because the turn is the
  unit counted here);
- `n_events`: every agent row except memory snapshots and duplicate turns (`dup_of_uid` set), so
  each message and each event counts once;
- `active_hours`: the run hours of the day (all blocks of the date, `run_periods.active_seconds`),
  so `n_events / active_hours` is comparable across the schedule regimes;
- `w_<word>`: occurrences of each lexical word (lexical.py).

Count metrics are per active agent-day (den = `active`). Family and all-agent series leave out the
Claude Code agent (a different scaffold, analysed separately; schema_notes section 5); its own
per-agent series are kept. A series whose median daily support (the count behind each daily value)
is below MIN_DAILY_SUPPORT is sparse and is pooled into BIN_RUN_DAYS-run-day bins aligned to run
day 1, each placed at its first run day. Series with fewer than MIN_POINTS points are skipped.

External series (`EXTERNAL_SERIES`) are hooks for module A's rolling-window results (shares of
baseline, human and agent triggered activity, spectral radius, agent count) and module B1's
monthly hazard. Each file, when present, has `run_day` (first run day of the window) or `date`, an
optional `group` column (population or family), and numeric value columns; every value column of
every group is a series, analysed on its own scale. An `n_agents` column is a series too, and its
segment means are attached to every change point of the same file (`n_agents_before`/`_after`),
since the spectral radius depends on the number of agents in the window.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from avsd.changepoint.lexical import Lexical, lexical_components, load_display_names
from avsd.events.agents import FAMILIES

ALL = "All agents"
BIN_RUN_DAYS = 5
MIN_DAILY_SUPPORT = 10
MIN_POINTS = 12
VILLAGE_DAY1 = date(2025, 4, 2)
# Hooks: source name -> file under paths.outputs (module A rolling windows, module B1 hazard).
EXTERNAL_SERIES: dict[str, str] = {
    "hawkes": "tables/hawkes_rolling.parquet",
    "memory_hazard": "tables/memory_hazard_monthly_v2.parquet",  # B1 main rule set v2 (owner's audit labels, 2026-10-03)
}
EXTERNAL_KEYS = ("run_day", "date", "group", "run_day_end")


@dataclass(frozen=True)
class Metric:
    name: str
    label: str            # capitalised, for tables and figures
    num: str              # component summed into the numerator
    den: str              # component summed into the denominator
    support: str          # component whose daily sum decides sparsity
    transform: str = "log1p"  # detection scale: log1p | identity
    scale: float = 1.0
    min_den: float = 1.0


METRICS: tuple[Metric, ...] = (
    Metric("msg_count", "Messages per agent-day", "n_msg", "active", "n_msg"),
    Metric("msg_len", "Mean message length", "len_sum", "n_msg", "n_msg", min_den=3),
    Metric("question_ratio", "Question ratio", "n_question", "n_msg", "n_msg", "identity", min_den=3),
    Metric("wait_count", "WAIT per agent-day", "n_wait", "active", "n_wait"),
    Metric("pause_count", "PAUSE per agent-day", "n_pause", "active", "n_pause"),
    Metric("session_count", "Sessions per agent-day", "n_session", "active", "n_session"),
    Metric("turns_per_session", "Turns per session", "n_session_turns", "n_session", "n_session",
           min_den=3),
    Metric("search_count", "Search history per agent-day", "n_search", "active", "n_search"),
    Metric("events_per_hour", "Events per run hour", "n_events", "active_hours", "n_events",
           min_den=0.5),
)


def word_metric(word: str) -> Metric:
    return Metric(f"word:{word}", f"'{word}' per 1,000 messages", f"w_{word}", "n_msg", f"w_{word}",
                  scale=1000.0, min_den=3)


@dataclass
class SeriesSpec:
    series_id: str
    level: str                 # family | agent | lexical | external
    entity: str                # family, "All agents", agent name, or external group
    metric: Metric
    agent_ids: tuple[str, ...] = ()
    resolution: int = 1
    n_points: int = 0
    skipped: str | None = None


@dataclass
class Components:
    daily: pl.DataFrame        # agent_id, run_day, active, active_hours, counts, w_<word>
    days: pl.DataFrame         # run_day, date, village_day, hours, main_start, main_end, last_end
    agents: pl.DataFrame       # agent_id, name, model_family, scaffold
    lexical: Lexical
    stats: dict = field(default_factory=dict)

    @property
    def n_days(self) -> int:
        return int(self.days["run_day"].max())


def load_days(processed: Path) -> pl.DataFrame:
    """One row per run day: date, village day, run hours, the main block and the end of the last block."""
    blocks = pl.read_parquet(Path(processed) / "run_periods.parquet")
    return (
        blocks.sort("realization_id")
        .group_by("run_day", maintain_order=True)
        .agg(
            pl.col("date").first(),
            (pl.col("active_seconds").sum() / 3600.0).alias("hours"),
            pl.col("start").filter(pl.col("is_main")).first().alias("main_start"),
            pl.col("end").filter(pl.col("is_main")).first().alias("main_end"),
            pl.col("end").max().alias("last_end"),
        )
        .sort("run_day")
        .with_columns(((pl.col("date") - pl.lit(VILLAGE_DAY1)).dt.total_days() + 1)
                      .cast(pl.Int32).alias("village_day"))
    )


def _agent_day_counts(unified: Path) -> pl.DataFrame:
    u = pl.scan_parquet(unified)
    ag = u.filter(pl.col("actor_type") == "agent")
    k = pl.col("kind")
    counts = (
        ag.group_by(pl.col("actor_id").alias("agent_id"), "run_day")
        .agg(
            (k == "agent_msg").sum().alias("n_msg"),
            pl.col("text_len").filter(k == "agent_msg").sum().alias("len_sum"),
            (k == "wait").sum().alias("n_wait"),
            (k == "pause").sum().alias("n_pause"),
            (k == "search_history").sum().alias("n_search"),
            (k == "session_start").sum().alias("n_session"),
            ((pl.col("source") != "memory") & pl.col("dup_of_uid").is_null()).sum().alias("n_events"),
        )
        .collect()
    )
    turns = u.filter(pl.col("source") == "turn").group_by("session_id").agg(pl.len().alias("n_turns"))
    sess = (
        ag.filter(k == "session_start")
        .select(pl.col("actor_id").alias("agent_id"), "run_day", "session_id")
        .join(turns, on="session_id", how="left")
        .group_by("agent_id", "run_day")
        .agg(pl.col("n_turns").fill_null(0).sum().alias("n_session_turns"))
        .collect()
    )
    return counts.join(sess, on=["agent_id", "run_day"], how="left")


def _messages(unified: Path, tables: Path) -> pl.DataFrame:
    """agent_id, run_day, content of every agent chat message."""
    m = (
        pl.scan_parquet(unified)
        .filter(pl.col("kind") == "agent_msg")
        .select(pl.col("actor_id").alias("agent_id"), "run_day",
                pl.col("text_ref").str.strip_prefix("chat_messages:").alias("id"))
        .collect()
    )
    content = pl.read_parquet(Path(tables) / "chat_messages.parquet", columns=["id", "content"])
    return m.join(content, on="id", how="left").drop("id")


def load_components(cfg: dict) -> Components:
    """Per-agent daily components from the unified event table and the lexical stage."""
    processed, tables = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["tables"])
    unified = processed / "events_unified.parquet"
    agents = pl.read_parquet(processed / "agents.parquet",
                             columns=["agent_id", "name", "model_family", "scaffold"])
    agents = agents.with_columns(pl.col("scaffold").cast(pl.String))
    days = load_days(processed)
    active = (
        pl.read_parquet(processed / "roster_daily.parquet", columns=["agent_id", "run_day", "active"])
        .filter(pl.col("active")).select("agent_id", "run_day")
    )
    counts = _agent_day_counts(unified)
    msgs = _messages(unified, tables)
    lex = lexical_components(msgs, agents, load_display_names(tables), FAMILIES)
    daily = (
        active.join(counts, on=["agent_id", "run_day"], how="left")
        .join(lex.question, on=["agent_id", "run_day"], how="left")
        .join(lex.word_counts, on=["agent_id", "run_day"], how="left")
        .join(days.select("run_day", "hours"), on="run_day", how="left")
    )
    num_cols = [c for c in daily.columns if c not in ("agent_id", "run_day", "hours")]
    daily = daily.with_columns(
        *[pl.col(c).fill_null(0).cast(pl.Float64) for c in num_cols],
        pl.lit(1.0).alias("active"),
        pl.col("hours").alias("active_hours"),
    ).drop("hours").sort("agent_id", "run_day")
    stats = {
        "agent_days": daily.height,
        "messages": int(daily["n_msg"].sum()),
        "messages_without_content": int(msgs["content"].is_null().sum()),
        "agent_days_dropped": int(counts.join(active, on=["agent_id", "run_day"], how="anti").height),
    }
    return Components(daily, days, agents, lex, stats)


def series_points(
    daily: pl.DataFrame, agent_ids: tuple[str, ...] | list[str], m: Metric, resolution: int = 1,
    lo: int | None = None, hi: int | None = None,
) -> pl.DataFrame:
    """Points of one series: run_day (bin start), num, den, support, n_agents, value.

    Rows with den below the metric's minimum are dropped. `lo`/`hi` restrict the run days used
    (bins are cut at those bounds).
    """
    d = daily.filter(pl.col("agent_id").is_in(list(agent_ids)))
    if lo is not None:
        d = d.filter(pl.col("run_day") >= lo)
    if hi is not None:
        d = d.filter(pl.col("run_day") <= hi)
    key = ((pl.col("run_day") - 1) // resolution * resolution + 1).cast(pl.Int32).alias("run_day")
    return (
        d.group_by(key)
        .agg(
            pl.col(m.num).sum().alias("num"),
            pl.col(m.den).sum().alias("den"),
            pl.col(m.support).sum().alias("support"),
            pl.col("agent_id").n_unique().cast(pl.Int32).alias("n_agents"),
        )
        .filter(pl.col("den") >= m.min_den)
        .with_columns((m.scale * pl.col("num") / pl.col("den")).alias("value"))
        .sort("run_day")
    )


def transform(values: np.ndarray, m: Metric) -> np.ndarray:
    """Values on the detection scale of the metric."""
    v = np.asarray(values, dtype=float)
    return np.log1p(np.maximum(v, 0.0)) if m.transform == "log1p" else v


def specs_for(comp: Components) -> list[SeriesSpec]:
    """Candidate series: family and all-agent behaviour, each agent's behaviour, family words."""
    ag = comp.agents
    std = ag.filter(pl.col("scaffold") == "standard")
    specs: list[SeriesSpec] = []
    groups = [(f, tuple(std.filter(pl.col("model_family") == f)["agent_id"].to_list())) for f in FAMILIES]
    groups.append((ALL, tuple(std["agent_id"].to_list())))
    for name, ids in groups:
        for m in METRICS:
            specs.append(SeriesSpec(f"family:{name}:{m.name}", "family", name, m, ids))
    for r in ag.sort("name").iter_rows(named=True):
        for m in METRICS:
            specs.append(SeriesSpec(f"agent:{r['name']}:{m.name}", "agent", r["name"], m,
                                    (r["agent_id"],)))
    for fam, words in comp.lexical.family_words.items():
        ids = dict(groups)[fam]
        for w in words:
            specs.append(SeriesSpec(f"lexical:{fam}:{w}", "lexical", fam, word_metric(w), ids))
    return specs


def build_series(comp: Components, specs: list[SeriesSpec]) -> pl.DataFrame:
    """Points of every spec (sets each spec's resolution, n_points and skip reason).

    Returns series_id, run_day, run_day_end, value, value_t, num, den, support, n_agents.
    """
    n_days = comp.n_days
    frames = []
    for s in specs:
        pts = series_points(comp.daily, s.agent_ids, s.metric, 1)
        if pts.height and float(pts["support"].median()) < MIN_DAILY_SUPPORT:
            s.resolution = BIN_RUN_DAYS
            pts = series_points(comp.daily, s.agent_ids, s.metric, BIN_RUN_DAYS)
        s.n_points = pts.height
        if s.n_points < MIN_POINTS:
            s.skipped = "too few points"
            continue
        frames.append(pts.with_columns(
            pl.lit(s.series_id).alias("series_id"),
            pl.min_horizontal(pl.col("run_day") + s.resolution - 1, pl.lit(n_days)).cast(pl.Int32)
            .alias("run_day_end"),
            pl.Series("value_t", transform(pts["value"].to_numpy(), s.metric)),
        ))
    cols = ["series_id", "run_day", "run_day_end", "value", "value_t", "num", "den", "support",
            "n_agents"]
    return pl.concat([f.select(cols) for f in frames]) if frames else pl.DataFrame()


def load_external(cfg: dict, days: pl.DataFrame) -> tuple[list[SeriesSpec], pl.DataFrame, dict[str, str]]:
    """Series from the module A and B1 hook files that exist (see module docstring)."""
    out_dir = Path(cfg["paths"]["outputs"])
    specs, frames, status = [], [], {}
    n_days = int(days["run_day"].max())
    for source, rel in EXTERNAL_SERIES.items():
        path = out_dir / rel
        if not path.exists():
            status[source] = f"not available ({rel})"
            continue
        df = pl.read_parquet(path) if path.suffix == ".parquet" else pl.read_csv(path, try_parse_dates=True)
        if "run_day" not in df.columns:
            d = days.select("run_day", "date").sort("date")
            df = df.sort("date").join_asof(d, on="date", strategy="forward")
        if "group" not in df.columns:
            df = df.with_columns(pl.lit("all").alias("group"))
        values = [c for c, t in df.schema.items() if c not in EXTERNAL_KEYS and t.is_numeric()]
        for g, sub in df.group_by("group", maintain_order=True):
            sub = sub.drop_nulls("run_day").with_columns(pl.col("run_day").cast(pl.Int32)).sort("run_day")
            rd = sub["run_day"].to_numpy()
            res = int(np.median(np.diff(rd))) if len(rd) > 1 else 1
            agents = (pl.col("n_agents").cast(pl.Int32) if "n_agents" in sub.columns
                      else pl.lit(None, pl.Int32)).alias("n_agents")
            for c in values:
                part = sub.select("run_day", pl.col(c).cast(pl.Float64).alias("value"), agents)
                part = part.drop_nulls(["run_day", "value"])
                m = Metric(c, c.replace("_", " ").capitalize(), c, c, c, "identity")
                sid = f"{source}:{g[0]}:{c}"
                spec = SeriesSpec(sid, "external", f"{source} {g[0]}", m, (), max(1, res), part.height)
                specs.append(spec)
                if part.height < MIN_POINTS:
                    spec.skipped = "too few points"
                    continue
                frames.append(part.with_columns(
                    pl.lit(sid).alias("series_id"),
                    pl.min_horizontal(pl.col("run_day") + spec.resolution - 1, pl.lit(n_days))
                    .cast(pl.Int32).alias("run_day_end"),
                    pl.col("value").alias("value_t"),
                    pl.lit(None, pl.Float64).alias("num"), pl.lit(None, pl.Float64).alias("den"),
                    pl.lit(None, pl.Float64).alias("support"),
                ))
        status[source] = f"{len(values)} value columns from {rel}"
    cols = ["series_id", "run_day", "run_day_end", "value", "value_t", "num", "den", "support",
            "n_agents"]
    return specs, (pl.concat([f.select(cols) for f in frames]) if frames else pl.DataFrame()), status
