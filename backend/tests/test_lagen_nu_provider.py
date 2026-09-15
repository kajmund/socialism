"""Official lagen.nu KnowledgeProvider: descriptor, adapter, provenance, isolation."""

from __future__ import annotations

import inspect

from app.services.knowledge.models import KnowledgeScope
from app.services.lagen_nu.mcp_client import (
    OfficialLagenNuMcpError,
    parse_document,
    parse_resolved_citations,
    parse_search_results,
)
from app.services.lagen_nu.models import (
    LagenNuDocument,
    LagenNuPin,
    LagenNuSearchHit,
    ResolvedCitations,
    SearchResults,
)
from app.services.lagen_nu.registration import (
    LAGEN_NU_ADAPTER,
    LAGEN_NU_AUTHORITY_WARNING,
    LAGEN_NU_PROVIDER_ID,
    lagen_nu_capability_descriptors,
    lagen_nu_descriptor,
)
from app.services.lagen_nu.uris import canonical_lagen_nu_uri, compose_canonical_uri
from app.services.research import (
    KnowledgeProviderCapabilityRegistry,
    KnowledgeResearchSource,
    LagenNuResearchSource,
    ResearchContext,
    ResearchNeed,
    ResearchRouter,
    build_research_registry,
    production_registered_source_types,
)
from app.services.research.composition import standard_available_source_types
from app.services.research.lagen_nu_source import (
    MAX_DOCUMENT_FETCHES,
    MAX_SEARCH_HITS,
    looks_like_citation,
    select_lagen_nu_flow,
)
from app.services.research.registry import default_standard_capability_descriptors
from tests.test_research import RecordingKnowledgeProvider, _context, _need


def _hit(
    *,
    uri: str = "https://lagen.nu/1915:218",
    title: str = "Avtalslagen",
    source: str = "sfs",
    pinpoint: str | None = "P36",
    highlight: str = "Avtalsvillkor får jämkas",
    score: float | None = 12.5,
) -> LagenNuSearchHit:
    pin = None
    if pinpoint:
        pin = LagenNuPin(
            uri=f"{uri}#{pinpoint}",
            pinpoint=pinpoint,
            label="36 §",
            highlight=(highlight,),
        )
    return LagenNuSearchHit(
        id=f"{uri}#{pinpoint}" if pinpoint else uri,
        uri=uri,
        url="https://ferenda.lagen.nu/1915:218",
        title=title,
        identifier="SFS 1915:218",
        source=source,
        kind="lag",
        score=score,
        inbound_count=10,
        pin=pin,
        fragments=(),
        highlight=(),
    )


def _document(
    *,
    uri: str = "https://lagen.nu/1915:218",
    pinpoint: str | None = "P36",
    text: str = "Avtalsvillkor får jämkas eller lämnas utan avseende.",
    source: str = "sfs",
) -> LagenNuDocument:
    return LagenNuDocument(
        uri=uri,
        title="Lag (1915:218) om avtal",
        text=text,
        source=source,
        kind="lag",
        label="36 §",
        publisher_source_url="https://svenskforfattningssamling.se/1915:218",
        pinpoint=pinpoint,
        truncated=False,
        inbound_count=10,
    )


class FakeLagenNuClient:
    def __init__(
        self,
        *,
        search: SearchResults | None = None,
        resolved: ResolvedCitations | None = None,
        documents: dict[str, LagenNuDocument] | None = None,
        search_error: Exception | None = None,
        resolve_error: Exception | None = None,
        document_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.search_payload = search or SearchResults(query="", total=0, results=())
        self.resolved_payload = resolved or ResolvedCitations()
        self.documents = documents or {}
        self.search_error = search_error
        self.resolve_error = resolve_error
        self.document_error = document_error

    async def search(self, query: str, *, source: str | None = None, kind: str | None = None, limit: int = 10):
        self.calls.append(("search", {"query": query, "source": source, "kind": kind, "limit": limit}))
        if self.search_error is not None:
            raise self.search_error
        return self.search_payload

    async def resolve_citation(self, citation: str):
        self.calls.append(("resolve_citation", {"citation": citation}))
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.resolved_payload

    async def get_document(self, uri: str, *, pinpoint: str | None = None, max_chars: int = 8000):
        self.calls.append(
            ("get_document", {"uri": uri, "pinpoint": pinpoint, "max_chars": max_chars})
        )
        if self.document_error is not None:
            raise self.document_error
        key = uri if pinpoint is None else f"{uri}#{pinpoint}"
        if key in self.documents:
            return self.documents[key]
        if uri in self.documents:
            return self.documents[uri]
        raise OfficialLagenNuMcpError(f"missing document {key}")


def _source(
    client: FakeLagenNuClient,
    source_type: str = "swedish_law",
) -> LagenNuResearchSource:
    return LagenNuResearchSource(source_type=source_type, client=client)


def test_canonical_uri_rewrites_ferenda_and_rejects_foreign_hosts():
    assert canonical_lagen_nu_uri("https://ferenda.lagen.nu/1915:218#P36") == (
        "https://lagen.nu/1915:218#P36"
    )
    assert canonical_lagen_nu_uri("http://lagen.nu/1981:130") == "https://lagen.nu/1981:130"
    assert canonical_lagen_nu_uri("https://example.com/1915:218") is None
    assert compose_canonical_uri("https://lagen.nu/1915:218", "P36") == (
        "https://lagen.nu/1915:218#P36"
    )


def test_parse_search_and_resolve_payloads():
    search = parse_search_results(
        {
            "query": "avtalslagen",
            "total": 1,
            "results": [
                {
                    "id": "https://lagen.nu/1915:218#P36",
                    "uri": "https://lagen.nu/1915:218",
                    "url": "https://ferenda.lagen.nu/1915:218",
                    "title": "Avtalslagen",
                    "source": "sfs",
                    "kind": "lag",
                    "score": 1.5,
                    "pin": {
                        "uri": "https://lagen.nu/1915:218#P36",
                        "pinpoint": "P36",
                        "label": "36 §",
                        "highlight": ["<em>Avtal</em>svillkor"],
                    },
                    "fragments": [],
                }
            ],
        }
    )
    assert search.results[0].uri == "https://lagen.nu/1915:218"
    assert search.results[0].pin is not None
    assert search.results[0].pin.pinpoint == "P36"
    resolved = parse_resolved_citations(
        {
            "results": [],
            "recognized": [{"uri": "https://lagen.nu/2099:1", "source": "sfs", "invalid": True}],
        }
    )
    assert resolved.recognized[0].invalid is True
    document = parse_document(
        {
            "uri": "https://lagen.nu/1915:218",
            "title": "Avtalslagen",
            "text": "text",
            "source": "sfs",
            "kind": "lag",
            "label": "Avtalslagen",
            "source_url": "https://svenskforfattningssamling.se/1915:218",
            "inbound_count": 1,
            "pinpoint": None,
            "format": "md",
            "truncated": False,
        }
    )
    assert document.publisher_source_url is not None


def test_production_introspection_exposes_lagen_nu_natures():
    descriptors = default_standard_capability_descriptors()
    lagen = [item for item in descriptors if item.access.adapter == LAGEN_NU_ADAPTER]
    assert lagen == list(lagen_nu_capability_descriptors())
    assert {item.provider_id for item in lagen} == {
        "lagen_nu.swedish_law",
        "lagen_nu.swedish_preparatory_works",
    }
    for item in lagen:
        assert item.domains == frozenset({"law"})
        assert item.modalities == frozenset({"text"})
        assert item.access.mechanism == "mcp"
        assert item.authority["jurisdiction"] == "SE"
        assert item.authority["tenant_bound"] is False
        assert "citation_graph" not in item.capabilities
    offered = production_registered_source_types()
    assert offered == standard_available_source_types()
    assert "swedish_law" in offered
    assert "swedish_preparatory_works" in offered
    assert "web" not in offered
    assert "domain_knowledge" not in offered


def test_planner_sees_legal_natures_from_registry_not_a_hardcoded_list():
    source = inspect.getsource(production_registered_source_types)
    assert "standard_capability_descriptors" in source
    assert '"swedish_law"' not in source
    assert offered_from_descriptors() == production_registered_source_types()


def offered_from_descriptors() -> tuple[str, ...]:
    seen: list[str] = []
    for descriptor in default_standard_capability_descriptors():
        for nature in sorted(descriptor.evidence_natures):
            if nature not in seen:
                seen.append(nature)
    return tuple(seen)


def test_descriptor_factory_refuses_unimplemented_nature():
    try:
        lagen_nu_descriptor("web")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "web" in str(exc)
    else:
        raise AssertionError("expected ValueError")


async def test_search_normalizes_canonical_uri_and_mcp_provenance():
    hit = _hit()
    client = FakeLagenNuClient(
        search=SearchResults(query="jämkning", total=1, results=(hit,)),
        documents={"https://lagen.nu/1915:218#P36": _document()},
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="jämkning av avtalsvillkor"),
        _context(customer_id=9, case_id="case-secret"),
    )
    assert [item.status for item in evidence] == ["found"]
    item = evidence[0]
    assert item.provider == LAGEN_NU_PROVIDER_ID
    assert item.source_type == "swedish_law"
    assert item.source_id == "https://lagen.nu/1915:218#P36"
    assert item.source_url == "https://lagen.nu/1915:218#P36"
    assert item.title == "Lag (1915:218) om avtal"
    assert "jämkas" in (item.excerpt or "")
    assert item.locator == "P36"
    assert item.metadata["canonical_uri"] == item.source_id
    assert item.metadata["automated_corpus"] is True
    assert item.metadata["authority_warning"] == LAGEN_NU_AUTHORITY_WARNING
    assert item.metadata["jurisdiction"] == "SE"
    assert item.metadata["publisher_source_url"] == (
        "https://svenskforfattningssamling.se/1915:218"
    )
    tools = [call["tool"] for call in item.metadata["mcp_calls"]]
    assert tools == ["search", "get_document"]
    assert [name for name, _args in client.calls] == ["search", "get_document"]
    assert client.calls[0][1]["source"] == "sfs"
    assert "customer_id" not in str(client.calls)
    assert "case-secret" not in str(client.calls)


async def test_citation_resolution_path_fetches_pinpoint():
    hit = _hit()
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(hit,)),
        documents={"https://lagen.nu/1915:218#P36": _document()},
    )
    need = ResearchNeed(
        id="research_1",
        question="avtalslagen 36 §",
        why_needed="w",
        source_types=["swedish_law"],
        capabilities=["resolve_citation"],
    )
    evidence = await _source(client).research(need, _context())
    assert evidence[0].status == "found"
    assert evidence[0].source_id == "https://lagen.nu/1915:218#P36"
    assert [name for name, _args in client.calls] == ["resolve_citation", "get_document"]
    assert looks_like_citation(need.question)
    assert select_lagen_nu_flow(need) == "resolve"


async def test_recognized_only_citation_is_not_found_without_search():
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(
            recognized=(),
        )
    )
    client.resolved_payload = parse_resolved_citations(
        {"results": [], "recognized": [{"uri": "https://lagen.nu/2099:1", "invalid": True}]}
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="SFS 2099:1"),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert [name for name, _args in client.calls] == ["resolve_citation"]


async def test_empty_resolve_falls_through_to_search():
    hit = _hit()
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(),
        search=SearchResults(query="q", total=1, results=(hit,)),
        documents={"https://lagen.nu/1915:218#P36": _document()},
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="avtalslagen 36 §"),
        _context(),
    )
    assert evidence[0].status == "found"
    assert [name for name, _args in client.calls] == [
        "resolve_citation",
        "search",
        "get_document",
    ]


async def test_no_hit_is_not_found_without_tenant_fallback():
    provider = RecordingKnowledgeProvider()
    client = FakeLagenNuClient(search=SearchResults(query="q", total=0, results=()))
    registry = KnowledgeProviderCapabilityRegistry()
    registry.register(
        _source(client),
        descriptor=lagen_nu_descriptor("swedish_law"),
    )
    registry.register(KnowledgeResearchSource(provider, source_type="case_knowledge"))
    evidence = await ResearchRouter(registry).execute_need(
        _need("swedish_law", question="okänt påhittat lagrum"),
        _context(customer_id=3, case_id="case-1"),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].provider == LAGEN_NU_PROVIDER_ID
    assert provider.queries == []
    assert [name for name, _args in client.calls] == ["search"]


async def test_provider_error_is_isolated_and_does_not_call_tenant_knowledge():
    provider = RecordingKnowledgeProvider()
    client = FakeLagenNuClient(search_error=OfficialLagenNuMcpError("lagen.nu MCP timed out"))
    registry = build_research_registry(provider)
    for entry in list(registry.registered_providers()):
        if entry.descriptor.access.adapter == LAGEN_NU_ADAPTER:
            entry.source._client = client  # type: ignore[attr-defined]
    evidence = await ResearchRouter(registry).execute_need(
        _need("swedish_law", "case_knowledge", question="jämkning"),
        _context(customer_id=3, case_id="case-1"),
    )
    statuses = [item.status for item in evidence]
    assert "error" in statuses
    assert statuses.count("error") == 1
    error = next(item for item in evidence if item.status == "error")
    assert error.provider == LAGEN_NU_PROVIDER_ID
    assert error.metadata["error_type"] == "OfficialLagenNuMcpError"
    assert provider.queries  # case_knowledge still ran
    assert all("customer_id" not in str(args) for _name, args in client.calls)


async def test_call_bounds_cap_search_and_fetches():
    hits = tuple(
        _hit(uri=f"https://lagen.nu/1981:{index}", pinpoint=None, highlight=f"hit {index}")
        for index in range(1, 9)
    )
    documents = {
        f"https://lagen.nu/1981:{index}": _document(
            uri=f"https://lagen.nu/1981:{index}",
            pinpoint=None,
            text=f"text {index}",
        )
        for index in range(1, 9)
    }
    client = FakeLagenNuClient(
        search=SearchResults(query="preskription", total=20, results=hits),
        documents=documents,
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="preskription av fordran"),
        ResearchContext(scope=KnowledgeScope(customer_id=1, case_id="c", module="dd"), limit=20),
    )
    assert [item.status for item in evidence] == ["found"] * MAX_DOCUMENT_FETCHES
    search_calls = [args for name, args in client.calls if name == "search"]
    fetch_calls = [args for name, args in client.calls if name == "get_document"]
    assert search_calls[0]["limit"] == MAX_SEARCH_HITS
    assert len(fetch_calls) == MAX_DOCUMENT_FETCHES
    assert len(client.calls) == 1 + MAX_DOCUMENT_FETCHES


async def test_preparatory_works_use_forarbete_source_filter():
    hit = _hit(
        uri="https://lagen.nu/prop/2009/10:241",
        title="Prop. 2009/10:241",
        source="forarbete",
        pinpoint="sec1",
        highlight="integritetsskydd",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="integritetsskydd", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/prop/2009/10:241#sec1": _document(
                uri="https://lagen.nu/prop/2009/10:241",
                pinpoint="sec1",
                text="Ett förstärkt integritetsskydd",
                source="forarbete",
            )
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need("swedish_preparatory_works", question="integritetsskydd"),
        _context(),
    )
    assert evidence[0].status == "found"
    assert evidence[0].source_type == "swedish_preparatory_works"
    assert client.calls[0][1]["source"] == "forarbete"
    assert evidence[0].source_id == "https://lagen.nu/prop/2009/10:241#sec1"


async def test_wrong_source_hits_are_not_used_for_swedish_law():
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(
            results=(_hit(source="eurlex", uri="https://lagen.nu/celex/32016R0679"),)
        )
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="GDPR artikel 32"),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert [name for name, _args in client.calls] == ["resolve_citation"]


async def test_standard_registry_keeps_tenant_providers_unchanged():
    provider = RecordingKnowledgeProvider()
    registry = build_research_registry(provider)
    knowledge = [
        entry
        for entry in registry.registered_providers()
        if entry.descriptor.access.adapter == "knowledge_research_source"
    ]
    lagen = [
        entry
        for entry in registry.registered_providers()
        if entry.descriptor.access.adapter == LAGEN_NU_ADAPTER
    ]
    assert len(knowledge) == 2
    assert len(lagen) == 2
    assert all(entry.descriptor.authority["tenant_bound"] is True for entry in knowledge)
    assert all(entry.source.provider_id == "memory" for entry in knowledge)
    assert all(entry.source.provider_id == LAGEN_NU_PROVIDER_ID for entry in lagen)
    await ResearchRouter(registry).execute_need(
        _need("case_knowledge"),
        _context(customer_id=4, case_id="case-1"),
    )
    assert provider.queries
    assert provider.queries[0].scope.customer_id == 4


def test_adapter_is_programmatic():
    source = inspect.getsource(LagenNuResearchSource)
    for marker in ("complete_text", "complete_structured", "openai", "chat.completions"):
        assert marker not in source
    assert "resolve_citation" in source
    assert "get_document" in source


def test_flow_selection_is_deterministic():
    search_need = _need("swedish_law", question="Vad gäller skattesatsen?")
    assert select_lagen_nu_flow(search_need) == "search"
    resolve_need = ResearchNeed(
        id="research_1",
        question="Vad gäller skattesatsen?",
        why_needed="w",
        source_types=["swedish_law"],
        capabilities=["resolve_citation"],
    )
    assert select_lagen_nu_flow(resolve_need) == "resolve"
