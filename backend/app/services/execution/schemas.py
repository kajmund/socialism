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
    research_objective: str | None = None
    research_context: dict[str, Any] = Field(default_factory=dict)


class ResearchNeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    why_needed: str = ""
    requested_by: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    modalities: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class ResearchPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs: list[ResearchNeedIn] = Field(default_factory=list)


class AttemptResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_objective: str | None = None
    research_context: dict[str, Any] = Field(default_factory=dict)
    research_plan: ResearchPlanIn | None = None


class AttemptExecuteRequest(BaseModel):
    """Empty body. extra=forbid so a caller cannot smuggle customer_id."""

    model_config = ConfigDict(extra="forbid")


class AttemptCloneRequest(BaseModel):
    """Optional full configuration replacement. extra=forbid — no ids or merge."""

    model_config = ConfigDict(extra="forbid")

    configuration_snapshot: dict[str, Any] | None = None


class ResearchNeedAssessmentOut(BaseModel):
    research_need_id: str
    sufficient: bool
    supporting_evidence_ids: list[str]
    missing_or_weak: str
    contradictions: list[str]
    further_information: str | None


class RuntimeResearchNeedOut(BaseModel):
    research_need_id: str
    question: str
    why_needed: str
    requested_by: list[str]
    source_types: list[str]
    domains: list[str] = Field(default_factory=list)
    modalities: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    origin: str
    wave_number: int
    parent_research_need_id: str | None
    source_assessment_pass: int | None
    source_completeness_pass: int | None = None
    source_gap: str
    question_key: str


class ResearchAssessmentOut(BaseModel):
    id: str
    attempt_id: str
    evidence_set_id: str
    assessment_pass: int
    result: str
    rationale: str
    need_assessments: list[ResearchNeedAssessmentOut]
    gaps: list[str]
    contradictions: list[str]
    considered_evidence_ids: list[str]
    evidence_fingerprint: str
    model_provider: str | None
    model_name: str | None
    model_version: str | None
    created_at: datetime


class MissingQuestionOut(BaseModel):
    question: str
    why_needed: str
    rationale: str
    source_types: list[str]
    unavailable_source_types: list[str] = []
    capability_gap: str | None = None


class ResearchCompletenessOut(BaseModel):
    id: str
    attempt_id: str
    evidence_set_id: str
    completeness_pass: int
    result: str
    rationale: str
    missing_questions: list[MissingQuestionOut]
    considered_evidence_ids: list[str]
    considered_question_keys: list[str]
    evidence_fingerprint: str
    question_fingerprint: str
    model_provider: str | None
    model_name: str | None
    model_version: str | None
    created_at: datetime


class AttemptResearchOut(BaseModel):
    attempt_id: str
    evidence_set_id: str | None
    status: str
    found_count: int
    not_found_count: int
    error_count: int
    assessment: ResearchAssessmentOut | None = None
    assessments: list[ResearchAssessmentOut] = Field(default_factory=list)
    completeness: ResearchCompletenessOut | None = None
    completeness_passes: list[ResearchCompletenessOut] = Field(default_factory=list)
    research_wave: int = 0
    stop_reason: str | None = None
    runtime_needs: list[RuntimeResearchNeedOut] = Field(default_factory=list)


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
    research_objective_snapshot: dict[str, Any] | None = None
    research_plan_snapshot: dict[str, Any] | None
    evidence: EvidenceSummaryOut | None
    assessment: ResearchAssessmentOut | None = None
    assessments: list[ResearchAssessmentOut] = Field(default_factory=list)
    completeness: ResearchCompletenessOut | None = None
    completeness_passes: list[ResearchCompletenessOut] = Field(default_factory=list)
    research_wave: int = 0
    stop_reason: str | None = None
    runtime_needs: list[RuntimeResearchNeedOut] = Field(default_factory=list)
    result: AttemptResultOut | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AttemptExecuteOut(BaseModel):
    attempt: ExecutionAttemptOut
    result: AttemptResultOut | None


class EvidenceQualityFlagOut(BaseModel):
    code: str
    detail: str


class EvidenceQualityOut(BaseModel):
    """Auditable per-item quality. Separate from EvidenceSet contents."""

    id: str
    evidence_set_item_id: str
    original_evidence_id: str | None
    scoring_policy_version: str
    authority: str
    relevance: str
    currentness: str
    source_nature: str
    source_timestamp: datetime | None
    independence_key: str
    independent_source_count: int
    flags: list[EvidenceQualityFlagOut]
    rationale: str
    declared_signals: dict[str, Any]
    model_provider: str | None
    model_name: str | None
    model_version: str | None
    created_at: datetime


class EvidenceSetItemOut(BaseModel):
    id: str
    evidence_set_id: str
    research_need_id: str | None
    research_need_ids: list[str]
    passage_id: str | None
    domain_result_id: str | None = None
    raw_source_id: str | None = None
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
    quality: EvidenceQualityOut | None = None


class EvidenceSetOut(BaseModel):
    id: str
    run_id: str
    created_from_attempt_id: str | None
    status: str
    created_at: datetime
    frozen_at: datetime | None
    items: list[EvidenceSetItemOut]
    sources: list[EvidenceSourceGroupOut]


class EvidenceSourceGroupOut(BaseModel):
    source_key: str
    title: str | None
    source_url: str | None
    item_ids: list[str]
    research_need_ids: list[str]
    domain_result_ids: list[str]
    raw_source_ids: list[str]
    successful_analyses: int
    error_count: int
    claim_count: int


class RawSourceOut(BaseModel):
    id: str
    source_id: str
    content_hash: str
    raw_text: str
    truncated: bool


class DomainResearchResultOut(BaseModel):
    id: str
    raw_source_id: str
    research_need_id: str
    domain: str
    schema_version: int
    result: dict[str, Any]
    claims: list[dict[str, Any]]


class ResearchProgressEventOut(BaseModel):
    id: str
    attempt_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime


class ResearchProgressEventListOut(BaseModel):
    attempt_id: str
    after_sequence: int
    events: list[ResearchProgressEventOut]


class ResearchExpertOut(BaseModel):
    id: str
    name: str


class ResearchSourceOut(BaseModel):
    derived: bool = False
    failure_category: str | None = None
    id: str
    passage_id: str | None
    domain_result_id: str | None = None
    raw_source_id: str | None = None
    analysis: str | None = None
    research_need_ids: list[str]
    status: str
    title: str | None
    excerpt: str | None
    locator: str | None
    source_url: str | None
    source_type: str
    provider: str | None


class ResearchQuestionOverviewOut(BaseModel):
    id: str
    question: str
    specific_question: str
    why_needed: str
    status: str
    raw_status: str
    outcome_reason: str | None
    origin: str
    depth: int
    child_attempt_id: str | None
    child_attempt_status: str | None
    dependency_ids: list[str]
    blocking_dependency_ids: list[str] = Field(default_factory=list)
    raised_by: list[ResearchExpertOut]
    assigned_to: ResearchExpertOut | None
    sources: list[ResearchSourceOut]
    source_count: int
    need_assessment: ResearchNeedAssessmentOut | None = None


class ResearchOverviewCountsOut(BaseModel):
    total: int
    answered: int
    running: int
    waiting: int
    insufficient: int
    unanswered: int
    failed: int
    blocked: int


class ResearchOverviewOut(BaseModel):
    run_id: str
    attempt_id: str
    attempt_status: str
    phase: str
    latest_sequence: int
    counts: ResearchOverviewCountsOut
    questions: list[ResearchQuestionOverviewOut]
