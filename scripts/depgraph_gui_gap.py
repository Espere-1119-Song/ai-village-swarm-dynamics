"""Diagnose why most D2 GUI writes have no focus (follow-up to SPEC 8.3).

    python scripts/depgraph_gui_gap.py

Writes outputs/qa/swarmsim_gui_gap.md, outputs/tables/depgraph_gui_gap.csv,
outputs/tables/depgraph_gui_heuristics.csv and outputs/tables/depgraph_gui_eras.csv; the private
per-write table goes to data/interim/depgraph/gui_writes.parquet.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse

from avsd.config import load_config
from avsd.swarmsim.depgraph_data import default_workers
from avsd.swarmsim.gui_gap import run_gui_gap


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="Path to a YAML config.")
    ap.add_argument("--workers", type=int, default=0, help="Processes (default SLURM_CPUS_PER_TASK).")
    args = ap.parse_args()
    res = run_gui_gap(load_config(args.config), args.workers or default_workers(),
                      log=lambda m: print(m, flush=True))
    print("outputs:", *res["files"].values(), sep="\n  ")


if __name__ == "__main__":
    main()
