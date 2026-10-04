#!/bin/bash
#SBATCH --job-name=avsd_lineage_memory
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=48
#SBATCH --mem=200G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so scripts/env.sh cannot unpack the env there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# CPU-only. Module B1 (SPEC 6.3): memory chains, fact-unit retention, H2 test.
# Full run about 30 min on 48 CPUs (spaCy on 13.8M distinct lines); about 3 min from the cache.
# Writes outputs/tables/memory_*.csv, outputs/figures/F6_memory_retention.{pdf,png},
# outputs/qa/lineage_memory.md, data/interim/memory_facts.parquet and
# data/labels/memory_pairs.csv. Line hashes and anchors are cached in
# data/interim/b1_cache/ (no text); pass --reextract to rebuild them.
# Other arguments: --workers N, --agents "Name A,Name B" (pilot outputs get a pilot_ prefix),
# --rules v2 (literal presence fallback and line-aligned modification; _v2 outputs next to v1).
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
python -c "import sys; from avsd.lineage.memory import main; main(sys.argv[1:])" "$@"
