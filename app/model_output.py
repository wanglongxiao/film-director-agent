"""Decode model envelopes without exposing protocol JSON as chat text."""
from __future__ import annotations

import json
import re

from json_repair import repair_json


def _unicode(value):
    if isinstance(value, str):
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(value, dict):
        return {key: _unicode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unicode(item) for item in value]
    return value


def extract_json(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    candidate = text[start:].strip()
    try:
        parsed, _ = json.JSONDecoder(strict=False).raw_decode(candidate)
    except ValueError:
        try:
            parsed = repair_json(candidate, return_objects=True)
        except (ValueError, TypeError, RecursionError):
            return None
    return _unicode(parsed) if isinstance(parsed, dict) else None


def is_envelope(text: str) -> bool:
    return bool(re.match(r'\s*(?:```(?:json)?\s*)?\{\s*"(?:thought|reply|stage|state_update)"\s*:', text))


def partial_string(text: str, key: str) -> tuple[str | None, bool]:
    match = re.search(r'(?<!\\)"' + re.escape(key) + r'"\s*:\s*"', text)
    if not match:
        return None, False
    parts = []
    i = match.end()
    while i < len(text):
        char = text[i]
        if char == "\\":
            if i + 1 >= len(text):
                break
            escaped = text[i + 1]
            if escaped == "u":
                count = 6
                if len(text) < i + count:
                    break
                # Hold a high surrogate until its low surrogate arrives.
                code = text[i + 2:i + 6]
                if re.fullmatch(r"[dD][89aAbB][0-9a-fA-F]{2}", code):
                    count = 12
                    if len(text) < i + count:
                        break
                token = text[i:i + count]
                try:
                    parts.append(json.loads('"' + token + '"'))
                except ValueError:
                    parts.append(token)
                i += count
                continue
            parts.append({"n": "\n", "r": "\r", "t": "\t", "b": "\b",
                          "f": "\f", '"': '"', "\\": "\\", "/": "/"}.get(escaped, "\\" + escaped))
            i += 2
            continue
        if char == '"':
            tail = text[i + 1:]
            # Wait across chunk boundaries before deciding if a quote closes
            # the field or is an unescaped quote inside the prose.
            if not tail.strip():
                break
            if re.match(r'\s*(?:,\s*"(?:thought|reply|stage|state_update)"\s*:|})', tail):
                return "".join(parts), True
            if re.match(r'\s*,\s*(?:"[a-z_]*"?\s*:?\s*)?$', tail):
                break
        parts.append(char)
        i += 1
    return "".join(parts), False


def visible_reply(raw: str, parsed: dict | None = None) -> str:
    parsed = parsed if parsed is not None else extract_json(raw)
    if parsed and isinstance(parsed.get("reply"), str) and parsed["reply"].strip():
        return parsed["reply"]
    if is_envelope(raw):
        reply, _ = partial_string(raw, "reply")
        if reply and reply.strip():
            return reply
        raise ValueError("模型回复格式不完整，请重试。")
    return raw


def display_history(history: list[dict]) -> list[dict]:
    result = []
    for message in history:
        if message.get("role") == "assistant" and is_envelope(message.get("content", "")):
            try:
                message = {**message, "content": visible_reply(message["content"])}
            except ValueError:
                message = {**message, "content": "模型回复格式不完整，请重新发送上一条消息。"}
        result.append(message)
    return result


def recover_history_fields(state: dict, history: list[dict]) -> bool:
    """Fill missing discussion data only; existing story/prose is authoritative."""
    from .schemas import SessionState

    changed = False
    for message in reversed(history):
        raw = message.get("content", "")
        if message.get("role") != "assistant" or not is_envelope(raw):
            continue
        parsed = extract_json(raw) or {}
        update = parsed.get("state_update")
        if not isinstance(update, dict):
            continue
        for key in ("title", "background", "genre", "tone", "characters", "outline",
                    "script_type", "style", "rating", "discussion_chapters"):
            if state.get(key) or not update.get(key):
                continue
            if key == "discussion_chapters" and state.get("novel"):
                continue
            try:
                validated = SessionState.model_validate({**state, key: update[key]})
            except ValueError:
                continue
            if key == "discussion_chapters" and [c.number for c in validated.discussion_chapters] != list(
                range(1, validated.writing.chapters_count + 1)
            ):
                continue
            state[key] = validated.model_dump(mode="json")[key]
            changed = True
    return changed
