"""Real source-path tests. Recorded official documents plus opt-in live network/model tests."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.services.lagen_nu.mcp_client import OfficialLagenNuMcpClient, parse_document
from app.services.lagen_nu.question_validation import (
    COMMERCIAL_AVTL_QUESTION,
    MIXED_MD_AVTL_QUESTION,
    ScriptedLegalQuestionValidator,
    canonical_legal_question_verdicts,
    forbidden_retrieval_questions,
)
from app.services.lagen_nu.research_source import MAX_DOCUMENT_CHARS, LagenNuResearchSource
from app.services.legal_research_result import LegalResearchResult
from app.services.research_domain_results import legal_claims
from tests.test_lagen_nu_provider import _context, _need

FIXTURES = Path(__file__).parent / "fixtures" / "research_eval"
SOURCES = [
    ("NJA 1987 s. 394", "swedish_case_law"),
    ("NJA 1992 s. 782", "swedish_case_law"),
    ("NJA 2009 s. 672", "swedish_case_law"),
    ("NJA 2002 s. 244", "swedish_case_law"),
    ("AD 1998 nr 109", "swedish_case_law"),
    ("SOU 1974:83", "swedish_preparatory_works"),
    ("NJA 2005 s. 142", "swedish_case_law"),
    ("prop. 1975/76:81", "swedish_preparatory_works"),
]
NJA_OUTCOME = (
    "HD avgjorde frågan genom avtalstolkning och återbetalning, inte genom jämkning enligt 36 §."
)
NJA_QUOTE = "Rätten att höja leasingavgiften vid en ränteuppgång motsvaras således av en skyldighet att sänka avgiften vid en räntenedgång."
PARTY_QUOTE = "Ränteklausulen är oskälig, och skall jämkas enligt [36 § avtalslagen](https://lagen.nu/1915:218#P36) till yrkat belopp"


def document(name):
    return parse_document(json.loads((FIXTURES / f"{name}.json").read_text())["document"])


def nja_result(source=None, raw_text=None):
    d = document("nja_2005_142")
    uri = d.uri
    return LegalResearchResult.model_validate(
        {
            "source": source.model_dump()
            if source
            else {"kind": "case_law", "title": d.title, "canonical_uri": uri},
            "raw_text": raw_text or d.text,
            "truncated": False,
            "relation": {
                "relation": "limits",
                "explanation": "Avtalstolkning, inte positivt jämkningsfall.",
                "confidence": "high",
            },
            "case_law": {
                "legal_issue": "Tolkning och jämkning av ränteklausul",
                "court_reasoning": "Skyldigheten att sänka avgiften följer av klausulens tolkning.",
                "outcome": NJA_OUTCOME,
                "adjustment_granted": False,
                "holding_status": "established",
                "authoritative_holding": {
                    "court_level": "supreme",
                    "text_role": "majority_reasons",
                    "outcome": NJA_OUTCOME,
                    "adjustment_granted": False,
                    "decision_basis": "contract_interpretation",
                    "citations": [{"source_uri": uri, "quote": NJA_QUOTE}],
                },
                "other_statements": [
                    {
                        "court_level": "first_instance",
                        "text_role": "party_submission",
                        "outcome": "Jämkning yrkas",
                        "adjustment_granted": None,
                        "citations": [{"source_uri": uri, "quote": PARTY_QUOTE}],
                    }
                ],
                "citations": [{"source_uri": uri, "quote": NJA_QUOTE}],
            },
        }
    )


def test_nja_2005_142_authoritative_outcome_uses_hd_citations_only():
    result = nja_result()
    claims = legal_claims(result, result_id="golden", research_need_id="36-avtl")
    outcome = next(row for row in claims if row.predicate == "legal.adjustment_granted")
    assert outcome.value == {"value": False}
    assert outcome.citations == [
        {
            "source_uri": result.source.canonical_uri,
            "quote": NJA_QUOTE,
            "source_span_id": None,
            "pinpoint": None,
        }
    ]
    assert PARTY_QUOTE in result.raw_text


@pytest.mark.parametrize("mutation", ["wrong_basis", "party_as_holding", "invented_quote"])
def test_contradictory_or_ungrounded_holding_is_rejected(mutation):
    payload = nja_result().model_dump()
    if mutation == "wrong_basis":
        payload["case_law"]["authoritative_holding"]["adjustment_granted"] = True
    if mutation == "party_as_holding":
        payload["case_law"]["authoritative_holding"]["text_role"] = "party_submission"
    if mutation == "invented_quote":
        payload["case_law"]["authoritative_holding"]["citations"][0]["quote"] = "invented"
    with pytest.raises(ValidationError):
        LegalResearchResult.model_validate(payload)


@pytest.mark.asyncio
async def test_official_transport_resolve_fetch_interpret_actual_nja_path():
    d = document("nja_2005_142")
    calls = []

    async def handler(request):
        payload = json.loads(request.content)
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})
        name = payload["params"]["name"]
        calls.append(name)
        result = (
            {"results": [{"uri": d.uri, "source": "dv", "title": d.title}], "recognized": []}
            if name == "resolve_citation"
            else d.raw
        )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"structuredContent": result}},
        )

    class Interpreter:
        async def interpret(self, *, source, raw_text, **kwargs):
            assert PARTY_QUOTE in raw_text and NJA_QUOTE in raw_text
            return nja_result(source, raw_text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OfficialLagenNuMcpClient(http=http)
        provider = LagenNuResearchSource(
            source_type="swedish_case_law", client=client, interpreter=Interpreter()
        )
        evidence = await provider.research(
            _need(
                "swedish_case_law", question="Jämkade HD villkoret i NJA 2005 s. 142 enligt 36 §?"
            ),
            _context(),
        )
    assert calls == ["resolve_citation", "get_document"]
    assert evidence[0].status == "found"
    assert evidence[0].legal_result.case_law.adjustment_granted is False
    assert evidence[0].excerpt == NJA_QUOTE


def test_36_eval_topics_do_not_send_mixed_md_avtl_to_retrieval():
    topic_questions = [
        COMMERCIAL_AVTL_QUESTION,
        "Vilka konsumentskyddshänsyn har varit avgörande i rättsfall om 36 § avtalslagen och konsumentavtal?",
        "Vilka HD- eller hovrättsavgöranden har faktiskt beviljat jämkning enligt 36 § avtalslagen, och av vilka skäl?",
    ]
    assert forbidden_retrieval_questions(topic_questions) == []
    assert forbidden_retrieval_questions([*topic_questions, MIXED_MD_AVTL_QUESTION]) == [
        MIXED_MD_AVTL_QUESTION
    ]


@pytest.mark.asyncio
async def test_mixed_md_avtl_question_is_rejected_before_document_retrieval():
    calls = []

    async def handler(request):
        payload = json.loads(request.content)
        calls.append(payload.get("method") or payload.get("params", {}).get("name"))
        raise AssertionError(f"must not retrieve mixed question: {payload}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OfficialLagenNuMcpClient(http=http)
        provider = LagenNuResearchSource(
            source_type="swedish_case_law",
            client=client,
            question_validator=ScriptedLegalQuestionValidator(
                canonical_legal_question_verdicts()
            ),
        )
        evidence = await provider.research(
            _need("swedish_case_law", question=MIXED_MD_AVTL_QUESTION),
            _context(),
        )
    assert calls == []
    assert evidence[0].status == "not_found"
    assert evidence[0].metadata["failure_category"] == "question_incoherent"


def test_sou_source_is_ocr_and_truncation_is_preserved():
    d = document("sou_1974_83")
    assert d.uri == "https://lagen.nu/sou/1974:83"
    assert d.truncated and len(d.text) == MAX_DOCUMENT_CHARS
    assert "**36§**" in d.text
    assert "Föreslagen lydelse" in d.text


@pytest.mark.integration
@pytest.mark.parametrize("citation,source_type", SOURCES)
@pytest.mark.asyncio
async def test_live_resolver_and_fetch(request, citation, source_type):
    if not request.config.getoption("--live-research-sources"):
        pytest.skip("requires --live-research-sources")
    client = OfficialLagenNuMcpClient()
    try:
        resolved = await client.resolve_citation(citation)
        assert resolved.results, f"resolve_no_document: {citation}"
        d = await client.get_document(resolved.results[0].uri, max_chars=MAX_DOCUMENT_CHARS)
        assert d.text.strip(), f"unsupported_source_shape: {citation}"
        assert d.source == ("dv" if source_type == "swedish_case_law" else "forarbete")
        if citation == "prop. 1975/76:81":
            assert "https://lagen.nu/sou/1974:83" in d.text
            linked = await client.resolve_citation("SOU 1974:83")
            linked_doc = await client.get_document(
                linked.results[0].uri, max_chars=MAX_DOCUMENT_CHARS
            )
            assert "**36§**" in linked_doc.text
    finally:
        await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_model_nja_and_sou(request, tmp_path):
    if not request.config.getoption("--live-research-model"):
        pytest.skip("requires --live-research-model and configured provider credentials")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.database.base import Base
    from app.database.models import Kund
    from app.llm import set_structured_completer
    from app.llm.legal_research import LlmLegalInterpreter
    from app.services.knowledge.models import KnowledgeScope
    from app.services.prompt_catalog import PROMPT_FIELDS
    from app.services.prompt_fields_store import ensure_prompt_field_defaults
    from app.services.research.models import ResearchContext

    assert settings.selected_llm_api_key != "test-key-not-real", (
        "A real configured model key is required"
    )
    set_structured_completer(None)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/live.sqlite")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        customer = Kund(name="Eval", slug="eval", available_modules=["dd"])
        session.add(customer)
        await ensure_prompt_field_defaults(session, "dd", PROMPT_FIELDS)
        await session.commit()
        context = ResearchContext(scope=KnowledgeScope(customer_id=customer.id, module="dd"))
    try:
        for citation, source_type in [
            ("NJA 2005 s. 142", "swedish_case_law"),
            ("SOU 1974:83", "swedish_preparatory_works"),
        ]:
            source = LagenNuResearchSource(
                source_type=source_type, interpreter=LlmLegalInterpreter(session_factory=factory)
            )
            rows = await source.research(
                _need(
                    source_type,
                    question=f"Hur behandlas jämkning enligt 36 § avtalslagen i {citation}? Skilj instanser, partsyrkanden och slutligt avgörande.",
                ),
                context,
            )
            assert rows[0].status == "found", rows[0].metadata
            result = rows[0].legal_result
            if result.case_law:
                assert result.case_law.holding_status == "established"
                assert result.case_law.authoritative_holding.court_level == "supreme"
                assert result.case_law.adjustment_granted is False
            else:
                assert result.preparatory_work.interpretation_guidance
                assert result.truncated
    finally:
        await engine.dispose()


def test_outcome_is_projected_from_authoritative_statement_not_duplicate_model_fields():
    payload = nja_result().model_dump()
    payload["case_law"]["adjustment_granted"] = True
    payload["case_law"]["outcome"] = "Conflicting duplicate text"
    result = LegalResearchResult.model_validate(payload)
    assert result.case_law.adjustment_granted is False
    assert result.case_law.outcome == NJA_OUTCOME
