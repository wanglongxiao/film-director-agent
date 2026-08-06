# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Unit tests for the agent tools, callbacks and generation wrappers.

Covers the agent-side building blocks behind the product features:
- 长文档增量草稿工具（draft_reset / add_section / add_image / status / build_document）
  —— 图文混排 PDF/Word 长剧本生成的关键工作流；
- 本地知识 save/search 工具；
- 单轮输出预算护栏 + 自动续写回调（before/after/on_error），即 agent 的自动化 long-run；
- 严禁触发检索链路（禁用工具剥离）；
- 图片/视频「主模型 + 模型相关错误自动降级」包装器（一致性生成的稳定性保障）；
- root_agent 工具注册完整性。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

import tests._helpers as helpers  # noqa: F401  (ensures sys.path setup)
from tests._helpers import FakeToolContext, FakeCallbackContext

import assistant.agent as agent
from assistant.document_draft_store import DocumentDraftStore
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class _DraftToolsTestBase(unittest.TestCase):
    """Rebinds the module-level draft store to a throwaway temp sqlite per test."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._orig_store = agent.document_draft_store
        agent.document_draft_store = DocumentDraftStore(db_path=self.tmp.name)
        self.ctx = FakeToolContext()

    def tearDown(self):
        agent.document_draft_store = self._orig_store
        os.unlink(self.tmp.name)


class DraftWorkflowToolTest(_DraftToolsTestBase):
    def test_missing_tool_context_returns_error(self):
        self.assertFalse(agent.draft_add_section("x", tool_context=None)["ok"])
        self.assertFalse(agent.draft_status(tool_context=None)["ok"])
        self.assertFalse(agent.draft_build_document("f.pdf", tool_context=None)["ok"])

    def test_add_section_rejects_empty(self):
        res = agent.draft_add_section("", title="", tool_context=self.ctx)
        self.assertFalse(res["ok"])

    def test_incremental_flow_updates_status(self):
        agent.draft_reset(tool_context=self.ctx)
        agent.draft_add_section("第一场戏……", title="第一幕", tool_context=self.ctx)
        agent.draft_add_image("http://cdn/shot1.png", caption="分镜1", tool_context=self.ctx)
        res = agent.draft_add_section("第二场戏……", tool_context=self.ctx)
        self.assertTrue(res["ok"])
        self.assertEqual(res["seq"], 3)
        stats = agent.draft_status(tool_context=self.ctx)["stats"]
        self.assertEqual(stats["sections"], 2)
        self.assertEqual(stats["images"], 1)

    def test_add_image_rejects_empty_url(self):
        self.assertFalse(agent.draft_add_image("", tool_context=self.ctx)["ok"])

    def test_reset_clears_previous_document(self):
        agent.draft_add_section("旧内容", tool_context=self.ctx)
        out = agent.draft_reset(tool_context=self.ctx)
        self.assertTrue(out["ok"])
        self.assertEqual(out["deleted"], 1)
        self.assertEqual(agent.draft_status(tool_context=self.ctx)["stats"]["total_items"], 0)

    def test_build_document_on_empty_draft_errors(self):
        res = agent.draft_build_document("empty.pdf", tool_context=self.ctx)
        self.assertFalse(res["ok"])
        self.assertIn("empty", res["error"])

    def test_build_document_assembles_and_delegates_to_create_document(self):
        # Stub create_document (sandbox) — assert the assembled HTML is what gets passed,
        # proving the LLM never re-emits the long body at build time.
        captured = {}

        def fake_create_document(*, doc_format, filename, content, title, tool_context):
            captured.update(doc_format=doc_format, filename=filename,
                            content=content, title=title)
            return {"ok": True, "path": "/home/gem/veadk_docs/" + filename,
                    "fmt": doc_format, "size_bytes": 1234}

        import assistant.document_tools as doctools
        orig = doctools.create_document
        doctools.create_document = fake_create_document
        try:
            agent.draft_add_section("# 场景\n- 主角登场", title="第一幕", tool_context=self.ctx)
            agent.draft_add_image("http://cdn/k.png", caption="关键镜头", tool_context=self.ctx)
            res = agent.draft_build_document("霓虹之眼.pdf", doc_format="pdf",
                                             title="霓虹之眼", tool_context=self.ctx)
        finally:
            doctools.create_document = orig

        self.assertTrue(res["ok"])
        self.assertEqual(res["draft_id"], "default")
        self.assertEqual(res["assembled_from"]["sections"], 1)
        self.assertEqual(res["assembled_from"]["images"], 1)
        # Server-side assembled HTML carries both the script text and the image.
        self.assertIn("第一幕", captured["content"])
        self.assertIn("http://cdn/k.png", captured["content"])
        self.assertEqual(captured["doc_format"], "pdf")

    def test_build_document_normalizes_bad_format_to_pdf(self):
        import assistant.document_tools as doctools
        orig = doctools.create_document
        doctools.create_document = lambda **kw: {"ok": True, "fmt": kw["doc_format"],
                                                 "path": "/home/gem/veadk_docs/x"}
        try:
            agent.draft_add_section("a", tool_context=self.ctx)
            res = agent.draft_build_document("x.bogus", doc_format="rtf",
                                             tool_context=self.ctx)
        finally:
            doctools.create_document = orig
        self.assertEqual(res["fmt"], "pdf")


class LocalKnowledgeToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        from assistant.local_knowledge_store import LocalKnowledgeStore
        self._orig = agent.local_knowledge_store
        agent.local_knowledge_store = LocalKnowledgeStore(db_path=self.tmp.name)
        self.ctx = FakeToolContext()

    def tearDown(self):
        agent.local_knowledge_store = self._orig
        os.unlink(self.tmp.name)

    def test_save_then_search_roundtrip(self):
        saved = agent.save_local_knowledge("世界观", "故事发生在 2099 年的新东京", tool_context=self.ctx)
        self.assertTrue(saved["ok"])
        found = agent.search_local_knowledge("新东京", tool_context=self.ctx)
        self.assertTrue(found["ok"])
        self.assertEqual(len(found["results"]), 1)

    def test_tools_require_context(self):
        self.assertFalse(agent.save_local_knowledge("t", "c")["ok"])
        self.assertFalse(agent.search_local_knowledge("q")["ok"])


class BudgetGuardCallbackTest(unittest.TestCase):
    def test_before_model_sets_default_output_budget(self):
        cc = FakeCallbackContext(user_text="帮我写一个赛博朋克短剧")
        req = LlmRequest()
        agent._before_model_budget_guard(cc, req)
        self.assertEqual(req.config.max_output_tokens, agent._DEFAULT_MAX_OUTPUT_TOKENS)

    def test_before_model_uses_smaller_continuation_budget_on_continue(self):
        cc = FakeCallbackContext(user_text="继续")
        req = LlmRequest()
        agent._before_model_budget_guard(cc, req)
        self.assertEqual(req.config.max_output_tokens,
                         agent._CONTINUATION_MAX_OUTPUT_TOKENS)

    def test_before_model_never_raises_existing_lower_budget(self):
        cc = FakeCallbackContext(user_text="写点东西")
        req = LlmRequest()
        req.config.max_output_tokens = 500  # caller already set a tighter cap
        agent._before_model_budget_guard(cc, req)
        self.assertEqual(req.config.max_output_tokens, 500)

    def test_is_continue_request_detection(self):
        self.assertTrue(agent._is_continue_request("继续"))
        self.assertTrue(agent._is_continue_request("继续第2部分"))
        self.assertFalse(agent._is_continue_request("请写一个新的故事"))


class AfterModelTruncationGuardTest(unittest.TestCase):
    def _resp(self, text, *, finish_reason=None, error_code=None, partial=None):
        return LlmResponse(
            content=types.Content(role="model",
                                  parts=[types.Part.from_text(text=text)]),
            finish_reason=finish_reason,
            error_code=error_code,
            partial=partial,
        )

    def _cont_store(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        from assistant.continuation_store import ContinuationStore
        return ContinuationStore(db_path=tmp.name)

    def setUp(self):
        self._orig = agent.continuation_store
        agent.continuation_store = self._cont_store()

    def tearDown(self):
        agent.continuation_store = self._orig

    def test_partial_chunk_is_passed_through(self):
        cc = FakeCallbackContext()
        out = agent._after_model_truncation_guard(cc, self._resp("part", partial=True))
        self.assertIsNone(out)  # partial -> no rewrite

    def test_normal_completion_saves_checkpoint_and_returns_none(self):
        cc = FakeCallbackContext()
        out = agent._after_model_truncation_guard(
            cc, self._resp("最终答案", finish_reason="STOP"))
        self.assertIsNone(out)
        self.assertFalse(cc.state["temp:last_output_truncated"])
        self.assertFalse(cc.state["temp:auto_continue_active"])

    def test_max_tokens_triggers_auto_continue_function_call(self):
        cc = FakeCallbackContext()
        out = agent._after_model_truncation_guard(
            cc, self._resp("被截断的长文本", finish_reason="MAX_TOKENS"))
        self.assertIsNotNone(out)
        # error code is cleared so the run is not treated as failed
        self.assertIsNone(out.error_code)
        self.assertTrue(cc.state["temp:auto_continue_active"])
        self.assertEqual(cc.state["temp:auto_continue_count"], 1)
        names = [getattr(p.function_call, "name", None)
                 for p in out.content.parts if getattr(p, "function_call", None)]
        self.assertIn("auto_continue_generation", names)

    def test_auto_continue_stops_after_max_steps(self):
        cc = FakeCallbackContext()
        # Establish request state first (otherwise the counter is reset to 0 on the
        # first checkpoint of a new invocation), then pretend we've already auto-
        # continued MAX_STEPS times so this turn crosses the limit.
        agent._ensure_request_state(cc)
        cc.state["temp:auto_continue_count"] = agent._AUTO_CONTINUE_MAX_STEPS
        out = agent._after_model_truncation_guard(
            cc, self._resp("还在截断", finish_reason="MAX_TOKENS"))
        self.assertIsNotNone(out)
        self.assertFalse(cc.state["temp:auto_continue_active"])
        self.assertTrue(out.custom_metadata.get("auto_continue_limit_reached"))
        # No further auto_continue function-call is emitted; a user-facing notice is added.
        text = "".join(p.text for p in out.content.parts if getattr(p, "text", None))
        self.assertIn("输出已截断", text)

    def test_forbidden_retrieval_tool_call_is_stripped(self):
        cc = FakeCallbackContext()
        resp = LlmResponse(content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(
                id="c1", name="load_knowledgebase", args={}))],
        ))
        out = agent._after_model_truncation_guard(cc, resp)
        self.assertIsNotNone(out)
        self.assertTrue(out.custom_metadata.get("forbidden_retrieval_tool_call_blocked"))
        self.assertIn("load_knowledgebase", out.custom_metadata.get("blocked_tools", []))
        remaining = [getattr(p.function_call, "name", None)
                     for p in out.content.parts if getattr(p, "function_call", None)]
        self.assertNotIn("load_knowledgebase", remaining)


class OnModelErrorGuardTest(unittest.TestCase):
    def test_max_tokens_exception_is_converted_to_continuable_response(self):
        cc = FakeCallbackContext()
        out = agent._on_model_error_budget_guard(
            cc, LlmRequest(), RuntimeError("hit MAX_TOKENS limit"))
        self.assertIsInstance(out, LlmResponse)
        self.assertTrue(cc.state["temp:last_output_can_continue"])

    def test_non_max_tokens_error_is_not_handled(self):
        cc = FakeCallbackContext()
        out = agent._on_model_error_budget_guard(
            cc, LlmRequest(), ValueError("some other failure"))
        self.assertIsNone(out)


class ModelFallbackWrapperTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_success_on_primary_keeps_result_clean(self):
        calls = []

        async def raw(**kwargs):
            calls.append(kwargs["model_name"])
            return {"status": "success", "success_list": [{"a.png": "http://x/a.png"}]}

        wrapped = agent._wrap_with_model_fallback(
            raw, primary_model="primary", fallback_models=["fb1"], kind="图片生成")
        res = self._run(wrapped())
        self.assertEqual(res["status"], "success")
        self.assertEqual(calls, ["primary"])  # never fell back
        self.assertNotIn("model_downgrade_note", res)

    def test_model_related_error_triggers_downgrade(self):
        calls = []

        async def raw(**kwargs):
            calls.append(kwargs["model_name"])
            if kwargs["model_name"] == "primary":
                return {"status": "error", "error_list": ["ModelNotOpen: 未开通"]}
            return {"status": "success", "success_list": [{"a.png": "http://x/a.png"}]}

        wrapped = agent._wrap_with_model_fallback(
            raw, primary_model="primary", fallback_models=["fb1"], kind="图片生成")
        res = self._run(wrapped())
        self.assertEqual(res["status"], "success")
        self.assertEqual(calls, ["primary", "fb1"])
        self.assertEqual(res["model_used"], "fb1")
        self.assertIn("降级", res["model_downgrade_note"])

    def test_non_model_error_does_not_downgrade(self):
        calls = []

        async def raw(**kwargs):
            calls.append(kwargs["model_name"])
            return {"status": "error", "error_list": ["InvalidParameter: bad size"]}

        wrapped = agent._wrap_with_model_fallback(
            raw, primary_model="primary", fallback_models=["fb1", "fb2"], kind="图片生成")
        res = self._run(wrapped())
        self.assertEqual(res["status"], "error")
        self.assertEqual(calls, ["primary"])  # parameter error -> no fallback

    def test_is_model_related_error_helpers(self):
        self.assertTrue(agent._is_model_related_error(
            {"status": "error", "error": "AccessDenied"}))
        self.assertFalse(agent._is_model_related_error(
            {"status": "error", "success_list": [{"a": "b"}], "error": "ModelNotOpen"}))
        self.assertFalse(agent._is_model_related_error({"status": "success"}))


class AgentRegistrationTest(unittest.TestCase):
    def test_root_agent_registers_all_feature_tools(self):
        names = {getattr(t, "__name__", getattr(t, "name", "")) for t in agent.root_agent.tools}
        for expected in (
            "image_generate", "video_generate",          # 定妆照/场景图/分镜图 & 小样视频
            "create_document", "read_document",           # 图文混排 pdf/word
            "save_local_knowledge", "search_local_knowledge",
            "draft_add_section", "draft_add_image",       # 长文档增量草稿
            "draft_status", "draft_reset", "draft_build_document",
            "auto_continue_generation",                   # 自动化 long-run
        ):
            self.assertIn(expected, names, f"missing tool: {expected}")
        self.assertEqual(agent.root_agent.name, "movie_script_agent")


if __name__ == "__main__":
    unittest.main()
