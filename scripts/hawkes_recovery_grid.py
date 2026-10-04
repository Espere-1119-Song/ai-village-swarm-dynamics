"""SPEC 5.6-1 recovery on simulated windows, by kernel sharing and L1 policy.

Each window: K agents, 5-10 run days of about 3.5 h, 2k-6k agent messages,
human messages and targeted system nudges (avsd.hawkes.synth). Every window
is fitted with kernel_sharing cell / class / global, each with l1 = 0 ("none"),
the select_l1 choice over all cells ("cv") and over cross-agent cells only
("cv_cross"); shares are scored against the realized parent labels, as the
5-share MAE (mae) and the SPEC four-way MAE with the exogenous sources pooled
(mae4, the decomposition the 0.05 bar was set for).

The numbers are conditional on the generator's regime (class kernel means
W_CLASS, self shares 0.23-0.39, rho 0.65-0.85, 3.5-h days, K <= 20), which
differs from the real windows; scripts/hawkes_matched_recovery.py measures
the error per real window.

Misspecification arms: --kappa draws each cell's kernel shape from
Dirichlet(kappa * class mean); --tilt s gives each agent its own latency
(every kernel into agent i tilted by exp(g_i (m - 1)), g_i ~ N(0, s^2)). An
arm window has the same seed, truth parameters and exogenous events as the
main-grid window, but its realized events differ (delays change, and with them
all later random draws), so arms are compared with the main grid through
per-window differences and their standard errors (--summarize --vs main),
not as exactly paired runs.

    python scripts/hawkes_recovery_grid.py --tag main --workers 16 --shard i/6         # i = 0..5
    python scripts/hawkes_recovery_grid.py --tag misspec5 --kappa 5 --K 10 20 \
        --sharing cell class --l1 none cv_cross --workers 16 --shard i/2                # i = 0, 1
    python scripts/hawkes_recovery_grid.py --tag tilt075 --tilt 0.75 --K 10 20 \
        --sharing cell class --l1 none cv_cross --workers 16 --shard i/2
    python scripts/hawkes_recovery_grid.py --summarize --by tag K sharing l1_policy
    python scripts/hawkes_recovery_grid.py --summarize --vs main --tags misspec5 tilt075 --by tag K sharing l1_policy

Results: data/interim/hawkes_probe/recovery_<tag>_<shard>.parquet.

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

from hawkes_common import (
    BAR, OUT, SEED, class_kernel_error, fit_variant, pack_window, realistic_window, score, warm_up,
)

VARIANTS = ("sparse", "dense")
KEY = ["K", "variant", "rep", "sharing", "l1_policy"]


def run_task(task: tuple) -> dict:
    tag, K, variant, rep, kappa, tilt, sharing, l1_policy = task
    seed = [SEED, K, VARIANTS.index(variant), rep]   # same truth for every arm
    truth, days, labels, D, n_target = realistic_window(K, variant, seed, kappa, tilt)
    pk = pack_window(days, K)
    f, l1, secs = fit_variant(pk, K, sharing, l1_policy)
    row = {"tag": tag, "K": K, "variant": variant, "rep": rep, "kappa": kappa or 0.0, "tilt": tilt or 0.0,
           "sharing": sharing, "l1_policy": l1_policy, "l1": l1, "D": D, "n_target": n_target, "secs": secs,
           **score(days, labels, pk, f, truth)}
    row["w_err"] = class_kernel_error(f, truth)
    return row


def load(pattern: str, tags: list[str] | None = None) -> pl.DataFrame:
    df = pl.concat([pl.read_parquet(p) for p in sorted(glob.glob(pattern))], how="diagonal_relaxed")
    return df.filter(pl.col("tag").is_in(tags)) if tags else df


def summarize(df: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    """Mean share MAE (5-share and four-way), pass rates, per-share bias and fit diagnostics by `by`."""
    share_cols = [c for c in df.columns if c.startswith("err_")]
    return df.group_by(by).agg(
        n=pl.len(), events=pl.col("n_events").median(), mae=pl.col("mae").mean(),
        mae_se=pl.col("mae").std() / pl.len().sqrt(), mae4=pl.col("mae4").mean(),
        mae4_se=pl.col("mae4").std() / pl.len().sqrt(), pass_rate=(pl.col("mae") < BAR).mean(),
        pass4_rate=(pl.col("mae4") < BAR).mean(), max_err=pl.col("max_err").mean(),
        **{c.replace("err_", "b_"): pl.col(c).mean() for c in share_cols},
        rho_err=(pl.col("rho") - pl.col("rho_true")).mean(), n_mae_aa=pl.col("n_mae_aa").mean(),
        self_n_err=pl.col("n_mae_self").mean(), w_err=pl.col("w_err").mean(), l1=pl.col("l1").median(),
        iters=pl.col("n_iter").median(), conv=pl.col("converged").mean(), viol=pl.col("n_viol").sum(),
        spread_gt005=(pl.col("start_spread") > 0.05).mean(), secs=pl.col("secs").mean(),
        secs_max=pl.col("secs").max(),
    ).sort(by)


def versus(df: pl.DataFrame, base: str, by: list[str]) -> pl.DataFrame:
    """Per-window differences of each arm from the `base` tag (same K, variant, rep, sharing,
    l1_policy), with standard errors over windows."""
    b = df.filter(pl.col("tag") == base).select(*KEY, mae0=pl.col("mae"), mae40=pl.col("mae4"),
                                                self0=pl.col("err_self"), other0=pl.col("err_other_agents"))
    j = df.filter(pl.col("tag") != base).join(b, on=KEY)
    d = {"d_mae": pl.col("mae") - pl.col("mae0"), "d_mae4": pl.col("mae4") - pl.col("mae40"),
         "d_self": pl.col("err_self") - pl.col("self0"), "d_other": pl.col("err_other_agents") - pl.col("other0")}
    return j.group_by(by).agg(n=pl.len(), **{k: v.mean() for k, v in d.items()},
                              **{f"{k}_se": v.std() / pl.len().sqrt() for k, v in d.items()}).sort(by)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="main")
    ap.add_argument("--K", type=int, nargs="+", default=[7, 10, 13, 20])
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--sharing", nargs="+", default=["cell", "class", "global"])
    ap.add_argument("--l1", nargs="+", default=["none", "cv", "cv_cross"])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--kappa", type=float, default=None)
    ap.add_argument("--tilt", type=float, default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--vs", default=None, help="with --summarize: differences from this tag")
    ap.add_argument("--by", nargs="+", default=["tag", "K", "variant", "sharing", "l1_policy"])
    ap.add_argument("--tags", nargs="+", default=None)
    a = ap.parse_args()
    if a.summarize:
        pl.Config.set_tbl_rows(300), pl.Config.set_tbl_cols(40), pl.Config.set_tbl_width_chars(400)
        pl.Config.set_float_precision(3)
        df = load(os.path.join(OUT, "recovery_*.parquet"), a.tags + [a.vs] if a.vs and a.tags else a.tags)
        print(versus(df, a.vs, a.by) if a.vs else summarize(df, a.by))
        return
    i, n = (int(x) for x in a.shard.split("/"))
    tasks = [(a.tag, K, v, r, a.kappa, a.tilt, s, l) for K in a.K for v in a.variants for r in range(a.reps)
             for s in a.sharing for l in a.l1]
    # Expensive tasks first (select_l1, many agents), then interleave for load balance.
    tasks.sort(key=lambda t: (t[7] == "none", -t[1], t[3], t[2], t[6], t[7]))
    tasks = tasks[i::n]
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    rows = []
    warm_up()
    with Pool(a.workers) as pool:
        for k, row in enumerate(pool.imap_unordered(run_task, tasks), 1):
            rows.append(row)
            if k % 20 == 0 or k == len(tasks):
                print(f"{k}/{len(tasks)} tasks, {time.time() - t0:.0f}s", flush=True)
    out = os.path.join(OUT, f"recovery_{a.tag}_{i}of{n}.parquet")
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(out)
    print(f"wrote {out} ({len(rows)} rows) in {time.time() - t0:.0f}s; CPU-seconds in fits "
          f"{np.sum([r['secs'] for r in rows]):.0f}")


if __name__ == "__main__":
    main()
