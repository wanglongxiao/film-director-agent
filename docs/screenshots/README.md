# Screenshots

Drop your captures here with the exact filenames referenced from
[../../README.md](../../README.md) and [../../README.zh-CN.md](../../README.zh-CN.md):

| # | Filename | What to capture |
|---|---|---|
| 1 | `01-overview.png` | Full Web UI: left history sidebar + chat area + composer, with 2–3 sessions listed. |
| 2 | `02-streaming.png` | An in-flight assistant reply — thinking pane open, at least one tool-call chip visible. |
| 3 | `03-image.png` | An assistant message with an inline generated image (from `image_generate`). |
| 4 | `04-video.png` | An assistant message with an inline HTML5 video player (from `video_generate`). |
| 5 | `05-pdf.png` | A PDF attachment card with 预览/下载 buttons, iframe preview expanded. |
| 6 | `06-history.png` | Left sidebar showing multiple past sessions, hover state exposing the × delete button. |

Suggested capture flow (local run):

```bash
bash webui/run_local.sh
# then open http://127.0.0.1:8090/ and drive the flows above.
```

PNG is preferred; keep width around 1400–1600px for readable inline rendering
on GitHub.
