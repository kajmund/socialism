"""API schemas for personal underlag files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ExtractionStatus = Literal["ok", "failed", "empty", "unsupported"]


class UnderlagOut(BaseModel):
    id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    module: str
    owner_user_id: str | None = None
    extraction_status: ExtractionStatus | None = None
    extracted_text: str | None = None
    created_at: str = ""
