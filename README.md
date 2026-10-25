# Movie Agent · Film Director Agent

[简体中文](README.zh-CN.md) | English

A streaming writing app that turns a story idea into character profiles, a complete outline, a chapter-by-chapter novella, and film storyboards. It uses FastAPI, plain JavaScript, BytePlus ModelArk text models, and Seedream images.

## Demo

[Open Demo Site](https://sh0o6o11ievepvnqcjrvg.apigateway-ap-southeast-1.apigw-byteplus.com/)

The cloud demo requires an access password.

[Watch movieagent-demo.mp4](https://github.com/wanglongxiao/film-director-agent/blob/main/movieagent-demo.mp4)

The video shows an earlier version; the current app also supports full manuscripts, model selection, and Word export.

## Features

- Discuss the background, characters, outline, film format, style, and age rating.
- Choose `deepseek-1017` (default) or `seed-sc-0215` for writing, independently of the main agent.
- Plan 10–120 chapters, then automatically write one chapter per HTTP request. Each chapter is saved before the browser requests the next.
- Export Word with the title, chapter index, full prose, and an appendix with background, character profiles, and each character's portrait.
- Generate 4:3 character and scene reference images, with up to 10 concurrent requests and retries for transient failures.
- Use Simplified Chinese, Traditional Chinese, English, Japanese, or Korean.
- Record speech in the input bar and convert it to editable text with Seed-Speech. Recording requires microphone permission and HTTPS (localhost also works), and stops after 120 seconds. Text is inserted without a success notice and is not sent automatically.
- On mobile, the input bar stays at the bottom of the visible screen while messages scroll inside the page. Portrait and landscape modes hide the reference-image panel.
- Restore discussions, completed chapters and images from script history after refresh or reopening. Desktop history and references share the right panel equally; mobile uses a history drawer.
- Isolate history with a signed browser cookie. Cloud tasks and image files persist in private TOS; local development uses SQLite.

## Run locally

Install Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 18+.

```bash
git clone https://github.com/wanglongxiao/film-director-agent.git
cd film-director-agent
cp .env.example .env
# Fill in ARK_API_KEY and model endpoints in .env.
npm ci
uv run --with-requirements requirements.txt uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Restart the backend after changing `.env`.

## Configuration

Keys and endpoint IDs stay on the server. `.env.example` leaves these fields empty; fill them with values from your own account.

| Setting | Example |
| --- | --- |
| `ARK_API_KEY` | Your private key; never commit it |
| `LLM_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `MAIN_AGENT_MODEL` | Your main agent endpoint |
| `MAIN_AGENT_MAX_TOKENS` | `300000` |
| `SCRIPT_DEEPSEEK_1017_MODEL` | Your DeepSeek endpoint |
| `SCRIPT_DEEPSEEK_1017_MAX_TOKENS` | `200000` |
| `SCRIPT_SEED_SC_0215_MODEL` | Your Seed endpoint |
| `SCRIPT_SEED_SC_0215_MAX_TOKENS` | `32000` |
| `LLM_MODEL_IMAGE` | Your Seedream endpoint |
| `IMAGE_SIZE` | `2048x1536` (4:3) |
| `SCRIPT_LLM_TEMPERATURE` | `0.9` |
| `SPEECH_API_KEY` | Private Seed-Speech API key |
| `SPEECH_APPID` | Your speech application ID |
| `SPEECH_ASR_URL` | Separate Seed-Speech API domain |
| `SPEECH_RESOURCE_ID` | `volc.seedasr.auc_turbo` |
| `BYTEPLUS_AK` / `BYTEPLUS_SK` | Private server credentials with access to the TOS task prefix |
| `TOS_REGION` | `ap-southeast-1` |
| `TOS_BUCKET` | Your private bucket |
| `TOS_ENDPOINT` | `https://tos-ap-southeast-1.bytepluses.com` |
| `TASK_STORAGE` | Local: `sqlite` (default) or `tos`; cloud always uses TOS |

The main agent handles discussion and story setup. The selected writer handles chapter plans, prose, summaries, and storyboards. `SCRIPT_LLM_TEMPERATURE` defaults to `0.9` for discussion and writing; continuity summaries use `0.2`. `/api/models` supplies model names, output budgets, generation limits and defaults, and speech availability, without private endpoints or keys. Actual output limits and available content depend on the model provider.

## BytePlus veFaaS

Use `run_cloud.sh` as the function command (`bash run_cloud.sh`), with Python 3.12, Linux dependencies in `vendor/`, and Linux Node.js in `runtime/bin/` for Word export. Inject model and speech settings, `ARK_API_KEY`, `WEBUI_CLOUD_MODE=true`, `WEBUI_ACCESS_PASSWORD`, a stable random `WEBUI_SESSION_SECRET`, and the TOS settings and server credentials above through server environment variables. Keep `.env`, credentials and local databases out of the deployment archive and Git. Seed-Speech uses its own API key; AK/SK are used server-side for TOS.

Set both `MinInstance` and `MaxInstance` to `1`. Bind an API gateway route with path prefix `/` and all app HTTP methods. For long generation requests, use a function timeout of 900 seconds and an API gateway route timeout of 900,000 milliseconds.

Cloud pages, static resources, and APIs require login; local mode has no password. TOS stores task JSON and original images below `movieagent/v1/tasks/{browser}/{task}/`, with a small per-task history summary under `movieagent/v1/history/{browser}/`. Bucket access stays private; the backend checks the signed browser identity before every task, image or export operation. Task writes use ETag conditions and a persisted request lease to reject concurrent edits. There is no shared mutable user index. Keep the session secret unchanged across deployments so existing browser cookies remain valid.

## Writing and export

1. First set 10–120 chapters (default 20) and 2,000–10,000 words per chapter in English, or characters in the other languages (default 4,000). These limits and defaults are defined in `config.GENERATION_SETTINGS` and loaded by the web UI.
2. Complete character profiles and the outline in the discussion panel. Reference images allow 1–10 per request (default 4) on desktop.
3. Generate the full manuscript. Planning has its own request; each following request writes one chapter using prior chapter facts and the previous chapter's ending. The browser automatically continues after saving.
4. Stop when needed, then continue with the same chapter plan and length. A chapter is saved only after reaching at least 80% of its target length without truncation.
5. Refresh or reopen to restore the active task, or select it from history. Export Word at any time after the first saved chapter. An incomplete book is labeled as an incomplete draft.

Both discussion and prose use the chapter count and length selected on the page. Chapter count is exact; chapter length is an approximate target, with at least 80% required before saving. Discussion saves a structured map containing exactly the selected number of chapters. Prose follows the discussion's background, characters, outline and chapter map while allowing compatible creative details. Changing the page settings before prose starts replaces the discussion map on the next request. Reference-image controls are hidden on mobile devices in both orientations.

Refresh and close preserve tasks. Switching language or choosing New Task creates another task while retaining history. Each chapter request has a bounded generation window below the gateway's 900-second limit; heartbeat cannot extend that limit. If a request disconnects, the browser checks durable progress before retrying. Only complete chapters are retained; an interrupted chapter may be regenerated. Closing the page stops subsequent browser requests; reopening automatically continues an active book. After an instance disappears, recovery may wait up to 14 minutes for its request lease to expire. Clearing browser cookies or using another browser gives a separate history. Explicit deletion removes the task and its images.

## Project files and local data

`app/main.py` is the FastAPI entry point; `app/static/` holds the five-language UI. `config.py` loads `.env`. `app/storage.py` provides conditional object writes through private TOS in cloud mode or the local `data/script.db` SQLite database; `app/store.py` manages runtime requests and recovery, and `app/persist.py` saves images and task state. Existing local archive tables are preserved; new browser-scoped tasks use the `task_objects` table. Keep the database to retain local history.

`package.json` and `package-lock.json` provide Word export dependencies. `movieagent-demo.mp4` is the demo. `.githooks/`, `.gitleaks.toml`, and `.github/workflows/secrets.yml` protect commits. Local `.env`, `data/`, `node_modules/`, and editor settings stay out of Git. The unrelated earlier remote implementation has been removed.

To check the running server:

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/models
```

## Before committing

Install [Gitleaks](https://github.com/gitleaks/gitleaks) (`brew install gitleaks` on macOS) and enable the included hook:

```bash
git config core.hooksPath .githooks
gitleaks git --redact --log-opts="--all" .
git diff --cached --name-only
```

The pre-commit hook checks staged files, rejects private configuration and runtime files, compares staged content with keys in local `.env` files without printing them, and fails if Gitleaks is unavailable. Gitleaks detects common credentials and the ModelArk key format. CI also scans the full Git history. `.gitignore` excludes environment files, private key files, logs, caches, editor settings, and SQLite data. Only `.env.example` is public.

These checks reduce the risk of accidental exposure; they cannot guarantee detection of every possible credential. If a key has already been shared or published, revoke it and issue a new one.
