"""API schemas for personal underlag files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ExtractionStatus = Literal["ok", "failed", "empty", "unsupported"]


class UnderlagOut(BaseModel):
    id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    module: str
    owner_user_id: str | None = None
    folder_id: str | None = None
    extraction_status: ExtractionStatus | None = None
    extracted_text: str | None = None
    created_at: str = ""


class UnderlagFolderOut(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    created_at: str = ""


class UnderlagListingOut(BaseModel):
    folder_id: str | None = None
    folders: list[UnderlagFolderOut]
    files: list[UnderlagOut]


class UnderlagFolderCreate(BaseModel):
    module: str
    name: str = Field(min_length=1, max_length=80)
    parent_id: str | None = None


class UnderlagMove(BaseModel):
    folder_id: str | None = None
