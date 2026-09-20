"""Question → Evidence graph contract. Graphiti stays behind an adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.research.knowledge_question import (
    KnowledgeQuestion,
    KnowledgeQuestionScope,
    QuestionIdentity,
)
from app.services.research.models import ResearchError

ANSWERED_BY = "ANSWERED_BY"
BESVARAS_AV = "BESVARAS_AV"
QUESTION_NODE_LABEL = "KnowledgeQuestion"
EVIDENCE_REF_NODE_LABEL = "EvidenceReference"

Freshness = Literal["fresh", "stale", "unknown"]
FRESHNESS_VALUES: tuple[Freshness, ...] = ("fresh", "stale", "unknown")
ReuseOrigin = Literal["persistent_knowledge", "fresh_retrieval"]


class QuestionEvidenceGraphError(ResearchError):
    """Graph lookup or upsert failed. Callers must not treat this as sufficiency."""


@dataclass(frozen=True)
class QuestionEvidenceLink:
    """ANSWERED_BY / BESVARAS_AV edge. Stores a reference, not a document copy."""

    question_id: str
    evidence_ref: str
    passage_id: str | None = None
    relation: str = ANSWERED_BY
    title: str | None = None
    excerpt: str | None = None
    locator: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    source_type: str | None = None
    provider: str | None = None
    provenance: dict[str, object] = field(default_factory=dict)
    retrieved_at: datetime | None = None
    observed_at: datetime | None = None
    freshness: Freshness = "unknown"
    version: str | None = None
    visibility: str = "tenant"
    source_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if self.relation not in {ANSWERED_BY, BESVARAS_AV}:
            raise QuestionEvidenceGraphError(
                f"Unsupported Question→Evidence relation: {self.relation}"
            )
        if self.freshness not in FRESHNESS_VALUES:
            raise QuestionEvidenceGraphError(
                f"Unknown freshness: {self.freshness}"
            )
        object.__setattr__(self, "provenance", dict(self.provenance))


class DisabledQuestionEvidenceGraph:
    """No persistent graph. Lookup is empty; upsert is a no-op."""

    async def match_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion | None:
        del session, identity, scope
        return None

    async def upsert_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion:
        del session
        return KnowledgeQuestion(
            id=uuid4().hex,
            identity_key=identity.identity_key,
            normalized_text=identity.normalized_text,
            display_text=identity.display_text,
            scope=scope,
        )

    async def lookup_answers(
        self,
        session: AsyncSession,
        *,
        question: KnowledgeQuestion,
        limit: int,
        exclude_attempt_id: str | None = None,
    ) -> list[QuestionEvidenceLink]:
        del session, question, limit, exclude_attempt_id
        return []

    async def upsert_answer(
        self,
        session: AsyncSession,
        link: QuestionEvidenceLink,
    ) -> QuestionEvidenceLink:
        del session
        return link


class QuestionEvidenceGraph(Protocol):
    """Persistent question/evidence graph. One hop. No Graphiti types here."""

    async def match_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion | None: ...

    async def upsert_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion: ...

    async def lookup_answers(
        self,
        session: AsyncSession,
        *,
        question: KnowledgeQuestion,
        limit: int,
        exclude_attempt_id: str | None = None,
    ) -> list[QuestionEvidenceLink]: ...

    async def upsert_answer(
        self,
        session: AsyncSession,
        link: QuestionEvidenceLink,
    ) -> QuestionEvidenceLink: ...
