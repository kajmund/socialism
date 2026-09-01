"""Serializable product-module metadata (no routers or callables)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModuleOut(BaseModel):
    id: str
    name: str
    icon: str
    prompt_namespace: str
    frontend_entry: str
    components: list[str] = Field(default_factory=list)
    report_modes: list[str] = Field(default_factory=list)
    has_sub_questions: bool
    has_expert_defaults: bool
    has_prompt_defaults: bool = False
    supports_interview: bool
