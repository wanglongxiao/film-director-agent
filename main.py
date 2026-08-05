# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""movie-script-agent — 以 AgentKit Runtime 形式服务的电影剧本智能助手。

装配三件事，确保 Agent 执行永不超出模型上下文限制：

1. **上下文自动压缩**：把 `root_agent` 放入 ADK `App`，并配置
   `events_compaction_config`（滑动窗口 + token 阈值触发的历史摘要）。压缩配置
   必须通过 `App` 传入才会在 Runner 每轮结束时生效——因此这里显式构造 `App` 而
   非传裸 agent。
2. **本地会话存储**：`ShortTermMemory(backend="sqlite")` 将会话/事件持久化到本地
   sqlite 文件，进程重启不丢历史。
3. **服务暴露**：`AgentkitAgentServerApp` 提供标准 ADK API server
   （/list-apps、/run、/run_sse、会话与产物管理），监听 0.0.0.0:8000。
"""

import os

from agentkit.apps import AgentkitAgentServerApp
from google.adk.apps.app import App, EventsCompactionConfig

from veadk.memory.short_term_memory import ShortTermMemory

from assistant import root_agent

# --- 本地会话存储（sqlite，重启不丢） ---------------------------------------
# 可用 VEADK_STM_DB_PATH 覆盖；默认落在 /tmp（云 Runtime 上可写）。
_STM_DB_PATH = os.getenv("VEADK_STM_DB_PATH", "/tmp/movie_script_sessions.db")
short_term_memory = ShortTermMemory(
    backend="sqlite",
    local_database_path=_STM_DB_PATH,
)

# --- 上下文自动压缩配置 ------------------------------------------------------
# summarizer 留空 -> ADK 自动用 root_agent 的模型构建 LlmEventSummarizer。
# compaction_interval/overlap_size：滑动窗口触发；token_threshold/event_retention_size：
# 按 prompt token 触发并保留最近 N 条原始事件不被压缩。二者共同确保上下文可控。
_compaction_config = EventsCompactionConfig(
    compaction_interval=int(os.getenv("VEADK_COMPACTION_INTERVAL", "6")),
    overlap_size=int(os.getenv("VEADK_COMPACTION_OVERLAP", "1")),
    token_threshold=int(os.getenv("VEADK_COMPACTION_TOKEN_THRESHOLD", "24000")),
    event_retention_size=int(os.getenv("VEADK_COMPACTION_RETENTION", "30")),
)

# App name 需匹配 ^[a-zA-Z][a-zA-Z0-9_-]*$ 且不能为 "user"；与 agent app_name 保持一致。
adk_app = App(
    name="movie_script_agent",
    root_agent=root_agent,
    events_compaction_config=_compaction_config,
)

# --- 服务暴露：传 App（而非裸 agent）以保留压缩配置 --------------------------
server = AgentkitAgentServerApp(app=adk_app, short_term_memory=short_term_memory)
app = server.app  # ASGI app：`uvicorn main:app` 亦可

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=8000)
