#!/bin/bash
#SBATCH --job-name=avsd_lineage_trees
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=48
#SBATCH --mem=220G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so scripts/env.sh cannot unpack the env there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# CPU-only. Module B2 (SPEC 6.4): transmission trees between agents.
# Stage 1 (avsd.lineage.b2_units): information units and occurrences in data/interim/b2/
#   (chat and search answers through the B1 extractor with spaCy, a memory scan, a scan of every
#   computer-use turn). Each stage is cached; pass --force to rebuild. About 45 min on 48 CPUs.
# Stage 2 (avsd.lineage.trees, `avsd lineage trees`): candidate parents, posterior, MAP tree,
#   200 posterior samples, H1 and H3, validation, synthetic runs, tables, F3 and F4, QA report.
# Usage: sbatch scripts/lineage_trees.sbatch [units|trees|all] [extra args for stage 2]
# Writes outputs/tables/trees_*.csv, outputs/figures/F3_*, F4_*, outputs/qa/lineage_trees.md and
# data/labels/parents.csv (explicit references, private).
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
STAGE="${1:-all}"
shift || true
if [ "$STAGE" = "units" ] || [ "$STAGE" = "all" ]; then
    python -m avsd.lineage.b2_units --workers "${SLURM_CPUS_PER_TASK:-48}"
fi
if [ "$STAGE" = "trees" ] || [ "$STAGE" = "all" ]; then
    python -m avsd.lineage.trees --workers "${SLURM_CPUS_PER_TASK:-48}" "$@"
fi
