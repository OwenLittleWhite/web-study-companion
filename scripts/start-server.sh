#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir/server"

# Keep the normal entry point lightweight. This explicit override wins over
# `.env`, so starting the API never preloads the large local ASR model by surprise.
export FUNASR_PRELOAD=false

echo "Starting Study Companion service without preloading local FunASR."
echo "Use scripts/start-server-local-asr.sh to start and warm the local model."
exec "$project_dir/.venv/bin/python" run.py
