"""Submit module A on the real data as parallel Slurm jobs (scripts/hawkes_stage.sbatch).

accept (goal windows: fits, recovery checks, merges) and rolling start at once; boot (12 shards by
default: each replicate is fitted from three starts and the full-data fit), matched (2), sens and
valid start when accept has finished; assemble runs last. Each job has 16 cores. Stages skip work
whose result file exists, so the script can be rerun after a failure.

    python scripts/hawkes_submit.py            # from the repository root on the login node
    python scripts/hawkes_submit.py --dry-run
    python scripts/hawkes_submit.py --skip-accept --boot-shards 16

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import subprocess


def submit(args: list[str], dep: list[str] | None, dry: bool, name: str) -> str:
    cmd = ["sbatch", "--parsable", f"--job-name=avsd_hawkes_{name}"]
    if dep:
        cmd.append("--dependency=afterok:" + ":".join(dep))
    cmd += ["scripts/hawkes_stage.sbatch", *args]
    if dry:
        print(" ".join(cmd))
        return name
    jid = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip().split(";")[0]
    print(f"{jid}  {' '.join(args)}" + (f"  after {','.join(dep)}" if dep else ""))
    return jid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-accept", action="store_true", help="accept already finished")
    ap.add_argument("--boot-shards", type=int, default=12)
    ap.add_argument("--matched-shards", type=int, default=2)
    a = ap.parse_args()
    plan = (("boot", a.boot_shards), ("matched", a.matched_shards), ("sens", 1), ("valid", 1))
    acc = [] if a.skip_accept else [submit(["accept"], None, a.dry_run, "accept")]
    jobs = [submit(["rolling"], None, a.dry_run, "rolling")]
    for stage, n in plan:
        jobs += [submit([stage, f"{i}/{n}"], acc, a.dry_run, f"{stage}{i}") for i in range(n)]
    submit(["assemble"], acc + jobs, a.dry_run, "assemble")


if __name__ == "__main__":
    main()
