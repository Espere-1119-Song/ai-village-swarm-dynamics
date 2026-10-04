#!/bin/bash
#SBATCH --job-name=avsd_monitor_validation
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas   # /scratch not writable there
# CPU-only. External validation of module A against the LLM monitor, V1 and V2
# (`python -m avsd.validate.monitor_hawkes`, docs/decisions.md). Needs module A's goal-window outputs
# (data/interim/hawkes_fit, outputs/tables/hawkes_*.csv) and data/processed/monitor_findings.parquet.
# Extra arguments go to the module (e.g. --boot 500).
set -euo pipefail
cd "$HOME/ai-village-swarm-dynamics"
. scripts/env.sh
mkdir -p logs
python -m avsd.validate.monitor_hawkes "$@"
