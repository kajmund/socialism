"""Public records for the isolated clause SSR library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ClassificationLevel = Literal["document", "clause", "variant"]
DecisionAnswer = Literal["yes", "no", "skip", "unsure"]
Polarity = Literal["positive", "negative"]
AnchorStatus = Literal["draft", "active", "revoked", "stale_embedding", "source_revoked"]
VerificationStatus = Literal["active", "superseded", "revoked"]
AnchorSetStatus = Literal["draft", "active", "superseded", "stale"]
SelectionMethod = Literal["deterministic_diversity"]

LEVELS: frozenset[str] = frozenset({"document", "clause", "variant"})
ANSWERS: frozenset[str] = frozenset({"yes", "no", "skip", "unsure"})
LABEL_ANSWERS: frozenset[str] = frozenset({"yes", "no"})


@dataclass(frozen=True)
class EmbeddingSpec:
    model: str
    revision: str
    dimension: int


@dataclass(frozen=True)
class ClassificationDefinition:
    id: str
    slug: str
    version: int
    question: str
    level: ClassificationLevel
    category: str
    active: bool
    scope_key: str


@dataclass(frozen=True)
class Verification:
    id: str
    source_unit_id: str
    source_document_id: str
    content_hash: str
    classification_id: str
    classification_version: int
    question: str
    category: str
    answer: DecisionAnswer
    polarity: Polarity | None
    reviewer_id: str
    decided_at_ms: int
    source: str
    revision: int
    status: VerificationStatus
    scope_key: str


@dataclass(frozen=True)
class Anchor:
    id: str
    verification_id: str
    source_unit_id: str
    classification_id: str
    category: str
    polarity: Polarity
    content_hash: str
    status: AnchorStatus
    embedding: EmbeddingSpec
    vector: tuple[float, ...] | None
    scope_key: str
    provenance: dict[str, str]


@dataclass(frozen=True)
class AnchorSet:
    id: str
    version: int
    category: str
    status: AnchorSetStatus
    selection_method: SelectionMethod
    embedding: EmbeddingSpec
    holdout_ids: tuple[str, ...]
    member_ids: tuple[str, ...]
    scope_key: str
    created_at_ms: int


@dataclass(frozen=True)
class VerificationWrite:
    key: str
    unit_id: str
    document_id: str
    content_hash: str
    classification_id: str
    classification_version: int
    question: str
    category: str
    answer: DecisionAnswer
    reviewer_id: str
    source: str
    revision: int
    status: VerificationStatus
    decided_at_ms: int | None = None


@dataclass(frozen=True)
class ReviewSession:
    id: str
    reviewer_id: str
    classification_id: str
    document_id: str | None
    last_unit_id: str | None
    last_verification_id: str | None
    decided_yes: int
    decided_no: int
    skipped: int
    unsure: int
    scope_key: str


@dataclass(frozen=True)
class QueueCard:
    unit_id: str
    document_id: str
    document_version_id: str
    text: str
    locator: str | None
    ordinal: int
    section_title: str | None
    content_hash: str
    classification: ClassificationDefinition
    similarity: float | None


@dataclass(frozen=True)
class QueuePage:
    cards: tuple[QueueCard, ...]
    session: ReviewSession
    remaining: int
    total_eligible: int


@dataclass(frozen=True)
class MatchHit:
    anchor_id: str
    classification_id: str
    category: str
    polarity: Polarity
    cosine_similarity: float
    source_unit_id: str
    content_hash: str


@dataclass(frozen=True)
class CategoryScore:
    category: str
    score: float
    margin: float
    support_count: int
    independent_support: int
    negative_signal: float
    top_similarity: float


@dataclass(frozen=True)
class MatchResult:
    top_k: tuple[MatchHit, ...]
    category_scores: tuple[CategoryScore, ...]
    labels: tuple[str, ...]
    abstained: bool
    abstain_reason: str | None
    embedding: EmbeddingSpec
