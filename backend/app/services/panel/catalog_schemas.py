"""Pydantic schemas for panel catalog CRUD (sub-questions and expert profiles)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

_KEY_PATTERN = r"^[a-z0-9_]+$"


class PanelSubQuestionOut(BaseModel):
    id: int
    module: str
    key: str
    label: str
    sort_order: int
    active: bool
    created_at: str
    updated_at: str


class PanelSubQuestionCreate(BaseModel):
    module: str = Field(min_length=1, max_length=32)
    key: str = Field(min_length=1, max_length=64, pattern=_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=255)
    sort_order: int | None = None
    active: bool = True

    @field_validator("module", "key", "label", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class PanelSubQuestionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = None
    active: bool | None = None

    @field_validator("label", mode="before")
    @classmethod
    def strip_label(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class PanelExpertProfileOut(BaseModel):
    id: int
    module: str
    key: str
    name: str
    description: str
    kompetensomrade: str
    radgivningsstil: str
    yrkesbakgrund: str
    professionell_anekdot: str
    sort_order: int
    active: bool
    created_at: str
    updated_at: str


class PanelExpertProfileCreate(BaseModel):
    module: str = Field(min_length=1, max_length=32)
    key: str | None = Field(default=None, min_length=1, max_length=64, pattern=_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    kompetensomrade: str = ""
    radgivningsstil: str = ""
    yrkesbakgrund: str = ""
    professionell_anekdot: str = ""
    sort_order: int | None = None
    active: bool = True

    @field_validator(
        "module",
        "key",
        "name",
        "description",
        "kompetensomrade",
        "radgivningsstil",
        "yrkesbakgrund",
        "professionell_anekdot",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class PanelExpertProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    kompetensomrade: str | None = None
    radgivningsstil: str | None = None
    yrkesbakgrund: str | None = None
    professionell_anekdot: str | None = None
    sort_order: int | None = None
    active: bool | None = None

    @field_validator(
        "name",
        "description",
        "kompetensomrade",
        "radgivningsstil",
        "yrkesbakgrund",
        "professionell_anekdot",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
