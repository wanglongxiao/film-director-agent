# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Unit tests for the Web UI BFF (webui/server.py).

Covers the Web-UI-facing behavior:
- /api/config exposes only labels ("云端 Agent" / "本地 Agent"), never keys;
- generated-media extraction: 主角定妆照/场景图/分镜图（image）、关键镜头小样视频（video）、
  图文混排 pdf/word（doc）—— all surfaced as `file` events for the UI;
- SSE chunk extraction (text / thought / tool_call / file);
- /api/file path guard (sandbox doc dir only) & inline-vs-download disposition;
- target resolution & auth-header handling (keys stay server-side).
"""

from __future__ import annotations

import asyncio
import unittest

import tests._helpers  # noqa: F401  (sys.path setup so `import server` works)
import server
import httpx
from fastapi import HTTPException


def _run(coro):
    return asyncio.run(coro)


async def _get(app, url):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.get(url)


class FilesFromToolResponseTest(unittest.TestCase):
    def _files(self, name, resp):
        return list(server._files_from_tool_response(name, resp, "u1", "s1"))

    def test_image_generate_success_list(self):
        resp = {"status": "success",
                "success_list": [{"定妆照.png": "http://tos/dingzhuang.png"}]}
        files = self._files("image_generate", resp)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["kind"], "image")
        self.assertEqual(files[0]["url"], "http://tos/dingzhuang.png")
        self.assertEqual(files[0]["name"], "定妆照.png")

    def test_video_url_extraction(self):
        files = self._files("video_generate", {"video_url": "http://tos/keyshot.mp4?token=x"})
        # Both the explicit video_url branch and the extension-fallback branch match,
        # so >=1 video event is emitted; the frontend dedups by url+name.
        self.assertGreaterEqual(len(files), 1)
        self.assertTrue(all(f["kind"] == "video" for f in files))
        self.assertEqual(files[0]["name"], "keyshot.mp4")

    def test_video_generate_success_list_is_video_with_full_signed_url(self):
        # video_generate returns success_list (same shape as image_generate); it must
        # be classified as VIDEO (not image) and keep the full signed URL incl. query.
        signed = ("https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/x.mp4"
                  "?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Signature=abc123")
        resp = {"status": "success", "success_list": [{"scene1_rooftop": signed}]}
        files = self._files("video_generate", resp)
        video_files = [f for f in files if f["kind"] == "video"]
        self.assertTrue(video_files, "video_generate success_list must yield a video file")
        self.assertEqual(video_files[0]["url"], signed)  # 签名参数完整保留
        self.assertIn("X-Tos-Signature=abc123", video_files[0]["url"])
        # 不得被误判为 image（旧 bug：success_list 一律当图片 → 视频渲染成破图）。
        self.assertFalse(any(f["kind"] == "image" for f in files))

    def test_document_path_becomes_api_file_link(self):
        resp = {"ok": True, "fmt": "pdf",
                "path": "/home/gem/veadk_docs/霓虹之眼.pdf", "size_bytes": 1000}
        files = self._files("create_document", resp)
        self.assertEqual(len(files), 1)
        f = files[0]
        self.assertEqual(f["kind"], "doc")
        self.assertEqual(f["fmt"], "pdf")
        self.assertEqual(f["name"], "霓虹之眼.pdf")
        self.assertTrue(f["url"].startswith("/api/file?"))
        self.assertIn("user_id=u1", f["url"])
        self.assertIn("session_id=s1", f["url"])

    def test_draft_build_document_result_is_recognized_as_doc(self):
        # draft_build_document returns the same {ok, path, fmt} shape as create_document.
        resp = {"ok": True, "fmt": "pdf",
                "path": "/home/gem/veadk_docs/长剧本.pdf",
                "draft_id": "default", "assembled_from": {"sections": 4, "images": 4}}
        files = self._files("draft_build_document", resp)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["kind"], "doc")

    def test_document_outside_doc_dir_is_ignored(self):
        resp = {"ok": True, "fmt": "pdf", "path": "/etc/passwd"}
        self.assertEqual(self._files("create_document", resp), [])

    def test_fallback_media_url_by_extension(self):
        files = self._files("some_tool", {"cover": "http://cdn/scene.jpg"})
        kinds = {f["kind"] for f in files}
        self.assertIn("image", kinds)

    def test_non_dict_response_is_safe(self):
        self.assertEqual(self._files("x", "not-a-dict"), [])


class ExtractChunksTest(unittest.TestCase):
    def test_text_thought_toolcall_and_file(self):
        ev = {
            "partial": False,
            "content": {"parts": [
                {"text": "正文内容"},
                {"text": "思考中", "thought": True},
                {"functionCall": {"name": "image_generate"}},
                {"functionResponse": {"name": "image_generate",
                    "response": {"success_list": [{"a.png": "http://x/a.png"}]}}},
            ]},
        }
        chunks = list(server._extract_chunks(ev, "u1", "s1"))
        types_ = [c["type"] for c in chunks]
        self.assertIn("text", types_)
        self.assertIn("thought", types_)
        self.assertIn("tool_call", types_)
        self.assertIn("tool_result", types_)
        self.assertIn("file", types_)
        text_chunk = next(c for c in chunks if c["type"] == "text")
        self.assertEqual(text_chunk["text"], "正文内容")
        self.assertFalse(text_chunk["partial"])

    def test_snake_case_function_keys_supported(self):
        ev = {"content": {"parts": [{"function_call": {"name": "video_generate"}}]}}
        chunks = list(server._extract_chunks(ev))
        self.assertEqual(chunks[0]["type"], "tool_call")
        self.assertEqual(chunks[0]["name"], "video_generate")

    def test_sse_serialization_keeps_unicode(self):
        line = server._sse({"type": "text", "text": "中文"})
        self.assertTrue(line.startswith("data: "))
        self.assertTrue(line.endswith("\n\n"))
        self.assertIn("中文", line)  # ensure_ascii=False


class TargetConfTest(unittest.TestCase):
    def test_cloud_and_local_conf(self):
        self.assertEqual(server._target_conf("cloud")["app_name"], server.CLOUD_APP_NAME)
        self.assertEqual(server._target_conf("local")["api_key"], "")

    def test_unknown_target_raises(self):
        with self.assertRaises(HTTPException):
            server._target_conf("bogus")

    def test_auth_headers_only_when_key_present(self):
        self.assertEqual(server._auth_headers(""), {})
        self.assertEqual(server._auth_headers("k")["Authorization"], "Bearer k")


class ApiConfigRouteTest(unittest.TestCase):
    def tearDown(self):
        # Restore whatever the module started with.
        pass

    def test_config_lists_cloud_label_and_hides_keys(self):
        orig_key, orig_local = server.CLOUD_API_KEY, server.ENABLE_LOCAL
        server.CLOUD_API_KEY = "secret-key"
        server.ENABLE_LOCAL = True
        try:
            r = _run(_get(server.app, "/api/config"))
            data = r.json()
        finally:
            server.CLOUD_API_KEY, server.ENABLE_LOCAL = orig_key, orig_local

        self.assertEqual(r.status_code, 200)
        labels = {t["label"] for t in data["targets"]}
        self.assertIn("云端 Agent", labels)
        self.assertIn("本地 Agent", labels)
        self.assertEqual(data["default"], "cloud")
        # No secret leaks into the payload.
        self.assertNotIn("secret-key", r.text)

    def test_config_without_cloud_key_omits_cloud(self):
        orig_key, orig_local = server.CLOUD_API_KEY, server.ENABLE_LOCAL
        server.CLOUD_API_KEY = ""
        server.ENABLE_LOCAL = True
        try:
            data = _run(_get(server.app, "/api/config")).json()
        finally:
            server.CLOUD_API_KEY, server.ENABLE_LOCAL = orig_key, orig_local
        ids = {t["id"] for t in data["targets"]}
        self.assertNotIn("cloud", ids)
        self.assertEqual(data["default"], "local")


class ApiFileRouteTest(unittest.TestCase):
    def test_rejects_path_outside_doc_dir(self):
        r = _run(_get(server.app,
                      "/api/file?path=/etc/passwd&user_id=u1&session_id=s1"))
        self.assertEqual(r.status_code, 400)

    def test_reads_sandbox_file_inline_for_pdf(self):
        # Monkeypatch the sandbox reader so no network / credentials are needed.
        import sandbox_files
        orig = sandbox_files.read_sandbox_file
        sandbox_files.read_sandbox_file = lambda **kw: {
            "ok": True, "path": kw["path"], "size": 3, "data": b"PDF"}
        try:
            r = _run(_get(server.app,
                "/api/file?path=/home/gem/veadk_docs/a.pdf&user_id=u1&session_id=s1&fmt=pdf"))
        finally:
            sandbox_files.read_sandbox_file = orig
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertTrue(r.headers["content-disposition"].startswith("inline"))
        self.assertEqual(r.content, b"PDF")

    def test_docx_is_served_as_attachment(self):
        import sandbox_files
        orig = sandbox_files.read_sandbox_file
        sandbox_files.read_sandbox_file = lambda **kw: {
            "ok": True, "path": kw["path"], "size": 2, "data": b"DX"}
        try:
            r = _run(_get(server.app,
                "/api/file?path=/home/gem/veadk_docs/a.docx&user_id=u1&session_id=s1&fmt=docx"))
        finally:
            sandbox_files.read_sandbox_file = orig
        self.assertTrue(r.headers["content-disposition"].startswith("attachment"))

    def test_missing_file_returns_404(self):
        import sandbox_files
        orig = sandbox_files.read_sandbox_file
        sandbox_files.read_sandbox_file = lambda **kw: {"ok": False, "error": "not found"}
        try:
            r = _run(_get(server.app,
                "/api/file?path=/home/gem/veadk_docs/missing.pdf&user_id=u1&session_id=s1"))
        finally:
            sandbox_files.read_sandbox_file = orig
        self.assertEqual(r.status_code, 404)


class ApiVideoProxyRouteTest(unittest.TestCase):
    """视频播放包底：<video> 直连失败时由 BFF 用完整签名 URL 代理拉取。"""

    def test_rejects_non_http_url(self):
        r = _run(_get(server.app, "/api/video-proxy?url=ftp://x/a.mp4"))
        self.assertEqual(r.status_code, 400)

    def test_rejects_disallowed_host(self):
        # 仅允许方舟/TOS 域名，防止被当作任意 SSRF 代理。
        r = _run(_get(server.app, "/api/video-proxy?url=http://evil.example.com/a.mp4"))
        self.assertEqual(r.status_code, 400)

    def test_allows_volces_tos_signed_url(self):
        # 打桩上游，验证允许的签名 URL 被放行并流式转发（含 content-type 透传）。
        signed = ("https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/x.mp4"
                  "?X-Tos-Signature=abc")

        class _FakeUpstream:
            status_code = 200
            headers = {"content-type": "video/mp4", "content-length": "3"}

            async def aiter_bytes(self):
                yield b"MP4"

            async def aclose(self):
                pass

        real_async_client = server.httpx.AsyncClient

        class _FakeClient:
            def __init__(self, *a, **k):
                # 测试自身的 ASGI 客户端（带 transport）仍用真实实现，只有代理内部的
                # 出站请求（无 transport）走假上游，从而保持离线。
                self._real = real_async_client(*a, **k) if "transport" in k else None

            async def __aenter__(self):
                return await self._real.__aenter__()

            async def __aexit__(self, *a):
                return await self._real.__aexit__(*a)

            def build_request(self, *a, **k):
                return object()

            async def send(self, *a, **k):
                return _FakeUpstream()

            async def aclose(self):
                pass

        server.httpx.AsyncClient = _FakeClient
        try:
            r = _run(_get(server.app, "/api/video-proxy?url=" + signed))
        finally:
            server.httpx.AsyncClient = real_async_client
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "video/mp4")
        self.assertEqual(r.content, b"MP4")


if __name__ == "__main__":
    unittest.main()
