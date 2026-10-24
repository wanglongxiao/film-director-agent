"""SQLite persistence for valuable agent output.

Persists, per task: script background/tone/outline, character profiles, the
complete detailed script (episodes), and every generated image description
with its full URL. Data survives the interactive task being deleted.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Optional

import config

from .schemas import SessionState

PROJECT_ROOT = os.path.dirname(os.path.abspath(config.__file__))
DEFAULT_DB_PATH = os.getenv("SCRIPT_DB_PATH") or (
    "/tmp/movieagent/script.db" if config.WEBUI_CLOUD_MODE
    else os.path.join(PROJECT_ROOT, "data", "script.db")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    language    TEXT,
    stage       TEXT,
    genre       TEXT,
    tone        TEXT,
    background  TEXT,
    characters  TEXT,     -- JSON array of character profiles
    outline     TEXT,
    style       TEXT,
    rating      TEXT,
    script_type TEXT,
    episodes    TEXT,     -- JSON array of complete detailed script
    novel       TEXT,     -- complete chapter plan and finished prose
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS images (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT,
    episode_number   INTEGER,
    storyboard_index INTEGER,
    shot             TEXT,
    scene            TEXT,
    prompt           TEXT,
    image_url        TEXT,
    created_at       TEXT
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Persist:
    """Thread-safe SQLite persistence with a per-operation connection."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            # Add the manuscript column without losing existing scripts/images.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "novel" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN novel TEXT")
            if "text_model" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN text_model TEXT DEFAULT 'deepseek-1017'")
            image_columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)")}
            for name, column_type in (("kind", "TEXT"), ("character_name", "TEXT"), ("image_blob", "BLOB")):
                if name not in image_columns:
                    conn.execute(f"ALTER TABLE images ADD COLUMN {name} {column_type}")
            conn.commit()

    def save_task_state(self, task_id: str, state: SessionState) -> None:
        """Upsert the current script state (outline, characters, script)."""
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, language, stage, genre, tone, background, characters,
                    outline, style, rating, script_type, episodes, novel, text_model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    language=excluded.language, stage=excluded.stage, genre=excluded.genre,
                    tone=excluded.tone, background=excluded.background,
                    characters=excluded.characters, outline=excluded.outline,
                    style=excluded.style, rating=excluded.rating,
                    script_type=excluded.script_type, episodes=excluded.episodes,
                    novel=excluded.novel,
                    text_model=excluded.text_model,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    state.language,
                    state.stage,
                    state.genre,
                    state.tone,
                    state.background,
                    json.dumps([c.model_dump() for c in state.characters], ensure_ascii=False),
                    state.outline,
                    state.style,
                    state.rating,
                    state.script_type,
                    json.dumps([e.model_dump() for e in state.episodes], ensure_ascii=False),
                    state.novel.model_dump_json() if state.novel else None,
                    state.text_model,
                    _now(),
                    _now(),
                ),
            )
            conn.commit()

    def save_image(
        self,
        task_id: str,
        episode_number: int,
        storyboard_index: int,
        shot: str,
        scene: str,
        prompt: str,
        image_url: str,
        kind: str = "",
        character_name: str = "",
    ) -> None:
        """Persist a generated storyboard image description and its URL."""
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO images (
                    task_id, episode_number, storyboard_index, shot, scene, prompt,
                    image_url, created_at, kind, character_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    episode_number,
                    storyboard_index,
                    shot,
                    scene,
                    prompt,
                    image_url,
                    _now(),
                    kind,
                    character_name,
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[dict]:
        """Fetch a persisted task row (for inspection / recovery)."""
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def cache_image(self, image_id: int, data: bytes) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("UPDATE images SET image_blob = ? WHERE id = ?", (data, image_id))
            conn.commit()

    def get_images(self, task_id: str) -> list[dict]:
        """Fetch all persisted images for a task, ordered by episode/index."""
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM images WHERE task_id = ? ORDER BY id", (task_id,)
            ).fetchall()
            return [dict(r) for r in rows]
