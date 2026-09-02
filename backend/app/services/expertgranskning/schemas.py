"""Request/response models for the expertgranskning module API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.panel.schemas import PanelSessionStatus


class ExpertgranskningSessionCreate(BaseModel):
    document_text: str = Field(min_length=1, max_length=200_000)
    panel_id: int
    title: str = ""
    project_id: int | None = None

    @field_validator("document_text", "title", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class ExpertgranskningSessionOut(BaseModel):
    id: str
    protocol: str
    status: PanelSessionStatus
    module: str
    topic: str
    document_text: str
    panel_id: int | None
    project_id: int | None
    job_id: str | None
    error: str | None
    created_at: str
    updated_at: str
