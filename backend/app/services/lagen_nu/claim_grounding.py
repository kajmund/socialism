"""Project legal interpretations onto knowledge Claims grounded in TextUnits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.database.models import TextUnitRecord
from app.llm.legal_research import LegalDomainExtractionError
from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    knowledge_claim,
    supporting_text_unit_ids_for_quote,
)
from app.services.knowledge.observations import KnowledgeObservation, knowledge_observation
from app.services.knowledge.persistence_class import (
    DOMAIN_KNOWLEDGE,
    RESEARCH_OBSERVATION,
    SOURCE_QUALITY,
    classify_persistence,
)
from app.services.knowledge.scope import customer_scope
from app.services.legal_research_result import LegalResearchResult
from app.services.research.knowledge_question import research_question_key
from app.services.research_domain_results import legal_claims


@dataclass(frozen=True)
class GroundedLegalKnowledge:
    claims: tuple[KnowledgeClaim, ...]
    observations: tuple[KnowledgeObservation, ...]


def ground_legal_claims(
    result: LegalResearchResult,
    units: Sequence[TextUnitRecord],
    *,
    customer_id: int,
    research_need_id: str,
    result_id: str,
    question: str = "",
) -> list[KnowledgeClaim]:
    return list(
        ground_legal_extraction(
            result,
            units,
            customer_id=customer_id,
            research_need_id=research_need_id,
            result_id=result_id,
            question=question,
        ).claims
    )


def ground_legal_extraction(
    result: LegalResearchResult,
    units: Sequence[TextUnitRecord],
    *,
    customer_id: int,
    research_need_id: str,
    result_id: str,
    question: str = "",
) -> GroundedLegalKnowledge:
    """Ground domain claims. Source-quality and question-gap notes stay observations."""
    if not units:
        raise LegalDomainExtractionError(
            "cannot ground legal claims without TextUnits",
            category="citation_grounding_failed",
        )
    document_id = units[0].document_id
    document_version_id = units[0].document_version_id
    scope = customer_scope(customer_id)
    grounded: list[KnowledgeClaim] = []
    observations: list[KnowledgeObservation] = list(
        legal_source_observations(
            result,
            document_id=document_id,
            document_version_id=document_version_id,
            customer_id=customer_id,
            question=question,
        )
    )
    had_domain = False
    for domain_claim in legal_claims(
        result, result_id=result_id, research_need_id=research_need_id
    ):
        decision = classify_persistence(value=domain_claim.value)
        if decision.persistence_class != DOMAIN_KNOWLEDGE:
            observations.append(
                knowledge_observation(
                    scope=scope,
                    observation_class=decision.persistence_class,
                    kind=decision.kind,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    statement_normalized=decision.statement_normalized or domain_claim.predicate,
                    question_key=research_question_key(question) if question.strip() else "",
                    extra={"predicate": domain_claim.predicate},
                )
            )
            continue
        had_domain = True
        claim = _ground_domain_claim(
            domain_claim.predicate,
            domain_claim.value,
            domain_claim.citations,
            units,
            customer_id=customer_id,
            document_id=document_id,
            document_version_id=document_version_id,
        )
        if claim is not None:
            grounded.append(claim)
    if had_domain and not grounded:
        raise LegalDomainExtractionError(
            "legal interpretation produced no TextUnit-grounded claims",
            category="citation_grounding_failed",
        )
    return GroundedLegalKnowledge(claims=tuple(grounded), observations=tuple(observations))


def legal_source_observations(
    result: LegalResearchResult,
    *,
    document_id: str,
    document_version_id: str,
    customer_id: int,
    question: str = "",
) -> list[KnowledgeObservation]:
    scope = customer_scope(customer_id)
    question_key = research_question_key(question) if question.strip() else ""
    items: list[KnowledgeObservation] = []
    if result.truncated:
        items.append(
            knowledge_observation(
                scope=scope,
                observation_class=SOURCE_QUALITY,
                kind="truncation",
                document_id=document_id,
                document_version_id=document_version_id,
                statement_normalized="source text was truncated during retrieval",
                extra={"truncated": True},
            )
        )
    if result.relation.relation == "irrelevant":
        items.append(
            knowledge_observation(
                scope=scope,
                observation_class=RESEARCH_OBSERVATION,
                kind="does_not_answer",
                document_id=document_id,
                document_version_id=document_version_id,
                statement_normalized="source does not answer the research question",
                question_key=question_key,
                extra={"relation": result.relation.relation},
            )
        )
    return items


def _ground_domain_claim(
    predicate: str,
    value: dict[str, object],
    citations: list[dict[str, object]],
    units: Sequence[TextUnitRecord],
    *,
    customer_id: int,
    document_id: str,
    document_version_id: str,
) -> KnowledgeClaim | None:
    quotes = [
        str(citation.get("quote") or "").strip()
        for citation in citations
        if str(citation.get("quote") or "").strip()
    ]
    if not quotes:
        return None
    support: list[str] = []
    seen: set[str] = set()
    for quote in quotes:
        try:
            unit_ids = supporting_text_unit_ids_for_quote(quote, units)
        except KnowledgeClaimError as exc:
            raise LegalDomainExtractionError(
                str(exc),
                category="citation_grounding_failed",
            ) from exc
        for unit_id in unit_ids:
            if unit_id not in seen:
                seen.add(unit_id)
                support.append(unit_id)
    if not support:
        raise LegalDomainExtractionError(
            f"legal claim {predicate} has no TextUnit support",
            category="citation_grounding_failed",
        )
    return knowledge_claim(
        customer_id=customer_id,
        document_id=document_id,
        document_version_id=document_version_id,
        predicate=predicate,
        value=value,
        supporting_text_unit_ids=support,
    )
