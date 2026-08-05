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
    "VEADK_LOCAL_KB_DB_PATH", "/tmp/movie_script_local_knowledge.db"
)


class LocalKnowledgeStore:
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
                CREATE TABLE IF NOT EXISTS local_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_local_knowledge_lookup
                ON local_knowledge (app_name, user_id, session_id, created_at)
                """
            )
            conn.commit()

    def save(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        title: str,
        content: str,
    ) -> int | None:
        if not title.strip() or not content.strip():
            return None

        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO local_knowledge (
                    app_name, user_id, session_id, title, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    app_name,
                    user_id,
                    session_id,
                    title,
                    content,
                    time.time(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid) if cur.lastrowid is not None else None

    def search(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        if not query.strip():
            return []

        limit = max(1, min(int(limit), 20))
        pattern = f"%{query.strip()}%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, content, created_at
                FROM local_knowledge
                WHERE app_name = ? AND user_id = ? AND session_id = ?
                  AND (title LIKE ? OR content LIKE ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (app_name, user_id, session_id, pattern, pattern, limit),
            ).fetchall()

        results: list[dict] = []
        for row in rows:
            content = row["content"] or ""
            results.append(
                {
                    "id": int(row["id"]),
                    "title": row["title"],
                    "snippet": content[:400],
                    "created_at": float(row["created_at"]),
                }
            )
        return results


local_knowledge_store = LocalKnowledgeStore()
