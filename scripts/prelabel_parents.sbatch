#!/bin/bash
#SBATCH --job-name=avsd_prelabel_parents
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --constraint=a40|l40|l40s|a6000
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so neither env can be unpacked or built there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# Module B2 labelling sheet (SPEC 6.4.5): 50 occurrences for the owner to label by hand, with pre-labels
# from a local open-weight model (Qwen3-14B, Apache-2.0, bf16, one 48 GB GPU, inference only; owner's
# decision 2026-10-01: no paid API). Run after `avsd lineage trees` (it reads the MAP parents).
# Stages (src/avsd/lineage/prelabel_parents.py):
#   prepare   project env, CPU: sample 50 items, build masked excerpts and prompts
#   download  public weights to ~/models/Qwen3-14B, once and anonymously (never the owner's token)
#   infer     separate vLLM env on node-local /scratch, one GPU, greedy JSON-schema decoding
#   report    data/labels/parents_review.csv (+ _README.md, private), outputs/qa/parent_prelabel.md
# Every prompt and output is cached in data/interim/llm_cache/parent_prelabel/.
# Re-check (owner's request 2026-10-01): Qwen3.5-122B-A10B-FP8 and gpt-oss-120b answer the same cached requests
# through `sbatch scripts/prelabel_strong.sbatch <qwen35_122b|gptoss_120b> --task parents`; `report` then adds
# their choices and a suggested parent, sets priority 1 where they disagree with each other or with the MAP
# parent, and keeps the first sheet as data/labels/parents_review_qwen14b.csv. Rerunning this script (prepare)
# draws a new sample and makes those answers stale.
# After the owner fills human_parent: source scripts/env.sh && python -m avsd.lineage.prelabel_parents metrics
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs

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
python -m avsd.lineage.prelabel_parents prepare
python -m avsd.lineage.prelabel_parents download --dest "$MODEL_DIR"

if [ "$(cat "$VENV/.avsd_vllm" 2>/dev/null)" != "$VLLM_VERSION" ]; then
    echo "[$(date +%T)] building the vLLM $VLLM_VERSION env in $VENV"
    rm -rf "$VENV"
    UV_PYTHON_INSTALL_DIR="$SCR/uv/python-vllm" "$UV" venv -q --python 3.11 "$VENV"
    "$UV" pip install -q --python "$VENV/bin/python" "vllm==$VLLM_VERSION"
    echo "$VLLM_VERSION" > "$VENV/.avsd_vllm"
fi
echo "[$(date +%T)] inference"
HF_HUB_OFFLINE=1 PYTHONPATH="$AVSD/src" "$VENV/bin/python" -m avsd.lineage.prelabel_parents infer --model-dir "$MODEL_DIR"
python -m avsd.lineage.prelabel_parents report
echo "[$(date +%T)] done"
