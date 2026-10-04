#!/bin/bash
#SBATCH --job-name=avsd_gemini_label
#SBATCH --account=gu-account
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x-%j.out
# al-l40s-0 has no writable /scratch, so the project env cannot be unpacked there.
#SBATCH --exclude=al-l40s-0.grasp.maas
# Gemini as an extra independent rater of the rows the owner labels blind (owner's request 2026-10-01,
# free-tier key, data terms accepted by the owner; the owner's blind labels stay the reference and Gemini
# output is never shown to the owner). scripts/gemini_label.py:
#   prepare  redacted prompts from data/labels/{memory_pairs,parents}_blind.csv (spaCy names, emails, phones
#            replaced), once; data/interim/llm_cache/gemini_hard/requests.jsonl
#   run      cache-driven labelling: hard rows (B1 stratum A, B2) on gemini-3.1-pro-preview then 2.5 Pro, the
#            rest on 2.5 Flash; backs off on 429, stops a model for the day when its daily quota is used up
#   export   data/labels/memory_pairs_gemini.csv and parents_gemini.csv (private)
#   compare  aggregates in the private cache dir (compare.md), not in outputs/
# The key (~/.config/avsd/gemini_key) is read at run time and sent only to generativelanguage.googleapis.com
# in the x-goog-api-key header; it is never printed, logged or cached.
# When rows wait for a daily quota reset (exit code 3) or the time budget ran out (4), the job resubmits
# itself to start after the reset (midnight Pacific time + 5 min) or in 5 minutes, at most GEMINI_MAX_ROUNDS
# rounds and not after GEMINI_DEADLINE (local time).
set -uo pipefail
source "$HOME/ai-village-swarm-dynamics/scripts/env.sh" || exit 1
mkdir -p logs
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN GEMINI_API_KEY GOOGLE_API_KEY || true
ROUND="${GEMINI_ROUND:-1}"
MAX_ROUNDS="${GEMINI_MAX_ROUNDS:-6}"
DEADLINE="${GEMINI_DEADLINE:-2026-10-04T12:00:00}"

echo "[$(date +%T)] node $(hostname), round $ROUND"
python scripts/gemini_label.py prepare || exit 1
python scripts/gemini_label.py run --minutes 330
rc=$?
python scripts/gemini_label.py export
python scripts/gemini_label.py compare
python scripts/gemini_label.py status
if { [ "$rc" -eq 3 ] || [ "$rc" -eq 4 ]; } && [ "$ROUND" -lt "$MAX_ROUNDS" ] \
        && [ "$(date +%s)" -lt "$(date -d "$DEADLINE" +%s)" ]; then
    if [ "$rc" -eq 3 ]; then begin=$(python scripts/gemini_label.py next-reset); else begin=now+5minutes; fi
    sbatch --begin="$begin" --export=ALL,GEMINI_ROUND=$((ROUND + 1)) scripts/gemini_label.sbatch
    echo "[$(date +%T)] resubmitted for $begin (round $((ROUND + 1)))"
fi
echo "[$(date +%T)] done (run exit code $rc)"
