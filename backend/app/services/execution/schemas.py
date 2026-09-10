"""Read/write HTTP models for the execution domain. Projection only — no rules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: int
    module: str
    title: str
    context: dict[str, Any] = Field(default_factory=dict)


class ExecutionRunOut(BaseModel):
    id: str
    customer_id: int
    module: str
    title: str
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExecutionAttemptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_type: str
    configuration_snapshot: dict[str, Any] = Field(default_factory=dict)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)


class ResearchNeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    why_needed: str = ""
    requested_by: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)


class ResearchPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs: list[ResearchNeedIn] = Field(default_factory=list)


class AttemptResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_plan: ResearchPlanIn = Field(default_factory=ResearchPlanIn)


class AttemptExecuteRequest(BaseModel):
    """Empty body. extra=forbid so a caller cannot smuggle customer_id."""

    model_config = ConfigDict(extra="forbid")


class AttemptCloneRequest(BaseModel):
    """Optional full configuration replacement. extra=forbid — no ids or merge."""

    model_config = ConfigDict(extra="forbid")

    configuration_snapshot: dict[str, Any] | None = None


class AttemptResearchOut(BaseModel):
    attempt_id: str
    evidence_set_id: str | None
    status: str
    found_count: int
    not_found_count: int
    error_count: int


class EvidenceSummaryOut(BaseModel):
    evidence_set_id: str
    status: str
    found_count: int
    not_found_count: int
    error_count: int


class AttemptResultOut(BaseModel):
    id: str
    result_type: str
    schema_version: str
    payload: dict[str, Any]
    evidence_refs: dict[str, Any]
    panel_session_id: str | None
    created_at: datetime


class ExecutionAttemptOut(BaseModel):
    id: str
    run_id: str
    parent_attempt_id: str | None
    attempt_type: str
    status: str
    configuration_snapshot: dict[str, Any]
    input_snapshot: dict[str, Any]
    research_plan_snapshot: dict[str, Any] | None
    evidence: EvidenceSummaryOut | None
    result: AttemptResultOut | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AttemptExecuteOut(BaseModel):
    attempt: ExecutionAttemptOut
    result: AttemptResultOut | None


class EvidenceSetItemOut(BaseModel):
    id: str
    evidence_set_id: str
    research_need_id: str | None
    original_evidence_id: str | None
    ordinal: int
    source_type: str
    status: str
    title: str | None
    excerpt: str | None
    locator: str | None
    source_id: str | None
    source_url: str | None
    provider: str | None
    score: float | None
    provenance: dict[str, Any]
    retrieved_at: datetime
    content_hash: str


class EvidenceSetOut(BaseModel):
    id: str
    run_id: str
    created_from_attempt_id: str | None
    status: str
    created_at: datetime
    frozen_at: datetime | None
    items: list[EvidenceSetItemOut]
