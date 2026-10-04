#!/bin/bash
#SBATCH --job-name=avsd_hawkes_fit
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas   # /scratch not writable there
# CPU-only. Module A (SPEC 5) in one job: `sbatch scripts/hawkes_fit.sbatch goal` runs every stage
# of the goal windows (`avsd hawkes fit --window goal`), `... rolling` the rolling windows; both end
# with the assemble stage. scripts/hawkes_submit.py runs the same stages as parallel jobs, which is
# faster (runtimes in outputs/qa/hawkes.md). Extra arguments go to the CLI.
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1   # one BLAS thread per worker process
mkdir -p logs
WINDOW="${1:-goal}"
shift || true
avsd hawkes fit --window "$WINDOW" --workers "${SLURM_CPUS_PER_TASK:-16}" "$@"
