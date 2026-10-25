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
- 规划 10–120 章，每次 HTTP 请求生成一章，保存成功后自动请求下一章，无需逐章手动操作。
- 导出 Word：剧本题目、章节索引、小说正文、附录（背景设定、人物侧写及对应角色图片）。
- 生成 4:3 角色定妆图与场景参考图，最大并发 10，支持临时错误重试。
- 支持简体中文、繁体中文、英文、日文和韩文。
- 底部输入栏支持录音，通过 Seed-Speech 转为可编辑文字；识别成功后不显示额外提示，不自动发送。需允许麦克风权限并使用 HTTPS（localhost 也可），单次录音最长 120 秒。
- 移动端输入栏保持在可见屏幕底部，消息区内部滚动；竖屏和横屏均隐藏参考图模块。
- 刷新或重新打开可恢复讨论、已完成章节和图片；桌面右栏历史剧本与参考图各占一半，移动端使用历史抽屉。
- 签名浏览器 Cookie 隔离历史任务；本地与云端任务、图片统一持久保存在私有 TOS。

## 本地启动

安装 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Node.js 18+。

```bash
git clone https://github.com/wanglongxiao/film-director-agent.git
cd film-director-agent
cp .env.example .env
# 在 .env 中填写模型参数与私有 TOS 凭据。
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
| `SCRIPT_LLM_TEMPERATURE` | `0.9` |
| `SPEECH_API_KEY` | Seed-Speech 私有 API Key |
| `SPEECH_APPID` | 自己账户的语音应用 ID |
| `SPEECH_ASR_URL` | 独立的 Seed-Speech API 域名 |
| `SPEECH_RESOURCE_ID` | `volc.seedasr.auc_turbo` |
| `BYTEPLUS_AK` / `BYTEPLUS_SK` | 具有 TOS 任务前缀权限的服务端私有凭据 |
| `TOS_REGION` | `ap-southeast-1` |
| `TOS_BUCKET` | 自己的私有桶 |
| `TOS_ENDPOINT` | `https://tos-ap-southeast-1.bytepluses.com` |

主 Agent 负责讨论、背景、人物侧写、大纲和信息补全；所选剧本模型负责章节规划、正文、连续性摘要和分镜。`SCRIPT_LLM_TEMPERATURE` 默认 `0.9`，用于讨论与创作，连续性摘要使用 `0.2`。网页通过 `/api/models` 自动读取模型名称、输出上限、篇幅范围及默认值、语音功能可用状态，不返回私有端点和密钥。实际输出能力、请求上限和内容限制以模型服务商为准。

## BytePlus veFaaS 部署

函数使用 Python 3.12，启动命令为 `bash run_cloud.sh`；Linux Python 依赖放在 `vendor/`，Word 导出所需的 Linux Node.js 放在 `runtime/bin/`。通过服务端环境变量注入模型和语音参数、`ARK_API_KEY`、`WEBUI_CLOUD_MODE=true`、`WEBUI_ACCESS_PASSWORD`、保持稳定的随机 `WEBUI_SESSION_SECRET`，以及上述 TOS 配置和服务端 AK/SK。部署压缩包及 Git 不包含 `.env`、凭据或本地数据库。Seed-Speech 使用独立 API Key，AK/SK 仅在服务端用于访问 TOS。

`MinInstance` 和 `MaxInstance` 均设为 `1`。API 网关路由匹配 `/` 前缀并允许应用使用的 HTTP 方法。长文本生成使用函数超时 900 秒、API 网关路由超时 900,000 毫秒。

云端页面、静态资源和 API 均需登录，本地模式不需要密码。TOS 的 `movieagent/v1/tasks/{浏览器}/{任务}/` 保存任务 JSON 和原始图片，`movieagent/v1/history/{浏览器}/` 保存每项任务的简要索引。桶保持私有；每次任务、图片和导出操作都验证签名浏览器身份。任务写入使用 ETag 条件校验及持久化请求占用标记，拒绝并发修改，不使用所有用户共用的可变索引。部署时保持会话签名密钥不变，已有浏览器身份才能继续有效。

## 写作与导出

1. 先设置 10–120 章（默认 20 章），每章 2,000–10,000 字（默认 4,000 字）；英文按单词计数。范围与默认值统一定义在 `config.GENERATION_SETTINGS`，网页自动读取。
2. 在创作讨论中完成角色侧写和故事大纲。桌面端参考图每次 1–10 张，默认 4 张。
3. 生成完整正文：直接将讨论中确认的章节计划保存为正文目录，立即展示，不再重复调用模型规划；仅缺少计划时单独规划。随后每个请求只写一章，保存成功后浏览器自动继续。模型思考期间也每 10 秒返回运行心跳，避免连接长期无数据，但不延长网关绝对超时。失败会记录日志并显示任务状态。各章参考已完成章节的事实摘要与上一章结尾，保持叙事连贯。
4. 可停止后继续；使用同一章节规划和篇幅设置。章节达到目标篇幅至少 80% 且未被截断后才保存。
5. 刷新或重新打开恢复当前任务，也可从历史剧本中选择。保存第一章后即可导出 Word；未完成作品标注“未完成稿”。

创作讨论与小说正文均使用网页中的章数和每章字数。章数严格遵守，字数为近似目标，至少达到 80% 才保存。讨论会保存包含指定章数的结构化章节计划；正文以讨论中的背景、人物、大纲和章节计划为主要要求，允许兼容这些设定的细节创意发挥。正文开始前修改篇幅时，下次请求会重新生成讨论章节计划。移动设备竖屏和横屏均隐藏参考图模块。

刷新和关闭保留任务；切换语言或点击“新任务”会创建另一个任务，原任务仍在历史中。每章请求设置低于网关 900 秒上限的生成时间窗口，心跳不能延长网关上限。连接中断后，浏览器先查询已保存进度，再决定是否重试。只保存完整章节，中断章节可能重新生成。关闭页面后不会请求后续章节，重新打开后自动继续尚在生成中的作品。实例消失后，可能需等待最长 14 分钟的请求占用期结束。清除浏览器 Cookie 或换浏览器会获得独立历史；逐条删除会移除该任务和全部图片。

## 项目目录与本地数据

`app/main.py` 是 FastAPI 入口，`app/static/` 是五语言页面，`config.py` 读取 `.env`。`app/storage.py` 在本地和云端统一使用私有 TOS，提供带版本校验的对象写入；`app/store.py` 管理请求运行和恢复，`app/persist.py` 保存图片与任务状态。本地启动也需要配置 TOS 凭据；旧数据库归档不再读写。

`package.json` 和 `package-lock.json` 提供 Word 导出依赖；`movieagent-demo.mp4` 是演示视频。提交钩子和忽略规则属于本地工具，不通过 GitHub 分发。本地 `.env`、旧归档数据、`node_modules/` 和编辑器设置不提交。

检查运行中的服务：

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/models
```

## 提交前密钥检查

安装 [Gitleaks](https://github.com/gitleaks/gitleaks)（macOS 可用 `brew install gitleaks`），提交前扫描：

```bash
gitleaks git --redact --log-opts="--all" .
git diff --cached --name-only
```

只公开 `.env.example`。环境文件、私钥、日志、缓存、编辑器配置和旧归档数据不应提交。克隆后自行配置本地忽略规则和提交钩子；仓库不分发这些文件及 CI 工作流。

这些检查降低误泄露风险，无法保证识别所有形式的凭据。已分享或公开的密钥应撤销并重新签发。
