"""Ask-time Q&A records. Not a proof engine and not a research KnowledgeQuestion."""

from __future__ import annotations

from dataclasses import dataclass

QUESTION_KINDS = ("document_chat", "tabular_review", "expert")
ANSWER_STATUSES = ("ANSWERED", "NOT_FOUND", "UNCERTAIN")
REVIEW_STATUSES = ("unreviewed", "user_verified", "rejected")
EXAMINED_SCOPES = ("retrieved_evidence", "whole_document", "existing_analysis")

# NOT_FOUND: not found in the examined material. Not a proof of absence.
# retrieved_evidence is a limited investigation, not a whole-document reading.


@dataclass(frozen=True)
class AnalysisContract:
    kind: str
    method: str
    model: str
    model_version: str
    examined_scope: str = "existing_analysis"
    question_context: str = ""

    def __post_init__(self) -> None:
        if self.kind not in QUESTION_KINDS:
            raise ValueError(f"unsupported question kind: {self.kind}")
        if self.examined_scope not in EXAMINED_SCOPES:
            raise ValueError(f"unsupported examined scope: {self.examined_scope}")
        if not self.method or not self.model or not self.model_version:
            raise ValueError("analysis contract is incomplete")


@dataclass(frozen=True)
class SourceCite:
    text_unit_id: str
    excerpt: str
    start: int | None = None
    end: int | None = None
    position_validated: bool = False

    def __post_init__(self) -> None:
        if not self.text_unit_id or not self.excerpt.strip():
            raise ValueError("source cite needs a TextUnit id and an excerpt")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("source position is invalid")


@dataclass(frozen=True)
class AnswerPostWrite:
    text: str
    sources: tuple[SourceCite, ...]


@dataclass(frozen=True)
class QaWrite:
    question_text: str
    document_id: str
    document_version_id: str
    workspace_id: str
    contract: AnalysisContract
    status: str
    answer_text: str
    posts: tuple[AnswerPostWrite, ...]
    asked_at: str
    created_at: str
    embedding: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if self.status not in ANSWER_STATUSES:
            raise ValueError(f"unsupported answer status: {self.status}")
        if not self.question_text.strip() or not self.document_id or not self.document_version_id:
            raise ValueError("Q&A write is missing document or question identity")
        if not self.posts:
            raise ValueError("answer needs at least one post")


@dataclass(frozen=True)
class LoadedCite:
    text_unit_id: str
    excerpt: str
    start: int | None
    end: int | None
    position_validated: bool
    document_version_id: str


@dataclass(frozen=True)
class LoadedPost:
    key: str
    text: str
    ordinal: int
    sources: tuple[LoadedCite, ...]


@dataclass(frozen=True)
class LoadedAnswer:
    key: str
    status: str
    text: str
    model: str
    model_version: str
    method: str
    review_status: str
    created_at: str
    posts: tuple[LoadedPost, ...]


@dataclass(frozen=True)
class LoadedQuestion:
    key: str
    text: str
    normalized: str
    document_id: str
    document_version_id: str
    workspace_id: str
    asked_at: str
    archived: bool
    answers: tuple[LoadedAnswer, ...]


@dataclass(frozen=True)
class ExactHit:
    question: LoadedQuestion
    answer: LoadedAnswer
    reuse: str = "exact"


@dataclass(frozen=True)
class SemanticCandidate:
    question: LoadedQuestion
    score: float
    current_version: bool
    reuse: str = "semantic"


@dataclass(frozen=True)
class CacheDecision:
    reuse: str
    exact: ExactHit | None
    candidates: tuple[SemanticCandidate, ...]


@dataclass(frozen=True)
class UserAnswer:
    text: str
    status: str
    persisted: bool


@dataclass(frozen=True)
class FlushResult:
    ok: bool
    reason: str = ""
