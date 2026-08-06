# film-director-agent · Director Assistant

> Repo: **[github.com/wanglongxiao/film-director-agent](https://github.com/wanglongxiao/film-director-agent)** · Live demo: **[VeFaaS Web UI](https://s9tgaudevr5vp3i737sc8.apigateway-cn-beijing.volceapi.com)**

An AI **film-director assistant** built on [VeADK](https://github.com/volcengine/veadk-python)
(Volcengine Agent Development Kit) and shipped as an **AgentKit Runtime**. It
turns a rough idea into a shootable package — tone & concept, characters,
outline, episode breakdown, shot lists, style-graded key frames, and previz
video — while surviving the practical pain points of long-form LLM generation
(context blowup, MAX\_TOKENS mid-cut-off, tool failure, quota churn).

Two front doors are provided:

- **AgentKit Runtime API** (`main.py`, port `:8000`) — standard ADK server with
  `/list-apps`, `/run`, `/run_sse`, sessions, artifacts. Also deployable as a
  **Feishu bot** via `agentkit deploy`.
- **Web UI + BFF** (`webui/`) — a self-hosted streaming chat page (FastAPI
  backend + vanilla HTML/CSS/JS frontend) that talks to either the local ADK
  server or the deployed cloud runtime, hides the API key on the server side,
  and can be deployed to **Volcengine VeFaaS** as a serverless app.

**中文说明：** [README.zh-CN.md](README.zh-CN.md)

***

## 1. Feature highlights

### 1.1 Agent capabilities

| Capability                                         | Underlying tool                                   | Backend                                                                                |
| -------------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Web search & fetch & link read                     | `web_search` / `web_fetch` / `link_reader`        | VeADK builtin                                                                          |
| Storyboard / poster / key-frame generation         | `image_generate`                                  | Doubao **Seedream** models (auto-fallback chain)                                       |
| Previz / teaser video generation                   | `video_generate`                                  | Doubao **Seedance** models (auto-fallback chain)                                       |
| Real code execution                                | `run_code` / `coding`                             | AgentKit sandbox tool\_id (CodeEnv)                                                    |
| Word / PDF / PPT / HTML **generation + read-back** | `create_document` / `read_document`               | Same sandbox, using image-baked `python-docx` / `python-pptx` / `pypdf` / `weasyprint` |
| Story-bible knowledge base                         | `save_local_knowledge` / `search_local_knowledge` | **Local SQLite** (no cloud vector-search hop)                                          |
| Reliable long-form output                          | `auto_continue_generation`                        | Local SQLite checkpoint + resume prompt                                                |

Strict guarantees enforced in the system instruction:

- **No cloud vector-search / knowledge-base tools.** Any built-in "retrieval" style tool is blacklisted; the agent uses only the local SQLite knowledge store, chat context, and user-supplied information.
- **Same sandbox session across tools** so `create_document` + `read_document` + `run_code` see the same files.
- **Model auto-fallback** for image/video: only truly *model-related* errors (ModelNotOpen / AccessDenied) trigger fallback — parameter errors, moderation refusals, and quota errors surface as-is.

### 1.2 Web UI highlights

- **Streaming SSE** chat with a live "thinking" collapsible pane and tool-call chips.
- **Local ↔ Cloud switch**: one dropdown targets either the local ADK
  (`http://127.0.0.1:8000`, app=`assistant`) or the deployed AgentKit runtime
  (`app=movie_script_agent`). Health status shown live.
- **Auto mode (unattended long runs)**: for long jobs that need many continuation
  turns (script + storyboards + image/video + a mixed image-and-text PDF), flip the
  top **"Auto"** toggle. Whenever the agent stops at `MAX_TOKENS` or wraps a stage
  and asks you to "reply continue", the UI shows a **10-second countdown** banner;
  if nobody acts before it expires, it auto-sends "继续" (continue) so the long task
  runs to completion hands-free.
  - **Interruptible anytime**: any interaction during the countdown (focusing the
    input, hitting stop, switching sessions, …) **immediately cancels** the pending
    auto-continue and hands control back to you.
  - **Continuation detection**: the frontend `shouldAutoContinue()` uses a lenient
    regex to catch "continue" signals wrapped in Markdown bold / quotes / closing
    questions, so it doesn't miss them.
  - **Stop button**: while a run is in flight the "Send" button becomes "Stop";
    clicking it aborts the current SSE request via `AbortController` and rolls the
    UI back to the pre-send state.
- **File attachments** rendered inline in the chat:
  - **Images** → `<img>` with click-to-open;
  - **Videos** → HTML5 `<video controls>`;
  - **PDF / HTML** → inline `<iframe>` preview toggle + download;
  - **DOCX / PPTX** → download card.
  - Behind the scenes, `/api/file` reads generated files from the AgentKit
    sandbox via signed Volcengine RunCode calls, so browsers never need direct
    sandbox access.
- **History sessions** in a left sidebar:
  - Switch between past conversations with one click;
  - Delete a single session (× on hover) or clear all with confirmation;
  - **Capped at 20 sessions**, oldest auto-evicted with LRU order;
  - Persisted in `localStorage` — survives page reload.
- **Key isolation**: API keys never leave the server. The browser only ever
  sees same-origin `/api/*` endpoints.

***

## 2. Demo screenshots

All shots are of the deployed Web UI (BFF at `webui/server.py` + static frontend
at `webui/static/index.html`), talking to either the local ADK server or the
cloud AgentKit Runtime.

### 2.1 Auto mode (unattended long runs)

Auto mode is the Web UI's best fit for long-running tasks: when the agent stops
at `MAX_TOKENS` or wraps a stage and asks the user to "reply continue", the UI
shows a 10-second countdown banner; if nobody intervenes, it auto-sends
"continue" and keeps the pipeline moving. Any user interaction cancels the
pending auto-continue immediately and returns control to the operator.

Demo Video: [00-autorun.mp4](https://raw.githubusercontent.com/wanglongxiao/film-director-agent/main/docs/screenshots/00-autorun.mp4)

This clip shows the real Auto-mode behavior: a long task reaches a
"continue" boundary, the countdown banner appears, and the UI resumes execution
automatically without manual babysitting.

### 2.2 Web UI overview — chat + history sidebar

![Web UI overview](docs/screenshots/01-overview.png)

Two-column layout: left is the LRU-managed 20-session history (switch / delete-one
/ clear-all); right is the streaming chat pane. Target switch (local vs. cloud)
is a single radio at the top.

### 2.3 Streaming reply with thinking & tool-call chips

![Streaming reply](docs/screenshots/02-streaming.png)

Server-Sent Events stream `text` / `thought` / `tool_call` / `file` events.
The frontend collapses the model's thinking into a foldable block and renders
each tool invocation as a compact chip so you can see which sandbox action
fired.

### 2.4 Inline image attachment (Seedream)

![Image attachment](docs/screenshots/03-image.png)

`image_generate` returns a public TOS URL for a Seedream-rendered still —
storyboard panels, key frames, posters. The BFF passes it through to the UI
which shows it inline as an attachment card with one-click download.

### 2.5 Inline video player (Seedance)

![Video attachment](docs/screenshots/04-video.png)

`video_generate` returns a public URL for a Seedance-rendered clip. It is
mounted directly as a `<video controls>` element so you can preview
previz / teasers without leaving the chat.

### 2.6 PDF card with preview + download

![PDF preview & download](docs/screenshots/05-pdf.png)

`create_document` writes docx / pdf / pptx / html inside the AgentKit sandbox
(`/home/gem/veadk_docs/*`). Because sandbox files have no public URL, the BFF
`/api/file` endpoint pipes bytes back over signed AgentKit RunCode — the
frontend surfaces a preview + a download button.

### 2.7 History sidebar — switch / delete / clear-all

![History sidebar](docs/screenshots/06-history.png)

Sessions persist in `localStorage["awdir_sessions_v1"]` (up to 20, LRU-evicted).
Titles auto-derive from the first user message (≤24 chars); `renderMessage()`
faithfully rebuilds attachments, thought-blocks, and tool chips when you switch
back to an older session.

***

## 3. What problem does it solve?

Directing an audiovisual project is a **long, multimodal, multi-tool pipeline**.
A single "one-shot" LLM call can't do it — you need:

| Pain point                                    | What breaks a naïve LLM chat                     | How film-director-agent handles it                                                                 |
| --------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Long-form generation gets cut at MAX\_TOKENS  | Reply ends mid-sentence, no way to resume        | Per-turn output budget + auto-continue + local SQLite checkpoint                                   |
| Chat history explodes → context overflow      | LLM 400 / OOM after a few turns                  | ADK `App` sliding-window compaction (token & event thresholds)                                     |
| Every restart forgets the story bible         | Users re-paste setup                             | ShortTermMemory backed by SQLite (survives restart)                                                |
| Tool sprawl: search, image, video, code, docs | Ad-hoc chain-of-tools, models drift out of quota | Unified tool set + auto model-fallback chain for image/video                                       |
| Users want the file, not a text preview       | LLM just describes the picture / doc             | Real files (JPG / MP4 / DOCX / PDF / PPTX / HTML) rendered, played, and downloadable in the Web UI |
| API-key leakage in browser                    | Copy-paste keys into a static page               | BFF (server) holds the keys; browser only sees same-origin `/api/*`                                |

***

## 4. Underlying framework & models

### 4.1 Framework: VeADK + Google ADK + AgentKit

- **[VeADK](https://github.com/volcengine/veadk-python)** — Volcengine Agent
  Development Kit. Extends Google ADK with Volcengine-native goodies:
  Doubao / Seedream / Seedance builtin tools, sandbox integration, memory
  backends, and the AgentKit deploy pipeline.
- **[Google ADK](https://github.com/google/adk-python)** — provides `Agent`,
  `Runner`, session service, event stream, tool contracts, model-callback
  hooks (`before_model_callback` / `after_model_callback` /
  `on_model_error_callback`) and the `App`-level events-compaction config.
- **[Volcengine AgentKit](https://www.volcengine.com/product/AgentKit)** —
  the runtime & tooling that hosts the agent as a service: `AgentkitAgentServerApp`
  wraps the ADK app into a HTTP server (`/list-apps` / `/run` / `/run_sse`
  - session / artifact management), and `agentkit deploy` reads
    `.agentkit/agentkit.yaml` + `Dockerfile` to build & publish a cloud runtime.

### 4.2 LLM & multimodal models

| Role                 | Default model                                       | Where used                                                                             |
| -------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Reasoning / planning | `doubao-seed-2-1-pro-260628` on Volcengine ModelArk | agent brain                                                                            |
| Text-to-image (main) | `doubao-seedream-5-0-pro-260628`                    | `image_generate` — fallback chain: `seedream-5-0-260128` / `4-5-251128` / `4-0-250828` |
| Text-to-video (main) | `doubao-seedance-2-0-260128`                        | `video_generate` — fallback chain: `seedance-1-5-pro-251215` / `1-0-pro-250528`        |

All three roles share a **single Volcengine credential**: the AK/SK you set
locally auto-derives model access; on the AgentKit cloud runtime, the model
credential is provided by the platform, so nothing else needs configuring.

***

## 5. Module architecture

```
film-director-agent/
├── main.py                         # AgentKit Runtime entry (ADK App + compaction + STM + server)
├── assistant/                      # The agent, tools, and local persistence
│   ├── __init__.py                 # exposes root_agent
│   ├── agent.py                    # tool assembly, model fallback, budget guards, auto-continue
│   ├── document_tools.py           # create_document / read_document (sandbox-backed)
│   ├── document_draft_store.py      # SQLite incremental draft store (long docs assembled server-side)
│   ├── continuation_store.py       # SQLite output checkpoint (auto_continue_generation)
│   └── local_knowledge_store.py    # SQLite bible: save_local_knowledge / search_local_knowledge
├── webui/                          # Self-hosted chat UI + BFF
│   ├── server.py                   # FastAPI BFF: /api/config, /api/health, /api/chat (SSE), /api/file
│   ├── sandbox_files.py            # Read files back from AgentKit sandbox via signed RunCode
│   ├── static/index.html           # Frontend: streaming chat, attachments, history sidebar
│   ├── requirements.txt            # BFF deps
│   ├── run_local.sh                # Local dev on :8090 (both local + cloud targets)
│   ├── run.sh                      # VeFaaS runtime entry
│   └── deploy_vefaas.py            # One-shot VeFaaS deploy (create or update-bundle)
├── .env.example                    # Placeholder env — copy to .env
├── config.yaml                     # VeADK static config (overridable by env)
├── requirements.txt                # Cloud AgentKit Runtime deps
├── tests/                          # Offline unit-test suite (stdlib unittest)
│   ├── run_all.py                  # Convenience runner (isolated temp DBs + quiet logs)
│   ├── test_stores.py              # Draft / continuation / knowledge SQLite stores
│   ├── test_agent.py               # Tools, budget guards, auto-continue, model fallback
│   ├── test_server.py              # Web UI BFF: file extraction, SSE, /api/config, /api/file
│   ├── test_document_tools.py      # create/read_document validation + sandbox session-id
│   └── test_sandbox_files.py       # Sandbox file read guards + marker parsing
├── .github/workflows/tests.yml     # CI: runs the unit-test suite on push / PR
└── src/aw_director_agent/          # Console-script entry (project rename bookkeeping)
```

> **Not in the public repo (kept locally by `.gitignore`):**
> `.agentkit/agentkit.yaml`, `.github/workflows/deploy.yml`, `Dockerfile`,
> `.dockerignore`, `pyproject.toml`, `uv.lock`, `.python-version` — these encode
> private deploy identifiers and container plumbing specific to the maintainer's
> environment. (The offline `tests.yml` CI workflow *is* public.) You can
> recreate the rest for your own fork with `agentkit init` + `uv init`.

### 5.1 Runtime shape

```
Browser
  │  same-origin /api/*
  ▼
┌────────────────────────────────────────────────────────┐
│ webui/server.py  (FastAPI BFF)                         │
│   /api/chat  ─── SSE ─── extracts text / thought /     │
│                          tool_call / file events       │
│   /api/file  ─── signed RunCode ── AgentKit sandbox    │
└──────────────┬───────────────────────────┬─────────────┘
               │                           │
               ▼ target=local              ▼ target=cloud
┌──────────────────────────┐   ┌─────────────────────────────────┐
│ local ADK server :8000   │   │ AgentKit Runtime (cloud)         │
│ python main.py           │   │  gateway + Bearer apikey         │
│  ├─ App(compaction)      │   │  app_name = movie_script_agent   │
│  ├─ ShortTermMemory sqlite│   │                                 │
│  └─ root_agent (assistant)│   └─────────────────────────────────┘
└──────────────────────────┘
```

Both paths speak the same event contract, so the UI is agnostic to which
backend it's talking to.

### 5.2 Long-form output pipeline (why replies don't cut off)

1. `before_model_callback` sets a fixed `max_output_tokens` per turn.
2. `after_model_callback` catches `finish_reason=MAX_TOKENS` and marks the tail.
3. `auto_continue_generation` reads the last checkpoint from
   [continuation\_store.py](assistant/continuation_store.py) and asks the model
   to resume from where it stopped, without repeating.
4. On the *App* level, `EventsCompactionConfig` summarizes older events when a
   sliding window or a token threshold is crossed, keeping the prompt bounded.

***

## 6. Configuration

### 6.1 Get credentials

You need one Volcengine account with three things enabled:

1. **AK/SK** — <https://console.volcengine.com/iam/keymanage/> → create an
   access key. Copy Access Key ID + Secret Access Key. These are the *only*
   credentials required for local development.
2. **Ark (Doubao) inference endpoint** — <https://console.volcengine.com/ark>
   → 在线推理接入点 (Inference Endpoints) → 创建 → pick the reasoning model
   (Doubao Seed 2.1 or equivalent). Copy the endpoint ID (looks like
   `ep-YYYYMMDDhhmmss-xxxxx`). Set it as `MODEL_AGENT_NAME` in `.env`.
   *(Skip this on the cloud runtime — it uses a platform-provided credential.)*
3. **AgentKit sandbox tool** — <https://console.volcengine.com/agentkit>
   → 沙箱工具 (Sandbox tools) → 创建 → CodeEnv template. Copy the tool ID
   (`t-xxxx…`). Set `AGENTKIT_TOOL_ID*` in `.env` (the sample already ships a
   working default for the demo tool).
4. **Feishu app** *(optional, only if deploying as a bot)* — <https://open.feishu.cn>
   → 创建自建应用 → grant bot messaging scopes. Copy `App ID` and `App Secret`.

### 6.2 `.env`

```bash
cp .env.example .env
```

Fill in at minimum:

```env
# --- Volcengine credentials (only these are truly required to run locally) ---
VOLCENGINE_ACCESS_KEY=AKLT…
VOLCENGINE_SECRET_KEY=…

# --- Ark inference endpoint for the agent brain ---
MODEL_AGENT_API_KEY=…               # Ark API Key
MODEL_AGENT_NAME=ep-YYYYMMDD-xxxxx  # Your inference endpoint ID
MODEL_AGENT_PROVIDER=openai
MODEL_AGENT_API_BASE=https://ark.cn-beijing.volces.com/api/v3/

# --- Optional: pin the image / video main models (defaults ship in .env.example) ---
MODEL_IMAGE_NAME=doubao-seedream-5-0-pro-260628
MODEL_VIDEO_NAME=doubao-seedance-2-0-260128

# --- AgentKit sandbox tool_id (used by run_code / coding / document tools) ---
AGENTKIT_TOOL_ID=t-…
AGENTKIT_TOOL_ID_SCRIPT=t-…

# --- Web UI: cloud target (BFF holds these; browser never sees them) ---
CLOUD_AGENT_BASE_URL=https://<your-runtime>.apigateway-cn-beijing.volceapi.com
CLOUD_AGENT_API_KEY=…               # gateway consumer key
CLOUD_AGENT_APP_NAME=movie_script_agent
WEBUI_ENABLE_LOCAL=false            # 'true' when running locally

# --- Feishu (only if deploying as a bot) ---
FEISHU_APP_ID=…
FEISHU_APP_SECRET=…
```

### 6.3 Secrets hygiene

- `.env` is **gitignored** and never committed. `.env.example` only ships
  placeholders.
- API keys travel *server-side* only. The browser talks to same-origin
  `/api/*`; nothing sensitive is ever written to the frontend bundle.
- When deploying the Web UI to VeFaaS, `.env` is injected as function
  environment variables at deploy time; it is *not* bundled with the code.
- The AgentKit deploy manifest and any CI workflow that would carry
  `AGENTKIT_TOOL_ID*` / gateway ids are kept out of the public repo — see
  the note under §5 about locally-only files.

***

## 7. Running & deploying

### 7.1 Local — the agent server (:8000)

```bash
uv venv                              # or: python -m venv .venv
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
cp .env.example .env                 # then fill in credentials
python main.py                       # -> http://0.0.0.0:8000
```

Quick probe:

```bash
curl http://127.0.0.1:8000/list-apps
# -> ["assistant","src","webui"]  (whichever app dirs you kept)
```

### 7.2 Local — the Web UI (:8090)

```bash
bash webui/run_local.sh
# -> http://127.0.0.1:8090/
```

`run_local.sh` sets `WEBUI_ENABLE_LOCAL=true`, so the target dropdown offers
**both** the local ADK server and the deployed cloud runtime.

### 7.3 Deploy the agent as a cloud runtime + Feishu bot

```bash
export FEISHU_APP_ID=… FEISHU_APP_SECRET=…
agentkit deploy
```

This step needs an AgentKit deploy manifest (`.agentkit/agentkit.yaml`) and a
`Dockerfile`. Neither is shipped in the public repo — they carry environment-
specific tool ids and gateway details. Recreate them for your own fork via
`agentkit init` (VeADK / AgentKit CLI), then customise:

- keep `plugins.im.feishu` enabled so `agentkit deploy` also wires the Feishu
  proxy without extra flags;
- point `AGENTKIT_TOOL_ID*` at your own sandbox tool.

Redeploying re-uses the same domain, so downstream consumers don't need
re-configuration.

### 7.4 Deploy the Web UI to VeFaaS

```bash
.venv/bin/python webui/deploy_vefaas.py
```

- First run: creates a VeFaaS application named `aw-director-webui` (the
  historical name — the gateway domain has been in production since before
  the repo rename; overridable via `WEBUI_APP_NAME`).
- Subsequent runs: `update_application_code_bundle` uploads a new bundle to
  the existing application (URL stays stable, function envs preserved).
- `.env` is injected as function environment variables — the deployed
  function's env includes `VOLCENGINE_ACCESS_KEY/SECRET_KEY`,
  `AGENTKIT_TOOL_ID*`, `CLOUD_AGENT_*`, so `/api/file` (which needs to sign
  Volcengine RunCode calls) works out of the box.

***

## 8. Testing & CI

The repo ships a **fully offline** unit-test suite (Python standard-library
`unittest` — no pytest, no network, no Volcengine credentials, no sandbox). It
covers the director-assistant capabilities end-to-end at the logic level:

| Area | What is verified |
| ---- | ---------------- |
| Long-script + mixed image/text docs | Incremental draft store: per-draft sequence, stats, ordered image/text interleave in assembled HTML, page breaks, HTML-escaping (injection safety) |
| Poster / scene / storyboard images & key-shot videos | `_files_from_tool_response` turns `image_generate` / `video_generate` / doc results into UI `file` events (image / video / doc / extension-fallback) |
| Image/video consistency pipeline | `image_generate` / `video_generate` auto model-fallback wrapper: only *model-related* errors downgrade; the draft workflow keeps figure order deterministic |
| Mixed PDF / Word long-script generation | `draft_add_section` → `draft_add_image` → `draft_build_document` assembles HTML server-side and delegates to `create_document`; bad formats normalize to pdf |
| History sessions | `/api/config` labels, `/api/file` path-guard + inline/attachment disposition (ASGITransport route tests) |
| Send / Stop rollback & auto-continue | Per-turn output-budget guards, `MAX_TOKENS` → `auto_continue_generation` function-call, stop after max steps, checkpoint store |
| Auto vs. non-auto mode & agent long-run | Budget callbacks, continuation checkpoints, disabled-retrieval-tool stripping, tool registration completeness |
| Secret hygiene | `/api/config` never leaks the cloud key; sandbox reads refuse to hit the network without credentials |

Run it locally:

```bash
# Convenience runner — isolated temp DBs + quiet VeADK logs
uv run python tests/run_all.py
# or the standard discover entrypoint
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: **75 tests, OK**. The same suite runs in GitHub Actions on every push
/ PR to `main` via [`.github/workflows/tests.yml`](.github/workflows/tests.yml)
— it installs `requirements.txt` + `webui/requirements.txt` and runs
`unittest discover` with throwaway SQLite paths, so no secrets are needed.

***

## 9. FAQ

**Q: Do I need to also configure image / video model keys?**
No. The Volcengine AK/SK auto-derives model access. Only override
`MODEL_*_API_KEY` if you want to pin a specific credential.

**Q: I'm getting** **`You've reached the limit on the session number of tool`.**
The AgentKit sandbox tool has a per-tool session quota (usually 2). Every
distinct `UserSessionId` occupies one slot. Use
`agentkit sandbox delete --tool-id $AGENTKIT_TOOL_ID --sid <id> --force`
to free slots, or wait \~30 min for auto-expire.

**Q: How does the UI serve documents that only live inside the sandbox?**
`webui/server.py` emits SSE `file` events with a `/api/file?path=…` URL.
When the browser fetches that URL, `webui/sandbox_files.py` signs a
Volcengine `InvokeTool` (RunCode) request in the same sandbox session
(`movie_script_agent_{user_id}_{session_id}`), base64-reads the file, and
streams it back with the correct `Content-Type` and `Content-Disposition`.

**Q: Where do history sessions live?**
`localStorage["awdir_sessions_v1"]` in the browser. Capped at 20 sessions;
LRU order; oldest auto-evicted on overflow. Clearing the site data resets
them.

***

## 10. License / attribution

Copyright (c) 2026 Alex Wang.

- Author: Alex Wang · <https://github.com/wanglongxiao>
- Contact: <https://www.linkedin.com/in/alexwanglx/>

Open Source Usage: attribution required; preserve the copyright notice in
redistributions. Please keep the header comment intact in redistributed source files.
