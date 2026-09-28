#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir/server"

# The dedicated local-ASR entry point opts into the expensive model load and
# GPU warm-up before the HTTP service begins accepting requests.
export FUNASR_PRELOAD=true

echo "Starting Study Companion service and preloading local FunASR."
echo "This can take time and use substantial RAM, GPU memory, and model cache space."
exec "$project_dir/.venv/bin/python" run.py
