#!/bin/bash
# Render the demo video: data from outputs/, frames drawn by scenes.html in headless Chrome, H.264 by ffmpeg.
# Usage: scripts/demo_video/build_video.sh [out.mp4]   (python3 with the project packages, node 22+, Google Chrome, ffmpeg)
# With KOKORO_DIR set to the folder of the Kokoro model files, narration.py adds the English voice-over (needs uv).
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$DIR/../.." && pwd)
OUT=${1:-$ROOT/reports/demo.mp4}; FRAMES=$(mktemp -d); PORT=8795
python3 "$DIR/data_prep.py"
python3 -m http.server $PORT --bind 127.0.0.1 --directory "$DIR" >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER; rm -rf "$FRAMES"' EXIT
sleep 1
node "$DIR/render_frames.mjs" "http://127.0.0.1:$PORT/scenes.html" "$FRAMES" 30
AUDIO=(-an)
if [ -n "${KOKORO_DIR:-}" ]; then
  (cd "$DIR" && uv run --no-project --quiet --with kokoro-onnx --with soundfile python narration.py "$KOKORO_DIR")
  AUDIO=(-i "$DIR/narration.wav" -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:a aac -b:a 160k -ar 48000 -shortest)
fi
ffmpeg -v error -y -framerate 30 -i "$FRAMES/f_%05d.jpg" "${AUDIO[@]:0:2}" \
  -vf "scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p" \
  "${AUDIO[@]:2}" -c:v libx264 -preset slow -crf 20 -profile:v high -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv -movflags +faststart "$OUT"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT"
