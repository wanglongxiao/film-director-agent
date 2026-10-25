"""Shared work titles, including deterministic recovery for older tasks."""
from __future__ import annotations

import re

GENERIC = {"故事正文", "小说正文", "電影劇本", "电影剧本", "Story manuscript",
           "Manuscript", "物語本文", "이야기 본문"}


def clean_title(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().strip("#*「」『』《》\"“” ").strip()
    return value if value and value.casefold() not in {s.casefold() for s in GENERIC} else ""


def explicit_title(text: str) -> str:
    """Only labelled work titles; incidental book references are not titles."""
    match = re.search(
        r"(?:剧本(?:的)?(?:题目|标题|名称)|作品(?:名称|标题)|小说(?:名|标题)|书名|"
        r"故事(?:标题|名称)|(?<!章)(?:题目|标题)|(?i:book title|story title|title))"
        r"\s*[*：:]*\s*[《「『“\"]([^》」』”\"\n]{1,100})[》」』”\"]", text,
    )
    if not match:
        match = re.search(
            r"(?m)^\s*[#*\s]*(?:剧本标题|作品名称|书名|题目|标题|(?i:title))"
            r"\s*[:：]\s*([^\n]{1,100})", text,
        )
    return clean_title(match.group(1)) if match else ""


def recover_title(state: dict, history: list[dict] | None = None) -> str:
    book = state.get("novel") or {}
    title = clean_title(state.get("title")) or clean_title(book.get("title"))
    if title:
        return title
    # A user's latest explicit naming instruction takes precedence.
    for role in ("user", "assistant"):
        for message in reversed(history or []):
            if message.get("role") == role:
                title = explicit_title(message.get("content", ""))
                if title:
                    return title
    title = explicit_title(state.get("outline", ""))
    if title:
        return title
    chapters = book.get("chapters") or state.get("discussion_chapters") or []
    opening = clean_title(chapters[0].get("title")) if chapters else ""
    characters = state.get("characters") or []
    protagonist = next((c.get("name", "") for c in characters
                        if c.get("role") in ("protagonist", "主角", "主人公")), "")
    protagonist = protagonist or (characters[0].get("name", "") if characters else "")
    if opening:
        return f"{protagonist}：{opening}" if protagonist else opening
    if protagonist:
        return f"{protagonist} · {state.get('genre') or state.get('tone') or '故事'}"
    background = re.split(r"[\n。！？.!?]", state.get("background", ""))[0].strip()
    return background[:40]


def repair_document(doc: dict) -> bool:
    state = doc["state"]
    title = recover_title(state, doc.get("history"))
    if not title:
        return False
    changed = state.get("title") != title
    state["title"] = title
    if state.get("novel") and state["novel"].get("title") != title:
        state["novel"]["title"] = title
        changed = True
    return changed
