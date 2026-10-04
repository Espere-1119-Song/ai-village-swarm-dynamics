"""External validation of module A against the AI Village LLM monitor: V1 and V2 (docs/decisions.md).

`python -m avsd.validate.monitor_hawkes` (as a job: `sbatch scripts/monitor_validation.sbatch`).

The monitor (avsd.validate.monitor) is a second reading of the same days by an LLM, not ground truth;
its precision is unknown. These checks ask whether module A's Hawkes fit and the monitor's findings
point the same way. They make no causal claim.

Findings. In-export findings of data/processed/monitor_findings.parquet with their roster agents
(`agent_ids`; humans, outside accounts and AI agents that joined after the export are not dimensions
of any fit and are only counted). A finding repeated with the same category, timestamp and roster
agents (two monitor runs of one day) counts once. The V1/V2 set is the conflict findings with at
least one roster agent and the findings of any category with at least two.

Hawkes events and parents. Agent messages of module A's accepted goal windows (hawkes_windows.csv)
whose dates hold findings. The posterior probability of each parent class of every message
(background, human, system, other agents, self) is recomputed exactly from the module A fit
(data/interim/hawkes_fit/fits) with avsd.hawkes.model. hawkes_parents.parquet keeps only parents with
prob >= 0.01: the dropped mass averages about 0.08 per message and grows with the number of
candidate parents, so the stored table would understate the agent shares most in busy periods. The
recomputation is checked against every stored probability, and shares from the truncated table are
a sensitivity row.

V1, event level. A message of agent a is flagged when it lies within +-30 min of a V1 finding that
involves a. Its controls are a's messages in the same realization and group outside the +-30 min
window of every V1 finding that involves a. Strata are (window, group, realization, agent) with both
kinds. The difference of a parent-class share is the flagged-message-weighted mean over strata of
(flagged mean - control mean); its interval is a percentile bootstrap that draws realizations with
replacement. Besides the five classes: the share on messages of the agents a was flagged with
(co_involved), and other agents' and a's own messages in the preceding 10 min as context. Sensitivity
rows change the strata (also by hour of the run), the controls, the half width, the bootstrap unit
(run dates) and the source of the shares (hawkes_parents.parquet as stored).

V2, pair level. Every pair of roster agents of a finding gets the percentile rank (mid-rank among
the K(K-1)/2 agent pairs) of n_ij + n_ji in its fitting window: the accepted goal window of the
finding's date in which both agents are dimensions (the group with more of their messages within
+-30 min when two qualify). Intervals draw the findings' run dates with replacement and take n from
one module A bootstrap replicate per draw. References: a pair drawn uniformly from all pairs of the
window, and one drawn from the pairs of agents with a message in that group on the finding's date.
The share of conflict pairs inside one spectral cluster (module A's blocks, hawkes_excitation.csv)
is compared with the share of all pairs inside one cluster, which follows from the cluster sizes.
Where module A found one cluster both are 1, so partitions forced to k = 2, 3, 4 clusters with
module A's procedure are a sensitivity.

Outputs hold aggregates, AI agent names, categories, severities and dates only:
outputs/tables/monitor_v1.csv, monitor_v2.csv, monitor_v2_pairs.csv and outputs/qa/monitor_validation.md.
Per-message probabilities and flags and per-finding coverage stay in data/interim/monitor_validation/.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import itertools
import re
import time
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from avsd.config import load_config

HALF_MIN = 30.0                 # flag window: +- minutes around a finding's timestamp
HALF_MIN_SENS = (15.0, 60.0)
CONTEXT_MIN = 10.0              # context column: other agents' messages in the preceding minutes
N_BOOT = 2000
FORCED_K = (2, 3, 4)
PARENT_MIN = 0.01               # hawkes_parents.parquet keeps parents with at least this probability
TOP = 0.75                      # "top quartile" of the pair ranking
CONFLICT = "conflict"
SEVERE = ("medium", "high")
CLASSES = ("baseline", "human", "system", "other_agents", "self")   # module A's five-way order
# co_involved: parent probability on messages of the other roster agents of the findings that flag the
# agent in that stratum; *_msgs_10min: other agents' and the agent's own messages in the 10 min before.
MEASURES = ("other_agents", "co_involved", "human", "system", "self", "baseline", "other_msgs_10min",
            "own_msgs_10min")
CATEGORIES = (
    "conflict", "off-goal", "emotional-or-erratic", "likely-scaffolding-issue",
    "surreptitious-or-deceptive", "outside-agent-contact", "human-contact", "unsolicited-outreach",
    "good-tweet", "interesting-content", "other",
)
FINDING_COLS = ["finding_id", "date", "ts_utc", "ts_format", "window_label", "category", "severity",
                "confidence", "agent_ids", "unmatched_agents", "in_export", "fetched_at_utc"]
ALL = "all"
MAIN = "main"


# --- findings ---------------------------------------------------------------------------------------


def prepare_findings(raw: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """In-export findings in time order with unique sorted roster agents, `fid`, `t` (epoch seconds) and
    the V1/V2 flag `v1`. Repeats (same category, timestamp and roster agents) are dropped; their count
    is returned."""
    f = (raw.filter(pl.col("in_export"))
         .with_columns(pl.col("agent_ids").list.unique().list.sort(),
                       pl.col("unmatched_agents").list.len().fill_null(0).cast(pl.Int32).alias("n_unmatched"))
         .with_columns(pl.col("agent_ids").list.len().cast(pl.Int32).alias("n_roster"))
         .sort("ts_utc", "finding_id", nulls_last=True))
    key = pl.concat_str([pl.col("category"), pl.col("ts_utc").dt.epoch("us").cast(pl.String),
                         pl.col("agent_ids").list.join(",")], separator="|", ignore_nulls=True)
    keep = f.select(key.is_first_distinct()).to_series()
    n_dup = int((~keep).sum())
    v1 = pl.col("ts_utc").is_not_null() & (
        ((pl.col("category") == CONFLICT) & (pl.col("n_roster") >= 1)) | (pl.col("n_roster") >= 2))
    f = (f.filter(keep)
         .with_columns(v1.alias("v1"), (pl.col("ts_utc").dt.epoch("us") / 1e6).alias("t"))
         .with_row_index("fid"))
    return f, n_dup


def label_check(f: pl.DataFrame) -> dict[str, list[int]]:
    """Findings with a window label (the monitor's reading window, "HH:MM-HH:MM UTC"): per timestamp
    format, [timestamps inside the window, labels parsed]."""
    out: dict[str, list[int]] = {}
    sub = f.filter(pl.col("window_label").is_not_null() & pl.col("ts_utc").is_not_null())
    for lab, ts, fmt in sub.select("window_label", "ts_utc", "ts_format").iter_rows():
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\D+(\d{1,2}):(\d{2})\s*UTC\s*$", lab)
        if not m:
            continue
        a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
        x = ts.hour * 60 + ts.minute + ts.second / 60
        inside = a <= x <= b if a <= b else (x >= a or x <= b)
        c = out.setdefault(fmt, [0, 0])
        c[0] += int(inside)
        c[1] += 1
    return out


# --- module A inputs ----------------------------------------------------------------------------------


@dataclass
class WindowFit:
    """One accepted goal window and group of module A."""

    window_id: str
    group: str
    date_start: date
    date_end: date
    agent_ids: list[str]            # dimension order
    agent_names: list[str]
    n: np.ndarray                   # (K, K) agent block of the point estimate, n[i, j]: children of i per event of j
    blocks: np.ndarray              # (K,) module A's spectral clusters, 0-based
    n_boot: np.ndarray | None = None   # (R, K, K) module A's bootstrap replicates
    src_mass: np.ndarray | None = None    # (messages, K + H) parent probability by source, rows = events' src_row
    src_mass_q: np.ndarray | None = None  # the same from parents with prob >= PARENT_MIN only
    dim: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.dim = {a: k for k, a in enumerate(self.agent_ids)}

    @property
    def key(self) -> tuple[str, str]:
        return self.window_id, self.group

    @property
    def K(self) -> int:
        return len(self.agent_ids)

    def covers(self, d: date) -> bool:
        return self.date_start <= d <= self.date_end


def target_class_sums(tgt_dim: np.ndarray, ptr: np.ndarray, par_src: np.ndarray, p0: np.ndarray,
                      pp: np.ndarray, K: int, H: int) -> np.ndarray:
    """(N, 3 + H) posterior probability of each parent class of every target in module A's share order
    (baseline, the exogenous sources, other agents, self); the per-target version of
    avsd.hawkes.model._share_sums."""
    N, S = tgt_dim.size, 3 + H
    pair_tgt = np.repeat(np.arange(N), np.diff(ptr))
    cls = np.where(par_src >= K, 1 + par_src - K, np.where(par_src == tgt_dim[pair_tgt], H + 2, H + 1))
    out = np.bincount(pair_tgt * S + cls, weights=pp, minlength=N * S).reshape(N, S)
    out[:, 0] = p0
    return out


def accepted_windows(tables: Path) -> pl.DataFrame:
    w = pl.read_csv(Path(tables) / "hawkes_windows.csv", columns=["window_id", "group", "date_start", "date_end",
                                                                   "accepted"], try_parse_dates=True)
    return w.with_columns(pl.col("accepted").cast(pl.String).str.to_lowercase() == "true")


def module_a_blocks(tables: Path) -> dict[tuple[str, str], dict[str, int]]:
    """Spectral cluster (0-based) of every agent of every goal window, from hawkes_excitation.csv."""
    x = pl.read_csv(Path(tables) / "hawkes_excitation.csv",
                    columns=["window_id", "group", "target", "target_block"]).unique()
    return {(w, g): dict(zip(p["target"].to_list(), (p["target_block"] - 1).to_list()))
            for (w, g), p in x.partition_by(["window_id", "group"], as_dict=True).items()}


def _compare_stored(stored: pl.LazyFrame, window_id: str, group: str, uid: np.ndarray, pk, p0: np.ndarray,
                    pp: np.ndarray) -> dict:
    """Recomputed parent probabilities >= PARENT_MIN against hawkes_parents.parquet for one window."""
    s = (stored.filter((pl.col("window_id") == window_id) & (pl.col("group") == group))
         .select("event_uid", "parent_uid", "prob").collect())
    keep0, keepp = p0 >= PARENT_MIN, pp >= PARENT_MIN
    pair_tgt = np.repeat(np.arange(uid.size), np.diff(pk.ptr))
    rec = pl.DataFrame({
        "event_uid": np.concatenate([uid[keep0], uid[pair_tgt[keepp]]]).tolist(),
        "parent_uid": (["background"] * int(keep0.sum())) + pk.ev_uid[pk.par_ev[keepp]].astype(str).tolist(),
        "prob_new": np.concatenate([p0[keep0], pp[keepp]]),
    }, schema={"event_uid": pl.String, "parent_uid": pl.String, "prob_new": pl.Float64})
    j = s.join(rec, on=["event_uid", "parent_uid"], how="full", coalesce=True)
    both = j.filter(pl.col("prob").is_not_null() & pl.col("prob_new").is_not_null())
    diff = (both["prob"] - both["prob_new"]).abs()
    return {"stored_rows": s.height, "recomputed_rows": rec.height,
            "only_stored": int(j["prob_new"].null_count()), "only_recomputed": int(j["prob"].null_count()),
            "max_abs_diff": float(diff.max()) if both.height else float("nan"),
            "stored_events": int(s["event_uid"].n_unique()),
            "events_not_stored": int(len(set(uid.tolist()) - set(s["event_uid"].to_list())))}


def load_hawkes(cfg: dict, keys: set[tuple[str, str]], block_of: dict[tuple[str, str], dict[str, int]]
                ) -> tuple[pl.DataFrame, dict[tuple[str, str], WindowFit], list[dict]]:
    """Per-message parent-class probabilities (exact, p_*, and as stored with prob >= 0.01, q_*), the
    fits of the goal windows in `keys`, and per-window checks against module A's outputs."""
    from avsd.hawkes import pipeline as P
    from avsd.hawkes.model import _posterior, pack
    from avsd.hawkes.windows import EXO, Inputs

    P.apply_settings(cfg)
    inp = Inputs.load(cfg)
    stored_path = Path(cfg["paths"]["processed"]) / "hawkes_parents.parquet"
    stored = pl.scan_parquet(stored_path) if stored_path.exists() else None
    frames, fits, checks = [], {}, []
    for w in sorted(P.final_windows(cfg), key=lambda w: (w.date_start, w.group)):
        key = (w.window_id, w.group)
        if key not in keys:
            continue
        r = P.base_fit(cfg, w)
        d = inp.data(w)
        if list(d.agent_ids) != list(r.agent_ids):
            raise ValueError(f"{w.key}: the window data and the module A fit list different agents")
        pk = pack(d.days, d.K, r.fit.spec, exo_names=EXO)
        nt = pk.tgt_dim.size
        p0, pp = _posterior(r.fit.mu, r.fit.alpha, np.ones(nt), pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
        pq = np.where(pp >= PARENT_MIN, pp, 0.0)
        exact = target_class_sums(pk.tgt_dim, pk.ptr, pk.par_src, p0, pp, pk.K, pk.H)
        trunc = target_class_sums(pk.tgt_dim, pk.ptr, pk.par_src, np.where(p0 >= PARENT_MIN, p0, 0.0), pq,
                                  pk.K, pk.H)
        uid = pk.ev_uid[pk.tgt_ev].astype(str)
        frames.append(pl.DataFrame({
            "event_uid": uid.tolist(),
            "realization_id": np.asarray(d.realizations, np.int64)[pk.tgt_day],
            "run_date": [d.day_dates[k] for k in pk.tgt_day],
            "t_run": pk.ev_t[pk.tgt_ev],
            "src_row": np.arange(nt),
            "actor_id": [d.agent_ids[k] for k in pk.tgt_dim],
            "agent": [d.agent_names[k] for k in pk.tgt_dim],
            **{f"p_{c}": exact[:, k] for k, c in enumerate(CLASSES)},
            **{f"q_{c}": trunc[:, k] for k, c in enumerate(CLASSES)},
        }).with_columns(pl.lit(w.window_id).alias("window_id"), pl.lit(w.group).alias("group")))
        chk = {"window_id": w.window_id, "group": w.group, "date_start": w.date_start, "date_end": w.date_end,
               "K": d.K, "events": nt, "realizations": len(d.days),
               **{f"share_{c}": float(exact[:, k].mean()) for k, c in enumerate(CLASSES)},
               "dropped_mass_mean": float(1.0 - trunc.sum(1).mean())}
        if stored is not None:
            chk.update(_compare_stored(stored, w.window_id, w.group, uid, pk, p0, pp))
        checks.append(chk)
        K, S = d.K, d.K + pk.H
        pair_tgt = np.repeat(np.arange(nt), np.diff(pk.ptr))
        by_src = [np.bincount(pair_tgt * S + pk.par_src, weights=x, minlength=nt * S).reshape(nt, S) for x in (pp, pq)]
        boot = P.boot_of(cfg, w)
        names = block_of.get(key, {})
        fits[key] = WindowFit(w.window_id, w.group, w.date_start, w.date_end, list(d.agent_ids), list(d.agent_names),
                              np.asarray(r.fit.n)[:, :K].copy(),
                              np.array([names.get(nm, 0) for nm in d.agent_names], np.int64),
                              None if boot is None else np.asarray(boot[0].n)[:, :, :K].copy(), *by_src)
        if not names:
            checks[-1]["blocks_missing"] = True
    if not frames:
        raise ValueError("no accepted goal window covers a monitor date")
    ts = inp.msgs.select("event_uid", "ts_utc")
    ev = pl.concat(frames).join(ts, on="event_uid", how="left")
    if ev["ts_utc"].null_count():
        raise ValueError("Hawkes events without a timestamp in the unified event table")
    return finish_events(ev), fits, checks


def finish_events(ev: pl.DataFrame) -> pl.DataFrame:
    """Sort by time and add t (epoch s), the stratum keys (also by hour of the run, from t_run, seconds
    since the realization's start) and the message counts of the preceding 10 min."""
    ev = ev.with_columns((pl.col("ts_utc").dt.epoch("us") / 1e6).alias("t")).sort("t", "event_uid")
    ev = ev.with_columns(pl.concat_str([pl.col("window_id"), pl.col("group"), pl.col("realization_id").cast(pl.String),
                                        pl.col("actor_id")], separator="|").alias("stratum"),
                         (pl.col("t_run") // 3600).cast(pl.Int32).alias("run_hour"))
    ev = ev.with_columns(pl.concat_str([pl.col("stratum"), pl.col("run_hour").cast(pl.String)], separator="|")
                         .alias("stratum_hour"))
    other, own = recent_counts(ev, CONTEXT_MIN * 60.0)
    return ev.with_columns(pl.Series("other_msgs_10min", other), pl.Series("own_msgs_10min", own))


def recent_counts(ev: pl.DataFrame, window_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Per message, the messages of other agents and of its own agent in the same window, group and
    realization within the preceding window_s seconds ([t - window_s, t))."""
    t_all, act_all = ev["t"].to_numpy(), ev["actor_id"].to_numpy()
    other, own = np.zeros(ev.height), np.zeros(ev.height)
    groups = ev.with_row_index("_i").group_by("window_id", "group", "realization_id").agg("_i")
    for idx in groups["_i"].to_list():
        idx = np.asarray(idx, np.int64)
        idx = idx[np.argsort(t_all[idx], kind="stable")]
        t, a = t_all[idx], act_all[idx]
        tot = np.searchsorted(t, t, "left") - np.searchsorted(t, t - window_s, "left")
        mine = np.zeros(idx.size)
        for x in np.unique(a):
            m = a == x
            tx = t[m]
            mine[m] = np.searchsorted(tx, tx, "left") - np.searchsorted(tx, tx - window_s, "left")
        other[idx], own[idx] = tot - mine, mine
    return other, own


def partner_share(ev: pl.DataFrame, fits: dict[tuple[str, str], WindowFit], hits: list[np.ndarray],
                  f_agents: list[list[str]], truncated: bool = False) -> np.ndarray:
    """Per message, the parent probability on messages of its agent's partners: the other roster agents
    of the findings that flag the agent's messages in the same stratum (window, group, realization,
    agent). nan for messages of strata without flagged messages."""
    strata, actor = ev["stratum"].to_numpy(), ev["actor_id"].to_numpy()
    partners: dict[str, set[str]] = {}
    for h, ags in zip(hits, f_agents):
        for i in h:
            partners.setdefault(strata[i], set()).update(a for a in ags if a != actor[i])
    out = np.full(ev.height, np.nan)
    wid, grp, row = ev["window_id"].to_numpy(), ev["group"].to_numpy(), ev["src_row"].to_numpy()
    for i in np.flatnonzero(np.fromiter((s in partners for s in strata), bool, ev.height)):
        w = fits.get((wid[i], grp[i]))
        mass = None if w is None else (w.src_mass_q if truncated else w.src_mass)
        if mass is None:
            continue
        dims = [w.dim[p] for p in partners[strata[i]] if p in w.dim]
        out[i] = float(mass[row[i], dims].sum()) if dims else 0.0
    return out


# --- V1 -------------------------------------------------------------------------------------------------


def actor_index(ev: pl.DataFrame) -> dict[str, np.ndarray]:
    """Row indices of each actor's messages in time order (ev sorted by t)."""
    g = ev.with_row_index("_i").group_by("actor_id").agg("_i")
    return {a: np.sort(np.asarray(i, np.int64)) for a, i in zip(g["actor_id"].to_list(), g["_i"].to_list())}


def finding_hits(t: np.ndarray, actor_idx: dict[str, np.ndarray], f_agents: list[list[str]], f_t: np.ndarray,
                 half_s: float) -> list[np.ndarray]:
    """Per finding, the rows of its agents' messages within +-half_s of its timestamp."""
    out = []
    for ags, tc in zip(f_agents, f_t):
        hits = []
        for a in ags:
            idx = actor_idx.get(a)
            if idx is None:
                continue
            ta = t[idx]
            hits.append(idx[np.searchsorted(ta, tc - half_s, "left"):np.searchsorted(ta, tc + half_s, "right")])
        out.append(np.concatenate(hits) if hits else np.empty(0, np.int64))
    return out


def union_mask(n: int, hits: list[np.ndarray]) -> np.ndarray:
    m = np.zeros(n, bool)
    if hits:
        m[np.concatenate(hits).astype(np.int64)] = True
    return m


def near_mask(t: np.ndarray, centers: np.ndarray, half_s: float) -> np.ndarray:
    """Messages within +-half_s of any center, whoever is involved."""
    if centers.size == 0:
        return np.zeros(t.size, bool)
    c = np.sort(centers)
    i = np.searchsorted(c, t)
    left = np.abs(t - c[np.clip(i - 1, 0, c.size - 1)])
    right = np.abs(c[np.clip(i, 0, c.size - 1)] - t)
    return np.minimum(left, right) <= half_s


def boot_counts(rng: np.random.Generator, n_clusters: int, n_boot: int) -> np.ndarray:
    """(n_boot, n_clusters) draw counts of a cluster bootstrap."""
    draws = rng.integers(0, n_clusters, size=(n_boot, n_clusters))
    W = np.zeros((n_boot, n_clusters))
    np.add.at(W, (np.repeat(np.arange(n_boot), n_clusters), draws.ravel()), 1.0)
    return W


def _q(x: np.ndarray, p: float) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(np.quantile(x, p)) if x.size else float("nan")


def v1_effect(ev: pl.DataFrame, flagged: np.ndarray, control: np.ndarray, cluster: str, n_boot: int, seed: int,
              prefix: str = "p_", measures: tuple[str, ...] = MEASURES, stratum_col: str = "stratum") -> dict:
    """Stratified flagged-minus-control difference of each measure with a cluster-bootstrap interval.

    Strata (window, group, realization, agent; `stratum_col`) count when they hold flagged and control
    messages. The flagged mean is the mean over flagged messages, the control mean the mean of the
    strata's control means weighted by their flagged messages, and the difference their difference.
    Measures missing from ev are skipped."""
    if (flagged & control).any():
        raise ValueError("a message cannot be flagged and a control")
    measures = tuple(m for m in measures if (f"{prefix}{m}" if m in CLASSES else m) in ev.columns)
    cols = {m: (f"{prefix}{m}" if m in CLASSES else m) for m in measures}
    df = (ev.select(pl.col(stratum_col).alias("stratum"), "actor_id", pl.col(cluster).alias("_cl"),
                    *[pl.col(c).alias(m) for m, c in cols.items()])
          .with_columns(pl.Series("_f", flagged), pl.Series("_c", control))
          .filter(pl.col("_f") | pl.col("_c")))
    agg = (df.group_by("stratum")
           .agg(pl.col("_cl").first(), pl.col("actor_id").first(), pl.col("_f").sum().alias("nF"),
                pl.col("_c").sum().alias("nC"),
                *[pl.col(m).filter(pl.col("_f")).sum().alias(f"sF_{m}") for m in measures],
                *[pl.col(m).filter(pl.col("_c")).sum().alias(f"sC_{m}") for m in measures])
           .filter((pl.col("nF") > 0) & (pl.col("nC") > 0)).sort("stratum"))
    res: dict = {"n_strata": agg.height, "n_flagged_msgs": int(agg["nF"].sum()) if agg.height else 0,
                 "n_control_msgs": int(agg["nC"].sum()) if agg.height else 0,
                 "n_clusters": int(agg["_cl"].n_unique()), "n_agents": int(agg["actor_id"].n_unique()),
                 "strata": set(agg["stratum"].to_list())}
    if agg.is_empty():
        return res | {"measures": {}}
    _, inv = np.unique(agg["_cl"].to_numpy(), return_inverse=True)
    C = int(inv.max()) + 1
    nF, nC = agg["nF"].to_numpy().astype(float), agg["nC"].to_numpy().astype(float)
    den = np.bincount(inv, weights=nF, minlength=C)
    W = boot_counts(np.random.default_rng(seed), C, n_boot)
    Wden = W @ den
    out = {}
    for m in measures:
        fm, cm = agg[f"sF_{m}"].to_numpy() / nF, agg[f"sC_{m}"].to_numpy() / nC
        fl = np.bincount(inv, weights=nF * fm, minlength=C)
        ct = np.bincount(inv, weights=nF * cm, minlength=C)
        bf, bc = (W @ fl) / Wden, (W @ ct) / Wden
        pf, pc = float(fl.sum() / den.sum()), float(ct.sum() / den.sum())
        out[m] = {"flagged_mean": pf, "control_mean": pc, "diff": pf - pc,
                  "diff_lo": _q(bf - bc, 0.025), "diff_hi": _q(bf - bc, 0.975),
                  "flagged_lo": _q(bf, 0.025), "flagged_hi": _q(bf, 0.975)}
    return res | {"measures": out}


def _seed(base: int, *parts: str) -> int:
    return int(zlib.crc32(":".join([str(base), *parts]).encode()))


def v1_subsets(f1: pl.DataFrame) -> list[tuple[str, pl.Expr]]:
    """Subsets of the V1 findings reported in monitor_v1.csv: all, each category, low and medium/high severity."""
    subs = [(ALL, pl.lit(True))]
    present = set(f1["category"].to_list())
    subs += [(f"category: {c}", pl.col("category") == c) for c in CATEGORIES if c in present]
    subs += [("severity: low", pl.col("severity") == "low"),
             ("severity: medium/high", pl.col("severity").is_in(list(SEVERE)))]
    return subs


AGENT_RULE = "outside the agent's V1 finding windows"
ANY_RULE = "outside every V1 finding window"
ALLCAT_RULE = "outside every finding window of the agent"


def run_v1(ev: pl.DataFrame, f: pl.DataFrame, fits: dict[tuple[str, str], WindowFit], n_boot: int, seed: int
           ) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """monitor_v1.csv rows, per-finding coverage (fid, n_flagged_msgs, used) and the main analysis' flags."""
    t, n = ev["t"].to_numpy(), ev.height
    aidx = actor_index(ev)
    f1 = f.filter(pl.col("v1"))
    f1_agents = f1["agent_ids"].to_list()
    rows, flags = [], {}

    def hits_of(sub: pl.DataFrame, half_s: float) -> list[np.ndarray]:
        return finding_hits(t, aidx, sub["agent_ids"].to_list(), sub["t"].to_numpy(), half_s)

    def analyse(analysis: str, half: float, control_rule: str, cluster: str = "realization_id",
                shares: str = "exact", subsets: list[tuple[str, pl.Expr]] | None = None,
                stratum_col: str = "stratum") -> None:
        half_s = half * 60.0
        all_hits = hits_of(f1, half_s)
        if control_rule == AGENT_RULE:
            control = ~union_mask(n, all_hits)
        elif control_rule == ANY_RULE:
            control = ~near_mask(t, f1["t"].to_numpy(), half_s)
        elif control_rule == ALLCAT_RULE:
            fa = f.filter(pl.col("ts_utc").is_not_null() & (pl.col("n_roster") >= 1))
            control = ~union_mask(n, hits_of(fa, half_s))
        else:
            raise ValueError(control_rule)
        strata = ev[stratum_col].to_numpy()
        for subset, expr in subsets if subsets is not None else v1_subsets(f1):
            mask = f1.with_columns(expr.alias("_m"))["_m"].to_numpy().astype(bool)
            sub_hits = [h for h, k in zip(all_hits, mask) if k]
            flagged = union_mask(n, sub_hits)
            co = partner_share(ev, fits, sub_hits, [a for a, k in zip(f1_agents, mask) if k], shares != "exact")
            res = v1_effect(ev.with_columns(pl.Series("co_involved", co)), flagged, control, cluster, n_boot,
                            _seed(seed, "v1", analysis, subset), prefix="p_" if shares == "exact" else "q_",
                            stratum_col=stratum_col)
            used = [bool(h.size and any(s in res["strata"] for s in strata[h])) for h in sub_hits]
            base = {"analysis": analysis, "subset": subset, "half_width_min": half, "cluster_unit": cluster,
                    "strata": stratum_col, "shares_from": shares, "control_rule": control_rule,
                    "n_findings": int(mask.sum()), "n_findings_with_msgs": sum(1 for h in sub_hits if h.size),
                    "n_findings_used": sum(used),
                    **{k: res[k] for k in ("n_flagged_msgs", "n_control_msgs", "n_strata", "n_clusters", "n_agents")}}
            for m in MEASURES:
                r = res["measures"].get(m, {})
                rows.append(base | {"measure": m, **{k: r.get(k) for k in ("flagged_mean", "control_mean", "diff",
                                                                            "diff_lo", "diff_hi")}})
            if analysis == MAIN and subset == ALL:
                flags.update(flagged=flagged, control=control, hits=all_hits, used=used)

    analyse(MAIN, HALF_MIN, AGENT_RULE)
    key_subsets = [(ALL, pl.lit(True)), (f"category: {CONFLICT}", pl.col("category") == CONFLICT)]
    analyse("strata also by hour of the run", HALF_MIN, AGENT_RULE, subsets=key_subsets, stratum_col="stratum_hour")
    analyse("controls outside every V1 finding window", HALF_MIN, ANY_RULE, subsets=key_subsets)
    analyse("controls outside every finding of the agent", HALF_MIN, ALLCAT_RULE, subsets=key_subsets)
    for h in HALF_MIN_SENS:
        analyse(f"half width {h:g} min", h, AGENT_RULE, subsets=key_subsets)
    analyse("clusters = run dates", HALF_MIN, AGENT_RULE, cluster="run_date", subsets=key_subsets)
    analyse("parents table (prob >= 0.01)", HALF_MIN, AGENT_RULE, shares="parents_table", subsets=key_subsets)

    cov = pl.DataFrame({"fid": f1["fid"].to_list(), "n_flagged_msgs": [int(h.size) for h in flags["hits"]],
                        "used": flags["used"]},
                       schema={"fid": pl.UInt32, "n_flagged_msgs": pl.Int64, "used": pl.Boolean})
    return pl.DataFrame(rows, infer_schema_length=None), cov, flags


# --- V2 -------------------------------------------------------------------------------------------------


def pair_percentiles(n_aa: np.ndarray) -> np.ndarray:
    """Mid-rank percentile of n_ij + n_ji among the K(K-1)/2 agent pairs, (..., K, K) with a nan
    diagonal; (#pairs below + half the #pairs equal, itself included) / #pairs, so a uniformly drawn
    pair has mean 0.5."""
    from scipy.stats import rankdata

    n_aa = np.asarray(n_aa, float)
    K = n_aa.shape[-1]
    out = np.full(n_aa.shape, np.nan)
    if K < 2:
        return out
    s = n_aa + np.swapaxes(n_aa, -1, -2)
    iu = np.triu_indices(K, 1)
    v = s[..., iu[0], iu[1]]
    pct = (rankdata(v, method="average", axis=-1) - 0.5) / v.shape[-1]
    out[..., iu[0], iu[1]] = pct
    out[..., iu[1], iu[0]] = pct
    return out


def mean_over_pairs(mat: np.ndarray, dims: np.ndarray) -> np.ndarray:
    """Mean of a (..., K, K) matrix over the pairs among `dims` (upper triangle)."""
    dims = np.sort(np.asarray(dims, np.int64))
    iu = np.triu_indices(dims.size, 1)
    return mat[..., dims[iu[0]], dims[iu[1]]].mean(-1)


def within_share_from_sizes(blocks: np.ndarray) -> float:
    """Share of all agent pairs inside one cluster: sum s(s - 1) / (K(K - 1))."""
    K = blocks.size
    s = np.bincount(blocks).astype(float)
    return float((s * (s - 1)).sum() / (K * (K - 1))) if K > 1 else float("nan")


def forced_blocks(n_aa: np.ndarray, k: int, seed: int) -> np.ndarray:
    """Module A's spectral clustering (avsd.hawkes.report.spectral_blocks: symmetrized N_AA without
    the diagonal, the same connectivity floor, kmeans labels, n_init 20) with k fixed instead of
    chosen by the eigengap; labels ordered by cluster size."""
    from sklearn.cluster import SpectralClustering

    K = n_aa.shape[0]
    if k <= 1 or K < max(4, k + 1):
        return np.zeros(K, np.int64)
    A = (n_aa + n_aa.T) / 2
    np.fill_diagonal(A, 0.0)
    A = A + 1e-6 * max(float(A.mean()), 1e-12) * (1 - np.eye(K))
    lab = SpectralClustering(k, affinity="precomputed", random_state=seed, assign_labels="kmeans",
                             n_init=20).fit_predict(A)
    order = np.argsort(-np.bincount(lab, minlength=k), kind="stable")
    remap = np.empty(k, np.int64)
    remap[order] = np.arange(k)
    return remap[lab]


def pair_instances(f: pl.DataFrame, fits: dict[tuple[str, str], WindowFit],
                   times: dict[tuple[str, str, str], np.ndarray], half_s: float) -> pl.DataFrame:
    """One row per (finding, pair of its roster agents): the window and group in which both agents are
    dimensions (the one with more of the pair's messages within +-half_s, then on the date, when
    several qualify), with dimension indices ia < ib, or the reason the pair is not covered."""
    rows = []
    wins = sorted(fits.values(), key=lambda w: (w.date_start, w.group))
    for r in f.filter(pl.col("n_roster") >= 2).iter_rows(named=True):
        d, tc = r["date"], r["t"]
        cands = [w for w in wins if w.covers(d)]
        for a, b in itertools.combinations(r["agent_ids"], 2):
            base = {"fid": r["fid"], "date": d, "category": r["category"], "severity": r["severity"]}
            opts = [w for w in cands if a in w.dim and b in w.dim]
            if not opts:
                rows.append(base | {"window_id": None, "group": None, "ia": None, "ib": None, "covered": False,
                                    "reason": "no fitted window on the date" if not cands else "agent not a dimension"})
                continue

            def score(w: WindowFit) -> tuple[int, int]:
                near = day = 0
                for x in (a, b):
                    ts = times.get((w.window_id, w.group, x))
                    if ts is not None:
                        near += int(np.searchsorted(ts, tc + half_s, "right")
                                    - np.searchsorted(ts, tc - half_s, "left"))
                        day += int(np.searchsorted(ts, tc + 43200, "right") - np.searchsorted(ts, tc - 43200, "left"))
                return near, day

            w = max(opts, key=score)
            ia, ib = sorted((w.dim[a], w.dim[b]))
            rows.append(base | {"window_id": w.window_id, "group": w.group, "ia": ia, "ib": ib, "covered": True,
                                "reason": ""})
    schema = {"fid": pl.UInt32, "date": pl.Date, "category": pl.String, "severity": pl.String,
              "window_id": pl.String, "group": pl.String, "ia": pl.Int64, "ib": pl.Int64, "covered": pl.Boolean,
              "reason": pl.String}
    return pl.DataFrame(rows, schema=schema)


def _stat_row(val_pt: np.ndarray, val_b: np.ndarray, ref_all_pt: np.ndarray, ref_all_b: np.ndarray,
              ref_act_pt: np.ndarray, ref_act_b: np.ndarray, clusters: np.ndarray, n_boot: int, seed: int) -> dict:
    """Mean of a per-instance value with cluster-bootstrap intervals, against two references.

    *_b are (n, n_boot): the value in the bootstrap draw's module A replicate. Intervals: lo/hi resample
    clusters and take the replicate values; lo_point_n/hi_point_n resample clusters only."""
    _, inv = np.unique(clusters, return_inverse=True)
    W = boot_counts(np.random.default_rng(seed), int(inv.max()) + 1, n_boot)[:, inv]   # (B, n)
    sw = W.sum(1)

    def bmean(x: np.ndarray) -> np.ndarray:
        return (W * (x.T if x.ndim == 2 else x[None, :])).sum(1) / sw

    v, a, c = bmean(val_b), bmean(ref_all_b), bmean(ref_act_b)
    vp = bmean(val_pt)
    out = {"value": float(val_pt.mean()), "lo": _q(v, 0.025), "hi": _q(v, 0.975),
           "lo_point_n": _q(vp, 0.025), "hi_point_n": _q(vp, 0.975),
           "ref_all_pairs": float(ref_all_pt.mean()), "ref_active_pairs": float(ref_act_pt.mean())}
    out["diff_all"] = out["value"] - out["ref_all_pairs"]
    out["diff_all_lo"], out["diff_all_hi"] = _q(v - a, 0.025), _q(v - a, 0.975)
    out["diff_active"] = out["value"] - out["ref_active_pairs"]
    out["diff_active_lo"], out["diff_active_hi"] = _q(v - c, 0.025), _q(v - c, 0.975)
    return out


@dataclass
class PairTables:
    """Per covered instance: rank and reference values, point and per bootstrap draw."""

    inst: pl.DataFrame
    pct_pt: np.ndarray
    pct_b: np.ndarray
    all_top_pt: np.ndarray
    all_top_b: np.ndarray
    act_pt: np.ndarray
    act_b: np.ndarray
    act_top_pt: np.ndarray
    act_top_b: np.ndarray
    n_replicates: dict[tuple[str, str], int]


def pair_tables(inst: pl.DataFrame, fits: dict[tuple[str, str], WindowFit],
                active: dict[tuple[str, str, date], set[str]], n_boot: int) -> PairTables:
    """Percentile ranks of the covered instances in module A's point estimate and in replicate b % R of
    each draw b, and the two references (all pairs of the window; pairs of the agents with a message in
    the group on the finding's date, all pairs when fewer than two)."""
    cov = inst.filter(pl.col("covered")).with_row_index("_k")
    n = cov.height
    out = {k: np.zeros(n) for k in ("pct_pt", "all_top_pt", "act_pt", "act_top_pt")}
    out |= {k: np.zeros((n, n_boot)) for k in ("pct_b", "all_top_b", "act_b", "act_top_b")}
    n_rep = {}
    b = np.arange(n_boot)
    for (wid, grp), part in cov.partition_by(["window_id", "group"], as_dict=True).items():
        w = fits[(wid, grp)]
        P0 = pair_percentiles(w.n)
        R = 0 if w.n_boot is None else w.n_boot.shape[0]
        PR = pair_percentiles(w.n_boot) if R else P0[None]
        n_rep[(wid, grp)] = R
        rb = b % PR.shape[0]
        k, ia, ib = part["_k"].to_numpy(), part["ia"].to_numpy(), part["ib"].to_numpy()
        out["pct_pt"][k] = P0[ia, ib]
        out["pct_b"][k] = PR[rb][:, ia, ib].T
        all_dims = np.arange(w.K)
        top0, topR = mean_over_pairs((P0 >= TOP).astype(float), all_dims), mean_over_pairs((PR >= TOP).astype(float),
                                                                                             all_dims)
        out["all_top_pt"][k] = top0
        out["all_top_b"][k] = topR[rb][None, :]
        for (d,), sub in part.partition_by("date", as_dict=True).items():
            act = np.array(sorted(w.dim[x] for x in active.get((wid, grp, d), set()) if x in w.dim), np.int64)
            dims = act if act.size >= 2 else all_dims
            kk = sub["_k"].to_numpy()
            out["act_pt"][kk] = mean_over_pairs(P0, dims)
            out["act_b"][kk] = mean_over_pairs(PR, dims)[rb][None, :]
            out["act_top_pt"][kk] = mean_over_pairs((P0 >= TOP).astype(float), dims)
            out["act_top_b"][kk] = mean_over_pairs((PR >= TOP).astype(float), dims)[rb][None, :]
    return PairTables(cov, n_replicates=n_rep, **out)


def v2_subsets(f1: pl.DataFrame) -> list[tuple[str, pl.Expr]]:
    present = set(f1.filter(pl.col("n_roster") >= 2)["category"].to_list())
    return [(ALL, pl.lit(True))] + [(f"category: {c}", pl.col("category") == c) for c in CATEGORIES if c in present]


def run_v2(f: pl.DataFrame, ev: pl.DataFrame, fits: dict[tuple[str, str], WindowFit], n_boot: int, seed: int
           ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict]:
    """monitor_v2.csv rows, monitor_v2_pairs.csv, the instances and facts for the QA report."""
    f1 = f.filter(pl.col("v1"))
    times = {(w, g, a): np.sort(np.asarray(t)) for w, g, a, t in
             ev.group_by("window_id", "group", "actor_id").agg("t").iter_rows()}
    active = {(w, g, d): set(a) for w, g, d, a in
              ev.group_by("window_id", "group", "run_date").agg(pl.col("actor_id").unique()).iter_rows()}
    inst = pair_instances(f1, fits, times, HALF_MIN * 60.0)
    pt = pair_tables(inst, fits, active, n_boot)
    cov = pt.inst
    rows = []
    for subset, expr in v2_subsets(f1):
        cats = f1.filter(expr)["fid"]
        m = cov.select(pl.col("fid").is_in(cats.implode())).to_series().to_numpy()
        n_all = int(inst.filter(pl.col("fid").is_in(cats.implode())).height)
        if not m.any():
            continue
        sub = cov.filter(m)
        counts = {"n_instances": int(m.sum()),
                  "n_unique_pairs": int(sub.select("window_id", "group", "ia", "ib").unique().height),
                  "n_findings": int(sub["fid"].n_unique()), "n_dates": int(sub["date"].n_unique()),
                  "n_windows": int(sub.select("window_id", "group").unique().height),
                  "n_not_covered": n_all - int(m.sum())}
        clusters = sub["date"].to_numpy()
        for stat, val_pt, val_b, a_pt, a_b, c_pt, c_b in (
                ("mean_percentile", pt.pct_pt, pt.pct_b, np.full(cov.height, 0.5), np.full((cov.height, n_boot), 0.5),
                 pt.act_pt, pt.act_b),
                ("top_quartile_share", (pt.pct_pt >= TOP).astype(float), (pt.pct_b >= TOP).astype(float),
                 pt.all_top_pt, pt.all_top_b, pt.act_top_pt, pt.act_top_b)):
            r = _stat_row(val_pt[m], val_b[m], a_pt[m], a_b[m], c_pt[m], c_b[m], clusters, n_boot,
                          _seed(seed, "v2", subset, stat))
            rows.append({"part": "rank of n_ij + n_ji", "subset": subset, "unit": "finding pair", "blocks": "",
                         "statistic": stat, **r, **counts})
        # Unique pairs: each (window, pair) once, resampled as independent units.
        u = (sub.with_columns(pl.Series("_m", np.flatnonzero(m)))
             .group_by("window_id", "group", "ia", "ib", maintain_order=True).agg(pl.col("_m")))
        first = np.array([x[0] for x in u["_m"].to_list()], np.int64)
        act_pt = np.array([pt.act_pt[x].mean() for x in u["_m"].to_list()])
        act_b = np.vstack([pt.act_b[x].mean(0) for x in u["_m"].to_list()])
        r = _stat_row(pt.pct_pt[first], pt.pct_b[first], np.full(first.size, 0.5), np.full((first.size, n_boot), 0.5),
                      act_pt, act_b, np.arange(first.size), n_boot, _seed(seed, "v2u", subset))
        rows.append({"part": "rank of n_ij + n_ji", "subset": subset, "unit": "unique pair", "blocks": "",
                     "statistic": "mean_percentile", **r, **counts})

    # Within versus between spectral clusters: module A's blocks, then forced k.
    schemes = {"module A (eigengap)": {k: w.blocks for k, w in fits.items()}}
    for k in FORCED_K:
        schemes[f"forced k = {k}"] = {key: forced_blocks(w.n, k, seed) for key, w in fits.items()}
    multi = {name: sum(1 for b in s.values() if np.unique(b).size > 1) for name, s in schemes.items()}
    for subset, expr in ((f"category: {CONFLICT}", pl.col("category") == CONFLICT), (ALL, pl.lit(True))):
        cats = f1.filter(expr)["fid"]
        m = cov.select(pl.col("fid").is_in(cats.implode())).to_series().to_numpy()
        if not m.any():
            continue
        sub = cov.filter(m)
        counts = {"n_instances": int(m.sum()),
                  "n_unique_pairs": int(sub.select("window_id", "group", "ia", "ib").unique().height),
                  "n_findings": int(sub["fid"].n_unique()), "n_dates": int(sub["date"].n_unique()),
                  "n_windows": int(sub.select("window_id", "group").unique().height),
                  "n_not_covered": int(inst.filter(pl.col("fid").is_in(cats.implode())).height) - int(m.sum())}
        for name, scheme in schemes.items():
            val, ref_all, ref_act = np.zeros(sub.height), np.zeros(sub.height), np.zeros(sub.height)
            for i, r in enumerate(sub.iter_rows(named=True)):
                w = fits[(r["window_id"], r["group"])]
                bl = scheme[w.key]
                same = (bl[:, None] == bl[None, :]).astype(float)
                val[i] = float(bl[r["ia"]] == bl[r["ib"]])
                ref_all[i] = within_share_from_sizes(bl)
                act = np.array(sorted(w.dim[x] for x in active.get((w.window_id, w.group, r["date"]), set())
                                      if x in w.dim), np.int64)
                ref_act[i] = float(mean_over_pairs(same, act if act.size >= 2 else np.arange(w.K)))
            used = set(sub.select("window_id", "group").unique().iter_rows())
            row = _stat_row(val, np.repeat(val[:, None], n_boot, 1), ref_all, np.repeat(ref_all[:, None], n_boot, 1),
                            ref_act, np.repeat(ref_act[:, None], n_boot, 1), sub["date"].to_numpy(), n_boot,
                            _seed(seed, "v2b", subset, name))
            row["lo_point_n"] = row["hi_point_n"] = float("nan")
            rows.append({"part": "within one spectral cluster", "subset": subset, "unit": "finding pair",
                         "blocks": name, "statistic": "within_share", **row, **counts,
                         "n_windows_multi_cluster": sum(1 for k in used if np.unique(scheme[k]).size > 1)})

    pairs = pair_table(cov, f1, fits, pt)
    facts = {"instances": inst, "multi_cluster": multi, "n_replicates": pt.n_replicates}
    return pl.DataFrame(rows, infer_schema_length=None), pairs, inst, facts


def pair_table(cov: pl.DataFrame, f1: pl.DataFrame, fits: dict[tuple[str, str], WindowFit], pt: PairTables
               ) -> pl.DataFrame:
    """One row per flagged (window, pair): n in both directions, the percentile with its range over
    module A's bootstrap replicates, module A's clusters and the findings by category."""
    rows = []
    sev = dict(zip(f1["fid"].to_list(), f1["severity"].to_list()))
    ranks: dict[tuple[str, str], tuple[np.ndarray, np.ndarray | None]] = {}
    for (wid, grp, ia, ib), part in cov.partition_by(["window_id", "group", "ia", "ib"], as_dict=True).items():
        w = fits[(wid, grp)]
        if w.key not in ranks:
            ranks[w.key] = (pair_percentiles(w.n), None if w.n_boot is None else pair_percentiles(w.n_boot))
        p0, pr = ranks[w.key]
        cats = part["category"].to_list()
        reps = None if pr is None else pr[:, ia, ib]
        rows.append({
            "window_id": wid, "group": grp, "agent_a": w.agent_names[ia], "agent_b": w.agent_names[ib],
            "n_a_from_b": float(w.n[ia, ib]), "n_b_from_a": float(w.n[ib, ia]),
            "n_sum": float(w.n[ia, ib] + w.n[ib, ia]), "percentile": float(p0[ia, ib]),
            "percentile_lo": _q(reps, 0.025) if reps is not None else float("nan"),
            "percentile_hi": _q(reps, 0.975) if reps is not None else float("nan"),
            "cluster_a": int(w.blocks[ia]) + 1, "cluster_b": int(w.blocks[ib]) + 1,
            "n_findings": part["fid"].n_unique(),
            "n_conflict": part.filter(pl.col("category") == CONFLICT)["fid"].n_unique(),
            "n_medium_high": sum(1 for x in set(part["fid"].to_list()) if sev.get(x) in SEVERE),
            "by_category": ";".join(f"{c}:{cats.count(c)}" for c in CATEGORIES if c in cats),
            "first_date": part["date"].min(), "last_date": part["date"].max(), "K": w.K,
        })
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, infer_schema_length=None).sort(["n_conflict", "n_findings", "n_sum"],
                                                             descending=True)


# --- coverage ---------------------------------------------------------------------------------------------


def coverage_table(f: pl.DataFrame, fits: dict[tuple[str, str], WindowFit], v1_cov: pl.DataFrame,
                   inst: pl.DataFrame) -> pl.DataFrame:
    """Per category (and all): V1/V2 findings, how many fall on a date of a fitted window, have a roster
    agent that is a dimension there, have flagged messages, enter V1, and their covered pairs."""
    f1 = f.filter(pl.col("v1")).join(v1_cov, on="fid", how="left")
    wins = list(fits.values())
    in_win, has_dim = [], []
    for d, ags in f1.select("date", "agent_ids").iter_rows():
        ws = [w for w in wins if w.covers(d)]
        in_win.append(bool(ws))
        has_dim.append(any(a in w.dim for w in ws for a in ags))
    f1 = f1.with_columns(pl.Series("in_window", in_win), pl.Series("agent_is_dimension", has_dim))
    pairs = inst.group_by("fid").agg(pl.len().alias("pairs"), pl.col("covered").sum().alias("pairs_covered"))
    f1 = f1.join(pairs, on="fid", how="left").with_columns(pl.col("pairs", "pairs_covered").fill_null(0))
    rows = []
    for name, sub in [(ALL, f1)] + [(c, f1.filter(pl.col("category") == c)) for c in CATEGORIES]:
        if sub.is_empty():
            continue
        rows.append({"category": name, "findings": sub.height,
                     "with_unmatched_names": int((sub["n_unmatched"] > 0).sum()),
                     "date_in_fitted_window": int(sub["in_window"].sum()),
                     "agent_is_dimension": int(sub["agent_is_dimension"].sum()),
                     "with_flagged_msgs": int((sub["n_flagged_msgs"].fill_null(0) > 0).sum()),
                     "used_in_v1": int(sub["used"].fill_null(False).sum()),
                     "pairs": int(sub["pairs"].sum()), "pairs_covered": int(sub["pairs_covered"].sum())})
    return pl.DataFrame(rows)


# --- module C status (V3) ---------------------------------------------------------------------------------


def v3_status(tables: Path) -> list[str]:
    """What module C (avsd.changepoint, round 2 "monitor sets") holds for V3, read from its outputs."""
    lines = []
    try:
        s = pl.read_csv(tables / "changepoint_series.csv", infer_schema_length=0)
        mon = s.filter(pl.col("series_id").str.starts_with("monitor:"))
        ok = mon.filter(pl.col("skipped").is_null() | (pl.col("skipped") == ""))
        lines.append(f"- Series: {mon.height} monitor count series (category by all agents and by model family), "
                     f"{ok.height} analysed (`changepoint_series.csv`, level `external`).")
    except Exception as e:     # module C may be mid-rerun
        lines.append(f"- Series: changepoint_series.csv not readable ({type(e).__name__}).")
    try:
        c = pl.read_csv(tables / "changepoints.csv", columns=["series_id", "level", "method", "monitor_covered_days"],
                        infer_schema_length=0)
        l2 = c.filter(pl.col("method") == "pelt_l2")
        ann = l2.filter(pl.col("monitor_covered_days").cast(pl.Int64, strict=False).fill_null(0) > 0)
        own = ann.filter(pl.col("level") != "external")
        lines.append(f"- Annotations: {ann.height:,} PELT l2 change points have a monitor-covered run day within w "
                     f"({own.height:,} on module C's own series); `changepoints.csv` carries counts by category and "
                     "severity, `changepoint_monitor_findings.parquet` the change point and finding id pairs.")
    except Exception as e:
        lines.append(f"- Annotations: changepoints.csv not readable ({type(e).__name__}).")
    try:
        a = pl.read_csv(tables / "changepoint_alignment.csv", columns=["entry_set"], infer_schema_length=0)
        sets = sorted(x for x in a["entry_set"].unique().to_list() if x and x.startswith("monitor"))
        lines.append(f"- Alignment test: entry sets {', '.join(sets) if sets else 'none'} in "
                     "`changepoint_alignment.csv`.")
    except Exception as e:
        lines.append(f"- Alignment test: changepoint_alignment.csv not readable ({type(e).__name__}).")
    return lines


# --- report -----------------------------------------------------------------------------------------------


def _f(x, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    return "n/a" if not np.isfinite(x) else f"{x:.{nd}f}"


def _ci(v, lo, hi, nd: int = 3) -> str:
    return f"{_f(v, nd)} [{_f(lo, nd)}, {_f(hi, nd)}]"


def _table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|",
            *["| " + " | ".join(str(c) for c in r) + " |" for r in rows]]


def _v1_get(v1: pl.DataFrame, analysis: str, subset: str, measure: str) -> dict | None:
    r = v1.filter((pl.col("analysis") == analysis) & (pl.col("subset") == subset) & (pl.col("measure") == measure))
    return r.row(0, named=True) if r.height else None


def write_report(path: Path, ctx: dict) -> None:
    v1, v2, pairs, cov, checks = ctx["v1"], ctx["v2"], ctx["pairs"], ctx["coverage"], ctx["checks"]
    L = ["# QA: external validation of module A against the LLM monitor (V1, V2)", "",
         f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `python -m avsd.validate.monitor_hawkes` "
         f"in {ctx['secs']:.0f} s. Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village; "
         f"monitor findings from theaidigest.org/village/monitor (fetched {ctx['fetched']}).",
         "",
         "The monitor is a second reading of the same days by an LLM, not ground truth; its precision is unknown. "
         "Agreement or disagreement below says how module A's fit and that reading relate. Nothing here identifies "
         "a cause. Only aggregates, AI agent names, categories, severities and dates appear; finding and message "
         "text, human names and parent probabilities stay in `data/`.", ""]

    L += ["## 1. Inputs", ""]
    fx = ctx["findings_facts"]
    L += [f"- Findings in the pinned export: {fx['in_export']:,}; repeats dropped (same category, timestamp and roster "
          f"agents): {fx['dups']:,}; kept {fx['kept']:,}. V1/V2 set (conflict with at least one roster agent, or any "
          f"category with at least two): {fx['v1']:,}, of which conflict {fx['v1_conflict']:,}.",
          f"- Roster agents only: names that are not roster agents (humans, outside accounts, AI agents added after "
          f"the export) are counted, never listed; {fx['v1_unmatched']:,} V1/V2 findings name at least one.",
          "- Timestamps: findings that carry a reading-window label also carry an exact time; the share of those times "
          "inside the label's UTC window is " + "; ".join(
              f"{k} {v[0]:,} of {v[1]:,}" for k, v in sorted(ctx["labels"].items())) + ".",
          f"- Hawkes windows (accepted goal windows of module A whose dates hold findings): {len(checks)}. Per-message "
          "parent-class probabilities are recomputed from the module A fits (`data/interim/hawkes_fit/fits`).", ""]
    L += _table(["Window", "Group", "Dates", "K", "Messages", "Realizations", "Other-agent share",
                 "Mass below 0.01 (mean)", "Stored rows matched", "Max abs diff to stored"],
                [[c["window_id"], c["group"], f"{c['date_start']} to {c['date_end']}", c["K"], f"{c['events']:,}",
                  c["realizations"], _f(c["share_other_agents"]), _f(c["dropped_mass_mean"]),
                  f"{c.get('stored_rows', 0) - c.get('only_stored', 0):,} of {c.get('stored_rows', 0):,}",
                  f"{c.get('max_abs_diff', float('nan')):.1e}"] for c in checks])
    L += ["", f"Window shares recomputed from the messages agree with `hawkes_windows.csv` to {ctx['share_check']:.1e} "
              "(largest absolute difference over the five classes; the CSV has four decimals). Messages of a window "
              f"missing from `hawkes_parents.parquet`: {sum(c.get('events_not_stored', 0) for c in checks)}. Rows "
              f"only in the recomputation (probabilities next to 0.01): "
              f"{sum(c.get('only_recomputed', 0) for c in checks)}.", ""]

    L += ["## 2. Coverage", "",
          "Per category of the V1/V2 set: findings, those naming a non-roster participant, those on a date of an "
          "accepted fitted window, those with a roster agent that is a dimension of such a window, those with at "
          "least one message of an involved agent within +-30 min in a fitted group, those that enter V1 (a flagged "
          "message in a stratum with controls), and the agent pairs of V2 with how many lie in one fitted group.", ""]
    L += _table(["Category", "Findings", "Non-roster names", "Date in fitted window", "Agent is a dimension",
                 "Flagged messages", "Used in V1", "Pairs", "Pairs covered"],
                [[r["category"], r["findings"], r["with_unmatched_names"], r["date_in_fitted_window"],
                  r["agent_is_dimension"], r["with_flagged_msgs"], r["used_in_v1"], r["pairs"], r["pairs_covered"]]
                 for r in cov.iter_rows(named=True)])
    reasons = ctx["instances"].filter(~pl.col("covered")).group_by("reason").len().sort("len", descending=True)
    if reasons.height:
        L += ["", "Pairs not covered: " + "; ".join(f"{r} {n:,}" for r, n in reasons.iter_rows()) + "."]
    L += [""]

    L += ["## 3. V1: parent classes of the involved agents' messages near a finding", "",
          "Flagged: messages of an involved agent within +-30 min of a finding. Control: the same agent's messages in "
          "the same realization and group outside the +-30 min window of every V1 finding that involves it. Values are "
          "mean posterior shares of each parent class (module A, exact); the control mean is weighted by the stratum's "
          "flagged messages; differences are flagged minus control with 95% percentile intervals from "
          f"{ctx['n_boot']:,} draws of realizations. Co-involved: the share on messages of the agents it was flagged "
          "with (the other roster agents of the findings that flag the agent in that stratum), for flagged and control "
          "messages alike; it is part of the other-agent share. It is specific within one category (a conflict "
          f"finding names a median of {_f(fx.get('conflict_median_agents'), 0)} roster agents); in the pooled rows a "
          "stratum's partner set is the union over many findings and grows toward all other agents. Other and own "
          "msgs: other agents' and the agent's own messages in the group in the 10 min before a message (context for "
          "the candidate parents).", ""]
    rows = []
    for subset in v1.filter(pl.col("analysis") == MAIN)["subset"].unique(maintain_order=True).to_list():
        o = _v1_get(v1, MAIN, subset, "other_agents")
        if o is None:
            continue
        rows.append([subset, f"{o['n_findings_used']} of {o['n_findings']}", f"{o['n_flagged_msgs']:,}",
                     f"{o['n_control_msgs']:,}", o["n_strata"], o["n_clusters"],
                     f"{_f(o.get('flagged_mean'))} / {_f(o.get('control_mean'))}",
                     *[_diff(_v1_get(v1, MAIN, subset, m)) for m in MEASURES]])
    L += _table(["Subset", "Findings used", "Flagged msgs", "Control msgs", "Strata", "Realizations",
                 "Other agents: flagged / control", "Other agents diff", "Co-involved diff", "Human diff",
                 "System diff", "Self diff", "Baseline diff", "Other msgs (10 min) diff",
                 "Own msgs (10 min) diff"], rows)
    L += ["", "Intervals are not adjusted for the number of subsets. Severity rows pool categories.", ""]

    L += ["## 4. V1 sensitivity", ""]
    rows = []
    for an in v1["analysis"].unique(maintain_order=True).to_list():
        for subset in (ALL, f"category: {CONFLICT}"):
            o = _v1_get(v1, an, subset, "other_agents")
            if o is None:
                continue
            rows.append([an, subset, f"{o['n_flagged_msgs']:,}", f"{o['n_control_msgs']:,}", o["n_strata"],
                         o["n_clusters"], _diff(o), *[_diff(_v1_get(v1, an, subset, m))
                                                      for m in ("co_involved", "self", "human", "system")]])
    L += _table(["Analysis", "Subset", "Flagged msgs", "Control msgs", "Strata", "Clusters", "Other agents diff",
                 "Co-involved diff", "Self diff", "Human diff", "System diff"], rows)
    L += ["", "Strata also by hour of the run compare a flagged message only with the agent's control messages of the "
              "same hour since the realization's start (time of day). Controls outside every V1 finding window drop "
              "the agent's messages near any V1 finding, whoever it involves; controls outside every finding of the "
              "agent drop its messages near any finding at all (all categories, also single-agent ones). The "
              "parents-table row uses `hawkes_parents.parquet` as stored (parents with prob >= 0.01, not "
              "renormalised).", ""]

    L += ["## 5. V2: rank of the flagged pairs in N_AA", "",
          "Percentile rank of n_ij + n_ji of each pair of a finding's roster agents among all K(K-1)/2 pairs of its "
          "fitting window (mid-ranks; a uniformly drawn pair has mean 0.5 and a top-quartile share near 0.25). "
          "Active pairs: pairs of the agents with a message in that group on the finding's date. Interval: "
          f"{ctx['n_boot']:,} draws that resample the findings' run dates and take n from one module A bootstrap "
          "replicate each; 'point n' resamples dates only. Unique pairs count each (window, pair) once and are "
          "resampled as units.", ""]
    rows = []
    for r in v2.filter(pl.col("part") == "rank of n_ij + n_ji").iter_rows(named=True):
        rows.append([r["subset"], r["unit"], r["statistic"], r["n_instances"] if r["unit"] == "finding pair"
                     else r["n_unique_pairs"], r["n_dates"], _ci(r["value"], r["lo"], r["hi"]),
                     f"[{_f(r['lo_point_n'])}, {_f(r['hi_point_n'])}]", _f(r["ref_all_pairs"]),
                     _f(r["ref_active_pairs"]), _ci(r["diff_active"], r["diff_active_lo"], r["diff_active_hi"])])
    L += _table(["Subset", "Unit", "Statistic", "n", "Dates", "Value [95% CI]", "CI, point n", "All pairs",
                 "Active pairs", "Minus active pairs"], rows)
    L += [""]

    L += ["## 6. V2: conflicts within versus between spectral clusters", ""]
    mc = ctx["v2_facts"]["multi_cluster"]
    L += [f"Module A's eigengap rule (SPEC 5.5, `hawkes_blocks.csv`) gives more than one cluster in "
          f"{mc.get('module A (eigengap)', 0)} of the {len(checks)} windows used here, so with its clusters the within "
          "share of conflict pairs and the share expected from cluster sizes are both 1 wherever a single cluster was "
          "found: the comparison is not informative there. Partitions forced to k clusters with module A's procedure "
          "(a sensitivity, not module A's choice) give: " + ", ".join(
              f"{k} {v} windows with more than one cluster" for k, v in mc.items() if k != "module A (eigengap)") + ".",
          "Forced clusters are built from N_AA itself, so a pair inside one cluster tends to have a high n_ij + n_ji; "
          "these rows restate the rank result in cluster terms.", ""]
    rows = []
    for r in v2.filter(pl.col("part") == "within one spectral cluster").iter_rows(named=True):
        rows.append([r["subset"], r["blocks"], r["n_instances"], r["n_dates"], r.get("n_windows_multi_cluster"),
                     _ci(r["value"], r["lo"], r["hi"]), _f(r["ref_all_pairs"]),
                     _ci(r["diff_all"], r["diff_all_lo"], r["diff_all_hi"]), _f(r["ref_active_pairs"]),
                     _ci(r["diff_active"], r["diff_active_lo"], r["diff_active_hi"])])
    L += _table(["Subset", "Clusters", "Pairs", "Dates", "Windows with >1 cluster", "Within share [95% CI]",
                 "Expected from sizes", "Minus expected", "Active pairs", "Minus active pairs"], rows)
    L += [""]

    L += ["## 7. Flagged pairs", "",
          "The 15 pairs with the most conflict findings, then the most findings (`tables/monitor_v2_pairs.csv` lists "
          "all). n_a_from_b is the expected number of a's messages triggered by one message of b. The percentile range "
          "is over module A's bootstrap replicates.", ""]
    if pairs.height:
        L += _table(["Window", "Group", "Agent a", "Agent b", "n_a_from_b", "n_b_from_a", "Percentile [range]",
                     "Conflict findings", "All findings", "Dates"],
                    [[r["window_id"], r["group"], r["agent_a"], r["agent_b"], _f(r["n_a_from_b"]), _f(r["n_b_from_a"]),
                      _ci(r["percentile"], r["percentile_lo"], r["percentile_hi"], 2), r["n_conflict"], r["n_findings"],
                      f"{r['first_date']} to {r['last_date']}"] for r in pairs.head(15).iter_rows(named=True)])
    L += [""]

    L += ["## 8. V3 (module C): status", "",
          "V3 lives in module C (`avsd.changepoint.monitor`, round 2 \"monitor sets\", docs/decisions.md); this "
          "command does not run or change it. Current module C outputs:", ""]
    L += ctx["v3"]
    L += ["- Not done as planned: the plan listed a paraphrased heading per finding next to each change point. "
          "Module C keeps ids, categories, severities, confidences and offsets only (finding text can name people), "
          "so headings are not shown.",
          "- Added beyond the plan: high-severity-only entry sets, because medium/high findings fall on almost every "
          "covered run day and cannot discriminate at w >= 1; monitor sets are annotations, never causes (`cause` "
          "stays CHANGELOG-only).", ""]

    L += ["## 9. Reading", ""]
    L += ctx["reading"]
    L += ["", "## 10. Outputs", "",
          "- `outputs/tables/monitor_v1.csv`: V1 by analysis, subset and measure (flagged and control means, "
          "difference and interval, counts).",
          "- `outputs/tables/monitor_v2.csv`: V2 rank statistics and within-cluster shares with references and "
          "intervals.",
          "- `outputs/tables/monitor_v2_pairs.csv`: one row per flagged (window, pair).",
          "- `data/interim/monitor_validation/` (private): per-message parent-class probabilities and flags, "
          "per-finding coverage, pair instances.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _says(lo, hi) -> str:
    if lo is None or hi is None or not (np.isfinite(lo) and np.isfinite(hi)):
        return "no interval"
    return "above 0" if lo > 0 else "below 0" if hi < 0 else "covers 0"


def _diff(r: dict | None) -> str:
    return _ci(r.get("diff"), r.get("diff_lo"), r.get("diff_hi")) if r and r.get("diff") is not None else "n/a"


def reading_lines(v1: pl.DataFrame, v2: pl.DataFrame) -> list[str]:
    """Plain statements of the headline numbers, with the direction of each interval."""
    out = []
    for subset in (ALL, f"category: {CONFLICT}"):
        o = _v1_get(v1, MAIN, subset, "other_agents")
        if o is None or o.get("diff") is None:
            continue
        g = {m: _v1_get(v1, MAIN, subset, m) for m in MEASURES}
        hr = _v1_get(v1, "strata also by hour of the run", subset, "other_agents")
        out.append(f"- V1, {subset}: other-agent share near a finding minus the same agents' other messages of the "
                   f"realization {_diff(o)} ({_says(o['diff_lo'], o['diff_hi'])}; {o['n_flagged_msgs']:,} flagged and "
                   f"{o['n_control_msgs']:,} control messages in {o['n_clusters']} realizations); within the same hour "
                   f"of the run {_diff(hr)}. Co-involved agents {_diff(g['co_involved'])}, self {_diff(g['self'])}, "
                   f"baseline {_diff(g['baseline'])}, human {_diff(g['human'])}, system {_diff(g['system'])}. In the "
                   f"10 min before a message: other agents' messages {_diff(g['other_msgs_10min'])}, the agent's own "
                   f"{_diff(g['own_msgs_10min'])}.")
    for subset in (f"category: {CONFLICT}", ALL):
        r = v2.filter((pl.col("part") == "rank of n_ij + n_ji") & (pl.col("subset") == subset)
                      & (pl.col("unit") == "finding pair") & (pl.col("statistic") == "mean_percentile"))
        if r.height:
            r = r.row(0, named=True)
            out.append(f"- V2, {subset}: mean percentile of the flagged pairs {_ci(r['value'], r['lo'], r['hi'])} "
                       f"(n = {r['n_instances']:,} pairs of {r['n_findings']:,} findings on {r['n_dates']} dates); "
                       "minus the active-pair reference "
                       f"{_ci(r['diff_active'], r['diff_active_lo'], r['diff_active_hi'])} "
                       f"({_says(r['diff_active_lo'], r['diff_active_hi'])}).")
    b = v2.filter((pl.col("part") == "within one spectral cluster") & (pl.col("blocks") == "module A (eigengap)")
                  & (pl.col("subset") == f"category: {CONFLICT}"))
    if b.height:
        r = b.row(0, named=True)
        out.append(f"- V2, conflicts within one of module A's clusters: {_f(r['value'])} against "
                   f"{_f(r['ref_all_pairs'])} expected from the cluster sizes, with "
                   f"{r.get('n_windows_multi_cluster', 0)} of the {r['n_windows']} windows holding the conflict pairs "
                   "split into more than one cluster.")
    out.append("- A share is a posterior attribution under module A's fit, so it moves with the candidate parents "
               "around a message (the 10-min counts) as well as with n. A difference between flagged and control "
               "messages says how module A reads the stretches the monitor flags, checked against an independent "
               "reading; it does not say what caused the episodes, and why the flagged stretches differ is a cause "
               "unidentified. An interval that covers 0 means the fit does not separate them.")
    return out


# --- driver ---------------------------------------------------------------------------------------------------


def run(cfg: dict, n_boot: int = N_BOOT) -> dict:
    t0 = time.time()
    processed, interim = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["interim"])
    outputs = Path(cfg["paths"]["outputs"])
    tables = outputs / "tables"
    seed = int(cfg.get("seed", 20261003))
    raw = pl.read_parquet(processed / "monitor_findings.parquet", columns=FINDING_COLS)
    f, n_dup = prepare_findings(raw)
    dates = set(f.filter(pl.col("ts_utc").is_not_null())["date"].to_list())
    acc = accepted_windows(tables)
    keys = {(r["window_id"], r["group"]) for r in acc.filter(pl.col("accepted")).iter_rows(named=True)
            if any(r["date_start"] <= d <= r["date_end"] for d in dates)}
    ev, fits, checks = load_hawkes(cfg, keys, module_a_blocks(tables))
    hw = {(r["window_id"], r["group"]): r for r in pl.read_csv(tables / "hawkes_windows.csv").iter_rows(named=True)}
    share_check = max((abs(c[f"share_{k}"] - float(hw[(c["window_id"], c["group"])][f"share_{k}"]))
                       for c in checks for k in CLASSES), default=float("nan"))
    v1, v1_cov, flags = run_v1(ev, f, fits, n_boot, seed)
    v2, pairs, inst, v2_facts = run_v2(f, ev, fits, n_boot, seed)
    cov = coverage_table(f, fits, v1_cov, inst)

    priv = interim / "monitor_validation"
    priv.mkdir(parents=True, exist_ok=True)
    ev.with_columns(pl.Series("flagged", flags["flagged"]), pl.Series("control", flags["control"])).drop(
        "stratum", "stratum_hour").write_parquet(priv / "event_shares.parquet")
    f.select("fid", "finding_id", "date", "category", "severity", "n_roster", "n_unmatched", "v1").join(
        v1_cov, on="fid", how="left").write_parquet(priv / "finding_coverage.parquet")
    inst.join(f.select("fid", "finding_id"), on="fid", how="left").write_parquet(priv / "pair_instances.parquet")

    tables.mkdir(parents=True, exist_ok=True)
    v1.write_csv(tables / "monitor_v1.csv", float_precision=4)
    v2.write_csv(tables / "monitor_v2.csv", float_precision=4)
    pairs.write_csv(tables / "monitor_v2_pairs.csv", float_precision=4)
    f1 = f.filter(pl.col("v1"))
    ctx = {"v1": v1, "v2": v2, "pairs": pairs, "coverage": cov, "checks": checks, "instances": inst,
           "v2_facts": v2_facts, "n_boot": n_boot, "share_check": share_check, "labels": label_check(f),
           "fetched": f"{raw['fetched_at_utc'].min()} to {raw['fetched_at_utc'].max()}",
           "findings_facts": {"in_export": int(raw["in_export"].sum()), "dups": n_dup, "kept": f.height,
                              "v1": f1.height, "v1_conflict": int((f1["category"] == CONFLICT).sum()),
                              "v1_unmatched": int((f1["n_unmatched"] > 0).sum()),
                              "conflict_median_agents": f1.filter(pl.col("category") == CONFLICT)["n_roster"].median()},
           "v3": v3_status(tables), "reading": reading_lines(v1, v2)}
    ctx["secs"] = time.time() - t0
    write_report(outputs / "qa" / "monitor_validation.md", ctx)
    return {"findings_v1": f1.height, "events": ev.height, "windows": len(fits), "secs": time.time() - t0}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--boot", type=int, default=N_BOOT, help="bootstrap draws for V1 and V2")
    a = ap.parse_args(argv)
    print(run(load_config(a.config), a.boot), flush=True)


if __name__ == "__main__":
    main()
