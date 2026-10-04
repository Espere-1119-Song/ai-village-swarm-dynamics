#!/bin/bash
#SBATCH --job-name=avsd_swarmsim
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
# CPU-only. Module D1 (SPEC 8.2): reproduction of the blog's swarm simulator. Writes
# outputs/tables/swarmsim_{reproduction,scaling}.csv, outputs/figures/swarmsim_coverage.{pdf,png},
# outputs/qa/swarmsim_d1.md and data/interim/swarmsim_family_stats.parquet.
# Extra arguments go to scripts/swarmsim_reproduce.py (--families N, --workers N, --gen-dags N).
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
python scripts/swarmsim_reproduce.py "$@"
