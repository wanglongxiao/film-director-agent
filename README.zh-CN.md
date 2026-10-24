# Movie Agent · 电影导演 Agent

简体中文 | [English](README.md)

将故事创意转化为人物侧写、完整大纲、逐章生成的中短篇小说和电影分镜。采用 FastAPI、原生 JavaScript、BytePlus ModelArk 文字模型与 Seedream 图片生成，支持流式输出与 Word 导出。

## Demo 视频

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

远端原有 VeADK 实现保留在 `assistant/`、`webui/`、`src/` 和 `main.py`，相应依赖及离线测试也保留。其独立配置位于 `.env.example` 中 Movie Agent 配置之后。

## 配置

密钥仅放在服务端 `.env`；公开模板 `.env.example` 的密钥字段为空。模型端点 ID 是配置项，不是密钥，需要替换为自己账户可用的端点。

| 配置项 | 示例 |
| --- | --- |
| `ARK_API_KEY` | 私有密钥，禁止提交 |
| `LLM_BASE_URL` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `MAIN_AGENT_MODEL` | `ep-20261024085949-9rwj7` |
| `MAIN_AGENT_MAX_TOKENS` | `300000` |
| `SCRIPT_DEEPSEEK_1017_MODEL` | `ep-20261024085949-9rwj7` |
| `SCRIPT_DEEPSEEK_1017_MAX_TOKENS` | `200000` |
| `SCRIPT_SEED_SC_0215_MODEL` | `ep-20260731212724-gglbc` |
| `SCRIPT_SEED_SC_0215_MAX_TOKENS` | `32000` |
| `LLM_MODEL_IMAGE` | `ep-20261003165202-jlrtk` |
| `IMAGE_SIZE` | `2048x1536`（4:3） |

主 Agent 负责讨论、背景、人物侧写、大纲和信息补全；所选剧本模型负责章节规划、正文、连续性摘要和分镜。网页通过 `/api/models` 自动读取模型名称及配置上限。实际输出能力、请求上限和内容限制以模型服务商为准。

## 写作与导出

1. 在创作讨论中完成角色侧写和故事大纲。
2. 设置章节数及每章目标篇幅，默认 12 章、每章 2,500 字；英文按单词计数。
3. 生成完整正文，各章参考已完成章节的事实摘要与上一章结尾，保持叙事连贯。
4. 可停止后继续；使用同一章节规划和篇幅设置。章节达到目标篇幅至少 80% 且未被截断后才保存。
5. 刷新或关闭前导出 Word；未完成作品标注“未完成稿”。

刷新、关闭或切换语言会新建交互任务。完成章节及图片保存在 `data/script.db`；知道原任务 ID 时，可通过 `/api/sessions/{id}/export/word` 导出归档。私人运行数据不提交到 Git。

## 提交前密钥检查

安装 [Gitleaks](https://github.com/gitleaks/gitleaks)（macOS 可用 `brew install gitleaks`），启用仓库提交钩子：

```bash
git config core.hooksPath .githooks
gitleaks git --redact --log-opts="--all" .
git diff --cached --name-only
```

提交钩子检查暂存区、拒绝私有配置和运行文件，并在未安装 Gitleaks 时阻止提交。CI 扫描完整 Git 历史。`.gitignore` 排除环境文件、私钥文件、日志、缓存、编辑器配置和 SQLite 数据，只公开 `.env.example`。

这些检查降低误泄露风险，无法保证识别所有形式的凭据。已分享或公开的密钥应撤销并重新签发。
