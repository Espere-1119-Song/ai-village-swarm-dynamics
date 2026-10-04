#!/bin/bash
#SBATCH --job-name=avsd_prelabel
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --constraint=a40|l40|l40s|a6000
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:30:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so neither env can be unpacked or built there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# Module B1 validation set (SPEC 6.3.4): pre-label the 500 units of data/labels/memory_pairs.csv
# with a local open-weight model (Qwen3-14B, Apache-2.0, bf16, one 48 GB GPU, inference only;
# owner's decision 2026-10-01: no paid API), then write the review sheet for the owner.
# Stages (src/avsd/lineage/prelabel.py):
#   prepare   project env, CPU: recover units and excerpts, write the requests
#   download  public weights to ~/models/Qwen3-14B, once and anonymously (never the owner's token)
#   infer     separate vLLM env on node-local /scratch, one GPU, greedy JSON-schema decoding
#   report    data/labels/memory_pairs_review.csv (+ _README.md), outputs/qa/memory_prelabel.md
# Every prompt and output is cached in data/interim/llm_cache/memory_prelabel/, so a rerun
# generates nothing. About 6 min on a node without the vLLM env (2-3 min to build it, 1 min to
# read the weights from NFS), 3-4 min otherwise. Ran on L40 nodes (ll-l40-2, dj-l40-0).
# Since the re-check of 2026-10-01 (scripts/prelabel_strong.sbatch: Qwen3.5-122B-A10B-FP8 and gpt-oss-120b),
# `report` also needs their cached answers; it builds the review sheet from them (re-check design).
# After the owner fills human_label (review priorities 1 and 2; CPU, seconds):
#   source scripts/env.sh && python -m avsd.lineage.prelabel metrics
# metrics scores rule sets v1, v2, v3 (data/labels/memory_pairs_rule_v<K>.csv), Qwen3-14B and the two
# re-check models, weighted by the design's inclusion probabilities.
# Overrides: PRELABEL_MODEL_DIR, PRELABEL_VLLM_VERSION. 0.19.0 pins torch 2.10 with CUDA 12.8, which
# runs on the GPU nodes' drivers (535 through CUDA minor-version compatibility, 570 natively);
# vLLM >= 0.20 needs torch >= 2.11 built for CUDA 13, which needs driver >= 580.
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs

# Never send the owner's Hugging Face token (its API quota is used up) and keep small-file
# caches off the slow NFS home.
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN || true
SCR=/scratch/tmp/enxinson
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HOME="$SCR/hf_home"
export VLLM_CACHE_ROOT="$SCR/vllm_cache" TRITON_CACHE_DIR="$SCR/triton_cache" \
       TORCHINDUCTOR_CACHE_DIR="$SCR/inductor_cache" XDG_CACHE_HOME="$SCR/xdg_cache" \
       VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false
MODEL_DIR="${PRELABEL_MODEL_DIR:-$HOME/models/Qwen3-14B}"
VLLM_VERSION="${PRELABEL_VLLM_VERSION:-0.19.0}"
VENV="$SCR/vllm-venv"
UV="$HOME/.local/bin/uv"

echo "[$(date +%T)] node $(hostname), GPU $(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)"
python -m avsd.lineage.prelabel prepare --workers "${SLURM_CPUS_PER_TASK:-8}"
python -m avsd.lineage.prelabel download --dest "$MODEL_DIR"

if [ "$(cat "$VENV/.avsd_vllm" 2>/dev/null)" != "$VLLM_VERSION" ]; then
    echo "[$(date +%T)] building the vLLM $VLLM_VERSION env in $VENV"
    rm -rf "$VENV"
    UV_PYTHON_INSTALL_DIR="$SCR/uv/python-vllm" "$UV" venv -q --python 3.11 "$VENV"
    "$UV" pip install -q --python "$VENV/bin/python" "vllm==$VLLM_VERSION"
    echo "$VLLM_VERSION" > "$VENV/.avsd_vllm"
fi
echo "[$(date +%T)] inference"
HF_HUB_OFFLINE=1 PYTHONPATH="$AVSD/src" "$VENV/bin/python" -m avsd.lineage.prelabel infer --model-dir "$MODEL_DIR"
python -m avsd.lineage.prelabel report
echo "[$(date +%T)] done"
