# aw-director-agent

一个基于 [VeADK](https://github.com/volcengine/veadk-python) 的「电影剧本智能助手」项目，
可本地通过 ADK API Server（/run、/run_sse、Dev UI）运行，也可通过 `agentkit deploy` 部署为飞书机器人。
另附一个自建的轻量 Web 聊天 UI（前端 + BFF 后端），支持对接本地或云端 Agent，并可部署到火山引擎 VeFaaS（见「Web UI」章节）。

> 说明：云端 AgentKit Runtime 仍沿用历史名称 `veadk-demo`（其调用域名保持不变、持续可用），
> 仓库与本地工程名统一为 `aw-director-agent`。

核心特性：
- 长任务稳态输出：单轮输出预算 + 自动续写 + 本地 sqlite checkpoint（避免 MAX_TOKENS 中断）
- 本地知识沉淀：使用本地 sqlite 保存/检索设定与素材（save_local_knowledge / search_local_knowledge）
- 严格禁用检索链路：禁止调用任何知识库/向量检索工具（如 load_knowledgebase、vesearch）

## Run it locally

```bash
pip install -r requirements.txt
cp .env.example .env        # set your Volcengine AK/SK
python main.py              # serves the ADK API on http://0.0.0.0:8000
```

Probe it: `curl localhost:8000/list-apps`.

## Deploy it (with the Feishu bot)

```bash
export FEISHU_APP_ID=... FEISHU_APP_SECRET=...
agentkit deploy
```

`im.feishu` is already enabled in `.agentkit/agentkit.yaml`, so `agentkit deploy`
also ships the Feishu proxy — no flags needed. See the docs for creating the
Feishu app and granting bot permissions.

## Web UI（自建轻量聊天 UI + BFF）

`webui/` 提供一个自建的流式聊天 Web 界面，前端只调用同源 `/api/chat`，
云端 Agent 的调用域名与 apikey 全部由 BFF 后端保管，**不会下发到浏览器**。
支持在「本地 Agent（ADK :8000，app=`assistant`）」与「云端 Agent
（AgentKit Runtime，app=`movie_script_agent`）」之间切换。

本地调试（同时暴露 本地 / 云端 两个目标）：

```bash
bash webui/run_local.sh          # 默认 http://127.0.0.1:8090/
```

部署到火山引擎 VeFaaS（仅暴露云端目标，apikey 作为函数环境变量注入）：

```bash
.venv/bin/python webui/deploy_vefaas.py
```

相关环境变量（写在项目根 `.env`，部署时由 VeADK 注入到 VeFaaS 函数）：
`CLOUD_AGENT_BASE_URL` / `CLOUD_AGENT_API_KEY` / `CLOUD_AGENT_APP_NAME` / `WEBUI_ENABLE_LOCAL`。

## Next steps

- 根据需要调整 `assistant/agent.py` 的指令与工具集（尤其是长内容生成策略与分段交付格式）。
- 若要沉淀更多结构化素材，可扩展 `assistant/local_knowledge_store.py` 的 schema 与查询能力。
