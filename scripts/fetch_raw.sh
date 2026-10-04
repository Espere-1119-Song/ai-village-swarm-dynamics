#!/bin/bash
# Download the non-screenshot files at the pinned revision with curl.
# Used when the Python environment is not ready. Token is read from the
# Hugging Face token file and only sent to huggingface.co.
set -euo pipefail
cd "$HOME/ai-village-swarm-dynamics"
R=838b4150303ca8228e8edb432d8b8ccae353d258
BASE=https://huggingface.co/datasets/aidigestorg/ai-village/resolve/$R
OUT=data/raw/ai-village
mkdir -p "$OUT/images/computer-use-turns"
H="Authorization: Bearer $(cat ~/.cache/huggingface/token)"
FILES="README.md SCHEMA.md CHANGELOG.md manifest.json example.py
agents.jsonl.gz villages.jsonl.gz village_goals.jsonl.gz agent_goals.jsonl.gz chat_rooms.jsonl.gz
summaries.jsonl.gz claude_code_sessions.jsonl.gz chat_messages.jsonl.gz computer_use_sessions.jsonl.gz
claude_code_messages.jsonl.gz events.jsonl.gz agent_memories.jsonl.gz computer_use_turns.jsonl.gz
images/computer-use-turns/index.json"
for f in $FILES; do
  if [ -s "$OUT/$f.done" ] || { [ -s "$OUT/$f" ] && [[ "$f" != *.gz ]]; }; then
    echo "skip $f"; continue
  fi
  curl -sSfL --retry 5 -C - -H "$H" -o "$OUT/$f" "$BASE/$f"
  echo ok > "$OUT/$f.done"
  echo "$(date +%T) $(du -h "$OUT/$f" | cut -f1) $f"
done
echo DONE
