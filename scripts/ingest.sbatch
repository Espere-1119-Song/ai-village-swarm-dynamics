#!/bin/bash
#SBATCH --job-name=avsd_ingest
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas   # /scratch not writable there
# CPU-only. Converts the gz JSONL tables to parquet and writes outputs/qa/ingest.md.
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
avsd ingest "$@"
