"""Content-addressed raw documents, question-specific interpretations and claims."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.services.legal_research_result import LegalResearchResult


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def raw_source_id(source_key: str, raw_text: str) -> str:
    return _digest(source_key, hashlib.sha256(raw_text.encode("utf-8")).hexdigest())


def domain_result_id(raw_id: str, research_need_id: str, result: LegalResearchResult) -> str:
    return _digest(
        raw_id,
        research_need_id,
        _canonical_json(result.model_dump(mode="json", exclude={"raw_text"})),
    )


@dataclass(frozen=True)
class DomainClaim:
    id: str
    domain_result_id: str
    research_need_id: str
    predicate: str
    value: dict[str, object]
    relation: str
    citations: list[dict[str, object]]


def legal_claims(
    result: LegalResearchResult, *, result_id: str, research_need_id: str
) -> list[DomainClaim]:
    """Project explicit structured interpretation fields; never infer from prose."""
    analysis = result.case_law or result.preparatory_work or result.statute
    assert analysis is not None
    citations = [citation.model_dump(mode="json") for citation in analysis.citations]
    claims: list[DomainClaim] = []

    def add(
        predicate: str, value: object, *, support: list[dict[str, object]] | None = None
    ) -> None:
        if value is None or value == "" or value == [] or value == "unknown":
            return
        structured = {"value": value}
        claims.append(
            DomainClaim(
                id=_digest(result_id, predicate, _canonical_json(structured)),
                domain_result_id=result_id,
                research_need_id=research_need_id,
                predicate=predicate,
                value=structured,
                relation=result.relation.relation,
                citations=citations if support is None else support,
            )
        )

    if result.case_law is not None:
        case = result.case_law
        add("legal.adjustment_requested", case.adjustment_requested)
        holding_citations = (
            [citation.model_dump(mode="json") for citation in case.authoritative_holding.citations]
            if case.authoritative_holding
            else []
        )
        if case.holding_status == "established":
            add("legal.adjustment_granted", case.adjustment_granted, support=holding_citations)
            add("legal.outcome", case.outcome, support=holding_citations)
        add("legal.holding_status", case.holding_status)
        add("legal.adjusted_term_type", case.adjusted_term_type)
        add("legal.contract_type", case.contract_type)
        add("legal.party_context", case.party_context)
        for factor in case.decisive_factors:
            add("legal.decisive_factor", factor)
        for argument in case.rejected_arguments:
            add("legal.rejected_argument", argument)
        add("legal.rule_or_principle", case.rule_or_principle)
        for provision in case.applied_provisions:
            add("legal.applied_provision", provision)
    elif result.preparatory_work is not None:
        preparatory = result.preparatory_work
        if preparatory.attribution:
            attribution = preparatory.attribution
            role_support = [citation.model_dump(mode="json") for citation in attribution.role_citations]
            add("legal.source_speaker", attribution.speaker, support=role_support)
            add("legal.source_text_role", attribution.text_role, support=role_support)
        add("legal.legislative_intent", preparatory.legislative_intent)
        for guidance in preparatory.interpretation_guidance:
            add("legal.interpretation_guidance", guidance)
        for policy in preparatory.policy_considerations:
            add("legal.policy_consideration", policy)
        for example in preparatory.examples:
            add("legal.example", example)
        for provision in preparatory.provisions:
            add("legal.provision", provision)
    else:
        statute = result.statute
        assert statute is not None
        add("legal.operative_rule", statute.operative_rule)
        for condition in statute.conditions:
            add("legal.condition", condition)
        for effect in statute.legal_effects:
            add("legal.legal_effect", effect)
        for exception in statute.exceptions:
            add("legal.exception", exception)
        for reference in statute.cross_references:
            add("legal.cross_reference", reference)
    for limitation in analysis.limitations if hasattr(analysis, "limitations") else []:
        add("legal.limitation", limitation)
    return claims
