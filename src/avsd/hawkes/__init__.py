"""Module A: multivariate Hawkes process of agent messages with exogenous inputs (SPEC 5).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from avsd.hawkes.bootstrap import BootstrapResult, bootstrap, bootstrap_reps
from avsd.hawkes.gof import Rescaling, compensator_at_events, time_rescaling
from avsd.hawkes.model import (
    BACKGROUND, BETAS, L1_SCOPES, SHARES, SHARING, STARTS, Day, Decomposition, HawkesFit, HawkesSpec, Packed,
    decompose, default_exo_names, fit, kernel_classes, l1_weights, loglik, pack, share_names,
    spectral_radius,
)
from avsd.hawkes.simulate import label_shares, simulate, simulate_day
from avsd.hawkes.validate import SHARES4, L1Selection, Recovery, pool_exogenous, recovery_check, select_l1

__all__ = [
    "BACKGROUND", "BETAS", "L1_SCOPES", "SHARES", "SHARES4", "SHARING", "STARTS", "BootstrapResult", "Day",
    "Decomposition",
    "HawkesFit", "HawkesSpec", "L1Selection", "Packed", "Recovery", "Rescaling", "bootstrap",
    "bootstrap_reps", "compensator_at_events", "decompose", "default_exo_names", "fit", "kernel_classes",
    "l1_weights", "label_shares", "loglik", "pack", "pool_exogenous", "recovery_check", "select_l1",
    "share_names",
    "simulate", "simulate_day", "spectral_radius", "time_rescaling",
]
