"""Official lagen.nu KnowledgeProvider: descriptor, adapter, provenance, isolation."""

from __future__ import annotations

import inspect
from dataclasses import replace

from app.services.knowledge.models import KnowledgeScope
from app.services.lagen_nu.display import choose_legal_excerpt
from app.services.lagen_nu.mcp_client import (
    OfficialLagenNuMcpError,
    parse_document,
    parse_incoming_citations,
    parse_resolved_citations,
    parse_search_results,
)
from app.services.lagen_nu.models import (
    IncomingCitations,
    LagenNuDocument,
    LagenNuPin,
    LagenNuSearchHit,
    ResolvedCitations,
    SearchResults,
)
from app.services.lagen_nu.registration import (
    LAGEN_NU_ADAPTER,
    LAGEN_NU_PROVIDER_ID,
    LAGEN_NU_PUBLICATION_NOTE,
    lagen_nu_capability_descriptors,
    lagen_nu_descriptor,
)
from app.services.lagen_nu.research_source import (
    MAX_DOCUMENT_FETCHES,
    MAX_MCP_TOOL_CALLS,
    MAX_SEARCH_HITS,
    LagenNuResearchSource,
    _candidates,
    _preparatory_citations,
    _query_terms,
    looks_like_citation,
    select_lagen_nu_flow,
)
from app.services.lagen_nu.selection import (
    ExcerptDecision,
    HitDecision,
    LagenNuPassageSelector,
    LagenNuSelectionError,
    SelectableDocument,
    SelectableHit,
    set_passage_selector_factory,
    verify_excerpt_span,
)
from app.services.lagen_nu.uris import canonical_lagen_nu_uri, compose_canonical_uri
from app.services.research import (
    KnowledgeProviderCapabilityRegistry,
    KnowledgeResearchSource,
    ResearchContext,
    ResearchNeed,
    ResearchRouter,
    build_research_registry,
    production_registered_source_types,
)
from app.services.research.composition import standard_available_source_types
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
        highlight=() if pin is not None else ((highlight,) if highlight else ()),
    )


def _document(
    *,
    uri: str = "https://lagen.nu/1915:218",
    title: str = "Lag (1915:218) om avtal",
    pinpoint: str | None = "P36",
    text: str = "Avtalsvillkor får jämkas eller lämnas utan avseende.",
    source: str = "sfs",
) -> LagenNuDocument:
    return LagenNuDocument(
        uri=uri,
        title=title,
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
        incoming: IncomingCitations | None = None,
        documents: dict[str, LagenNuDocument] | None = None,
        search_error: Exception | None = None,
        resolve_error: Exception | None = None,
        document_error: Exception | None = None,
        resolved_by_citation: dict[str, ResolvedCitations] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.search_payload = search or SearchResults(query="", total=0, results=())
        self.resolved_payload = resolved or ResolvedCitations()
        self.resolved_by_citation = resolved_by_citation or {}
        self.incoming_payload = incoming or IncomingCitations(uri="https://lagen.nu/", total=0)
        self.documents = documents or {}
        self.search_error = search_error
        self.resolve_error = resolve_error
        self.document_error = document_error
        self.closed = False

    async def search(
        self, query: str, *, source: str | None = None, kind: str | None = None, limit: int = 10
    ):
        self.calls.append(
            ("search", {"query": query, "source": source, "kind": kind, "limit": limit})
        )
        if self.search_error is not None:
            raise self.search_error
        return self.search_payload

    async def resolve_citation(self, citation: str):
        self.calls.append(("resolve_citation", {"citation": citation}))
        if self.resolve_error is not None:
            raise self.resolve_error
        keyed = self.resolved_by_citation.get(citation) or self.resolved_by_citation.get(
            citation.casefold()
        )
        if keyed is not None:
            return keyed
        return self.resolved_payload

    async def get_incoming_citations(
        self,
        uri: str,
        *,
        source: str | None = None,
        sort: str = "rail",
        limit: int = 10,
    ):
        self.calls.append(
            (
                "get_incoming_citations",
                {"uri": uri, "source": source, "sort": sort, "limit": limit},
            )
        )
        return self.incoming_payload

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

    async def aclose(self) -> None:
        self.closed = True


class PassthroughLagenNuSelector:
    async def select_hits(
        self,
        *,
        need,
        source_type,
        candidates: list[SelectableHit],
        context,
    ) -> list[HitDecision]:
        return [
            HitDecision(
                candidate_id=item.candidate_id,
                keep=True,
                role="ratio",
                why="passthrough",
            )
            for item in candidates
        ]

    async def select_excerpt(
        self,
        *,
        need,
        source_type,
        document: SelectableDocument,
        context,
    ) -> ExcerptDecision:
        text = document.text or document.highlight
        if source_type == "swedish_case_law":
            excerpt = text
        else:
            excerpt = choose_legal_excerpt(
                document_text=text,
                hit_excerpt=document.highlight,
                terms=_query_terms(need.question),
                title=document.title,
                max_chars=16000,
            )
        excerpt = verify_excerpt_span(
            text,
            excerpt,
            max_chars=16000,
            allowed_extra=document.highlight,
        )
        return ExcerptDecision(
            excerpt=excerpt,
            pinpoint=document.pinpoint,
            why="passthrough",
        )


class TargetCaseCitationPlanner:
    async def plan(self, *, need, citations, context):
        from app.llm.lagen_nu_citation_intent import CaseCitationIntent, CaseCitationPlan
        return CaseCitationPlan(citations=[CaseCitationIntent(citation=c, role="target")
                                           for c in citations], search_query="")


def _source(
    client: FakeLagenNuClient,
    source_type: str = "swedish_law",
    selector: LagenNuPassageSelector | None = None,
    interpreter=None,
) -> LagenNuResearchSource:
    return LagenNuResearchSource(
        source_type=source_type,
        client=client,
        selector=selector or PassthroughLagenNuSelector(),
        interpreter=interpreter or FakeLegalInterpreter(),
        case_citation_planner=TargetCaseCitationPlanner(),
    )


class FakeLegalInterpreter:
    def __init__(self, *, quote=None, relation="contextual"):
        self.quote = quote
        self.relation = relation

    async def interpret(self, *, source, question, raw_text, truncated, context):
        from app.services.legal_research_result import (
            CaseLawAnalysis,
            LegalCitation,
            LegalQuestionRelation,
            LegalResearchResult,
            PreparatoryWorkAnalysis,
            StatuteAnalysis,
        )

        citation = LegalCitation(
            source_uri=source.canonical_uri,
            quote=self.quote or raw_text[: min(len(raw_text), 100)],
        )
        analyses = {
            "case_law": lambda: {
                "case_law": CaseLawAnalysis(
                    legal_issue=question,
                    court_reasoning=raw_text,
                    outcome="unknown",
                    citations=[citation],
                )
            },
            "preparatory_work": lambda: {
                "preparatory_work": PreparatoryWorkAnalysis(
                    legislative_intent=raw_text,
                    proposal_or_commentary=raw_text,
                    citations=[citation],
                )
            },
            "statute": lambda: {
                "statute": StatuteAnalysis(operative_rule=raw_text, citations=[citation])
            },
        }
        return LegalResearchResult(
            source=source,
            relation=LegalQuestionRelation(
                relation=self.relation, explanation=raw_text, confidence="low"
            ),
            raw_text=raw_text,
            truncated=truncated,
            **analyses[source.kind](),
        )


async def test_domain_extraction_failure_is_isolated_to_one_document():
    from app.llm.legal_research import LegalDomainExtractionError

    first_uri = "https://lagen.nu/1981:101"
    second_uri = "https://lagen.nu/1981:102"

    class FailsFirst(FakeLegalInterpreter):
        async def interpret(self, *, source, question, raw_text, truncated, context):
            if source.canonical_uri == first_uri:
                raise LegalDomainExtractionError("invalid structured output")
            return await super().interpret(
                source=source,
                question=question,
                raw_text=raw_text,
                truncated=truncated,
                context=context,
            )

    client = FakeLagenNuClient(
        search=SearchResults(
            query="preskription",
            total=2,
            results=(
                _hit(uri=first_uri, pinpoint=None, highlight="första fordran"),
                _hit(uri=second_uri, pinpoint=None, highlight="andra fordran"),
            ),
        ),
        documents={
            first_uri: _document(
                uri=first_uri,
                pinpoint=None,
                text="Första fordran preskriberas.",
            ),
            second_uri: _document(
                uri=second_uri,
                pinpoint=None,
                text="Andra fordran preskriberas.",
            ),
        },
    )
    evidence = await _source(client, interpreter=FailsFirst()).research(
        _need("swedish_law", question="preskription av fordran"), _context()
    )

    assert [item.status for item in evidence] == ["error", "found"]
    assert evidence[0].metadata["reason"] == "domain_schema_invalid"
    assert evidence[1].source_id == second_uri
    assert evidence[1].legal_result is not None
    assert [args["uri"] for name, args in client.calls if name == "get_document"] == [
        first_uri,
        second_uri,
    ]


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


def test_parse_incoming_citations_payload():
    parsed = parse_incoming_citations(
        {
            "uri": "https://lagen.nu/1915:218#P36",
            "total": 1,
            "citations": [
                {
                    "uri": "https://lagen.nu/dom/nja/1987s394",
                    "title": "NJA 1987 s. 394",
                    "source": "dv",
                    "kind": "case",
                    "inbound_count": 32,
                }
            ],
        }
    )
    assert parsed.uri == "https://lagen.nu/1915:218#P36"
    assert parsed.total == 1
    assert parsed.results[0].source == "dv"
    assert parsed.results[0].kind == "case"


def test_production_introspection_exposes_lagen_nu_natures():
    descriptors = default_standard_capability_descriptors()
    lagen = [item for item in descriptors if item.access.adapter == LAGEN_NU_ADAPTER]
    assert lagen == list(lagen_nu_capability_descriptors())
    assert {item.provider_id for item in lagen} == {
        "lagen_nu.swedish_law",
        "lagen_nu.swedish_case_law",
        "lagen_nu.swedish_preparatory_works",
    }
    for item in lagen:
        assert item.domains == frozenset({"law"})
        assert item.modalities == frozenset({"text"})
        assert item.access.mechanism == "mcp"
        assert item.authority["jurisdiction"] == "SE"
        assert item.authority["tenant_bound"] is False
    case_law = next(item for item in lagen if item.provider_id.endswith("swedish_case_law"))
    assert "citation_graph" in case_law.capabilities
    offered = production_registered_source_types()
    assert offered == standard_available_source_types()
    assert "swedish_law" in offered
    assert "swedish_case_law" in offered
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
    assert item.metadata["authority_level"] == "trusted"
    assert item.metadata["primary_source"] is True
    assert item.metadata["publication_note"] == LAGEN_NU_PUBLICATION_NOTE
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


async def test_proposition_cover_page_is_replaced_by_body_and_citation_title():
    hit = _hit(
        uri="https://lagen.nu/prop/1975:6",
        title="Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
        source="forarbete",
        pinpoint=None,
        highlight="Regeringens proposition nr 6 år 1975",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="q", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/prop/1975:6": _document(
                uri="https://lagen.nu/prop/1975:6",
                title="Regeringens proposition om ändring i konkurslagen (1921:225) m.m.",
                pinpoint=None,
                source="forarbete",
                text=(
                    "Regeringens proposition nr 6 år 1975 Prop. 1975:6 Nr 6 "
                    "Regeringens proposition om ändring i konkurslagen (1921:225) m.m.; "
                    "beslutad den 16 januari 1975.\n\n"
                    "Kungl. Maj:t föreslår riksdagen att anta ett nytt obeståndsbegrepp "
                    "som knyter konkursförutsättningen till gäldenärens betalningsoförmåga."
                ),
            )
        },
    )
    evidence = await _source(client, "swedish_preparatory_works", interpreter=FakeLegalInterpreter(quote="Kungl. Maj:t föreslår riksdagen att anta ett nytt obeståndsbegrepp som knyter konkursförutsättningen till gäldenärens betalningsoförmåga.")).research(
        _need(
            "swedish_preparatory_works",
            question="Hur bedöms obestånd enligt konkurslagen?",
        ),
        _context(),
    )
    item = evidence[0]
    assert item.status == "found"
    assert item.title == "Prop. 1975:6 — Ändring i konkurslagen (1921:225)"
    assert "obeståndsbegrepp" in (item.excerpt or "")
    assert "beslutad den 16 januari 1975" not in (item.excerpt or "")


async def test_search_highlight_cannot_replace_grounded_citation():
    hit = _hit(pinpoint=None, highlight="Omsättningstillgångar är tillgångar som...")
    client = FakeLagenNuClient(
        search=SearchResults(query="q", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/1915:218": _document(
                pinpoint=None,
                text="1 kap. Inledande bestämmelser\n" + ("x" * 20000),
            )
        },
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="Hur definieras omsättningstillgångar?"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found"]
    item = evidence[0]
    assert item.locator is None
    assert item.excerpt == item.legal_result.statute.citations[0].quote
    assert "Omsättningstillgångar" not in item.excerpt


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
        {
            "results": [],
            "recognized": [{"uri": "https://lagen.nu/2099:1", "source": "sfs", "invalid": True}],
        }
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


async def test_provider_error_does_not_call_disabled_tenant_knowledge():
    provider = RecordingKnowledgeProvider()
    client = FakeLagenNuClient(search_error=OfficialLagenNuMcpError("lagen.nu MCP timed out"))
    registry = build_research_registry(provider)
    for entry in list(registry.registered_providers()):
        if entry.descriptor.access.adapter == LAGEN_NU_ADAPTER:
            entry.source._client = client  # type: ignore[attr-defined]
    evidence = await ResearchRouter(registry).execute_need(
        _need("swedish_law", question="jämkning"),
        _context(customer_id=3, case_id="case-1"),
    )
    statuses = [item.status for item in evidence]
    assert "error" in statuses
    assert statuses.count("error") == 1
    error = next(item for item in evidence if item.status == "error")
    assert error.provider == LAGEN_NU_PROVIDER_ID
    assert error.metadata["failure_category"] == "fetch_failed"
    assert provider.queries == []
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
            "https://lagen.nu/prop/2009/10:241": _document(
                uri="https://lagen.nu/prop/2009/10:241",
                pinpoint=None,
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
    assert evidence[0].source_id == "https://lagen.nu/prop/2009/10:241"


async def test_preparatory_works_search_when_resolution_only_finds_statute():
    statute = _hit()
    preparatory_work = replace(
        _hit(
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            source="forarbete",
            pinpoint=None,
        ),
        highlight=("Förarbeten till 36 § avtalslagen.",),
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        search=SearchResults(
            query="prop. 1975/76:81",
            total=1,
            results=(preparatory_work,),
        ),
        documents={
            "https://lagen.nu/prop/1975/76:81": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                pinpoint=None,
                text="Förslag om en generalklausul i avtalslagen.",
                source="forarbete",
            )
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question="Vad anger prop. 1975/76:81 om avtalslagen 36 §?",
        ),
        _context(),
    )
    assert evidence[0].status == "found"
    assert [name for name, _args in client.calls] == [
        "resolve_citation",
        "search",
        "get_document",
    ]
    assert client.calls[0][1]["citation"] == "prop. 1975/76:81"
    assert client.calls[1][1]["query"] == ("prop. 1975/76:81 avtalslagen")
    assert client.calls[1][1]["source"] == "forarbete"


async def test_preparatory_works_use_incoming_citations_for_a_named_provision():
    statute = _hit()
    proposition = replace(
        _hit(
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            source="forarbete",
            pinpoint=None,
            highlight="36 § avtalslagen",
        ),
        identifier="Prop. 1975/76:81",
    )
    sou = replace(
        _hit(
            uri="https://lagen.nu/sou/1974:83",
            title="SOU 1974:83",
            source="forarbete",
            pinpoint=None,
            highlight="generalklausul 36 §",
        ),
        identifier="SOU 1974:83",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        incoming=IncomingCitations(
            uri="https://lagen.nu/1915:218#P36",
            total=2,
            results=(proposition, sou),
        ),
        documents={
            "https://lagen.nu/prop/1975/76:81": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                pinpoint=None,
                text=(
                    "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
                    "avtalets innehåll och omständigheterna vid avtalets tillkomst."
                ),
                source="forarbete",
            ),
            "https://lagen.nu/sou/1974:83": _document(
                uri="https://lagen.nu/sou/1974:83",
                pinpoint=None,
                text=(
                    "Utredningen föreslår att 36 § avtalslagen skall ge "
                    "domstolen rätt att jämka oskäliga avtalsvillkor."
                ),
                source="forarbete",
            ),
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question=(
                "Hur anger förarbetena till 36 § avtalslagen att jämkningsbedömningen ska göras?"
            ),
        ),
        _context(),
    )
    assert {item.source_id for item in evidence} == {
        "https://lagen.nu/prop/1975/76:81",
        "https://lagen.nu/sou/1974:83",
    }
    assert [name for name, _args in client.calls if name == "resolve_citation"] == [
        "resolve_citation"
    ]
    assert client.calls[0][1]["citation"] == "36 § avtalslagen"
    incoming = next(args for name, args in client.calls if name == "get_incoming_citations")
    assert incoming["uri"] == "https://lagen.nu/1915:218#P36"
    assert incoming["source"] == "forarbete"
    assert incoming["sort"] == "rail"


async def test_preparatory_works_resolve_every_named_citation():
    proposition = _hit(
        uri="https://lagen.nu/prop/1975/76:81",
        title="Prop. 1975/76:81",
        source="forarbete",
        pinpoint=None,
        highlight="Prop. 1975/76:81",
    )
    sou = _hit(
        uri="https://lagen.nu/sou/1974:83",
        title="SOU 1974:83",
        source="forarbete",
        pinpoint=None,
        highlight="SOU 1974:83",
    )
    false_positive = replace(
        _hit(
            uri="https://lagen.nu/sou/1979:36",
            title="SOU 1979:36",
            source="forarbete",
            pinpoint=None,
        ),
        highlight=("Kort omnämnande av 36 § avtalslagen.",),
        identifier="SOU 1979:36",
    )
    client = FakeLagenNuClient(
        resolved_by_citation={
            "prop. 1975/76:81": ResolvedCitations(results=(proposition,)),
            "SOU 1974:83": ResolvedCitations(results=(sou,)),
        },
        search=SearchResults(
            query="36 §",
            total=1,
            results=(false_positive,),
        ),
        documents={
            "https://lagen.nu/prop/1975/76:81": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                title="Prop. 1975/76:81 med förslag till lag om ändring i avtalslagen",
                pinpoint=None,
                text=(
                    "# Prop. 1975/76:81: med förslag till lag om ändring i lagen "
                    "(1915:218) om avtal\n\n"
                    "Huvudsakligt innehåll Propositionen föreslår en "
                    "generalklausul i avtalslagen.\n\n"
                    "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
                    "avtalets innehåll, omständigheterna vid avtalets tillkomst "
                    "och omständigheterna i övrigt. Syftet är att kunna jämka "
                    "oskäliga avtalsvillkor."
                ),
                source="forarbete",
            ),
            "https://lagen.nu/sou/1974:83": _document(
                uri="https://lagen.nu/sou/1974:83",
                title="SOU 1974:83 Generalklausul i förmögenhetsrätten",
                pinpoint=None,
                text=(
                    "Utredningen föreslår att 36 § avtalslagen skall ge "
                    "domstolen rätt att jämka oskäliga avtalsvillkor med "
                    "hänsyn till vägledande faktorer som partsställning."
                ),
                source="forarbete",
            ),
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question=(
                "Vad anger prop. 1975/76:81 och SOU 1974:83 om syftet med "
                "36 § avtalslagen och de vägledande faktorerna?"
            ),
        ),
        _context(),
    )
    assert {item.source_id for item in evidence} == {
        "https://lagen.nu/prop/1975/76:81",
        "https://lagen.nu/sou/1974:83",
    }
    assert [args["citation"] for name, args in client.calls if name == "resolve_citation"] == [
        "prop. 1975/76:81",
        "SOU 1974:83",
    ]
    assert not any(name == "search" for name, _args in client.calls)
    proposition_item = next(
        item for item in evidence if "prop/1975/76:81" in (item.source_id or "")
    )
    assert proposition_item.excerpt == proposition_item.legal_result.preparatory_work.citations[0].quote


async def test_search_hits_are_fetched_only_when_selector_keeps_them():
    mephedrone = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2011s357",
            title="Mefedrondomen (NJA 2011 s. 357)",
            source="dv",
            pinpoint=None,
        ),
        highlight=("Narkotikaklassificering av mefedron var avgörande.",),
    )
    relevant = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/1987s394",
            title="NJA 1987 s. 394",
            source="dv",
            pinpoint=None,
        ),
        highlight=("36 § ledde till jämkning av ansvarsbegränsningen.",),
    )

    class KeepRelevant(PassthroughLagenNuSelector):
        async def select_hits(self, *, need, source_type, candidates, context):
            return [
                HitDecision(
                    candidate_id=item.candidate_id,
                    keep="1987s394" in item.uri,
                    role="ratio" if "1987s394" in item.uri else "wrong_subject",
                    why="scripted",
                )
                for item in candidates
            ]

    client = FakeLagenNuClient(
        search=SearchResults(query="36 §", total=2, results=(mephedrone, relevant)),
        documents={
            "https://lagen.nu/dom/nja/1987s394": _document(
                uri="https://lagen.nu/dom/nja/1987s394",
                pinpoint=None,
                text="HD jämkade villkoret med stöd av 36 §.",
                source="dv",
            ),
        },
    )
    evidence = await _source(
        client,
        "swedish_case_law",
        selector=KeepRelevant(),
    ).research(
        _need(
            "swedish_case_law",
            question="Vilka omständigheter var avgörande där 36 § lett till jämkning?",
        ),
        _context(),
    )
    assert [item.source_id for item in evidence] == ["https://lagen.nu/dom/nja/1987s394"]
    assert not any(
        args["uri"] == "https://lagen.nu/dom/nja/2011s357"
        for name, args in client.calls
        if name == "get_document"
    )


async def test_case_law_uses_incoming_citations_for_named_statute():
    statute = _hit()
    decision = _hit(
        uri="https://lagen.nu/dom/nja/1987s394",
        title="NJA 1987 s. 394",
        source="dv",
        pinpoint=None,
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        incoming=IncomingCitations(
            uri="https://lagen.nu/1915:218#P36",
            total=1,
            results=(decision,),
        ),
        documents={
            "https://lagen.nu/dom/nja/1987s394": _document(
                uri="https://lagen.nu/dom/nja/1987s394",
                pinpoint=None,
                text="Högsta domstolen prövade 36 § avtalslagen.",
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need(
            "swedish_case_law",
            question="Vilka avgöranden tillämpar avtalslagen 36 §?",
        ),
        _context(),
    )
    assert evidence[0].status == "found"
    assert evidence[0].source_type == "swedish_case_law"
    assert evidence[0].source_id == "https://lagen.nu/dom/nja/1987s394"
    assert [name for name, _args in client.calls] == [
        "resolve_citation",
        "get_incoming_citations",
        "search",
        "get_document",
    ]
    assert client.calls[1][1]["source"] == "dv"
    assert client.calls[1][1]["sort"] == "citations"


async def test_case_law_fuses_search_and_graph_and_prefers_overlap():
    statute = _hit()
    graph_only = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/1987s394",
            title="NJA 1987 s. 394",
            source="dv",
            pinpoint=None,
        ),
        highlight=("allmän avtalsrätt",),
    )
    overlap = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2012s776",
            title="NJA 2012 s. 776",
            source="dv",
            pinpoint=None,
        ),
        highlight=("36 § avtalslagen om konsumentavtal och oskäligt villkor",),
    )
    search_only = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2017s113",
            title="NJA 2017 s. 113",
            source="dv",
            pinpoint=None,
        ),
        highlight=("36 § avtalslagen om konsumentavtal",),
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        incoming=IncomingCitations(
            uri="https://lagen.nu/1915:218#P36",
            total=2,
            results=(graph_only, overlap),
        ),
        search=SearchResults(
            query="konsumentavtal",
            total=2,
            results=(overlap, search_only),
        ),
        documents={
            hit.uri: _document(
                uri=hit.uri or "",
                pinpoint=None,
                text=f"Domskäl om 36 § avtalslagen. {hit.title or ''}",
                source="dv",
            )
            for hit in (graph_only, overlap, search_only)
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need(
            "swedish_case_law",
            question="Hur tillämpas avtalslagen 36 § i konsumentavtal?",
        ),
        _context(),
    )
    assert [item.source_id for item in evidence] == [
        "https://lagen.nu/dom/nja/2012s776",
        "https://lagen.nu/dom/nja/2017s113",
        "https://lagen.nu/dom/nja/1987s394",
    ]
    assert evidence[0].metadata["retrieval_origins"] == [
        "search",
        "citation_graph",
    ]
    search_args = next(args for name, args in client.calls if name == "search")
    assert search_args["query"] == "36 § avtalslagen konsumentavtal"
    fetches = [call for call in client.calls if call[0] == "get_document"]
    assert len(fetches) == 3


async def test_case_search_filters_false_provision_matches():
    statute = _hit()
    false_match = replace(
        _hit(
            uri="https://lagen.nu/dom/pmod/PMT2851-25/2026-04-23",
            title="PMT 2851-25",
            source="dv",
            pinpoint=None,
        ),
        highlight=(
            "36 kap. offentlighets- och sekretesslagen. I övrigt nämns "
            "avtalslagen utan koppling till paragrafen."
        ),
    )
    exact_match = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2012s776",
            title="NJA 2012 s. 776",
            source="dv",
            pinpoint=None,
        ),
        highlight=("Villkoret prövades enligt 36 § avtalslagen.",),
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        incoming=IncomingCitations(
            uri="https://lagen.nu/1915:218#P36",
            total=0,
        ),
        search=SearchResults(
            query="36 § avtalslagen",
            total=2,
            results=(false_match, exact_match),
        ),
        documents={
            "https://lagen.nu/dom/nja/2012s776": _document(
                uri="https://lagen.nu/dom/nja/2012s776",
                pinpoint=None,
                text="Domskäl om 36 § avtalslagen.",
                source="dv",
            )
        },
    )

    class KeepExactProvision(PassthroughLagenNuSelector):
        async def select_hits(self, *, need, source_type, candidates, context):
            return [
                HitDecision(
                    candidate_id=item.candidate_id,
                    keep="2012s776" in item.uri,
                    role="ratio" if "2012s776" in item.uri else "wrong_subject",
                    why="scripted",
                )
                for item in candidates
            ]

    evidence = await _source(
        client,
        "swedish_case_law",
        selector=KeepExactProvision(),
    ).research(
        _need(
            "swedish_case_law",
            question="Hur tillämpas avtalslagen 36 §?",
        ),
        _context(),
    )
    assert [item.source_id for item in evidence] == ["https://lagen.nu/dom/nja/2012s776"]


async def test_case_fetch_preserves_whole_document_for_role_analysis():
    submissions = LagenNuPin(
        uri="https://lagen.nu/dom/nja/2012s776#yrkanden",
        pinpoint="yrkanden",
        label="Parternas yrkanden",
        highlight=("Konsumenten yrkade jämkning av det oskäliga avtalsvillkoret.",),
    )
    reasons = LagenNuPin(
        uri="https://lagen.nu/dom/nja/2012s776",
        pinpoint="domskal",
        label="Högsta domstolens domskäl",
        highlight=("Högsta domstolen bedömer om villkoret ska jämkas.",),
    )
    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2012s776",
            title="NJA 2012 s. 776",
            source="dv",
            pinpoint=None,
        ),
        fragments=(submissions, reasons),
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="jämkning villkor", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/dom/nja/2012s776": _document(
                uri="https://lagen.nu/dom/nja/2012s776",
                pinpoint=None,
                text="Högsta domstolens avgörande skäl.",
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need(
            "swedish_case_law",
            question="Vilka villkor jämkas?",
        ),
        _context(),
    )
    assert evidence[0].source_id == "https://lagen.nu/dom/nja/2012s776"
    fetch = next(args for name, args in client.calls if name == "get_document")
    assert fetch["pinpoint"] is None


async def test_preparatory_work_fetches_most_relevant_fragment():
    relevant = LagenNuPin(
        uri="https://lagen.nu/prop/1975/76:81#sec-oskalighet",
        pinpoint="sec-oskalighet",
        label="Oskäliga avtalsvillkor",
        highlight=("Faktorer vid bedömning av oskäliga konsumentavtal enligt 36 §.",),
    )
    unrelated = LagenNuPin(
        uri="https://lagen.nu/prop/1975/76:81#sec-inledning",
        pinpoint="sec-inledning",
        label="Inledning",
        highlight=("Allmän bakgrund.",),
    )
    hit = replace(
        _hit(
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            source="forarbete",
            pinpoint=None,
        ),
        fragments=(unrelated, relevant),
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="oskäliga konsumentavtal", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/prop/1975/76:81#sec-oskalighet": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                pinpoint="sec-oskalighet",
                text=(
                    "Huvudsakligt innehåll Propositionen föreslår en generalklausul.\n\n"
                    "Relevanta faktorer för oskälighetsbedömningen enligt 36 §."
                ),
                source="forarbete",
            )
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question="Vilka faktorer gäller för oskäliga konsumentavtal enligt 36 §?",
        ),
        _context(),
    )
    assert evidence[0].source_id == "https://lagen.nu/prop/1975/76:81#sec-oskalighet"
    fetch = next(args for name, args in client.calls if name == "get_document")
    assert fetch["pinpoint"] == "sec-oskalighet"
    assert fetch["max_chars"] == 200000
    assert evidence[0].excerpt == evidence[0].legal_result.preparatory_work.citations[0].quote


async def test_hybrid_case_law_stays_within_quality_budget():
    statute = _hit()
    decisions = tuple(
        _hit(
            uri=f"https://lagen.nu/dom/nja/2000s{index}",
            title=f"NJA 2000 s. {index}",
            source="dv",
            pinpoint=None,
            highlight=f"jämkning {index}",
        )
        for index in range(1, 11)
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        incoming=IncomingCitations(
            uri="https://lagen.nu/1915:218#P36",
            total=len(decisions),
            results=decisions,
        ),
        search=SearchResults(
            query="jämkning",
            total=len(decisions),
            results=tuple(reversed(decisions)),
        ),
        documents={
            hit.uri: _document(
                uri=hit.uri or "",
                pinpoint=None,
                text=f"Domskäl om 36 § avtalslagen. {hit.title or ''}",
                source="dv",
            )
            for hit in decisions
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need(
            "swedish_case_law",
            question="Vilka avgöranden tillämpar avtalslagen 36 § vid jämkning?",
        ),
        ResearchContext(
            scope=KnowledgeScope(customer_id=1, module="dd"),
            limit=10,
        ),
    )
    assert len(evidence) == MAX_DOCUMENT_FETCHES
    assert len(client.calls) <= MAX_MCP_TOOL_CALLS
    assert [name for name, _args in client.calls[:3]] == [
        "resolve_citation",
        "get_incoming_citations",
        "search",
    ]


async def test_case_law_searches_dv_cases_without_named_citation():
    decision = _hit(
        uri="https://lagen.nu/dom/nja/2017s113",
        title="NJA 2017 s. 113",
        source="dv",
        pinpoint=None,
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="avtalsvillkor", total=1, results=(decision,)),
        documents={
            "https://lagen.nu/dom/nja/2017s113": _document(
                uri="https://lagen.nu/dom/nja/2017s113",
                pinpoint=None,
                text="Avgörande om oskäliga avtalsvillkor.",
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need("swedish_case_law", question="Praxis om oskäliga avtalsvillkor"),
        _context(),
    )
    assert evidence[0].status == "found"
    assert client.calls[0] == (
        "search",
        {
            "query": "oskäliga avtalsvillkor",
            "source": "dv",
            "kind": "case",
            "limit": MAX_SEARCH_HITS,
        },
    )


async def test_case_law_fetches_resolved_decision_directly():
    decision = _hit(
        uri="https://lagen.nu/dom/nja/2005s142",
        title="NJA 2005 s. 142",
        source="dv",
        pinpoint=None,
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(decision,)),
        documents={
            "https://lagen.nu/dom/nja/2005s142": _document(
                uri="https://lagen.nu/dom/nja/2005s142",
                pinpoint=None,
                text="Högsta domstolens avgörande.",
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need("swedish_case_law", question="NJA 2005 s. 142"),
        _context(),
    )
    assert evidence[0].status == "found"
    assert evidence[0].source_id == "https://lagen.nu/dom/nja/2005s142"
    assert [name for name, _args in client.calls] == [
        "resolve_citation",
        "get_document",
    ]


async def test_case_law_resolves_every_named_nja_citation():
    first = _hit(
        uri="https://lagen.nu/dom/nja/1983s385",
        title="NJA 1983 s. 385",
        source="dv",
        pinpoint=None,
    )
    second = _hit(
        uri="https://lagen.nu/dom/nja/1989s346",
        title="NJA 1989 s. 346",
        source="dv",
        pinpoint=None,
    )
    client = FakeLagenNuClient(
        resolved_by_citation={
            "NJA 1983 s. 385": ResolvedCitations(results=(first,)),
            "NJA 1989 s. 346": ResolvedCitations(results=(second,)),
        },
        documents={
            "https://lagen.nu/dom/nja/1983s385": _document(
                uri="https://lagen.nu/dom/nja/1983s385",
                title="NJA 1983 s. 385",
                pinpoint=None,
                text="HD prövade arrendeavgiften mot 36 §.",
                source="dv",
            ),
            "https://lagen.nu/dom/nja/1989s346": _document(
                uri="https://lagen.nu/dom/nja/1989s346",
                title="NJA 1989 s. 346",
                pinpoint=None,
                text="HD prövade jämkning av avtalsvillkor enligt 36 §.",
                source="dv",
            ),
        },
    )
    evidence = await _source(client, "swedish_case_law").research(
        _need(
            "swedish_case_law",
            question=(
                "Vilka centrala HD-avgöranden om 36 § avtalslagen "
                "(t.ex. NJA 1983 s. 385, NJA 1989 s. 346) är vägledande?"
            ),
        ),
        _context(),
    )
    assert {item.source_id for item in evidence} == {
        "https://lagen.nu/dom/nja/1983s385",
        "https://lagen.nu/dom/nja/1989s346",
    }
    assert [name for name, _args in client.calls] == [
        "resolve_citation",
        "resolve_citation",
        "get_document",
        "get_document",
    ]
    assert [args["citation"] for name, args in client.calls if name == "resolve_citation"] == [
        "NJA 1983 s. 385",
        "NJA 1989 s. 346",
    ]


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
    assert [name for name, _args in client.calls] == ["resolve_citation", "search"]


async def test_standard_registry_excludes_tenant_providers():
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
    assert knowledge == []
    assert len(lagen) == 3
    assert all(entry.source.provider_id == LAGEN_NU_PROVIDER_ID for entry in lagen)
    evidence = await ResearchRouter(registry).execute_need(
        _need("case_knowledge"),
        _context(customer_id=4, case_id="case-1"),
    )
    assert [item.status for item in evidence] == ["error"]
    assert provider.queries == []


def test_adapter_is_programmatic():
    source = inspect.getsource(LagenNuResearchSource)
    for marker in ("complete_text", "complete_structured", "openai", "chat.completions"):
        assert marker not in source
    assert "resolve_citation" in source
    assert "get_document" in source
    assert "select_hits" in source


async def test_search_requires_a_selector():
    set_passage_selector_factory(None)
    client = FakeLagenNuClient(
        search=SearchResults(query="jämkning", total=1, results=(_hit(),)),
        documents={"https://lagen.nu/1915:218#P36": _document()},
    )
    source = LagenNuResearchSource(source_type="swedish_law", client=client)
    evidence = await source.research(_need("swedish_law", question="jämkning"), _context())
    assert evidence[0].metadata["failure_category"] == "selection_failed"


async def test_owned_client_is_closed_on_no_hit_and_error():
    no_hit = FakeLagenNuClient(search=SearchResults(query="q", total=0, results=()))
    source = LagenNuResearchSource(source_type="swedish_law")
    source._owned_client = no_hit
    evidence = await source.research(
        _need("swedish_law", question="okänt påhittat lagrum"),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert no_hit.closed is True
    assert source._owned_client is None
    assert source._client is None

    boom = FakeLagenNuClient(search_error=OfficialLagenNuMcpError("lagen.nu MCP timed out"))
    failing = LagenNuResearchSource(source_type="swedish_law")
    failing._owned_client = boom
    evidence = await failing.research(_need("swedish_law", question="jämkning"), _context())
    assert evidence[0].metadata["failure_category"] == "fetch_failed"
    assert boom.closed is True
    assert failing._owned_client is None
    assert failing._client is None


async def test_injected_client_is_not_owned_or_closed():
    client = FakeLagenNuClient(search=SearchResults(query="q", total=0, results=()))
    source = LagenNuResearchSource(source_type="swedish_law", client=client)
    evidence = await source.research(
        _need("swedish_law", question="okänt påhittat lagrum"),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert client.closed is False
    assert source._owned_client is None
    assert source._client is client


async def test_duplicate_fetch_targets_do_not_consume_later_distinct_hit():
    duplicate = _hit()
    later = _hit(
        uri="https://lagen.nu/1981:130",
        title="Preskriptionslag",
        pinpoint="P2",
        highlight="Preskription innebär",
    )
    client = FakeLagenNuClient(
        search=SearchResults(
            query="q",
            total=5,
            results=(duplicate, duplicate, duplicate, duplicate, later),
        ),
        documents={
            "https://lagen.nu/1915:218#P36": _document(),
            "https://lagen.nu/1981:130#P2": _document(
                uri="https://lagen.nu/1981:130",
                pinpoint="P2",
                text="Preskription innebär att fordran faller.",
            ),
        },
    )
    evidence = await _source(client).research(
        _need("swedish_law", question="preskription av fordran"),
        _context(),
    )
    fetch_targets = [
        (args["uri"], args["pinpoint"]) for name, args in client.calls if name == "get_document"
    ]
    assert fetch_targets == [
        ("https://lagen.nu/1981:130", "P2"),
        ("https://lagen.nu/1915:218", "P36"),
    ]
    assert [item.source_id for item in evidence] == [
        "https://lagen.nu/1981:130#P2",
        "https://lagen.nu/1915:218#P36",
    ]
    assert client.closed is False


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


async def test_display_selector_cannot_discard_domain_results():
    class InventOneExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            if "1915:218" in document.uri:
                return ExcerptDecision(
                    excerpt="Lagstiftaren avsåg att skydda den svagare parten.",
                    why="invented",
                )
            return await super().select_excerpt(
                need=need,
                source_type=source_type,
                document=document,
                context=context,
            )

    other = _hit(
        uri="https://lagen.nu/1981:130",
        title="Köplagen",
        pinpoint="P1",
        highlight="Köplagen kompletterar avtalslagen.",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="jämkning", total=2, results=(_hit(), other)),
        documents={
            "https://lagen.nu/1915:218#P36": _document(),
            "https://lagen.nu/1981:130#P1": _document(
                uri="https://lagen.nu/1981:130",
                title="Köplagen",
                pinpoint="P1",
                text="Köplagen kompletterar avtalslagen när 36 § inte räcker.",
            ),
        },
    )
    evidence = await _source(client, "swedish_law", selector=InventOneExcerpt()).research(
        _need("swedish_law", question="jämkning"), _context()
    )
    assert [item.status for item in evidence] == ["found", "found"]
    assert all(item.legal_result is not None for item in evidence)


async def test_cover_pinpoint_fetches_full_travaux():
    hit = replace(
        _hit(
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            source="forarbete",
            pinpoint=None,
            highlight="Propositionens huvudsakliga innehåll",
        ),
        identifier="Prop. 1975/76:81",
        pin=LagenNuPin(
            uri="https://lagen.nu/prop/1975/76:81#Propositionens huvudsakliga innehåll",
            pinpoint="Propositionens huvudsakliga innehåll",
            label="Propositionens huvudsakliga innehåll",
            highlight=("Propositionens huvudsakliga innehåll",),
        ),
    )
    body = (
        "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
        "avtalets innehåll och omständigheterna vid avtalets tillkomst."
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(hit,)),
        documents={
            "https://lagen.nu/prop/1975/76:81": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                title="Prop. 1975/76:81",
                pinpoint=None,
                text=(
                    "Propositionens huvudsakliga innehåll Propositionen föreslår "
                    "en generalklausul.\n\n" + body
                ),
                source="forarbete",
            )
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question="Vad anger prop. 1975/76:81 om 36 § avtalslagen?",
        ),
        _context(),
    )
    fetch = next(args for name, args in client.calls if name == "get_document")
    assert fetch["pinpoint"] is None
    assert evidence[0].status == "found"
    assert evidence[0].locator != "Propositionens huvudsakliga innehåll"


async def test_named_case_without_the_provision_is_skipped():
    named = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/1992s66",
            title="NJA 1992 s. 66",
            source="dv",
            pinpoint=None,
            highlight="Optionsavtal beträffande bostadsrätt.",
        ),
        identifier="NJA 1992 s. 66",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(named,)),
        documents={
            "https://lagen.nu/dom/nja/1992s66": _document(
                uri="https://lagen.nu/dom/nja/1992s66",
                pinpoint=None,
                text="Optionsavtal beträffande överlåtelse av bostadsrätt är bindande.",
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", interpreter=FakeLegalInterpreter(relation="irrelevant")).research(
        _need(
            "swedish_case_law",
            question="Vilka villkor jämkades i NJA 1992 s. 66 enligt 36 §?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata["fetch_success"] is True
    assert evidence[0].metadata.get("reason") == "domain_relation_irrelevant"


async def test_excerpt_without_the_provision_is_skipped():
    class OptionsExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            return ExcerptDecision(
                excerpt="Optionsavtal beträffande överlåtelse av bostadsrätt är bindande.",
                why="fel fråga",
            )

    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/1992s66",
            title="NJA 1992 s. 66",
            source="dv",
            pinpoint=None,
            highlight="Optionsavtal",
        ),
        identifier="NJA 1992 s. 66",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="36 §", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/dom/nja/1992s66": _document(
                uri="https://lagen.nu/dom/nja/1992s66",
                pinpoint=None,
                text="Optionsavtal beträffande överlåtelse av bostadsrätt är bindande.",
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", selector=OptionsExcerpt(), interpreter=FakeLegalInterpreter(relation="irrelevant")).research(
        _need(
            "swedish_case_law",
            question="Vilka villkor har jämkats enligt 36 § avtalslagen?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata.get("reason") == "domain_relation_irrelevant"


async def test_party_submission_excerpt_is_skipped():
    class PartyExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            return ExcerptDecision(
                excerpt=(
                    "First Reserve har invänt: Konkurrensklausulen har utgjort "
                    "avtalsinnehåll. Bestämmelsen i 36 § avtalslagen är inte "
                    "tillämplig i förevarande fall."
                ),
                why="parts talan",
            )

    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/ad/1998:80",
            title="AD 1998 nr 80",
            source="dv",
            pinpoint=None,
            highlight="36 § avtalslagen är inte tillämplig",
        ),
        identifier="AD 1998 nr 80",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="36 §", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/dom/ad/1998:80": _document(
                uri="https://lagen.nu/dom/ad/1998:80",
                pinpoint=None,
                text=(
                    "First Reserve har invänt: Konkurrensklausulen har utgjort "
                    "avtalsinnehåll. Bestämmelsen i 36 § avtalslagen är inte "
                    "tillämplig i förevarande fall."
                ),
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", selector=PartyExcerpt(), interpreter=FakeLegalInterpreter(relation="irrelevant")).research(
        _need(
            "swedish_case_law",
            question="Finns det skillnader i hur 36 § tillämpas?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata.get("reason") == "domain_relation_irrelevant"


async def test_named_citations_survive_search_selection_failure():
    class BoomHits(PassthroughLagenNuSelector):
        async def select_hits(self, *, need, source_type, candidates, context):
            raise LagenNuSelectionError("selector model call failed: length")

    named = replace(
        _hit(
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            source="forarbete",
            pinpoint=None,
            highlight="36 § avtalslagen",
        ),
        identifier="Prop. 1975/76:81",
    )
    noise = replace(
        _hit(
            uri="https://lagen.nu/sou/1979:36",
            title="SOU 1979:36",
            source="forarbete",
            pinpoint=None,
            highlight="konsumenttjänst",
        ),
        identifier="SOU 1979:36",
    )
    source = _source(
        FakeLagenNuClient(),
        "swedish_preparatory_works",
        selector=BoomHits(),
    )
    kept = await source._select_candidates(
        _need(
            "swedish_preparatory_works",
            question="Vad anger prop. 1975/76:81 om 36 § avtalslagen?",
        ),
        _context(),
        _candidates((named,), source="forarbete", origin="resolve")
        + _candidates((noise,), source="forarbete", origin="search"),
    )
    assert [item.hit.uri for item in kept] == ["https://lagen.nu/prop/1975/76:81"]


def test_preparatory_citations_normalize_proposition_wording():
    assert _preparatory_citations(
        "Vad anger proposition 1975/76:81, prop 1994/95:17, prop. 1971:15 och "
        "lagutskottets betänkande 1975/76:LU21 jämfört med SOU 1974:83?"
    ) == [
        "prop. 1975/76:81",
        "prop. 1994/95:17",
        "prop. 1971:15",
        "bet. 1975/76:LU21",
        "SOU 1974:83",
    ]


async def test_proposition_wording_resolves_named_travaux():
    proposition = _hit(
        uri="https://lagen.nu/prop/1975/76:81",
        title="Prop. 1975/76:81",
        source="forarbete",
        pinpoint=None,
        highlight="Prop. 1975/76:81",
    )
    client = FakeLagenNuClient(
        resolved_by_citation={
            "prop. 1975/76:81": ResolvedCitations(results=(proposition,)),
        },
        documents={
            "https://lagen.nu/prop/1975/76:81": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                title="Prop. 1975/76:81",
                pinpoint=None,
                text=(
                    "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
                    "avtalets innehåll och omständigheterna vid avtalets tillkomst."
                ),
                source="forarbete",
            ),
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question="Vad anger proposition 1975/76:81 om syftet med 36 §?",
        ),
        _context(),
    )
    assert [item.source_id for item in evidence] == ["https://lagen.nu/prop/1975/76:81"]
    assert client.calls[0] == (
        "resolve_citation",
        {"citation": "prop. 1975/76:81"},
    )


async def test_citation_graph_is_subject_to_selection():
    class DropSearch(PassthroughLagenNuSelector):
        async def select_hits(self, *, need, source_type, candidates, context):
            return [
                HitDecision(
                    candidate_id=item.candidate_id,
                    keep=False,
                    role="wrong_subject",
                    why="drop search",
                )
                for item in candidates
            ]

    graph = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2005s142",
            title="NJA 2005 s. 142",
            source="dv",
            pinpoint=None,
            highlight="jämkning av ansvarsbegränsning",
        ),
        identifier="NJA 2005 s. 142",
    )
    search_only = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2017s113",
            title="NJA 2017 s. 113",
            source="dv",
            pinpoint=None,
            highlight="oskäliga avtalsvillkor",
        ),
        identifier="NJA 2017 s. 113",
    )
    source = _source(
        FakeLagenNuClient(),
        "swedish_case_law",
        selector=DropSearch(),
    )
    kept = await source._select_candidates(
        _need(
            "swedish_case_law",
            question="Vilka villkor har jämkats enligt 36 § avtalslagen?",
        ),
        _context(),
        _candidates((graph,), source="dv", origin="citation_graph")
        + _candidates((search_only,), source="dv", origin="search"),
    )
    assert kept == []


async def test_judicial_reasons_with_jamkning_are_kept_without_repeating_section():
    class JamkExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            return ExcerptDecision(
                excerpt=(
                    "Högsta domstolen finner att ansvarsbegränsningen ska jämkas "
                    "med hänsyn till partsställningen och villkorets tyngd."
                ),
                why="domskäl",
            )

    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2005s142",
            title="NJA 2005 s. 142",
            source="dv",
            pinpoint=None,
            highlight="ansvarsbegränsning jämkades",
        ),
        identifier="NJA 2005 s. 142",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(hit,)),
        documents={
            "https://lagen.nu/dom/nja/2005s142": _document(
                uri="https://lagen.nu/dom/nja/2005s142",
                pinpoint=None,
                text=(
                    "Högsta domstolen finner att ansvarsbegränsningen ska jämkas "
                    "med hänsyn till partsställningen och villkorets tyngd."
                ),
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", selector=JamkExcerpt()).research(
        _need(
            "swedish_case_law",
            question="Vilka villkor jämkades i NJA 2005 s. 142 enligt 36 §?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["found"]
    assert "ansvarsbegränsningen" in (evidence[0].excerpt or "")


async def test_statute_restatement_excerpt_is_skipped():
    class RestateExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            return ExcerptDecision(
                excerpt=(
                    "Enligt 36 § avtalslagen får avtalsvillkor jämkas eller "
                    "lämnas utan avseende om villkoret är oskäligt."
                ),
                why="lagtext",
            )

    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2015s98",
            title="NJA 2015 s. 98",
            source="dv",
            pinpoint=None,
            highlight="36 § avtalslagen",
        ),
        identifier="NJA 2015 s. 98",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(hit,)),
        documents={
            "https://lagen.nu/dom/nja/2015s98": _document(
                uri="https://lagen.nu/dom/nja/2015s98",
                pinpoint=None,
                text=(
                    "Enligt 36 § avtalslagen får avtalsvillkor jämkas eller "
                    "lämnas utan avseende om villkoret är oskäligt."
                ),
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", selector=RestateExcerpt(), interpreter=FakeLegalInterpreter(relation="irrelevant")).research(
        _need(
            "swedish_case_law",
            question="Vilka faktorer vägde HD i NJA 2015 s. 98 enligt 36 §?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata.get("reason") == "domain_relation_irrelevant"


async def test_named_case_keeps_window_when_selector_excerpt_is_empty():
    class EmptyExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            return ExcerptDecision(excerpt="", why="tom")

    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2005s142",
            title="NJA 2005 s. 142",
            source="dv",
            pinpoint=None,
            highlight="ansvarsbegränsning jämkades",
        ),
        identifier="NJA 2005 s. 142",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(hit,)),
        documents={
            "https://lagen.nu/dom/nja/2005s142": _document(
                uri="https://lagen.nu/dom/nja/2005s142",
                pinpoint=None,
                text=(
                    "Högsta domstolen\n\nDomskäl\n\n"
                    "Högsta domstolen finner att ansvarsbegränsningen ska jämkas "
                    "med hänsyn till partsställningen och villkorets tyngd.\n\n"
                    "Domslut\n\nVillkoret jämkas."
                ),
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", selector=EmptyExcerpt()).research(
        _need(
            "swedish_case_law",
            question="Vilka villkor jämkades i NJA 2005 s. 142 enligt 36 §?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["found"]
    assert "ansvarsbegränsningen" in (evidence[0].excerpt or "")
    assert evidence[0].metadata.get("selection_why") == "verified_domain_citation"


async def test_search_empty_excerpt_is_still_skipped():
    class EmptyExcerpt(PassthroughLagenNuSelector):
        async def select_excerpt(self, *, need, source_type, document, context):
            return ExcerptDecision(excerpt="", why="tom")

    hit = replace(
        _hit(
            uri="https://lagen.nu/dom/nja/2005s142",
            title="NJA 2005 s. 142",
            source="dv",
            pinpoint=None,
            highlight="ansvarsbegränsning jämkades",
        ),
        identifier="NJA 2005 s. 142",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="36 §", total=1, results=(hit,)),
        documents={
            "https://lagen.nu/dom/nja/2005s142": _document(
                uri="https://lagen.nu/dom/nja/2005s142",
                pinpoint=None,
                text=(
                    "Högsta domstolen finner att ansvarsbegränsningen ska jämkas "
                    "med hänsyn till partsställningen."
                ),
                source="dv",
            )
        },
    )
    evidence = await _source(client, "swedish_case_law", selector=EmptyExcerpt(), interpreter=FakeLegalInterpreter(relation="irrelevant")).research(
        _need(
            "swedish_case_law",
            question="Vilka villkor har jämkats enligt 36 § avtalslagen?",
        ),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]


async def test_incoming_travaux_reach_interpreter_without_literal_section():
    statute = _hit()
    older = replace(
        _hit(
            uri="https://lagen.nu/prop/1971:15",
            title="Prop. 1971:15",
            source="forarbete",
            pinpoint=None,
            highlight="jämkning av köp",
        ),
        identifier="Prop. 1971:15",
    )
    travaux = replace(
        _hit(
            uri="https://lagen.nu/prop/1975/76:81",
            title="Prop. 1975/76:81",
            source="forarbete",
            pinpoint=None,
            highlight="36 § avtalslagen",
        ),
        identifier="Prop. 1975/76:81",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(statute,)),
        incoming=IncomingCitations(
            uri="https://lagen.nu/1915:218#P36",
            total=2,
            results=(older, travaux),
        ),
        documents={
            "https://lagen.nu/prop/1971:15": _document(
                uri="https://lagen.nu/prop/1971:15",
                pinpoint=None,
                text=(
                    "Vid bedömningen om jämkning skall ske skall hänsyn tagas "
                    "dels till den förlust säljaren kan ha lidit."
                ),
                source="forarbete",
            ),
            "https://lagen.nu/prop/1975/76:81": _document(
                uri="https://lagen.nu/prop/1975/76:81",
                pinpoint=None,
                text=(
                    "Vid tillämpning av 36 § avtalslagen skall hänsyn tas till "
                    "avtalets innehåll och omständigheterna vid avtalets tillkomst."
                ),
                source="forarbete",
            ),
        },
    )
    evidence = await _source(client, "swedish_preparatory_works").research(
        _need(
            "swedish_preparatory_works",
            question="Hur anger förarbetena till 36 § avtalslagen att jämkning ska göras?",
        ),
        _context(),
    )
    assert {item.source_id for item in evidence} == {"https://lagen.nu/prop/1971:15", "https://lagen.nu/prop/1975/76:81"}


async def test_36_avtl_live_selection_rejects_wrong_proposition_despite_keep_flag():
    from app.llm.lagen_nu_selector import LlmLagenNuSelector
    from app.services.prompt_catalog import default_prompts

    async def complete_selection(messages, response_model):
        if response_model.__name__ == "HitSelectionModel":
            return response_model(
                decisions=[
                    {
                        "candidate_id": wrong_uri,
                        "keep": True,
                        "role": "wrong_subject",
                        "why": "36 § refers to another law",
                    },
                    {
                        "candidate_id": right_uri,
                        "keep": True,
                        "role": "travaux",
                        "why": "36 § avtalslagen",
                    },
                ]
            )
        return response_model(
            excerpt="36 § avtalslagen är en generalklausul om oskäliga avtalsvillkor."
        )

    prompts = default_prompts("sv")
    selector = LlmLagenNuSelector(
        completer=complete_selection,
        system_prompt=prompts["research.lagen_nu.select.system"],
        triage_prompt=prompts["research.lagen_nu.select.triage"],
        user_prompt=prompts["research.lagen_nu.select.user"],
        excerpt_system_prompt=prompts["research.lagen_nu.excerpt.system"],
        excerpt_user_prompt=prompts["research.lagen_nu.excerpt.user"],
    )

    wrong_uri = "https://lagen.nu/prop/1971:20"
    right_uri = "https://lagen.nu/prop/1975/76:81"
    wrong = replace(
        _hit(
            uri=wrong_uri,
            title="Prop. 1971:20 — exekutiv försäljning av fast egendom",
            source="forarbete",
            pinpoint=None,
            highlight="tillträdesdag som anges i 36 §",
        ),
        identifier="Prop. 1971:20",
    )
    right = replace(
        _hit(
            uri=right_uri,
            title="Prop. 1975/76:81 — 36 § avtalslagen",
            source="forarbete",
            pinpoint=None,
            highlight="36 § avtalslagen",
        ),
        identifier="Prop. 1975/76:81",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="36 § avtalslagen", total=2, results=(wrong, right)),
        documents={
            wrong_uri: _document(
                uri=wrong_uri,
                title=wrong.title,
                pinpoint=None,
                text="Exekutiv försäljning av fast egendom. Tillträdesdag som anges i 36 §.",
                source="forarbete",
            ),
            right_uri: _document(
                uri=right_uri,
                title=right.title,
                pinpoint=None,
                text="36 § avtalslagen är en generalklausul om oskäliga avtalsvillkor.",
                source="forarbete",
            ),
        },
    )
    evidence = await _source(client, "swedish_preparatory_works", selector=selector).research(
        _need("swedish_preparatory_works", question="Vad innebär 36 § avtalslagen?"), _context()
    )
    assert [item.source_id for item in evidence if item.status == "found"] == [right_uri]
    assert wrong_uri not in [args["uri"] for name, args in client.calls if name == "get_document"]


async def test_36_avtl_domain_irrelevance_cannot_be_found():
    from app.services.legal_research_result import LegalQuestionRelation

    class IrrelevantInterpreter(FakeLegalInterpreter):
        async def interpret(self, **kwargs):
            result = await super().interpret(**kwargs)
            return result.model_copy(
                update={
                    "relation": LegalQuestionRelation(
                        relation="irrelevant",
                        explanation="36 § concerns another statute",
                        confidence="high",
                    )
                }
            )

    uri = "https://lagen.nu/prop/1971:20"
    hit = replace(
        _hit(
            uri=uri,
            title="Exekutiv försäljning av fast egendom",
            source="forarbete",
            pinpoint=None,
            highlight="tillträdesdag som anges i 36 §",
        ),
        identifier="Prop. 1971:20",
    )
    client = FakeLagenNuClient(
        search=SearchResults(query="36 § avtalslagen", total=1, results=(hit,)),
        documents={
            uri: _document(
                uri=uri,
                title=hit.title,
                pinpoint=None,
                text="Tillträdesdag som anges i 36 § vid exekutiv försäljning av fast egendom.",
                source="forarbete",
            )
        },
    )
    evidence = await _source(
        client, "swedish_preparatory_works", interpreter=IrrelevantInterpreter()
    ).research(
        _need("swedish_preparatory_works", question="Vad innebär 36 § avtalslagen?"), _context()
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata["reason"] == "domain_relation_irrelevant"
