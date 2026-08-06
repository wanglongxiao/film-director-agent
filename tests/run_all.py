#!/usr/bin/env python
# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Run the full offline unit-test suite for the film-director-agent.

Usage:
    uv run python tests/run_all.py          # normal
    uv run python tests/run_all.py -q       # quiet

Sets throwaway sqlite DB paths and quiets VeADK import logging so the run is
fast, deterministic and needs no network / credentials.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest

# Isolate all sqlite stores into a temp dir (module-level default paths read these).
_TMP = tempfile.mkdtemp(prefix="director-agent-tests-")
os.environ.setdefault("VEADK_DOC_DRAFT_DB_PATH", os.path.join(_TMP, "draft.db"))
os.environ.setdefault("VEADK_OUTPUT_MEMORY_DB_PATH", os.path.join(_TMP, "cont.db"))
os.environ.setdefault("VEADK_LOCAL_KB_DB_PATH", os.path.join(_TMP, "kb.db"))
os.environ.setdefault("VEADK_ARTIFACT_DB_PATH", os.path.join(_TMP, "artifacts.db"))
# Keep assemble_html offline & deterministic: don't hit the network to inline images.
os.environ.setdefault("VEADK_DOC_INLINE_IMAGES", "0")
# Keep Web UI tests in local-mode by default; password gate is covered explicitly
# in dedicated tests that monkeypatch module globals.
os.environ.setdefault("WEBUI_ENABLE_LOCAL", "true")
os.environ.setdefault("WEBUI_ACCESS_PASSWORD", "")

# Quiet the noisy VeADK import-time logging (keep only warnings+).
logging.getLogger("veadk").setLevel(logging.WARNING)
logging.disable(logging.INFO)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "webui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main() -> int:
    verbosity = 1 if "-q" in sys.argv else 2
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=_HERE, pattern="test_*.py", top_level_dir=_ROOT)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
