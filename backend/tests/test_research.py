"""ResearchNeed → ResearchRouter → KnowledgeResearchSource → ResearchEvidence."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import KnowledgeDocumentRecord, Kund
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    KnowledgeScopeRequiredError,
)
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID
from app.services.knowledge.supabase_provider import (
    SupabaseKnowledgeProvider,
    supabase_external_id,
)
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.research import (
    RESEARCH_SOURCE_TYPES,
    KnowledgeResearchSource,
    ResearchContext,
    ResearchNeed,
    ResearchRouter,
    ResearchSourceRegistry,
    ResearchSourceType,
    build_research_registry,
    make_evidence_id,
    provenance_from_hit,
    search_scope,
)
from app.services.research.router import ResearchRouter as RouterImpl
from tests.knowledge_fakes import FakeEmbeddingProvider, fake_embed_text

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "research"

_FORBIDDEN_IMPORT_PREFIXES = (
    "app.services.panel",
    "app.services.rattsunderlag",
    "app.llm",
    "app.services.dd.research",
    "app.services.spindoctor_mcp_tools",
)

_FORBIDDEN_MODULES = {
    "openai",
    "lagen_nu",
}

_LLM_MARKERS = (
    "complete_text",
    "complete_structured",
    "openai",
    "chat.completions",
    "EmbeddingProvider",
)


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


class RecordingKnowledgeProvider:
    provider_id = "memory"

    def __init__(self, hits: list[KnowledgeHit] | None = None, *, error: Exception | None = None) -> None:
        self.hits = hits or []
        self.error = error
        self.queries: list[KnowledgeQuery] = []

    async def search(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return [
            hit
            for hit in self.hits
            if hit.metadata.get("customer_id") in (None, query.scope.customer_id)
            and (
                query.scope.case_id is None
                or hit.metadata.get("case_id") in (None, query.scope.case_id)
            )
        ]

    async def get_document(self, document_id: str, scope: KnowledgeScope) -> KnowledgeDocument | None:
        return None

    async def fetch_content(self, document_id: str, scope: KnowledgeScope) -> bytes:
        raise AssertionError("research must not fetch document bytes")


class FakeResearchSource:
    def __init__(
        self,
        source_type: str,
        evidence: list | None = None,
        *,
        error: Exception | None = None,
        empty: bool = False,
        provider_id: str | None = "fake",
    ) -> None:
        self.source_type = source_type
        self._evidence = evidence or []
        self.error = error
        self.empty = empty
        self.provider_id = provider_id
        self.calls = 0

    async def research(self, need: ResearchNeed, context: ResearchContext):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.empty:
            return []
        return list(self._evidence)


def _need(*source_types: ResearchSourceType, question: str = "Vad gäller skattesatsen?") -> ResearchNeed:
    return ResearchNeed(
        id="research_1",
        question=question,
        why_needed="behövs för bedömning",
        requested_by=["legal"],
        source_types=list(source_types),
    )


def _context(*, customer_id: int = 7, case_id: str | None = "case-1", module: str | None = "dd") -> ResearchContext:
    return ResearchContext(
        scope=KnowledgeScope(customer_id=customer_id, case_id=case_id, module=module)
    )


def _hit(
    *,
    document_id: str = "doc-brief",
    excerpt: str = "kommunens skattesats är 32%",
    locator: str | None = "p1",
    customer_id: int = 7,
    case_id: str | None = "case-1",
    version: str = "1",
    source_url: str | None = None,
    extra: dict | None = None,
) -> KnowledgeHit:
    metadata: dict[str, object] = {
        "customer_id": customer_id,
        "case_id": case_id,
        "version": version,
        "origin": "files",
    }
    if source_url:
        metadata["source_url"] = source_url
    if extra:
        metadata.update(extra)
    return KnowledgeHit(
        document_id=document_id,
        provider=SUPABASE_PROVIDER_ID,
        title="Brief",
        excerpt=excerpt,
        score=0.91,
        locator=locator,
        external_id="acme/dd/files/brief.pdf",
        metadata=metadata,
    )


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
    case_id: str | None = "case-1",
    module: str | None = "dd",
) -> KnowledgeDocumentRecord:
    row = KnowledgeDocumentRecord(
        document_id=document_id,
        provider=SUPABASE_PROVIDER_ID,
        external_id=supabase_external_id("acme", "dd/files/brief.pdf"),
        customer_id=customer_id,
        case_id=case_id,
        module=module,
        title="Brief",
        mime_type="application/pdf",
        storage_bucket="acme",
        storage_key="dd/files/brief.pdf",
        version="1",
        extra={"origin": "files", "version": "1"},
    )
    session.add(row)
    await session.flush()
    return row


def _chunk(*, document_id: str, text: str, customer_id: int, case_id: str | None = "case-1") -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id=document_id,
        chunk_id="c1",
        text=text,
        customer_id=customer_id,
        case_id=case_id,
        module="dd",
        title="Brief",
        locator="p1",
        provider=SUPABASE_PROVIDER_ID,
        version="1",
        content_hash="hash-1",
        metadata={"version": "1"},
    )


def test_knowledge_adapter_refuses_unimplemented_domain_namespace():
    with pytest.raises(ValueError, match="not a private-knowledge adapter"):
        KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="domain_knowledge")


def test_source_type_taxonomy_matches_planned_research_plan():
    assert RESEARCH_SOURCE_TYPES == (
        "case_knowledge",
        "customer_knowledge",
        "domain_knowledge",
        "swedish_law",
        "swedish_preparatory_works",
        "web",
    )


def test_evidence_ids_are_deterministic():
    first = make_evidence_id(
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        provider="supabase",
        source_id="doc-brief",
        locator="p1",
        excerpt="kommunens skattesats",
    )
    second = make_evidence_id(
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        provider="supabase",
        source_id="doc-brief",
        locator="p1",
        excerpt="kommunens skattesats",
    )
    other_excerpt = make_evidence_id(
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        provider="supabase",
        source_id="doc-brief",
        locator="p1",
        excerpt="annan text",
    )
    assert first == second
    assert first != other_excerpt
    assert len(first) == 64


def test_knowledge_hit_normalizes_to_research_evidence():
    hit = _hit(source_url="https://example.test/brief")
    evidence = KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="case_knowledge")._from_hit(
        _need("case_knowledge"), hit
    )
    assert evidence.status == "found"
    assert evidence.title == "Brief"
    assert evidence.excerpt == hit.excerpt
    assert evidence.locator == "p1"
    assert evidence.source_id == "doc-brief"
    assert evidence.provider == "supabase"
    assert evidence.score == 0.91
    assert evidence.source_url == "https://example.test/brief"
    assert evidence.metadata["document_id"] == "doc-brief"
    assert evidence.metadata["external_id"] == "acme/dd/files/brief.pdf"
    assert evidence.metadata["version"] == "1"
    assert evidence.metadata["locator"] == "p1"
    assert evidence.metadata["origin"] == "files"
    assert evidence.evidence_id == make_evidence_id(
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        provider="supabase",
        source_id="doc-brief",
        locator="p1",
        excerpt=hit.excerpt,
    )


def test_provenance_keeps_version_and_drops_storage_secrets():
    hit = _hit(extra={"storage_bucket": "acme", "storage_key": "dd/files/brief.pdf", "api_key": "secret"})
    meta = provenance_from_hit(hit)
    assert meta["version"] == "1"
    assert meta["document_id"] == "doc-brief"
    assert "storage_bucket" not in meta
    assert "storage_key" not in meta
    assert "api_key" not in meta


def test_storage_path_is_not_used_as_source_url():
    hit = _hit()
    evidence = KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="case_knowledge")._from_hit(
        _need("case_knowledge"), hit
    )
    assert evidence.source_url is None
    assert evidence.source_id == hit.document_id


async def test_case_knowledge_uses_customer_and_case_scope():
    provider = RecordingKnowledgeProvider([_hit()])
    source = KnowledgeResearchSource(provider, source_type="case_knowledge")
    evidence = await source.research(_need("case_knowledge"), _context(customer_id=7, case_id="case-1"))
    assert [item.status for item in evidence] == ["found"]
    assert provider.queries[0].scope.customer_id == 7
    assert provider.queries[0].scope.case_id == "case-1"
    assert provider.queries[0].query == "Vad gäller skattesatsen?"


async def test_customer_knowledge_drops_case_but_keeps_customer_and_module():
    provider = RecordingKnowledgeProvider([_hit()])
    source = KnowledgeResearchSource(provider, source_type="customer_knowledge")
    context = _context(customer_id=7, case_id="case-1", module="dd")
    await source.research(_need("customer_knowledge"), context)
    scope = provider.queries[0].scope
    assert scope.customer_id == 7
    assert scope.case_id is None
    assert scope.module == "dd"
    assert context.scope.case_id == "case-1"


def test_search_scope_never_changes_customer_id():
    context = _context(customer_id=7, case_id="case-1", module="legal")
    case_scope = search_scope("case_knowledge", context)
    customer_scope = search_scope("customer_knowledge", context)
    assert case_scope.customer_id == 7
    assert customer_scope.customer_id == 7
    assert case_scope.case_id == "case-1"
    assert customer_scope.case_id is None
    with pytest.raises(Exception, match="no Knowledge adapter"):
        search_scope("domain_knowledge", context)


async def test_customer_knowledge_cannot_read_other_customer():
    provider = RecordingKnowledgeProvider(
        [_hit(customer_id=2, excerpt="hemlig skattesats från annan kund")]
    )
    source = KnowledgeResearchSource(provider, source_type="customer_knowledge")
    evidence = await source.research(_need("customer_knowledge"), _context(customer_id=1, case_id=None))
    assert [item.status for item in evidence] == ["not_found"]
    assert provider.queries[0].scope.customer_id == 1


async def test_missing_customer_scope_fails_closed():
    with pytest.raises(KnowledgeScopeRequiredError):
        ResearchContext(scope=KnowledgeScope())
    with pytest.raises(KnowledgeScopeRequiredError):
        KnowledgeScope(case_id="case-1", module="dd")


async def test_case_knowledge_without_case_id_fails_closed_as_error():
    provider = RecordingKnowledgeProvider([_hit()])
    registry = ResearchSourceRegistry()
    registry.register(KnowledgeResearchSource(provider, source_type="case_knowledge"))
    router = ResearchRouter(registry)
    evidence = await router.execute_need(_need("case_knowledge"), _context(case_id=None))
    assert [item.status for item in evidence] == ["error"]
    assert evidence[0].metadata["error_type"] == "ResearchScopeRequiredError"
    assert "case_id" in (evidence[0].excerpt or "")
    assert provider.queries == []
    assert "acme/" not in (evidence[0].excerpt or "")


async def test_empty_search_is_not_found():
    provider = RecordingKnowledgeProvider([])
    source = KnowledgeResearchSource(provider, source_type="case_knowledge")
    evidence = await source.research(_need("case_knowledge"), _context())
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].research_need_id == "research_1"
    assert evidence[0].source_type == "case_knowledge"
    assert evidence[0].provider == "memory"


async def test_source_exception_is_error_and_other_sources_continue():
    boom = FakeResearchSource("case_knowledge", error=RuntimeError("/secret/store/path leaked"))
    ok = FakeResearchSource(
        "customer_knowledge",
        [
            KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="customer_knowledge")._from_hit(
                _need("customer_knowledge"), _hit()
            )
        ],
    )
    registry = ResearchSourceRegistry()
    registry.register(boom)
    registry.register(ok)
    router = ResearchRouter(registry)
    evidence = await router.execute_need(
        _need("case_knowledge", "customer_knowledge"),
        _context(),
    )
    assert [item.source_type for item in evidence] == ["case_knowledge", "customer_knowledge"]
    assert evidence[0].status == "error"
    assert evidence[0].metadata["error_type"] == "RuntimeError"
    assert "/secret/store" not in (evidence[0].excerpt or "")
    assert "path leaked" not in (evidence[0].excerpt or "")
    assert evidence[1].status == "found"
    assert boom.calls == 1
    assert ok.calls == 1


async def test_router_runs_source_types_in_order_and_keeps_all_provenance():
    first = FakeResearchSource(
        "case_knowledge",
        [
            KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="case_knowledge")._from_hit(
                _need("case_knowledge"), _hit(document_id="doc-a", locator="p1", excerpt="alpha")
            ),
            KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="case_knowledge")._from_hit(
                _need("case_knowledge"), _hit(document_id="doc-a", locator="p2", excerpt="alpha-two")
            ),
        ],
    )
    second = FakeResearchSource(
        "customer_knowledge",
        [
            KnowledgeResearchSource(RecordingKnowledgeProvider(), source_type="customer_knowledge")._from_hit(
                _need("customer_knowledge"), _hit(document_id="doc-a", locator="p1", excerpt="alpha")
            )
        ],
    )
    registry = ResearchSourceRegistry()
    registry.register(first)
    registry.register(second)
    router = ResearchRouter(registry)
    evidence = await router.execute_need(
        _need("case_knowledge", "customer_knowledge"),
        _context(),
    )
    assert [item.source_type for item in evidence] == [
        "case_knowledge",
        "case_knowledge",
        "customer_knowledge",
    ]
    assert [item.locator for item in evidence] == ["p1", "p2", "p1"]
    assert evidence[0].evidence_id != evidence[1].evidence_id
    assert evidence[0].source_id == evidence[2].source_id


async def test_unregistered_source_type_is_explicit_error():
    registry = ResearchSourceRegistry()
    registry.register(
        KnowledgeResearchSource(RecordingKnowledgeProvider([_hit()]), source_type="case_knowledge")
    )
    router = ResearchRouter(registry)
    evidence = await router.execute_need(
        _need("case_knowledge", "domain_knowledge", "web"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found", "error", "error"]
    assert evidence[1].metadata["source_type"] == "domain_knowledge"
    assert "No research source registered" in (evidence[1].excerpt or "")
    assert "domain_knowledge" in (evidence[1].excerpt or "")
    assert "customer_id=None" not in (evidence[1].excerpt or "")
    assert evidence[2].metadata["source_type"] == "web"


def test_default_registry_has_no_domain_or_web_adapter():
    registry = build_research_registry(RecordingKnowledgeProvider())
    assert registry.registered_types() == ["case_knowledge", "customer_knowledge"]
    assert registry.sources_for("domain_knowledge") == []
    assert registry.sources_for("swedish_law") == []
    assert registry.sources_for("web") == []


def test_router_source_has_no_llm():
    source = inspect.getsource(RouterImpl)
    for marker in _LLM_MARKERS:
        assert marker not in source
    assert "source_types" in source
    assert "sources_for" in source


def test_research_package_has_no_panel_llm_or_mcp_imports():
    for path in sorted(RESEARCH_ROOT.rglob("*.py")):
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


def test_research_package_does_not_implement_web_or_law_clients():
    banned = {"lagen.nu", "LagenNu", "google", "mcp", "Riksdag", "OCR"}
    for path in RESEARCH_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path} mentions {token}"


def test_knowledge_source_uses_provider_search_not_domain_fallback():
    source = inspect.getsource(KnowledgeResearchSource)
    assert "KnowledgeProvider" in source
    assert "async def search" in inspect.getsource(RecordingKnowledgeProvider)
    assert "customer_id=None" in inspect.getsource(search_scope)


async def test_acceptance_router_searches_knowledge_provider(session: AsyncSession):
    kund = await _customer(session, "acme")
    await _index_document(session, customer_id=kund.id)
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            EmbeddedKnowledgeChunk(
                chunk=_chunk(
                    document_id="doc-brief",
                    text="kommunens skattesats är 32 procent",
                    customer_id=kund.id,
                ),
                embedding=fake_embed_text("kommunens skattesats är 32 procent"),
            )
        ]
    )
    provider = SupabaseKnowledgeProvider(
        session,
        vector_store=store,
        embeddings=FakeEmbeddingProvider(),
    )
    router = ResearchRouter(build_research_registry(provider))
    need = ResearchNeed(
        id="research_1",
        question="skattesats",
        why_needed="underlag",
        requested_by=["legal"],
        source_types=["case_knowledge"],
    )
    evidence = await router.execute_need(need, _context(customer_id=kund.id, case_id="case-1"))
    assert len(evidence) == 1
    item = evidence[0]
    assert item.status == "found"
    assert item.research_need_id == "research_1"
    assert item.source_type == "case_knowledge"
    assert item.source_id == "doc-brief"
    assert item.locator == "p1"
    assert "skattesats" in (item.excerpt or "")
    assert item.provider == SUPABASE_PROVIDER_ID
    assert item.metadata["document_id"] == "doc-brief"
    assert item.metadata["version"] == "1"
    assert item.retrieved_at.tzinfo is not None


async def test_acceptance_wrong_customer_is_not_found(session: AsyncSession):
    owner = await _customer(session, "acme")
    other = await _customer(session, "other")
    await _index_document(session, customer_id=owner.id)
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            EmbeddedKnowledgeChunk(
                chunk=_chunk(
                    document_id="doc-brief",
                    text="kommunens skattesats är 32 procent",
                    customer_id=owner.id,
                ),
                embedding=fake_embed_text("kommunens skattesats är 32 procent"),
            )
        ]
    )
    provider = SupabaseKnowledgeProvider(
        session,
        vector_store=store,
        embeddings=FakeEmbeddingProvider(),
    )
    router = ResearchRouter(build_research_registry(provider))
    evidence = await router.execute_need(
        _need("customer_knowledge", question="skattesats"),
        _context(customer_id=other.id, case_id=None),
    )
    assert [item.status for item in evidence] == ["not_found"]
