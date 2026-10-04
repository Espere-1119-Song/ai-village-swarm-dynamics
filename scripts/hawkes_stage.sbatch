#!/bin/bash
#SBATCH --job-name=avsd_hawkes
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas   # /scratch not writable there
# CPU-only. One stage (or one shard of a stage) of module A:
#   sbatch scripts/hawkes_stage.sbatch <stage> [i/n] [--reverse]
# stage: accept, boot, matched, sens, valid, rolling, assemble (avsd.hawkes.pipeline). Results go to
# data/interim/hawkes_fit/; assemble writes outputs/ and data/processed/hawkes_parents.parquet.
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1   # one BLAS thread per worker process
mkdir -p logs
STAGE="$1"
SHARD="${2:-0/1}"
shift; shift || true
python -m avsd.hawkes.pipeline "$STAGE" --shard "$SHARD" --workers "${SLURM_CPUS_PER_TASK:-16}" "$@"
