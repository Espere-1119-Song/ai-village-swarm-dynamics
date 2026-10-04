"""Outputs of module A on the real data (SPEC 5.5, 5.6, 5.7): tables, parents, figures and QA.

`assemble(cfg)` reads the stage results of avsd.hawkes.pipeline and writes

- outputs/tables/hawkes_params.parquet: one row per window, group, target agent and source
  (agents by name, then human and system): branching ratio n with its bootstrap interval (goal
  windows), alpha per kernel component, the target's hourly baseline (events per hour, on the
  realizations it is present) and its presence (share of the window's realizations);
- outputs/tables/hawkes_kernels.parquet: class kernel mixtures for module B2 (schema in
  KERNEL_SCHEMA), goal and rolling windows; every row of a goal window that failed the recovery
  check has identified = False. Goal windows of different rooms overlap in dates (best and rest in
  R2), so a lookup must choose the window by room and date together;
- outputs/tables/hawkes_rolling.parquet: the module C hook (changepoint.series.load_external):
  run_day, run_day_end, date, group, share_baseline, share_exogenous, share_agent,
  spectral_radius, n_agents, for every rolling group with at least 500 agent messages;
- outputs/tables/hawkes_*.csv: windows, decomposition, excitation, blocks, acceptance, matched
  arms, sensitivity, goodness of fit, reference check and action-opportunity results;
- data/processed/hawkes_parents.parquet (private): event_uid, parent_uid ("background"), prob >= 0.01,
  window_id, group, for the goal windows;
- outputs/figures/F1_excitation, F2_activity_shares, hawkes_qq (.pdf, .png);
- outputs/qa/hawkes.md.

Only aggregates and agent names leave data/; human messages appear only as the source "human".

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import polars as pl

from avsd.hawkes import pipeline as P
from avsd.hawkes.matched import ARMS
from avsd.hawkes.model import BACKGROUND, decompose, pack
from avsd.hawkes.validate import pool_exogenous
from avsd.hawkes.windows import EXO, Window

SHARE5 = ("baseline", "human", "system", "other_agents", "self")
SHARE4 = ("baseline", "exogenous", "other_agents", "self")
COMPONENTS = ("1m", "10m", "1h")
KERNEL_SCHEMA = {
    "window_kind": pl.String, "window_id": pl.String, "group": pl.String, "date_start": pl.Date,
    "date_end": pl.Date, "source_class": pl.String, "w_1m": pl.Float64, "w_10m": pl.Float64, "w_1h": pl.Float64,
    "L_s": pl.Float64, "expected_children": pl.Float64, "identified": pl.Boolean,
}
ROLLING_SCHEMA = {
    "run_day": pl.Int32, "run_day_end": pl.Int32, "date": pl.Date, "group": pl.String,
    "share_baseline": pl.Float64, "share_exogenous": pl.Float64, "share_agent": pl.Float64,
    "spectral_radius": pl.Float64, "n_agents": pl.Int32,
}
CLASSES = ("self", "other", "human", "system")


# --- block structure (SPEC 5.5) --------------------------------------------------------------------


def spectral_blocks(n_aa: np.ndarray, seed: int = P.SEED, k_max: int = 6) -> tuple[np.ndarray, int, float]:
    """Spectral clustering of the symmetrized agent block (self cells left out). The number of
    groups k in 2..k_max maximizes the eigengap of the normalized Laplacian; k = 1 when K < 4 or the
    largest gap is the first. Returns (labels ordered by group size, k, eigengap)."""
    from sklearn.cluster import SpectralClustering

    K = n_aa.shape[0]
    if K < 4:
        return np.zeros(K, np.int64), 1, float("nan")
    A = (n_aa + n_aa.T) / 2
    np.fill_diagonal(A, 0.0)
    A = A + 1e-6 * max(float(A.mean()), 1e-12) * (1 - np.eye(K))   # keep the graph connected
    deg = A.sum(1)
    Lap = np.eye(K) - A / np.sqrt(np.outer(deg, deg))
    ev = np.sort(np.linalg.eigvalsh(Lap))
    km = min(k_max, K - 1)
    gaps = np.diff(ev[: km + 1])          # gaps[k - 1] = ev[k] - ev[k - 1]
    k = int(np.argmax(gaps[1:]) + 2) if km >= 2 else 1
    if gaps[0] >= gaps[1:].max(initial=0.0):
        return np.zeros(K, np.int64), 1, float(gaps[0])
    lab = SpectralClustering(k, affinity="precomputed", random_state=seed, assign_labels="kmeans",
                             n_init=20).fit_predict(A)
    order = np.argsort(-np.bincount(lab, minlength=k), kind="stable")
    remap = np.empty(k, np.int64)
    remap[order] = np.arange(k)
    return remap[lab], k, float(gaps[k - 1])


def block_means(n_aa: np.ndarray, lab: np.ndarray) -> tuple[float, float, float]:
    """Mean n_ij within groups and between groups (agent j != i), and the mean self n_ii."""
    K = n_aa.shape[0]
    same = lab[:, None] == lab[None, :]
    off = ~np.eye(K, dtype=bool)
    within, between = n_aa[same & off], n_aa[~same & off]
    return (float(within.mean()) if within.size else float("nan"),
            float(between.mean()) if between.size else float("nan"), float(np.diag(n_aa).mean()))


def agent_order(lab: np.ndarray, n_aa: np.ndarray) -> np.ndarray:
    """Agents grouped by cluster, by total excitation within a cluster."""
    strength = n_aa.sum(0) + n_aa.sum(1) - 2 * np.diag(n_aa)
    return np.lexsort((-strength, lab))


# --- helpers -------------------------------------------------------------------------------------


def _ci(x: np.ndarray, axis: int = 0) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = np.nanquantile(x, [0.025, 0.975], axis=axis)
    return lo, hi


def _source_names(r: P.FitResult) -> list[str]:
    return [*r.agent_names, *EXO]


def _source_class(i: int, j: int, K: int) -> str:
    return "self" if i == j else "other" if j < K else EXO[j - K]


def _kernel_rows(r: P.FitResult, failed: bool = False) -> list[dict]:
    """B2 rows of one fit; failed (the window failed the recovery check) marks every class not identified."""
    w = r.window
    out = []
    names = r.fit.class_names
    for c in CLASSES:
        if c not in names:
            continue
        k = names.index(c)
        out.append({"window_kind": w.kind, "window_id": w.window_id, "group": w.group, "date_start": w.date_start,
                    "date_end": w.date_end, "source_class": c, "w_1m": float(r.fit.w[k, 0]),
                    "w_10m": float(r.fit.w[k, 1]), "w_1h": float(r.fit.w[k, 2]), "L_s": float(r.fit.spec.max_lag),
                    "expected_children": float(r.children[k]),
                    "identified": bool(r.children[k] >= P.IDENTIFIED) and not failed})
    return out


def _param_rows(r: P.FitResult, n_lo: np.ndarray | None, n_hi: np.ndarray | None) -> list[dict]:
    w, f = r.window, r.fit
    K = r.K
    n = f.n
    mu = f.mu * 3600.0
    src = _source_names(r)
    pres = r.presence
    rows = []
    for i in range(K):
        for j in range(K + len(EXO)):
            rows.append({"window_kind": w.kind, "window_id": w.window_id, "group": w.group, "target": r.agent_names[i],
                         "target_presence": float(pres[i]),
                         "source": src[j], "source_class": _source_class(i, j, K), "n": float(n[i, j]),
                         "n_lo": None if n_lo is None else float(n_lo[i, j]),
                         "n_hi": None if n_hi is None else float(n_hi[i, j]),
                         **{f"alpha_{c}": float(f.alpha[i, j, m]) for m, c in enumerate(COMPONENTS)},
                         "mu_per_hour": mu[i].tolist()})
    return rows


def _write_csv(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(path, float_precision=4)


def _fmt(x: float, nd: int = 3) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def _fmt_ci(v: float, lo: float, hi: float, nd: int = 3) -> str:
    return f"{_fmt(v, nd)} [{_fmt(lo, nd)}, {_fmt(hi, nd)}]"


def _md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    from scipy.stats import norm

    z = norm.ppf(0.975)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


REF_COLS = ["hawkes_match", "hawkes_other_match", "baseline_match"]
REF_DIFFS = [("hawkes_match", "baseline_match"), ("hawkes_other_match", "baseline_match")]


def _cluster_boot(df: pl.DataFrame, cols: list[str], diffs: list[tuple[str, str]] = (), reps: int = 1000,
                  seed: int = P.SEED) -> dict[str, tuple]:
    """Run-day (realization) cluster bootstrap: percentile intervals of the means of boolean columns
    and of the differences of the given column pairs. The clusters are sorted by realization before
    the draws, so a seed gives the same intervals on every call."""
    if df.is_empty():
        return {}
    g = (df.group_by("realization", maintain_order=True)
         .agg([pl.col(c).cast(pl.Float64).sum() for c in cols] + [pl.len().alias("_n")]).sort("realization"))
    S = g.select(cols).to_numpy()
    n = g["_n"].to_numpy().astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(n), (reps, len(n)))
    means = S[draws].sum(1) / n[draws].sum(1)[:, None]
    out = {c: tuple(np.quantile(means[:, k], [0.025, 0.975])) for k, c in enumerate(cols)}
    for a, b in diffs:
        out[f"{a}-{b}"] = tuple(np.quantile(means[:, cols.index(a)] - means[:, cols.index(b)], [0.025, 0.975]))
    return out


def _ref_row(window_id: str, group: str, rows: pl.DataFrame, realization_col: pl.Expr | None = None) -> dict:
    if realization_col is not None:
        rows = rows.with_columns(realization_col.alias("realization"))
    ci = _cluster_boot(rows, REF_COLS, REF_DIFFS)
    out = {"window_id": window_id, "group": group, "n_labels": rows.height}
    for c in REF_COLS:
        out[c], out[f"{c}_lo"], out[f"{c}_hi"] = float(rows[c].mean()), *ci[c]
    for a, b in REF_DIFFS:
        out[f"{a}_minus_baseline_lo"], out[f"{a}_minus_baseline_hi"] = ci[f"{a}-{b}"]
    out["label_in_candidates"] = float(rows["in_candidates"].mean())
    out["argmax_background"] = float(rows["argmax_background"].mean())
    out["argmax_self"] = float(rows["argmax_self"].mean())
    return out


# --- assemble ---------------------------------------------------------------------------------------


def assemble(cfg: dict) -> dict:
    t0 = time.time()
    out_dir = Path(cfg["paths"]["outputs"])
    tables, figures, qa = out_dir / "tables", out_dir / "figures", out_dir / "qa"
    for d in (tables, figures, qa):
        d.mkdir(parents=True, exist_ok=True)
    parents_path = Path(cfg.get("hawkes", {}).get("parents_path")
                        or Path(cfg["paths"]["processed"]) / "hawkes_parents.parquet")
    wd = P.work_dir(cfg)
    res: dict = {"files": []}
    goal_ok = (wd / "goal_windows.parquet").exists()
    windows = P.final_windows(cfg) if goal_ok else []
    fits = {w.key: P.base_fit(cfg, w) for w in windows}
    boots = {w.key: P.boot_of(cfg, w) for w in windows}
    rolling = P.rolling_windows(cfg) if (wd / "rolling_windows.parquet").exists() or goal_ok else []
    rfits = {w.key: P._load(P.rolling_path(cfg, w)) for w in rolling if P.rolling_path(cfg, w).exists()}

    # Parameters and kernels.
    acc = last_accept(cfg) if goal_ok else {}
    prow, krow = [], []
    for w in windows:
        r, b = fits[w.key], boots[w.key]
        lo, hi = _ci(b[0].n) if b is not None else (None, None)
        prow += _param_rows(r, lo, hi)
        krow += _kernel_rows(r, failed=acc.get(w.key, {}).get("passed") is False)
    for r in rfits.values():
        prow += _param_rows(r, None, None)
        krow += _kernel_rows(r)
    if prow:
        params = pl.DataFrame(prow, infer_schema_length=None).with_columns(
            pl.col("mu_per_hour").cast(pl.List(pl.Float64)))
        params.write_parquet(tables / "hawkes_params.parquet")
        res["files"].append(tables / "hawkes_params.parquet")
        kern = pl.DataFrame(krow, schema=KERNEL_SCHEMA)
        kern.write_parquet(tables / "hawkes_kernels.parquet")
        res["files"].append(tables / "hawkes_kernels.parquet")

    # Rolling hook for module C.
    if rfits:
        rr = []
        for w in rolling:
            r = rfits.get(w.key)
            if r is None:
                continue
            s4 = r.shares4
            rr.append({"run_day": w.run_days[0], "run_day_end": w.run_days[1], "date": w.date_start, "group": w.group,
                       "share_baseline": float(s4[0]), "share_exogenous": float(s4[1]),
                       "share_agent": float(s4[2] + s4[3]), "spectral_radius": r.fit.rho, "n_agents": r.K})
        roll = pl.DataFrame(rr, schema=ROLLING_SCHEMA).sort("group", "run_day")
        roll.write_parquet(tables / "hawkes_rolling.parquet")
        res["files"].append(tables / "hawkes_rolling.parquet")
        res["rolling"] = rolling_summary(rolling, rfits)
        _write_csv(res["rolling"]["table"], tables / "hawkes_rolling_windows.csv")

    if goal_ok:
        res.update(goal_outputs(cfg, windows, fits, boots, tables, parents_path))
        from avsd.hawkes.figure import plot_f1, plot_f2, plot_qq

        blocks = res["blocks_raw"]
        # The figures show the windows that passed the recovery check (failed ones stay in the tables).
        ok = {(r["window_id"], r["group"]) for r in res["windows"].iter_rows(named=True) if r["accepted"]}
        shown = [w for w in windows if (w.window_id, w.group) in ok]
        res["figure_windows"] = (len(shown), len(windows))
        res["files"] += plot_f1(shown, fits, blocks, figures / "F1_excitation")
        res["files"] += plot_f2(shown, fits, boots, figures / "F2_activity_shares")
        valids = {w.key: P.valid_of(cfg, w) for w in windows}
        if any(v is not None for v in valids.values()):
            res["files"] += plot_qq(windows, fits, valids, figures / "hawkes_qq")
    res["files"] = sorted({*res["files"], *tables.glob("hawkes_*"), *figures.glob("F1_excitation.*"),
                           *figures.glob("F2_activity_shares.*"), *figures.glob("hawkes_qq.*")})
    res["secs"] = time.time() - t0
    write_qa(cfg, res, qa / "hawkes.md")
    print(f"[assemble] {len(res['files'])} files in {res['secs']:.0f}s", flush=True)
    return res


def last_accept(cfg: dict) -> dict[str, dict]:
    """Each goal window's row of its last recovery-check round (accept.parquet), by window key."""
    path = P.work_dir(cfg) / "accept.parquet"
    if not path.exists():
        return {}
    last = pl.read_parquet(path).sort("round").group_by("key", maintain_order=True).agg(pl.all().last())
    return {r["key"]: r for r in last.iter_rows(named=True)}


def presence_cols(r: P.FitResult) -> dict:
    """Presence summary of a fit: realizations and run dates, agents present on fewer than
    CORE_PRESENCE of the realizations, and rho over the core agents."""
    pres = r.presence
    core = r.core()
    return {"n_days": r.n_days, "n_dates": r.n_dates, "agent_days_present": int(round(pres.sum() * r.n_days)),
            "K_part_time": int((pres < P.CORE_PRESENCE).sum()), "K_core": int(core.size), "rho_core": r.rho_core(),
            "max_n_self": float(np.diag(r.fit.n[:, :r.K]).max()) if r.K else float("nan")}


GAP_NATS = 0.1


def boot_cols(b, n_dates: int) -> dict:
    """Bootstrap diagnostics: replicates where the multi-start refit beat the warm start by more than
    GAP_NATS and the reverse, objective decreases over all refits, and the mean share of the run
    dates that a replicate keeps."""
    if b is None:
        return {"boot_starts_better": None, "boot_warm_better": None, "boot_max_gap": None,
                "boot_violations": None, "boot_dates_kept": None}
    gap = b.obj_starts - b.obj_warm
    ok = np.isfinite(gap)
    return {"boot_starts_better": int((gap[ok] > GAP_NATS).sum()), "boot_warm_better": int((gap[ok] < -GAP_NATS).sum()),
            "boot_max_gap": float(np.abs(gap[ok]).max()) if ok.any() else float("nan"),
            "boot_violations": int(b.n_violations.sum()), "boot_dates_kept": float(b.n_clusters.mean() / n_dates)}


def rolling_summary(rolling: list[Window], rfits: dict) -> dict:
    rows = []
    for w in rolling:
        r = rfits.get(w.key)
        row = {"window_id": w.window_id, "group": w.group, "date_start": w.date_start, "date_end": w.date_end,
               "n_msgs": w.n_msgs, "share_of_window": w.share, "fitted": r is not None}
        if r is not None:
            s = r.shares
            row.update(K=r.K, **presence_cols(r), rho=r.fit.rho, **{f"share_{c}": float(x) for c, x in zip(SHARE5, s)},
                       converged=bool(r.fit.converged), newton_gain=r.fit.newton_gain,
                       start_spread=r.fit.start_spread, n_violations=r.fit.n_violations, secs=r.secs,
                       **{f"identified_{c}": ok for c, ok in r.identified().items()})
        rows.append(row)
    return {"table": pl.DataFrame(rows, infer_schema_length=None)}


def coverage(windows: list[Window], fits: dict) -> dict:
    """Input accounting (SPEC 0.6): agent messages by room inside and outside the fitted goal-window
    groups, and the exogenous messages attached to them, clipped to t = 0 and dropped."""
    inp = P.ctx_inputs()
    fitted = (pl.DataFrame([{"room_id": w.room_id, "goal": g} for w in windows for g in w.goals],
                           schema={"room_id": pl.String, "goal": pl.Int32}).unique()
              .with_columns(pl.lit(True).alias("in")))
    am = (inp.agent_msgs.with_columns(pl.col("goal").cast(pl.Int32))
          .join(fitted, on=["room_id", "goal"], how="left").with_columns(pl.col("in").fill_null(False)))
    rooms = (am.group_by("room").agg(pl.len().alias("agent_msgs"), pl.col("in").sum().alias("in_fitted_groups"))
             .with_columns((pl.col("agent_msgs") - pl.col("in_fitted_groups")).alias("outside"))
             .sort("outside", "agent_msgs", descending=True))
    tot = inp.msgs.filter(pl.col("kind") != "agent").group_by("kind").agg(pl.len().alias("n"))
    tot = dict(tot.iter_rows())
    exo = []
    for src in EXO:
        att = sum(int(fits[w.key].counts.get(src, 0)) for w in windows)
        exo.append({"source": src, "messages": int(tot.get(src, 0)), "attached": att,
                    "not_attached": int(tot.get(src, 0)) - att})
    clipped = sum(int(fits[w.key].counts.get("clipped_to_start", 0)) for w in windows)
    dropped = sum(int(fits[w.key].counts.get("dropped_after_run", 0)) for w in windows)
    used = ("event_uid", "ts_utc", "actor_id", "room_id", "date", "realization_id", "run_day", "goal")
    nulls = {f"agent {c}": int(inp.agent_msgs[c].null_count()) for c in used}
    nulls |= {f"exogenous {c}": int(inp.msgs.filter(pl.col("kind") != "agent")[c].null_count())
              for c in ("event_uid", "ts_utc", "room_id", "date")}
    return {"rooms": rooms, "exo": pl.DataFrame(exo), "clipped": clipped, "dropped": dropped,
            "agent_total": am.height, "agent_in": int(am["in"].sum()), "nulls": nulls}


def goal_outputs(cfg: dict, windows: list[Window], fits: dict, boots: dict, tables: Path, parents_path: Path) -> dict:
    wd = P.work_dir(cfg)
    out: dict = {}
    accept = pl.read_parquet(wd / "accept.parquet")
    _write_csv(accept.drop("key"), tables / "hawkes_acceptance.csv")
    acc = last_accept(cfg)

    # Matched arms.
    mrows = []
    for w in windows:
        for arm in ARMS:
            path = wd / "matched" / P.fname(w.key) / f"{arm}.pkl"
            if path.exists():
                mrows += P._load(path)[0]
    matched = pl.DataFrame(mrows, infer_schema_length=None) if mrows else pl.DataFrame()
    marm = pl.DataFrame()
    if mrows:
        marm = (matched.filter(pl.col("mae4").is_not_null()).group_by("key", "arm").agg(
            pl.len().alias("reps"), pl.col("mae4").mean(), (pl.col("mae4").std() / pl.len().sqrt()).alias("mae4_se"),
            pl.col("mae").mean(), pl.col("err_self").mean().alias("bias_self"),
            pl.col("err_other_agents").mean().alias("bias_other"), pl.col("err_baseline").mean().alias("bias_baseline"),
            (pl.col("err_human") + pl.col("err_system")).mean().alias("bias_exogenous"),
            pl.col("n_self_bias").mean(), pl.col("n_other_bias").mean(),
            pl.col("self_rise").first(), pl.col("rho").mean().alias("rho_refit"),
            pl.col("rho_truth").first(), pl.col("converged").mean().alias("conv"),
            pl.col("n_violations").sum())
            .sort("key", "arm"))
        # Replicates stopped as exploded (validate.explosion_caps) have no mae4.
        boom = matched.group_by("key", "arm").agg(pl.col("mae4").is_null().sum().cast(pl.Int64).alias("exploded"))
        marm = marm.join(boom, on=["key", "arm"], how="full", coalesce=True).sort("key", "arm")
        _write_csv(marm.with_columns(pl.col("key").str.split(":").list.get(1).alias("window_id"),
                                     pl.col("key").str.split(":").list.get(2).alias("group")).drop("key")
                   .select("window_id", "group", pl.exclude("window_id", "group")), tables / "hawkes_matched.csv")
    mrange = {}
    for (k,), g in (marm.partition_by("key", as_dict=True).items() if mrows else ()):
        g = g.filter(pl.col("mae4").is_not_null())
        if g.height:
            mrange[k] = (float(g["mae4"].min()), float(g["mae4"].max()), g.sort("mae4")["arm"][-1])

    # Windows, decomposition, excitation, blocks, parents.
    wrows, drows, xrows, brows, members = [], [], [], [], []
    blocks_raw = {}
    parents = []
    for w in windows:
        r, b = fits[w.key], boots[w.key]
        f, K = r.fit, r.K
        s5, s4 = r.shares, r.shares4
        if b is not None:
            bs5 = b[0].shares
            bs4 = pool_exogenous(bs5)
            lo5, hi5 = _ci(bs5)
            lo4, hi4 = _ci(bs4)
            rlo, rhi = _ci(b[0].rho)
            nlo, nhi = _ci(b[0].n)
            bconv = float(b[0].converged.mean())
            m5, sd5, m4, sd4 = bs5.mean(0), bs5.std(0, ddof=1), bs4.mean(0), bs4.std(0, ddof=1)
            rmean, rsd = float(b[0].rho.mean()), float(b[0].rho.std(ddof=1))
        else:
            lo5 = hi5 = m5 = sd5 = np.full(5, np.nan)
            lo4 = hi4 = m4 = sd4 = np.full(4, np.nan)
            rlo = rhi = rmean = rsd = float("nan")
            nlo = nhi = np.full(f.n.shape, np.nan)
            bconv = float("nan")
        a = acc.get(w.key, {})
        mr = mrange.get(w.key, (float("nan"), float("nan"), ""))
        ident = r.identified()
        lab, k, gap = spectral_blocks(f.n[:, :K])
        blocks_raw[w.key] = lab
        within, between, self_mean = block_means(f.n[:, :K], lab)
        wrows.append({
            "window_id": w.window_id, "group": w.group, "goals": ",".join(str(g) for g in w.goals),
            "date_start": w.date_start, "date_end": w.date_end, **presence_cols(r), "hours": r.hours, "K": K,
            "agent_events": r.n_events, "human_events": r.counts.get("human"), "system_events": r.counts.get("system"),
            "exo_clipped_to_start": r.counts.get("clipped_to_start"),
            "exo_dropped_after_run": r.counts.get("dropped_after_run"),
            "rho": f.rho, "rho_lo": rlo, "rho_hi": rhi, "rho_boot_mean": rmean, "rho_boot_sd": rsd,
            **{f"share_{c}": float(x) for c, x in zip(SHARE5, s5)},
            **{f"share_{c}_lo": float(x) for c, x in zip(SHARE5, lo5)},
            **{f"share_{c}_hi": float(x) for c, x in zip(SHARE5, hi5)},
            **{f"share_{c}_boot_mean": float(x) for c, x in zip(SHARE5, m5)},
            "share4_exogenous": float(s4[1]), "share4_exogenous_lo": float(lo4[1]),
            "share4_exogenous_hi": float(hi4[1]),
            "mae4": a.get("mae4"), "mae4_se": a.get("mae4_se"), "recovery_reps": a.get("n_reps"),
            **{f"recovery_{c}": a.get(c) for c in (
                "bias_baseline", "bias_human", "bias_system", "bias_other_agents", "bias_self", "n_self_bias",
                "n_other_bias", "n_exogenous_bias", "n_self_abs_bias", "n_other_abs_bias", "n_exogenous_abs_bias")},
            "accepted": a.get("passed"), "merged": w.merged or "",
            "matched_mae4_min": mr[0], "matched_mae4_max": mr[1], "matched_worst_arm": mr[2],
            **{f"children_{c}": float(x) for c, x in zip(f.class_names, r.children)},
            **{f"identified_{c}": ok for c, ok in ident.items()},
            "converged": bool(f.converged), "newton_gain": f.newton_gain, "n_violations": f.n_violations,
            "start": f.start, "start_spread": f.start_spread, "n_iter": f.n_iter,
            **boot_cols(b[0] if b is not None else None, r.n_dates),
            "boot_converged": bconv, "boot_reps": 0 if b is None else int(b[0].rho.size),
            "recovery_converged": a.get("rec_converged"), "recovery_violations": a.get("rec_violations"),
            "fit_secs": r.secs, "boot_secs": None if b is None else b[2], "recovery_secs": a.get("rec_secs"),
        })
        reps5 = b[0].shares if b is not None else None
        for scheme, names, s, lo, hi, mb, sdb, reps in (
                ("five_way", SHARE5, s5, lo5, hi5, m5, sd5, reps5),
                ("spec_four_way", SHARE4, s4, lo4, hi4, m4, sd4, None if reps5 is None else pool_exogenous(reps5))):
            for k_, (c, x, l_, h_, m_, sd_) in enumerate(zip(names, s, lo, hi, mb, sdb)):
                drows.append({"window_id": w.window_id, "group": w.group, "date_start": w.date_start,
                              "date_end": w.date_end, "n_days": r.n_days, "n_dates": r.n_dates, "scheme": scheme,
                              "category": c, "share": float(x), "lo": float(l_), "hi": float(h_),
                              "boot_mean": float(m_), "boot_sd": float(sd_),
                              "normal_lo": float(max(x - 1.96 * sd_, 0.0)),
                              "normal_hi": float(min(x + 1.96 * sd_, 1.0)),
                              "estimate_in_ci": bool(l_ <= x <= h_) if np.isfinite(l_) else None,
                              # share of the replicates below the estimate (near 0 or 1: the estimate sits at
                              # an edge of the replicate distribution)
                              "estimate_quantile": None if reps is None else float((reps[:, k_] < x).mean())})
        src = _source_names(r)
        for i in range(K):
            for j in range(K + len(EXO)):
                xrows.append({"window_id": w.window_id, "group": w.group, "target": r.agent_names[i],
                              "target_presence": float(r.presence[i]),
                              "source": src[j], "source_class": _source_class(i, j, K), "n": float(f.n[i, j]),
                              "n_lo": float(nlo[i, j]), "n_hi": float(nhi[i, j]),
                              "target_block": int(lab[i]) + 1,
                              "source_block": int(lab[j]) + 1 if j < K else None})
        clusters = " | ".join(f"{c + 1}: " + ", ".join(r.agent_names[i] for i in np.flatnonzero(lab == c))
                              for c in range(k))
        brows.append({"window_id": w.window_id, "group": w.group, "K": K, "n_blocks": k, "eigengap": gap,
                      "mean_within": within, "mean_between": between,
                      "ratio_within_between": within / between if between and between > 0 else None,
                      "mean_self": self_mean, "blocks": clusters})
        for i in range(K):
            members.append({"window_id": w.window_id, "group": w.group, "agent": r.agent_names[i],
                            "block": int(lab[i]) + 1})
        d = P._data(w)
        pk = pack(d.days, d.K, f.spec, exo_names=EXO)
        par = decompose(pk, f, min_prob=P.PARENT_MIN).parents
        parents.append(par.with_columns(pl.lit(w.window_id).alias("window_id"), pl.lit(w.group).alias("group")))
    win = pl.DataFrame(wrows, infer_schema_length=None)
    _write_csv(win, tables / "hawkes_windows.csv")
    dec = pl.DataFrame(drows)
    _write_csv(dec, tables / "hawkes_decomposition.csv")
    _write_csv(pl.DataFrame(xrows, infer_schema_length=None), tables / "hawkes_excitation.csv")
    _write_csv(pl.DataFrame(brows, infer_schema_length=None), tables / "hawkes_blocks.csv")
    par = pl.concat(parents)
    parents_path.parent.mkdir(parents=True, exist_ok=True)
    par.write_parquet(parents_path)
    out["coverage"] = coverage(windows, fits)
    out["part_time"] = pl.DataFrame(
        [{"window_id": w.window_id, "group": w.group, "agent": fits[w.key].agent_names[i],
          "presence": float(fits[w.key].presence[i]), "events": int(round(fits[w.key].events_dim[i])),
          "n_self": float(fits[w.key].fit.n[i, i])}
         for w in windows for i in np.flatnonzero(fits[w.key].presence < P.CORE_PRESENCE)],
        schema={"window_id": pl.String, "group": pl.String, "agent": pl.String, "presence": pl.Float64,
                "events": pl.Int64, "n_self": pl.Float64})
    out.update(windows=win, accept=accept, matched=marm, decomposition=dec,
               blocks=pl.DataFrame(brows, infer_schema_length=None),
               blocks_raw=blocks_raw, n_parents=par.height,
               n_parent_events=par["event_uid"].n_unique(),
               parent_background=float(par.filter(pl.col("parent_uid") == BACKGROUND)["prob"].sum()))

    # Sensitivity. "core" is rho over the agents present on at least CORE_PRESENCE of the realizations
    # (the main fit's N_AA restricted to them, no refit).
    srows = []
    for w in windows:
        base = fits[w.key]
        core = base.core()
        srows.append({"window_id": w.window_id, "group": w.group, "variant": "core", "refit": False,
                      "note": f"rho of N_AA over the {core.size} of {base.K} agents present on at least "
                              f"{P.CORE_PRESENCE:.0%} of the realizations (main fit)",
                      "K": int(core.size), "n_days": base.n_days, "rho": base.rho_core(),
                      "d_rho": base.rho_core() - base.fit.rho})
        for v in P.sens_variants():
            s = P.sens_of(cfg, w, v)
            if s is None and v == "tie":
                srows.append({"window_id": w.window_id, "group": w.group, "variant": v, "refit": False,
                              "note": "all exogenous shapes identified"})
                continue
            if s is None:
                continue
            row = {"window_id": w.window_id, "group": w.group, "variant": v, "refit": not s.note, "note": s.note,
                   "tied": ",".join(s.fit.tie_exo), "K": s.K, "n_days": s.n_days, "agent_events": s.n_events,
                   "rho": s.fit.rho, "d_rho": s.fit.rho - base.fit.rho, "converged": bool(s.fit.converged),
                   "n_violations": int(s.fit.n_violations)}
            for c, x, x0 in zip(SHARE5, s.shares, base.shares):
                row[f"share_{c}"], row[f"d_{c}"] = float(x), float(x - x0)
            s4, b4 = s.shares4, base.shares4
            row["d4_max"] = float(np.abs(s4 - b4).max())
            srows.append(row)
    sens = pl.DataFrame(srows, infer_schema_length=None) if srows else pl.DataFrame()
    if srows:
        _write_csv(sens, tables / "hawkes_sensitivity.csv")
    out["sens"] = sens

    # Validation 2 to 4.
    grow, rrows, orows, dis, ref_rows = [], [], [], [], []
    for w in windows:
        v = P.valid_of(cfg, w)
        if v is None:
            continue
        r = fits[w.key]
        for i, name in enumerate(r.agent_names):
            grow.append({"window_id": w.window_id, "group": w.group, "agent": name, "n_increments": int(v["ks_n"][i]),
                         "ks": float(v["ks"][i]), "ks_p": float(v["ks_p"][i])})
        ref = v["refs"]
        if ref["n_labels"]:
            rows = ref["rows"]
            ref_rows.append(rows.with_columns(pl.lit(w.key).alias("key")))
            rrows.append(_ref_row(w.window_id, w.group, rows))
        o = v["opp"]
        orows.append({"window_id": w.window_id, "group": w.group, **{k: o[k] for k in (
            "n_actions", "msg_share", "agents_fitted", "pairs", "spearman", "spearman_p", "spearman_per_agent_mean",
            "n_agents_per_agent", "spearman_self", "top_source_agree", "n_top", "n_disagree")}})
        dis += [{"window_id": w.window_id, "group": w.group, **x} for x in o["disagreements"]]
    if grow:
        gof = pl.DataFrame(grow)
        _write_csv(gof, tables / "hawkes_gof.csv")
        out["gof"] = gof
    if ref_rows:
        allr = pl.concat(ref_rows)
        rid = pl.concat_str("key", pl.col("realization").cast(pl.String))
        total = _ref_row("all", "all", allr, rid)
        cand = _ref_row("all, label among candidates", "all", allr.filter(pl.col("in_candidates")), rid)
        by_label = [{"label": k[0], "n": g.height, **{c: float(g[c].mean()) for c in REF_COLS}}
                    for k, g in allr.group_by("label")]
        refs = pl.DataFrame([total, cand, *rrows])
        _write_csv(refs, tables / "hawkes_reference_check.csv")
        out["refs"] = refs
        out["refs_by_label"] = pl.DataFrame(by_label).sort("label")
        out["n_labels_total"] = pl.read_parquet(P.labels_path(cfg)).height if P.labels_path(cfg).exists() else None
    if orows:
        opp = pl.DataFrame(orows, infer_schema_length=None)
        _write_csv(opp, tables / "hawkes_opportunity.csv")
        out["opp"] = opp
        if dis:
            _write_csv(pl.DataFrame(dis), tables / "hawkes_opportunity_disagreements.csv")
        out["n_disagree"] = len(dis)
    return out


# --- QA report ----------------------------------------------------------------------------------------


def _runtime(cfg: dict) -> list[str]:
    d = P.work_dir(cfg) / "runtime"
    return [p.read_text().strip() for p in sorted(d.glob("*.txt"))] if d.exists() else []


def write_qa(cfg: dict, res: dict, path: Path) -> None:
    from avsd.hawkes.qa import render

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(cfg, res, _runtime(cfg)), encoding="utf-8")
    res["files"].append(path)
