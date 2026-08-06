# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Shared test helpers: lightweight fakes for ADK session / tool / callback context.

These fakes mirror only the attributes the code under test actually reads, so the
unit tests stay fast and offline (no ADK Runner, no network, no sandbox)."""

from __future__ import annotations

import os
import sys

# Make `webui/*.py` importable as top-level modules (server.py does `import sandbox_files`).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEBUI_DIR = os.path.join(_REPO_ROOT, "webui")
for _p in (_REPO_ROOT, _WEBUI_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class FakeSession:
    def __init__(self, app_name="test_app", session_id="sess-1"):
        self.app_name = app_name
        self.id = session_id


class FakeInvocationContext:
    """Mirrors the `_invocation_context` fields read by document_tools._sandbox_session_id."""

    def __init__(self, agent_name="movie_script_agent", user_id="u1", session=None):
        self.agent = type("Agent", (), {"name": agent_name})()
        self.user_id = user_id
        self.session = session or FakeSession()


class FakeToolContext:
    """Mirrors google.adk.tools.ToolContext fields used by the agent tools."""

    def __init__(self, app_name="test_app", user_id="u1", session_id="sess-1",
                 agent_name="movie_script_agent"):
        self.session = FakeSession(app_name, session_id)
        self.user_id = user_id
        self.state = {}
        self.invocation_id = "inv-1"
        self._invocation_context = FakeInvocationContext(
            agent_name=agent_name, user_id=user_id, session=self.session
        )


class FakeCallbackContext:
    """Mirrors the CallbackContext fields read by the budget-guard callbacks."""

    def __init__(self, app_name="test_app", user_id="u1", session_id="sess-1",
                 invocation_id="inv-1", user_text=""):
        self.session = FakeSession(app_name, session_id)
        self.user_id = user_id
        self.invocation_id = invocation_id
        self.state = {}
        self.user_content = _content_from_text(user_text) if user_text else None


def _content_from_text(text):
    from google.genai import types
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])
