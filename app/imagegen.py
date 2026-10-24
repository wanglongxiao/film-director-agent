"""Seedream image generation wrapper (BytePlus ModelArk /images/generations)."""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import requests

import config

# Seedream supports parallel image generation; cap concurrency at 10 to speed
# up batch generation without exceeding the service limit.
# Ref: https://docs.byteplus.com/en/docs/ModelArk/1541523
MAX_CONCURRENCY = 10

# Retry with exponential backoff when the service rate-limits us (HTTP 429)
# or briefly fails (5xx), so a burst of parallel requests degrades gracefully.
MAX_RETRIES = 4
_RETRY_STATUS = {429, 500, 502, 503, 504}


def generate_image(prompt: str, size: Optional[str] = None, timeout: int = 180) -> str:
    """Generate an image from a prompt; returns the resulting image URL.

    ``size`` defaults to the configured IMAGE_SIZE (4:3 unless overridden in .env).
    Retries with exponential backoff + jitter on rate-limit (429) and transient
    5xx responses.
    """
    url = f"{config.LLM_BASE_URL}/images/generations"
    headers = {
        "Authorization": f"Bearer {config.ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.LLM_MODEL_IMAGE,
        "prompt": prompt,
        "size": size or config.IMAGE_SIZE,
    }

    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code in _RETRY_STATUS and attempt < MAX_RETRIES:
            # Honor Retry-After when present, else exponential backoff + jitter.
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            else:
                delay = min(30.0, (2 ** attempt)) + random.uniform(0, 0.5)
            time.sleep(delay)
            last_exc = requests.HTTPError(f"{resp.status_code} (retrying)")
            continue
        resp.raise_for_status()
        data = resp.json()
        image = data["data"][0]
        return image.get("url", "")
    # Exhausted retries on a retryable status.
    if last_exc:
        raise last_exc
    return ""


def generate_images(
    prompts: list[str],
    size: Optional[str] = None,
    timeout: int = 180,
    max_workers: int = MAX_CONCURRENCY,
    on_error: Optional[Callable[[int, Exception], str]] = None,
) -> list[str]:
    """Generate multiple images in parallel (max concurrency 10).

    Results are returned in the same order as ``prompts``. If a single image
    fails, ``on_error(index, exc)`` decides its placeholder value (defaults to
    an ``(image generation failed: ...)`` marker) so one failure doesn't abort
    the whole batch.
    """
    if not prompts:
        return []
    workers = max(1, min(max_workers, MAX_CONCURRENCY, len(prompts)))

    def _one(idx: int, prompt: str) -> str:
        try:
            return generate_image(prompt, size=size, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                return on_error(idx, exc)
            return "(image generation failed)" if config.WEBUI_CLOUD_MODE else f"(image generation failed: {exc})"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # executor.map preserves input ordering of the results.
        return list(pool.map(lambda p: _one(*p), enumerate(prompts)))
