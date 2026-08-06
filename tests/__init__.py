# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""Unit tests for the film-director-agent (VeADK Agent + Web UI BFF).

Covers the features exposed by the agent and Web UI, including:
- long-script incremental drafting -> server-side PDF/Word assembly
  (the core fix for single-turn MAX_TOKENS), document store & stats;
- local-knowledge save/search;
- single-turn output budget guard + automatic continuation callbacks;
- forbidden retrieval-tool blocking;
- image/video model primary + fallback wrapper;
- document tool input validation;
- Web UI BFF: target config ("云端 Agent"), SSE chunk extraction, generated
  media/doc file extraction (image / video / doc), /api/file path guard;
- sandbox file reader path guard & marker parsing.

Run: uv run python -m unittest discover -s tests -v
"""
