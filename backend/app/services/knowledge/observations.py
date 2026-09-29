"""Typed source-quality and research observations. Not durable knowledge claims."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.knowledge_observation import KnowledgeObservationRecord
from app.services.knowledge.identity import knowledge_observation_id
from app.services.knowledge.persistence_class import (
    RESEARCH_OBSERVATION,
    SOURCE_QUALITY,
    PersistenceClass,
    PersistenceClassError,
    require_persistence_class,
)
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeTenantScope,
    persist_scope_fields,
    require_persist_scope,
)


class KnowledgeObservationError(RuntimeError):
    """An observation cannot be stored."""


@dataclass(frozen=True)
class ObservationSeed:
    observation_class: str
    kind: str
    document_id: str
    document_version_id: str
    statement_normalized: str
    question_key: str = ""
    extra: dict[str, object] | None = None


@dataclass(frozen=True)
class KnowledgeObservation:
    id: str
    customer_id: int | None
    observation_class: PersistenceClass
    kind: str
    document_id: str
    document_version_id: str
    question_key: str
    statement_normalized: str
    extra: dict[str, object]
    scope_type: str = SCOPE_CUSTOMER

    @property
    def scope(self) -> KnowledgeTenantScope:
        return require_persist_scope(scope_type=self.scope_type, customer_id=self.customer_id)


def knowledge_observation(
    seed: ObservationSeed,
    scope: KnowledgeTenantScope,
) -> KnowledgeObservation:
    try:
        classified = require_persistence_class(seed.observation_class)
    except PersistenceClassError as exc:
        raise KnowledgeObservationError(str(exc)) from exc
    if classified == "domain_knowledge":
        raise KnowledgeObservationError("domain_knowledge is not an observation class")
    resolved = require_persist_scope(scope=scope)
    normalized = " ".join(seed.statement_normalized.split())
    if not normalized:
        raise KnowledgeObservationError("observation statement is empty")
    question = seed.question_key.strip()
    if classified == RESEARCH_OBSERVATION and not question:
        raise KnowledgeObservationError("research_observation requires question_key")
    if classified == SOURCE_QUALITY:
        question = ""
    return KnowledgeObservation(
        id=knowledge_observation_id(
            scope_key=resolved.scope_key,
            observation_class=classified,
            kind=seed.kind.strip(),
            document_version_id=seed.document_version_id,
            question_key=question,
            statement_normalized=normalized,
        ),
        customer_id=resolved.customer_id,
        scope_type=resolved.scope_type,
        observation_class=classified,
        kind=seed.kind.strip(),
        document_id=seed.document_id,
        document_version_id=seed.document_version_id,
        question_key=question,
        statement_normalized=normalized,
        extra=dict(seed.extra or {}),
    )


async def persist_knowledge_observations(
    session: AsyncSession,
    observations: Sequence[KnowledgeObservation],
) -> list[tuple[KnowledgeObservationRecord, bool]]:
    return [await persist_knowledge_observation(session, item) for item in observations]


async def persist_knowledge_observation(
    session: AsyncSession,
    observation: KnowledgeObservation,
) -> tuple[KnowledgeObservationRecord, bool]:
    row = await session.get(KnowledgeObservationRecord, observation.id)
    if row is not None:
        return row, True
    row = KnowledgeObservationRecord(
        id=observation.id,
        observation_class=observation.observation_class,
        kind=observation.kind,
        document_id=observation.document_id,
        document_version_id=observation.document_version_id,
        question_key=observation.question_key,
        statement_normalized=observation.statement_normalized,
        extra=observation.extra,
        **persist_scope_fields(observation.scope),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        winner = await session.get(KnowledgeObservationRecord, observation.id)
        if winner is None:
            winner = await _lookup_observation(session, observation)
        if winner is None:
            raise
        return winner, True
    return row, False


async def _lookup_observation(
    session: AsyncSession,
    observation: KnowledgeObservation,
) -> KnowledgeObservationRecord | None:
    return (
        await session.execute(
            select(KnowledgeObservationRecord).where(
                KnowledgeObservationRecord.scope_key == observation.scope.scope_key,
                KnowledgeObservationRecord.observation_class == observation.observation_class,
                KnowledgeObservationRecord.kind == observation.kind,
                KnowledgeObservationRecord.document_version_id == observation.document_version_id,
                KnowledgeObservationRecord.question_key == observation.question_key,
                KnowledgeObservationRecord.statement_normalized == observation.statement_normalized,
            )
        )
    ).scalar_one_or_none()
