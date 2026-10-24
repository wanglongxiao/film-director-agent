# Movie Agent · 电影导演 Agent

简体中文 | [English](README.md)

将故事创意转化为人物侧写、完整大纲、逐章生成的中短篇小说和电影分镜。采用 FastAPI、原生 JavaScript、BytePlus ModelArk 文字模型与 Seedream 图片生成，支持流式输出与 Word 导出。

## Demo

[打开 Demo Site](https://sh0o6o11ievepvnqcjrvg.apigateway-ap-southeast-1.apigw-byteplus.com/)

云端演示需要准入密码。

[观看 movieagent-demo.mp4](https://github.com/wanglongxiao/film-director-agent/blob/main/movieagent-demo.mp4)

视频展示早期版本；当前应用已增加完整小说正文、模型选择和 Word 导出。

## 功能

- 讨论背景、角色、大纲、剧本形式、风格与年龄分级。
- 主 Agent 与剧本模型独立配置；网页可选 `deepseek-1017`（默认）和 `seed-sc-0215`。
- 规划 3–40 章，逐章流式生成；完成章节自动保存，支持停止与继续生成。
- 导出 Word：剧本题目、章节索引、小说正文、附录（背景设定、人物侧写及对应角色图片）。
- 生成 4:3 角色定妆图与场景参考图，最大并发 10，支持临时错误重试。
- 支持简体中文、繁体中文、英文、日文和韩文。
- 每个浏览器窗口独立任务，完成内容保存在本地 SQLite。

## 本地启动

安装 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Node.js 18+。

```bash
git clone https://github.com/wanglongxiao/film-director-agent.git
cd film-director-agent
cp .env.example .env
# 在 .env 中填写 ARK_API_KEY 及模型端点。
npm ci
uv run --with-requirements requirements.txt uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000。修改 `.env` 后重启后端；必要时使用 `Cmd+Shift+R` 刷新页面。

## 配置

密钥和模型端点仅保留在服务端；公开模板 `.env.example` 的对应字段为空，需要填写自己账户可用的密钥和端点。

| 配置项 | 示例 |
| --- | --- |
| `ARK_API_KEY` | 私有密钥，禁止提交 |
| `LLM_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `MAIN_AGENT_MODEL` | 自己账户的主 Agent 端点 |
| `MAIN_AGENT_MAX_TOKENS` | `300000` |
| `SCRIPT_DEEPSEEK_1017_MODEL` | 自己账户的 DeepSeek 端点 |
| `SCRIPT_DEEPSEEK_1017_MAX_TOKENS` | `200000` |
| `SCRIPT_SEED_SC_0215_MODEL` | 自己账户的 Seed 端点 |
| `SCRIPT_SEED_SC_0215_MAX_TOKENS` | `32000` |
| `LLM_MODEL_IMAGE` | 自己账户的 Seedream 端点 |
| `IMAGE_SIZE` | `2048x1536`（4:3） |

主 Agent 负责讨论、背景、人物侧写、大纲和信息补全；所选剧本模型负责章节规划、正文、连续性摘要和分镜。网页通过 `/api/models` 自动读取模型名称及配置上限。实际输出能力、请求上限和内容限制以模型服务商为准。

## BytePlus veFaaS 部署

函数使用 Python 3.12，启动命令为 `bash run_cloud.sh`；Linux Python 依赖放在 `vendor/`，Word 导出所需的 Linux Node.js 放在 `runtime/bin/`。通过服务端环境变量注入模型参数、`ARK_API_KEY`、`WEBUI_CLOUD_MODE=true`、`WEBUI_ACCESS_PASSWORD` 及随机生成的 `WEBUI_SESSION_SECRET`。部署包不包含 `.env`、云端 AK/SK 和本地数据库。

`MinInstance` 和 `MaxInstance` 均设为 `1`。API 网关路由匹配 `/` 前缀并允许应用使用的 HTTP 方法。长文本生成使用函数超时 900 秒、API 网关路由超时 900,000 毫秒。

云端页面、静态资源和 API 均需登录，本地模式不需要密码。`/api/models` 只返回模型名称及 Token 上限。云端 SQLite 默认路径为 `/tmp/movieagent/script.db`，实例重建时数据会丢失；重建前请导出作品，或挂载可写持久化存储并通过 `SCRIPT_DB_PATH` 指定路径。

## 写作与导出

1. 在创作讨论中完成角色侧写和故事大纲。
2. 设置章节数及每章目标篇幅，默认 12 章、每章 2,500 字；英文按单词计数。
3. 生成完整正文，各章参考已完成章节的事实摘要与上一章结尾，保持叙事连贯。
4. 可停止后继续；使用同一章节规划和篇幅设置。章节达到目标篇幅至少 80% 且未被截断后才保存。
5. 刷新或关闭前导出 Word；未完成作品标注“未完成稿”。

刷新、关闭或切换语言会新建交互任务。完成章节及图片保存在 `data/script.db`；知道原任务 ID 时，可通过 `/api/sessions/{id}/export/word` 导出归档。私人运行数据不提交到 Git。

## 项目目录与本地数据

`app/main.py` 是 FastAPI 入口，`app/static/` 是五语言页面。`config.py` 读取 `.env`，`app/persist.py` 读写实际使用的 `data/script.db`。数据库保存任务设定、完成正文、图片 URL 和角色图片缓存，属于有效归档，不是临时文件，应保留。数据库连接按操作打开和关闭，因此不一定持续出现在服务进程的打开文件列表中。

`package.json` 和 `package-lock.json` 提供 Word 导出依赖；`movieagent-demo.mp4` 是演示视频。`.githooks/`、`.gitleaks.toml` 和 `.github/workflows/secrets.yml` 用于提交保护。本地 `.env`、`data/`、`node_modules/` 和编辑器设置不提交。与当前项目无关的旧远端实现已删除。

检查运行中的服务：

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/models
```

## 提交前密钥检查

安装 [Gitleaks](https://github.com/gitleaks/gitleaks)（macOS 可用 `brew install gitleaks`），启用仓库提交钩子：

```bash
git config core.hooksPath .githooks
gitleaks git --redact --log-opts="--all" .
git diff --cached --name-only
```

提交钩子检查暂存区、拒绝私有配置和运行文件，并与本地 `.env` 中的密钥进行精确比对，且不输出密钥；未安装 Gitleaks 时阻止提交。Gitleaks 检测常见凭据及 ModelArk 密钥格式，CI 扫描完整 Git 历史。`.gitignore` 排除环境文件、私钥文件、日志、缓存、编辑器配置和 SQLite 数据，只公开 `.env.example`。

这些检查降低误泄露风险，无法保证识别所有形式的凭据。已分享或公开的密钥应撤销并重新签发。
