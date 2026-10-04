#!/bin/bash
# Check whether aidigestorg/ai-village has a newer revision than the pinned one.
# One Hub API call per run (the "main" revision). When the revision changed, it
# downloads the new manifest.json through the file endpoint and prints the row
# count differences. It never switches the pinned revision. Appends a line to
# data/interim/hf_revision_checks.log.
set -uo pipefail
cd "$HOME/ai-village-swarm-dynamics"
PINNED=$(sed -n 's/^  revision: \([0-9a-f]\{40\}\).*/\1/p' configs/default.yaml)
LOG=data/interim/hf_revision_checks.log
H="Authorization: Bearer $(cat ~/.cache/huggingface/token)"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESP=$(curl -sS -m 60 -w '\n%{http_code}' -H "$H" https://huggingface.co/api/datasets/aidigestorg/ai-village/revision/main)
CODE=$(printf '%s' "$RESP" | tail -n1)
BODY=$(printf '%s' "$RESP" | sed '$d')
if [ "$CODE" != "200" ]; then
    echo "$NOW http=$CODE check failed" | tee -a "$LOG"
    exit 2
fi
read -r SHA MOD < <(printf '%s' "$BODY" | /usr/bin/python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("sha"), d.get("lastModified"))')
if [ "$SHA" = "$PINNED" ]; then
    echo "$NOW unchanged sha=$SHA lastModified=$MOD" | tee -a "$LOG"
    exit 0
fi
echo "$NOW CHANGED pinned=$PINNED new=$SHA lastModified=$MOD" | tee -a "$LOG"
mkdir -p data/interim/hf_new_revision
curl -sSfL -m 120 -H "$H" -o "data/interim/hf_new_revision/manifest_$SHA.json" \
    "https://huggingface.co/datasets/aidigestorg/ai-village/resolve/$SHA/manifest.json" || exit 3
/usr/bin/python3 - "$PINNED" "$SHA" <<'EOF'
import json, sys
old = json.load(open("data/raw/ai-village/manifest.json"))
new = json.load(open(f"data/interim/hf_new_revision/manifest_{sys.argv[2]}.json"))
print("exportedAt", old.get("exportedAt"), "->", new.get("exportedAt"))
o, n = old.get("rowCounts", {}), new.get("rowCounts", {})
for k in sorted(set(o) | set(n)):
    a, b = o.get(k), n.get(k)
    if a != b:
        print(f"  {k}: {a} -> {b}")
print("droppedColumns changed:", old.get("droppedColumns") != new.get("droppedColumns"))
EOF
exit 10
