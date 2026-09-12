"""Neutral WordAction API models. Unknown action types fail closed."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SUPPORTED_WORD_ACTION_TYPES = frozenset({"comment", "replace"})
WordActionType = Literal["comment", "replace"]


class WordAnchorOut(BaseModel):
    paragraph_index: int
    unique_local_id: str | None = None
    reviewed_text: str
    text_hash: str
    previous_text_hash: str | None = None
    next_text_hash: str | None = None
    word_session_id: str | None = None


class WordActionSource(BaseModel):
    type: str
    id: str
    ordinal: int


class WordActionOut(BaseModel):
    id: str
    job_id: str
    action_type: WordActionType
    anchor: WordAnchorOut | None = None
    content: str
    explanation: str | None = None
    status: str
    application_id: str | None = None
    application_error: str | None = None
    word_artifact_id: str | None = None
    source: WordActionSource
    created_at: str

    @field_validator("action_type")
    @classmethod
    def known_action_type(cls, value: str) -> str:
        if value not in SUPPORTED_WORD_ACTION_TYPES:
            raise ValueError(f"unsupported action_type: {value}")
        return value

    @field_validator("content")
    @classmethod
    def non_empty_content(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("word action content is required")
        return value

    @model_validator(mode="after")
    def supported_types_require_content(self) -> WordActionOut:
        if self.action_type in SUPPORTED_WORD_ACTION_TYPES and not self.content.strip():
            raise ValueError("word action content is required")
        return self


class WordApplicationClaimIn(BaseModel):
    application_id: str = Field(min_length=1, max_length=64)


class WordApplicationCompleteIn(BaseModel):
    application_id: str = Field(min_length=1, max_length=64)
    word_artifact_id: str | None = Field(default=None, max_length=128)

    @field_validator("word_artifact_id", mode="before")
    @classmethod
    def empty_word_artifact_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class WordApplicationUnresolvedIn(BaseModel):
    application_id: str | None = Field(default=None, max_length=64)
    reason: str = Field(min_length=1, max_length=64)

    @field_validator("application_id", mode="before")
    @classmethod
    def empty_application_id(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
