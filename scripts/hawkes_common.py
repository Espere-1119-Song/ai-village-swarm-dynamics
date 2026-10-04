"""Shared helpers for the module A experiment scripts (scripts/hawkes_*.py).

The simulated windows (avsd.hawkes.synth) are a regime set by its constants
(class kernel means W_CLASS, self shares 0.23-0.39, rho 0.65-0.85, days of
about 3.5 h, K <= 20); numbers measured on them are conditional on that regime
and do not carry over to real windows (scripts/hawkes_matched_recovery.py).

Scoring follows SPEC 5.6-1: share errors against the realized parent labels.
"mae" averages the five shares (baseline, human, system, other agents, self);
"mae4" is the SPEC 5.5 four-way decomposition with the exogenous sources
pooled, which is what the 0.05 bar was set for. The near-empty system share
(about 1%, estimated almost without error) makes mae about 4/5 of mae4.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os
import time

import numpy as np

from avsd.hawkes import decompose, fit, label_shares, pack, pool_exogenous, select_l1
from avsd.hawkes.synth import (  # noqa: F401  (re-exported for the scripts)
    EXO, SPEC, W_CLASS, H, Truth, _scale_offdiag, make_truth, realistic_window, simulate_window,
)

SEED = 20261003
OUT = os.environ.get("HAWKES_OUT", "data/interim/hawkes_probe")
BAR = 0.05  # SPEC 5.6-1


def fit_variant(pk, K: int, sharing: str, l1_policy: str, **kw):
    """Fit with l1 = 0 ("none"), the select_l1 choice over all cells ("cv"), or
    over cross-agent cells only ("cv_cross"); returns (fit, l1, seconds)."""
    t = time.time()
    scope = "cross" if l1_policy == "cv_cross" else "all"
    l1 = 0.0
    if l1_policy != "none":
        l1 = select_l1(pk, K, kernel_sharing=sharing, l1_scope=scope, **kw).l1
    f = fit(pk, K, l1=l1, kernel_sharing=sharing, l1_scope=scope, **kw)
    return f, l1, time.time() - t


def share_errors(got: dict, true: dict) -> dict:
    """5-share and SPEC four-way (exogenous pooled) errors of got against true."""
    names = list(true)
    err = np.array([got[s] - true[s] for s in names])
    e4 = pool_exogenous(err)
    return {"mae": float(np.abs(err).mean()), "mae4": float(np.abs(e4).mean()), "max_err": float(np.abs(err).max()),
            **{f"err_{s}": float(e) for s, e in zip(names, err)}, "err_exogenous": float(e4[1]),
            **{f"true_{s}": float(true[s]) for s in names}}


def score(days, labels, pk, f, truth: Truth | None = None) -> dict:
    """Share errors against the realized labels, and n / rho errors against the truth."""
    K = pk.K
    true = label_shares(days, labels, K, pk.exo_names)
    got = decompose(pk, f).shares
    out = {**share_errors(got, true),
           "rho": f.rho, "n_iter": f.n_iter, "converged": bool(f.converged), "n_viol": int(f.n_violations),
           "n_events": int(pk.tgt_ev.size), "start": f.start, "start_spread": f.start_spread}
    if truth is not None:
        out["rho_true"] = float(np.abs(np.linalg.eigvals(truth.n_fit[:, :K])).max())
        out["n_mae_aa"] = float(np.abs(f.n[:, :K] - truth.n_fit[:, :K]).mean())
        out["n_mae_self"] = float(np.abs(np.diag(f.n) - np.diag(truth.n_fit)).mean())
    return out


def class_kernel_error(f, truth: Truth) -> float | None:
    """Max abs error of the fitted class weights (self, other, human, system)."""
    if f.kernel_sharing != "class":
        return None
    return float(np.abs(f.w - truth.w_class).max())


def pack_window(days, K):
    return pack(days, K, SPEC, exo_names=EXO)


def warm_up() -> None:
    """Compile the numba kernels in the parent process before a Pool forks: workers then
    inherit them and never read the on-disk cache, which concurrent processes can corrupt
    (a worker that dies while loading it hangs Pool.imap)."""
    _, days, labels, _, _ = realistic_window(7, "sparse", [SEED, 0, 0, 0])
    pk = pack_window(days[:1], 7)
    f = fit(pk, 7, kernel_sharing="class", starts=("default",))
    score(days[:1], labels[:1], pk, f)


__all__ = [
    "BAR",
    "EXO",
    "OUT",
    "SEED",
    "SPEC",
    "W_CLASS",
    "H",
    "Truth",
    "class_kernel_error",
    "fit_variant",
    "make_truth",
    "pack_window",
    "realistic_window",
    "score",
    "share_errors",
    "simulate_window",
    "warm_up",
]
