# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Unit tests for assistant/document_tools.py.

Only the offline-safe surface is exercised: input validation of create_document /
read_document (which reject bad input before any sandbox call) and the sandbox
session-id derivation contract that keeps generated files reachable across turns.
"""

from __future__ import annotations

import os
import unittest

import tests._helpers  # noqa: F401
from tests._helpers import FakeToolContext

import assistant.document_tools as doctools


class CreateDocumentValidationTest(unittest.TestCase):
    def test_unsupported_format_rejected(self):
        res = doctools.create_document("rtf", "a.rtf", "content")
        self.assertFalse(res["ok"])
        self.assertIn("unsupported", res["error"])

    def test_empty_content_and_title_rejected(self):
        res = doctools.create_document("pdf", "a.pdf", "", title=None)
        self.assertFalse(res["ok"])

    def test_supported_formats_pass_validation(self):
        # Stub the sandbox runner so validation-passing calls don't touch the network.
        orig = doctools._run_doc_script
        doctools._run_doc_script = lambda params, tc: {"ok": True, "echo": params}
        try:
            for fmt in ("docx", "pdf", "pptx", "html"):
                res = doctools.create_document(fmt, "f", "some body")
                self.assertTrue(res["ok"], fmt)
                self.assertEqual(res["echo"]["fmt"], fmt)
                self.assertEqual(res["echo"]["action"], "create")
        finally:
            doctools._run_doc_script = orig


class ReadDocumentValidationTest(unittest.TestCase):
    def test_empty_path_rejected(self):
        self.assertFalse(doctools.read_document("")["ok"])

    def test_bad_format_rejected(self):
        self.assertFalse(doctools.read_document("a.pdf", doc_format="rtf")["ok"])

    def test_valid_read_delegates_to_sandbox(self):
        orig = doctools._run_doc_script
        doctools._run_doc_script = lambda params, tc: {"ok": True, "action": params["action"]}
        try:
            res = doctools.read_document("/home/gem/veadk_docs/a.pdf")
        finally:
            doctools._run_doc_script = orig
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "read")


class SandboxSessionIdTest(unittest.TestCase):
    def test_session_id_derivation_matches_contract(self):
        ctx = FakeToolContext(user_id="u9", session_id="sX", agent_name="movie_script_agent")
        # sandbox_files derives the same "{agent}_{user}_{session}" — they must agree
        # so BFF can read files the agent wrote.
        self.assertEqual(
            doctools._sandbox_session_id(ctx), "movie_script_agent_u9_sX")

    def test_session_id_fallback_without_context(self):
        os.environ.pop("VEADK_DOC_TOOLS_SESSION", None)
        self.assertEqual(doctools._sandbox_session_id(None), "veadk-doc-tools")


if __name__ == "__main__":
    unittest.main()
