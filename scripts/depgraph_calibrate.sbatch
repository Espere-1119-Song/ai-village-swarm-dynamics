#!/bin/bash
#SBATCH --job-name=avsd_depgraph
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=48
#SBATCH --mem=200G
#SBATCH --time=03:00:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so scripts/env.sh cannot unpack the env there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# CPU-only. Modules D2 to D4 (SPEC 8.3 to 8.5) and figure F7: artifact touches of every turn
# (about 2 min, cached in data/interim/depgraph/), the dependency graph per village goal, the
# structure statistics against 64 generated DAGs per goal, step cost by layer and the
# continuation rate. Peak memory about 60 GB. Extra arguments go to scripts/depgraph_calibrate.py
# (--force-extract, --workers N).
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
python scripts/depgraph_calibrate.py "$@"
