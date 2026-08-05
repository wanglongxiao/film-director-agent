# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path


_DEFAULT_DB_PATH = os.getenv(
    "VEADK_OUTPUT_MEMORY_DB_PATH", "/tmp/movie_script_output_memory.db"
)


class ContinuationStore:
    """Persist long-form generation chunks to local sqlite.

    This store is intentionally simple and local-first:
    - durable across process restarts
    - safe for repeated auto-continue checkpoints
    - readable later if session context was compacted away
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_parent_dir()
        self._init_db()

    def _ensure_parent_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS output_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    truncated INTEGER NOT NULL DEFAULT 0,
                    finish_reason TEXT DEFAULT '',
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_output_checkpoints_lookup
                ON output_checkpoints (app_name, user_id, session_id, request_id, chunk_index)
                """
            )
            conn.commit()

    def save_chunk(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        request_id: str,
        chunk_index: int,
        content: str,
        truncated: bool,
        finish_reason: str = "",
    ) -> None:
        if not content.strip():
            return

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO output_checkpoints (
                    app_name, user_id, session_id, request_id, chunk_index,
                    truncated, finish_reason, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_name,
                    user_id,
                    session_id,
                    request_id,
                    chunk_index,
                    1 if truncated else 0,
                    finish_reason,
                    content,
                    time.time(),
                ),
            )
            conn.commit()

    def get_latest_request_id(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT request_id
                FROM output_checkpoints
                WHERE app_name = ? AND user_id = ? AND session_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (app_name, user_id, session_id),
            ).fetchone()
        return row["request_id"] if row else None

    def assemble_request(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        request_id: str,
    ) -> str:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT content
                FROM output_checkpoints
                WHERE app_name = ? AND user_id = ? AND session_id = ? AND request_id = ?
                ORDER BY chunk_index ASC, id ASC
                """,
                (app_name, user_id, session_id, request_id),
            ).fetchall()
        return "\n".join(row["content"] for row in rows if row["content"])

    def tail_chars(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        request_id: str,
        max_chars: int,
    ) -> str:
        assembled = self.assemble_request(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
        )
        if max_chars <= 0:
            return assembled
        return assembled[-max_chars:]

    def count_chunks(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        request_id: str,
    ) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM output_checkpoints
                WHERE app_name = ? AND user_id = ? AND session_id = ? AND request_id = ?
                """,
                (app_name, user_id, session_id, request_id),
            ).fetchone()
        return int(row["count"]) if row else 0


continuation_store = ContinuationStore()
