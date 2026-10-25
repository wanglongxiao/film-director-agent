"""Seed-Speech transcription; audio and credentials stay on the server."""
from __future__ import annotations

import base64
import io
import uuid
import wave

import requests

import config

MAX_AUDIO_BYTES = 16000 * 2 * config.SPEECH_MAX_SECONDS + 4096


class SpeechError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def transcribe(audio: bytes, language: str, session_id: str) -> str:
    if not config.SPEECH_API_KEY:
        raise SpeechError(503, "speech_unavailable")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
                1, 2, 16000, "NONE"
            ):
                raise ValueError("Unsupported WAV")
            frames = wav.getnframes()
            if not 4000 <= frames <= 16000 * config.SPEECH_MAX_SECONDS:
                raise ValueError("Invalid duration")
            if len(wav.readframes(frames)) != frames * 2:
                raise ValueError("Truncated WAV")
    except (wave.Error, EOFError, ValueError):
        raise SpeechError(400, "speech_invalid_audio") from None
    languages = {
        "zh-CN": "zh-CN", "zh-TW": "zh-CN", "en": "en-US",
        "ja": "ja-JP", "ko": "ko-KR",
    }
    options = {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True}
    if language == "zh-TW":
        options["output_zh_variant"] = "tw"
    try:
        response = requests.post(
            config.SPEECH_ASR_URL,
            headers={
                "X-Api-Key": config.SPEECH_API_KEY,
                "X-Api-Resource-Id": config.SPEECH_RESOURCE_ID,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "X-Api-Sequence": "-1",
            },
            json={
                "user": {"uid": session_id},
                "audio": {
                    "data": base64.b64encode(audio).decode(),
                    "format": "wav", "codec": "raw", "rate": 16000,
                    "bits": 16, "channel": 1,
                    "language": languages.get(language, "zh-CN"),
                },
                "request": options,
            },
            timeout=(10, 60),
        )
        if response.status_code == 429:
            raise SpeechError(429, "speech_busy")
        if response.status_code != 200 or response.headers.get("X-Api-Status-Code") != "20000000":
            raise SpeechError(502, "speech_failed")
        result = response.json().get("result", {})
        text = result.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise SpeechError(422, "speech_empty")
        return text.strip()
    except requests.Timeout:
        raise SpeechError(504, "speech_timeout") from None
    except (requests.RequestException, ValueError, AttributeError):
        raise SpeechError(502, "speech_failed") from None
