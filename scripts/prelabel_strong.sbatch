#!/bin/bash
#SBATCH --job-name=avsd_prelabel_strong
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --gres=gpu:4
#SBATCH --constraint=l40|l40s|a40|a6000
#SBATCH --cpus-per-task=16
#SBATCH --mem=240G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so neither env can be unpacked or built there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# Module B1 validation set (SPEC 6.3.4): the owner asked on 2026-10-01 that two stronger local open-weight
# models re-check the Qwen3-14B pre-labels before the owner reviews them. Each model labels the same 500
# cached requests (data/interim/llm_cache/memory_prelabel/requests.jsonl: same prompts and excerpts as
# Qwen3-14B, no rule or Qwen3-14B labels) on one node of 48 GB GPUs, inference only:
#   sbatch scripts/prelabel_strong.sbatch qwen35_122b                                            # 4 GPUs, TP 4
#   sbatch --gres=gpu:2 --mem=128G --cpus-per-task=8 --time=03:00:00 \
#          scripts/prelabel_strong.sbatch gptoss_120b                                            # 2 GPUs, TP 2
# Extra arguments go to `python -m avsd.lineage.prelabel infer` (e.g. --limit 8). Both models run in eager mode
# with gpu_memory_utilization 0.92 (MODELS): with CUDA graphs, vLLM 0.19 sized the KV cache without the graph
# memory and the capture ran out of memory on 48 GB GPUs (jobs 598313, 598314). Ran 2026-10-01 as jobs 599292
# (Qwen3.5, 4x L40, dj-l40-0) and 599293 (gpt-oss, 2x A40, dj-a40-1). Loading from the NFS home takes 12-17 min
# when the job's memory limit is below the weights' size (the page cache thrashes); --mem above it, or a node
# that still caches the files, loads in under a minute.
# Weights: scripts/prelabel_download.sbatch (anonymous, pinned revisions in avsd.lineage.prelabel.MODELS).
# vLLM 0.19.1 in its own node-local env (the Qwen3-14B jobs keep 0.19.0 in $SCR/vllm-venv): it has
# Qwen3_5MoeForConditionalGeneration and GptOssForCausalLM and runs on driver 535 (vLLM >= 0.20 needs
# driver >= 580). Settings per model (reasoning, sampling, token budgets, retries) are in MODELS and
# are written with every cached output and to runs_<model>.jsonl.
# After both models: python -m avsd.lineage.prelabel report (review sheet, README, QA comparison).
set -euo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh"
mkdir -p logs
MODEL="${1:?usage: sbatch scripts/prelabel_strong.sbatch <model key> [infer args]}"
shift

# Never send the owner's Hugging Face token; the weights are local, so stay offline.
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN || true
SCR=/scratch/tmp/enxinson
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HOME="$SCR/hf_home" HF_HUB_OFFLINE=1
export VLLM_CACHE_ROOT="$SCR/vllm_cache" TRITON_CACHE_DIR="$SCR/triton_cache" \
       TORCHINDUCTOR_CACHE_DIR="$SCR/inductor_cache" XDG_CACHE_HOME="$SCR/xdg_cache" \
       VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false
VLLM_VERSION="${PRELABEL_VLLM_VERSION:-0.19.1}"
VENV="$SCR/vllm-venv-$VLLM_VERSION"
UV="$HOME/.local/bin/uv"

echo "[$(date +%T)] node $(hostname), model $MODEL, GPUs:"
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader
# Two jobs on one node may both need the env: build it under a node-local lock.
(
    flock 9
    if [ "$(cat "$VENV/.avsd_vllm" 2>/dev/null)" != "$VLLM_VERSION" ]; then
        echo "[$(date +%T)] building the vLLM $VLLM_VERSION env in $VENV"
        rm -rf "$VENV"
        UV_PYTHON_INSTALL_DIR="$SCR/uv/python-vllm" "$UV" venv -q --python 3.11 "$VENV"
        "$UV" pip install -q --python "$VENV/bin/python" "vllm==$VLLM_VERSION"
        echo "$VLLM_VERSION" > "$VENV/.avsd_vllm"
    fi
) 9>"$SCR/.vllm-venv-$VLLM_VERSION.lock"
echo "[$(date +%T)] inference"
PYTHONPATH="$AVSD/src" "$VENV/bin/python" -m avsd.lineage.prelabel infer --model "$MODEL" "$@"
echo "[$(date +%T)] done"
