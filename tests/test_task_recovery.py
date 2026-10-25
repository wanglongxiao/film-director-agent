"""Regression coverage for durable chapters, browser ownership and write races."""
import os
import tempfile
import threading
import asyncio
import time
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.persist import Persist
from app.schemas import Chapter, Character, Novel
from app.storage import Conflict
from app.store import SessionStore
from app.streaming import with_heartbeats


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "SCRIPT_DB_PATH": os.path.join(self.directory.name, "tasks.db"),
            "TASK_STORAGE": "sqlite",
        })
        self.env.start()
        self.original = main.store, main.persist
        main.store = SessionStore()
        main.persist = Persist(main.store)
        # Middleware is constructed lazily; each test needs a fresh stack.
        main.app.user_middleware[-1].kwargs["store"] = main.store
        main.app.middleware_stack = None
        self.client = TestClient(main.app)
        self.sid = self.client.post("/api/sessions", json={}).json()["session_id"]
        state = main.store.get(self.sid)["state"]
        state.background = "Recovery test story"
        state.characters = [Character(name="Test", role="hero")]
        state.outline = "A complete ten-chapter story."
        state.novel = Novel(title="Recovery", chapters_count=10, chapter_length=2000,
                            chapters=[Chapter(number=i, title=f"Chapter {i}", synopsis="Plot")
                                      for i in range(1, 11)])
        main.persist.save_task_state(self.sid, state)

    def tearDown(self):
        main.store, main.persist = self.original
        main.app.user_middleware[-1].kwargs["store"] = main.store
        main.app.middleware_stack = None
        self.env.stop()
        self.directory.cleanup()

    @staticmethod
    def chapter(state, current, stopped, deadline=None):
        result = current.model_copy(deep=True)
        result.content = "test prose " * 250
        result.summary = "Established facts."
        yield {"type": "chapter_complete", "chapter": result}

    def test_one_chapter_per_request_and_restart(self):
        with patch.object(main.novel, "stream_chapter", self.chapter):
            for number in range(1, 11):
                response = self.client.post(f"/api/sessions/{self.sid}/novel/generate",
                                            json={"chapters_count": 10, "chapter_length": 2000})
                self.assertEqual(response.status_code, 200)
                events = [__import__("json").loads(line) for line in response.text.splitlines()]
                self.assertEqual([ev["chapter"]["number"] for ev in events if ev["type"] == "chapter_done"],
                                 [number])
                self.assertEqual(events[-1]["type"], "done" if number == 10 else "next")
        owner = main.store._sessions[self.sid]["doc"]["owner"]
        fresh = SessionStore()
        self.assertTrue(fresh.load_owned(owner, self.sid))
        recovered = fresh.public(self.sid)
        self.assertEqual(sum(bool(c.content) for c in recovered["state"].novel.chapters), 10)
        self.assertFalse(recovered["auto_run"])
        self.assertEqual(recovered["status"], "completed")

    def test_first_generation_reuses_discussion_and_emits_directory(self):
        state = main.store.get(self.sid)["state"]
        state.discussion_chapters = [c.model_copy(deep=True) for c in state.novel.chapters]
        state.writing.chapters_count = 10
        state.writing.chapter_length = 2000
        state.novel = None
        main.persist.save_task_state(self.sid, state)
        with patch.object(main.novel, "plan_novel", side_effect=AssertionError("duplicate planning")):
            response = self.client.post(f"/api/sessions/{self.sid}/novel/generate",
                                        json={"chapters_count": 10, "chapter_length": 2000})
        events = [__import__("json").loads(line) for line in response.text.splitlines()]
        self.assertEqual([event["type"] for event in events], ["plan", "next"])
        self.assertEqual(len(events[0]["state"]["novel"]["chapters"]), 10)
        self.assertEqual([c.title for c in main.store.get(self.sid)["state"].novel.chapters],
                         [c.title for c in state.discussion_chapters])
        with patch.object(main.novel, "stream_chapter", self.chapter):
            response = self.client.post(f"/api/sessions/{self.sid}/novel/generate",
                                        json={"chapters_count": 10, "chapter_length": 2000})
        self.assertIn('"type": "chapter_done"', response.text)

    def test_model_failure_is_persisted_and_visible(self):
        with patch.object(main.novel, "stream_chapter", side_effect=TimeoutError("private endpoint")):
            response = self.client.post(f"/api/sessions/{self.sid}/novel/generate",
                                        json={"chapters_count": 10, "chapter_length": 2000})
        self.assertIn('"message": "generation_timeout"', response.text)
        self.assertNotIn("private endpoint", response.text)
        snapshot = self.client.get(f"/api/sessions/{self.sid}").json()
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["last_error"], "generation_timeout")
        self.assertFalse(snapshot["auto_run"])
        self.assertFalse(snapshot["busy"])

    def test_heartbeats_arrive_before_slow_model_finishes(self):
        def slow():
            time.sleep(.07)
            yield '{"type":"plan"}\n'

        async def consume():
            events = []
            async for line in with_heartbeats(slow(), lambda: None):
                events.append(json.loads(line)["type"])
            return events

        with patch("app.streaming.HEARTBEAT_SECONDS", .01):
            events = asyncio.run(consume())
        self.assertEqual(events[-1], "plan")
        self.assertIn("heartbeat", events[:-1])

    def test_foreign_browser_cannot_read_mutate_export_or_delete(self):
        other = TestClient(main.app)
        for method, path, body in [
            ("GET", "", None), ("GET", "/export/word", None),
            ("GET", "/images", None), ("POST", "/stop", None),
            ("POST", "/novel/generate", {"chapters_count": 10, "chapter_length": 2000}),
            ("DELETE", "", None),
        ]:
            response = other.request(method, f"/api/sessions/{self.sid}{path}", json=body)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(other.get("/api/sessions").json()["tasks"], [])
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}").status_code, 200)

    def test_same_task_concurrent_claim_and_stale_write(self):
        owner = main.store._sessions[self.sid]["doc"]["owner"]
        independent = SessionStore()
        self.assertTrue(independent.load_owned(owner, self.sid))
        token = main.store.claim(self.sid, "novel")
        with self.assertRaises(Conflict):
            independent.claim(self.sid, "novel")
        with self.assertRaises(Conflict):
            independent.flush(self.sid)
        main.store.release(self.sid, token)
        second = independent.claim(self.sid, "chat")
        independent.release(self.sid, second)

    def test_refresh_preserves_discussion_and_explicit_delete_removes(self):
        main.store.add_history(self.sid, "user", "My story")
        main.store.add_history(self.sid, "assistant", "A discussion")
        main.store.flush(self.sid)
        self.client.post(f"/api/sessions/{self.sid}/close")
        response = self.client.get(f"/api/sessions/{self.sid}").json()
        self.assertEqual(len(response["history"]), 2)
        self.assertEqual(self.client.delete(f"/api/sessions/{self.sid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}").status_code, 404)
        self.assertEqual(self.client.get("/api/sessions").json()["tasks"], [])


if __name__ == "__main__":
    unittest.main()
