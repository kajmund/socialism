"""Workspace chat requests and read models."""

from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceChatCreate(BaseModel):
    workspace_id: str | None = None
    persona_id: str | None = None
    title: str = Field(default="", max_length=255)


class WorkspaceChatMessageWrite(BaseModel):
    content: str = Field(min_length=1, max_length=16000)


class WorkspaceResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    source_object_ids: list[str] | None = None
    entrypoint: Literal["modal", "tool"] = "modal"


class WorkspaceChatMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    attachment_object_id: str | None = None
    job_id: str | None = None
    created_at: str


class WorkspaceChatOut(BaseModel):
    id: str
    customer_id: int
    workspace_id: str
    persona_id: str | None
    module: str
    title: str
    messages: list[WorkspaceChatMessageOut]
