#!/bin/bash
#SBATCH --job-name=avsd_build_events
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --cpus-per-task=16
#SBATCH --mem=200G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas   # /scratch not writable there
# CPU-only. Builds data/processed/{events_unified,run_periods,pause_segments,
# agents,roster_daily,agent_room_intervals,human_ids,changelog}.parquet and
# outputs/qa/build_events.md.
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
avsd build-events "$@"
