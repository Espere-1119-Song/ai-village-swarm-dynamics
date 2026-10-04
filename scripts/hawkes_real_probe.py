"""Module A probe on real goal windows: cell vs class vs global kernel sharing, with recovery checks.

Events come from events_unified (chat rows) restricted to the window's main
room by agent message volume (SPEC 5.1): agent messages (kind agent_msg,
dimension = agent), human messages (human_msg, staff-typed run markers
included) and system nudges (system_msg with subkind nudge; the bot's daily
run markers are not nudges and are left out). Each run day is one
realization from run_periods: t = 0 at its start (the first agent row of any
kind) and T_d at its end. Exogenous messages of the same Pacific date posted
before the start are placed at t = 0 (agents can respond only once they run;
--pre-start drop discards them instead); later ones are dropped. Only
aggregates and agent names are printed.

    python scripts/hawkes_real_probe.py --workers 16 --n-rep 20
    python scripts/hawkes_real_probe.py --sharing class --recover class --tag _class   # one sharing per job

Fits use fit()'s defaults: several starts for shared kernels (start_spread is
the objective range across them) and the Newton-certified stopping rule.
recovery_check (SPEC 5.6-1) reports the 5-share MAE, the SPEC four-way MAE
(exogenous pooled, mae4), per-share biases and the n_ij bias by cell type.

Results: data/interim/hawkes_probe/real_fits<tag>.parquet, real_recovery<tag>.parquet.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os

# One BLAS thread per worker process (the Newton steps call eigh).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
import time
from dataclasses import dataclass, field
from multiprocessing import Pool

import numpy as np
import polars as pl

from avsd.hawkes import Day, Recovery, decompose, pool_exogenous, recovery_check
from hawkes_common import BAR, EXO, OUT, SEED, fit_variant, pack_window, warm_up

PROCESSED = "data/processed/"
TABLES = PROCESSED + "tables/"
TZ = "America/Los_Angeles"
# (label, goal start date in UTC, max run days or None for the whole goal window)
WINDOWS = (("2025-09 (R0, one room)", "2025-09-01", None),
           ("2026-06 (R2)", "2026-06-15", None),
           ("2026-07 (R3, first 5 days)", "2026-07-06", 5))


@dataclass
class Window:
    label: str
    room: str
    agents: list[str]        # agent display names, dimension order
    days: list[Day]
    counts: dict = field(default_factory=dict)  # exogenous rows clipped to t = 0, dropped, run markers left out


def load_window(label: str, start: str, max_days: int | None, pre_start: str = "clip") -> Window:
    if pre_start not in ("clip", "drop"):
        raise ValueError("pre_start must be 'clip' or 'drop'")
    goals = pl.read_parquet(TABLES + "village_goals.parquet", columns=["start_time", "end_time"])
    g = goals.filter(pl.col("start_time").dt.strftime("%Y-%m-%d") == start)
    if g.height != 1:
        raise ValueError(f"no unique goal starting {start}")
    t0, t1 = g["start_time"][0], g["end_time"][0]
    ev = pl.scan_parquet(PROCESSED + "events_unified.parquet").filter(
        (pl.col("source") == "chat") & pl.col("kind").is_in(["agent_msg", "human_msg", "system_msg"])
        & (pl.col("ts_utc") >= t0)).select("kind", "subkind", "ts_utc", "actor_id", "room_id", "realization_id")
    if t1 is not None:
        ev = ev.filter(pl.col("ts_utc") < t1)
    ev = ev.collect()
    agent = ev.filter(pl.col("kind") == "agent_msg")
    room = agent.group_by("room_id").len().sort("len", descending=True)["room_id"][0]
    ev = ev.filter(pl.col("room_id") == room)
    runs = pl.read_parquet(PROCESSED + "run_periods.parquet", columns=["realization_id", "date", "start", "end"])
    runs = runs.filter(pl.col("realization_id").is_in(ev.filter(pl.col("kind") == "agent_msg")["realization_id"]
                                                      .unique().implode())).sort("start")
    if max_days is not None:
        runs = runs.head(max_days)
    msgs = ev.filter(pl.col("kind") == "agent_msg")
    ids = sorted(msgs.filter(pl.col("realization_id").is_in(runs["realization_id"].implode()))["actor_id"]
                 .unique().to_list())
    dim = {a: k for k, a in enumerate(ids)}
    exo = ev.filter(pl.col("kind") != "agent_msg").with_columns(
        date=pl.col("ts_utc").dt.convert_time_zone(TZ).dt.date())
    exo = exo.filter(pl.col("date").is_in(runs["date"].implode()))
    marker = (pl.col("kind") == "system_msg") & (pl.col("subkind") != "nudge")
    counts = {"run_markers_left_out": exo.filter(marker).height, "clipped_to_start": 0, "dropped": 0}
    exo = exo.filter(~marker)
    taken = np.zeros(exo.height, bool)
    days = []
    for r in runs.iter_rows(named=True):
        s0, T = r["start"], (r["end"] - r["start"]).total_seconds()
        a = msgs.filter(pl.col("realization_id") == r["realization_id"]).sort("ts_utc")
        at = ((a["ts_utc"] - s0).dt.total_microseconds() / 1e6).to_numpy()
        rel = ((exo["ts_utc"] - s0).dt.total_microseconds() / 1e6).to_numpy()
        same = (exo["date"] == r["date"]).to_numpy() & ~taken
        pre, inside = same & (rel < 0), same & (rel >= 0) & (rel <= T)
        taken |= pre | inside
        counts["clipped_to_start" if pre_start == "clip" else "dropped"] += int(pre.sum())
        keep = inside | (pre if pre_start == "clip" else False)
        times = []
        for src, kind in zip(EXO, ("human_msg", "system_msg")):
            sel = keep & (exo["kind"] == kind).to_numpy()
            times.append(np.sort(np.clip(rel[sel], 0.0, T)))
        days.append(Day(T, at, np.array([dim[i] for i in a["actor_id"]]), exo_times=tuple(times)))
    counts["dropped"] += int((~taken).sum())
    names = dict(pl.read_parquet(TABLES + "agents.parquet", columns=["id", "name"]).iter_rows())
    return Window(label, room, [names.get(i, "?") for i in ids], days, counts)


def run_fit(task):
    w, sharing, l1_policy = task
    pk = pack_window(w.days, len(w.agents))
    f, l1, secs = fit_variant(pk, pk.K, sharing, l1_policy)
    dec = decompose(pk, f)
    s4 = pool_exogenous(np.array(list(dec.shares.values())))
    # Expected children per kernel class: how many events each class shape rests on.
    src = np.bincount(pk.ev_src, minlength=pk.K + pk.H)
    kids = np.bincount(f.classes.ravel(), weights=(f.n * src[None, :]).ravel(), minlength=len(f.class_names))
    return {"window": w.label, "sharing": sharing, "l1_policy": l1_policy, "l1": l1, "K": pk.K,
            "events": int(pk.tgt_ev.size), "rho": f.rho, "n_iter": f.n_iter, "converged": f.converged,
            "n_viol": f.n_violations, "start": f.start, "start_spread": f.start_spread,
            "newton_gain": f.newton_gain, "secs": secs, "loglik": float(f.loglik[-1]),
            "self_n_mean": float(np.diag(f.n).mean()), **dec.shares, "exogenous": float(s4[1]),
            "w": None if f.w is None else f.w.round(3).tolist(),
            "classes": None if f.w is None else list(f.class_names),
            "class_children": None if f.w is None else kids.round(1).tolist()}, f


def run_recovery(task):
    """One chunk of replicates of recovery_check for one fit."""
    w, sharing, l1_policy, f, start, n = task
    pk = pack_window(w.days, len(w.agents))
    t = time.time()
    refit = lambda p: fit_variant(p, p.K, sharing, l1_policy)[0]  # noqa: E731
    rec = recovery_check(pk, f, n_rep=n, seed=SEED, refit=refit, start=start)
    return (w.label, sharing, l1_policy), start, rec, time.time() - t


def recovery_row(key, rec: Recovery, f, secs: float) -> dict:
    return {"window": key[0], "sharing": key[1], "l1_policy": key[2], "n_rep": rec.mae.size,
            "mae": float(rec.mae.mean()), "mae4": float(rec.mae4.mean()), "mae_max": float(rec.mae.max()),
            "mae4_max": float(rec.mae4.max()), "pass_rate": float((rec.mae < BAR).mean()),
            "pass4_rate": float((rec.mae4 < BAR).mean()), **{f"b_{k}": v for k, v in rec.bias.items()},
            **rec.n_bias_summary(), "rho_fit": f.rho, "rho_refit": float(rec.rho.mean()),
            "conv": float(rec.converged.mean()), "events": float(rec.n_events.mean()), "secs": secs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--n-rep", type=int, default=20)
    ap.add_argument("--chunk", type=int, default=4, help="replicates per recovery task")
    ap.add_argument("--windows", type=int, nargs="+", default=list(range(len(WINDOWS))))
    ap.add_argument("--sharing", nargs="+", default=["cell", "class", "global"])
    ap.add_argument("--l1", nargs="+", default=["none", "cv", "cv_cross"])
    ap.add_argument("--recover", nargs="+", default=["class", "cell", "global"])
    ap.add_argument("--pre-start", default="clip", choices=["clip", "drop"])
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    pl.Config.set_tbl_rows(100), pl.Config.set_tbl_cols(40), pl.Config.set_tbl_width_chars(400)
    pl.Config.set_float_precision(3)
    wins = [load_window(*WINDOWS[i], pre_start=a.pre_start) for i in a.windows]
    for w in wins:
        ex = [sum(d.exo_times[h].size for d in w.days) for h in range(len(EXO))]
        print(f"{w.label}: K={len(w.agents)}, days={len(w.days)}, "
              f"agent msgs={sum(d.agent_times.size for d in w.days)}, human={ex[0]}, system nudges={ex[1]}, "
              f"{w.counts}, T_d h={np.round([d.T / 3600 for d in w.days], 2).tolist()}")
        print("   agents:", ", ".join(w.agents))
    tasks = [(w, s, l) for w in wins for s in a.sharing for l in a.l1]
    tasks.sort(key=lambda t: t[2] == "none")      # select_l1 runs first
    warm_up()
    with Pool(a.workers) as pool:
        out = pool.map(run_fit, tasks, chunksize=1)
        rows = [r for r, _ in out]
        fits = {(r["window"], r["sharing"], r["l1_policy"]): f for r, f in out}
        rec_tasks = [(w, s, l, fits[(w.label, s, l)], k, min(a.chunk, a.n_rep - k)) for w in wins
                     for s in a.recover for l in a.l1 if (w.label, s, l) in fits for k in range(0, a.n_rep, a.chunk)]
        rec_tasks.sort(key=lambda t: t[2] == "none")
        chunks = pool.map(run_recovery, rec_tasks, chunksize=1)
    parts: dict = {}
    for key, start, rec, secs in sorted(chunks, key=lambda c: (c[0], c[1])):
        parts.setdefault(key, []).append((rec, secs))
    recs = [recovery_row(key, Recovery.concat([r for r, _ in v]), fits[key], sum(s for _, s in v))
            for key, v in parts.items()]
    os.makedirs(OUT, exist_ok=True)
    fit_df = pl.DataFrame(rows, infer_schema_length=None).sort("window", "sharing", "l1_policy")
    rec_df = pl.DataFrame(recs, infer_schema_length=None).sort("window", "sharing", "l1_policy")
    fit_df.write_parquet(os.path.join(OUT, f"real_fits{a.tag}.parquet"))
    rec_df.write_parquet(os.path.join(OUT, f"real_recovery{a.tag}.parquet"))
    print(fit_df.drop("w", "classes", "class_children", "loglik"))
    print("kernel weights (1 min, 10 min, 1 h) and expected children per class; shapes resting on fewer than"
          " about 50 children are not identified (they flip between local maxima)")
    for r in fit_df.iter_rows(named=True):
        if r["w"] is not None:
            print(r["window"], r["sharing"], r["l1_policy"],
                  {c: (w, k) for c, w, k in zip(r["classes"], r["w"], r["class_children"])})
    print(rec_df)


if __name__ == "__main__":
    main()
