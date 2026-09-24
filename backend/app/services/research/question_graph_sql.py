"""SQL-backed QuestionEvidenceGraph. Documents stay on EvidenceSet items."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    EvidencePassage,
    KnowledgeQuestionEvidenceLink,
    KnowledgeQuestionRow,
)
from app.services.knowledge.scope import persist_scope_fields
from app.services.research.knowledge_question import (
    ExactQuestionIdentityMatcher,
    KnowledgeQuestion,
    KnowledgeQuestionError,
    KnowledgeQuestionScope,
    QuestionIdentity,
    QuestionIdentityMatcher,
)
from app.services.research.question_graph import (
    ANSWERED_BY,
    Freshness,
    QuestionEvidenceLink,
)


class SqlQuestionEvidenceGraph:
    def __init__(
        self,
        *,
        matcher: QuestionIdentityMatcher | None = None,
    ) -> None:
        self._matcher = matcher or ExactQuestionIdentityMatcher()

    async def match_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion | None:
        result = await session.execute(
            select(KnowledgeQuestionRow).where(
                KnowledgeQuestionRow.namespace == scope.namespace,
                KnowledgeQuestionRow.identity_key == identity.identity_key,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            if row.scope_key != scope.tenant.scope_key:
                raise KnowledgeQuestionError(
                    "canonical question reuse crossed a knowledge tenant boundary"
                )
            return _question_from_row(row)
        namespace_result = await session.execute(
            select(KnowledgeQuestionRow).where(
                KnowledgeQuestionRow.namespace == scope.namespace
            )
        )
        rows = list(namespace_result.scalars())
        candidates = [_question_from_row(item) for item in rows]
        await self._matcher.index(candidates)
        metadata = self._matcher.embedding_metadata
        if metadata is not None:
            model, version, dimension = metadata
            for row in rows:
                row.embedding_model = model
                row.embedding_version = version
                row.embedding_dimension = dimension
            await session.flush()
            candidates = [_question_from_row(item) for item in rows]
        return await self._matcher.match(
            normalized_text=identity.normalized_text,
            identity_key=identity.identity_key,
            candidates=candidates,
        )

    async def upsert_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion:
        existing = await self.match_question(session, identity, scope)
        if existing is not None:
            return existing
        row = KnowledgeQuestionRow(
            id=uuid4().hex,
            identity_key=identity.identity_key,
            normalized_text=identity.normalized_text,
            display_text=identity.display_text,
            namespace=scope.namespace,
            visibility=scope.visibility,
            **persist_scope_fields(scope.tenant),
        )
        session.add(row)
        await session.flush()
        question = _question_from_row(row)
        await self._matcher.index([question])
        metadata = self._matcher.embedding_metadata
        if metadata is not None:
            row.embedding_model, row.embedding_version, row.embedding_dimension = metadata
            await session.flush()
        return _question_from_row(row)

    async def lookup_answers(
        self,
        session: AsyncSession,
        *,
        question: KnowledgeQuestion,
        limit: int,
        exclude_attempt_id: str | None = None,
    ) -> list[QuestionEvidenceLink]:
        if limit < 1:
            raise ValueError("lookup limit must be >= 1")
        query = (
            select(KnowledgeQuestionEvidenceLink)
            .options(
                selectinload(KnowledgeQuestionEvidenceLink.passage).selectinload(
                    EvidencePassage.source
                )
            )
            .where(KnowledgeQuestionEvidenceLink.question_id == question.id)
        )
        if exclude_attempt_id is not None:
            query = query.where(
                or_(
                    KnowledgeQuestionEvidenceLink.source_attempt_id.is_(None),
                    KnowledgeQuestionEvidenceLink.source_attempt_id
                    != exclude_attempt_id,
                )
            )
        result = await session.execute(query.limit(limit))
        return [_link_from_row(row) for row in result.scalars()]

    async def upsert_answer(
        self,
        session: AsyncSession,
        link: QuestionEvidenceLink,
    ) -> QuestionEvidenceLink:
        result = await session.execute(
            select(KnowledgeQuestionEvidenceLink)
            .options(
                selectinload(KnowledgeQuestionEvidenceLink.passage).selectinload(
                    EvidencePassage.source
                )
            )
            .where(
                KnowledgeQuestionEvidenceLink.question_id == link.question_id,
                KnowledgeQuestionEvidenceLink.evidence_ref == link.evidence_ref,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = KnowledgeQuestionEvidenceLink(
                id=uuid4().hex,
                question_id=link.question_id,
                evidence_ref=link.evidence_ref,
                passage_id=link.passage_id,
                relation=link.relation or ANSWERED_BY,
                title=None,
                excerpt=None,
                locator=None,
                source_id=None,
                source_url=None,
                source_type=None,
                provider=None,
                provenance=dict(link.provenance),
                retrieved_at=link.retrieved_at,
                observed_at=link.observed_at,
                freshness=link.freshness,
                version=link.version,
                visibility=link.visibility,
                source_attempt_id=link.source_attempt_id,
            )
            session.add(row)
            await session.flush()
            return link
        _apply_link(row, link)
        await session.flush()
        return link


def _apply_link(row: KnowledgeQuestionEvidenceLink, link: QuestionEvidenceLink) -> None:
    row.relation = link.relation or row.relation
    if link.passage_id is not None:
        row.passage_id = link.passage_id
    if link.passage_id is None and link.title is not None:
        row.title = link.title
    if link.passage_id is None and link.excerpt is not None:
        row.excerpt = link.excerpt
    if link.passage_id is None and link.locator is not None:
        row.locator = link.locator
    if link.passage_id is None and link.source_id is not None:
        row.source_id = link.source_id
    if link.passage_id is None and link.source_url is not None:
        row.source_url = link.source_url
    if link.passage_id is None and link.source_type is not None:
        row.source_type = link.source_type
    if link.passage_id is None and link.provider is not None:
        row.provider = link.provider
    if link.provenance:
        row.provenance = dict(link.provenance)
    if link.retrieved_at is not None:
        row.retrieved_at = link.retrieved_at
    if link.observed_at is not None:
        row.observed_at = link.observed_at
    row.freshness = link.freshness
    if link.version is not None:
        row.version = link.version
    row.visibility = link.visibility
    if link.source_attempt_id is not None:
        row.source_attempt_id = link.source_attempt_id


def _question_from_row(row: KnowledgeQuestionRow) -> KnowledgeQuestion:
    return KnowledgeQuestion(
        id=row.id,
        identity_key=row.identity_key,
        normalized_text=row.normalized_text,
        display_text=row.display_text,
        scope=KnowledgeQuestionScope(
            visibility=row.visibility,  # type: ignore[arg-type]
            customer_id=row.customer_id,
        ),
        embedding_model=row.embedding_model,
        embedding_version=row.embedding_version,
        embedding_dimension=row.embedding_dimension,
        created_at=row.created_at,
    )


def _link_from_row(row: KnowledgeQuestionEvidenceLink) -> QuestionEvidenceLink:
    freshness: Freshness = row.freshness  # type: ignore[assignment]
    passage = row.passage
    source = passage.source if passage is not None else None
    provenance = dict(passage.provenance or {}) if passage is not None else {}
    provenance.update(dict(row.provenance or {}))
    return QuestionEvidenceLink(
        question_id=row.question_id,
        evidence_ref=row.evidence_ref,
        passage_id=row.passage_id,
        relation=row.relation,
        title=source.title if source is not None else row.title,
        excerpt=passage.excerpt if passage is not None else row.excerpt,
        locator=passage.locator if passage is not None else row.locator,
        source_id=passage.source_ref if passage is not None else row.source_id,
        source_url=source.source_url if source is not None else row.source_url,
        source_type=source.source_type if source is not None else row.source_type,
        provider=source.provider if source is not None else row.provider,
        provenance=provenance,
        retrieved_at=passage.retrieved_at if passage is not None else row.retrieved_at,
        observed_at=row.observed_at,
        freshness=freshness,
        version=row.version,
        visibility=row.visibility,
        source_attempt_id=row.source_attempt_id,
    )
