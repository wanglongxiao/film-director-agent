# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Unit tests for webui/sandbox_files.py (reading Agent-generated docs from the sandbox).

Focus on the parts that are safe to test offline:
- credential / tool-id guards (no network attempted when unset);
- the sandbox session-id derivation contract (must match document_tools);
- stdout marker extraction from an InvokeTool response envelope.
"""

from __future__ import annotations

import base64
import json
import os
import unittest

import tests._helpers  # noqa: F401  (sys.path setup)
import sandbox_files


class ReadSandboxFileGuardTest(unittest.TestCase):
    def setUp(self):
        # Snapshot & clear the credential env so guard paths are deterministic.
        self._saved = {k: os.environ.pop(k, None) for k in (
            "VOLCENGINE_ACCESS_KEY", "VOLCENGINE_SECRET_KEY",
            "AGENTKIT_TOOL_ID_SCRIPT", "AGENTKIT_TOOL_ID")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_missing_credentials_returns_error_without_network(self):
        res = sandbox_files.read_sandbox_file(
            path="/home/gem/veadk_docs/a.pdf",
            agent_name="movie_script_agent", user_id="u1", session_id="s1")
        self.assertFalse(res["ok"])
        self.assertIn("ACCESS_KEY", res["error"])

    def test_missing_tool_id_returns_error(self):
        os.environ["VOLCENGINE_ACCESS_KEY"] = "ak"
        os.environ["VOLCENGINE_SECRET_KEY"] = "sk"
        res = sandbox_files.read_sandbox_file(
            path="/home/gem/veadk_docs/a.pdf",
            agent_name="movie_script_agent", user_id="u1", session_id="s1")
        self.assertFalse(res["ok"])
        self.assertIn("TOOL_ID", res["error"])

    def test_path_outside_doc_dir_rejected(self):
        os.environ["VOLCENGINE_ACCESS_KEY"] = "ak"
        os.environ["VOLCENGINE_SECRET_KEY"] = "sk"
        os.environ["AGENTKIT_TOOL_ID_SCRIPT"] = "tool-x"
        res = sandbox_files.read_sandbox_file(
            path="/etc/passwd",
            agent_name="movie_script_agent", user_id="u1", session_id="s1")
        self.assertFalse(res["ok"])
        self.assertIn("not allowed", res["error"])


class ExtractMarkerTest(unittest.TestCase):
    def _envelope(self, stdout_text):
        # Mirror the AgentKit InvokeTool -> RunCode response shape.
        inner = {"data": {"outputs": [{"text": stdout_text}]}}
        return {"Result": {"Result": json.dumps(inner)}}

    def test_extracts_marker_json_line(self):
        payload = {"ok": True, "path": "/home/gem/veadk_docs/a.pdf", "size": 3,
                   "b64": base64.b64encode(b"abc").decode()}
        env = self._envelope("noise\nFILE_B64_JSON:" + json.dumps(payload) + "\nmore")
        out = sandbox_files._extract_marker(env, "FILE_B64_JSON:")
        self.assertTrue(out["ok"])
        self.assertEqual(out["size"], 3)

    def test_missing_marker_returns_none(self):
        env = self._envelope("just some output, no marker")
        self.assertIsNone(sandbox_files._extract_marker(env, "FILE_B64_JSON:"))

    def test_api_error_envelope_raises(self):
        err = {"ResponseMetadata": {"Error": {"Code": "AccessDenied", "Message": "no"}}}
        with self.assertRaises(RuntimeError):
            sandbox_files._extract_marker(err, "FILE_B64_JSON:")


if __name__ == "__main__":
    unittest.main()
