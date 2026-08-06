# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""创作产物持久化存储 —— 把 Agent 运行时产生的一切「有价值信息」落盘到本地 sqlite。

需求：Agent 运行时，将所有有价值的信息持久化存储，包含但不限于：
- 剧本大纲、主要人物侧写、完整的细致剧本；
- 生成的图片 / 视频的描述与「完整 URL」（含 X-Tos-* 签名参数，绝不截断）。

与 document_draft_store（面向「最终组装成 PDF」的有序草稿）不同，本模块面向「知识资产
留存」：按 kind 归档，可跨轮次检索回看，且对媒体资产强制保存 **完整 URL**（TEXT 无长度上限）。

一条产物由 (app_name, user_id, session_id) 圈定归属；kind 取值约定：
  outline    剧本大纲 / 分集结构
  character  主要人物侧写
  script     完整细致剧本（可分多条累积）
  image      生成的图片：content=描述，url=完整签名 URL
  video      生成的视频：content=描述，url=完整签名 URL
  note       其它有价值信息
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path


_DEFAULT_DB_PATH = os.getenv(
    "VEADK_ARTIFACT_DB_PATH", "/tmp/movie_script_artifacts.db"
)

# 约定的产物类别；非约定值一律归为 "note"，避免脏数据。
KNOWN_KINDS = ("outline", "character", "script", "image", "video", "note")


def _normalize_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    return k if k in KNOWN_KINDS else "note"


class ArtifactStore:
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
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_lookup
                ON artifacts (app_name, user_id, session_id, kind, created_at)
                """
            )
            # 幂等去重：同一会话内 (kind, url) 完全相同的媒体资产不重复存（url 非空时）。
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_media
                ON artifacts (app_name, user_id, session_id, kind, url)
                WHERE url <> ''
                """
            )
            conn.commit()

    def save(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        kind: str,
        title: str = "",
        content: str = "",
        url: str = "",
    ) -> int | None:
        """持久化一条产物；空内容且空 URL 视为无效。媒体资产按 (kind,url) 幂等。

        注意：url 原样整段保存，绝不截断签名参数。
        """
        kind = _normalize_kind(kind)
        title = (title or "").strip()
        content = content or ""
        url = (url or "").strip()
        if not content.strip() and not url:
            return None

        with self._lock, self._connect() as conn:
            # 媒体资产（有 url）先按 (kind,url) 查重，命中则更新描述而不新增。
            if url:
                existing = conn.execute(
                    """
                    SELECT id FROM artifacts
                    WHERE app_name = ? AND user_id = ? AND session_id = ?
                      AND kind = ? AND url = ?
                    """,
                    (app_name, user_id, session_id, kind, url),
                ).fetchone()
                if existing is not None:
                    conn.execute(
                        "UPDATE artifacts SET title = ?, content = ? WHERE id = ?",
                        (title, content, int(existing["id"])),
                    )
                    conn.commit()
                    return int(existing["id"])

            cur = conn.execute(
                """
                INSERT INTO artifacts (
                    app_name, user_id, session_id, kind, title, content, url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (app_name, user_id, session_id, kind, title, content, url, time.time()),
            )
            conn.commit()
            return int(cur.lastrowid) if cur.lastrowid is not None else None

    def list(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        kind: str = "",
        limit: int = 50,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        where = "app_name = ? AND user_id = ? AND session_id = ?"
        params: list = [app_name, user_id, session_id]
        if kind.strip():
            where += " AND kind = ?"
            params.append(_normalize_kind(kind))
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, kind, title, content, url, created_at
                FROM artifacts WHERE {where}
                ORDER BY id DESC LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        if not query.strip():
            return []
        limit = max(1, min(int(limit), 100))
        pattern = f"%{query.strip()}%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, title, content, url, created_at
                FROM artifacts
                WHERE app_name = ? AND user_id = ? AND session_id = ?
                  AND (title LIKE ? OR content LIKE ? OR url LIKE ?)
                ORDER BY id DESC LIMIT ?
                """,
                (app_name, user_id, session_id, pattern, pattern, pattern, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def stats(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT kind, COUNT(*) AS n FROM artifacts
                WHERE app_name = ? AND user_id = ? AND session_id = ?
                GROUP BY kind
                """,
                (app_name, user_id, session_id),
            ).fetchall()
        by_kind = {r["kind"]: int(r["n"]) for r in rows}
        return {"total": sum(by_kind.values()), "by_kind": by_kind}

    @staticmethod
    def _row_to_dict(row) -> dict:
        # content 完整返回；url 必须完整（含签名参数）绝不截断。
        return {
            "id": int(row["id"]),
            "kind": row["kind"],
            "title": row["title"] or "",
            "content": row["content"] or "",
            "url": row["url"] or "",
            "created_at": float(row["created_at"]),
        }


artifact_store = ArtifactStore()
