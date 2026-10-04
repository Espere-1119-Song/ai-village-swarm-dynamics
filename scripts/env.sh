# Source at the start of every job: `source scripts/env.sh`.
# GRASP's NFS home is very slow for small files, so the Python env lives on
# node-local /scratch. It is packed once into ~/envs/avsd-env.tar (one big
# file, fast over NFS) and unpacked here when the node lacks the current copy.
# Absolute paths inside the venv stay valid because every node uses the same
# /scratch/tmp/enxinson prefix.
# Files written by jobs are private: data/ holds gated data and personal text.
umask 077
export AVSD="$HOME/ai-village-swarm-dynamics"
export UV_PYTHON_INSTALL_DIR=/scratch/tmp/enxinson/uv/python
export UV_CACHE_DIR=/scratch/tmp/enxinson/uv/cache
export AVSD_VENV=/scratch/tmp/enxinson/avsd-venv
if ! mkdir -p /scratch/tmp/enxinson 2>/dev/null || [ ! -w /scratch/tmp/enxinson ]; then
    echo "env.sh: /scratch/tmp is not writable on $(hostname); resubmit with --exclude=$(hostname)" >&2
    return 1 2>/dev/null || exit 1
fi
_tar="$HOME/envs/avsd-env.tar"
_stamp="$AVSD_VENV/.packed_from"
if [ -f "$_tar" ] && [ "$(cat "$_stamp" 2>/dev/null)" != "$(stat -c %Y "$_tar")" ]; then
    mkdir -p /scratch/tmp/enxinson
    rm -rf "$AVSD_VENV" "$UV_PYTHON_INSTALL_DIR"
    tar -xf "$_tar" -C /
    stat -c %Y "$_tar" > "$_stamp"
fi
export PATH="$AVSD_VENV/bin:$PATH"
cd "$AVSD"
