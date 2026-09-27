"""lagen.nu research reads ingested TextUnits, not a parallel raw-text cache."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    KnowledgeClaimRecord,
    Kund,
    TextUnitRecord,
)
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.models import ResolvedCitations, SearchResults
from app.services.lagen_nu.passage_router import KeepAllPassageRouter
from app.services.lagen_nu.registration import LAGEN_NU_PROVIDER_ID
from app.services.lagen_nu.research_source import LagenNuResearchSource
from app.services.lagen_nu.text_unit_research import LagenNuResearchKnowledgeError
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient,
    FakeLegalInterpreter,
    PassthroughLagenNuSelector,
    _document,
    _hit,
)
from tests.test_research import _context, _need

URI = "https://lagen.nu/1915:218"
TEXT = "Avtalsvillkor får jämkas eller lämnas utan avseende om villkoret är oskäligt."


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=7, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


def _research_source(session: AsyncSession, client: FakeLagenNuClient) -> LagenNuResearchSource:
    return LagenNuResearchSource(
        source_type="swedish_law",
        client=client,
        selector=PassthroughLagenNuSelector(),
        interpreter=FakeLegalInterpreter(),
        session=session,
        embeddings=FakeEmbeddingProvider(),
        vector_store=MemoryKnowledgeVectorStore(),
        passage_router=KeepAllPassageRouter(),
    )


def _client() -> FakeLagenNuClient:
    hit = _hit(uri=URI, pinpoint="P36")
    return FakeLagenNuClient(
        search=SearchResults(query="", total=1, results=(hit,)),
        resolved=ResolvedCitations(results=(hit,)),
        documents={URI: _document(uri=URI, pinpoint=None, text=TEXT)},
    )


async def test_research_ingests_and_grounds_evidence_in_text_units(session: AsyncSession):
    client = _client()
    evidence = await _research_source(session, client).research(
        _need("swedish_law", question="När får avtalsvillkor jämkas?"),
        _context(),
    )
    await session.flush()
    units = list((await session.execute(select(TextUnitRecord))).scalars().all())
    documents = list((await session.execute(select(CanonicalDocumentRecord))).scalars().all())
    fetches = [args for name, args in client.calls if name == "get_document"]
    assert [item.status for item in evidence] == ["found"]
    assert fetches == [{"uri": URI, "pinpoint": None, "max_chars": 200000}]
    assert evidence[0].source_id == f"{URI}#P36"
    assert evidence[0].locator == "P36"
    assert evidence[0].legal_result is not None
    assert TEXT in evidence[0].legal_result.raw_text
    assert evidence[0].metadata["text_unit_ids"]
    assert evidence[0].metadata["canonical_document_id"] == documents[0].id
    assert evidence[0].metadata["document_version_id"] == units[0].document_version_id
    assert evidence[0].metadata["reused_text_units"] is False
    assert documents[0].source_type == LAGEN_NU_PROVIDER_ID
    assert documents[0].canonical_uri == URI
    assert {unit.text for unit in units} == {TEXT}


async def test_compute_drops_orm_and_a_changed_version_is_not_persisted(session: AsyncSession):
    observed: dict[str, object] = {}

    class WatchingInterpreter(FakeLegalInterpreter):
        async def interpret(self, *, source, question, raw_text, truncated, context):
            observed["in_transaction"] = session.in_transaction()
            observed["orm_units"] = [
                obj
                for obj in session.sync_session.identity_map.values()
                if isinstance(obj, TextUnitRecord)
            ]
            maker = async_sessionmaker(session.bind, expire_on_commit=False, class_=AsyncSession)
            async with maker() as other:
                version = await other.scalar(select(DocumentVersionRecord))
                unit = await other.scalar(select(TextUnitRecord))
                assert version is not None and unit is not None
                version.content_hash = "f" * 64
                unit.content_hash = "e" * 64
                await other.commit()
            return await FakeLegalInterpreter.interpret(
                self,
                source=source,
                question=question,
                raw_text=raw_text,
                truncated=truncated,
                context=context,
            )

    source = LagenNuResearchSource(
        source_type="swedish_law",
        client=_client(),
        selector=PassthroughLagenNuSelector(),
        interpreter=WatchingInterpreter(),
        session=session,
        embeddings=FakeEmbeddingProvider(),
        vector_store=MemoryKnowledgeVectorStore(),
        passage_router=KeepAllPassageRouter(),
    )
    evidence = await source.research(
        _need("swedish_law", question="När får avtalsvillkor jämkas?"),
        _context(),
    )

    claims = await session.scalar(select(func.count()).select_from(KnowledgeClaimRecord))
    assert observed["in_transaction"] is False
    assert observed["orm_units"] == []
    assert [item.status for item in evidence] == ["error"]
    assert "changed during passage interpretation" in str(evidence[0].metadata["detail"])
    assert claims == 0


async def test_second_research_reuses_text_units_without_mcp_fetch(session: AsyncSession):
    client = _client()
    source = _research_source(session, client)
    first = await source.research(
        _need("swedish_law", question="När får avtalsvillkor jämkas?"),
        _context(),
    )
    second = await source.research(
        _need("swedish_law", question="Vad gäller oskäliga avtalsvillkor?"),
        _context(),
    )
    await session.flush()
    fetches = [args for name, args in client.calls if name == "get_document"]
    documents = list((await session.execute(select(CanonicalDocumentRecord))).scalars().all())
    units = list((await session.execute(select(TextUnitRecord))).scalars().all())
    assert [item.status for item in first] == ["found"]
    assert [item.status for item in second] == ["found"]
    assert len(fetches) == 1
    assert second[0].metadata["reused_text_units"] is True
    assert second[0].metadata["text_unit_ids"] == first[0].metadata["text_unit_ids"]
    assert len(documents) == 1
    assert len(units) == 1


async def test_research_refuses_raw_mcp_text_without_knowledge_deps():
    client = _client()
    source = LagenNuResearchSource(
        source_type="swedish_law",
        client=client,
        selector=PassthroughLagenNuSelector(),
        interpreter=FakeLegalInterpreter(),
    )
    with pytest.raises(LagenNuResearchKnowledgeError, match="refusing to interpret raw MCP text"):
        await source.research(
            _need("swedish_law", question="När får avtalsvillkor jämkas?"),
            _context(),
        )
    assert [name for name, _ in client.calls if name == "get_document"] == []
