"""Private, owner-scoped task documents with conditional writes."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing

import config


class Conflict(RuntimeError):
    pass


class Storage:
    def __init__(self):
        self.cloud = config.WEBUI_CLOUD_MODE or os.getenv("TASK_STORAGE") == "tos"
        self.lock = threading.RLock()
        if self.cloud:
            import tos
            self.tos = tos
            self.bucket = config.TOS_BUCKET
            if not all((self.bucket, config.TOS_REGION, config.TOS_ENDPOINT,
                        os.getenv("BYTEPLUS_AK"), os.getenv("BYTEPLUS_SK"))):
                raise RuntimeError("TOS storage configuration is required.")
            self.client = tos.TosClientV2(
                os.environ["BYTEPLUS_AK"], os.environ["BYTEPLUS_SK"],
                config.TOS_ENDPOINT, config.TOS_REGION,
                connection_time=5, socket_timeout=10, max_retry_count=0,
            )
        else:
            self.path = os.getenv("SCRIPT_DB_PATH", os.path.join(os.path.dirname(config.__file__), "data", "script.db"))
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with closing(sqlite3.connect(self.path)) as db:
                db.execute("CREATE TABLE IF NOT EXISTS task_objects (key TEXT PRIMARY KEY, data BLOB, etag TEXT)")
                db.commit()

    def get(self, key):
        if self.cloud:
            try:
                result = self.client.get_object(self.bucket, key)
                return result.read(), result.etag
            except self.tos.exceptions.TosServerError as exc:
                if exc.status_code == 404:
                    return None, None
                raise
        with self.lock, closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT data, etag FROM task_objects WHERE key=?", (key,)).fetchone()
            return row if row else (None, None)

    def put(self, key, data, etag=None, create=False):
        if self.cloud:
            try:
                return self.client.put_object(
                    self.bucket, key, content=data, if_match=etag,
                    forbid_overwrite=True if create else None,
                    content_type="application/json" if key.endswith(".json") else "application/octet-stream",
                ).etag
            except self.tos.exceptions.TosServerError as exc:
                if exc.status_code in (409, 412):
                    raise Conflict("Task changed; reload before retrying.") from None
                raise
        with self.lock, closing(sqlite3.connect(self.path, timeout=30)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT etag FROM task_objects WHERE key=?", (key,)).fetchone()
            if (create and row) or (etag is not None and (not row or row[0] != etag)):
                raise Conflict("Task changed; reload before retrying.")
            version = uuid.uuid4().hex
            db.execute("INSERT OR REPLACE INTO task_objects VALUES (?,?,?)", (key, data, version))
            db.commit()
            return version

    def delete(self, key):
        if self.cloud:
            self.client.delete_object(self.bucket, key)
        else:
            with self.lock, closing(sqlite3.connect(self.path)) as db:
                db.execute("DELETE FROM task_objects WHERE key=?", (key,))
                db.commit()

    def keys(self, prefix):
        if self.cloud:
            token = None
            while True:
                result = self.client.list_objects_type2(self.bucket, prefix=prefix, continuation_token=token)
                yield from (obj.key for obj in result.contents)
                if not result.is_truncated:
                    break
                token = result.next_continuation_token
        else:
            with self.lock, closing(sqlite3.connect(self.path)) as db:
                yield from (r[0] for r in db.execute(
                    "SELECT key FROM task_objects WHERE key LIKE ?", (prefix + "%",)
                ))

    @staticmethod
    def task_key(owner, sid):
        return f"movieagent/v1/tasks/{owner}/{sid}/task.json"

    @staticmethod
    def summary_key(owner, sid):
        return f"movieagent/v1/history/{owner}/{sid}.json"

    def load(self, owner, sid):
        raw, etag = self.get(self.task_key(owner, sid))
        return (json.loads(raw), etag) if raw else (None, None)

    def save(self, doc, etag=None, create=False):
        owner, sid = doc["owner"], doc["session_id"]
        doc["updated_at"] = time.time()
        version = self.put(self.task_key(owner, sid),
                           json.dumps(doc, ensure_ascii=False).encode(), etag, create)
        state = doc["state"]
        book = state.get("novel") or {}
        summary = {
            "session_id": sid, "title": book.get("title") or state.get("background", "")[:70] or sid[:8],
            "created_at": doc["created_at"], "updated_at": doc["updated_at"],
            "completed": sum(bool(c.get("content")) for c in book.get("chapters", [])),
            "total": book.get("chapters_count", state.get("writing", {}).get("chapters_count", 20)),
            "status": doc.get("status", "idle"), "language": state["language"],
        }
        # The task document is authoritative. A failed summary update must not
        # turn a successfully committed chapter into a failed save.
        try:
            self.put(self.summary_key(owner, sid), json.dumps(summary, ensure_ascii=False).encode())
        except Exception:
            pass
        return version

    def history(self, owner):
        summaries = []
        for key in self.keys(f"movieagent/v1/history/{owner}/"):
            raw, _ = self.get(key)
            if raw:
                summaries.append(json.loads(raw))
        return sorted(summaries, key=lambda d: d["updated_at"], reverse=True)

    def remove(self, owner, sid):
        # Remove the index first, so deleted scripts stop appearing immediately.
        self.delete(self.summary_key(owner, sid))
        for key in list(self.keys(f"movieagent/v1/tasks/{owner}/{sid}/")):
            self.delete(key)
