#!/bin/bash
# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

# 本地调试启动：加载项目 .env（拿到 CLOUD_AGENT_API_KEY 等），
# 并强制开启「本地」目标，方便在本地同时调试 本地 Agent(:8000) 与 云端 Agent。
#
# 用法：  bash webui/run_local.sh          # 默认 8090 端口
#         WEBUI_PORT=9000 bash webui/run_local.sh
set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# 本地调试同时暴露 本地/云端 两个目标
export WEBUI_ENABLE_LOCAL=true
export WEBUI_PORT="${WEBUI_PORT:-8090}"

echo "Web UI (BFF) 本地调试： http://127.0.0.1:${WEBUI_PORT}/"
exec .venv/bin/python webui/server.py
