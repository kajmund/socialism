"""Typed source-quality and research observations. Not durable knowledge claims."""

from __future__ import annotations


from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.identity import knowledge_observation_id
from app.services.knowledge.persistence_class import (
    RESEARCH_OBSERVATION,
    SOURCE_QUALITY,
    PersistenceClass,
    PersistenceClassError,
    require_persistence_class,
)
from app.services.knowledge import owner_graph_mirror
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeTenantScope,
    require_persist_scope,
    scope_from_row,
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


@dataclass(frozen=True)
class PersistedObservation:
    """Outcome of an observation write. The graph node uses the domain id."""

    id: str


async def persist_knowledge_observations(
    session: AsyncSession,
    observations: Sequence[KnowledgeObservation],
) -> list[tuple[PersistedObservation, bool]]:
    return [await persist_knowledge_observation(session, item) for item in observations]


async def persist_knowledge_observation(
    session: AsyncSession,
    observation: KnowledgeObservation,
) -> tuple[PersistedObservation, bool]:
    """Write the observation to OverGraph. Provenance stays a database-read check."""
    await _validate_observation_provenance(session, observation)
    owner = get_owner_runtime().require_client()
    existing = await owner_graph_mirror.observation_exists(owner, observation)
    await owner_graph_mirror.mirror_observation(owner, observation)
    return PersistedObservation(id=observation.id), existing


async def _validate_observation_provenance(
    session: AsyncSession,
    observation: KnowledgeObservation,
) -> None:
    document = await session.get(CanonicalDocumentRecord, observation.document_id)
    version = await session.get(DocumentVersionRecord, observation.document_version_id)
    if document is None or version is None:
        raise KnowledgeObservationError("observation provenance is missing")
    if version.document_id != document.id:
        raise KnowledgeObservationError("observation version does not belong to document")
    document_scope = scope_from_row(document)
    version_scope = scope_from_row(version)
    if document_scope != version_scope:
        raise KnowledgeObservationError("observation document/version scopes differ")
    target = observation.scope
    if document_scope.scope_type == "customer" and document_scope != target:
        raise KnowledgeObservationError("observation cannot reference another tenant")
    if target.scope_type == "shared" and document_scope.scope_type != "shared":
        raise KnowledgeObservationError("shared observation cannot reference customer provenance")


