"""LegalInterpreter output becomes Claims SUPPORTED_BY TextUnits."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    Kund,
    TextUnitRecord,
)
from app.llm.legal_research import LegalDomainExtractionError
from app.services.knowledge.claims import supporting_text_unit_ids_for_claim
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

URI = "https://lagen.nu/dom/nja/2005s142"
HOLDING = "Högsta domstolen ogillade yrkandet om jämkning enligt 36 §."
BACKGROUND = "Leasingavtalet tecknades år 1998 och avsåg en personbil."


def _unit(unit_id: str, text: str, *, ordinal: int = 0) -> TextUnitRecord:
    return TextUnitRecord(
        id=unit_id,
        document_version_id="ver-a",
        document_id="doc-a",
        section_id="s1",
        ordinal=ordinal,
        text=text,
        content_hash=unit_id,
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
        claims = list((await session.execute(select(KnowledgeClaimRecord))).scalars().all())
        assert {row.id for row in claims} == set(claim_ids)
        support = await supporting_text_unit_ids_for_claim(session, claim_ids[0])
        assert support
        assert set(support) <= set(evidence[0].metadata["text_unit_ids"])
        links = list((await session.execute(select(KnowledgeClaimTextUnit))).scalars().all())
        assert links
        assert {link.relation for link in links} == {"SUPPORTED_BY"}
    await engine.dispose()
