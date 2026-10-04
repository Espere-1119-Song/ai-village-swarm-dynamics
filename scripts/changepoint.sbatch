#!/bin/bash
#SBATCH --job-name=avsd_changepoint
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas   # /scratch not writable there
# CPU-only. Module C (SPEC 7): change points and CHANGELOG alignment. Writes
# outputs/tables/{changepoints,changepoint_alignment,changepoint_series,lexical_words}.csv,
# data/processed/changepoint_series.parquet, outputs/figures/F5_changepoint_timeline.{pdf,png}
# and outputs/qa/changepoint.md. Extra arguments go to `python -m avsd.changepoint`.
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
python -m avsd.changepoint "$@"
