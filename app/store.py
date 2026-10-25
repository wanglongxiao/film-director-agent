"""Thread-safe runtime cache backed by durable owner-scoped task documents."""
from __future__ import annotations

import threading
import time
import uuid
import copy
from typing import Callable, Optional

from .schemas import Episode, SessionState
from .storage import Storage, Conflict
from .model_output import display_history


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.storage = Storage()
        self._active_tokens: dict[str, str] = {}
        self._sessions: dict[str, dict] = {}  # sid -> {"state", "history", "last_seen", "cancel"}

    def create(self, language: str = "zh-CN", owner: str = "") -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = {
                "state": SessionState(language=language),
                "history": [],
                "last_seen": time.time(),
                "cancel": False,
                "novel_busy": False,
                "novel_cancel": threading.Event(),
                "doc": {"owner": owner, "session_id": sid, "created_at": time.time(),
                        "state": SessionState(language=language).model_dump(mode="json"),
                        "history": [], "images": [], "job": None, "auto_run": False, "status": "idle"},
                "etag": None,
            }
            item = self._sessions[sid]
            item["etag"] = self.storage.save(item["doc"], create=True)
        return sid

    def load_owned(self, owner: str, sid: str) -> bool:
        with self._lock:
            cached = self._sessions.get(sid)
            if cached and cached["doc"]["owner"] != owner:
                return False
            if cached and cached["doc"].get("job"):
                return True
            doc, etag = self.storage.load(owner, sid)
            if not doc:
                return False
            self._sessions[sid] = {
                "state": SessionState.model_validate(doc["state"]), "history": doc["history"],
                "doc": doc, "etag": etag, "last_seen": time.time(), "cancel": False,
                "novel_busy": False, "novel_cancel": threading.Event(),
            }
            return True

    def flush(self, sid: str) -> None:
        with self._lock:
            item = self._sessions[sid]
            doc = item["doc"]
            doc["state"] = item["state"].model_dump(mode="json")
            doc["history"] = copy.deepcopy(item["history"])
            item["etag"] = self.storage.save(doc, item["etag"])

    def claim(self, sid: str, operation: str) -> str:
        with self._lock:
            if sid in self._active_tokens:
                raise Conflict("正文生成中，请勿重复提交。")
            item = self._sessions[sid]
            doc, etag = self.storage.load(item["doc"]["owner"], sid)
            if not doc:
                raise Conflict("session not found")
            if doc.get("job") and doc["job"]["expires_at"] > time.time():
                raise Conflict("正文生成中，请勿重复提交。")
            token = uuid.uuid4().hex
            doc["job"] = {"token": token, "operation": operation, "expires_at": time.time() + 840}
            doc["status"] = "running"
            doc["last_error"] = None
            item["etag"] = self.storage.save(doc, etag)
            item["doc"] = doc
            item["state"] = SessionState.model_validate(doc["state"])
            item["history"] = doc["history"]
            self._active_tokens[sid] = token
            return token

    def release(self, sid: str, token: str) -> None:
        with self._lock:
            if self._active_tokens.get(sid) == token:
                self._active_tokens.pop(sid, None)
            item = self._sessions.get(sid)
            if item and (item["doc"].get("job") or {}).get("token") == token:
                doc = item["doc"]
                doc["job"] = None
                book = item["state"].novel
                done = book and all(c.content for c in book.chapters)
                doc["status"] = "completed" if done else (
                    "failed" if doc.get("last_error") else ("queued" if doc["auto_run"] else "idle")
                )
                try:
                    self.flush(sid)
                except Conflict:
                    # An expired lease may already belong to a different
                    # instance. It must not be released by the old request.
                    self._sessions.pop(sid, None)

    def set_auto_run(self, sid: str, value: bool):
        with self._lock:
            self._sessions[sid]["doc"]["auto_run"] = value
            self.flush(sid)

    def fail_novel(self, sid: str, error: str):
        with self._lock:
            self._sessions[sid]["doc"]["auto_run"] = False
            self._sessions[sid]["doc"]["last_error"] = error
            self.flush(sid)

    def public(self, sid: str) -> dict:
        with self._lock:
            item = self._sessions[sid]
            doc = item["doc"]
            job = doc.get("job")
            return {"session_id": sid, "state": item["state"], "history": display_history(item["history"]),
                    "auto_run": doc["auto_run"], "busy": bool(job and job["expires_at"] > time.time()),
                    "status": doc.get("status", "idle"), "last_error": doc.get("last_error")}

    def get(self, sid: str) -> Optional[dict]:
        with self._lock:
            item = self._sessions.get(sid)
            if item is None:
                return None
            return {
                "state": item["state"].model_copy(deep=True),
                "history": list(item["history"]),
            }

    def exists(self, sid: str) -> bool:
        with self._lock:
            return sid in self._sessions

    def set_state(self, sid: str, state: SessionState) -> None:
        with self._lock:
            self._sessions[sid]["state"] = state.model_copy(deep=True)

    def set_model(self, sid: str, text_model: str) -> SessionState | None:
        with self._lock:
            item = self._sessions.get(sid)
            if item is None or item["novel_busy"]:
                return None
            item["state"].text_model = text_model
            return item["state"].model_copy(deep=True)

    def add_history(self, sid: str, role: str, content: str) -> None:
        with self._lock:
            self._sessions[sid]["history"].append({"role": role, "content": content})

    def add_episode(self, sid: str, episode: Episode) -> None:
        with self._lock:
            episodes = self._sessions[sid]["state"].episodes
            episodes[:] = [e for e in episodes if e.number != episode.number]
            episodes.append(episode)
            episodes.sort(key=lambda e: e.number)

    def begin_novel(self, sid: str) -> bool:
        with self._lock:
            item = self._sessions.get(sid)
            if item is None or item["novel_busy"]:
                return False
            item["novel_busy"] = True
            item["cancel"] = False
            item["novel_cancel"] = threading.Event()
            return True

    def novel_cancel_event(self, sid: str) -> threading.Event:
        with self._lock:
            return self._sessions[sid]["novel_cancel"]

    def save_novel_state(
        self, sid: str, state: SessionState, cancel_event: threading.Event,
        persist_state: Callable[[str, SessionState], None],
    ) -> bool:
        with self._lock:
            item = self._sessions.get(sid)
            if not item or item["novel_cancel"] is not cancel_event or cancel_event.is_set():
                return False
            # Commit memory and archive together before stop/resume can start another run.
            persist_state(sid, state)
            item["state"] = state.model_copy(deep=True)
            item["last_seen"] = time.time()
            return True

    def end_novel(self, sid: str, cancel_event: threading.Event | None = None) -> None:
        with self._lock:
            item = self._sessions.get(sid)
            if item and (cancel_event is None or item["novel_cancel"] is cancel_event):
                item["novel_busy"] = False

    def novel_busy(self, sid: str) -> bool:
        with self._lock:
            return bool(self._sessions.get(sid, {}).get("novel_busy"))

    def touch(self, sid: str) -> None:
        with self._lock:
            if sid in self._sessions:
                self._sessions[sid]["last_seen"] = time.time()

    def set_cancel(self, sid: str, value: bool) -> None:
        with self._lock:
            if sid in self._sessions:
                item = self._sessions[sid]
                item["cancel"] = bool(value)
                if value:
                    # Each run keeps its own event: resuming cannot revive an old
                    # request still waiting for the model's next network response.
                    item["novel_cancel"].set()
                    item["doc"]["auto_run"] = False
                    self.flush(sid)

    def is_cancel(self, sid: str) -> bool:
        with self._lock:
            return bool(self._sessions.get(sid, {}).get("cancel", False))

    def delete(self, sid: str) -> None:
        """Explicitly remove a task and its private objects."""
        with self._lock:
            item = self._sessions.get(sid)
            if item:
                self.storage.remove(item["doc"]["owner"], sid)
                self._sessions.pop(sid, None)

    def sweep(self, max_age_seconds: int = 600) -> None:
        """Remove sessions not seen for max_age_seconds (disconnected-window fallback)."""
        now = time.time()
        with self._lock:
            stale = [
                sid
                for sid, item in self._sessions.items()
                if now - item.get("last_seen", 0) > max_age_seconds and not item["doc"].get("job")
            ]
            for sid in stale:
                self._sessions.pop(sid, None)
