#!/bin/bash
# Run on the Mac: rebuild reports/index.html on GRASP, then copy that one file to
# /Users/songenxin/Downloads/avsd_report/index.html (override with AVSD_REPORT_DIR).
# The page is self-contained: open it straight from disk, no server needed.
set -euo pipefail

DEST_DIR="${AVSD_REPORT_DIR:-/Users/songenxin/Downloads/avsd_report}"
GR="$(command -v gr || echo "$HOME/.local/bin/gr")"
REMOTE="grasp:ai-village-swarm-dynamics/reports/index.html"

mkdir -p "$DEST_DIR"
"$GR" 'cd $AVSD && source scripts/env.sh && avsd report'
# Copy to a temporary name first so an open browser tab never sees a half-written file.
scp -q "$REMOTE" "$DEST_DIR/index.html.part" 2> >(grep -v hostkeys_prove >&2)
mv "$DEST_DIR/index.html.part" "$DEST_DIR/index.html"
echo "$DEST_DIR/index.html ($(du -h "$DEST_DIR/index.html" | cut -f1))"
