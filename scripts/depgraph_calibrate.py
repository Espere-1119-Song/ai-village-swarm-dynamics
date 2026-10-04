"""Run modules D2 to D4 (SPEC 8.3 to 8.5) and figure F7 on the real data.

    python scripts/depgraph_calibrate.py                  # main version (rules v2); cached touches if present
    python scripts/depgraph_calibrate.py --force-extract  # re-extract the artifact touches
    python scripts/depgraph_calibrate.py --rules v1       # sensitivity version; outputs get a _v1 suffix

Writes outputs/tables/depgraph_*.csv, outputs/figures/F7_depgraph_generator.{pdf,png} and
outputs/qa/swarmsim_d2_d4.md; private intermediates go to data/interim/depgraph/.
Same as `avsd swarmsim calibrate`.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse

from avsd.config import load_config
from avsd.swarmsim.calibrate import run_calibration


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="Path to a YAML config.")
    ap.add_argument("--force-extract", action="store_true", help="Re-extract the artifact touches.")
    ap.add_argument("--workers", type=int, help="Processes (default SLURM_CPUS_PER_TASK).")
    ap.add_argument("--rules", default=None,
                    help="Touch rules: v2 (main, confirmed by the owner; default) or v1 (sensitivity, outputs _v1).")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.workers:
        cfg["swarmsim_calibrate"] = {**(cfg.get("swarmsim_calibrate") or {}), "workers": args.workers}
    res = run_calibration(cfg, force_extract=args.force_extract, log=lambda m: print(m, flush=True),
                          rules=args.rules)
    print("outputs:", *res["outputs"].values(), sep="\n  ")
    print(f"runtime {res['runtime']['wall_s']:.0f} s on {res['runtime']['workers']} processes")


if __name__ == "__main__":
    main()
