"""Recovery on truths matched to each real window: what the real-window shares can claim.

The grid (scripts/hawkes_recovery_grid.py) uses its own regime, so its error
levels and recovery_check offsets do not transfer to the real windows. Here
the truth is the real window's own class fit (l1 = 0): its K, day lengths,
exogenous events, per-agent baselines, n and class kernel shapes. Arms change
what the fit may get wrong:

    fit      the fit itself (the truth recovery_check uses)
    slow     self and other kernels: half of the 10-min weight moved to the 1-h component
    fast     self and other kernels: half of the 1-h weight moved to the 10-min component
    self05   excitation moved from other agents to self so that the expected self share
             rises by 0.05 at an unchanged expected event count (fits are biased away
             from self, so the truth may have more self excitation than the fit)
    self10   the same with 0.10
    wclass   self and other kernel shapes set to the grid means W_CLASS

The arms (arm_truth, expected_counts, boost_self) live in avsd.hawkes.matched, which
the module A pipeline uses for every final goal window.

Each arm simulates R replicates with the window's exogenous events and day
lengths, refits them with fit() (class, l1 = 0, default starts) and scores the
shares against the realized parent labels: mae (5 shares), mae4 (SPEC
four-way, exogenous pooled), per-share errors and the n_ij bias. A nested
recovery_check at each refit (--n-rep) shows how far recovery_check's MAE is
from the actual error in that regime.

    python scripts/hawkes_matched_recovery.py --reps 12 --n-rep 5 --workers 16 --windows 0 1
    python scripts/hawkes_matched_recovery.py --summarize

Results: data/interim/hawkes_probe/matched_<windows>.parquet.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os

# One BLAS thread per worker process (the Newton steps call eigh).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
import glob
import time
from multiprocessing import Pool

import numpy as np
import polars as pl

from avsd.hawkes import fit, pack, recovery_check, simulate
from avsd.hawkes.matched import ARMS, CLASSES, arm_truth, expected_counts
from hawkes_common import BAR, EXO, OUT, SEED, SPEC, pack_window, score, warm_up
from hawkes_real_probe import WINDOWS, load_window

def run_task(task) -> dict:
    wi, label, arm, rep, mu, alpha, n_true, Ts, exo, K, n_rep = task
    rng = np.random.default_rng([SEED, 5151, wi, ARMS.index(arm), rep])
    days, labels = simulate(mu, alpha, Ts, exo, rng, SPEC)
    pk = pack(days, K, SPEC, exo_names=EXO)
    t0 = time.time()
    g = fit(pk, K, kernel_sharing="class")
    row = score(days, labels, pk, g)
    rec = recovery_check(pk, g, n_rep=n_rep, seed=SEED + 17) if n_rep else None
    nb = g.n - n_true
    diag = np.eye(K, dtype=bool)
    out = {"window": label, "arm": arm, "rep": rep, "K": K, **{k: v for k, v in row.items()},
           "n_self_bias": float(nb[:, :K][diag].mean()), "n_other_bias": float(nb[:, :K][~diag].mean()),
           "n_self_abs": float(np.abs(nb[:, :K][diag]).mean()), "n_other_abs": float(np.abs(nb[:, :K][~diag]).mean()),
           "rho_truth": float(np.abs(np.linalg.eigvals(n_true[:, :K])).max()), "secs": time.time() - t0}
    if rec is not None:
        out.update(rec_mae=float(rec.mae.mean()), rec_mae4=float(rec.mae4.mean()), rec_self=rec.bias["self"],
                   rec_other=rec.bias["other_agents"])
    for c, nm in enumerate(CLASSES):
        for m in range(SPEC.M):
            out[f"w_{nm}{m}"] = float(g.w[c, m])
    return out


def summarize(df: pl.DataFrame) -> None:
    pl.Config.set_tbl_rows(100), pl.Config.set_tbl_cols(40), pl.Config.set_tbl_width_chars(400)
    pl.Config.set_float_precision(3)
    se = lambda c: pl.col(c).std() / pl.len().sqrt()  # noqa: E731
    print(df.group_by("window", "arm").agg(
        n=pl.len(), events=pl.col("n_events").mean(), true_self=pl.col("true_self").mean(),
        mae=pl.col("mae").mean(), mae4=pl.col("mae4").mean(), mae4_se=se("mae4"),
        pass4=(pl.col("mae4") < BAR).mean(), b_self=pl.col("err_self").mean(),
        b_other=pl.col("err_other_agents").mean(), b_base=pl.col("err_baseline").mean(),
        b_exo=pl.col("err_exogenous").mean(), rec_mae4=pl.col("rec_mae4").mean(),
        gap4=(pl.col("mae4") - pl.col("rec_mae4")).mean(),
        gap4_se=(pl.col("mae4") - pl.col("rec_mae4")).std() / pl.len().sqrt(),
        rec_self=pl.col("rec_self").mean(), n_self_bias=pl.col("n_self_bias").mean(),
        n_other_bias=pl.col("n_other_bias").mean(), rho=pl.col("rho").mean(), rho_truth=pl.col("rho_truth").mean(),
        conv=pl.col("converged").mean(), secs=pl.col("secs").mean()).sort("window", "arm"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, nargs="+", default=list(range(len(WINDOWS))))
    ap.add_argument("--arms", nargs="+", default=list(ARMS))
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--n-rep", type=int, default=5)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args()
    if a.summarize:
        summarize(pl.concat([pl.read_parquet(p) for p in sorted(glob.glob(os.path.join(OUT, "matched_*.parquet")))],
                            how="diagonal_relaxed"))
        return
    tasks = []
    for wi in a.windows:
        w = load_window(*WINDOWS[wi])
        K = len(w.agents)
        pk = pack_window(w.days, K)
        f = fit(pk, K, kernel_sharing="class")
        Ts, exo = pk.day_T.tolist(), pk.exo_times()
        for arm in a.arms:
            mu, alpha, rise = arm_truth(arm, f, pk)
            if arm != "fit" and np.allclose(alpha, f.alpha) and np.allclose(mu, f.mu):
                print(f"{w.label} {arm}: same truth as fit, skipped")
                continue
            n_true = SPEC.branching(alpha)
            e = expected_counts(mu, alpha, Ts, exo, SPEC)
            print(f"{w.label} {arm}: expected events {e.sum():.0f} (real {pk.tgt_ev.size}); (baseline, exogenous, "
                  f"other, self) shares {np.round(e / e.sum(), 3).tolist()}; self share rise {rise:.3f}; rho "
                  f"{np.abs(np.linalg.eigvals(n_true[:, :K])).max():.3f}", flush=True)
            tasks += [(wi, w.label, arm, r, mu, alpha, n_true, Ts, exo, K, a.n_rep) for r in range(a.reps)]
    tasks.sort(key=lambda t: -t[9])
    t0 = time.time()
    warm_up()
    with Pool(a.workers) as pool:
        rows = list(pool.imap_unordered(run_task, tasks))
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"matched_{'_'.join(map(str, a.windows))}.parquet")
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(out)
    print(f"wrote {out} ({len(rows)} rows) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
