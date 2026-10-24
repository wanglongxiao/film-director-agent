"""Prepare embedded character portraits for the DOCX writer."""
from __future__ import annotations

import base64
import io
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageOps

from .persist import Persist
from .schemas import SessionState


def export_payload(sid: str, state: SessionState, persist: Persist) -> dict:
    payload = state.model_dump(mode="json")
    names = {c.name for c in state.characters}
    # Prefer the newest successful portrait for each character, including old archives.
    portraits = {}
    for row in persist.get_images(sid):
        name = row.get("character_name") or ""
        if not name and row["episode_number"] == 0 and row["scene"] == "character":
            name = row["shot"].removesuffix(" · 定妆图")
        if name in names and row.get("kind") in (None, "", "character") and (
            row.get("image_blob") or row["image_url"].startswith(("https://", "http://"))
        ):
            portraits[name] = row

    def load(entry):
        name, row = entry
        try:
            raw = row.get("image_blob")
            if not raw:
                with requests.get(row["image_url"], timeout=(5, 20), stream=True) as response:
                    response.raise_for_status()
                    parts, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 20 * 1024 * 1024:
                            raise ValueError("portrait exceeds 20 MB")
                        parts.append(chunk)
                    raw = b"".join(parts)
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1200, 1600))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                data = buffer.getvalue()
                scale = min(440 / image.width, 520 / image.height, 1)
                result = {
                    "character_name": name,
                    "data": base64.b64encode(data).decode("ascii"),
                    "width": round(image.width * scale),
                    "height": round(image.height * scale),
                }
            if not row.get("image_blob"):
                persist.cache_image(row["id"], data)
            return result
        except Exception as exc:
            raise ValueError(f"角色「{name}」的图片无法读取，请重试或重新生成参考图后导出。") from exc

    # Download portraits concurrently, with the same maximum of 10 as image generation.
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(portraits)))) as pool:
        payload["character_images"] = list(pool.map(load, portraits.items()))
    return payload
