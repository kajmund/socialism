"""Request/response models for the expertgranskning module API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.panel.schemas import PanelSessionStatus


class ExpertgranskningSessionCreate(BaseModel):
    """Create a session. Empty document/panel is allowed for drafts."""

    document_text: str = Field(default="", max_length=200_000)
    panel_id: int | None = None
    title: str = ""
    project_id: int | None = None

    @field_validator("document_text", "title", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class ExpertgranskningSessionUpdate(BaseModel):
    document_text: str | None = Field(default=None, max_length=200_000)
    panel_id: int | None = None
    title: str | None = None
    project_id: int | None = None
    clear_panel: bool = False

    @field_validator("document_text", "title", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return str(value).strip()


class ExpertgranskningSessionOut(BaseModel):
    id: str
    protocol: str
    status: PanelSessionStatus
    module: str
    topic: str
    document_text: str
    panel_id: int | None
    panel_name: str | None = None
    project_id: int | None
    job_id: str | None
    error: str | None
    created_at: str
    updated_at: str


class ExpertgranskningSessionSummary(BaseModel):
    id: str
    topic: str
    status: PanelSessionStatus
    panel_id: int | None
    panel_name: str | None
    job_id: str | None
    created_at: str
    updated_at: str
