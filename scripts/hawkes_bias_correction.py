"""How informative is recovery_check? Calibration on simulated windows, with a bias correction.

For each window of scripts/hawkes_recovery_grid.py (same seeds): fit the model;
run recovery_check at the fitted parameters (n_rep replicates simulated from
the fit and refit the same way); run the same protocol at the TRUE parameters
(the window's own exogenous events, per-agent nudge sources, refit and pool):
its MAE is the error the fit should expect on this window ("expected"). Score
the raw shares, and the shares minus recovery_check's estimated bias, against
the realized parent labels. A check that tracks the expected error, and fails
the windows whose actual error is above the bar, can serve as a gate; one that
passes almost every window cannot.

    python scripts/hawkes_bias_correction.py --K 7 10 13 20 --reps 20 --n-rep 8 --workers 16 --shard 0/4
    python scripts/hawkes_bias_correction.py --summarize

Results: data/interim/hawkes_probe/biascorr_<shard>.parquet.

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

from avsd.hawkes import decompose, fit, label_shares, pool_exogenous, recovery_check, simulate
from avsd.hawkes.synth import pool_window, window_exogenous
from hawkes_common import BAR, OUT, SEED, SPEC, pack_window, realistic_window, share_errors, warm_up

VARIANTS = ("sparse", "dense")


def expected_error(truth, Ts, exo, sharing: str, n_rep: int, seed) -> tuple[np.ndarray, np.ndarray]:
    """The SPEC 5.6-1 protocol at the true parameters: (R, 5) and (R, 4) share errors."""
    e5, e4 = [], []
    for r in range(n_rep):
        days, labels = simulate(truth.mu, truth.alpha, list(Ts), exo, np.random.default_rng([*seed, r]), SPEC)
        days, labels = pool_window(truth.K, days, labels)
        pk = pack_window(days, truth.K)
        f = fit(pk, truth.K, kernel_sharing=sharing)
        e = share_errors(decompose(pk, f).shares, label_shares(days, labels, truth.K, pk.exo_names))
        e5.append([e[k] for k in e if k.startswith("err_") and k != "err_exogenous"])
        e4.append(pool_exogenous(np.array(e5[-1])))
    return np.array(e5), np.array(e4)


def run_task(task: tuple) -> dict:
    K, variant, rep, sharing, n_rep = task
    seed = [SEED, K, VARIANTS.index(variant), rep]
    truth, days, labels, _, _ = realistic_window(K, variant, seed)
    pk = pack_window(days, K)
    t = time.time()
    f = fit(pk, K, kernel_sharing=sharing)
    rec = recovery_check(pk, f, n_rep=n_rep, seed=SEED)
    true = label_shares(days, labels, K, pk.exo_names)
    got = decompose(pk, f).shares
    names = list(true)
    raw = np.array([got[s] - true[s] for s in names])
    bias = np.array([rec.bias[s] for s in names])
    cor = raw - bias
    _, Ts, exo = window_exogenous(K, variant, seed)
    e5, e4 = expected_error(truth, Ts, exo, sharing, n_rep, [SEED, 99, K, VARIANTS.index(variant), rep])
    return {"K": K, "variant": variant, "rep": rep, "sharing": sharing, "n_rep": n_rep,
            "secs": time.time() - t, "mae_raw": float(np.abs(raw).mean()),
            "mae4_raw": float(np.abs(pool_exogenous(raw)).mean()),
            "mae_cor": float(np.abs(cor).mean()), "mae4_cor": float(np.abs(pool_exogenous(cor)).mean()),
            "mae_rec": float(rec.mae.mean()), "mae4_rec": float(rec.mae4.mean()),
            "mae_exp": float(np.abs(e5).mean()), "mae4_exp": float(np.abs(e4).mean()),
            "exp_self": float(e5[:, -1].mean()), "exp_other": float(e5[:, -2].mean()),
            "conv": float(rec.converged.mean()), "start_spread": f.start_spread,
            **{f"raw_{s}": float(e) for s, e in zip(names, raw)},
            **{f"rec_{s}": float(b) for s, b in zip(names, bias)},
            **{f"cor_{s}": float(e) for s, e in zip(names, cor)}}


def summarize(df: pl.DataFrame) -> None:
    pl.Config.set_tbl_rows(100), pl.Config.set_tbl_cols(40), pl.Config.set_tbl_width_chars(400)
    pl.Config.set_float_precision(3)
    fail = (pl.col("mae4_raw") >= BAR)
    print(df.group_by("K", "sharing").agg(
        n=pl.len(), mae_raw=pl.col("mae_raw").mean(), mae4_raw=pl.col("mae4_raw").mean(),
        mae4_exp=pl.col("mae4_exp").mean(), mae4_rec=pl.col("mae4_rec").mean(),
        gap4=(pl.col("mae4_raw") - pl.col("mae4_rec")).mean(), mae4_cor=pl.col("mae4_cor").mean(),
        raw_self=pl.col("raw_self").mean(), rec_self=pl.col("rec_self").mean(), exp_self=pl.col("exp_self").mean(),
        corr_rec=pl.corr("mae4_rec", "mae4_raw"), corr_exp=pl.corr("mae4_exp", "mae4_raw"),
        fail=fail.sum(), rec_flags_fail=(fail & (pl.col("mae4_rec") >= BAR)).sum(),
        rec_flags_pass=(~fail & (pl.col("mae4_rec") >= BAR)).sum(),
        exp_flags_fail=(fail & (pl.col("mae4_exp") >= BAR)).sum(),
        exp_flags_pass=(~fail & (pl.col("mae4_exp") >= BAR)).sum(),
        conv=pl.col("conv").mean(), secs=pl.col("secs").mean()).sort("K", "sharing"))
    print(df.group_by("sharing").agg(
        n=pl.len(), fail=fail.sum(), rec_flags_fail=(fail & (pl.col("mae4_rec") >= BAR)).sum(),
        rec_flags_pass=(~fail & (pl.col("mae4_rec") >= BAR)).sum(),
        exp_flags_fail=(fail & (pl.col("mae4_exp") >= BAR)).sum(),
        exp_flags_pass=(~fail & (pl.col("mae4_exp") >= BAR)).sum(),
        corr_rec=pl.corr("mae4_rec", "mae4_raw"), corr_exp=pl.corr("mae4_exp", "mae4_raw"),
        corr_rec_exp=pl.corr("mae4_rec", "mae4_exp")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--K", type=int, nargs="+", default=[7, 10, 13, 20])
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--sharing", nargs="+", default=["class"])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--n-rep", type=int, default=8)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args()
    if a.summarize:
        paths = sorted(glob.glob(os.path.join(OUT, "biascorr_*.parquet")))
        summarize(pl.concat([pl.read_parquet(p) for p in paths]))
        return
    i, n = (int(x) for x in a.shard.split("/"))
    tasks = [(K, v, r, s, a.n_rep) for K in a.K for v in a.variants for r in range(a.reps) for s in a.sharing]
    tasks = sorted(tasks, key=lambda t: -t[0])[i::n]
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    warm_up()
    with Pool(a.workers) as pool:
        rows = list(pool.imap_unordered(run_task, tasks))
    out = os.path.join(OUT, f"biascorr_{i}of{n}.parquet")
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(out)
    print(f"wrote {out} ({len(rows)} rows) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
