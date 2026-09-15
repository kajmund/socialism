"""Graphiti adapter for Question → Evidence. Research code uses domain types only.

The official Graphiti SDK is not a required runtime dependency. This module
owns Graphiti-shaped node/edge payloads so a later Neo4j driver can be
plugged in without leaking SDK types into the research loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
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
    ANSWERED_BY,
    BESVARAS_AV,
    EVIDENCE_REF_NODE_LABEL,
    QUESTION_NODE_LABEL,
    QuestionEvidenceGraphError,
    QuestionEvidenceLink,
)


@dataclass(frozen=True)
class GraphitiNode:
    uuid: str
    name: str
    labels: tuple[str, ...]
    attributes: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", tuple(self.labels))
        object.__setattr__(self, "attributes", dict(self.attributes))


@dataclass(frozen=True)
class GraphitiEdge:
    uuid: str
    source_uuid: str
    target_uuid: str
    name: str
    attributes: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", dict(self.attributes))


class GraphitiClient(Protocol):
    """Subset of Graphiti used by v1. No multi-hop search."""

    async def upsert_node(self, node: GraphitiNode) -> GraphitiNode: ...

    async def upsert_edge(self, edge: GraphitiEdge) -> GraphitiEdge: ...

    async def find_nodes(
        self,
        *,
        labels: tuple[str, ...],
        attributes: dict[str, object],
        limit: int,
    ) -> list[GraphitiNode]: ...

    async def edges_from(
        self,
        source_uuid: str,
        *,
        names: tuple[str, ...],
        limit: int,
    ) -> list[GraphitiEdge]: ...

    async def get_node(self, uuid: str) -> GraphitiNode | None: ...


class InMemoryGraphitiClient:
    """Test double for the Graphiti client. Not a second research engine."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphitiNode] = {}
        self.edges: dict[str, GraphitiEdge] = {}
        self._edge_keys: dict[tuple[str, str, str], str] = {}

    async def upsert_node(self, node: GraphitiNode) -> GraphitiNode:
        self.nodes[node.uuid] = node
        return node

    async def upsert_edge(self, edge: GraphitiEdge) -> GraphitiEdge:
        key = (edge.source_uuid, edge.target_uuid, edge.name)
        existing_id = self._edge_keys.get(key)
        if existing_id is not None:
            previous = self.edges[existing_id]
            merged = GraphitiEdge(
                uuid=previous.uuid,
                source_uuid=previous.source_uuid,
                target_uuid=previous.target_uuid,
                name=edge.name,
                attributes={**previous.attributes, **edge.attributes},
            )
            self.edges[previous.uuid] = merged
            return merged
        self._edge_keys[key] = edge.uuid
        self.edges[edge.uuid] = edge
        return edge

    async def find_nodes(
        self,
        *,
        labels: tuple[str, ...],
        attributes: dict[str, object],
        limit: int,
    ) -> list[GraphitiNode]:
        wanted = set(labels)
        matched: list[GraphitiNode] = []
        for node in self.nodes.values():
            if wanted and not wanted.intersection(node.labels):
                continue
            if any(node.attributes.get(key) != value for key, value in attributes.items()):
                continue
            matched.append(node)
            if len(matched) >= limit:
                break
        return matched

    async def edges_from(
        self,
        source_uuid: str,
        *,
        names: tuple[str, ...],
        limit: int,
    ) -> list[GraphitiEdge]:
        allowed = set(names)
        matched: list[GraphitiEdge] = []
        for edge in self.edges.values():
            if edge.source_uuid != source_uuid:
                continue
            if allowed and edge.name not in allowed:
                continue
            matched.append(edge)
            if len(matched) >= limit:
                break
        return matched

    async def get_node(self, uuid: str) -> GraphitiNode | None:
        return self.nodes.get(uuid)


def question_to_graphiti_node(question: KnowledgeQuestion) -> GraphitiNode:
    return GraphitiNode(
        uuid=question.id,
        name=question.display_text,
        labels=(QUESTION_NODE_LABEL,),
        attributes={
            "identity_key": question.identity_key,
            "normalized_text": question.normalized_text,
            "display_text": question.display_text,
            "namespace": question.scope.namespace,
            "visibility": question.scope.visibility,
            "customer_id": question.scope.customer_id,
            "embedding_model": question.embedding_model,
            "embedding_version": question.embedding_version,
            "embedding_dimension": question.embedding_dimension,
        },
    )


def question_from_graphiti_node(node: GraphitiNode) -> KnowledgeQuestion:
    attrs = node.attributes
    visibility = str(attrs.get("visibility") or "tenant")
    if visibility not in {"public", "tenant"}:
        raise QuestionEvidenceGraphError(
            f"Graphiti question node has invalid visibility: {visibility}"
        )
    customer_raw = attrs.get("customer_id")
    customer_id = int(customer_raw) if customer_raw is not None else None
    dimension = attrs.get("embedding_dimension")
    return KnowledgeQuestion(
        id=node.uuid,
        identity_key=str(attrs.get("identity_key") or ""),
        normalized_text=str(attrs.get("normalized_text") or ""),
        display_text=str(attrs.get("display_text") or node.name),
        scope=KnowledgeQuestionScope(
            visibility=visibility,  # type: ignore[arg-type]
            customer_id=customer_id,
        ),
        embedding_model=_optional_str(attrs.get("embedding_model")),
        embedding_version=_optional_str(attrs.get("embedding_version")),
        embedding_dimension=int(dimension) if dimension is not None else None,
    )


def evidence_ref_node(*, evidence_ref: str, link: QuestionEvidenceLink) -> GraphitiNode:
    return GraphitiNode(
        uuid=evidence_ref,
        name=link.title or link.locator or evidence_ref,
        labels=(EVIDENCE_REF_NODE_LABEL,),
        attributes={
            "evidence_ref": evidence_ref,
            "title": link.title,
            "excerpt": link.excerpt,
            "locator": link.locator,
            "source_id": link.source_id,
            "source_url": link.source_url,
            "source_type": link.source_type,
            "provider": link.provider,
            "version": link.version,
            "visibility": link.visibility,
            "source_attempt_id": link.source_attempt_id,
        },
    )


def link_to_graphiti_edge(link: QuestionEvidenceLink) -> GraphitiEdge:
    return GraphitiEdge(
        uuid=f"{link.question_id}:{link.evidence_ref}:{ANSWERED_BY}",
        source_uuid=link.question_id,
        target_uuid=link.evidence_ref,
        name=ANSWERED_BY,
        attributes={
            "relation": ANSWERED_BY,
            "relation_sv": BESVARAS_AV,
            "evidence_ref": link.evidence_ref,
            "title": link.title,
            "excerpt": link.excerpt,
            "locator": link.locator,
            "source_id": link.source_id,
            "source_url": link.source_url,
            "source_type": link.source_type,
            "provider": link.provider,
            "provenance": dict(link.provenance),
            "retrieved_at": _stamp(link.retrieved_at),
            "observed_at": _stamp(link.observed_at),
            "freshness": link.freshness,
            "version": link.version,
            "visibility": link.visibility,
            "source_attempt_id": link.source_attempt_id,
        },
    )


def link_from_graphiti_edge(edge: GraphitiEdge) -> QuestionEvidenceLink:
    attrs = edge.attributes
    freshness = str(attrs.get("freshness") or "unknown")
    if freshness not in {"fresh", "stale", "unknown"}:
        freshness = "unknown"
    provenance = attrs.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return QuestionEvidenceLink(
        question_id=edge.source_uuid,
        evidence_ref=str(attrs.get("evidence_ref") or edge.target_uuid),
        relation=str(attrs.get("relation") or ANSWERED_BY),
        title=_optional_str(attrs.get("title")),
        excerpt=_optional_str(attrs.get("excerpt")),
        locator=_optional_str(attrs.get("locator")),
        source_id=_optional_str(attrs.get("source_id")),
        source_url=_optional_str(attrs.get("source_url")),
        source_type=_optional_str(attrs.get("source_type")),
        provider=_optional_str(attrs.get("provider")),
        provenance=dict(provenance),
        retrieved_at=_parse_stamp(attrs.get("retrieved_at")),
        observed_at=_parse_stamp(attrs.get("observed_at")),
        freshness=freshness,  # type: ignore[arg-type]
        version=_optional_str(attrs.get("version")),
        visibility=str(attrs.get("visibility") or "tenant"),
        source_attempt_id=_optional_str(attrs.get("source_attempt_id")),
    )


class GraphitiQuestionEvidenceGraph:
    """QuestionEvidenceGraph backed by a GraphitiClient. One hop only."""

    def __init__(
        self,
        client: GraphitiClient,
        *,
        matcher: QuestionIdentityMatcher | None = None,
    ) -> None:
        self._client = client
        self._matcher = matcher or ExactQuestionIdentityMatcher()

    async def match_question(
        self,
        session: AsyncSession,
        identity: QuestionIdentity,
        scope: KnowledgeQuestionScope,
    ) -> KnowledgeQuestion | None:
        del session
        try:
            nodes = await self._client.find_nodes(
                labels=(QUESTION_NODE_LABEL,),
                attributes={
                    "namespace": scope.namespace,
                    "identity_key": identity.identity_key,
                },
                limit=1,
            )
            if nodes:
                return question_from_graphiti_node(nodes[0])
            namespace_nodes = await self._client.find_nodes(
                labels=(QUESTION_NODE_LABEL,),
                attributes={"namespace": scope.namespace},
                limit=32,
            )
            candidates = [question_from_graphiti_node(node) for node in namespace_nodes]
            return await self._matcher.match(
                normalized_text=identity.normalized_text,
                identity_key=identity.identity_key,
                candidates=candidates,
            )
        except QuestionEvidenceGraphError:
            raise
        except Exception as exc:
            raise QuestionEvidenceGraphError("Graphiti question match failed") from exc

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
        try:
            await self._client.upsert_node(question_to_graphiti_node(question))
        except QuestionEvidenceGraphError:
            raise
        except Exception as exc:
            raise QuestionEvidenceGraphError("Graphiti question upsert failed") from exc
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
        try:
            edges = await self._client.edges_from(
                question.id,
                names=(ANSWERED_BY, BESVARAS_AV),
                limit=limit,
            )
            links = [link_from_graphiti_edge(edge) for edge in edges]
            if exclude_attempt_id is not None:
                links = [
                    link
                    for link in links
                    if link.source_attempt_id != exclude_attempt_id
                ]
            return links[:limit]
        except QuestionEvidenceGraphError:
            raise
        except Exception as exc:
            raise QuestionEvidenceGraphError("Graphiti answer lookup failed") from exc

    async def upsert_answer(
        self,
        session: AsyncSession,
        link: QuestionEvidenceLink,
    ) -> QuestionEvidenceLink:
        del session
        try:
            await self._client.upsert_node(
                evidence_ref_node(evidence_ref=link.evidence_ref, link=link)
            )
            stored = await self._client.upsert_edge(link_to_graphiti_edge(link))
        except QuestionEvidenceGraphError:
            raise
        except Exception as exc:
            raise QuestionEvidenceGraphError("Graphiti answer upsert failed") from exc
        return link_from_graphiti_edge(stored)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value)


class UnavailableGraphitiClient:
    """Explicit outage. Lookup callers must fall back to providers."""

    async def upsert_node(self, node: GraphitiNode) -> GraphitiNode:
        raise QuestionEvidenceGraphError("Graphiti unavailable")

    async def upsert_edge(self, edge: GraphitiEdge) -> GraphitiEdge:
        raise QuestionEvidenceGraphError("Graphiti unavailable")

    async def find_nodes(
        self,
        *,
        labels: tuple[str, ...],
        attributes: dict[str, object],
        limit: int,
    ) -> list[GraphitiNode]:
        raise QuestionEvidenceGraphError("Graphiti unavailable")

    async def edges_from(
        self,
        source_uuid: str,
        *,
        names: tuple[str, ...],
        limit: int,
    ) -> list[GraphitiEdge]:
        raise QuestionEvidenceGraphError("Graphiti unavailable")

    async def get_node(self, uuid: str) -> GraphitiNode | None:
        raise QuestionEvidenceGraphError("Graphiti unavailable")
