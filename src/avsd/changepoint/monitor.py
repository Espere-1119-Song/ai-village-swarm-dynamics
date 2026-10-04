"""AI Village LLM monitor findings in module C (docs/decisions.md, V3): series, entries, annotations.

Findings come from `data/processed/monitor_findings.parquet` (avsd.validate.monitor), restricted to
the pinned export (`in_export`). A finding belongs to the run day of its monitor date. Run days
with at least one finding are covered; the coverage window is the longest stretch of covered run
days without a gap of more than 10 run days (2026-06-16 to 2026-09-18; the isolated 2026-04-06
falls outside it).

- Series: daily counts of findings per category on covered run days of the window, for all
  findings and per model family (a finding counts for every family among its agents, through
  `agent_ids` and agents.parquet). They are external series (level "external").
- Entries: the run days with at least one medium or high severity finding of a category, inside
  the window, and the sharper set of run days with a high severity finding. The alignment test
  places them only on covered run days of the window.
- Annotations: for a change point whose window of +-w run days (plus half a bin) holds a covered
  run day, the findings in that window, counted by category and severity, overall and for those
  that involve the series' agents; their ids go to a separate link table.

Outputs hold ids, categories, severities and counts only, never the heading, summary or evidence
text (which may name people), nor the `agents` names (which include humans).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from avsd.changepoint.series import Metric, SeriesSpec, series_points, transform

CATEGORIES = (
    "conflict", "off-goal", "emotional-or-erratic", "likely-scaffolding-issue",
    "surreptitious-or-deceptive", "outside-agent-contact", "human-contact", "unsolicited-outreach",
    "good-tweet", "interesting-content", "other",
)
SEVERITIES = ("high", "medium", "low")
TEST_CATEGORIES = ("likely-scaffolding-issue", "emotional-or-erratic")
SEVERE = ("medium", "high")
WINDOW_GAP_RUN_DAYS = 10
MIN_POINTS = 12
MIN_DAILY_SUPPORT = 10
BIN_RUN_DAYS = 5
ALL = "All agents"


@dataclass
class Monitor:
    findings: pl.DataFrame     # finding_id, run_day, category, severity, confidence, agent_ids
    covered: np.ndarray        # run days with findings
    window: tuple[int, int]    # first and last run day of the coverage window

    @property
    def domain(self) -> np.ndarray:
        """Covered run days inside the window."""
        lo, hi = self.window
        return self.covered[(self.covered >= lo) & (self.covered <= hi)]


def load_monitor(processed: Path, days: pl.DataFrame) -> Monitor | None:
    """Findings of the pinned export with run days; None when the file is missing."""
    path = Path(processed) / "monitor_findings.parquet"
    if not path.exists():
        return None
    f = (pl.read_parquet(path, columns=["finding_id", "date", "category", "severity", "confidence",
                                        "agent_ids", "in_export"])
         .filter(pl.col("in_export"))
         .join(days.select("date", "run_day"), on="date", how="inner")
         .drop("in_export"))
    covered = np.unique(f["run_day"].to_numpy())
    if covered.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(covered) > WINDOW_GAP_RUN_DAYS)
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, covered.size - 1]
    best = int(np.argmax(ends - starts))
    return Monitor(f, covered, (int(covered[starts[best]]), int(covered[ends[best]])))


def _col(category: str) -> str:
    return "m_" + category.replace("-", "_")


def monitor_series(mon: Monitor, agents: pl.DataFrame, n_days: int) -> tuple[list[SeriesSpec], pl.DataFrame]:
    """Daily finding counts per category, for all findings and per family (external series)."""
    fam = dict(agents.select("agent_id", "model_family").iter_rows())
    f = mon.findings.filter(pl.col("run_day").is_in(mon.domain.tolist()))
    groups = f.with_columns(
        pl.col("agent_ids").list.eval(pl.element().replace_strict(fam, default=None))
        .list.drop_nulls().list.unique().alias("families"))
    rows = []
    for g in (ALL, *sorted(set(fam.values()))):
        sub = groups if g == ALL else groups.filter(pl.col("families").list.contains(g))
        counts = sub.group_by("run_day").agg(*[(pl.col("category") == c).sum().alias(_col(c))
                                              for c in CATEGORIES])
        d = (pl.DataFrame({"run_day": mon.domain.astype(np.int32)})
             .join(counts.with_columns(pl.col("run_day").cast(pl.Int32)), on="run_day", how="left")
             .with_columns(*[pl.col(_col(c)).fill_null(0).cast(pl.Float64) for c in CATEGORIES],
                           pl.lit(f"monitor:{g}").alias("agent_id"), pl.lit(1.0).alias("active")))
        rows.append(d)
    daily = pl.concat(rows, how="diagonal_relaxed")
    specs, frames = [], []
    for g in (ALL, *sorted(set(fam.values()))):
        for c in CATEGORIES:
            m = Metric(c, f"Monitor {c} findings per run day", _col(c), "active", _col(c))
            spec = SeriesSpec(f"monitor:{g}:{c}", "external", f"Monitor {g}", m, (f"monitor:{g}",))
            pts = series_points(daily, spec.agent_ids, m, 1)
            if pts.height and float(pts["support"].median()) < MIN_DAILY_SUPPORT:
                spec.resolution = BIN_RUN_DAYS
                pts = series_points(daily, spec.agent_ids, m, BIN_RUN_DAYS)
            spec.n_points = pts.height
            specs.append(spec)
            if spec.n_points < MIN_POINTS or float(pts["num"].sum()) == 0:
                spec.skipped = "too few points" if spec.n_points < MIN_POINTS else "constant"
                continue
            frames.append(pts.with_columns(
                pl.lit(spec.series_id).alias("series_id"),
                pl.min_horizontal(pl.col("run_day") + spec.resolution - 1, pl.lit(n_days))
                .cast(pl.Int32).alias("run_day_end"),
                pl.Series("value_t", transform(pts["value"].to_numpy(), m)),
                pl.lit(None, pl.Int32).alias("n_agents"),
            ))
    cols = ["series_id", "run_day", "run_day_end", "value", "value_t", "num", "den", "support",
            "n_agents"]
    return specs, (pl.concat([x.select(cols) for x in frames]) if frames else pl.DataFrame())


def monitor_entries(mon: Monitor, category: str, days: pl.DataFrame,
                    severities: tuple[str, ...] = SEVERE) -> pl.DataFrame:
    """Run days in the window with a finding of `category` at one of `severities`."""
    lo, hi = mon.window
    rd = np.unique(mon.findings.filter(
        (pl.col("category") == category) & pl.col("severity").is_in(list(severities))
        & pl.col("run_day").is_between(lo, hi))["run_day"].to_numpy())
    date_of = dict(days.select("run_day", "date").iter_rows())
    return pl.DataFrame({
        "entry_id": [f"monitor-{category}-{date_of[int(r)]}" for r in rd],
        "source": ["monitor"] * len(rd),
        "date_start": [date_of[int(r)] for r in rd], "date_end": [date_of[int(r)] for r in rd],
        "categories": [[category]] * len(rd),
        "rd_start": rd.astype(np.int32), "rd_end": rd.astype(np.int32),
    }, schema_overrides={"categories": pl.List(pl.String)})


def _counts(sub: pl.DataFrame, key: str, levels: tuple[str, ...]) -> str:
    c = dict(sub.group_by(key).len().iter_rows())
    return ";".join(f"{k}:{c[k]}" for k in levels if c.get(k))


def annotate(cps: pl.DataFrame, mon: Monitor, series_agents: dict[str, set[str] | None], w: int
             ) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Monitor findings near each change point: columns aligned with `cps` rows, and a link table.

    `cps` has series_id, method, cp_index, run_day, resolution_run_days. `series_agents` maps a
    series to the agent ids it concerns (None: every agent).
    """
    covered = set(mon.covered.tolist())
    by_day = mon.findings.partition_by("run_day", as_dict=True)
    cols, links = [], []
    for r in cps.select("series_id", "method", "cp_index", "run_day", "resolution_run_days").iter_rows(named=True):
        h = (r["resolution_run_days"] - 1) // 2
        lo, hi = r["run_day"] - h - w, r["run_day"] + h + w
        n_cov = sum(d in covered for d in range(lo, hi + 1))
        if not n_cov:
            cols.append({"monitor_covered_days": 0})
            continue
        parts = [by_day[(d,)] for d in range(lo, hi + 1) if (d,) in by_day]
        f = pl.concat(parts) if parts else mon.findings.head(0)
        ag = series_agents.get(r["series_id"])
        mine = f if ag is None else f.filter(pl.col("agent_ids").list.eval(
            pl.element().is_in(list(ag))).list.any())
        cols.append({
            "monitor_covered_days": n_cov, "monitor_n_findings": f.height,
            "monitor_n_series_agents": mine.height,
            "monitor_by_category": _counts(f, "category", CATEGORIES),
            "monitor_by_severity": _counts(f, "severity", SEVERITIES),
            "monitor_series_agents_by_category": _counts(mine, "category", CATEGORIES),
            "monitor_series_agents_severe_ids": ";".join(
                mine.filter(pl.col("severity").is_in(SEVERE))["finding_id"].to_list()),
        })
        if mine.height:
            links.append(mine.select(
                pl.lit(r["series_id"]).alias("series_id"), pl.lit(r["method"]).alias("method"),
                pl.lit(r["cp_index"]).alias("cp_index"), pl.lit(r["run_day"]).alias("cp_run_day"),
                "finding_id", pl.col("run_day").alias("finding_run_day"),
                (pl.col("run_day") - r["run_day"]).alias("offset_run_days"),
                "category", "severity", "confidence"))
    schema = {"monitor_covered_days": pl.Int32, "monitor_n_findings": pl.Int32,
              "monitor_n_series_agents": pl.Int32, "monitor_by_category": pl.String,
              "monitor_by_severity": pl.String, "monitor_series_agents_by_category": pl.String,
              "monitor_series_agents_severe_ids": pl.String}
    out = pl.DataFrame(cols, schema=schema)
    link = pl.concat(links) if links else pl.DataFrame()
    return out, link
