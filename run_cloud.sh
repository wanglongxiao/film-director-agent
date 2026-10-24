#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export WEBUI_CLOUD_MODE=true
export PYTHONPATH="$PWD/vendor${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$PWD/runtime/bin:$PATH"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
