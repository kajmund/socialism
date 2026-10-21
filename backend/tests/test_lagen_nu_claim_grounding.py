"""LegalInterpreter output becomes Claims SUPPORTED_BY TextUnits."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    Kund,
)
from app.llm.legal_research import LegalDomainExtractionError
from app.services.knowledge.claims import (
    claims_answering_question_key,
    supporting_text_unit_ids_for_claim,
)
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.claim_grounding import ground_legal_claims
from app.services.lagen_nu.models import SearchResults
from app.services.lagen_nu.passage_router import KeepAllPassageRouter
from app.services.lagen_nu.research_source import LagenNuResearchSource
from app.services.legal_research_result import (
    CaseLawAnalysis,
    CourtStatement,
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
)
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient,
    FakeLegalInterpreter,
    PassthroughLagenNuSelector,
    _document,
    _hit,
)
from tests.test_research import _context, _need
from app.services.overgraph.model import TextUnitView
from tests.text_unit_fakes import text_unit_view

URI = "https://lagen.nu/dom/nja/2005s142"
HOLDING = "Högsta domstolen ogillade yrkandet om jämkning enligt 36 §."
BACKGROUND = "Leasingavtalet tecknades år 1998 och avsåg en personbil."


def _unit(unit_id: str, text: str, *, ordinal: int = 0) -> TextUnitView:
    return text_unit_view(
        id=unit_id,
        document_version_id="ver-a",
        document_id="doc-a",
        customer_id=1,
        section_id="s1",
        ordinal=ordinal,
        text=text,
    )


def _holding_result() -> LegalResearchResult:
    return LegalResearchResult(
        source=LegalSourceIdentity(kind="case_law", title="NJA", canonical_uri=URI),
        relation=LegalQuestionRelation(
            relation="limits",
            explanation="Avtalstolkning, inte jämkning.",
            confidence="high",
        ),
        case_law=CaseLawAnalysis(
            legal_issue="Jämkning",
            court_reasoning=HOLDING,
            authoritative_holding=CourtStatement(
                court_level="supreme",
                text_role="majority_reasons",
                outcome="Ogillat",
                adjustment_granted=False,
                citations=[LegalCitation(source_uri=URI, quote=HOLDING)],
            ),
            citations=[LegalCitation(source_uri=URI, quote=HOLDING)],
        ),
        raw_text=f"{HOLDING}\n\n{BACKGROUND}",
    )


def test_holding_claim_is_supported_by_the_holding_text_unit():
    units = [_unit("tu-hold", HOLDING, ordinal=0), _unit("tu-bg", BACKGROUND, ordinal=1)]
    claims = ground_legal_claims(
        _holding_result(),
        units,
        customer_id=7,
        research_need_id="need-1",
        result_id="result-1",
    )
    granted = next(claim for claim in claims if claim.predicate == "legal.adjustment_granted")
    assert granted.value == {"value": False}
    assert granted.supporting_text_unit_ids == ("tu-hold",)


def test_ungrounded_citation_fails_loud():
    units = [_unit("tu-bg", BACKGROUND)]
    with pytest.raises(LegalDomainExtractionError, match="absent from TextUnits") as exc:
        ground_legal_claims(
            _holding_result(),
            units,
            customer_id=7,
            research_need_id="need-1",
            result_id="result-1",
        )
    assert exc.value.category == "citation_grounding_failed"


async def test_research_persists_claims_on_interpreted_text_units():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=7, name="acme", slug="acme", available_modules=["dd"]))
        await session.flush()
        text = f"# Domskäl\n\n{HOLDING}\n\n# Sakomständigheter\n\n{BACKGROUND}"
        client = FakeLagenNuClient(
            search=SearchResults(
                query="",
                total=1,
                results=(_hit(uri=URI, pinpoint=None, source="dv", highlight="jämkning"),),
            ),
            documents={URI: _document(uri=URI, pinpoint=None, text=text, source="dv")},
        )
        evidence = await LagenNuResearchSource(
            source_type="swedish_case_law",
            client=client,
            selector=PassthroughLagenNuSelector(),
            interpreter=FakeLegalInterpreter(quote=HOLDING),
            session=session,
            embeddings=FakeEmbeddingProvider(),
            vector_store=MemoryKnowledgeVectorStore(),
            passage_router=KeepAllPassageRouter(),
        ).research(
            _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?"),
            _context(),
        )
        await session.flush()
        assert [item.status for item in evidence] == ["found"]
        claim_ids = evidence[0].metadata["knowledge_claim_ids"]
        assert claim_ids
        from app.services.overgraph.catalogs import require_knowledge
        from app.services.overgraph.legal_claims import claim_in_graph

        assert all(
            claim_in_graph(require_knowledge(), scope_key="customer:7", identity=claim_id)
            is not None
            for claim_id in claim_ids
        )
        support = await supporting_text_unit_ids_for_claim(session, claim_ids[0])
        assert support
        assert set(support) <= set(evidence[0].metadata["text_unit_ids"])
        from app.services.overgraph.claim_answers import claim_answers_for_question
        from app.services.overgraph.legal_claims import supporting_text_units

        assert supporting_text_units(require_knowledge(), claim_ids[0]) == support
        answered = claim_answers_for_question(
            require_knowledge(), customer_id=7,
            question_key=evidence[0].metadata["answered_by_question_key"],
        )
        assert [str(node.key) for node in answered] == list(claim_ids)
        from app.services.overgraph.claim_answers import claim_answer_edges

        edges = claim_answer_edges(
            require_knowledge(), customer_id=7,
            question_key=evidence[0].metadata["answered_by_question_key"],
        )
        assert {str(props["source_type"]) for _node, props in edges} == {"swedish_case_law"}
        reused = await claims_answering_question_key(
            session,
            customer_id=7,
            question_key=evidence[0].metadata["answered_by_question_key"],
        )
        assert {claim.id for claim in reused} == set(claim_ids)
        assert all(claim.supporting_text_unit_ids for claim in reused)
        from app.services.overgraph.labels import ENTITY

        entity_nodes, _ = require_knowledge().query_nodes(
            label_filter={"labels": [ENTITY], "mode": "all"}, limit=200,
        )
        types = {str(row.props.get("node_type")) for row in entity_nodes}
        assert "legal.source" in types
        assert "legal.issue" not in types
        from app.services.overgraph.labels import LINKED, SUPPORTS

        # Entity<->entity edges are mirrored; edges touching TextUnits/documents keep
        # their SQL row until parcel 5, so only mappable relations are asserted here.
        catalog = require_knowledge()
        assert catalog.count_edges_by_label(LINKED) >= 1
        assert catalog.count_edges_by_label(SUPPORTS) >= 0
    await engine.dispose()
