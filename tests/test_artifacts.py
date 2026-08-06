# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Tests for the artifact persistence store + agent tools + media auto-capture.

需求覆盖：
- 剧本大纲/人物侧写/完整剧本/媒体描述都能持久化并可检索；
- 生成图片/视频的【完整 URL】（含 X-Tos-* 签名参数）原样存储、绝不截断；
- image_generate/video_generate 成功后自动落盘媒体 URL（不依赖模型主动记忆）。
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest

import tests._helpers as _helpers  # noqa: F401  (sys.path setup)
from tests._helpers import FakeToolContext

import assistant.agent as agent
from assistant.artifact_store import ArtifactStore

_IDS = {"app_name": "app", "user_id": "u1", "session_id": "s1"}

# 型如用户示例的完整签名 URL，务必整段保留。
_IMG_URL = (
    "https://ark-acg-ap-southeast-1.tos-ap-southeast-1.volces.com/seedream-5-0/"
    "02178600144455049d9e4e345fff0a9cbe1dfa11f8e7ca07aac10_0.jpeg"
    "?X-Tos-Algorithm=TOS4-HMAC-SHA256"
    "&X-Tos-Credential=AKLTYWJk%2F20260806%2Fap-southeast-1%2Ftos%2Frequest"
    "&X-Tos-Date=20260806T073104Z&X-Tos-Expires=86400"
    "&X-Tos-Signature=d9e55c28a1a7a1d6c7b1bcbb59d85cb84e23b81670f46b6bf5c88e7"
    "&X-Tos-SignedHeaders=host"
)
_VID_URL = (
    "https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/"
    "doubao-seedance-1-0-pro/02175020976416700000000000000000000ffffac182c17248b6f.mp4"
    "?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Signature=a1b1f79bd0348516"
    "&X-Tos-SignedHeaders=host"
)


class ArtifactStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = ArtifactStore(db_path=self.tmp.name)

    def test_saves_text_artifacts_by_kind(self):
        self.store.save(**_IDS, kind="outline", content="三幕结构大纲")
        self.store.save(**_IDS, kind="character", content="男主：偏执的操盘手")
        self.store.save(**_IDS, kind="script", content="第一幕 完整分场……")
        stats = self.store.stats(**_IDS)
        self.assertEqual(stats["by_kind"], {"outline": 1, "character": 1, "script": 1})
        self.assertEqual(stats["total"], 3)

    def test_media_url_is_stored_in_full_never_truncated(self):
        self.store.save(**_IDS, kind="image", content="男主定妆照", url=_IMG_URL)
        self.store.save(**_IDS, kind="video", content="终幕毁灭", url=_VID_URL)
        imgs = self.store.list(**_IDS, kind="image")
        vids = self.store.list(**_IDS, kind="video")
        self.assertEqual(imgs[0]["url"], _IMG_URL)  # 完整 URL，含全部签名参数
        self.assertIn("X-Tos-Signature=", imgs[0]["url"])
        self.assertIn("X-Tos-SignedHeaders=host", imgs[0]["url"])
        self.assertEqual(vids[0]["url"], _VID_URL)

    def test_same_media_url_is_deduped_and_description_updated(self):
        i1 = self.store.save(**_IDS, kind="image", content="初版描述", url=_IMG_URL)
        i2 = self.store.save(**_IDS, kind="image", content="更细的描述", url=_IMG_URL)
        self.assertEqual(i1, i2)  # 幂等：同 (kind,url) 不重复插入
        rows = self.store.list(**_IDS, kind="image")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "更细的描述")  # 描述被更新

    def test_empty_content_and_url_is_rejected(self):
        self.assertIsNone(self.store.save(**_IDS, kind="note", content="  ", url=""))

    def test_unknown_kind_falls_back_to_note(self):
        self.store.save(**_IDS, kind="weird", content="x")
        self.assertEqual(self.store.list(**_IDS, kind="note")[0]["kind"], "note")

    def test_search_matches_title_content_and_url(self):
        self.store.save(**_IDS, kind="image", content="雨夜天台", url=_IMG_URL)
        by_content = self.store.search(**_IDS, query="天台")
        by_url = self.store.search(**_IDS, query="seedream-5-0")
        self.assertTrue(by_content and by_content[0]["url"] == _IMG_URL)
        self.assertTrue(by_url and by_url[0]["url"] == _IMG_URL)

    def test_media_urls_returns_only_full_signed_image_and_video_urls(self):
        self.store.save(**_IDS, kind="image", content="男主", url=_IMG_URL)
        self.store.save(**_IDS, kind="video", content="终幕", url=_VID_URL)
        self.store.save(**_IDS, kind="outline", content="大纲无 URL")
        urls = self.store.media_urls(**_IDS)
        self.assertIn(_IMG_URL, urls)
        self.assertIn(_VID_URL, urls)
        self.assertEqual(len(urls), 2)  # 只含图/视频，且都是完整签名 URL


class ReferenceUrlCanonicalizeTest(unittest.TestCase):
    """把模型抄短/丢签名的参考图 URL 还原成持久化中的完整签名 URL（根因修复）。"""

    def test_restores_truncated_reference_urls_by_basename(self):
        # 模型抄短形式：省略路径中段，只保留文件名。
        short = ("https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/"
                 "0b532c8d.../02178600144455049d9e4e345fff0a9cbe1dfa11f8e7ca07aac10_0.jpeg")
        params = [{"prompt": "天台对峙 [图1]", "first_frame": short,
                   "reference_images": [short]}]
        fixed = agent._canonicalize_reference_urls(params, [_IMG_URL])
        self.assertEqual(fixed, 2)
        self.assertEqual(params[0]["first_frame"], _IMG_URL)
        self.assertEqual(params[0]["reference_images"][0], _IMG_URL)

    def test_keeps_already_full_signed_url_untouched(self):
        params = [{"first_frame": _IMG_URL}]
        self.assertEqual(agent._canonicalize_reference_urls(params, [_IMG_URL]), 0)
        self.assertEqual(params[0]["first_frame"], _IMG_URL)

    def test_unknown_basename_is_left_as_is(self):
        params = [{"first_frame": "https://x/unknown.jpeg"}]
        self.assertEqual(agent._canonicalize_reference_urls(params, [_IMG_URL]), 0)
        self.assertEqual(params[0]["first_frame"], "https://x/unknown.jpeg")

    def test_no_known_urls_is_noop(self):
        params = [{"first_frame": "https://x/whatever.jpeg"}]
        self.assertEqual(agent._canonicalize_reference_urls(params, []), 0)

    def test_non_http_values_untouched(self):
        params = [{"first_frame": "data:image/jpeg;base64,AAAA"}]
        self.assertEqual(agent._canonicalize_reference_urls(params, [_IMG_URL]), 0)
        self.assertEqual(params[0]["first_frame"], "data:image/jpeg;base64,AAAA")

    def test_url_helpers(self):
        self.assertTrue(agent._url_is_signed(_IMG_URL))
        self.assertFalse(agent._url_is_signed("https://x/a.jpeg"))
        self.assertEqual(
            agent._url_basename("https://x/y/z/a.JPEG?q=1"), "a.jpeg"
        )


class ArtifactAgentToolTest(unittest.TestCase):
    def setUp(self):
        # 用临时库替换全局 store，避免污染真实文件。
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._orig = agent.artifact_store
        agent.artifact_store = ArtifactStore(db_path=self.tmp.name)
        self.ctx = FakeToolContext()

    def tearDown(self):
        agent.artifact_store = self._orig

    def test_save_and_list_roundtrip(self):
        r = agent.save_artifact(kind="video", content="终幕", url=_VID_URL,
                                tool_context=self.ctx)
        self.assertTrue(r["ok"])
        listed = agent.list_artifacts(kind="video", tool_context=self.ctx)
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["results"][0]["url"], _VID_URL)

    def test_tools_require_context(self):
        self.assertFalse(agent.save_artifact(kind="note", content="x")["ok"])
        self.assertFalse(agent.list_artifacts()["ok"])

    def test_save_rejects_empty(self):
        self.assertFalse(
            agent.save_artifact(kind="note", content="", url="", tool_context=self.ctx)["ok"]
        )


class MediaAutoCaptureTest(unittest.TestCase):
    """image/video 成功后由包装层自动落盘完整 URL，无需模型主动调用 save_artifact。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._orig = agent.artifact_store
        agent.artifact_store = ArtifactStore(db_path=self.tmp.name)
        self.ctx = FakeToolContext()

    def tearDown(self):
        agent.artifact_store = self._orig

    def _run(self, coro):
        return asyncio.run(coro)

    def test_image_wrapper_auto_persists_full_url(self):
        async def raw(**kwargs):
            return {"status": "success", "success_list": [{"男主定妆照.png": _IMG_URL}]}

        wrapped = agent._wrap_with_model_fallback(
            raw, primary_model="p", fallback_models=[], kind="图片生成")
        res = self._run(wrapped(tool_context=self.ctx))
        self.assertEqual(res["status"], "success")
        app, user, sess = agent._draft_ids(self.ctx)
        saved = agent.artifact_store.list(app_name=app, user_id=user,
                                          session_id=sess, kind="image")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["url"], _IMG_URL)  # 完整 URL 落盘

    def test_video_wrapper_auto_persists_full_url(self):
        async def raw(**kwargs):
            return {"status": "success", "success_list": [{"终幕.mp4": _VID_URL}]}

        wrapped = agent._wrap_with_model_fallback(
            raw, primary_model="p", fallback_models=[], kind="视频生成")
        res = self._run(wrapped(tool_context=self.ctx))
        app, user, sess = agent._draft_ids(self.ctx)
        saved = agent.artifact_store.list(app_name=app, user_id=user,
                                          session_id=sess, kind="video")
        self.assertEqual(saved[0]["url"], _VID_URL)

    def test_failed_generation_persists_nothing(self):
        async def raw(**kwargs):
            return {"status": "error", "error_list": ["InvalidParameter"]}

        wrapped = agent._wrap_with_model_fallback(
            raw, primary_model="p", fallback_models=[], kind="图片生成")
        self._run(wrapped(tool_context=self.ctx))
        app, user, sess = agent._draft_ids(self.ctx)
        self.assertEqual(
            agent.artifact_store.stats(app_name=app, user_id=user, session_id=sess)["total"], 0
        )


if __name__ == "__main__":
    unittest.main()
