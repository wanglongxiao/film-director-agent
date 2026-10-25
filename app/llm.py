"""Main-agent and script-writer clients (BytePlus ModelArk, OpenAI-compatible)."""
from __future__ import annotations

from typing import Iterator, Optional

from openai import OpenAI

import config

_client: Optional[OpenAI] = None

# Set the deep-reasoning effort level to "low" for faster responses.
# ModelArk deep-reasoning models accept a string `reasoning_effort` in the
# request body (see docs.byteplus.com/en/docs/ModelArk/1449737 & 1494384).
# Allowed values: minimal / low / medium / high / xhigh / max.
_REASONING = {"reasoning_effort": "low"}


class OutputTruncatedError(ValueError):
    """The model exhausted its output budget before finishing."""


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.ARK_API_KEY)
    return _client


def chat(
    messages: list[dict],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model_key: Optional[str] = None,
) -> str:
    """Send a completion; use the main agent unless a writer key is supplied."""
    model_key = config.normalize_text_model(model_key)
    settings = config.MAIN_AGENT_MODEL if model_key is None else config.CHAT_MODELS[model_key]
    kwargs: dict = {
        "model": settings["endpoint"],
        "messages": messages,
        "temperature": config.SCRIPT_LLM_TEMPERATURE if temperature is None else temperature,
    }
    if model_key is None or model_key.startswith("deepseek-"):
        kwargs["extra_body"] = dict(_REASONING)
    kwargs["max_tokens"] = min(max_tokens or settings["max_tokens"], settings["max_tokens"])
    resp = get_client().chat.completions.create(**kwargs)
    if resp.choices[0].finish_reason == "length":
        raise OutputTruncatedError("模型输出达到 token 上限，请缩小单次生成范围后重试。")
    return (resp.choices[0].message.content or "").strip()


def chat_stream(
    messages: list[dict],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model_key: Optional[str] = None,
) -> Iterator[str]:
    """Stream a completion; use the main agent unless a writer key is supplied."""
    model_key = config.normalize_text_model(model_key)
    settings = config.MAIN_AGENT_MODEL if model_key is None else config.CHAT_MODELS[model_key]
    kwargs: dict = {
        "model": settings["endpoint"],
        "messages": messages,
        "temperature": config.SCRIPT_LLM_TEMPERATURE if temperature is None else temperature,
        "stream": True,
    }
    if model_key is None or model_key.startswith("deepseek-"):
        kwargs["extra_body"] = dict(_REASONING)
    kwargs["max_tokens"] = min(max_tokens or settings["max_tokens"], settings["max_tokens"])
    stream = get_client().chat.completions.create(**kwargs)
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content
            if chunk.choices[0].finish_reason == "length":
                raise OutputTruncatedError("模型输出达到 token 上限。")
    finally:
        stream.close()
