"""Build OpenAI-compatible multimodal user content for vision chat models."""

from __future__ import annotations

from typing import Any

from app.services.image_cache import image_data_url
from app.services.llm_runtime_settings import require_vision_support


def user_content_with_optional_image(
    text: str,
    image_sha256: str | None,
) -> str | list[dict[str, Any]]:
    """Return plain text or multimodal parts for a user turn.

    Raises ValueError when an image is requested but the active model lacks
    vision support, or when the cache entry is missing.
    """
    digest = (image_sha256 or "").strip().lower() or None
    cleaned = (text or "").strip()
    if digest is None:
        return cleaned
    require_vision_support()
    data_url = image_data_url(digest)
    parts: list[dict[str, Any]] = []
    if cleaned:
        parts.append({"type": "text", "text": cleaned})
    parts.append({"type": "image_url", "image_url": {"url": data_url}})
    return parts
