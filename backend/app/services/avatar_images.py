"""Normalize uploaded profile photos for object storage."""

from __future__ import annotations

import io

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 5 * 1024 * 1024


def normalize_avatar_image(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format not in {"JPEG", "PNG", "WEBP"}
                or image.width * image.height > 16_000_000
                or image.width > 8192
                or image.height > 8192
            ):
                raise ValueError("invalid_avatar")
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1024, 1024))
            clean = Image.new("RGB", image.size)
            clean.paste(image)
            out = io.BytesIO()
            clean.save(out, format="JPEG", quality=88)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "invalid_avatar") from exc
