"""Project legal interpretations onto knowledge Claims grounded in TextUnits."""

from __future__ import annotations

from collections.abc import Sequence

from app.database.models import TextUnitRecord
from app.llm.legal_research import LegalDomainExtractionError
from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    knowledge_claim_id,
    supporting_text_unit_ids_for_quote,
)
from app.services.legal_research_result import LegalResearchResult
from app.services.research_domain_results import legal_claims


def ground_legal_claims(
    result: LegalResearchResult,
    units: Sequence[TextUnitRecord],
    *,
    customer_id: int,
    research_need_id: str,
    result_id: str,
) -> list[KnowledgeClaim]:
    """Each legal claim with citations must SUPPORTED_BY at least one TextUnit."""
    if not units:
        raise LegalDomainExtractionError(
            "cannot ground legal claims without TextUnits",
            category="citation_grounding_failed",
        )
    document_id = units[0].document_id
    document_version_id = units[0].document_version_id
    grounded: list[KnowledgeClaim] = []
    for domain_claim in legal_claims(
        result, result_id=result_id, research_need_id=research_need_id
    ):
        quotes = [
            str(citation.get("quote") or "").strip()
            for citation in domain_claim.citations
            if str(citation.get("quote") or "").strip()
        ]
        if not quotes:
            continue
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
                f"legal claim {domain_claim.predicate} has no TextUnit support",
                category="citation_grounding_failed",
            )
        grounded.append(
            KnowledgeClaim(
                id=knowledge_claim_id(
                    document_version_id=document_version_id,
                    predicate=domain_claim.predicate,
                    value=domain_claim.value,
                ),
                customer_id=customer_id,
                document_id=document_id,
                document_version_id=document_version_id,
                predicate=domain_claim.predicate,
                value=domain_claim.value,
                supporting_text_unit_ids=tuple(support),
            )
        )
    if not grounded:
        raise LegalDomainExtractionError(
            "legal interpretation produced no TextUnit-grounded claims",
            category="citation_grounding_failed",
        )
    return grounded
