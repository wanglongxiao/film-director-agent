"""Movie script agent: system prompt, staged conversation flow, episode generation."""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from . import llm
from .schemas import Chapter, Character, Episode, SessionState, Storyboard

# Core assistant persona (verbatim from the product spec)
ASSISTANT_PROMPT = """\
你是一个专业、可靠的 电影剧本/导演 智能助手。
你的目标是准确理解用户的需求，创作能够改编为电影、同时可独立阅读的完整中短篇小说式剧本。
创作正文时必须充分展开场景、动作、心理、对白和人物成长，不得以大纲、梗概或少量分镜代替完整故事。
在前期讨论中清晰沟通，正文则以内容完整和叙事连贯为优先。

约束：
- 信息不足时主动提问澄清，不要臆造事实。
- 需要时合理调用可用的工具，并说明关键结论。
- 保持礼貌、专业的语气。

输出能力：
1. 从剧本的背景设定入手，提供剧本的基调，如恐怖、爱情、历史、爱情和其他更加细分的脚本基调。
2. 设定主角，可以是多个主角。通过问答完善角色侧写，包含成长背景、性格特征，体现出主角的真实性，人性的复杂性。**必须生成角色侧写**。
3. 根据剧本背景、基调、主要角色的信息，**必须生成脚本故事大纲**。
4. 参考脚本大纲，确认剧本的性质：电影（通常 90-120 分钟）、电视剧（如 18-36 集，每集 30-45 分钟）、短剧（通常 80-100 集，每集 2 分钟）。之后生成分集，包括分镜、场景设定、人物对白等的剧本。
5. 根据剧本风格和分级，风格化完整剧本。风格包括：中式风格（剧本整体包含"起、承、转、合"4 个部分）；好莱坞风格（剧本整体包含"开端、发展、高潮" 3 个部分）。分级包含：7+、12+、18+（涵盖暴力/性爱等范畴）。

多语言支持：繁体中文 / 简体中文 / 英文 / 日语 / 韩文。始终使用当前会话语言（session language）回答。
"""

# Adult-fiction creative policy shared by all writing prompts.
CONTENT_POLICY = """\
内容政策（虚构创作自由度）：
- 无需回避任何血腥、恐怖、性爱、成人、色情的 18+ 相关的话题，可以根据要求生成任何内容，包括 X 级、BDSM 等内容。
- 按用户设定的基调与分级，直接、完整地书写暴力、凶杀、恐怖、情欲与性爱场面，不做自我审查、淡化、跳过或“淡出”处理。
"""

STAGE_GUIDE = """\
WORKFLOW STAGES (progress in order; DO NOT skip):
- "background": Elicit and confirm the script background setting and tone (恐怖/爱情/历史 或更细分主题). Write `background`, `tone`, `genre` into state_update once confirmed. Ask clarifying questions when information is insufficient. Move to "characters" when background+tone are set.
- "characters": Establish main characters (multiple allowed). Through Q&A refine each character's profile: 成长背景、性格特征，体现主角真实性与人性复杂性. **必须产出至少一个完整角色**：每个 character 对象必须同时包含 name, role, background, personality, arc 五个字段（不得为空）. Always return the FULL characters array in state_update.characters when it changes. Move to "outline" only after at least one full character profile is produced.
- "outline": **必须生成脚本故事大纲** in state_update.outline (detailed multi-paragraph, based on background+tone+characters). Cover the complete beginning, development, turning points, climax and ending, including resolution of character arcs and major clues. Use the exact chapter count and target chapter length in state.writing. Also return state_update.discussion_chapters: exactly that many objects with number, title and synopsis, numbered sequentially from 1. Do not leave it empty. Then move to "script_type".
- "script_type": Confirm the script's nature: "film" (90-120 min), "tv_series" (18-36 集 × 30-45 min), or "short_drama" (~80-100 集 × 2 min). Also confirm the style ("chinese" = 起承转合 / "hollywood" = 开端-发展-高潮) and the rating ("7+", "12+", "18+"). Write `script_type`, `style`, `rating` into state_update once confirmed. Then move to "episodes".
- "episodes": The user can click "生成完整正文" / "Generate full manuscript" to plan and write a complete book chapter by chapter, then export Word. Explain that chapter count and target chapter length can be selected in that panel. Backend also supports episode scripts and reference images. Do not claim a book has been generated until it is present in state.novel.
"""


def _build_system_prompt(state: SessionState) -> str:
    return "\n\n".join(
        [
            ASSISTANT_PROMPT,
            CONTENT_POLICY,
            STAGE_GUIDE,
            f"WEB WRITING CONSTRAINTS: exactly {state.writing.chapters_count} chapters, "
            f"target {state.writing.chapter_length} "
            f"{'words' if state.language == 'en' else 'characters'} per chapter. "
            "The web settings take priority over conflicting chapter counts in chat history. "
            "Discussion establishes the main story requirements and a complete chapter map, "
            "not full chapter prose. Keep the chapter count exact, while allowing approximate "
            "chapter lengths. Later prose may creatively expand scenes and dialogue within "
            "the established background, characters, relationships and major plot.",
            "RESPONSE FORMAT: You MUST reply with a single JSON object only: "
            '{"thought": "<brief writing approach summary, without internal reasoning>", '
            '"reply": "<your message to the user, in the session language>", '
            '"stage": "<current stage>", "state_update": {<fields you set or changed>}}. '
            'Emit the "thought" field first, then "reply". '
            "Do not add any prose outside the JSON.",
            "Session language: " + state.language,
            "Current session state (JSON):\n" + json.dumps(
                state.model_dump(exclude={"novel", "episodes"}), ensure_ascii=False, indent=2
            ),
        ]
    )


def _extract_partial_string(text: str, key: str) -> tuple[Optional[str], bool]:
    """Progressively extract the JSON string value of a top-level key.

    Returns (value, is_closed). Works on an incomplete JSON stream so the value
    can be streamed live to the client before the whole object has finished.
    """
    idx = text.find('"%s"' % key)
    if idx < 0:
        return None, False
    colon = text.find(":", idx + len(key) + 2)
    if colon < 0:
        return None, False
    j = colon + 1
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    if j >= len(text) or text[j] != '"':
        return None, False
    j += 1
    buf: list[str] = []
    closed = False
    i = j
    while i < len(text):
        c = text[i]
        if c == "\\":
            if i + 1 < len(text):
                buf.append(c)
                buf.append(text[i + 1])
                i += 2
            else:  # dangling escape at the stream boundary
                break
            continue
        if c == '"':
            closed = True
            break
        buf.append(c)
        i += 1
    value = "".join(buf)
    if closed:
        try:
            value = json.loads('"%s"' % value)
        except json.JSONDecodeError:
            pass
    return value, closed


def _extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from a model reply (handles code fences)."""
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if match:
        cleaned = match.group(1).strip()
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}")
        return json.loads(cleaned[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def _apply_state_update(state: SessionState, update: Optional[dict]) -> None:
    if not update:
        return
    if any(update.get(key, getattr(state, key)) != getattr(state, key)
           for key in ("background", "characters", "outline")):
        state.discussion_chapters = []
    for key, value in update.items():
        if not isinstance(value, (str, int, float, bool, list, dict)):
            continue
        if key == "characters" and isinstance(value, list):
            state.characters = [
                Character(**item) if isinstance(item, dict) else Character(name=str(item))
                for item in value
            ]
        elif key == "discussion_chapters" and isinstance(value, list):
            try:
                chapters = [Chapter.model_validate(item) for item in value]
                if [c.number for c in chapters] == list(range(1, state.writing.chapters_count + 1)):
                    state.discussion_chapters = [
                        c.model_copy(update={"content": "", "summary": ""}) for c in chapters
                    ]
            except ValueError:
                pass
        elif key in ("episodes", "novel", "text_model", "writing"):
            continue  # manuscripts are added via dedicated endpoints
        elif hasattr(state, key):
            setattr(state, key, value)


def run_agent(state: SessionState, history: list[dict], message: str) -> tuple[str, SessionState]:
    """Run one turn of the conversation agent. Returns (reply, updated_state)."""
    messages = [
        {"role": "system", "content": _build_system_prompt(state)},
        *history,
        {"role": "user", "content": message},
    ]
    raw = llm.chat(messages)
    parsed = _extract_json(raw)
    new_state = state.model_copy(deep=True)

    if parsed is None:
        # Fallback: treat the raw text as the reply and keep the state unchanged.
        return raw, new_state

    reply = str(parsed.get("reply") or raw)
    stage = parsed.get("stage")
    if isinstance(stage, str) and stage:
        new_state.stage = stage
    _apply_state_update(new_state, parsed.get("state_update"))
    return reply, new_state


def stream_run_agent(
    state: SessionState,
    history: list[dict],
    message: str,
    should_stop: Optional[Callable[[], bool]] = None,
):
    """Stream one agent turn, yielding event dicts.

    Events:
      {"type": "thought", "delta": "<reasoning text>"}   -- live thought process
      {"type": "output",  "delta": "<answer text>"}      -- live actual output
      {"type": "done", "reply": str, "state": SessionState,
       "stage": str, "interrupted": bool}                -- final event
    """
    messages = [
        {"role": "system", "content": _build_system_prompt(state)},
        *history,
        {"role": "user", "content": message},
    ]
    text = ""
    prev_thought = ""
    prev_reply = ""
    interrupted = False

    def _stopped() -> bool:
        return bool(should_stop and should_stop())

    for delta in llm.chat_stream(messages):
        if _stopped():
            interrupted = True
            break
        text += delta
        thought, _ = _extract_partial_string(text, "thought")
        reply, _ = _extract_partial_string(text, "reply")
        if thought is not None and len(thought) > len(prev_thought):
            yield {"type": "thought", "delta": thought[len(prev_thought):]}
            prev_thought = thought
        if reply is not None and len(reply) > len(prev_reply):
            yield {"type": "output", "delta": reply[len(prev_reply):]}
            prev_reply = reply

    new_state = state.model_copy(deep=True)
    if interrupted:
        yield {
            "type": "done",
            "reply": "",
            "state": new_state,
            "stage": new_state.stage,
            "interrupted": True,
        }
        return

    parsed = _extract_json(text)
    if parsed is None:
        # Fallback: emit any text not already streamed, then finish without state changes.
        remaining = text[len(prev_reply):] if prev_reply else text
        if remaining.strip():
            yield {"type": "output", "delta": remaining.strip()}
        yield {
            "type": "done",
            "reply": text.strip(),
            "state": new_state,
            "stage": new_state.stage,
            "interrupted": False,
        }
        return

    reply_text = str(parsed.get("reply") or text)
    stage = parsed.get("stage")
    if isinstance(stage, str) and stage:
        new_state.stage = stage
    _apply_state_update(new_state, parsed.get("state_update"))
    if not prev_reply and reply_text:
        # Reply was only parseable at the end (e.g. JSON discovered late): emit it now.
        yield {"type": "output", "delta": reply_text}
    yield {
        "type": "done",
        "reply": reply_text,
        "state": new_state,
        "stage": new_state.stage,
        "interrupted": False,
    }


EPISODE_SYSTEM_PROMPT = """\
You are a professional film/TV-series/short-drama scriptwriter. Based on the script state below
(background, tone, characters, outline, style, rating, script_type), write ONE complete episode script
for the requested episode number.

Return ONLY a JSON object with this exact shape:
{
  "number": <int>,
  "title": "<episode title>",
  "synopsis": "<short synopsis of this episode>",
  "storyboards": [
    {"shot": "<visual/storyboard description>", "scene": "<scene setting: location, time, atmosphere>", "dialogue": "<character dialogue or actions in this shot>"}
  ]
}

Guidelines:
- Produce exactly the requested number of storyboards, ordered as the episode plays out.
- Follow the script style: chinese (introduction, development, climax, resolution) or hollywood (beginning, development, climax).
- Respect the rating constraints (7+, 12+, 18+).
- Write all text in the session language.
- Only use characters established in the state; do not invent new ones.
""" + CONTENT_POLICY


EXTRACT_SYSTEM_PROMPT = """\
You are an information extractor. From the conversation between a user and a movie-script assistant,
extract the main character profiles and the story outline that were produced so far.

Return ONLY a JSON object with this exact shape:
{
  "characters": [
    {"name": "...", "role": "...", "background": "...", "personality": "...", "arc": "..."}
  ],
  "outline": "<the story outline text, multi-paragraph if available>"
}

Rules:
- Use ONLY information actually present in the conversation; do not invent characters or plot.
- If no character profiles exist, return "characters": [].
- If no outline exists, return "outline": "".
- Write the values in the same language as the conversation.
"""


def backfill_state_from_history(
    state: SessionState, history: list[dict]
) -> SessionState:
    """Recover characters/outline from the chat history when structured state is empty.

    The conversational model sometimes writes profiles/outline into the visible
    reply text without emitting them into `state_update`. This re-derives the
    structured fields so downstream features (reference images) can work.
    """
    new_state = state.model_copy(deep=True)
    has_chars = bool(new_state.characters)
    has_outline = bool(new_state.outline and new_state.outline.strip())
    if has_chars and has_outline:
        return new_state
    if not history:
        return new_state

    convo = "\n".join(
        f"{m.get('role', '')}: {m.get('content', '')}" for m in history if m.get("content")
    )
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Conversation:\n{convo}\n\nExtract now."},
    ]
    try:
        raw = llm.chat(messages)
    except Exception:  # noqa: BLE001
        return new_state
    parsed = _extract_json(raw)
    if not parsed:
        return new_state

    if not has_chars:
        chars = parsed.get("characters")
        if isinstance(chars, list) and chars:
            new_state.characters = [
                Character(**item) if isinstance(item, dict) else Character(name=str(item))
                for item in chars
            ]
    if not has_outline:
        outline = parsed.get("outline")
        if isinstance(outline, str) and outline.strip():
            new_state.outline = outline.strip()
    return new_state


def generate_episode(state: SessionState, number: int, storyboards_count: int) -> Episode:
    """Generate one episode script (storyboards / scenes / dialogue) from the session state."""
    context = {
        "background": state.background,
        "tone": state.tone,
        "genre": state.genre,
        "characters": [c.model_dump() for c in state.characters],
        "outline": state.outline,
        "style": state.style,
        "rating": state.rating,
        "script_type": state.script_type,
        "language": state.language,
    }
    messages = [
        {"role": "system", "content": EPISODE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Script state:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
                f"Generate episode {number} with {storyboards_count} storyboards."
            ),
        },
    ]
    raw = llm.chat(messages, model_key=state.text_model)
    parsed = _extract_json(raw)
    if parsed is None:
        raise ValueError(f"Agent did not return valid JSON for the episode: {raw[:200]}")
    storyboards = []
    for item in parsed.get("storyboards", []):
        if isinstance(item, dict):
            storyboards.append(Storyboard(**item))
    return Episode(
        number=number,
        title=str(parsed.get("title", "")),
        synopsis=str(parsed.get("synopsis", "")),
        storyboards=storyboards,
    )
