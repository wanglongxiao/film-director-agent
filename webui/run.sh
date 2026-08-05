#!/bin/bash
# VeFaaS 原生 python 运行时启动脚本（native-python3.12/v1）。
# VeFaaS 会以 bundle 根目录为 cwd 执行 ./run.sh，并通过 _FAAS_RUNTIME_PORT 指定监听端口。
set -e

pip install -r requirements.txt

HOST="0.0.0.0"
PORT="${_FAAS_RUNTIME_PORT:-8080}"

echo "Starting aw-director-agent Web UI (BFF) on ${HOST}:${PORT} ..."
exec python -m uvicorn server:app --host "$HOST" --port "$PORT"
