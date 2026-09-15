"""In-process QuestionEvidenceGraph for tests. Same contract as SQL / Graphiti."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.research.knowledge_question import (
    ExactQuestionIdentityMatcher,
    KnowledgeQuestion,
    KnowledgeQuestionScope,
    QuestionIdentity,
    QuestionIdentityMatcher,
)
from app.services.research.question_graph import (
    QuestionEvidenceLink,
)


class InMemoryQuestionEvidenceGraph:
    def __init__(
        self,
        *,
        matcher: QuestionIdentityMatcher | None = None,
    ) -> None:
        self._matcher = matcher or ExactQuestionIdentityMatcher()
        self._questions: dict[tuple[str, str], KnowledgeQuestion] = {}
        self._links: dict[tuple[str, str], QuestionEvidenceLink] = {}

    def questions(self) -> list[KnowledgeQuestion]:
        return list(self._questions.values())

    def links(self) -> list[QuestionEvidenceLink]:
        return list(self._links.values())

    async def match_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion | None:
        del session
        exact = self._questions.get((scope.namespace, identity.identity_key))
        if exact is not None:
            return exact
        namespace_rows = [
            row for row in self._questions.values() if row.scope.namespace == scope.namespace
        ]
        return await self._matcher.match(
            normalized_text=identity.normalized_text,
            identity_key=identity.identity_key,
            candidates=namespace_rows,
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
        question = KnowledgeQuestion(
            id=uuid4().hex,
            identity_key=identity.identity_key,
            normalized_text=identity.normalized_text,
            display_text=identity.display_text,
            scope=scope,
        )
        self._questions[(scope.namespace, identity.identity_key)] = question
        return question

    async def lookup_answers(
        self,
        session: AsyncSession,
        *,
        question: KnowledgeQuestion,
        limit: int,
        exclude_attempt_id: str | None = None,
    ) -> list[QuestionEvidenceLink]:
        del session
        if limit < 1:
            raise ValueError("lookup limit must be >= 1")
        rows = [
            link
            for (question_id, _ref), link in self._links.items()
            if question_id == question.id
            and (
                exclude_attempt_id is None
                or link.source_attempt_id != exclude_attempt_id
            )
        ]
        return rows[:limit]

    async def upsert_answer(
        self,
        session: AsyncSession,
        link: QuestionEvidenceLink,
    ) -> QuestionEvidenceLink:
        del session
        key = (link.question_id, link.evidence_ref)
        previous = self._links.get(key)
        if previous is None:
            self._links[key] = link
            return link
        merged = QuestionEvidenceLink(
            question_id=previous.question_id,
            evidence_ref=previous.evidence_ref,
            relation=link.relation,
            title=link.title if link.title is not None else previous.title,
            excerpt=link.excerpt if link.excerpt is not None else previous.excerpt,
            locator=link.locator if link.locator is not None else previous.locator,
            source_id=link.source_id if link.source_id is not None else previous.source_id,
            source_url=(
                link.source_url if link.source_url is not None else previous.source_url
            ),
            source_type=(
                link.source_type if link.source_type is not None else previous.source_type
            ),
            provider=link.provider if link.provider is not None else previous.provider,
            provenance=link.provenance or previous.provenance,
            retrieved_at=link.retrieved_at or previous.retrieved_at,
            observed_at=link.observed_at or previous.observed_at,
            freshness=link.freshness,
            version=link.version if link.version is not None else previous.version,
            visibility=link.visibility,
            source_attempt_id=link.source_attempt_id or previous.source_attempt_id,
        )
        self._links[key] = merged
        return merged
