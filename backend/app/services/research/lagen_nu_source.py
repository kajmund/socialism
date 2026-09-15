"""Official lagen.nu adapter behind ResearchSource. MCP stays an access mechanism."""

from __future__ import annotations

import re
from typing import Literal

from app.services.lagen_nu.mcp_client import (
    LagenNuMcpClient,
    OfficialLagenNuMcpClient,
    OfficialLagenNuMcpError,
    OfficialLagenNuMcpNotFoundError,
)
from app.services.lagen_nu.models import LagenNuDocument, LagenNuSearchHit
from app.services.lagen_nu.registration import (
    LAGEN_NU_AUTHORITY_WARNING,
    LAGEN_NU_EVIDENCE_NATURES,
    LAGEN_NU_JURISDICTION,
    LAGEN_NU_PROVIDER_ID,
    mcp_source_for_nature,
)
from app.services.lagen_nu.uris import compose_canonical_uri
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchSourceType,
    research_evidence,
)

MAX_SEARCH_HITS = 5
MAX_DOCUMENT_FETCHES = 3
MAX_DOCUMENT_CHARS = 4000
MAX_MCP_TOOL_CALLS = 4

_HTML_TAG = re.compile(r"<[^>]+>")
_CITATION_HINT = re.compile(
    r"("
    r"§|"
    r"\bkap\.|"
    r"\bSFS\b|"
    r"\b\d{4}:\d+\b|"
    r"\bprop\.\s*\d{4}/\d{2}:\d+|"
    r"\bSOU\s+\d{4}:\d+|"
    r"\bNJA\s+\d{4}|"
    r"\bart(?:ikel|\.)?\s*\d+"
    r")",
    re.IGNORECASE,
)


def looks_like_citation(question: str) -> bool:
    return _CITATION_HINT.search(question) is not None


def select_lagen_nu_flow(need: ResearchNeed) -> Literal["resolve", "search"]:
    caps = {item.strip().lower() for item in need.capabilities if item.strip()}
    if "resolve_citation" in caps or "resolve" in caps:
        return "resolve"
    if "search" in caps:
        return "search"
    if looks_like_citation(need.question):
        return "resolve"
    return "search"


def _plain_text(value: str) -> str:
    return _HTML_TAG.sub("", value).replace("&#x2F;", "/").strip()


def _excerpt_from_hit(hit: LagenNuSearchHit) -> str | None:
    parts: list[str] = []
    if hit.pin is not None:
        parts.extend(hit.pin.highlight)
    for fragment in hit.fragments:
        parts.extend(fragment.highlight)
    parts.extend(hit.highlight)
    for part in parts:
        text = _plain_text(part)
        if text:
            return text
    return None


class LagenNuResearchSource:
    def __init__(
        self,
        *,
        source_type: ResearchSourceType,
        client: LagenNuMcpClient | None = None,
    ) -> None:
        if source_type not in LAGEN_NU_EVIDENCE_NATURES:
            raise ValueError(
                f"{source_type} is not implemented by the official lagen.nu adapter"
            )
        self.source_type = source_type
        self.provider_id = LAGEN_NU_PROVIDER_ID
        self._client = client
        self._owned_client: OfficialLagenNuMcpClient | None = None

    def _mcp(self) -> LagenNuMcpClient:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = OfficialLagenNuMcpClient()
        return self._owned_client

    async def research(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        try:
            return await self._research(need, context)
        finally:
            await self._aclose_owned_client()

    async def _aclose_owned_client(self) -> None:
        client = self._owned_client
        if client is None:
            return
        self._owned_client = None
        await client.aclose()

    async def _research(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        # Public corpus: never send ResearchContext.scope to lagen.nu.
        budget = _CallBudget(MAX_MCP_TOOL_CALLS)
        mcp_source = mcp_source_for_nature(self.source_type)
        hits = await self._hits_for_need(need, context, budget, mcp_source)
        if not hits:
            return [self._not_found(need, budget, reason="no_hit")]
        found = await self._fetch_hits(need, hits, budget, mcp_source)
        if found:
            return found
        return [self._not_found(need, budget, reason="no_fetchable_document")]

    async def _hits_for_need(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        budget: _CallBudget,
        mcp_source: str,
    ) -> list[LagenNuSearchHit]:
        flow = select_lagen_nu_flow(need)
        if flow == "resolve":
            resolved = await budget.call(
                "resolve_citation",
                self._mcp().resolve_citation(need.question),
                {"citation": need.question},
            )
            usable = _hits_for_source(resolved.results, mcp_source)
            if usable:
                return usable
            if resolved.recognized:
                return []
            if resolved.results:
                return []
        limit = min(context.limit, MAX_SEARCH_HITS)
        searched = await budget.call(
            "search",
            self._mcp().search(need.question, source=mcp_source, limit=limit),
            {"query": need.question, "source": mcp_source, "limit": limit},
        )
        return list(_hits_for_source(searched.results, mcp_source))

    async def _fetch_hits(
        self,
        need: ResearchNeed,
        hits: list[LagenNuSearchHit],
        budget: _CallBudget,
        mcp_source: str,
    ) -> list[ResearchEvidence]:
        found: list[ResearchEvidence] = []
        seen: set[str] = set()
        for hit in hits:
            if len(found) >= MAX_DOCUMENT_FETCHES:
                break
            if budget.remaining <= 0:
                break
            uri, pinpoint = _fetch_target(hit)
            if uri is None:
                continue
            target_key = uri if pinpoint is None else f"{uri}#{pinpoint}"
            if target_key in seen:
                continue
            seen.add(target_key)
            try:
                document = await budget.call(
                    "get_document",
                    self._mcp().get_document(
                        uri, pinpoint=pinpoint, max_chars=MAX_DOCUMENT_CHARS
                    ),
                    {
                        "uri": uri,
                        "pinpoint": pinpoint,
                        "max_chars": MAX_DOCUMENT_CHARS,
                    },
                )
            except OfficialLagenNuMcpNotFoundError:
                continue
            if document.source and document.source != mcp_source:
                continue
            found.append(self._from_document(need, hit, document, budget))
        return found

    def _from_document(
        self,
        need: ResearchNeed,
        hit: LagenNuSearchHit,
        document: LagenNuDocument,
        budget: _CallBudget,
    ) -> ResearchEvidence:
        pinpoint = document.pinpoint or (hit.pin.pinpoint if hit.pin else None)
        source_uri = compose_canonical_uri(document.uri, pinpoint)
        excerpt = document.text.strip() or _excerpt_from_hit(hit)
        return research_evidence(
            research_need_id=need.id,
            source_type=self.source_type,
            status="found",
            title=document.title or hit.title,
            excerpt=excerpt,
            locator=pinpoint or (hit.pin.label if hit.pin else None),
            source_id=source_uri,
            source_url=source_uri,
            provider=self.provider_id,
            score=hit.score,
            metadata=self._provenance(
                budget,
                canonical_uri=source_uri,
                source=document.source or hit.source,
                kind=document.kind or hit.kind,
                identifier=hit.identifier,
                publisher_source_url=document.publisher_source_url,
                pinpoint=pinpoint,
                truncated=document.truncated,
                inbound_count=document.inbound_count,
            ),
        )

    def _not_found(
        self,
        need: ResearchNeed,
        budget: _CallBudget,
        *,
        reason: str,
    ) -> ResearchEvidence:
        return research_evidence(
            research_need_id=need.id,
            source_type=self.source_type,
            status="not_found",
            provider=self.provider_id,
            metadata=self._provenance(budget, reason=reason),
        )

    def _provenance(
        self,
        budget: _CallBudget,
        **extra: object,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "jurisdiction": LAGEN_NU_JURISDICTION,
            "access_mechanism": "mcp",
            "retrieval_provider": LAGEN_NU_PROVIDER_ID,
            "automated_corpus": True,
            "not_official_publication": True,
            "authority_warning": LAGEN_NU_AUTHORITY_WARNING,
            "mcp_calls": budget.as_metadata(),
        }
        for key, value in extra.items():
            if value is not None:
                metadata[key] = value
        return metadata


class _CallBudget:
    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.remaining = max_calls
        self.calls: list[dict[str, object]] = []

    async def call(self, tool: str, awaitable, arguments: dict[str, object]):
        if self.remaining <= 0:
            raise OfficialLagenNuMcpError("lagen.nu MCP call bound reached")
        self.remaining -= 1
        self.calls.append({"tool": tool, "arguments": dict(arguments)})
        return await awaitable

    def as_metadata(self) -> list[dict[str, object]]:
        return [dict(item) for item in self.calls]


def _hits_for_source(
    hits: tuple[LagenNuSearchHit, ...] | list[LagenNuSearchHit],
    mcp_source: str,
) -> list[LagenNuSearchHit]:
    return [hit for hit in hits if hit.source == mcp_source and hit.uri]


def _fetch_target(hit: LagenNuSearchHit) -> tuple[str | None, str | None]:
    if hit.pin is not None and hit.pin.uri:
        return hit.pin.uri.split("#", 1)[0], hit.pin.pinpoint
    if hit.uri is None:
        return None, None
    if "#" in hit.uri:
        document_uri, pinpoint = hit.uri.split("#", 1)
        return document_uri, pinpoint or None
    return hit.uri, None
