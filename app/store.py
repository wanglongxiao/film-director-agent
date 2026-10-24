"""In-memory session store (thread-safe)."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Optional

from .schemas import Episode, SessionState


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}  # sid -> {"state", "history", "last_seen", "cancel"}

    def create(self, language: str = "zh-CN") -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = {
                "state": SessionState(language=language),
                "history": [],
                "last_seen": time.time(),
                "cancel": False,
                "novel_busy": False,
                "novel_cancel": threading.Event(),
            }
        return sid

    def get(self, sid: str) -> Optional[dict]:
        with self._lock:
            item = self._sessions.get(sid)
            if item is None:
                return None
            return {
                "state": item["state"].model_copy(deep=True),
                "history": list(item["history"]),
            }

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
                    item["novel_busy"] = False

    def is_cancel(self, sid: str) -> bool:
        with self._lock:
            return bool(self._sessions.get(sid, {}).get("cancel", False))

    def delete(self, sid: str) -> None:
        """Delete an interactive task (called when the browser window closes)."""
        with self._lock:
            self._sessions.pop(sid, None)

    def sweep(self, max_age_seconds: int = 600) -> None:
        """Remove sessions not seen for max_age_seconds (disconnected-window fallback)."""
        now = time.time()
        with self._lock:
            stale = [
                sid
                for sid, item in self._sessions.items()
                if now - item.get("last_seen", 0) > max_age_seconds
            ]
            for sid in stale:
                self._sessions.pop(sid, None)
