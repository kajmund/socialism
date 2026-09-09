"""Knowledge ingest: extract → chunk → embed → vector store. No panel/OCR/MCP."""

from __future__ import annotations

import ast
import hashlib
import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import KnowledgeDocumentRecord, Kund
from app.services.knowledge.chunking import KnowledgeChunker, hash_text, make_chunk_id
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.knowledge.extractors import DOCX_MIME, DefaultTextExtractor
from app.services.knowledge.ingest import KnowledgeIngestService
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
)
from app.services.knowledge.provider import KnowledgeNotFoundError
from app.services.knowledge.supabase_provider import (
    SUPABASE_PROVIDER_ID,
    SupabaseKnowledgeProvider,
    supabase_external_id,
)
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.object_storage import put_object

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


class FakeEmbeddingProvider:
    provider_id = "fake"
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = False

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        if self.fail:
            raise RuntimeError("embedding failed")
        return [_vector(text) for text in texts]


class TrackingProvider:
    def __init__(self, inner: SupabaseKnowledgeProvider) -> None:
        self.provider_id = inner.provider_id
        self._inner = inner
        self.fetch_calls: list[tuple[str, KnowledgeScope]] = []

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        return await self._inner.search(query)

    async def get_document(self, document_id: str, scope: KnowledgeScope):
        return await self._inner.get_document(document_id, scope)

    async def fetch_content(self, document_id: str, scope: KnowledgeScope) -> bytes:
        self.fetch_calls.append((document_id, scope))
        return await self._inner.fetch_content(document_id, scope)


def _vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [byte / 255.0 for byte in digest[:8]]


def _scope(*, customer_id: int, case_id: str | None = "case-1", module: str | None = "dd") -> KnowledgeScope:
    return KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module)


async def _customer(session: AsyncSession, slug: str) -> Kund:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


async def _index_document(
    session: AsyncSession,
    *,
    customer_id: int,
    document_id: str,
    mime_type: str,
    key: str,
    title: str = "Brief",
    case_id: str | None = "case-1",
    module: str | None = "dd",
    bucket: str = "acme",
    version: str = "1",
) -> KnowledgeDocumentRecord:
    row = KnowledgeDocumentRecord(
        document_id=document_id,
        provider=SUPABASE_PROVIDER_ID,
        external_id=supabase_external_id(bucket, key),
        customer_id=customer_id,
        case_id=case_id,
        module=module,
        title=title,
        mime_type=mime_type,
        storage_bucket=bucket,
        storage_key=key,
        version=version,
        extra={"origin": "files"},
    )
    session.add(row)
    await session.flush()
    return row


def _ingest(
    provider: TrackingProvider | SupabaseKnowledgeProvider,
    store: MemoryKnowledgeVectorStore,
    embeddings: FakeEmbeddingProvider,
    *,
    chunker: KnowledgeChunker | None = None,
) -> KnowledgeIngestService:
    return KnowledgeIngestService(
        provider=provider,
        vector_store=store,
        embeddings=embeddings,
        chunker=chunker,
    )


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_text_pdf(*page_texts: str, with_text: bool = True) -> bytes:
    texts = list(page_texts) or [""]
    page_ids = [4 + index * 2 for index in range(len(texts))]
    content_ids = [pid + 1 for pid in page_ids]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objs: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, content_id, text in zip(page_ids, content_ids, texts, strict=True):
        if with_text and text:
            stream = f"BT /F1 12 Tf 72 720 Td ({_pdf_escape(text)}) Tj ET\n"
        else:
            stream = "\n"
        objs[content_id] = f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}endstream"
        objs[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        )
    out = bytearray(b"%PDF-1.1\n")
    offsets: dict[int, int] = {}
    for obj_id in range(1, max(objs) + 1):
        offsets[obj_id] = len(out)
        out.extend(f"{obj_id} 0 obj\n{objs[obj_id]}\nendobj\n".encode("latin-1"))
    xref_pos = len(out)
    count = max(objs) + 1
    out.extend(f"xref\n0 {count}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, count):
        out.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode())
    out.extend(f"trailer << /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())
    return bytes(out)


def build_docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


async def test_plaintext_ingest_searchable_with_locator(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
    )
    body = "Kommunens skattesats för vindkraft.\n\nAndra stycket om cykelbanor."
    await put_object("acme", "dd/files/brief.txt", body.encode(), "text/plain")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(provider, store, embeddings).ingest_document(
        document_id="doc-txt",
        scope=_scope(customer_id=kund.id),
    )
    assert result.status == "indexed"
    assert result.chunks_indexed >= 1
    assert result.content_hash == hashlib.sha256(body.encode()).hexdigest()
    assert len(embeddings.calls) == 1
    assert len(embeddings.calls[0]) == result.chunks_indexed
    hits = await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id))
    )
    assert len(hits) == 1
    assert hits[0].document_id == "doc-txt"
    assert "skattesats" in hits[0].excerpt
    assert hits[0].locator is not None
    assert hits[0].locator.startswith("line:")


async def test_text_pdf_is_indexed(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-pdf",
        mime_type="application/pdf",
        key="dd/files/brief.pdf",
    )
    pdf = build_text_pdf("kommunens skattesats")
    await put_object("acme", "dd/files/brief.pdf", pdf, "application/pdf")
    store = MemoryKnowledgeVectorStore()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(provider, store, FakeEmbeddingProvider()).ingest_document(
        document_id="doc-pdf",
        scope=_scope(customer_id=kund.id),
    )
    assert result.status == "indexed"
    hits = await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id))
    )
    assert [hit.document_id for hit in hits] == ["doc-pdf"]
    assert hits[0].locator == "page:1"


async def test_docx_is_indexed(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-docx",
        mime_type=DOCX_MIME,
        key="dd/files/brief.docx",
    )
    await put_object("acme", "dd/files/brief.docx", build_docx("vatten och avlopp"), DOCX_MIME)
    store = MemoryKnowledgeVectorStore()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(provider, store, FakeEmbeddingProvider()).ingest_document(
        document_id="doc-docx",
        scope=_scope(customer_id=kund.id),
    )
    assert result.status == "indexed"
    hits = await provider.search(
        KnowledgeQuery(query="avlopp", scope=_scope(customer_id=kund.id))
    )
    assert [hit.document_id for hit in hits] == ["doc-docx"]
    assert hits[0].locator == "paragraph:1"


async def test_empty_document_returns_empty(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-empty",
        mime_type="text/plain",
        key="dd/files/empty.txt",
    )
    await put_object("acme", "dd/files/empty.txt", b"   \n", "text/plain")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(provider, store, embeddings).ingest_document(
        document_id="doc-empty",
        scope=_scope(customer_id=kund.id),
    )
    assert result.status == "empty"
    assert result.chunks_indexed == 0
    assert embeddings.calls == []
    assert store.chunks == []


async def test_scanned_pdf_returns_needs_ocr(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-scan",
        mime_type="application/pdf",
        key="dd/files/scan.pdf",
    )
    await put_object("acme", "dd/files/scan.pdf", build_text_pdf("", with_text=False), "application/pdf")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(provider, store, embeddings).ingest_document(
        document_id="doc-scan",
        scope=_scope(customer_id=kund.id),
    )
    assert result.status == "needs_ocr"
    assert result.chunks_indexed == 0
    assert embeddings.calls == []


async def test_unsupported_mime_returns_unsupported(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-png",
        mime_type="image/png",
        key="dd/files/shot.png",
    )
    await put_object("acme", "dd/files/shot.png", b"\x89PNG", "image/png")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(provider, store, embeddings).ingest_document(
        document_id="doc-png",
        scope=_scope(customer_id=kund.id),
    )
    assert result.status == "unsupported"
    assert embeddings.calls == []


async def test_wrong_customer_scope_denied_before_fetch(session: AsyncSession):
    owner = await _customer(session, "acme")
    other = await _customer(session, "other")
    await _index_document(
        session,
        customer_id=owner.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
    )
    await put_object("acme", "dd/files/brief.txt", b"hemligt", "text/plain")
    store = MemoryKnowledgeVectorStore()
    inner = SupabaseKnowledgeProvider(session, vector_store=store)
    provider = TrackingProvider(inner)
    with pytest.raises(KnowledgeNotFoundError):
        await _ingest(provider, store, FakeEmbeddingProvider()).ingest_document(
            document_id="doc-txt",
            scope=_scope(customer_id=other.id),
        )
    assert provider.fetch_calls == []


async def test_chunk_metadata_uses_verified_document_scope(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
        case_id="case-owned",
        module="dd",
    )
    await put_object("acme", "dd/files/brief.txt", b"skattesats i kommunen", "text/plain")
    store = MemoryKnowledgeVectorStore()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    await _ingest(provider, store, FakeEmbeddingProvider()).ingest_document(
        document_id="doc-txt",
        scope=KnowledgeScope(customer_id=kund.id),
    )
    assert store.chunks
    for item in store.chunks:
        chunk = item.chunk
        assert chunk.customer_id == kund.id
        assert chunk.case_id == "case-owned"
        assert chunk.module == "dd"
        assert chunk.provider == SUPABASE_PROVIDER_ID
        assert chunk.metadata["customer_id"] == kund.id
        assert chunk.metadata["case_id"] == "case-owned"
        assert chunk.metadata["module"] == "dd"
        assert chunk.metadata["document_id"] == "doc-txt"
        assert chunk.metadata["provider"] == SUPABASE_PROVIDER_ID
        assert chunk.metadata["content_hash"] == chunk.content_hash
        assert chunk.metadata["locator"] == chunk.locator


async def test_same_document_version_text_reuses_chunk_id():
    document = KnowledgeDocument(
        document_id="doc-a",
        provider="supabase",
        external_id="acme/a.txt",
        title="A",
        mime_type="text/plain",
        scope=KnowledgeScope(customer_id=1, case_id="c1", module="dd"),
        version="3",
    )
    extracted = await DefaultTextExtractor().extract(
        b"Samma stycke om skattesats.",
        "text/plain",
    )
    chunker = KnowledgeChunker(target_chars=80, overlap_chars=0)
    first = chunker.chunk(extracted, document)
    second = chunker.chunk(extracted, document)
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert first[0].chunk_id == make_chunk_id(
        document_id="doc-a",
        version="3",
        locator=first[0].locator,
        content_hash=first[0].content_hash or "",
    )


async def test_changed_text_changes_content_hash():
    scope = KnowledgeScope(customer_id=1, case_id="c1", module="dd")
    document = KnowledgeDocument(
        document_id="doc-a",
        provider="supabase",
        external_id="acme/a.txt",
        title="A",
        mime_type="text/plain",
        scope=scope,
        version="1",
    )
    chunker = KnowledgeChunker(target_chars=80, overlap_chars=0)
    first = chunker.chunk(await DefaultTextExtractor().extract(b"alpha", "text/plain"), document)
    second = chunker.chunk(await DefaultTextExtractor().extract(b"beta", "text/plain"), document)
    assert first[0].content_hash != second[0].content_hash
    assert first[0].content_hash == hash_text(first[0].text)


async def test_embeddings_are_batched(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
    )
    body = "Forsta stycket om skola.\n\nAndra stycket om vard.\n\nTredje stycket om trafik."
    await put_object("acme", "dd/files/brief.txt", body.encode(), "text/plain")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await _ingest(
        provider,
        store,
        embeddings,
        chunker=KnowledgeChunker(target_chars=40, overlap_chars=0),
    ).ingest_document(document_id="doc-txt", scope=_scope(customer_id=kund.id))
    assert result.status == "indexed"
    assert result.chunks_indexed >= 2
    assert len(embeddings.calls) == 1
    assert len(embeddings.calls[0]) == result.chunks_indexed


async def test_openai_embedding_provider_batches_one_request_per_window():
    requests: list[list[str]] = []

    class _Client:
        class embeddings:
            @staticmethod
            async def create(*, model: str, input: list[str]):
                requests.append(input)
                return SimpleNamespace(
                    data=[
                        SimpleNamespace(index=index, embedding=[float(index)])
                        for index in range(len(input))
                    ]
                )

    provider = OpenAIEmbeddingProvider(client=_Client(), batch_size=2, dimension=1)
    vectors = await provider.embed(["a", "b", "c"])
    assert requests == [["a", "b"], ["c"]]
    assert vectors == [[0.0], [1.0], [0.0]]


async def test_extraction_failure_leaves_old_vectors(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-pdf",
        mime_type="application/pdf",
        key="dd/files/brief.pdf",
    )
    await put_object(
        "acme",
        "dd/files/brief.pdf",
        build_text_pdf("ursprunglig skattesats"),
        "application/pdf",
    )
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    service = _ingest(provider, store, embeddings)
    first = await service.ingest_document(document_id="doc-pdf", scope=_scope(customer_id=kund.id))
    assert first.status == "indexed"
    old_ids = {item.chunk.chunk_id for item in store.chunks}

    await put_object("acme", "dd/files/brief.pdf", b"%PDF-1.4 not-a-real-pdf", "application/pdf")
    failed = await service.ingest_document(document_id="doc-pdf", scope=_scope(customer_id=kund.id))
    assert failed.status == "failed"
    assert {item.chunk.chunk_id for item in store.chunks} == old_ids
    hits = await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id))
    )
    assert [hit.document_id for hit in hits] == ["doc-pdf"]


async def test_embedding_failure_leaves_old_vectors(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
    )
    await put_object("acme", "dd/files/brief.txt", b"ursprunglig skattesats", "text/plain")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    service = _ingest(provider, store, embeddings)
    first = await service.ingest_document(document_id="doc-txt", scope=_scope(customer_id=kund.id))
    assert first.status == "indexed"
    old_ids = {item.chunk.chunk_id for item in store.chunks}

    await put_object("acme", "dd/files/brief.txt", b"ny text om cykelbanor", "text/plain")
    embeddings.fail = True
    failed = await service.ingest_document(document_id="doc-txt", scope=_scope(customer_id=kund.id))
    assert failed.status == "failed"
    assert {item.chunk.chunk_id for item in store.chunks} == old_ids
    hits = await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id))
    )
    assert [hit.document_id for hit in hits] == ["doc-txt"]


async def test_successful_reindex_replaces_old_chunks(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
    )
    await put_object("acme", "dd/files/brief.txt", b"ursprunglig skattesats", "text/plain")
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    service = _ingest(provider, store, embeddings)
    first = await service.ingest_document(document_id="doc-txt", scope=_scope(customer_id=kund.id))
    assert first.status == "indexed"
    old_ids = {item.chunk.chunk_id for item in store.chunks}

    await put_object("acme", "dd/files/brief.txt", b"ny text om cykelbanor", "text/plain")
    second = await service.ingest_document(document_id="doc-txt", scope=_scope(customer_id=kund.id))
    assert second.status == "indexed"
    new_ids = {item.chunk.chunk_id for item in store.chunks}
    assert new_ids
    assert old_ids.isdisjoint(new_ids)
    assert await provider.search(
        KnowledgeQuery(query="skattesats", scope=_scope(customer_id=kund.id))
    ) == []
    hits = await provider.search(
        KnowledgeQuery(query="cykelbanor", scope=_scope(customer_id=kund.id))
    )
    assert [hit.document_id for hit in hits] == ["doc-txt"]


async def test_vector_store_and_embeddings_are_replaceable(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(
        session,
        customer_id=kund.id,
        document_id="doc-txt",
        mime_type="text/plain",
        key="dd/files/brief.txt",
    )
    await put_object("acme", "dd/files/brief.txt", b"ersattbar vektorbutik", "text/plain")

    class AlternateStore(MemoryKnowledgeVectorStore):
        def __init__(self) -> None:
            super().__init__()
            self.replaced: list[str] = []

        async def replace_document_chunks(
            self,
            document_id: str,
            chunks: Sequence[EmbeddedKnowledgeChunk],
        ) -> None:
            self.replaced.append(document_id)
            await super().replace_document_chunks(document_id, chunks)

    store = AlternateStore()
    embeddings = FakeEmbeddingProvider()
    provider = SupabaseKnowledgeProvider(session, vector_store=store)
    result = await KnowledgeIngestService(
        provider=provider,
        vector_store=store,
        embeddings=embeddings,
    ).ingest_document(document_id="doc-txt", scope=_scope(customer_id=kund.id))
    assert result.status == "indexed"
    assert store.replaced == ["doc-txt"]
    assert embeddings.calls


def test_ingest_modules_stay_isolated_from_panel_research_and_mcp():
    for path in sorted(KNOWLEDGE_ROOT.rglob("*.py")):
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


def test_no_ocr_helpers_in_ingest_modules():
    banned = {"ocr_image", "ocr_pdf", "run_ocr", "tesseract"}
    for path in sorted(KNOWLEDGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not (defined & banned), f"{path} defines OCR helpers"
