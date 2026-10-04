#!/bin/bash
# Pack the node-local env into one tarball on NFS. Run on the login node after
# changing dependencies.
set -euo pipefail
mkdir -p "$HOME/envs"
tar -cf "$HOME/envs/avsd-env.tar.tmp" -C / \
    scratch/tmp/enxinson/avsd-venv scratch/tmp/enxinson/uv/python
mv "$HOME/envs/avsd-env.tar.tmp" "$HOME/envs/avsd-env.tar"
stat -c %Y "$HOME/envs/avsd-env.tar" > /scratch/tmp/enxinson/avsd-venv/.packed_from
ls -lh "$HOME/envs/avsd-env.tar"
