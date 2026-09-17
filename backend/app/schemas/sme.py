"""SME Messenger API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SmeThreadType = Literal["expert", "panel"]


class SmeInboxItem(BaseModel):
    thread_type: SmeThreadType
    thread_id: str
    name: str
    initials: str
    subtitle: str
    preview: str
    last_message_at: datetime | None
    unread_count: int
    member_names: list[str] = Field(default_factory=list)


class SmeMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    persona_id: str | None = None
    persona_name: str | None = None


class SmePanelMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class SmeReadOut(BaseModel):
    last_read_message_id: int | None
