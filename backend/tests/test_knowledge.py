"""Read-only knowledge layer: registry, scope, object storage, vector store."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import KnowledgeDocumentRecord, Kund
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    EmbeddedKnowledgeQuery,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    KnowledgeScopeRequiredError,
)
from app.services.knowledge.provider import (
    SUPABASE_PROVIDER_ID,
    KnowledgeNotFoundError,
    KnowledgeProvider,
    KnowledgeProviderNotFoundError,
    KnowledgeVectorStoreError,
)
from app.services.knowledge.registry import (
    KnowledgeProviderRegistry,
    build_knowledge_registry,
)
from app.services.knowledge.supabase_provider import (
    SupabaseKnowledgeProvider,
    supabase_external_id,
)
from app.services.knowledge.vector_store import (
    MemoryKnowledgeVectorStore,
    SupabaseVectorBucketStore,
    VectorBucketRecord,
    chunk_in_scope,
    cosine_score,
)
from app.services.object_storage import get_object, get_object_storage, put_object
from tests.knowledge_fakes import FakeEmbeddingProvider, fake_embed_text

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "knowledge"

_FORBIDDEN_IMPORT_PREFIXES = (
    "app.services.panel",
    "app.services.rattsunderlag",
    "app.services.dd.research",
    "app.services.ssr",
    "app.services.underlag_extract",
    "app.services.spindoctor_mcp_tools",
)

_FORBIDDEN_MODULES = {
    "pytesseract",
    "unstructured",
    "pypdf",
}


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
        yield db
    await engine.dispose()


async def _customer(session: AsyncSession, slug: str) -> Kund:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


async def _index_document(
    session: AsyncSession,
    *,
    customer_id: int,
    document_id: str = "doc-brief",
    provider: str = SUPABASE_PROVIDER_ID,
    case_id: str | None = "case-1",
    module: str | None = "dd",
    bucket: str = "acme",
    key: str = "dd/files/brief.pdf",
    title: str = "Brief",
    extra: dict | None = None,
) -> KnowledgeDocumentRecord:
    row = KnowledgeDocumentRecord(
        document_id=document_id,
        provider=provider,
        external_id=supabase_external_id(bucket, key),
        customer_id=customer_id,
        case_id=case_id,
        module=module,
        title=title,
        mime_type="application/pdf",
        storage_bucket=bucket,
        storage_key=key,
        version="1",
        extra=extra or {"origin": "files"},
    )
    session.add(row)
    await session.flush()
    return row


def _scope(*, customer_id: int, case_id: str | None = "case-1", module: str | None = "dd") -> KnowledgeScope:
    return KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module)


def _chunk(
    *,
    document_id: str,
    text: str,
    customer_id: int,
    case_id: str | None = "case-1",
    module: str | None = "dd",
    title: str = "Brief",
    chunk_id: str = "c1",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id=document_id,
        chunk_id=chunk_id,
        text=text,
        customer_id=customer_id,
        case_id=case_id,
        module=module,
        title=title,
        locator="p1",
        provider=SUPABASE_PROVIDER_ID,
        version="1",
        content_hash="hash-1",
    )


def _embedded(chunk: KnowledgeChunk) -> EmbeddedKnowledgeChunk:
    return EmbeddedKnowledgeChunk(chunk=chunk, embedding=fake_embed_text(chunk.text))


def _provider(
    session: AsyncSession,
    store: MemoryKnowledgeVectorStore | SupabaseVectorBucketStore | RankedVectorStore | None = None,
    *,
    embeddings: FakeEmbeddingProvider | None = None,
    fetch_object=None,
) -> SupabaseKnowledgeProvider:
    return SupabaseKnowledgeProvider(
        session,
        vector_store=store or MemoryKnowledgeVectorStore(),
        embeddings=embeddings or FakeEmbeddingProvider(),
        fetch_object=fetch_object,
    )


async def _embedded_query(
    text: str,
    scope: KnowledgeScope,
    *,
    limit: int = 10,
) -> EmbeddedKnowledgeQuery:
    vectors = await FakeEmbeddingProvider().embed([text])
    return EmbeddedKnowledgeQuery(
        query=KnowledgeQuery(query=text, scope=scope, limit=limit),
        embedding=vectors[0],
    )


class RankedVectorStore:
    """Returns pre-ranked hits and honors limit so over-fetch can be observed."""

    def __init__(self, hits: list[KnowledgeHit]) -> None:
        self.hits = hits
        self.requested_limits: list[int] = []

    async def search(self, query: EmbeddedKnowledgeQuery) -> list[KnowledgeHit]:
        self.requested_limits.append(query.query.limit)
        return self.hits[: query.query.limit]

    async def upsert_chunks(self, chunks: Sequence[EmbeddedKnowledgeChunk]) -> None:
        return None

    async def replace_document_chunks(
        self,
        document_id: str,
        chunks: Sequence[EmbeddedKnowledgeChunk],
    ) -> None:
        return None

    async def delete_document(self, document_id: str) -> None:
        return None


class FakeVectorBucketClient:
    """Stand-in for the alpha Vector Bucket transport."""

    def __init__(self) -> None:
        self.records: list[VectorBucketRecord] = []
        self.last_query: dict[str, Any] | None = None

    async def upsert(self, records: Sequence[VectorBucketRecord]) -> None:
        ids = {(record.document_id, record.chunk_id) for record in records}
        self.records = [
            existing
            for existing in self.records
            if (existing.document_id, existing.chunk_id) not in ids
        ]
        self.records.extend(records)

    async def replace(self, document_id: str, records: Sequence[VectorBucketRecord]) -> None:
        self.records = [record for record in self.records if record.document_id != document_id]
        self.records.extend(records)

    async def query(
        self,
        *,
        vector: Sequence[float],
        filters: Mapping[str, Any],
        limit: int,
    ) -> Sequence[VectorBucketRecord]:
        self.last_query = {"vector": list(vector), "filters": dict(filters), "limit": limit}
        matched: list[VectorBucketRecord] = []
        for record in self.records:
            if any(record.metadata.get(key) != value for key, value in filters.items()):
                continue
            score = cosine_score(vector, record.embedding)
            if score <= 0:
                continue
            matched.append(
                VectorBucketRecord(
                    document_id=record.document_id,
                    chunk_id=record.chunk_id,
                    text=record.text,
                    title=record.title,
                    score=score,
                    locator=record.locator,
                    provider=record.provider,
                    version=record.version,
                    metadata=dict(record.metadata),
                )
            )
        return matched[:limit]

    async def delete(self, document_id: str) -> None:
        self.records = [record for record in self.records if record.document_id != document_id]


async def test_registry_resolves_supabase(session: AsyncSession):
    registry = build_knowledge_registry(
        session,
        vector_store=MemoryKnowledgeVectorStore(),
        embeddings=FakeEmbeddingProvider(),
    )
    provider = registry.get("supabase")
    assert provider.provider_id == SUPABASE_PROVIDER_ID
    assert isinstance(provider, SupabaseKnowledgeProvider)
    assert registry.list_ids() == ["supabase"]
    with pytest.raises(KnowledgeProviderNotFoundError):
        registry.get("gdrive")


async def test_known_document_resolves_to_generic_document(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id)
    provider = _provider(session)
    doc = await provider.get_document("doc-brief", _scope(customer_id=kund.id))
    assert isinstance(doc, KnowledgeDocument)
    assert doc.document_id == "doc-brief"
    assert doc.provider == "supabase"
    assert doc.external_id == "acme/dd/files/brief.pdf"
    assert doc.title == "Brief"
    assert doc.mime_type == "application/pdf"
    assert doc.scope == _scope(customer_id=kund.id)
    assert doc.version == "1"
    assert doc.document_id != doc.external_id


async def test_fetch_uses_existing_object_storage(session: AsyncSession):
    kund = await _customer(session, "acme")
    row = await _index_document(session, customer_id=kund.id)
    await put_object(row.storage_bucket, row.storage_key, b"%PDF-1.4 original", "application/pdf")

    storage = get_object_storage()
    stored, content_type = storage.get_object(row.storage_bucket, row.storage_key)
    assert stored == b"%PDF-1.4 original"
    assert content_type == "application/pdf"

    provider = _provider(session)
    content = await provider.fetch_content("doc-brief", _scope(customer_id=kund.id))
    assert content == b"%PDF-1.4 original"
    via_helper, _ = await get_object(row.storage_bucket, row.storage_key)
    assert via_helper == content


async def test_correct_customer_case_scope_succeeds(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id, case_id="case-1")
    await put_object("acme", "dd/files/brief.pdf", b"ok", "application/pdf")
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [_embedded(_chunk(document_id="doc-brief", text="kommunens skattesats", customer_id=kund.id))]
    )
    provider = _provider(session, store)
    scope = _scope(customer_id=kund.id, case_id="case-1")
    doc = await provider.get_document("doc-brief", scope)
    assert doc is not None
    assert await provider.fetch_content("doc-brief", scope) == b"ok"
    hits = await provider.search(KnowledgeQuery(query="skattesats", scope=scope))
    assert [hit.document_id for hit in hits] == ["doc-brief"]


async def test_wrong_customer_and_case_scope_fails_closed(session: AsyncSession):
    owner = await _customer(session, "acme")
    other = await _customer(session, "other")
    await _index_document(session, customer_id=owner.id, case_id="case-1")
    await put_object("acme", "dd/files/brief.pdf", b"secret", "application/pdf")
    calls: list[tuple[str, str]] = []

    async def tracking_get(bucket: str, key: str) -> tuple[bytes, str]:
        calls.append((bucket, key))
        return await get_object(bucket, key)

    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [_embedded(_chunk(document_id="doc-brief", text="kommunens skattesats", customer_id=owner.id))]
    )
    provider = _provider(session, store, fetch_object=tracking_get)
    wrong_customer = _scope(customer_id=other.id, case_id="case-1")
    wrong_case = _scope(customer_id=owner.id, case_id="case-9")
    assert await provider.get_document("doc-brief", wrong_customer) is None
    assert await provider.get_document("doc-brief", wrong_case) is None
    with pytest.raises(KnowledgeNotFoundError):
        await provider.fetch_content("doc-brief", wrong_customer)
    with pytest.raises(KnowledgeNotFoundError):
        await provider.fetch_content("doc-brief", wrong_case)
    assert calls == []
    assert await provider.search(KnowledgeQuery(query="skattesats", scope=wrong_customer)) == []
    assert await provider.search(KnowledgeQuery(query="skattesats", scope=wrong_case)) == []


async def test_unknown_document_has_defined_not_found(session: AsyncSession):
    kund = await _customer(session, "acme")
    provider = _provider(session)
    scope = _scope(customer_id=kund.id)
    assert await provider.get_document("missing-doc", scope) is None
    with pytest.raises(KnowledgeNotFoundError):
        await provider.fetch_content("missing-doc", scope)


async def test_vector_search_returns_normalized_knowledge_hit(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id)
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [_embedded(_chunk(document_id="doc-brief", text="vindkraft i kommunen", customer_id=kund.id))]
    )
    provider = _provider(session, store)
    hits = await provider.search(
        KnowledgeQuery(query="vindkraft", scope=_scope(customer_id=kund.id))
    )
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, KnowledgeHit)
    assert hit.document_id == "doc-brief"
    assert hit.provider == "supabase"
    assert hit.title == "Brief"
    assert "vindkraft" in hit.excerpt
    assert hit.locator == "p1"
    assert hit.external_id == "acme/dd/files/brief.pdf"


async def test_vector_metadata_filtering_enforces_scope():
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            _embedded(
                _chunk(
                    document_id="doc-a",
                    text="skola i acme",
                    customer_id=1,
                    case_id="case-a",
                )
            ),
            _embedded(
                _chunk(
                    document_id="doc-b",
                    text="skola i other",
                    customer_id=2,
                    case_id="case-b",
                )
            ),
        ]
    )
    hits = await store.search(
        await _embedded_query("skola", KnowledgeScope(customer_id=1, case_id="case-a"))
    )
    assert [hit.document_id for hit in hits] == ["doc-a"]
    assert all(isinstance(hit, KnowledgeHit) for hit in hits)
    foreign = _chunk(document_id="doc-b", text="x", customer_id=2, case_id="case-b")
    assert not chunk_in_scope(foreign, KnowledgeScope(customer_id=1, case_id="case-a"))


async def test_supabase_vector_bucket_store_normalizes_and_filters():
    client = FakeVectorBucketClient()
    store = SupabaseVectorBucketStore(client)
    await store.upsert_chunks(
        [
            _embedded(
                _chunk(
                    document_id="doc-a",
                    text="vatten och avlopp",
                    customer_id=1,
                    case_id="case-a",
                )
            ),
            _embedded(
                _chunk(
                    document_id="doc-b",
                    text="vatten i annan kund",
                    customer_id=2,
                    case_id="case-b",
                    chunk_id="c2",
                )
            ),
        ]
    )
    query = await _embedded_query("vatten", KnowledgeScope(customer_id=1, case_id="case-a"))
    hits = await store.search(query)
    assert [hit.document_id for hit in hits] == ["doc-a"]
    assert isinstance(hits[0], KnowledgeHit)
    assert hits[0].excerpt == "vatten och avlopp"
    assert hits[0].locator == "p1"
    assert not any(type(hit).__name__ == "VectorBucketRecord" for hit in hits)
    assert client.last_query is not None
    assert client.last_query["vector"] == query.embedding
    assert "query" not in client.last_query


def test_provider_api_is_read_only():
    public = {
        name
        for name, member in inspect.getmembers(
            SupabaseKnowledgeProvider,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert public == {"search", "get_document", "fetch_content"}
    protocol_source = inspect.getsource(KnowledgeProvider)
    for banned in ("async def upload", "async def delete", "async def overwrite", "async def ingest"):
        assert banned not in protocol_source
    assert "async def search" in protocol_source
    assert "async def get_document" in protocol_source
    assert "async def fetch_content" in protocol_source


def _knowledge_python_files() -> list[Path]:
    return sorted(path for path in KNOWLEDGE_ROOT.rglob("*.py") if path.is_file())


def test_no_panel_research_router_or_mcp_imports():
    for path in _knowledge_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name not in _FORBIDDEN_MODULES, f"{path} imports {name}"
                for prefix in _FORBIDDEN_IMPORT_PREFIXES:
                    assert name != prefix and not name.startswith(prefix + "."), (
                        f"{path} imports {name}"
                    )


def test_no_ocr_implementation():
    banned_names = {
        "ocr_image",
        "ocr_pdf",
        "run_ocr",
        "tesseract",
    }
    for path in _knowledge_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        overlap = defined & banned_names
        assert not overlap, f"{path} defines OCR helpers {overlap}"


async def test_vector_store_is_replaceable(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id)
    memory = MemoryKnowledgeVectorStore()
    await memory.upsert_chunks(
        [_embedded(_chunk(document_id="doc-brief", text="cykelbana", customer_id=kund.id))]
    )
    fake_client = FakeVectorBucketClient()
    bucket_store = SupabaseVectorBucketStore(fake_client)
    await bucket_store.upsert_chunks(
        [_embedded(_chunk(document_id="doc-brief", text="cykelbana", customer_id=kund.id))]
    )
    scope = _scope(customer_id=kund.id)
    query = KnowledgeQuery(query="cykelbana", scope=scope)
    via_memory = _provider(session, memory)
    via_bucket = _provider(session, bucket_store)
    memory_hits = await via_memory.search(query)
    bucket_hits = await via_bucket.search(query)
    assert [hit.document_id for hit in memory_hits] == ["doc-brief"]
    assert [hit.document_id for hit in bucket_hits] == ["doc-brief"]
    assert all(isinstance(hit, KnowledgeHit) for hit in memory_hits + bucket_hits)


def test_knowledge_scope_requires_customer_id():
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeScope(module="legal")
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeScope(case_id="case-1")
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeScope()
    scoped = KnowledgeScope(customer_id=7)
    assert scoped.customer_id == 7
    assert scoped.case_id is None
    assert scoped.module is None
    narrowed = KnowledgeScope(customer_id=7, case_id="case-1", module="legal")
    assert narrowed.customer_id == 7
    assert narrowed.case_id == "case-1"
    assert narrowed.module == "legal"


def test_query_rejects_unscoped_global_retrieval():
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeQuery(query="anything", scope=KnowledgeScope())
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeQuery(query="anything", scope=KnowledgeScope(module="legal"))
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeQuery(query="anything", scope=KnowledgeScope(case_id="case-1"))


async def test_provider_lookup_ignores_other_provider_rows(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-drive",
        provider="gdrive",
        bucket="drive",
        key="files/brief.pdf",
    )
    await put_object("drive", "files/brief.pdf", b"drive-bytes", "application/pdf")
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            _embedded(
                KnowledgeChunk(
                    document_id="doc-drive",
                    chunk_id="c1",
                    text="skattesats från drive",
                    customer_id=kund.id,
                    case_id="case-1",
                    module="dd",
                    title="Brief",
                    locator="p1",
                    provider=SUPABASE_PROVIDER_ID,
                )
            )
        ]
    )
    provider = _provider(session, store)
    scope = _scope(customer_id=kund.id)
    assert await provider.get_document("doc-drive", scope) is None
    with pytest.raises(KnowledgeNotFoundError):
        await provider.fetch_content("doc-drive", scope)
    assert await provider.search(KnowledgeQuery(query="skattesats", scope=scope)) == []


async def test_search_overfetches_when_top_hits_are_not_visible(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id, document_id="doc-valid")
    store = RankedVectorStore(
        [
            KnowledgeHit(
                document_id="doc-stale",
                provider=SUPABASE_PROVIDER_ID,
                title="Stale",
                excerpt="skattesats stale",
                locator="p0",
            ),
            KnowledgeHit(
                document_id="doc-valid",
                provider=SUPABASE_PROVIDER_ID,
                title="Brief",
                excerpt="skattesats valid",
                locator="p1",
            ),
        ]
    )
    embeddings = FakeEmbeddingProvider()
    provider = _provider(session, store, embeddings=embeddings)
    hits = await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id), limit=1)
    )
    assert [hit.document_id for hit in hits] == ["doc-valid"]
    assert store.requested_limits[0] == 1
    assert store.requested_limits[-1] >= 2
    assert embeddings.calls == [("skattesats",)]


async def test_search_stops_when_first_page_fills_limit(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id, document_id="doc-valid")
    store = RankedVectorStore(
        [
            KnowledgeHit(
                document_id="doc-valid",
                provider=SUPABASE_PROVIDER_ID,
                title="Brief",
                excerpt="skattesats valid",
                locator="p1",
            ),
            KnowledgeHit(
                document_id="doc-extra",
                provider=SUPABASE_PROVIDER_ID,
                title="Extra",
                excerpt="skattesats extra",
                locator="p2",
            ),
        ]
    )
    provider = _provider(session, store)
    hits = await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id), limit=1)
    )
    assert [hit.document_id for hit in hits] == ["doc-valid"]
    assert store.requested_limits == [1]


def test_registry_starts_empty_until_register():
    registry = KnowledgeProviderRegistry()
    assert registry.list_ids() == []
    with pytest.raises(KnowledgeProviderNotFoundError):
        registry.get("supabase")


def test_embedded_query_rejects_empty_vector():
    with pytest.raises(ValueError, match="embedding"):
        EmbeddedKnowledgeQuery(
            query=KnowledgeQuery(query="x", scope=KnowledgeScope(customer_id=1)),
            embedding=[],
        )


async def test_search_rejects_dimension_mismatch():
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [_embedded(_chunk(document_id="doc-a", text="skola", customer_id=1))]
    )
    with pytest.raises(KnowledgeVectorStoreError, match="dimension"):
        await store.search(
            EmbeddedKnowledgeQuery(
                query=KnowledgeQuery(query="skola", scope=KnowledgeScope(customer_id=1)),
                embedding=[0.1, 0.2],
            )
        )


def test_vector_store_does_not_create_embeddings():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "knowledge"
        / "vector_store.py"
    ).read_text(encoding="utf-8")
    assert "EmbeddingProvider" not in source
    assert "embed(" not in source
    assert "query=query.query" not in source
