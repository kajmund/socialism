"""Legal entities and relations on top of the generic knowledge graph."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.knowledge.claims import SUPPORTED_BY, KnowledgeClaim
from app.services.knowledge.entities import KnowledgeEntity, knowledge_entity
from app.services.knowledge.relationships import (
    ABOUT,
    SAME_AS,
    KnowledgeRelationship,
    knowledge_relationship,
)
from app.services.legal_research_result import LegalResearchResult

LEGAL_CITES = "legal.cites"
LEGAL_APPLIES = "legal.applies"
LEGAL_DECIDED_BY = "legal.decided_by"

LEGAL_SOURCE = "legal.source"
LEGAL_COURT = "legal.court"
LEGAL_ISSUE = "legal.issue"
LEGAL_PROVISION = "legal.provision"


def ground_legal_graph(
    result: LegalResearchResult,
    claims: Sequence[KnowledgeClaim],
    *,
    customer_id: int,
    document_id: str,
) -> tuple[list[KnowledgeEntity], list[KnowledgeRelationship]]:
    """Project explicit legal fields onto Entity / Relationship. No prose inference."""
    entities: dict[str, KnowledgeEntity] = {}
    edges: dict[str, KnowledgeRelationship] = {}

    def add_entity(entity: KnowledgeEntity) -> KnowledgeEntity:
        entities[entity.id] = entity
        return entity

    def add_edge(edge: KnowledgeRelationship) -> None:
        edges[edge.id] = edge

    source = add_entity(
        knowledge_entity(
            customer_id=customer_id,
            entity_type=LEGAL_SOURCE,
            key=result.source.canonical_uri,
            name=result.source.title,
            extra={"kind": result.source.kind, "canonical_uri": result.source.canonical_uri},
        )
    )
    add_edge(
        knowledge_relationship(
            customer_id=customer_id,
            relation=ABOUT,
            from_kind="document",
            from_id=document_id,
            to_kind="entity",
            to_id=source.id,
        )
    )
    identifier = (result.source.identifier or "").strip()
    if identifier:
        alias = add_entity(
            knowledge_entity(
                customer_id=customer_id,
                entity_type=LEGAL_SOURCE,
                key=identifier,
                name=identifier,
                extra={"identifier": identifier},
            )
        )
        if alias.id != source.id:
            add_edge(
                knowledge_relationship(
                    customer_id=customer_id,
                    relation=SAME_AS,
                    from_kind="entity",
                    from_id=source.id,
                    to_kind="entity",
                    to_id=alias.id,
                )
            )

    court = _court_entity(result, customer_id=customer_id)
    if court is not None:
        add_entity(court)
        add_edge(
            knowledge_relationship(
                customer_id=customer_id,
                relation=LEGAL_DECIDED_BY,
                from_kind="entity",
                from_id=source.id,
                to_kind="entity",
                to_id=court.id,
            )
        )

    issue = _issue_entity(result, customer_id=customer_id)
    if issue is not None:
        add_entity(issue)

    provisions = _provision_entities(result, customer_id=customer_id)
    for provision in provisions:
        add_entity(provision)
        add_edge(
            knowledge_relationship(
                customer_id=customer_id,
                relation=LEGAL_APPLIES,
                from_kind="entity",
                from_id=source.id,
                to_kind="entity",
                to_id=provision.id,
            )
        )

    for citation in _citation_uris(result):
        cited = add_entity(
            knowledge_entity(
                customer_id=customer_id,
                entity_type=LEGAL_SOURCE,
                key=citation,
                name=citation,
                extra={"canonical_uri": citation},
            )
        )
        if cited.id == source.id:
            continue
        add_edge(
            knowledge_relationship(
                customer_id=customer_id,
                relation=LEGAL_CITES,
                from_kind="entity",
                from_id=source.id,
                to_kind="entity",
                to_id=cited.id,
            )
        )

    for claim in claims:
        add_edge(
            knowledge_relationship(
                customer_id=customer_id,
                relation=ABOUT,
                from_kind="claim",
                from_id=claim.id,
                to_kind="entity",
                to_id=source.id,
            )
        )
        if issue is not None:
            add_edge(
                knowledge_relationship(
                    customer_id=customer_id,
                    relation=ABOUT,
                    from_kind="claim",
                    from_id=claim.id,
                    to_kind="entity",
                    to_id=issue.id,
                )
            )
        if court is not None:
            add_edge(
                knowledge_relationship(
                    customer_id=customer_id,
                    relation=ABOUT,
                    from_kind="claim",
                    from_id=claim.id,
                    to_kind="entity",
                    to_id=court.id,
                )
            )
        for unit_id in claim.supporting_text_unit_ids:
            add_edge(
                knowledge_relationship(
                    customer_id=customer_id,
                    relation=SUPPORTED_BY,
                    from_kind="claim",
                    from_id=claim.id,
                    to_kind="text_unit",
                    to_id=unit_id,
                )
            )
        if claim.predicate == "legal.applied_provision":
            provision_name = _claim_value_text(claim.value)
            if provision_name:
                provision = add_entity(
                    knowledge_entity(
                        customer_id=customer_id,
                        entity_type=LEGAL_PROVISION,
                        key=provision_name,
                        name=provision_name,
                    )
                )
                add_edge(
                    knowledge_relationship(
                        customer_id=customer_id,
                        relation=LEGAL_APPLIES,
                        from_kind="claim",
                        from_id=claim.id,
                        to_kind="entity",
                        to_id=provision.id,
                    )
                )
    return list(entities.values()), list(edges.values())


def _court_entity(
    result: LegalResearchResult,
    *,
    customer_id: int,
) -> KnowledgeEntity | None:
    name = (result.source.court or "").strip()
    if not name and result.case_law is not None and result.case_law.authoritative_holding:
        name = result.case_law.authoritative_holding.court_level
    if not name or name == "unknown":
        return None
    return knowledge_entity(
        customer_id=customer_id,
        entity_type=LEGAL_COURT,
        key=name,
        name=name,
    )


def _issue_entity(
    result: LegalResearchResult,
    *,
    customer_id: int,
) -> KnowledgeEntity | None:
    if result.case_law is None:
        return None
    issue = result.case_law.legal_issue.strip()
    if not issue:
        return None
    return knowledge_entity(
        customer_id=customer_id,
        entity_type=LEGAL_ISSUE,
        key=issue,
        name=issue,
    )


def _provision_entities(
    result: LegalResearchResult,
    *,
    customer_id: int,
) -> list[KnowledgeEntity]:
    if result.case_law is None:
        return []
    entities: list[KnowledgeEntity] = []
    for provision in result.case_law.applied_provisions:
        text = provision.strip()
        if not text:
            continue
        entities.append(
            knowledge_entity(
                customer_id=customer_id,
                entity_type=LEGAL_PROVISION,
                key=text,
                name=text,
            )
        )
    return entities


def _citation_uris(result: LegalResearchResult) -> list[str]:
    analysis = result.case_law or result.preparatory_work or result.statute
    if analysis is None:
        return []
    uris: list[str] = []
    seen: set[str] = set()
    for citation in analysis.citations:
        uri = citation.source_uri.strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        uris.append(uri)
    return uris


def _claim_value_text(value: dict[str, object]) -> str:
    raw = value.get("value")
    if isinstance(raw, str):
        return raw.strip()
    return ""
