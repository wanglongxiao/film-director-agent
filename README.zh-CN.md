# aw-director-agent · 导演助手

一个基于 [VeADK](https://github.com/volcengine/veadk-python)（Volcengine Agent
Development Kit）构建、以 **AgentKit Runtime** 形式发布的「导演助手」智能体。它把
一个粗略想法一路推到「可拍摄套件」——基调概念、角色、大纲、分集、分镜、风格化关键帧、
预演视频——同时解决长文本生成的实际痛点（上下文爆炸、MAX_TOKENS 半路截断、工具失败、
配额抖动）。

提供两种入口：

- **AgentKit Runtime API**（`main.py`，端口 `:8000`）——标准 ADK 服务，
  包含 `/list-apps`、`/run`、`/run_sse`、会话与产物管理。可通过 `agentkit deploy`
  直接部署为**飞书机器人**。
- **Web UI + BFF**（`webui/`）——自建的流式聊天页面（FastAPI 后端 + 原生
  HTML/CSS/JS 前端），可连本地 ADK 服务或已部署的云端 Runtime，API Key
  在服务端保管，可部署到**火山引擎 VeFaaS** 作为 Serverless 应用。

> 云端 AgentKit Runtime 沿用历史名称 `veadk-demo`（网关域名保持稳定）；仓库
> 与本地工程更名为 `aw-director-agent`。

**English:** [README.md](README.md)

---

## 1. 解决什么问题

导演一部视听作品是**长流程、多模态、多工具串联**的活。一次性 LLM 调用做不到——
你需要：

| 痛点 | 朴素 LLM 聊天为何崩 | aw-director-agent 如何解决 |
|---|---|---|
| 长文本生成在 MAX_TOKENS 处被截断 | 回复半句话结束，无法续写 | 单轮输出预算 + 自动续写 + 本地 SQLite checkpoint |
| 聊天历史膨胀 → 上下文溢出 | 几轮后 LLM 400 / OOM | ADK `App` 滑动窗口压缩（token & 事件阈值触发） |
| 进程重启忘光设定 | 用户每次都要重新粘贴 | ShortTermMemory 后端 SQLite（重启不丢） |
| 工具繁多：搜索、图像、视频、代码、文档 | 手工串工具、模型经常撞额度 | 统一工具集 + 图/视频模型「自动降级链」 |
| 用户要**文件**而不是文字描述 | LLM 只会「描述」图片/文档 | 真实生成 JPG / MP4 / DOCX / PDF / PPTX / HTML，可在 Web UI 内直接查看/播放/下载 |
| 浏览器泄露 API Key | 静态页面里明文粘贴 key | BFF（服务端）持有 key，浏览器只见同源 `/api/*` |

---

## 2. 系统功能与卖点

### 2.1 Agent 能力矩阵

| 能力 | 对应工具 | 后端 |
|---|---|---|
| 网页搜索 / 拉取 / 链接阅读 | `web_search` / `web_fetch` / `link_reader` | VeADK 内置工具 |
| 分镜 / 海报 / 关键帧图像生成 | `image_generate` | 豆包 **Seedream** 系列（自动降级链） |
| 预演 / 预告视频生成 | `video_generate` | 豆包 **Seedance** 系列（自动降级链） |
| 真实代码执行 | `run_code` / `coding` | AgentKit 沙箱工具（CodeEnv） |
| Word / PDF / PPT / HTML **生成 + 读回** | `create_document` / `read_document` | 同一个沙箱，使用镜像内 `python-docx` / `python-pptx` / `pypdf` / `weasyprint` |
| 剧本圣经知识库 | `save_local_knowledge` / `search_local_knowledge` | **本地 SQLite**（不走云端向量检索） |
| 稳定长文本输出 | `auto_continue_generation` | 本地 SQLite checkpoint + 续写引导 |

系统指令中的强约束：

- **严禁云端知识库 / 向量检索类工具**。任何「retrieval」类内置工具已加入黑名单；只用本地 SQLite 知识库 + 会话上下文 + 用户补充信息。
- **同一沙箱会话贯穿工具调用**，`create_document` + `read_document` + `run_code` 看到的是同一批文件。
- **图/视频模型自动降级**：只有真正的「模型相关错误」（ModelNotOpen / AccessDenied）才会触发降级；参数错误、内容审核、额度不足会原样抛出，避免掩盖真实问题。

### 2.2 Web UI 特色

- **SSE 流式聊天**，实时展示「思考」可折叠面板与「工具调用」chip。
- **本地 ↔ 云端切换**：一个下拉框在本地 ADK（`http://127.0.0.1:8000`，
  app=`assistant`）与已部署的 AgentKit Runtime（app=`movie_script_agent`）之间切换。
  状态指示灯实时展示。
- **文件附件在聊天中原地渲染**：
  - **图片** → `<img>` 点击放大；
  - **视频** → HTML5 `<video controls>` 播放；
  - **PDF / HTML** → 折叠式 `<iframe>` 内联预览 + 下载；
  - **DOCX / PPTX** → 下载卡片。
  - 幕后由 `/api/file` 通过火山引擎签名的 RunCode 从 AgentKit 沙箱把文件读出来，
    浏览器无需直连沙箱。
- **历史会话侧栏**：
  - 一键切换过往对话；
  - 逐一删除（hover 出 `×`）或一键清空（二次确认）；
  - **最多 20 个会话**，超过时按 LRU 顺序自动淘汰最早的；
  - `localStorage` 持久化，刷新/重开浏览器不丢。
- **密钥隔离**：API Key 从不下发到浏览器，前端只跟同源 `/api/*` 通信。

---

## 3. Demo 截屏

截图放在 [`docs/screenshots/`](docs/screenshots/) 目录下。使用同名文件替换后即可自动渲染：

| # | 页面 | 路径 |
|---|---|---|
| 1 | Web UI 总览（聊天 + 历史侧栏） | `docs/screenshots/01-overview.png` |
| 2 | 流式回复（思考 + 工具 chip） | `docs/screenshots/02-streaming.png` |
| 3 | 图片附件内联展示（Seedream） | `docs/screenshots/03-image.png` |
| 4 | 视频播放（Seedance） | `docs/screenshots/04-video.png` |
| 5 | PDF 预览 + 下载卡片 | `docs/screenshots/05-pdf.png` |
| 6 | 历史侧栏（切换 / 删除 / 清空） | `docs/screenshots/06-history.png` |

```
![Web UI 总览](docs/screenshots/01-overview.png)
![流式回复](docs/screenshots/02-streaming.png)
![图片附件](docs/screenshots/03-image.png)
![视频播放](docs/screenshots/04-video.png)
![PDF 预览与下载](docs/screenshots/05-pdf.png)
![历史侧栏](docs/screenshots/06-history.png)
```

---

## 4. 使用的 Agent 框架与模型

### 4.1 框架：VeADK + Google ADK + AgentKit

- **[VeADK](https://github.com/volcengine/veadk-python)** —— 火山引擎 Agent
  Development Kit。在 Google ADK 之上做了火山原生扩展：豆包 / Seedream /
  Seedance 内置工具、沙箱集成、多种 memory 后端，以及 AgentKit 部署链路。
- **[Google ADK](https://github.com/google/adk-python)** —— 提供 `Agent`、
  `Runner`、Session Service、事件流、工具契约、模型回调
  （`before_model_callback` / `after_model_callback` /
  `on_model_error_callback`）与 `App` 级事件压缩配置。
- **[Volcengine AgentKit](https://www.volcengine.com/product/AgentKit)** ——
  托管 Agent 的运行时与工具链：`AgentkitAgentServerApp` 把 ADK app 包成 HTTP
  服务（`/list-apps` / `/run` / `/run_sse` + 会话 / 产物管理）；`agentkit deploy`
  读取 `.agentkit/agentkit.yaml` + `Dockerfile`，云端构建镜像并发布 Runtime。

### 4.2 LLM 与多模态模型

| 角色 | 默认模型 | 使用场景 |
|---|---|---|
| 推理 / 规划 | 火山 Ark 上的 `doubao-seed-1-6-250615`（通过固定推理接入点访问，默认 `ep-20260804114747-mc7ct`） | Agent 大脑 |
| 文生图（主模型） | `doubao-seedream-5-0-pro-260628` | `image_generate` — 降级链：`seedream-5-0-260128` / `4-5-251128` / `4-0-250828` |
| 文生视频（主模型） | `doubao-seedance-2-0-260128` | `video_generate` — 降级链：`seedance-1-5-pro-251215` / `1-0-pro-250528` |

三个角色共享**一把火山凭证**：本地 AK/SK 会自动派生出模型访问权限；云端 Runtime
上模型凭证由平台自动提供，无需额外配置。

---

## 5. 程序模块架构

```
aw-director-agent/
├── main.py                         # AgentKit Runtime 入口（ADK App + 压缩 + STM + 服务）
├── assistant/                      # Agent 本体、工具与本地持久化
│   ├── __init__.py                 # 导出 root_agent
│   ├── agent.py                    # 工具装配、模型降级、输出预算守护、自动续写
│   ├── document_tools.py           # create_document / read_document（沙箱兜底）
│   ├── continuation_store.py       # SQLite 输出 checkpoint（auto_continue_generation）
│   └── local_knowledge_store.py    # SQLite 剧本圣经：save_local_knowledge / search_local_knowledge
├── webui/                          # 自建聊天 UI + BFF
│   ├── server.py                   # FastAPI BFF：/api/config、/api/health、/api/chat（SSE）、/api/file
│   ├── sandbox_files.py            # 通过签名 RunCode 从 AgentKit 沙箱读回文件
│   ├── static/index.html           # 前端：流式聊天、附件渲染、历史侧栏
│   ├── requirements.txt            # BFF 依赖
│   ├── run_local.sh                # 本地调试（:8090，同时暴露 local + cloud 目标）
│   ├── run.sh                      # VeFaaS 运行时入口
│   └── deploy_vefaas.py            # VeFaaS 一键部署（首建或 update-bundle）
├── .agentkit/agentkit.yaml         # AgentKit 部署清单（envs、插件、runtime spec）
├── .github/workflows/deploy.yml    # CI：main 推送时 `agentkit deploy`
├── .env.example                    # 占位符 env — 复制为 .env
├── config.yaml                     # VeADK 静态配置（可被环境变量覆盖）
├── Dockerfile                      # Runtime 镜像
├── pyproject.toml / requirements.txt
└── src/aw_director_agent/          # 命令行入口（项目改名的账本）
```

### 5.1 运行拓扑

```
浏览器
  │  同源 /api/*
  ▼
┌────────────────────────────────────────────────────────┐
│ webui/server.py（FastAPI BFF）                         │
│   /api/chat  ─── SSE ─── 提取 text / thought /         │
│                          tool_call / file 事件         │
│   /api/file  ─── 签名 RunCode ── AgentKit 沙箱         │
└──────────────┬───────────────────────────┬─────────────┘
               │                           │
               ▼ target=local              ▼ target=cloud
┌──────────────────────────┐   ┌─────────────────────────────────┐
│ 本地 ADK :8000           │   │ AgentKit Runtime（云端）        │
│ python main.py           │   │  网关域名 + Bearer apikey       │
│  ├─ App（压缩配置）      │   │  app_name = movie_script_agent  │
│  ├─ ShortTermMemory sqlite│   │                                 │
│  └─ root_agent（assistant）│   └─────────────────────────────────┘
└──────────────────────────┘
```

两条路径遵循同一套事件契约，UI 对后端无感。

### 5.2 长文本输出流水线（回复为何不会被截断）

1. `before_model_callback` 对每轮设定固定的 `max_output_tokens`；
2. `after_model_callback` 捕获 `finish_reason=MAX_TOKENS` 并记录尾部；
3. `auto_continue_generation` 从 [continuation_store.py](assistant/continuation_store.py)
   读回最近 checkpoint，引导模型从「上一段停止的位置」续写，不重复；
4. App 级 `EventsCompactionConfig` 在滑动窗口或 token 阈值触发时压缩老事件，
   把 prompt 控制在可用范围内。

---

## 6. 配置

### 6.1 获取凭证

一个火山引擎账号 + 三件事：

1. **AK/SK** —— <https://console.volcengine.com/iam/keymanage/> → 新建访问密钥。
   记下 Access Key ID + Secret Access Key。本地开发**只需要这一项**。
2. **Ark 豆包推理接入点** —— <https://console.volcengine.com/ark>
   → 在线推理接入点 → 创建，选择推理模型（豆包 Seed 1.6 或同等）。
   记下 endpoint id（形如 `ep-YYYYMMDDhhmmss-xxxxx`），填入 `.env` 的
   `MODEL_AGENT_NAME`。*（云端 Runtime 上无需此步——凭证由平台自动提供。）*
3. **AgentKit 沙箱工具** —— <https://console.volcengine.com/agentkit>
   → 沙箱工具 → 创建，选择 CodeEnv 模板。记下 tool id（`t-xxxx…`），填入
   `.env` 的 `AGENTKIT_TOOL_ID*`（`.env.example` 已附带 demo 可用默认值）。
4. **飞书应用**（可选，仅当发布为飞书机器人时）—— <https://open.feishu.cn>
   → 创建自建应用 → 授予机器人消息权限。记下 `App ID` 与 `App Secret`。

### 6.2 `.env`

```bash
cp .env.example .env
```

至少填写：

```env
# --- 火山凭证（本地最小必填项）---
VOLCENGINE_ACCESS_KEY=AKLT…
VOLCENGINE_SECRET_KEY=…

# --- Agent 推理模型（Ark 接入点）---
MODEL_AGENT_API_KEY=…               # Ark API Key
MODEL_AGENT_NAME=ep-YYYYMMDD-xxxxx  # 你的推理接入点 ID
MODEL_AGENT_PROVIDER=openai
MODEL_AGENT_API_BASE=https://ark.cn-beijing.volces.com/api/v3/

# --- 可选：图/视频主模型（.env.example 已给默认值）---
MODEL_IMAGE_NAME=doubao-seedream-5-0-pro-260628
MODEL_VIDEO_NAME=doubao-seedance-2-0-260128

# --- AgentKit 沙箱 tool_id（run_code / coding / document tools 使用）---
AGENTKIT_TOOL_ID=t-…
AGENTKIT_TOOL_ID_SCRIPT=t-…

# --- Web UI：云端目标（BFF 保管，浏览器看不到）---
CLOUD_AGENT_BASE_URL=https://<your-runtime>.apigateway-cn-beijing.volceapi.com
CLOUD_AGENT_API_KEY=…               # 网关消费者 apikey
CLOUD_AGENT_APP_NAME=movie_script_agent
WEBUI_ENABLE_LOCAL=false            # 本地调试时为 true

# --- 飞书（仅飞书机器人部署需要）---
FEISHU_APP_ID=…
FEISHU_APP_SECRET=…
```

### 6.3 密钥保护约定

- `.env` 已加入 `.gitignore`，永不提交。`.env.example` 只放占位符。
- API Key 只在**服务端**流转。浏览器只跟同源 `/api/*` 说话，前端 bundle 里没有敏感值。
- CI（`.github/workflows/deploy.yml`）从 GitHub **Repo Secrets** 读取 AK/SK 与
  飞书凭证，不从代码里取。
- Web UI 部署到 VeFaaS 时，`.env` 作为**函数环境变量**在部署时注入，代码
  bundle 里不包含 `.env`。

---

## 7. 运行与发布

### 7.1 本地：Agent 服务（:8000）

```bash
uv venv                              # 或：python -m venv .venv
uv pip install -r requirements.txt   # 或：pip install -r requirements.txt
cp .env.example .env                 # 然后填入凭证
python main.py                       # -> http://0.0.0.0:8000
```

快速探针：

```bash
curl http://127.0.0.1:8000/list-apps
# -> ["assistant","src","webui"]（取决于你保留了哪些 app 目录）
```

### 7.2 本地：Web UI（:8090）

```bash
bash webui/run_local.sh
# -> http://127.0.0.1:8090/
```

`run_local.sh` 会设置 `WEBUI_ENABLE_LOCAL=true`，目标下拉框同时展示**本地
ADK 服务**与**已部署的云端 Runtime**。

### 7.3 发布为 云端 Runtime + 飞书机器人

```bash
export FEISHU_APP_ID=… FEISHU_APP_SECRET=…
agentkit deploy
```

自动读取 `.agentkit/agentkit.yaml` + `Dockerfile`，云端构建镜像、创建或更新
AgentKit Runtime；由于 manifest 已开启 `im.feishu`，`agentkit deploy` 会同时
挂上飞书代理，无需额外参数。重新部署复用同一域名，下游消费者无需重配。

CI/CD：向 `main` 推送时会触发 [.github/workflows/deploy.yml](.github/workflows/deploy.yml)，
在 GitHub Actions 里用 Repo Secrets 执行 `agentkit deploy`。

### 7.4 发布 Web UI 到 VeFaaS

```bash
.venv/bin/python webui/deploy_vefaas.py
```

- 首次运行：创建 VeFaaS 应用 `aw-director-webui`。
- 后续运行：`update_application_code_bundle` 上传新 bundle 到已有应用（URL 稳定，
  函数环境变量保留）。
- `.env` 会以函数环境变量注入 —— 部署后的函数 env 含
  `VOLCENGINE_ACCESS_KEY/SECRET_KEY`、`AGENTKIT_TOOL_ID*`、`CLOUD_AGENT_*`，
  这样 `/api/file`（需要用火山 SigV4 签名调 RunCode）在云端也能正常工作。

---

## 8. FAQ

**Q：图/视频模型 key 也要另配吗？**
不用。AK/SK 会自动派生模型访问权限。只有当你想钉死一把特定的凭证时，才需要覆盖
`MODEL_*_API_KEY`。

**Q：报错 `You've reached the limit on the session number of tool`。**
AgentKit 沙箱工具有每个 tool 的会话配额（通常 2 个）。每个不同的
`UserSessionId` 会占一个槽。用
`agentkit sandbox delete --tool-id $AGENTKIT_TOOL_ID --sid <id> --force`
手动释放，或等约 30 分钟自动过期。

**Q：UI 是怎么读取只存在于沙箱里的文档的？**
`webui/server.py` 在 SSE 中派发 `file` 事件，url 形如 `/api/file?path=…`。
浏览器请求该 url 时，`webui/sandbox_files.py` 用同一沙箱会话
（`movie_script_agent_{user_id}_{session_id}`）签一个 Volcengine `InvokeTool`
（RunCode）请求，把文件 base64 读出，用正确的 `Content-Type` /
`Content-Disposition` 回传。

**Q：历史会话存在哪儿？**
浏览器 `localStorage["awdir_sessions_v1"]`。上限 20 条，LRU 顺序，溢出时自动
淘汰最早的。清除站点数据即重置。

---

## 9. 许可 / 署名

Copyright (c) 2026 Alex Wang.

- 作者：Alex Wang · <https://github.com/wanglongxiao>
- 联系：<https://www.linkedin.com/in/alexwanglx/>

Open Source Usage：需保留署名；再分发时请保留源码头部的版权注释块。
