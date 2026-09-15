"""KnowledgeProvider capability registry + deterministic routing."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.services.research import (
    KnowledgeProviderCapabilityRegistry,
    KnowledgeProviderDescriptor,
    KnowledgeResearchSource,
    NeedConstraints,
    ProviderAccess,
    ResearchContext,
    ResearchNeed,
    ResearchRouter,
    build_research_registry,
    constraints_from_need,
    rank_provider_candidates,
)
from app.services.research.provider import descriptor_from_source
from app.services.research.router import ResearchRouter as RouterImpl
from tests.test_research import (
    FakeResearchSource,
    RecordingKnowledgeProvider,
    _context,
    _hit,
    _need,
)

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "research"

_LLM_MARKERS = (
    "complete_text",
    "complete_structured",
    "openai",
    "chat.completions",
    "EmbeddingProvider",
    "embed",
)


def _descriptor(
    provider_id: str,
    *,
    source_type: str = "case_knowledge",
    domains: frozenset[str] = frozenset(),
    modalities: frozenset[str] = frozenset({"text"}),
    capabilities: frozenset[str] = frozenset({"search"}),
    rank: int = 0,
    mechanism: str = "adapter",
) -> KnowledgeProviderDescriptor:
    return KnowledgeProviderDescriptor(
        provider_id=provider_id,
        domains=domains,
        modalities=modalities,
        capabilities=capabilities,
        evidence_natures=frozenset({source_type}),
        authority={"retrieval_provider": provider_id.split(".", 1)[0]},
        access=ProviderAccess(mechanism=mechanism, adapter="fake"),
        rank=rank,
    )


def _found_source(
    source_type: str,
    provider_id: str,
    excerpt: str,
    *,
    descriptor: KnowledgeProviderDescriptor | None = None,
) -> tuple[FakeResearchSource, KnowledgeProviderDescriptor]:
    evidence = KnowledgeResearchSource(
        RecordingKnowledgeProvider(), source_type=source_type
    )._from_hit(
        _need(source_type),
        _hit(document_id=f"doc-{provider_id}", excerpt=excerpt, locator="p1"),
    )
    source = FakeResearchSource(source_type, [evidence], provider_id=provider_id)
    return source, descriptor or _descriptor(f"{provider_id}.{source_type}", source_type=source_type)


def test_constraints_from_need_use_source_types_as_evidence_natures():
    need = ResearchNeed(
        id="research_1",
        question="q",
        why_needed="w",
        source_types=["case_knowledge", "customer_knowledge"],
        domains=["tenant"],
        modalities=["text"],
        capabilities=["search"],
    )
    constraints = constraints_from_need(need)
    assert constraints.evidence_natures == ("case_knowledge", "customer_knowledge")
    assert constraints.domains == frozenset({"tenant"})
    assert constraints.modalities == frozenset({"text"})
    assert constraints.capabilities == frozenset({"search"})


async def test_multiple_matching_providers_run_in_deterministic_order():
    first, first_desc = _found_source("case_knowledge", "alpha", "alpha-hit")
    second, second_desc = _found_source("case_knowledge", "beta", "beta-hit")
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(second, descriptor=second_desc)
    registry.register(first, descriptor=first_desc)
    evidence = await ResearchRouter(registry).execute_need(_need("case_knowledge"), _context())
    assert [item.excerpt for item in evidence] == ["alpha-hit", "beta-hit"]
    assert [item.provider for item in evidence] == ["supabase", "supabase"]
    assert first.calls == 1
    assert second.calls == 1


async def test_no_matching_provider_is_explicit_not_found():
    source, descriptor = _found_source("case_knowledge", "memory", "should-not-run")
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(source, descriptor=descriptor)
    need = ResearchNeed(
        id="research_1",
        question="q",
        why_needed="w",
        source_types=["case_knowledge"],
        capabilities=["similarity"],
    )
    evidence = await ResearchRouter(registry).execute_need(need, _context())
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata["reason"] == "no_matching_provider"
    assert evidence[0].metadata["error_type"] == "ResearchCapabilityUnavailableError"
    assert "similarity" in (evidence[0].excerpt or "")
    assert source.calls == 0


async def test_unregistered_evidence_nature_is_error_not_fallback():
    source, descriptor = _found_source("case_knowledge", "memory", "should-not-run")
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(source, descriptor=descriptor)
    evidence = await ResearchRouter(registry).execute_need(_need("domain_knowledge"), _context())
    assert [item.status for item in evidence] == ["error"]
    assert evidence[0].metadata["source_type"] == "domain_knowledge"
    assert "No research source registered" in (evidence[0].excerpt or "")
    assert source.calls == 0


async def test_capability_and_domain_filters_do_not_use_unrelated_providers():
    tenant, tenant_desc = _found_source(
        "case_knowledge",
        "tenant-search",
        "tenant-hit",
        descriptor=_descriptor(
            "tenant.search",
            domains=frozenset({"tenant"}),
            capabilities=frozenset({"search"}),
        ),
    )
    public, public_desc = _found_source(
        "case_knowledge",
        "public-search",
        "public-hit",
        descriptor=_descriptor(
            "public.search",
            domains=frozenset({"public"}),
            capabilities=frozenset({"search"}),
        ),
    )
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(public, descriptor=public_desc)
    registry.register(tenant, descriptor=tenant_desc)
    need = ResearchNeed(
        id="research_1",
        question="q",
        why_needed="w",
        source_types=["case_knowledge"],
        domains=["tenant"],
        capabilities=["search"],
    )
    evidence = await ResearchRouter(registry).execute_need(need, _context())
    assert [item.excerpt for item in evidence] == ["tenant-hit"]
    assert tenant.calls == 1
    assert public.calls == 0


async def test_ranking_is_rank_then_provider_id():
    late, late_desc = _found_source(
        "case_knowledge",
        "zeta",
        "late-hit",
        descriptor=_descriptor("zeta.case", rank=0),
    )
    early, early_desc = _found_source(
        "case_knowledge",
        "alpha",
        "early-hit",
        descriptor=_descriptor("alpha.case", rank=5),
    )
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(early, descriptor=early_desc)
    registry.register(late, descriptor=late_desc)
    first = await ResearchRouter(registry).execute_need(_need("case_knowledge"), _context())
    assert [item.excerpt for item in first] == ["late-hit", "early-hit"]
    ranked = rank_provider_candidates(registry.registered_providers(), constraints_from_need(_need("case_knowledge")))
    assert [item.descriptor.provider_id for item in ranked] == ["zeta.case", "alpha.case"]
    again = rank_provider_candidates(list(reversed(registry.registered_providers())), NeedConstraints())
    assert [item.descriptor.provider_id for item in again] == ["zeta.case", "alpha.case"]


async def test_tenant_scope_is_not_widened_by_routed_provider():
    provider = RecordingKnowledgeProvider([_hit(customer_id=7, case_id="case-1")])
    registry = build_research_registry(provider)
    context = _context(customer_id=7, case_id="case-1")
    evidence = await ResearchRouter(registry).execute_need(
        _need("case_knowledge", "customer_knowledge"),
        context,
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert provider.queries[0].scope.customer_id == 7
    assert provider.queries[0].scope.case_id == "case-1"
    assert provider.queries[1].scope.customer_id == 7
    assert provider.queries[1].scope.case_id is None
    assert context.scope.case_id == "case-1"
    assert context.scope.customer_id == 7


async def test_provider_exception_is_isolated():
    boom = FakeResearchSource("case_knowledge", error=RuntimeError("/secret/store/path leaked"))
    ok, ok_desc = _found_source("customer_knowledge", "ok", "ok-hit")
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(boom, descriptor=_descriptor("boom.case", source_type="case_knowledge"))
    registry.register(ok, descriptor=ok_desc)
    evidence = await ResearchRouter(registry).execute_need(
        _need("case_knowledge", "customer_knowledge"),
        _context(),
    )
    assert [item.status for item in evidence] == ["error", "found"]
    assert evidence[0].metadata["error_type"] == "RuntimeError"
    assert "/secret/store" not in (evidence[0].excerpt or "")
    assert evidence[1].excerpt == "ok-hit"
    assert boom.calls == 1
    assert ok.calls == 1


async def test_provenance_survives_capability_routing():
    source, descriptor = _found_source("case_knowledge", "memory", "kommunens skattesats")
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(source, descriptor=descriptor)
    evidence = await ResearchRouter(registry).execute_need(_need("case_knowledge"), _context())
    item = evidence[0]
    assert item.status == "found"
    assert item.provider == "supabase"
    assert item.source_type == "case_knowledge"
    assert item.source_id == "doc-memory"
    assert item.locator == "p1"
    assert item.source_url is None
    assert item.score == 0.91
    assert item.metadata["document_id"] == "doc-memory"


async def test_existing_knowledge_providers_keep_tenant_behavior():
    provider = RecordingKnowledgeProvider([_hit()])
    registry = build_research_registry(provider)
    assert isinstance(registry, KnowledgeProviderCapabilityRegistry)
    ids = [entry.descriptor.provider_id for entry in registry.registered_providers()]
    assert ids == ["memory.case_knowledge", "memory.customer_knowledge"]
    for entry in registry.registered_providers():
        assert entry.descriptor.modalities == frozenset({"text"})
        assert entry.descriptor.capabilities == frozenset({"search"})
        assert entry.descriptor.access.mechanism == "adapter"
        assert entry.descriptor.authority["tenant_bound"] is True
    source = KnowledgeResearchSource(provider, source_type="customer_knowledge")
    await source.research(_need("customer_knowledge"), _context(customer_id=7, case_id="case-1"))
    assert provider.queries[-1].scope.customer_id == 7
    assert provider.queries[-1].scope.case_id is None


def test_router_and_registry_make_no_llm_or_embedding_call():
    for source in (
        inspect.getsource(RouterImpl),
        inspect.getsource(KnowledgeProviderCapabilityRegistry),
        inspect.getsource(rank_provider_candidates),
    ):
        for marker in _LLM_MARKERS:
            assert marker not in source


async def test_synthetic_non_text_capability_needs_no_router_change():
    text, text_desc = _found_source(
        "case_knowledge",
        "text-search",
        "text-hit",
        descriptor=_descriptor("text.search", capabilities=frozenset({"search"})),
    )
    image_hit = KnowledgeResearchSource(
        RecordingKnowledgeProvider(), source_type="case_knowledge"
    )._from_hit(_need("case_knowledge"), _hit(document_id="img-1", excerpt="similar-image", locator="img"))
    image = FakeResearchSource("case_knowledge", [image_hit], provider_id="image-sim")
    image_desc = KnowledgeProviderDescriptor(
        provider_id="synthetic.image_similarity",
        domains=frozenset({"example"}),
        modalities=frozenset({"image"}),
        capabilities=frozenset({"similarity"}),
        evidence_natures=frozenset({"case_knowledge"}),
        authority={"retrieval_provider": "image-sim"},
        access=ProviderAccess(mechanism="vector_store", adapter="fake_image"),
        rank=0,
    )
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(text, descriptor=text_desc)
    registry.register(image, descriptor=image_desc)
    need = ResearchNeed(
        id="research_1",
        question="hitta liknande bild",
        why_needed="w",
        source_types=["case_knowledge"],
        modalities=["image"],
        capabilities=["similarity"],
    )
    evidence = await ResearchRouter(registry).execute_need(need, _context())
    assert [item.excerpt for item in evidence] == ["similar-image"]
    assert image.calls == 1
    assert text.calls == 0
    router_source = inspect.getsource(RouterImpl)
    assert "image" not in router_source
    assert "similarity" not in router_source
    assert "vector_store" not in router_source


async def test_empty_need_does_not_select_all_providers():
    source, descriptor = _found_source("case_knowledge", "memory", "should-not-run")
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(source, descriptor=descriptor)
    need = ResearchNeed(id="research_1", question="q", why_needed="w")
    evidence = await ResearchRouter(registry).execute_need(need, _context())
    assert evidence == []
    assert source.calls == 0


def test_inferred_descriptor_keeps_research_source_compat():
    source = FakeResearchSource("customer_knowledge", provider_id="fake")
    descriptor = descriptor_from_source(source)
    assert descriptor.provider_id == "fake.customer_knowledge"
    assert descriptor.evidence_natures == frozenset({"customer_knowledge"})
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(source)
    assert registry.sources_for("customer_knowledge") == [source]
    assert registry.registered_types() == ["customer_knowledge"]


def test_research_package_still_forbids_llm_imports():
    forbidden = {"openai", "app.llm"}
    for path in RESEARCH_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name not in forbidden
                assert not name.startswith("app.llm.")
