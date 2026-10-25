"""Plan a complete book, then stream chapters with bounded continuity context."""
from __future__ import annotations

import json
import re
from typing import Callable

from . import llm
from .agent import CONTENT_POLICY, _extract_json
from .schemas import Chapter, Novel, NovelRequest, SessionState


def manuscript_length(text: str, language: str) -> int:
    """Count words for English; non-whitespace characters for CJK languages."""
    if language == "en":
        return len(re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", text))
    return len(re.sub(r"\s", "", text))


def story_context(state: SessionState) -> dict:
    return state.model_dump(exclude={"novel", "episodes", "stage"})


def novel_from_discussion(state: SessionState, request: NovelRequest) -> Novel | None:
    """Reuse the exact accepted chapter map without another planning LLM call."""
    if [c.number for c in state.discussion_chapters] != list(range(1, request.chapters_count + 1)):
        return None
    titles = {"zh-CN": "故事正文", "zh-TW": "故事正文", "en": "Story manuscript",
              "ja": "物語本文", "ko": "이야기 본문"}
    return Novel(
        title=titles.get(state.language, "Story manuscript"),
        chapters_count=request.chapters_count, chapter_length=request.chapter_length,
        chapters=[c.model_copy(update={"content": "", "summary": ""}, deep=True)
                  for c in state.discussion_chapters],
    )


def plan_novel(state: SessionState, request: NovelRequest, deadline=None) -> Novel:
    messages = [
        {"role": "system", "content": (
            "You are a novelist and screenwriter planning a COMPLETE novella. "
            "Return only JSON: {\"title\":\"book title\", \"chapters\":["
            "{\"number\":1,\"title\":\"chapter title\",\"synopsis\":\"detailed chapter plot\"}]}. "
            "Plan exactly the requested number of sequential chapters from 1. "
            "Each synopsis must specify events, character choices, consequences and clues. "
            "Honor the supplied outline, characters, style and rating; ensure enough plot for "
            "the target length, with escalating conflict, a climax and a resolved ending. "
            "The discussion requirements and chapter map are the main constraints. Preserve "
            "their core events and character arcs; creatively enrich scenes, motivations, "
            "dialogue and secondary developments without contradicting those requirements. "
            "The final chapter must resolve all major threads and character arcs. "
            "Write in the session language. Do not generate chapter prose yet.\n\n"
            + CONTENT_POLICY
        )},
        {"role": "user", "content": json.dumps({
            "story": story_context(state),
            "chapters_count": request.chapters_count,
            "target_length_per_chapter": request.chapter_length,
            "length_unit": "words" if state.language == "en" else "characters",
        }, ensure_ascii=False)},
    ]
    parsed = _extract_json(llm.chat(messages, model_key=state.text_model, deadline=deadline))
    if not parsed:
        raise ValueError("章节规划未返回有效 JSON，请重试。")
    chapters = [Chapter.model_validate(c) for c in parsed.get("chapters", [])]
    if len(chapters) != request.chapters_count or [c.number for c in chapters] != list(
        range(1, request.chapters_count + 1)
    ):
        raise ValueError("章节规划的数量或顺序不完整，请重试。")
    # Never trust prose or summaries in a planning response.
    for chapter in chapters:
        chapter.content = ""
        chapter.summary = ""
    return Novel(
        title=parsed.get("title", ""),
        chapters_count=request.chapters_count,
        chapter_length=request.chapter_length,
        chapters=chapters,
    )


def stream_chapter(state: SessionState, chapter: Chapter, should_stop: Callable[[], bool], deadline=None):
    """Emit prose deltas, then a validated completed chapter; never save fragments."""
    novel = state.novel
    if novel is None:
        raise ValueError("缺少章节规划。")
    previous = [c for c in novel.chapters if c.number < chapter.number and c.content]
    context = {
        "story": story_context(state),
        "book_title": novel.title,
        "chapter_plan": [
            {"number": c.number, "title": c.title, "synopsis": c.synopsis}
            for c in novel.chapters
        ],
        "previous_chapter_facts": [
            {"number": c.number, "summary": c.summary or c.synopsis} for c in previous
        ],
        "previous_chapter_ending": previous[-1].content[-8000:] if previous else "",
        "current_chapter": chapter.model_dump(exclude={"content", "summary"}),
        "target_length": novel.chapter_length,
        "chapters_count": novel.chapters_count,
        "length_unit": "words" if state.language == "en" else "characters",
        "final_chapter": chapter.number == novel.chapters_count,
    }
    messages = [
        {"role": "system", "content": (
            "Write ONE complete chapter of a literary novella that can be adapted into a film. "
            "Output only full narrative prose with paragraph breaks, no JSON, Markdown, "
            "headings, explanations or outline. Expand vivid scenes, sensory detail, "
            "physical action, natural dialogue, interior thoughts and character development. "
            "Follow the plan and established facts, relationships, chronology and clues. "
            "The discussion is the main source of story requirements, but you may invent "
            "compatible scene details, dialogue and secondary developments. Never add, "
            "remove or renumber chapters; the supplied chapter count is fixed. "
            "Do not summarize events instead of dramatizing them. Aim for the requested "
            "length; a brief synopsis is unacceptable. Use the session language and rating. "
            "End this chapter at a deliberate narrative beat. Only the last chapter resolves "
            "the entire story; it MUST deliver the climax's consequences and a full ending. "
            "After the entire chapter, put [[CHAPTER_END]] on a separate line.\n\n"
            + CONTENT_POLICY
        )},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]
    full_text = ""
    marker = "[[CHAPTER_END]]"
    for attempt in range(3):
        if should_stop():
            return
        pending = ""
        generated = ""
        truncated = False
        try:
            for delta in llm.chat_stream(
                messages, model_key=state.text_model, deadline=deadline
            ):
                if should_stop():
                    return
                generated += delta
                pending += delta
                # Keep a tail so the terminator never flashes in the reader.
                if len(pending) > len(marker) + 4:
                    visible = pending[: -(len(marker) + 4)]
                    pending = pending[-(len(marker) + 4):]
                    visible = visible.replace(marker, "")
                    full_text += visible
                    yield {"type": "chapter_delta", "number": chapter.number, "delta": visible}
        except llm.OutputTruncatedError:
            truncated = True
        pending = pending.replace(marker, "")
        full_text += pending
        if pending:
            yield {"type": "chapter_delta", "number": chapter.number, "delta": pending}
        full_text = full_text.replace(marker, "").strip()
        if not truncated and manuscript_length(full_text, state.language) >= novel.chapter_length * 0.8:
            completed = chapter.model_copy(deep=True)
            completed.content = full_text
            # Summarize actual prose, not just the intended plot, for future chapters.
            try:
                completed.summary = llm.chat([
                    {"role": "system", "content": (
                        "Summarize only established facts from this chapter for the next writer: "
                        "events, chronology, names, relationships, decisions, clues, unresolved "
                        "threads and the ending situation. No inventions. Use the text's language."
                    )},
                    {"role": "user", "content": full_text},
                ], temperature=0.2, max_tokens=2048, model_key=state.text_model, deadline=deadline)
            except Exception:
                # Exact final prose is also supplied to the next chapter.
                completed.summary = full_text[-3000:]
            if should_stop():
                return
            yield {"type": "chapter_complete", "chapter": completed}
            return
        messages.extend([
            {"role": "assistant", "content": generated.replace(marker, "")},
            {"role": "user", "content": (
                f"Continue this same chapter from the exact last sentence without repeating "
                f"existing text or adding a heading. It currently has "
                f"{manuscript_length(full_text, state.language)} {context['length_unit']}, "
                f"target {novel.chapter_length}. Fully develop the remaining scenes, "
                "then finish the chapter and emit [[CHAPTER_END]]."
            )},
        ])
        if attempt < 2:
            full_text += "\n\n"
            yield {"type": "chapter_delta", "number": chapter.number, "delta": "\n\n"}
    raise ValueError(f"第 {chapter.number} 章未达到目标篇幅或输出被截断；已完成章节保留，可继续生成。")
