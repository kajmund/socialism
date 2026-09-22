"""Domain extraction must not turn invented quotations into research evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.llm.legal_research import LegalDomainExtractionError, LlmLegalInterpreter
from app.llm.research_assessment import _evidence_payload as assessment_payload
from app.llm.research_completeness import _evidence_payload as completeness_payload
from app.services.execution.snapshots import snapshot_research_evidence
from app.services.knowledge.models import KnowledgeScope
from app.services.legal_research_result import (
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
    StatuteAnalysis,
)
from app.services.research.assessment import (
    AssessableEvidence,
    EvidenceReviewGroup,
    group_evidence_for_review,
)
from app.services.research.models import ResearchContext, research_evidence
from app.services.research_domain_results import legal_claims


def _result(quote: str = "fordran preskriberas") -> LegalResearchResult:
    uri = "https://lagen.nu/1981:130#P2"
    return LegalResearchResult(
        source=LegalSourceIdentity(kind="statute", title="Preskriptionslag", canonical_uri=uri),
        relation=LegalQuestionRelation(
            relation="supports", explanation="Regeln gäller fordran.", confidence="high"
        ),
        statute=StatuteAnalysis(
            operative_rule="Fordran preskriberas efter viss tid.",
            citations=[LegalCitation(source_uri=uri, quote=quote)],
        ),
        raw_text="En fordran preskriberas tio år efter tillkomsten.",
    )


def test_citation_must_be_an_exact_span_of_the_original_document():
    assert _result().statute.citations[0].quote == "fordran preskriberas"
    with pytest.raises(ValidationError, match="absent from raw source"):
        _result("fordran får aldrig preskriberas")


def test_legal_analysis_without_verified_citation_is_rejected():
    payload = _result().model_dump(mode="json")
    payload["statute"]["citations"] = []
    with pytest.raises(ValidationError, match="requires a verified citation"):
        LegalResearchResult.model_validate(payload)


def test_legal_claim_projection_preserves_negative_outcomes_and_citations():
    from app.services.legal_research_result import CaseLawAnalysis

    uri = "https://lagen.nu/dom/example"
    result = LegalResearchResult(
        source=LegalSourceIdentity(kind="case_law", title="Testfall", canonical_uri=uri),
        relation=LegalQuestionRelation(relation="limits", explanation="Avslag", confidence="high"),
        case_law=CaseLawAnalysis(
            legal_issue="36 §",
            court_reasoning="Ingen jämkning",
            outcome="Avslag",
            adjustment_requested=True,
            adjustment_granted=False,
            holding_status="established",
            authoritative_holding={
                "court_level": "supreme",
                "text_role": "majority_reasons",
                "outcome": "Avslag",
                "adjustment_granted": False,
                "citations": [{"source_uri": uri, "quote": "Ingen jämkning"}],
            },
            contract_type="insurance",
            party_context="consumer",
            decisive_factors=["konsumentens ställning"],
            citations=[LegalCitation(source_uri=uri, quote="Ingen jämkning")],
        ),
        raw_text="Ingen jämkning beslutades.",
    )
    claims = legal_claims(result, result_id="result-1", research_need_id="need-1")
    granted = next(claim for claim in claims if claim.predicate == "legal.adjustment_granted")
    assert granted.value == {"value": False}
    assert granted.relation == "limits"
    assert granted.citations[0]["quote"] == "Ingen jämkning"
    assert {claim.predicate for claim in claims} >= {
        "legal.contract_type",
        "legal.party_context",
        "legal.decisive_factor",
    }


def test_domain_result_is_preserved_separately_from_excerpt():
    result = _result()
    evidence = research_evidence(
        research_need_id="need-1",
        source_type="swedish_law",
        status="found",
        excerpt="Kort passage",
        legal_result=result,
    )
    snapshot = snapshot_research_evidence(evidence)
    assert snapshot.excerpt == "Kort passage"
    assert "legal_result" not in snapshot.provenance
    assert snapshot.legal_result == result


def test_assessment_and_completeness_read_structured_legal_result():
    result = _result()
    item = AssessableEvidence(
        evidence_id="e1",
        research_need_id="n1",
        source_type="swedish_law",
        status="found",
        title=result.source.title,
        excerpt="Kort passage",
        locator="P2",
        source_id=result.source.canonical_uri,
        source_url=result.source.canonical_uri,
        provider="lagen_nu",
        score=None,
        provenance={"legal_result": result.model_dump(mode="json")},
        retrieved_at=datetime.now(UTC),
        content_hash="abc",
        legal_result=result,
    )
    group = EvidenceReviewGroup(
        evidence=item,
        research_need_ids=("n1",),
        duplicate_evidence_ids=(),
    )
    for payload in (assessment_payload(group), completeness_payload(group)):
        assert payload["legal_result"]["relation"]["relation"] == "supports"
        assert payload["legal_result"]["statute"]["citations"][0]["quote"] == "fordran preskriberas"
        assert "raw_text" not in payload["legal_result"]
        assert "legal_result" not in payload["provenance"]

    second = replace(
        item,
        evidence_id="e2",
        research_need_id="n2",
        research_need_ids=("n2",),
        content_hash="different-analysis",
    )
    groups = group_evidence_for_review([item, second])
    assert len(groups) == 2
    assert [group.research_need_ids for group in groups] == [("n1",), ("n2",)]


@pytest.mark.asyncio
async def test_structured_interpreter_verifies_model_quote(monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def prompts(*_args, **_kwargs):
        return {
            "research.lagen_nu.domain.v3.system": "Read the source",
            "research.lagen_nu.domain.v3.repair": "Repair: {validation_errors}",
            "research.lagen_nu.domain.v3.user": (
                "{question}\n{source_kind}\n{source_uri}\n{source_text}"
            ),
        }

    async def complete(messages, schema):
        assert "fordran preskriberas" in messages[1]["content"]
        return {
            "relation": {
                "relation": "supports",
                "explanation": "Regeln gäller.",
                "confidence": "high",
            },
            "statute": {
                "operative_rule": "Preskription gäller.",
                "citations": [
                    {"source_uri": "https://lagen.nu/1981:130", "quote": "påhittat citat"}
                ],
            },
        }

    async def invoke(completer, messages, schema, *, prompt_key):
        assert prompt_key == "research.lagen_nu.domain.v3.system"
        return await completer(messages, schema)

    monkeypatch.setattr("app.llm.legal_research.invoke_structured_completer", invoke)
    monkeypatch.setattr("app.llm.legal_research.require_active_prompts", prompts)
    interpreter = LlmLegalInterpreter(completer=complete, session_factory=Session)
    with pytest.raises(LegalDomainExtractionError) as error:
        await interpreter.interpret(
            source=LegalSourceIdentity(
                kind="statute", title="Preskriptionslag", canonical_uri="https://lagen.nu/1981:130"
            ),
            question="När preskriberas fordran?",
            raw_text="En fordran preskriberas tio år efter tillkomsten.",
            truncated=False,
            context=ResearchContext(scope=KnowledgeScope(customer_id=1, module="dd")),
        )
    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.asyncio
@pytest.mark.parametrize("span_id,valid", [("s1", True), ("invented", False)])
async def test_interpreter_projects_selected_source_span_exactly(monkeypatch, span_id, valid):
    from app.services.prompt_catalog import default_prompts

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def prompts(*_args, **_kwargs):
        return default_prompts("sv")

    raw = "Heading\n\nExact [section](https://lagen.nu/1981:130#P2), punctuation and spacing."

    async def complete(messages, schema):
        assert "[s1]" in messages[1]["content"]
        return {
            "relation": {
                "relation": "supports",
                "explanation": "Direct rule",
                "confidence": "high",
            },
            "statute": {
                "operative_rule": "Rule",
                "citations": [
                    {
                        "source_uri": "https://lagen.nu/1981:130",
                        "quote": "",
                        "source_span_id": span_id,
                    }
                ],
            },
        }

    async def invoke(completer, messages, schema, *, prompt_key):
        assert prompt_key == "research.lagen_nu.domain.v3.system"
        return await completer(messages, schema)

    monkeypatch.setattr("app.llm.legal_research.invoke_structured_completer", invoke)
    monkeypatch.setattr("app.llm.legal_research.require_active_prompts", prompts)
    interpreter = LlmLegalInterpreter(completer=complete, session_factory=Session)
    kwargs = {
        "source": LegalSourceIdentity(
            kind="statute", title="Source", canonical_uri="https://lagen.nu/1981:130"
        ),
        "question": "Rule?",
        "raw_text": raw,
        "truncated": False,
        "context": ResearchContext(scope=KnowledgeScope(customer_id=1, module="dd")),
    }
    if valid:
        result = await interpreter.interpret(**kwargs)
        assert result.statute.citations[0].quote == raw.split("\n\n")[1]
    else:
        with pytest.raises(LegalDomainExtractionError) as error:
            await interpreter.interpret(**kwargs)
        assert error.value.category == "citation_grounding_failed"


def test_review_claim_citations_are_deduplicated_without_losing_text():
    from app.services.research.review_payload import compact_claims

    quote = {"source_uri": "source", "quote": "Exact original"}
    claims = [{"id": str(i), "predicate": "fact", "citations": [quote]} for i in range(50)]
    result = compact_claims(claims)
    assert len(result["claim_citations"]) == 1
    for claim in result["claims"]:
        assert result["claim_citations"][claim["citation_ids"][0]] == quote
    assert claims[0]["citations"] == [quote]
