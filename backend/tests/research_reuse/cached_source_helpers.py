"""Persist a source cache; mock only external research boundaries."""

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from sqlalchemy import select, text

from app.database.models import DocumentVersionRecord, TextUnitRecord
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.publish import publish_legal_fact
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.canonical_ingest import ingest_lagen_nu_document
from app.services.lagen_nu.models import SearchResults, ResolvedCitations
from app.services.lagen_nu.passage_router import JevPassageRouter
from app.services.lagen_nu.research_source import LagenNuResearchSource
from tests.knowledge_fakes import FakeEmbeddingProvider, fake_embed_text
from tests.test_lagen_nu_passage_router import ScriptedPassageJev
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient, FakeLegalInterpreter, PassthroughLagenNuSelector, _document, _hit,
)
from tests.test_research_question_evidence import _router

URI = "https://lagen.nu/1915:218"
SOURCE_TEXT = "# 36 §\n\nAvtalsvillkor får jämkas när villkoret är oskäligt."
QUESTION = "När får oskäliga avtalsvillkor enligt 36 § avtalslagen jämkas?"


async def available_connection(factory):
    async with factory() as session:
        assert await session.scalar(text("SELECT 1")) == 1


@dataclass
class CachedSource:
    factory: object
    document_id: str
    version_id: str
    unit_ids: list[str]
    store: MemoryKnowledgeVectorStore

    async def snapshot(self):
        async with self.factory() as session:
            versions = list(await session.scalars(select(DocumentVersionRecord)))
            units = list(await session.scalars(select(TextUnitRecord)))
            assert len(versions) == 1 and versions[0].content_hash == hash_text(SOURCE_TEXT)
            assert all(unit.content_hash == hash_text(unit.text) for unit in units)
            return [(unit.id, unit.content_hash, unit.text) for unit in units]


async def seed_cache(factory) -> CachedSource:
    store = MemoryKnowledgeVectorStore()
    async with factory() as session:
        result = await ingest_lagen_nu_document(
            session, customer_id=1, document=_document(uri=URI, pinpoint=None, text=SOURCE_TEXT),
            embeddings=FakeEmbeddingProvider(), vector_store=store,
        )
        scope = customer_scope(1)
        subject = await resolve_node(session, NodeInput(node_type="legal.source", name=URI, scope=scope))
        target = await resolve_node(session, NodeInput(node_type="legal.concept", name="Jämkning", scope=scope))
        fact, _decision = await resolve_fact(session, FactInput(
            source_id=subject.id, target_id=target.id, scope=scope, predicate="legal.provision",
            fact_text="36 § avtalslagen avser oskäliga avtalsvillkor",
            embedding=tuple(fake_embed_text("36 § avtalslagen avser oskäliga avtalsvillkor")),
            embedding_model=FakeEmbeddingProvider.model,
            sources=(SourceRef("text_unit", result.segmented.text_units[0].id),),
        ))
        unit = result.segmented.text_units[0]
        publish_legal_fact(
            require_knowledge(),
            FactInput(
                source_id=subject.id, target_id=target.id, scope=scope, predicate="legal.provision",
                fact_text="36 § avtalslagen avser oskäliga avtalsvillkor",
                embedding=tuple(fake_embed_text("36 § avtalslagen avser oskäliga avtalsvillkor")),
                sources=(SourceRef("text_unit", unit.id),),
            ),
            fact_id=fact.id,
            source=NodeInput(node_type="legal.source", name=URI, scope=scope),
            target=NodeInput(node_type="legal.concept", name="Jämkning", scope=scope),
            units=[TextUnitWrite(
                unit_id=unit.id, scope=scope, document_id=result.document_id,
                document_version_id=result.document_version_id, text=unit.text,
                content_hash=unit.content_hash, ordinal=unit.ordinal, locator=unit.locator,
                embedding=tuple(fake_embed_text(unit.text)),
            )],
        )
        await session.commit()
    return CachedSource(
        factory, result.document_id, result.document_version_id,
        [unit.id for unit in result.segmented.text_units], store,
    )


def source_boundary(cache, monkeypatch):
    hit = _hit(uri=URI)
    client = FakeLagenNuClient(
        search=SearchResults(query="", total=1, results=(hit,)),
        resolved=ResolvedCitations(results=(hit,)),
    )
    client.get_document = AsyncMock(side_effect=AssertionError("Cached source was fetched"))
    original_search = client.search

    async def search(*args, **kwargs):
        await available_connection(cache.factory)
        return await original_search(*args, **kwargs)

    client.search = AsyncMock(side_effect=search)
    embedding = FakeEmbeddingProvider()
    original_embed = embedding.embed

    async def embed(texts):
        assert texts == [QUESTION], "Cached source text must not be embedded again"
        await available_connection(cache.factory)
        return await original_embed(texts)

    embedding.embed = AsyncMock(side_effect=embed)
    jev = ScriptedPassageJev(1.0)
    original_ask = jev.ask

    async def ask(**kwargs):
        await available_connection(cache.factory)
        return await original_ask(**kwargs)

    jev.ask = AsyncMock(side_effect=ask)
    interpreter = FakeLegalInterpreter()
    original_interpret = interpreter.interpret

    async def interpret(**kwargs):
        await available_connection(cache.factory)
        return await original_interpret(**kwargs)

    interpreter.interpret = AsyncMock(side_effect=interpret)
    ingest = AsyncMock(side_effect=AssertionError("Cached source was ingested"))
    chunk = Mock(side_effect=AssertionError("Cached source was chunked"))
    monkeypatch.setattr("app.services.lagen_nu.text_unit_research.ingest_lagen_nu_document", ingest)
    monkeypatch.setattr("app.services.knowledge.chunking.KnowledgeChunker.segment", chunk)
    cache.store.replace_document_chunks = AsyncMock(side_effect=AssertionError("Cached vectors replaced"))

    def router_factory(session):
        source = LagenNuResearchSource(
            source_type="swedish_law", client=client, session=session,
            embeddings=embedding, vector_store=cache.store,
            selector=PassthroughLagenNuSelector(), interpreter=interpreter,
            passage_router=JevPassageRouter(jev),
        )
        return _router(source)[0]

    return SimpleNamespace(
        client=client, embedding=embedding, jev=jev, interpreter=interpreter,
        ingest=ingest, chunk=chunk, router_factory=router_factory,
    )
