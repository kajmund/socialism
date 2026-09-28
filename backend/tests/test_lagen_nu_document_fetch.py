"""lagen.nu document fetches overlap when research_document_concurrency > 1."""

from __future__ import annotations

import asyncio
import inspect

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import Kund
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu import document_fetch
from app.services.lagen_nu.models import SearchResults
from app.services.lagen_nu.passage_router import KeepAllPassageRouter
from app.services.research.concurrency import reset_research_concurrency
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient,
    FakeLegalInterpreter,
    PassthroughLagenNuSelector,
    _document,
    _hit,
    _source,
)
from tests.test_research import _context, _need


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


def test_document_fetch_owns_get_document():
    source = inspect.getsource(document_fetch)
    assert "get_document" in source


def _two_doc_client() -> FakeLagenNuClient:
    hits = tuple(
        _hit(
            uri=f"https://lagen.nu/1981:{index}",
            pinpoint=None,
            highlight=f"preskription {index}",
        )
        for index in (1, 2)
    )
    documents = {
        f"https://lagen.nu/1981:{index}": _document(
            uri=f"https://lagen.nu/1981:{index}",
            pinpoint=None,
            text=f"Preskription text {index}",
        )
        for index in (1, 2)
    }
    return FakeLagenNuClient(
        search=SearchResults(query="preskription", total=2, results=hits),
        documents=documents,
    )


class _CountingClient(FakeLagenNuClient):
    def __init__(self) -> None:
        super().__init__(
            search=_two_doc_client().search_payload,
            documents=_two_doc_client().documents,
        )
        self.current = 0
        self.max_seen = 0
        self._lock = asyncio.Lock()

    async def get_document(self, uri: str, *, pinpoint: str | None = None, max_chars: int = 8000):
        async with self._lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
        try:
            await asyncio.sleep(0.04)
            return await super().get_document(uri, pinpoint=pinpoint, max_chars=max_chars)
        finally:
            async with self._lock:
                self.current -= 1


class _CountingInterpreter(FakeLegalInterpreter):
    def __init__(self) -> None:
        super().__init__()
        self.current = 0
        self.max_seen = 0
        self._lock = asyncio.Lock()

    async def interpret(self, **kwargs):
        async with self._lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
        try:
            await asyncio.sleep(0.04)
            return await super().interpret(**kwargs)
        finally:
            async with self._lock:
                self.current -= 1


def _law_source(
    session: AsyncSession,
    client: FakeLagenNuClient,
    *,
    interpreter: FakeLegalInterpreter | None = None,
):
    return _source(
        client,
        session=session,
        embeddings=FakeEmbeddingProvider(),
        vector_store=MemoryKnowledgeVectorStore(),
        selector=PassthroughLagenNuSelector(),
        interpreter=interpreter or FakeLegalInterpreter(),
        passage_router=KeepAllPassageRouter(),
    )


@pytest.mark.asyncio
async def test_document_fetches_stay_serial_by_default(session: AsyncSession):
    reset_research_concurrency()
    client = _CountingClient()
    evidence = await _law_source(session, client).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert client.max_seen == 1
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_document_fetches_overlap_when_limit_is_raised(session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "research_document_concurrency", 2)
    reset_research_concurrency()
    client = _CountingClient()
    evidence = await _law_source(session, client).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert client.max_seen == 2
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_document_interpret_stays_serial_by_default(session: AsyncSession):
    reset_research_concurrency()
    interpreter = _CountingInterpreter()
    evidence = await _law_source(session, _two_doc_client(), interpreter=interpreter).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert interpreter.max_seen == 1
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_document_interpret_overlaps_when_limit_is_raised(session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "research_document_concurrency", 2)
    reset_research_concurrency()
    interpreter = _CountingInterpreter()
    evidence = await _law_source(session, _two_doc_client(), interpreter=interpreter).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert interpreter.max_seen == 2
    reset_research_concurrency()


@pytest.mark.asyncio
async def test_document_ingest_stays_serial_when_interpret_overlaps(
    session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(settings, "research_document_concurrency", 2)
    reset_research_concurrency()
    current = 0
    max_seen = 0
    lock = asyncio.Lock()
    original = document_fetch.ingest_and_load_text_units

    async def counting_ingest(*args, **kwargs):
        nonlocal current, max_seen
        async with lock:
            current += 1
            max_seen = max(max_seen, current)
        try:
            await asyncio.sleep(0.04)
            return await original(*args, **kwargs)
        finally:
            async with lock:
                current -= 1

    monkeypatch.setattr(document_fetch, "ingest_and_load_text_units", counting_ingest)
    evidence = await _law_source(session, _two_doc_client()).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert max_seen == 1
    reset_research_concurrency()
