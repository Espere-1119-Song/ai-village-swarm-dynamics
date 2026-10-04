"""Run the D1 reproduction of the blog's swarm simulator (SPEC 8.2) and print the check table.

    python scripts/swarmsim_reproduce.py                 # defaults: 256 families of 16 tasks
    python scripts/swarmsim_reproduce.py --families 8    # quick run

Writes outputs/tables/swarmsim_reproduction.csv, outputs/tables/swarmsim_scaling.csv,
outputs/figures/swarmsim_coverage.{pdf,png}, outputs/qa/swarmsim_d1.md and
data/interim/swarmsim_family_stats.parquet.

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

import argparse
import math

from avsd.config import load_config
from avsd.swarmsim import run_reproduction


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="Path to a YAML config.")
    ap.add_argument("--families", type=int, help="Independent 16-task families.")
    ap.add_argument("--workers", type=int, help="Processes (default SLURM_CPUS_PER_TASK).")
    ap.add_argument("--gen-dags", type=int, help="DAGs for the generator statistics.")
    args = ap.parse_args()
    cfg = load_config(args.config)
    over = dict(cfg.get("swarmsim") or {})
    for key, val in (("families", args.families), ("workers", args.workers),
                     ("gen_dags", args.gen_dags)):
        if val is not None:
            over[key] = val
    cfg["swarmsim"] = over
    res = run_reproduction(cfg)
    for r in res["checks"]:
        ours = "" if not math.isfinite(r["ours"]) else f"{r['ours']:.3g}"
        print(f"{r['status']:>11}  {r['check']}: blog {r['blog']}, ours {ours}")
    rt = res["runtime"]
    print(f"runtime {rt['wall_s']:.0f} s wall, {rt['workers']} workers, {rt['cpu_s']:.0f} s CPU")
    print("outputs:", *res["outputs"].values(), sep="\n  ")


if __name__ == "__main__":
    main()
