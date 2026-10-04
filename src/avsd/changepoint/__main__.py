"""`python -m avsd.changepoint [--config PATH] [--workers N]`: run module C (SPEC 7)."""

from __future__ import annotations

import argparse
import json

from avsd.changepoint.pipeline import run_changepoint
from avsd.config import load_config

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None, help="YAML config (default configs/default.yaml)")
    ap.add_argument("--workers", type=int, default=0, help="processes (default SLURM_CPUS_PER_TASK)")
    a = ap.parse_args()
    res = run_changepoint(load_config(a.config), n_workers=a.workers or None)
    print(json.dumps(res, indent=1, default=str))
