#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install --upgrade pip
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/server/requirements.txt"

if [[ ! -f "$project_dir/.env" ]]; then
  cp "$project_dir/.env.example" "$project_dir/.env"
fi

echo "Core environment ready."
echo "For local ASR, run: $project_dir/.venv/bin/pip install -r $project_dir/server/requirements-local-asr.txt"
