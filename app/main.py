"""FastAPI backend for the movie script agent (streaming chat + persistence)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, imagegen, novel, word_export, persist as persist_mod
import config
from .schemas import (
    ChatRequest,
    ChatResponse,
    EpisodeRequest,
    EpisodeResponse,
    NovelRequest,
    ModelRequest,
    ReferenceImage,
    ReferenceRequest,
    ReferenceResponse,
    SessionCreate,
    SessionOut,
    SessionState,
)
from .store import SessionStore
from .access import CloudAccess

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

store = SessionStore()
persist = persist_mod.Persist()


async def _sweep_loop() -> None:
    """Periodically drop sessions whose browser window has disconnected."""
    while True:
        await asyncio.sleep(60)
        store.sweep(max_age_seconds=600)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    task = asyncio.create_task(_sweep_loop())
    yield
    task.cancel()


app = FastAPI(title="Movie Script Agent", version="0.4.0", lifespan=_lifespan)
app.add_middleware(CloudAccess)


def public_error(exc: Exception) -> str:
    """避免第三方异常将模型端点、密钥或签名 URL 返回浏览器。"""
    if config.WEBUI_CLOUD_MODE:
        return "生成失败，请重试。"
    return str(exc)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/models")
def models() -> dict:
    return {"default": config.DEFAULT_TEXT_MODEL, "models": [
        {"id": key, "max_tokens": value["max_tokens"]} for key, value in config.CHAT_MODELS.items()
    ]}


@app.post("/api/sessions", response_model=SessionOut)
def create_session(body: SessionCreate) -> SessionOut:
    sid = store.create(body.language)
    store.set_model(sid, body.text_model)
    item = store.get(sid)
    return SessionOut(session_id=sid, state=item["state"])


@app.patch("/api/sessions/{sid}/model", response_model=SessionOut)
def select_model(sid: str, body: ModelRequest) -> SessionOut:
    if store.get(sid) is None:
        raise HTTPException(status_code=404, detail="session not found")
    state = store.set_model(sid, body.text_model)
    if state is None:
        raise HTTPException(status_code=409, detail="请先停止正文生成，再切换模型。")
    persist.save_task_state(sid, state)
    return SessionOut(session_id=sid, state=state)


@app.get("/api/sessions/{sid}", response_model=SessionOut)
def get_session(sid: str) -> SessionOut:
    item = store.get(sid)
    if item is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.touch(sid)
    return SessionOut(session_id=sid, state=item["state"])


@app.post("/api/sessions/{sid}/heartbeat")
def heartbeat(sid: str) -> dict:
    if store.get(sid) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.touch(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/chat", response_model=ChatResponse)
def chat(sid: str, body: ChatRequest) -> ChatResponse:
    item = store.get(sid)
    if item is None:
        raise HTTPException(status_code=404, detail="session not found")
    if store.novel_busy(sid):
        raise HTTPException(status_code=409, detail="正文生成中，请先停止生成。")
    try:
        reply, new_state = agent.run_agent(item["state"], item["history"], body.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=public_error(exc)) from exc
    store.add_history(sid, "user", body.message)
    store.add_history(sid, "assistant", reply)
    if new_state.stage in ("script_type", "episodes") and (
        not new_state.characters or not new_state.outline
    ):
        new_state = agent.backfill_state_from_history(new_state, store.get(sid)["history"])
    store.set_state(sid, new_state)
    persist.save_task_state(sid, new_state)
    return ChatResponse(reply=reply, state=new_state)


@app.post("/api/sessions/{sid}/chat/stream")
def chat_stream(sid: str, body: ChatRequest) -> StreamingResponse:
    """Stream one agent turn as newline-delimited JSON.

    Events: {"type":"thought"|"output","delta":...} then
    {"type":"done","reply","stage","state"} / {"type":"interrupted"} / {"type":"error"}.
    """
    item = store.get(sid)
    if item is None:
        raise HTTPException(status_code=404, detail="session not found")
    if store.novel_busy(sid):
        raise HTTPException(status_code=409, detail="正文生成中，请先停止生成。")
    store.set_cancel(sid, False)

    def generate():
        store.touch(sid)
        events = agent.stream_run_agent(
            item["state"],
            item["history"],
            body.message,
            should_stop=lambda: store.is_cancel(sid),
        )
        try:
            for ev in events:
                store.touch(sid)
                etype = ev["type"]
                if etype in ("thought", "output"):
                    yield json.dumps({"type": etype, "delta": ev["delta"]}, ensure_ascii=False) + "\n"
                elif etype == "done":
                    if ev.get("interrupted"):
                        yield json.dumps({"type": "interrupted"}, ensure_ascii=False) + "\n"
                        return
                    new_state = ev["state"]
                    store.add_history(sid, "user", body.message)
                    store.add_history(sid, "assistant", ev["reply"])
                    if new_state.stage in ("script_type", "episodes") and (
                        not new_state.characters or not new_state.outline
                    ):
                        new_state = agent.backfill_state_from_history(
                            new_state, store.get(sid)["history"]
                        )
                    store.set_state(sid, new_state)
                    persist.save_task_state(sid, new_state)
                    payload = {
                        "type": "done",
                        "reply": ev["reply"],
                        "stage": new_state.stage,
                        "state": new_state.model_dump(mode="json"),
                    }
                    yield json.dumps(payload, ensure_ascii=False) + "\n"
                    return
        except GeneratorExit:
            raise
        except Exception as exc:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": public_error(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/api/sessions/{sid}/stop")
def stop_generation(sid: str) -> dict:
    """Signal the in-flight generation to stop."""
    if store.get(sid) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.set_cancel(sid, True)
    return {"ok": True}


@app.post("/api/sessions/{sid}/close")
def close_session(sid: str) -> dict:
    """Delete the interactive task (browser window closed / refreshed)."""
    store.delete(sid)
    return {"ok": True}


@app.post("/api/sessions/{sid}/episodes/generate", response_model=EpisodeResponse)
def generate_episode(sid: str, body: EpisodeRequest) -> EpisodeResponse:
    item = store.get(sid)
    if item is None:
        raise HTTPException(status_code=404, detail="session not found")
    if store.novel_busy(sid):
        raise HTTPException(status_code=409, detail="正文生成中，请先停止生成。")
    state = item["state"]
    try:
        episode = agent.generate_episode(state, body.number, body.storyboards_count)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=public_error(exc)) from exc
    if body.with_images:
        prompts = [
            f"Storyboard: {sb.shot}\nScene: {sb.scene}".strip()
            for sb in episode.storyboards
        ]
        # Generate storyboard images in parallel (max concurrency 10).
        urls = imagegen.generate_images(prompts)
        for idx, (sb, prompt, image_url) in enumerate(
            zip(episode.storyboards, prompts, urls)
        ):
            sb.image_url = image_url
            persist.save_image(sid, episode.number, idx, sb.shot, sb.scene, prompt, sb.image_url)
    store.add_episode(sid, episode)
    item = store.get(sid)
    persist.save_task_state(sid, item["state"])
    return EpisodeResponse(episode=episode, state=item["state"])


@app.post("/api/sessions/{sid}/references/generate", response_model=ReferenceResponse)
def generate_references(sid: str, body: ReferenceRequest) -> ReferenceResponse:
    """Generate reference images: main character portraits + key scene references.

    Requires character profiles and story outline to be present in the session.
    """
    item = store.get(sid)
    if item is None:
        raise HTTPException(status_code=404, detail="session not found")
    if store.novel_busy(sid):
        raise HTTPException(status_code=409, detail="正文生成中，请先停止生成。")
    state = item["state"]
    # The conversational model sometimes writes profiles/outline into the visible
    # reply only. Recover them from history so this feature isn't blocked.
    if not state.characters or not state.outline:
        state = agent.backfill_state_from_history(state, item["history"])
        if state.characters and state.outline:
            store.set_state(sid, state)
            persist.save_task_state(sid, state)
    if not state.characters or not state.outline:
        raise HTTPException(
            status_code=400,
            detail="missing_prerequisites",
        )
    total = max(1, min(8, body.total))

    # Prefer characters first (up to available), remainder goes to scenes.
    char_slots = min(len(state.characters), total)
    scene_slots = total - char_slots

    tasks: list[ReferenceImage] = []
    for c in state.characters[:char_slots]:
        prompt = (
            f"Character concept portrait of {c.name} ({c.role}). "
            f"Background: {c.background}. Personality: {c.personality}. "
            "Full-body reference sheet, neutral background, cinematic lighting."
        )
        tasks.append(ReferenceImage(
            kind="character", title=f"{c.name} · 定妆图", prompt=prompt, character_name=c.name
        ))

    # Break the outline into scene beats for the remaining slots.
    outline = state.outline.strip()
    beats = [b.strip() for b in outline.replace("\r", "").split("\n") if b.strip()]
    if not beats:
        beats = [outline]
    step = max(1, len(beats) // max(1, scene_slots))
    picks = beats[::step][:scene_slots] if scene_slots else []
    for i, beat in enumerate(picks, 1):
        prompt = f"Key scene reference for the script. Scene {i}: {beat}. Cinematic, wide shot."
        tasks.append(ReferenceImage(kind="scene", title=f"关键分镜 {i}", prompt=prompt))

    # Generate all reference images in parallel (max concurrency 10).
    urls = imagegen.generate_images([ref.prompt for ref in tasks])
    for idx, (ref, image_url) in enumerate(zip(tasks, urls)):
        ref.image_url = image_url
        persist.save_image(
            sid, 0, idx, ref.title, ref.kind, ref.prompt, ref.image_url,
            kind=ref.kind, character_name=ref.character_name,
        )

    return ReferenceResponse(images=tasks)


@app.post("/api/sessions/{sid}/novel/generate")
def generate_novel(sid: str, body: NovelRequest) -> StreamingResponse:
    item = store.get(sid)
    if item is None:
        raise HTTPException(status_code=404, detail="session not found")
    if not item["state"].characters or not item["state"].outline:
        raise HTTPException(status_code=400, detail="请先完成角色侧写和故事大纲。")
    existing = item["state"].novel
    if existing and (existing.chapters_count, existing.chapter_length) != (
        body.chapters_count, body.chapter_length
    ):
        raise HTTPException(status_code=409, detail="已有章节规划，请使用原篇幅设置继续，或新建任务。")
    if not store.begin_novel(sid):
        raise HTTPException(status_code=409, detail="正文生成中，请勿重复提交。")
    cancel_event = store.novel_cancel_event(sid)

    def encode(event):
        return json.dumps(event, ensure_ascii=False) + "\n"

    def stopped():
        return store.get(sid) is None or cancel_event.is_set()

    def save(state):
        return store.save_novel_state(sid, state, cancel_event, persist.save_task_state)

    def generate():
        state = item["state"]
        try:
            if state.novel is None:
                yield encode({"type": "planning"})
                state.novel = novel.plan_novel(state, body)
                if not save(state):
                    yield encode({"type": "interrupted"})
                    return
            yield encode({"type": "plan", "state": state.model_dump(mode="json")})
            for chapter in state.novel.chapters:
                if stopped():
                    yield encode({"type": "interrupted"})
                    return
                if chapter.content:
                    continue
                yield encode({"type": "chapter_start", "number": chapter.number, "title": chapter.title})
                completed = False
                for ev in novel.stream_chapter(state, chapter, stopped):
                    store.touch(sid)
                    if ev["type"] == "chapter_complete":
                        result = ev["chapter"]
                        chapter.content = result.content
                        chapter.summary = result.summary
                        if not save(state):
                            yield encode({"type": "interrupted"})
                            return
                        completed = True
                        yield encode({
                            "type": "chapter_done",
                            "chapter": chapter.model_dump(mode="json"),
                            "length": novel.manuscript_length(chapter.content, state.language),
                        })
                    else:
                        yield encode(ev)
                if not completed:
                    yield encode({"type": "interrupted"})
                    return
            yield encode({"type": "done", "state": state.model_dump(mode="json")})
        except GeneratorExit:
            raise
        except Exception as exc:
            yield encode({"type": "error", "message": public_error(exc)})
        finally:
            store.end_novel(sid, cancel_event)

    return StreamingResponse(
        generate(), media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions/{sid}/export/word")
def export_word(sid: str) -> Response:
    item = store.get(sid)
    if item:
        state = item["state"]
    else:
        # Completed output survives the browser task being closed/refreshed.
        row = persist.get_task(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        data = {key: row[key] for key in SessionState.model_fields if key in row}
        for key in ("characters", "episodes", "novel"):
            data[key] = json.loads(row[key]) if row.get(key) else ([] if key != "novel" else None)
        state = SessionState.model_validate(data)
    if not (state.novel and any(c.content for c in state.novel.chapters)) and not state.episodes:
        raise HTTPException(status_code=400, detail="请先生成至少一章正文或分镜剧本。")
    node = shutil.which("node")
    if not node:
        raise HTTPException(status_code=503, detail="Word 导出需要 Node.js，请安装 Node.js 并运行 npm ci。")
    try:
        payload = word_export.export_payload(sid, state, persist)
        result = subprocess.run(
            [node, os.path.join(os.path.dirname(__file__), "export_docx.cjs")],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True, check=True, timeout=60,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=public_error(exc)) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(status_code=500, detail="Word 导出失败，请确认已运行 npm ci。") from exc
    title = state.novel.title if state.novel else "电影剧本"
    return Response(
        result.stdout,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"manuscript.docx\"; filename*=UTF-8''{quote(title, safe='')}.docx"},
    )


# Serve the frontend; API routes above take precedence.
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
