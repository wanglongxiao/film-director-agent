# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""aw-director-agent Web UI —— BFF（Backend For Frontend）后端。

职责：
- 对浏览器只暴露同源接口（/api/*），把「Agent 调用域名 + apikey」保管在服务端，
  绝不下发到前端，规避密钥泄露。
- 统一代理「本地 ADK（:8000，无鉴权，app=assistant）」与「云端 AgentKit Runtime
  （固定域名 + Bearer apikey，app=movie_script_agent）」两个目标；前端只需选择
  target=local|cloud，其余（app 名解析、会话创建、SSE 转发）由本层完成。
- 以 SSE 流式把 Agent 的增量输出透传给前端，天然支持流式对话。

此外还支持「Agent 生成的文件」在 UI 中直接查看 / 下载 / 播放：
- 图片、视频工具返回的是公网 URL（TOS/方舟，24h 有效），前端可直接 <img>/<video>；
- create_document 生成的 docx/pdf/pptx/html 只返回沙箱内路径，本层通过 /api/file
  从 AgentKit sandbox 把文件读回并以正确 Content-Type 回传（PDF/HTML 内联预览，
  docx/pptx 走下载）。
本层解析 SSE 里的 functionResponse，抽出文件引用，作为 `file` 事件推给前端渲染。

环境变量（部署到 VeFaaS 时通过服务端环境注入，不写死密钥）：
- CLOUD_AGENT_BASE_URL  云端 Agent 调用域名（默认取用户给定域名）
- CLOUD_AGENT_API_KEY   云端 Agent 的 apikey（Bearer；务必用密钥/环境变量注入）
- CLOUD_AGENT_APP_NAME  云端 ADK app 名（默认 movie_script_agent；留空则自动探测）
- LOCAL_AGENT_BASE_URL  本地 ADK 地址（默认 http://127.0.0.1:8000）
- LOCAL_AGENT_APP_NAME  本地 ADK app 名（默认 assistant；留空则自动探测）
- WEBUI_ENABLE_LOCAL    是否在前端暴露「本地」目标（默认 true；云端部署可设 false）
- SANDBOX_AGENT_NAME    沙箱会话派生用的 agent.name（默认 movie_script_agent，本地/云端一致）
- VOLCENGINE_ACCESS_KEY / VOLCENGINE_SECRET_KEY / AGENTKIT_TOOL_ID(_SCRIPT)
                        读沙箱文档所需（由 .env 注入函数环境变量）
"""

from __future__ import annotations

import json
import os
from typing import Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import sandbox_files

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_HERE, "static")

# 沙箱会话派生用的 agent.name（document_tools 用 ic.agent.name 派生，本地/云端都是它）
SANDBOX_AGENT_NAME = os.getenv("SANDBOX_AGENT_NAME", "movie_script_agent").strip()

# 文件识别用的常量与 MIME 映射
_DOC_DIR = "/home/gem/veadk_docs"
_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")
_VID_EXT = (".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv")
_DOC_MIME = {
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
# PDF/HTML 可在浏览器内联预览，其余走下载
_INLINE_FMTS = {"pdf", "html"}

# --- 目标 Agent 配置 --------------------------------------------------------
_DEFAULT_CLOUD_BASE = "https://so8ldqr2sttae5hejrvrv.apigateway-cn-beijing.volceapi.com"


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


CLOUD_BASE_URL = os.getenv("CLOUD_AGENT_BASE_URL", _DEFAULT_CLOUD_BASE).rstrip("/")
CLOUD_API_KEY = os.getenv("CLOUD_AGENT_API_KEY", "").strip()
CLOUD_APP_NAME = os.getenv("CLOUD_AGENT_APP_NAME", "movie_script_agent").strip()
LOCAL_BASE_URL = os.getenv("LOCAL_AGENT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
LOCAL_APP_NAME = os.getenv("LOCAL_AGENT_APP_NAME", "assistant").strip()
ENABLE_LOCAL = _bool_env("WEBUI_ENABLE_LOCAL", True)

# app 名探测结果缓存，避免每次请求都打 /list-apps
_APP_NAME_CACHE: dict[str, str] = {}


def _target_conf(target: str) -> dict:
    if target == "cloud":
        return {
            "base_url": CLOUD_BASE_URL,
            "api_key": CLOUD_API_KEY,
            "app_name": CLOUD_APP_NAME,
        }
    if target == "local":
        return {"base_url": LOCAL_BASE_URL, "api_key": "", "app_name": LOCAL_APP_NAME}
    raise HTTPException(status_code=400, detail=f"unknown target: {target}")


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


app = FastAPI(title="aw-director-agent Web UI (BFF)")


async def _resolve_app_name(client: httpx.AsyncClient, conf: dict) -> str:
    """优先用配置的 app 名；为空时探测 /list-apps 取第一个。"""
    if conf["app_name"]:
        return conf["app_name"]
    cache_key = conf["base_url"]
    if cache_key in _APP_NAME_CACHE:
        return _APP_NAME_CACHE[cache_key]
    r = await client.get(
        f"{conf['base_url']}/list-apps", headers=_auth_headers(conf["api_key"])
    )
    r.raise_for_status()
    apps = r.json()
    if not apps:
        raise HTTPException(status_code=502, detail="target has no apps")
    _APP_NAME_CACHE[cache_key] = apps[0]
    return apps[0]


@app.get("/api/config")
async def api_config():
    """告诉前端有哪些可用目标（不含任何密钥）。"""
    targets = []
    if ENABLE_LOCAL:
        targets.append({"id": "local", "label": "本地 Agent"})
    if CLOUD_API_KEY:
        targets.append({"id": "cloud", "label": "云端 Agent"})
    default = "cloud" if any(t["id"] == "cloud" for t in targets) else (
        targets[0]["id"] if targets else None
    )
    return {"targets": targets, "default": default}


@app.get("/api/health")
async def api_health(target: str = "cloud"):
    """探测某目标是否可达（返回其 app 列表）。"""
    conf = _target_conf(target)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{conf['base_url']}/list-apps",
                headers=_auth_headers(conf["api_key"]),
            )
            r.raise_for_status()
            return {"ok": True, "target": target, "apps": r.json()}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"ok": False, "target": target, "error": repr(e)}
        )


async def _ensure_session(
    client: httpx.AsyncClient, conf: dict, app_name: str, user_id: str, session_id: str
) -> None:
    """幂等创建会话：已存在则忽略错误。"""
    url = f"{conf['base_url']}/apps/{app_name}/users/{user_id}/sessions/{session_id}"
    try:
        await client.post(url, headers=_auth_headers(conf["api_key"]), json={})
    except Exception:  # noqa: BLE001
        pass


@app.post("/api/chat")
async def api_chat(request: Request):
    """把前端消息转成 ADK /run_sse 调用，并以 SSE 流式回传增量文本。"""
    body = await request.json()
    target = body.get("target") or "cloud"
    message = (body.get("message") or "").strip()
    user_id = body.get("user_id") or "webui-user"
    session_id = body.get("session_id") or "webui-default"
    if not message:
        raise HTTPException(status_code=400, detail="empty message")

    conf = _target_conf(target)
    if target == "cloud" and not conf["api_key"]:
        raise HTTPException(status_code=400, detail="cloud apikey not configured on server")

    async def event_stream():
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                app_name = await _resolve_app_name(client, conf)
            except Exception as e:  # noqa: BLE001
                yield _sse({"type": "error", "error": f"resolve app failed: {e!r}"})
                return

            await _ensure_session(client, conf, app_name, user_id, session_id)

            payload = {
                "app_name": app_name,
                "user_id": user_id,
                "session_id": session_id,
                "new_message": {"role": "user", "parts": [{"text": message}]},
                "streaming": True,
            }
            headers = {"Content-Type": "application/json", **_auth_headers(conf["api_key"])}
            try:
                async with client.stream(
                    "POST", f"{conf['base_url']}/run_sse", json=payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        detail = (await resp.aread()).decode("utf-8", "ignore")[:500]
                        yield _sse({"type": "error", "error": f"HTTP {resp.status_code}: {detail}"})
                        return
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[len("data:"):].strip()
                        if not raw:
                            continue
                        try:
                            ev = json.loads(raw)
                        except Exception:  # noqa: BLE001
                            continue
                        for chunk in _extract_chunks(ev, user_id, session_id):
                            yield _sse(chunk)
                yield _sse({"type": "done"})
            except Exception as e:  # noqa: BLE001
                yield _sse({"type": "error", "error": repr(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _files_from_tool_response(name: str, resp: dict, user_id: str, session_id: str):
    """从工具返回体里抽取「可在 UI 展示/下载/播放的文件引用」。

    产出的 file 事件字段：
      kind: image|video|doc     媒体类别（决定前端用 <img>/<video>/预览+下载）
      url:  直链（图片/视频公网 URL，或指向本层 /api/file 的文档链接）
      name: 文件名
      fmt:  文档格式（doc 才有：pdf/docx/pptx/html）
    """
    if not isinstance(resp, dict):
        return

    # 1) 图片：image_generate → {"status":"success","success_list":[{name:url}, ...]}
    if name == "image_generate" or "success_list" in resp:
        for item in resp.get("success_list") or []:
            if isinstance(item, dict):
                for fname, url in item.items():
                    if isinstance(url, str) and url.startswith("http"):
                        yield {"type": "file", "kind": "image", "url": url, "name": fname}

    # 2) 视频：video_generate / video_task_query → {"video_url": "http..."}
    vurl = resp.get("video_url")
    if isinstance(vurl, str) and vurl.startswith("http"):
        yield {"type": "file", "kind": "video", "url": vurl,
               "name": os.path.basename(vurl.split("?")[0]) or "video.mp4"}

    # 3) 文档：create_document → {"ok":true,"fmt":...,"path":"/home/gem/veadk_docs/xxx"}
    if resp.get("ok") and resp.get("path") and str(resp["path"]).startswith(_DOC_DIR):
        path = resp["path"]
        fmt = (resp.get("fmt") or path.rsplit(".", 1)[-1]).lower()
        fname = os.path.basename(path)
        # 让前端通过本层 /api/file 拉取（携带同一会话上下文以定位沙箱）
        qs = (
            f"path={quote(path)}&user_id={quote(user_id)}"
            f"&session_id={quote(session_id)}&fmt={quote(fmt)}"
        )
        yield {"type": "file", "kind": "doc", "fmt": fmt, "name": fname,
               "url": f"/api/file?{qs}"}

    # 4) 兜底：任意字符串型 URL 且带媒体后缀
    for v in resp.values():
        if isinstance(v, str) and v.startswith("http"):
            low = v.split("?")[0].lower()
            if low.endswith(_IMG_EXT):
                yield {"type": "file", "kind": "image", "url": v,
                       "name": os.path.basename(low)}
            elif low.endswith(_VID_EXT):
                yield {"type": "file", "kind": "video", "url": v,
                       "name": os.path.basename(low)}


def _extract_chunks(ev: dict, user_id: str = "", session_id: str = ""):
    """从一条 ADK SSE 事件里抽取要展示给前端的片段。

    - 文本 part：区分 thought（思考）与正文；
    - function_call：作为「工具调用」提示；
    - function_response：抽取文件引用 → `file` 事件，供前端渲染/下载/播放。
    """
    content = ev.get("content") or {}
    parts = content.get("parts") or []
    partial = bool(ev.get("partial"))
    for p in parts:
        if p.get("text"):
            yield {
                "type": "thought" if p.get("thought") else "text",
                "text": p["text"],
                "partial": partial,
            }
        fc = p.get("functionCall") or p.get("function_call")
        if fc:
            yield {"type": "tool_call", "name": fc.get("name", "?")}
        fr = p.get("functionResponse") or p.get("function_response")
        if fr:
            fname = fr.get("name", "?")
            yield {"type": "tool_result", "name": fname}
            resp = fr.get("response") or {}
            for file_ev in _files_from_tool_response(fname, resp, user_id, session_id):
                yield file_ev


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.get("/api/file")
async def api_file(
    path: str, user_id: str, session_id: str,
    fmt: str = "", download: int = 0,
):
    """把 Agent 在沙箱里生成的文档读回并回传浏览器（PDF/HTML 内联预览，其余下载）。

    通过与聊天相同的 (SANDBOX_AGENT_NAME, user_id, session_id) 定位到同一沙箱会话。
    """
    if not path.startswith(_DOC_DIR):
        raise HTTPException(status_code=400, detail="path not allowed")

    fmt = (fmt or path.rsplit(".", 1)[-1]).lower()
    try:
        res = await run_in_threadpool(
            sandbox_files.read_sandbox_file,
            path=path,
            agent_name=SANDBOX_AGENT_NAME,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"read sandbox file failed: {e!r}")

    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("error", "file not found"))

    media_type = _DOC_MIME.get(fmt, "application/octet-stream")
    fname = os.path.basename(path)
    # PDF/HTML 默认内联预览；docx/pptx 或显式 download=1 走附件下载。
    inline = (fmt in _INLINE_FMTS) and not download
    disp = "inline" if inline else "attachment"
    headers = {
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(fname)}",
        "Cache-Control": "no-store",
    }
    return Response(content=res["data"], media_type=media_type, headers=headers)


# --- 静态前端 ---------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", os.getenv("WEBUI_PORT", "8080")))
    uvicorn.run(app, host="0.0.0.0", port=port)
