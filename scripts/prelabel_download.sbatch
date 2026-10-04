#!/bin/bash
#SBATCH --job-name=avsd_prelabel_download
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --exclude=al-l40s-0.grasp.maas
# Weights of the two B1 re-check models (owner's approval 2026-10-01; no GPU needed), from the official
# Hugging Face repositories at the revisions pinned in avsd.lineage.prelabel.MODELS, anonymously:
#   Qwen/Qwen3.5-122B-A10B-FP8  -> ~/models/Qwen3.5-122B-A10B-FP8  (about 127 GB, Apache-2.0)
#   openai/gpt-oss-120b         -> ~/models/gpt-oss-120b           (about 65 GB, Apache-2.0; original/ and
#                                                                    metal/ are skipped)
# Usage: sbatch scripts/prelabel_download.sbatch [model key ...]   (default: qwen35_122b gptoss_120b)
# The weights are deleted after inference (scripts/prelabel_strong.sbatch, then `rm -rf` of the two dirs).
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs

# Never send the owner's Hugging Face token: no token variables, no implicit token, and HF_HOME on
# /scratch (so ~/.cache/huggingface/token is not read either).
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN || true
SCR=/scratch/tmp/enxinson
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HOME="$SCR/hf_home_dl" \
       HF_XET_CHUNK_CACHE_SIZE_BYTES=0 HF_HUB_DISABLE_PROGRESS_BARS=1 DO_NOT_TRACK=1
MODELS=("$@")
[ ${#MODELS[@]} -gt 0 ] || MODELS=(qwen35_122b gptoss_120b)

echo "[$(date +%T)] node $(hostname); downloading ${MODELS[*]}"
pids=()
for m in "${MODELS[@]}"; do
    python -m avsd.lineage.prelabel download --model "$m" > "logs/avsd_prelabel_download-${SLURM_JOB_ID:-0}-$m.log" 2>&1 &
    pids+=($!)
done
rc=0
for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
        echo "[$(date +%T)] ${MODELS[$i]}: done"
    else
        echo "[$(date +%T)] ${MODELS[$i]}: FAILED"; rc=1
    fi
    tail -n 3 "logs/avsd_prelabel_download-${SLURM_JOB_ID:-0}-${MODELS[$i]}.log" || true
done
du -sh "$HOME"/models/* || true
exit $rc
