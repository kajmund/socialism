"""Provider-owned lagen.nu retrieval behind the generic ResearchSource seam."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Literal

from app.llm.legal_research import LegalInterpreter, LlmLegalInterpreter
from app.services.lagen_nu.display import (
    WINDOW_CHARS,
    display_source_title,
    is_legal_front_matter,
    relevant_legal_excerpt,
    selector_passage_text,
)
from app.services.lagen_nu.selection import (
    MAX_SELECTOR_DOCUMENT_CHARS,
    HitDecision,
    LagenNuPassageSelector,
    LagenNuSelectionError,
    SelectableDocument,
    SelectableHit,
    clip_selector_document,
    resolve_passage_selector,
    verify_excerpt_span,
)
from app.services.lagen_nu.mcp_client import (
    LagenNuMcpClient,
    OfficialLagenNuMcpClient,
    OfficialLagenNuMcpError,
    OfficialLagenNuMcpNotFoundError,
)
from app.services.lagen_nu.models import LagenNuDocument, LagenNuSearchHit
from app.services.legal_research_result import LegalSourceIdentity
from app.services.lagen_nu.registration import (
    LAGEN_NU_EVIDENCE_NATURES,
    LAGEN_NU_JURISDICTION,
    LAGEN_NU_PROVIDER_ID,
    LAGEN_NU_PUBLICATION_NOTE,
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

logger = logging.getLogger(__name__)

MAX_SEARCH_HITS = 10
MAX_DOCUMENT_FETCHES = 5
MAX_DOCUMENT_CHARS = 100000
MAX_EVIDENCE_CHARS = 16000
MAX_MCP_TOOL_CALLS = 12

_HTML_TAG = re.compile(r"<[^>]+>")
_TOKEN = re.compile(r"[0-9A-Za-zÅÄÖåäö]+")
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
_CASE_CITATION = re.compile(
    r"\b(?:NJA|AD|MÖD|HFD|RÅ)\s+\d{4}(?:\s+(?:s\.\s*\d+|nr\s+\d+))?",
    re.IGNORECASE,
)
_PREPARATORY_CITATION = re.compile(
    r"\b(?:prop(?:osition)?\.?\s*\d{4}(?:/\d{2})?:\d+|SOU\s+\d{4}:\d+|"
    r"bet(?:änkande)?\.?\s*\d{4}/\d{2}:[A-Za-z]+\d+)",
    re.IGNORECASE,
)
_STATUTE_RESTATEMENT = re.compile(
    r"jämkas eller lämnas utan avseende.{0,80}oskäligt",
    re.IGNORECASE,
)
_PROVISION_CITATION = re.compile(r"\b\d+\s*§")
_STATUTE_PINPOINT = re.compile(r"^(?:K\d+)?P\d+[A-Za-z]?$")
_COVER_PINPOINT = re.compile(
    r"huvudsaklig|innehållsförteckning|titelsida|omslag",
    re.IGNORECASE,
)
_PROVISION_EXCERPT_CUES = ("jämk", "oskälig")
_JUDICIAL_REASON_CUES = (
    "domskäl",
    "domstolens bedömning",
    "högsta domstolen",
    "arbetsdomstolens bedömning",
    "skälen för avgörandet",
)
_PARTY_SUBMISSION_CUES = (
    "yrkande",
    "yrkanden",
    "grunder",
    "utveckling av talan",
    "parterna har anfört",
    "har invänt",
    "har anfört",
    "åberopade i tr",
)
_COURT_HEADINGS = (
    "högsta domstolen",
    "högsta förvaltningsdomstolen",
    "arbetsdomstolen",
    "patent- och marknadsöverdomstolen",
    "marknadsöverdomstolen",
    "hovrätt",
)
_REASON_HEADINGS = (
    "domskäl",
    "domstolens bedömning",
    "bedömning",
    "skälen för avgörandet",
)
_QUERY_STOPWORDS = frozenset(
    {
        "anger",
        "att",
        "av",
        "bedömning",
        "domstol",
        "domstolar",
        "den",
        "det",
        "eller",
        "enligt",
        "ett",
        "finns",
        "faktorer",
        "för",
        "har",
        "hur",
        "med",
        "och",
        "om",
        "praxis",
        "prop",
        "rättsfall",
        "som",
        "sou",
        "tillämpas",
        "tillämpning",
        "tyngst",
        "vad",
        "väger",
        "vilka",
    }
)


@dataclass(frozen=True)
class _Candidate:
    hit: LagenNuSearchHit
    direct_rank: int | None = None
    search_rank: int | None = None
    citation_rank: int | None = None

    @property
    def origins(self) -> tuple[str, ...]:
        origins: list[str] = []
        if self.direct_rank is not None:
            origins.append("resolve")
        if self.search_rank is not None:
            origins.append("search")
        if self.citation_rank is not None:
            origins.append("citation_graph")
        return tuple(origins)


def looks_like_citation(question: str) -> bool:
    return _CITATION_HINT.search(question) is not None


def looks_like_case_citation(question: str) -> bool:
    return _CASE_CITATION.search(question) is not None


def _unique_citations(pattern: re.Pattern[str], question: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in pattern.finditer(question):
        citation = " ".join(match.group(0).split())
        key = citation.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(citation)
    return ordered


def _case_citations(question: str) -> list[str]:
    return _unique_citations(_CASE_CITATION, question)


def _normalize_preparatory_citation(citation: str) -> str:
    text = " ".join(citation.split())
    proposition = re.fullmatch(
        r"(?i)prop(?:osition)?\.?\s*(\d{4})(?:/(\d{2}))?:(\d+)",
        text,
    )
    if proposition is not None:
        year, suffix, number = proposition.groups()
        if suffix:
            return f"prop. {year}/{suffix}:{number}"
        return f"prop. {year}:{number}"
    betankande = re.fullmatch(
        r"(?i)bet(?:änkande)?\.?\s*(\d{4}/\d{2}:[A-Za-z]+\d+)",
        text,
    )
    if betankande is not None:
        return f"bet. {betankande.group(1)}"
    return text


def _preparatory_citations(question: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for citation in _unique_citations(_PREPARATORY_CITATION, question):
        normalized = _normalize_preparatory_citation(citation)
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered


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


def _query_terms(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in (match.group(0).casefold() for match in _TOKEN.finditer(value))
        if len(token) > 2 and token not in _QUERY_STOPWORDS
    )


def _resolution_query(need: ResearchNeed, source_type: ResearchSourceType) -> str:
    if source_type == "swedish_preparatory_works":
        match = _PREPARATORY_CITATION.search(need.question)
        if match is not None:
            return match.group(0)
    if source_type == "swedish_case_law":
        match = _CASE_CITATION.search(need.question)
        if match is not None:
            return match.group(0)
    provision = _provision_resolution_query(need.question)
    if provision is not None:
        return provision
    return need.question


def _provision_resolution_query(question: str) -> str | None:
    provision = _PROVISION_CITATION.search(question)
    if provision is None:
        return None
    law = re.search(r"\b[A-Za-zÅÄÖåäö]+lagen\b", question, re.IGNORECASE)
    if law is None:
        return provision.group(0)
    return f"{provision.group(0)} {law.group(0)}"


def _search_query(question: str, source_type: ResearchSourceType) -> str:
    prefixes: list[str] = []
    for pattern in (_PREPARATORY_CITATION, _PROVISION_CITATION):
        match = pattern.search(question)
        if match is not None:
            prefixes.append(match.group(0))
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(question):
        token = match.group(0)
        normalized = token.casefold()
        if (
            len(normalized) <= 2
            or normalized in _QUERY_STOPWORDS
            or normalized.isdigit()
            or normalized in seen
        ):
            continue
        seen.add(normalized)
        terms.append(token)
    if source_type == "swedish_preparatory_works":
        prefixes = [
            item for item in prefixes if _PREPARATORY_CITATION.search(item)
        ]
        extra: list[str] = []
        if "förarbet" in question.casefold() and "generalklausul" not in {
            term.casefold() for term in terms
        }:
            extra.append("generalklausul")
        law_terms = [term for term in terms if term.casefold().endswith("lagen")]
        if _PREPARATORY_CITATION.search(question) and law_terms:
            terms = extra + law_terms[:2]
        elif _PROVISION_CITATION.search(question) and law_terms:
            terms = extra + law_terms[:2]
        else:
            terms = extra + terms[:3]
    query = " ".join((*prefixes, *terms[:6])).strip()
    return query or question


def _highlight_text(hit: LagenNuSearchHit) -> str:
    parts: list[str] = [hit.title or "", hit.identifier or ""]
    if hit.pin is not None:
        parts.extend(hit.pin.highlight)
        parts.append(hit.pin.label or "")
    for fragment in hit.fragments:
        parts.extend(fragment.highlight)
        parts.append(fragment.label or "")
    parts.extend(hit.highlight)
    return " ".join(_plain_text(part) for part in parts if part)


def _term_overlap(terms: frozenset[str], value: str) -> int:
    if not terms:
        return 0
    return len(terms & _query_terms(value))


def _judicial_reasons(text: str) -> str:
    """Return the highest available court's reasons and outcome."""
    lines = text.splitlines()
    legacy_courts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^(?:HD|HFD|AD)\s*\(", line)
        or "Högsta domstolen" in line
        or "Högsta förvaltningsdomstolen" in line
    ]
    if legacy_courts:
        court_start = legacy_courts[-1]
        reason_start = next(
            (
                index
                for index in range(court_start, len(lines))
                if lines[index].strip().casefold().startswith("domskäl")
            ),
            court_start,
        )
        outcome_end = next(
            (
                index + 1
                for index in range(reason_start + 1, len(lines))
                if lines[index].strip().casefold().startswith("domslut")
            ),
            len(lines),
        )
        selected = "\n".join(lines[reason_start:outcome_end]).strip()
        if selected:
            return selected[:MAX_EVIDENCE_CHARS]
    headings = [
        (index, line[3:].strip().casefold())
        for index, line in enumerate(lines)
        if line.startswith("## ")
    ]
    if not headings:
        return text[:MAX_EVIDENCE_CHARS]
    court_positions = [
        (index, heading)
        for index, heading in headings
        if any(court in heading for court in _COURT_HEADINGS)
    ]
    court_start = court_positions[-1][0] if court_positions else 0
    next_court = next(
        (
            index
            for index, heading in headings
            if index > court_start
            and any(court in heading for court in _COURT_HEADINGS)
        ),
        len(lines),
    )
    reason_start = next(
        (
            index
            for index, heading in headings
            if court_start <= index < next_court
            and any(reason in heading for reason in _REASON_HEADINGS)
        ),
        court_start,
    )
    outcome_end = next(
        (
            index
            for index, heading in headings
            if index > reason_start and "domslut" in heading
        ),
        next_court,
    )
    following_heading = next(
        (index for index, _heading in headings if index > outcome_end),
        len(lines),
    )
    selected = "\n".join(lines[reason_start:following_heading]).strip()
    return (selected or text)[:MAX_EVIDENCE_CHARS]


def _fragment_rank(
    terms: frozenset[str],
    text: str,
    index: int,
) -> tuple[int, int, int]:
    normalized = _plain_text(text).casefold()
    reason_cues = sum(cue in normalized for cue in _JUDICIAL_REASON_CUES)
    submission_cues = sum(cue in normalized for cue in _PARTY_SUBMISSION_CUES)
    return (
        -(reason_cues - submission_cues),
        -_term_overlap(terms, normalized),
        index,
    )


def _excerpt_from_hit(hit: LagenNuSearchHit, terms: frozenset[str]) -> str | None:
    parts: list[str] = []
    if hit.pin is not None:
        parts.extend(hit.pin.highlight)
    for fragment in hit.fragments:
        parts.extend(fragment.highlight)
    parts.extend(hit.highlight)
    ranked = sorted(
        enumerate(parts),
        key=lambda item: _fragment_rank(terms, item[1], item[0]),
    )
    for _index, part in ranked:
        text = _plain_text(part)
        if text:
            return text
    return None


def _document_identity(hit: LagenNuSearchHit) -> str:
    return (hit.uri or hit.url or hit.id or "").split("#", 1)[0].rstrip("/")


def _prefer_hit(current: LagenNuSearchHit, incoming: LagenNuSearchHit) -> LagenNuSearchHit:
    current_detail = bool(current.pin or current.fragments or current.highlight)
    incoming_detail = bool(incoming.pin or incoming.fragments or incoming.highlight)
    selected = incoming if incoming_detail and not current_detail else current
    inbound_count = max(
        value
        for value in (current.inbound_count, incoming.inbound_count, 0)
    )
    score = selected.score
    if score is None:
        score = current.score if current.score is not None else incoming.score
    return replace(selected, inbound_count=inbound_count or None, score=score)


def _merge_candidates(*groups: list[_Candidate]) -> list[_Candidate]:
    merged: dict[str, _Candidate] = {}
    for group in groups:
        for candidate in group:
            identity = _document_identity(candidate.hit)
            if not identity:
                continue
            current = merged.get(identity)
            if current is None:
                merged[identity] = candidate
                continue
            merged[identity] = _Candidate(
                hit=_prefer_hit(current.hit, candidate.hit),
                direct_rank=_minimum_rank(current.direct_rank, candidate.direct_rank),
                search_rank=_minimum_rank(current.search_rank, candidate.search_rank),
                citation_rank=_minimum_rank(
                    current.citation_rank,
                    candidate.citation_rank,
                ),
            )
    return list(merged.values())


def _minimum_rank(first: int | None, second: int | None) -> int | None:
    values = [value for value in (first, second) if value is not None]
    return min(values) if values else None


def _rank_candidates(need: ResearchNeed, candidates: list[_Candidate]) -> list[_Candidate]:
    terms = _query_terms(need.question)
    large = MAX_SEARCH_HITS + 1

    def key(candidate: _Candidate) -> tuple[object, ...]:
        exact = candidate.direct_rank is not None
        overlap_sources = (
            candidate.search_rank is not None
            and candidate.citation_rank is not None
        )
        return (
            0 if exact else 1,
            0 if overlap_sources else 1,
            -_term_overlap(terms, _highlight_text(candidate.hit)),
            candidate.search_rank if candidate.search_rank is not None else large,
            candidate.citation_rank if candidate.citation_rank is not None else large,
            -(candidate.hit.inbound_count or 0),
            _document_identity(candidate.hit),
        )

    return sorted(candidates, key=key)


def _candidates(
    hits: tuple[LagenNuSearchHit, ...] | list[LagenNuSearchHit],
    *,
    source: str,
    origin: Literal["resolve", "search", "citation_graph"],
) -> list[_Candidate]:
    selected: list[_Candidate] = []
    for rank, hit in enumerate(hits):
        if hit.source != source or not hit.uri:
            continue
        selected.append(
            _Candidate(
                hit=hit,
                direct_rank=rank if origin == "resolve" else None,
                search_rank=rank if origin == "search" else None,
                citation_rank=rank if origin == "citation_graph" else None,
            )
        )
    return selected


def _selectable_hit(candidate: _Candidate) -> SelectableHit:
    hit = candidate.hit
    identity = _document_identity(hit)
    return SelectableHit(
        candidate_id=identity or hit.id or hit.uri or "",
        uri=hit.uri or identity,
        title=hit.title,
        identifier=hit.identifier,
        highlight=_highlight_text(hit),
        pinpoint=_hit_pinpoint(hit, frozenset()),
    )


def _kept_candidates(
    candidates: list[_Candidate],
    decisions: list[HitDecision],
) -> list[_Candidate]:
    by_id = {item.candidate_id: item for item in decisions}
    kept: list[_Candidate] = []
    for candidate in candidates:
        decision = by_id[_selectable_hit(candidate).candidate_id]
        if not decision.keep:
            continue
        hit = candidate.hit
        if decision.pinpoint:
            hit = _hit_with_pinpoint(hit, decision.pinpoint)
        kept.append(
            _Candidate(
                hit=hit,
                direct_rank=candidate.direct_rank,
                search_rank=candidate.search_rank,
                citation_rank=candidate.citation_rank,
            )
        )
    return kept


def _hit_with_pinpoint(hit: LagenNuSearchHit, pinpoint: str) -> LagenNuSearchHit:
    if hit.pin is not None and (
        hit.pin.pinpoint == pinpoint or (hit.pin.uri or "").endswith(f"#{pinpoint}")
    ):
        return hit
    for fragment in hit.fragments:
        if fragment.pinpoint == pinpoint:
            return replace(hit, pin=fragment)
    return hit


class LagenNuResearchSource:
    def __init__(
        self,
        *,
        source_type: ResearchSourceType,
        client: LagenNuMcpClient | None = None,
        selector: LagenNuPassageSelector | None = None,
        interpreter: LegalInterpreter | None = None,
    ) -> None:
        if source_type not in LAGEN_NU_EVIDENCE_NATURES:
            raise ValueError(
                f"{source_type} is not implemented by the official lagen.nu adapter"
            )
        self.source_type = source_type
        self.provider_id = LAGEN_NU_PROVIDER_ID
        self._client = client
        self._selector = selector
        self._interpreter = interpreter or LlmLegalInterpreter()
        self._owned_client: OfficialLagenNuMcpClient | None = None

    def _require_selector(self) -> LagenNuPassageSelector:
        return resolve_passage_selector(self._selector)

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
        source = mcp_source_for_nature(self.source_type)
        if self.source_type == "swedish_case_law":
            candidates = await self._case_law_candidates(need, context, budget, source)
        else:
            candidates = await self._document_candidates(need, context, budget, source)
        ranked = _rank_candidates(need, _merge_candidates(candidates))
        if not ranked:
            return [self._not_found(need, budget, reason="no_hit")]
        selected = await self._select_candidates(need, context, ranked)
        if not selected:
            return [self._not_found(need, budget, reason="selector_rejected")]
        found = await self._fetch_candidates(need, context, selected, budget, source)
        if found:
            return found
        return [self._not_found(need, budget, reason="no_fetchable_document")]

    async def _document_candidates(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        budget: _CallBudget,
        source: str,
    ) -> list[_Candidate]:
        direct: list[_Candidate] = []
        named = (
            _preparatory_citations(need.question)
            if self.source_type == "swedish_preparatory_works"
            else []
        )
        if named:
            for citation in named:
                if budget.remaining <= 0:
                    break
                resolved = await budget.call(
                    "resolve_citation",
                    self._mcp().resolve_citation(citation),
                    {"citation": citation},
                )
                direct.extend(
                    _candidates(resolved.results, source=source, origin="resolve")
                )
            if direct:
                return _merge_candidates(direct)
        citation_graph: list[_Candidate] = []
        provision_query = _provision_resolution_query(need.question)
        resolved_provision = False
        if (
            self.source_type == "swedish_preparatory_works"
            and provision_query
            and not named
        ):
            resolved = await budget.call(
                "resolve_citation",
                self._mcp().resolve_citation(provision_query),
                {"citation": provision_query},
            )
            resolved_provision = True
            target = _resolved_provision_target(resolved.results)
            if target is not None:
                limit = min(context.limit, MAX_SEARCH_HITS)
                incoming = await budget.call(
                    "get_incoming_citations",
                    self._mcp().get_incoming_citations(
                        target,
                        source=source,
                        sort="rail",
                        limit=limit,
                    ),
                    {
                        "uri": target,
                        "source": source,
                        "sort": "rail",
                        "limit": limit,
                    },
                )
                citation_graph = _candidates(
                    incoming.results,
                    source=source,
                    origin="citation_graph",
                )
        flow = select_lagen_nu_flow(need)
        if flow == "resolve" and not named and not resolved_provision:
            resolved = await budget.call(
                "resolve_citation",
                self._mcp().resolve_citation(
                    _resolution_query(need, self.source_type)
                ),
                {"citation": _resolution_query(need, self.source_type)},
            )
            direct = _candidates(resolved.results, source=source, origin="resolve")
            if self.source_type == "swedish_law" and direct:
                return direct
            if (
                self.source_type == "swedish_law"
                and not direct
                and any(item.source == source for item in resolved.recognized)
            ):
                return []
        limit = min(context.limit, MAX_SEARCH_HITS)
        query = _search_query(need.question, self.source_type)
        searched = await budget.call(
            "search",
            self._mcp().search(query, source=source, limit=limit),
            {"query": query, "source": source, "limit": limit},
        )
        search = _candidates(searched.results, source=source, origin="search")
        return _merge_candidates(direct, citation_graph, search)

    async def _case_law_candidates(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        budget: _CallBudget,
        source: str,
    ) -> list[_Candidate]:
        direct: list[_Candidate] = []
        citation_graph: list[_Candidate] = []
        target: str | None = None
        named_cases = _case_citations(need.question)
        if named_cases:
            for citation in named_cases:
                if budget.remaining <= 0:
                    break
                resolved = await budget.call(
                    "resolve_citation",
                    self._mcp().resolve_citation(citation),
                    {"citation": citation},
                )
                direct.extend(
                    _candidates(resolved.results, source=source, origin="resolve")
                )
            if direct:
                return _merge_candidates(direct)
        if looks_like_citation(need.question) and not named_cases:
            resolved = await budget.call(
                "resolve_citation",
                self._mcp().resolve_citation(
                    _resolution_query(need, self.source_type)
                ),
                {"citation": _resolution_query(need, self.source_type)},
            )
            direct = _candidates(resolved.results, source=source, origin="resolve")
            target = _resolved_provision_target(resolved.results)
            if target is not None:
                limit = min(context.limit, MAX_SEARCH_HITS)
                incoming = await budget.call(
                    "get_incoming_citations",
                    self._mcp().get_incoming_citations(
                        target,
                        source=source,
                        sort="citations",
                        limit=limit,
                    ),
                    {
                        "uri": target,
                        "source": source,
                        "sort": "citations",
                        "limit": limit,
                    },
                )
                citation_graph = _candidates(
                    incoming.results,
                    source=source,
                    origin="citation_graph",
                )
        limit = min(context.limit, MAX_SEARCH_HITS)
        query = _search_query(need.question, self.source_type)
        searched = await budget.call(
            "search",
            self._mcp().search(
                query,
                source=source,
                kind="case",
                limit=limit,
            ),
            {
                "query": query,
                "source": source,
                "kind": "case",
                "limit": limit,
            },
        )
        search = _candidates(searched.results, source=source, origin="search")
        return _merge_candidates(direct, search, citation_graph)

    async def _select_candidates(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        candidates: list[_Candidate],
    ) -> list[_Candidate]:
        named = [item for item in candidates if item.direct_rank is not None]
        graph = [
            item
            for item in candidates
            if item.direct_rank is None and item.citation_rank is not None
        ]
        others = [
            item
            for item in candidates
            if item.direct_rank is None and item.citation_rank is None
        ]
        kept = list(named) + list(graph)
        if others:
            selectable = [_selectable_hit(item) for item in others]
            try:
                decisions = await self._require_selector().select_hits(
                    need=need,
                    source_type=self.source_type,
                    candidates=selectable,
                    context=context,
                )
            except LagenNuSelectionError:
                if not named and not graph:
                    raise
                logger.exception(
                    "lagen.nu hit selection failed for %s; keeping named and graph hits",
                    need.id,
                )
            else:
                kept.extend(_kept_candidates(others, decisions))
        return _rank_candidates(need, _merge_candidates(kept))

    async def _fetch_candidates(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        candidates: list[_Candidate],
        budget: _CallBudget,
        source: str,
    ) -> list[ResearchEvidence]:
        found: list[ResearchEvidence] = []
        seen: set[str] = set()
        terms = _query_terms(need.question)
        for candidate in candidates:
            if len(found) >= MAX_DOCUMENT_FETCHES or budget.remaining <= 0:
                break
            uri, pinpoint = _fetch_target(
                candidate.hit, terms, source_type=self.source_type
            )
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
                        uri,
                        pinpoint=pinpoint,
                        max_chars=MAX_DOCUMENT_CHARS,
                    ),
                    {
                        "uri": uri,
                        "pinpoint": pinpoint,
                        "max_chars": MAX_DOCUMENT_CHARS,
                    },
                )
            except OfficialLagenNuMcpNotFoundError:
                continue
            if document.source and document.source != source:
                continue
            try:
                found.append(
                    await self._from_document(
                        need,
                        context,
                        candidate,
                        document,
                        budget,
                        terms=terms,
                    )
                )
            except LagenNuSelectionError:
                logger.exception(
                    "lagen.nu excerpt rejected for %s (%s)",
                    uri,
                    need.id,
                )
        return found

    async def _from_document(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        candidate: _Candidate,
        document: LagenNuDocument,
        budget: _CallBudget,
        *,
        terms: frozenset[str],
    ) -> ResearchEvidence:
        hit = candidate.hit
        raw_document = document.text.strip()
        hit_excerpt = _excerpt_from_hit(hit, terms) or ""
        passage_source = raw_document or hit_excerpt
        passage = selector_passage_text(
            passage_source,
            needles=_passage_needles(need.question, terms),
            title=document.title or hit.title,
            max_chars=MAX_SELECTOR_DOCUMENT_CHARS,
        )
        trusted = (
            candidate.direct_rank is not None or candidate.citation_rank is not None
        )
        excerpt = None
        excerpt_why = ""
        excerpt_pinpoint = None
        try:
            excerpt_decision = await self._require_selector().select_excerpt(
                need=need,
                source_type=self.source_type,
                document=SelectableDocument(
                    uri=document.uri,
                    title=document.title or hit.title,
                    identifier=hit.identifier,
                    pinpoint=_usable_fetch_pinpoint(
                        document.pinpoint or _hit_pinpoint(hit, terms),
                        source_type=self.source_type,
                    ),
                    text=passage or clip_selector_document(raw_document or hit_excerpt),
                    highlight=hit_excerpt,
                    truncated=bool(document.truncated),
                ),
                context=context,
            )
            excerpt = self._usable_excerpt(
                excerpt_decision.excerpt,
                need=need,
                document=document,
                hit=hit,
                raw_document=raw_document,
                hit_excerpt=hit_excerpt,
                excerpt_pinpoint=excerpt_decision.pinpoint,
            )
            excerpt_why = excerpt_decision.why
            excerpt_pinpoint = excerpt_decision.pinpoint
        except LagenNuSelectionError:
            if not trusted:
                raise
            logger.exception(
                "lagen.nu excerpt rejected for trusted %s (%s); using window",
                document.uri,
                need.id,
            )
        if excerpt is None:
            excerpt = self._usable_excerpt(
                _window_excerpt(
                    passage or raw_document or hit_excerpt,
                    need.question,
                    title=document.title or hit.title,
                ),
                need=need,
                document=document,
                hit=hit,
                raw_document=raw_document,
                hit_excerpt=hit_excerpt,
                excerpt_pinpoint=None,
            )
            excerpt_why = excerpt_why or "windowed_passage"
        pinpoint = _usable_fetch_pinpoint(
            document.pinpoint or excerpt_pinpoint,
            source_type=self.source_type,
            label=excerpt,
        )
        source_uri = compose_canonical_uri(document.uri, pinpoint)
        title = display_source_title(
            uri=source_uri,
            identifier=hit.identifier,
            title=document.title or hit.title,
        )
        kind = {
            "swedish_case_law": "case_law",
            "swedish_preparatory_works": "preparatory_work",
            "swedish_law": "statute",
        }[self.source_type]
        legal_result = await self._interpreter.interpret(
            source=LegalSourceIdentity(
                kind=kind, title=title, canonical_uri=source_uri,
                identifier=hit.identifier,
                publisher_url=document.publisher_source_url,
            ),
            question=need.question, raw_text=raw_document,
            truncated=bool(document.truncated), context=context,
        )
        return research_evidence(
            research_need_id=need.id,
            source_type=self.source_type,
            status="found",
            title=title,
            excerpt=excerpt,
            locator=pinpoint,
            source_id=source_uri,
            source_url=source_uri,
            provider=self.provider_id,
            score=hit.score,
            legal_result=legal_result,
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
                retrieval_origins=list(candidate.origins),
                search_rank=candidate.search_rank,
                citation_rank=candidate.citation_rank,
                direct_rank=candidate.direct_rank,
                query_term_overlap=_term_overlap(terms, _highlight_text(hit)),
                selection_role=(
                    "named_citation" if candidate.direct_rank is not None else None
                ),
                selection_why=excerpt_why or None,
            ),
        )

    def _usable_excerpt(
        self,
        excerpt: str,
        *,
        need: ResearchNeed,
        document: LagenNuDocument,
        hit: LagenNuSearchHit,
        raw_document: str,
        hit_excerpt: str,
        excerpt_pinpoint: str | None,
    ) -> str:
        verified = verify_excerpt_span(
            raw_document or hit_excerpt,
            excerpt,
            max_chars=MAX_EVIDENCE_CHARS,
            allowed_extra=hit_excerpt,
        )
        if is_legal_front_matter(verified, title=document.title or hit.title):
            raise LagenNuSelectionError("selector excerpt is front matter")
        if self.source_type == "swedish_case_law" and _excerpt_is_party_submission(
            verified
        ):
            raise LagenNuSelectionError("selector excerpt is a party submission")
        if self.source_type == "swedish_case_law" and _excerpt_is_statute_restatement(
            verified
        ):
            raise LagenNuSelectionError("selector excerpt only restates the statute")
        pinpoint = _usable_fetch_pinpoint(
            document.pinpoint or excerpt_pinpoint,
            source_type=self.source_type,
            label=verified,
        )
        if not _excerpt_addresses_question(
            verified,
            need.question,
            pinpoint=pinpoint or document.pinpoint,
            source_type=self.source_type,
        ):
            raise LagenNuSelectionError(
                "selector excerpt does not mention the provision in the question"
            )
        return verified

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
            excerpt=reason,
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
            "authority_level": "trusted",
            "primary_source": True,
            "source_nature": "primary",
            "official_source_aggregator": True,
            "publication_note": LAGEN_NU_PUBLICATION_NOTE,
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


def _resolved_provision_target(hits: tuple[LagenNuSearchHit, ...]) -> str | None:
    preferred = [hit for hit in hits if hit.source == "sfs"]
    for hit in (*preferred, *hits):
        if hit.pin is not None and hit.pin.uri:
            return hit.pin.uri
    for hit in (*preferred, *hits):
        if hit.uri:
            return hit.uri
    return None


def _best_fragment(
    hit: LagenNuSearchHit,
    terms: frozenset[str],
):
    ranked = sorted(
        enumerate(hit.fragments),
        key=lambda item: _fragment_rank(
            terms,
            " ".join((*item[1].highlight, item[1].label or "")),
            item[0],
        ),
    )
    return ranked[0][1] if ranked else None


def _hit_pinpoint(hit: LagenNuSearchHit, terms: frozenset[str]) -> str | None:
    if hit.pin is not None and hit.pin.pinpoint:
        return hit.pin.pinpoint
    fragment = _best_fragment(hit, terms)
    return fragment.pinpoint if fragment is not None else None


def _passage_needles(question: str, terms: frozenset[str]) -> frozenset[str]:
    needles = set(terms)
    needles.update(_PROVISION_EXCERPT_CUES)
    for match in _PROVISION_CITATION.finditer(question):
        needles.add(match.group(0))
        needles.add(match.group(0).replace(" ", ""))
    return frozenset(needles)


def _window_excerpt(passage: str, question: str, *, title: str | None) -> str:
    terms = _query_terms(question) | frozenset(_PROVISION_EXCERPT_CUES)
    chosen = relevant_legal_excerpt(
        passage,
        terms=terms,
        title=title,
        max_chars=WINDOW_CHARS,
    )
    return (chosen or passage).strip()


def _excerpt_addresses_question(
    excerpt: str,
    question: str,
    *,
    pinpoint: str | None = None,
    source_type: ResearchSourceType | None = None,
) -> bool:
    provisions = [match.group(0) for match in _PROVISION_CITATION.finditer(question)]
    if not provisions:
        return True
    compact = excerpt.casefold()
    compact_nospace = compact.replace(" ", "")
    if any(
        provision.casefold() in compact
        or provision.casefold().replace(" ", "") in compact_nospace
        for provision in provisions
    ):
        return True
    if _pinpoint_matches_provision(pinpoint, provisions):
        return True
    if source_type == "swedish_preparatory_works":
        return False
    excerpt_numbers = {
        match.group(0).replace(" ", "").replace("§", "")
        for match in _PROVISION_CITATION.finditer(excerpt)
    }
    asked_numbers = {
        provision.casefold().replace(" ", "").replace("§", "") for provision in provisions
    }
    if excerpt_numbers and excerpt_numbers.isdisjoint(asked_numbers):
        return False
    return any(cue in compact for cue in _PROVISION_EXCERPT_CUES)


def _excerpt_is_statute_restatement(excerpt: str) -> bool:
    compact = " ".join(excerpt.split()).casefold()
    if _STATUTE_RESTATEMENT.search(compact) is None:
        return False
    if any(cue in compact for cue in _JUDICIAL_REASON_CUES):
        return False
    return len(compact) < 400


def _excerpt_is_party_submission(excerpt: str) -> bool:
    normalized = excerpt.casefold()
    submissions = sum(cue in normalized for cue in _PARTY_SUBMISSION_CUES)
    reasons = sum(cue in normalized for cue in _JUDICIAL_REASON_CUES)
    return submissions > 0 and reasons == 0


def _pinpoint_matches_provision(
    pinpoint: str | None,
    provisions: list[str],
) -> bool:
    if not pinpoint:
        return False
    match = _STATUTE_PINPOINT.fullmatch(pinpoint)
    if match is None:
        return False
    number = re.sub(r"^(?:K\d+)?P", "", pinpoint)
    number = re.sub(r"[A-Za-z]$", "", number)
    return any(re.search(rf"\b{re.escape(number)}\s*§", provision) for provision in provisions)


def _usable_fetch_pinpoint(
    pinpoint: str | None,
    *,
    source_type: ResearchSourceType,
    label: str = "",
) -> str | None:
    if not pinpoint or not pinpoint.strip():
        return None
    blob = f"{pinpoint} {label}".strip()
    if (
        _COVER_PINPOINT.search(blob)
        or is_legal_front_matter(pinpoint)
        or is_legal_front_matter(label)
    ):
        return None
    if source_type == "swedish_preparatory_works" and not _STATUTE_PINPOINT.fullmatch(
        pinpoint
    ):
        return None
    return pinpoint


def _fetch_target(
    hit: LagenNuSearchHit,
    terms: frozenset[str],
    *,
    source_type: ResearchSourceType,
) -> tuple[str | None, str | None]:
    if hit.pin is not None and hit.pin.uri:
        uri = hit.pin.uri.split("#", 1)[0]
        return uri, _usable_fetch_pinpoint(
            hit.pin.pinpoint,
            source_type=source_type,
            label=" ".join((hit.pin.label or "", *hit.pin.highlight)),
        )
    fragment = _best_fragment(hit, terms)
    if fragment is not None and fragment.uri:
        uri = fragment.uri.split("#", 1)[0]
        return uri, _usable_fetch_pinpoint(
            fragment.pinpoint,
            source_type=source_type,
            label=" ".join((fragment.label or "", *fragment.highlight)),
        )
    if hit.uri is None:
        return None, None
    if "#" in hit.uri:
        document_uri, pinpoint = hit.uri.split("#", 1)
        return document_uri, _usable_fetch_pinpoint(
            pinpoint or None, source_type=source_type
        )
    return hit.uri, None
