# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Unit tests for the three local sqlite stores.

- DocumentDraftStore   长文档「增量落盘 -> 服务端组装」的核心设施（图文混排 PDF/Word）。
- ContinuationStore    长任务自动续写的 checkpoint 存储。
- LocalKnowledgeStore  阶段性设定/素材的本地保存与检索。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from assistant.document_draft_store import (
    DocumentDraftStore,
    _section_body_to_html,
    _esc,
)
from assistant.continuation_store import ContinuationStore
from assistant.local_knowledge_store import LocalKnowledgeStore


_IDS = dict(app_name="app", user_id="u1", session_id="s1")


class DocumentDraftStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = DocumentDraftStore(db_path=self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_add_item_assigns_incrementing_seq_per_draft(self):
        s1 = self.store.add_item(**_IDS, draft_id="default", kind="section", body="A")
        s2 = self.store.add_item(**_IDS, draft_id="default", kind="section", body="B")
        # A separate draft_id keeps its own seq counter.
        other = self.store.add_item(**_IDS, draft_id="other", kind="section", body="X")
        self.assertEqual((s1, s2), (1, 2))
        self.assertEqual(other, 1)

    def test_stats_counts_sections_images_and_chars(self):
        self.store.add_item(**_IDS, draft_id="d", kind="section", body="hello")
        self.store.add_item(**_IDS, draft_id="d", kind="section", body="world!")
        self.store.add_item(**_IDS, draft_id="d", kind="image", url="http://x/a.png")
        stats = self.store.stats(**_IDS, draft_id="d")
        self.assertEqual(stats["sections"], 2)
        self.assertEqual(stats["images"], 1)
        self.assertEqual(stats["total_items"], 3)
        self.assertEqual(stats["total_chars"], len("hello") + len("world!"))

    def test_clear_removes_only_target_draft(self):
        self.store.add_item(**_IDS, draft_id="keep", kind="section", body="k")
        self.store.add_item(**_IDS, draft_id="drop", kind="section", body="d")
        deleted = self.store.clear(**_IDS, draft_id="drop")
        self.assertEqual(deleted, 1)
        self.assertEqual(self.store.stats(**_IDS, draft_id="drop")["total_items"], 0)
        self.assertEqual(self.store.stats(**_IDS, draft_id="keep")["total_items"], 1)

    def test_assemble_html_interleaves_text_and_images_in_order(self):
        # 图文混排：先一段剧本，再插一张分镜图，再一段剧本，验证顺序被保留。
        self.store.add_item(**_IDS, draft_id="d", kind="section",
                            title="第一幕", body="# 场景一\n- 主角登场")
        self.store.add_item(**_IDS, draft_id="d", kind="image",
                            url="http://cdn/keyshot.png", caption="关键镜头小样")
        self.store.add_item(**_IDS, draft_id="d", kind="section", body="旁白：夜色降临。")
        html = self.store.assemble_html(**_IDS, draft_id="d", title="霓虹之眼")

        self.assertIn("<h1>霓虹之眼</h1>", html)
        self.assertIn("<h2>第一幕</h2>", html)
        self.assertIn('<img src="http://cdn/keyshot.png"', html)
        self.assertIn("<figcaption>关键镜头小样</figcaption>", html)
        # 顺序断言：小标题在图片之前，最后一段旁白在图片之后。
        self.assertLess(html.index("第一幕"), html.index("keyshot.png"))
        self.assertLess(html.index("keyshot.png"), html.index("旁白：夜色降临。"))

    def test_assemble_html_renders_pagebreak_and_empty_doc(self):
        empty = self.store.assemble_html(**_IDS, draft_id="none")
        self.assertIn("(空文档)", empty)
        self.store.add_item(**_IDS, draft_id="p", kind="pagebreak")
        self.assertIn('<div class="page-break"></div>',
                      self.store.assemble_html(**_IDS, draft_id="p"))

    def test_assemble_skips_image_without_url(self):
        self.store.add_item(**_IDS, draft_id="d", kind="image", url="", caption="x")
        html = self.store.assemble_html(**_IDS, draft_id="d")
        self.assertNotIn("<img", html)


class SectionMarkdownTest(unittest.TestCase):
    def test_headings_bullets_and_paragraphs(self):
        html = _section_body_to_html("# 标题\n## 小标题\n- 要点1\n- 要点2\n普通段落")
        self.assertIn("<h2>标题</h2>", html)
        self.assertIn("<h3>小标题</h3>", html)
        self.assertIn("<ul>", html)
        self.assertEqual(html.count("<li>"), 2)
        self.assertIn("<p>普通段落</p>", html)

    def test_html_escaping_prevents_injection(self):
        self.assertEqual(_esc("<b>&</b>"), "&lt;b&gt;&amp;&lt;/b&gt;")
        html = _section_body_to_html("<script>alert(1)</script>")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class ContinuationStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = ContinuationStore(db_path=self.tmp.name)
        self.ids = dict(app_name="app", user_id="u1", session_id="s1", request_id="r1")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_save_and_assemble_orders_by_chunk_index(self):
        self.store.save_chunk(**self.ids, chunk_index=2, content="second", truncated=True)
        self.store.save_chunk(**self.ids, chunk_index=1, content="first", truncated=True)
        self.assertEqual(self.store.assemble_request(**self.ids), "first\nsecond")
        self.assertEqual(self.store.count_chunks(**self.ids), 2)

    def test_save_chunk_ignores_blank_content(self):
        self.store.save_chunk(**self.ids, chunk_index=1, content="   ", truncated=False)
        self.assertEqual(self.store.count_chunks(**self.ids), 0)

    def test_tail_chars_returns_suffix(self):
        self.store.save_chunk(**self.ids, chunk_index=1, content="abcdefghij", truncated=True)
        self.assertEqual(self.store.tail_chars(**self.ids, max_chars=3), "hij")
        self.assertEqual(self.store.tail_chars(**self.ids, max_chars=0), "abcdefghij")

    def test_get_latest_request_id(self):
        self.assertIsNone(self.store.get_latest_request_id(
            app_name="app", user_id="u1", session_id="s1"))
        self.store.save_chunk(**self.ids, chunk_index=1, content="x", truncated=True)
        self.assertEqual(
            self.store.get_latest_request_id(app_name="app", user_id="u1", session_id="s1"),
            "r1",
        )


class LocalKnowledgeStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = LocalKnowledgeStore(db_path=self.tmp.name)
        self.ids = dict(app_name="app", user_id="u1", session_id="s1")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_save_returns_id_and_search_finds_it(self):
        rid = self.store.save(**self.ids, title="主角小传", content="赛博朋克侦探，患有失忆症")
        self.assertIsInstance(rid, int)
        hits = self.store.search(**self.ids, query="失忆")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "主角小传")
        self.assertIn("赛博朋克", hits[0]["snippet"])

    def test_save_rejects_empty(self):
        self.assertIsNone(self.store.save(**self.ids, title="", content="x"))
        self.assertIsNone(self.store.save(**self.ids, title="t", content="  "))

    def test_search_empty_query_and_limit_clamped(self):
        self.assertEqual(self.store.search(**self.ids, query="  "), [])
        for i in range(30):
            self.store.save(**self.ids, title=f"t{i}", content="共同关键词 kw")
        # limit is clamped to 20 max even if a larger value is requested.
        self.assertEqual(len(self.store.search(**self.ids, query="kw", limit=100)), 20)

    def test_search_is_scoped_by_session(self):
        self.store.save(**self.ids, title="a", content="scoped kw")
        other = dict(app_name="app", user_id="u1", session_id="OTHER")
        self.assertEqual(self.store.search(**other, query="kw"), [])


if __name__ == "__main__":
    unittest.main()
