# Movie Agent · Film Director Agent

[简体中文](README.zh-CN.md) | English

A streaming writing app that turns a story idea into character profiles, a complete outline, a chapter-by-chapter novella, and film storyboards. It uses FastAPI, plain JavaScript, BytePlus ModelArk text models, and Seedream images.

## Demo

[Watch movieagent-demo.mp4](https://github.com/wanglongxiao/film-director-agent/blob/main/movieagent-demo.mp4)

The video shows an earlier version; the current app also supports full manuscripts, model selection, and Word export.

## Features

- Discuss the background, characters, outline, film format, style, and age rating.
- Choose `deepseek-1017` (default) or `seed-sc-0215` for writing, independently of the main agent.
- Plan 3–40 chapters and stream each chapter. Completed chapters are saved; stop and continue from the next unfinished chapter.
- Export Word with the title, chapter index, full prose, and an appendix with background, character profiles, and each character's portrait.
- Generate 4:3 character and scene reference images, with up to 10 concurrent requests and retries for transient failures.
- Use Simplified Chinese, Traditional Chinese, English, Japanese, or Korean.
- Keep browser tasks separate, with completed work archived in local SQLite.

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

Keys stay in `.env` on the server. `.env.example` contains empty key fields. Endpoint IDs are configuration, not credentials; replace them with endpoints available in your own account.

| Setting | Example |
| --- | --- |
| `ARK_API_KEY` | Your private key; never commit it |
| `LLM_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `MAIN_AGENT_MODEL` | `ep-20261024085949-9rwj7` |
| `MAIN_AGENT_MAX_TOKENS` | `300000` |
| `SCRIPT_DEEPSEEK_1017_MODEL` | `ep-20261024085949-9rwj7` |
| `SCRIPT_DEEPSEEK_1017_MAX_TOKENS` | `200000` |
| `SCRIPT_SEED_SC_0215_MODEL` | `ep-20260731212724-gglbc` |
| `SCRIPT_SEED_SC_0215_MAX_TOKENS` | `32000` |
| `LLM_MODEL_IMAGE` | `ep-20261003165202-jlrtk` |
| `IMAGE_SIZE` | `2048x1536` (4:3) |

The main agent handles discussion and story setup. The selected writer handles chapter plans, prose, summaries, and storyboards. `/api/models` supplies the web model list and configured output budgets. Actual output limits and available content depend on the model provider.

## Writing and export

1. Complete character profiles and the outline in the discussion panel.
2. Set the chapter count and target length: default 12 chapters × 2,500 words in English, or characters in the other languages.
3. Generate the full manuscript. Each chapter uses prior chapter facts and the previous chapter's ending for continuity.
4. Stop when needed, then continue with the same chapter plan and length. A chapter is saved only after reaching at least 80% of its target length without truncation.
5. Export Word before refreshing or closing the browser. An incomplete book is labeled as an incomplete draft.

Refreshing, closing, or changing language creates a new interactive task. Completed chapters and images remain in `data/script.db`; an archived task can be exported through `/api/sessions/{id}/export/word` when its ID is known. Private runtime data is excluded from Git.

## Before committing

Install [Gitleaks](https://github.com/gitleaks/gitleaks) (`brew install gitleaks` on macOS) and enable the included hook:

```bash
git config core.hooksPath .githooks
gitleaks git --redact --log-opts="--all" .
git diff --cached --name-only
```

The pre-commit hook checks staged files, rejects private configuration and runtime files, and fails if Gitleaks is unavailable. CI also scans the full Git history. `.gitignore` excludes environment files, private key files, logs, caches, editor settings, and SQLite data. Only `.env.example` is public.

These checks reduce the risk of accidental exposure; they cannot guarantee detection of every possible credential. If a key has already been shared or published, revoke it and issue a new one.
