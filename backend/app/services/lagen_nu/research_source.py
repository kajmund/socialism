"""Provider-owned lagen.nu retrieval behind the generic ResearchSource seam."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    DomainResearchResultRecord,
    EvidenceSet,
    EvidenceSetItem,
    EvidenceSource,
    RawSource,
    ResearchRuntimeNeed,
    TextUnitRecord,
)
from app.llm.legal_research import (
    LegalDomainExtractionError,
    LegalInterpreter,
    LlmLegalInterpreter,
)
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.lagen_nu.display import (
    display_source_title,
    is_legal_front_matter,
)
from app.services.lagen_nu.mcp_client import (
    LagenNuMcpClient,
    OfficialLagenNuMcpClient,
    OfficialLagenNuMcpError,
    OfficialLagenNuMcpNotFoundError,
)
from app.services.lagen_nu.models import LagenNuDocument, LagenNuSearchHit
from app.services.lagen_nu.passage_router import (
    JevPassageRouter,
    LagenNuPassageRouter,
    PassageRoutingError,
)
from app.services.lagen_nu.question_validation import (
    LegalQuestionValidator,
    is_legal_research_need,
)
from app.services.lagen_nu.registration import (
    LAGEN_NU_EVIDENCE_NATURES,
    LAGEN_NU_JURISDICTION,
    LAGEN_NU_PROVIDER_ID,
    LAGEN_NU_PUBLICATION_NOTE,
    mcp_source_for_nature,
)
from app.services.lagen_nu.selection import (
    HitDecision,
    LagenNuPassageSelector,
    LagenNuSelectionError,
    SelectableHit,
    resolve_passage_selector,
)
from app.services.lagen_nu.text_unit_research import (
    LagenNuResearchKnowledgeError,
    current_lagen_nu_units,
    document_identity_uri,
    ingest_and_load_text_units,
    require_lagen_nu_research_knowledge,
)
from app.services.lagen_nu.uris import compose_canonical_uri
from app.services.legal_research_result import LegalResearchResult, LegalSourceIdentity
from app.services.research.evidence_identity import canonical_source_identity
from app.services.research.failures import FailureCategory
from app.services.research.knowledge_question import research_question_key
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
MAX_DOCUMENT_CHARS = 200000
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
_PROVISION_CITATION = re.compile(r"\b\d+\s*§")
_COVER_PINPOINT = re.compile(
    r"huvudsaklig|innehållsförteckning|titelsida|omslag",
    re.IGNORECASE,
)
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
        prefixes = [item for item in prefixes if _PREPARATORY_CITATION.search(item)]
        extra: list[str] = []
        if "förarbet" in question.casefold() and "generalklausul" not in {
            term.casefold() for term in terms
        }:
            extra.append("generalklausul")
        law_terms = [term for term in terms if term.casefold().endswith("lagen")]
        if (
            _PREPARATORY_CITATION.search(question)
            and law_terms
            or _PROVISION_CITATION.search(question)
            and law_terms
        ):
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
    inbound_count = max(value for value in (current.inbound_count, incoming.inbound_count, 0))
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
        overlap_sources = candidate.search_rank is not None and candidate.citation_rank is not None
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
        if not decision.keep or decision.role in {"wrong_number", "wrong_subject"}:
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
        session: AsyncSession | None = None,
        embeddings: EmbeddingProvider | None = None,
        vector_store: KnowledgeVectorStore | None = None,
        question_validator: LegalQuestionValidator | None = None,
        passage_router: LagenNuPassageRouter | None = None,
    ) -> None:
        if source_type not in LAGEN_NU_EVIDENCE_NATURES:
            raise ValueError(f"{source_type} is not implemented by the official lagen.nu adapter")
        self.source_type = source_type
        self.provider_id = LAGEN_NU_PROVIDER_ID
        self._client = client
        self._selector = selector
        self._interpreter = interpreter or LlmLegalInterpreter()
        self._session = session
        self._embeddings = embeddings
        self._vector_store = vector_store
        self._question_validator = question_validator
        self._passage_router = passage_router
        self._owned_client: OfficialLagenNuMcpClient | None = None

    def _require_selector(self) -> LagenNuPassageSelector:
        return resolve_passage_selector(self._selector)

    def _require_passage_router(self) -> LagenNuPassageRouter:
        if self._passage_router is not None:
            return self._passage_router
        return JevPassageRouter()

    def _mcp(self) -> LagenNuMcpClient:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = OfficialLagenNuMcpClient()
        return self._owned_client

    async def _cached_domain_result(
        self, *, need: ResearchNeed, source_uri: str, raw_text: str
    ) -> tuple[str, LegalResearchResult] | None:
        session = self._session
        if session is None:
            return None
        source_identity = canonical_source_identity(source_uri, None)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        row = (
            await session.execute(
                select(DomainResearchResultRecord)
                .join(RawSource, DomainResearchResultRecord.raw_source_id == RawSource.id)
                .join(EvidenceSource, RawSource.source_id == EvidenceSource.id)
                .join(
                    EvidenceSetItem,
                    (EvidenceSetItem.domain_result_id == DomainResearchResultRecord.id)
                    & (
                        EvidenceSetItem.research_need_id
                        == DomainResearchResultRecord.research_need_id
                    ),
                )
                .join(EvidenceSet, EvidenceSetItem.evidence_set_id == EvidenceSet.id)
                .join(
                    ResearchRuntimeNeed,
                    (ResearchRuntimeNeed.attempt_id == EvidenceSet.created_from_attempt_id)
                    & (
                        ResearchRuntimeNeed.research_need_id
                        == DomainResearchResultRecord.research_need_id
                    ),
                )
                .where(
                    EvidenceSource.provider == self.provider_id,
                    EvidenceSource.canonical_identity == source_identity,
                    RawSource.content_hash == raw_hash,
                    DomainResearchResultRecord.schema_version == 4,
                    ResearchRuntimeNeed.question_key == research_question_key(need.question),
                )
                .order_by(DomainResearchResultRecord.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        logger.info(
            "domain_result_reused provider=%s source=%s domain_result_id=%s",
            self.provider_id,
            source_uri,
            row.id,
        )
        return row.id, LegalResearchResult.model_validate({**row.result, "raw_text": raw_text})

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
        if (
            self._question_validator is not None
            and not need.already_normalized
            and is_legal_research_need(need.source_types)
        ):
            verdict = await self._question_validator.validate(
                question=need.question,
                why_needed=need.why_needed,
                source_types=need.source_types,
            )
            if verdict.action != "keep":
                return [self._not_found(need, budget, reason="question_incoherent")]
        source = mcp_source_for_nature(self.source_type)
        try:
            if self.source_type == "swedish_case_law":
                candidates = await self._case_law_candidates(need, context, budget, source)
            else:
                candidates = await self._document_candidates(need, context, budget, source)
        except OfficialLagenNuMcpError as exc:
            return [self._failure(need, budget, exc.category, None, str(exc))]
        ranked = _rank_candidates(need, _merge_candidates(candidates))
        if not ranked:
            return [
                self._not_found(
                    need,
                    budget,
                    reason="resolve_no_document"
                    if any(call["tool"] == "resolve_citation" for call in budget.calls)
                    else "search_no_hit",
                )
            ]
        try:
            selected = await self._select_candidates(need, context, ranked)
        except LagenNuSelectionError as exc:
            return [self._failure(need, budget, "selection_failed", None, str(exc))]
        if not selected:
            return [self._not_found(need, budget, reason="irrelevant_relation")]
        found = await self._fetch_candidates(need, context, selected, budget, source)
        if found:
            return found
        return [self._not_found(need, budget, reason="budget_exhausted")]

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
                direct.extend(_candidates(resolved.results, source=source, origin="resolve"))
            if direct:
                return _merge_candidates(direct)
        citation_graph: list[_Candidate] = []
        provision_query = _provision_resolution_query(need.question)
        resolved_provision = False
        if self.source_type == "swedish_preparatory_works" and provision_query and not named:
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
                self._mcp().resolve_citation(_resolution_query(need, self.source_type)),
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
                direct.extend(_candidates(resolved.results, source=source, origin="resolve"))
            if direct:
                return _merge_candidates(direct)
        if looks_like_citation(need.question) and not named_cases:
            resolved = await budget.call(
                "resolve_citation",
                self._mcp().resolve_citation(_resolution_query(need, self.source_type)),
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
        others = graph + [
            item for item in candidates if item.direct_rank is None and item.citation_rank is None
        ]
        kept = list(named)
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
                if not named:
                    raise
                logger.exception(
                    "lagen.nu hit selection failed for %s; keeping named hits",
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
        session, embeddings, vector_store = require_lagen_nu_research_knowledge(
            session=self._session,
            embeddings=self._embeddings,
            vector_store=self._vector_store,
        )
        customer_id = context.scope.customer_id
        if customer_id is None:
            raise LagenNuResearchKnowledgeError("lagen.nu research requires customer_id")
        found: list[ResearchEvidence] = []
        seen: set[str] = set()
        terms = _query_terms(need.question)
        for candidate in candidates:
            if len(found) >= MAX_DOCUMENT_FETCHES or budget.remaining <= 0:
                break
            uri, pinpoint = _fetch_target(candidate.hit, terms, source_type=self.source_type)
            if uri is None:
                continue
            try:
                canonical_uri = document_identity_uri(uri)
            except LagenNuResearchKnowledgeError as exc:
                found.append(self._failure(need, budget, "unsupported_source_shape", uri, str(exc)))
                continue
            target_key = canonical_uri if pinpoint is None else f"{canonical_uri}#{pinpoint}"
            if target_key in seen:
                continue
            seen.add(target_key)
            try:
                units = await current_lagen_nu_units(
                    session,
                    customer_id=customer_id,
                    canonical_uri=canonical_uri,
                )
                reused_units = units is not None
                document = None
                if units is None:
                    logger.info(
                        "provider_retrieval_started provider=%s source=%s",
                        self.provider_id,
                        canonical_uri,
                    )
                    document = await budget.call(
                        "get_document",
                        self._mcp().get_document(
                            canonical_uri,
                            pinpoint=None,
                            max_chars=MAX_DOCUMENT_CHARS,
                        ),
                        {
                            "uri": canonical_uri,
                            "pinpoint": None,
                            "max_chars": MAX_DOCUMENT_CHARS,
                        },
                    )
                    if document.source and document.source != source:
                        found.append(
                            self._failure(
                                need,
                                budget,
                                "unsupported_source_shape",
                                canonical_uri,
                                f"expected source {source}, received {document.source}",
                                fetch_success=True,
                            )
                        )
                        continue
                    ingest_result, units = await ingest_and_load_text_units(
                        session,
                        customer_id=customer_id,
                        document=document,
                        embeddings=embeddings,
                        vector_store=vector_store,
                    )
                    if ingest_result.status != "indexed" or units is None:
                        raise LegalDomainExtractionError(
                            ingest_result.message or "retrieved document has no text",
                            category="unsupported_source_shape",
                        )
                found.append(
                    await self._from_document(
                        need,
                        context,
                        candidate,
                        units,
                        budget,
                        terms=terms,
                        canonical_uri=canonical_uri,
                        pinpoint=pinpoint,
                        document=document,
                        reused_units=reused_units,
                    )
                )
            except OfficialLagenNuMcpError as exc:
                category = (
                    "resolve_no_document"
                    if isinstance(exc, OfficialLagenNuMcpNotFoundError)
                    else getattr(exc, "category", "fetch_failed")
                )
                found.append(self._failure(need, budget, category, canonical_uri, str(exc)))
            except LegalDomainExtractionError as exc:
                found.append(
                    self._failure(
                        need,
                        budget,
                        exc.category,
                        canonical_uri,
                        str(exc),
                        fetch_success=True,
                    )
                )
            except LagenNuResearchKnowledgeError as exc:
                found.append(self._failure(need, budget, "fetch_failed", canonical_uri, str(exc)))
            except PassageRoutingError as exc:
                found.append(
                    self._failure(
                        need,
                        budget,
                        exc.category,
                        canonical_uri,
                        str(exc),
                        fetch_success=True,
                    )
                )
        return found

    async def _from_document(
        self,
        need: ResearchNeed,
        context: ResearchContext,
        candidate: _Candidate,
        units: list[TextUnitRecord],
        budget: _CallBudget,
        *,
        terms: frozenset[str],
        canonical_uri: str,
        pinpoint: str | None,
        document: LagenNuDocument | None,
        reused_units: bool = False,
    ) -> ResearchEvidence:
        hit = candidate.hit
        if self._embeddings is None or self._vector_store is None:
            raise LagenNuResearchKnowledgeError(
                "lagen.nu research requires embeddings and stored TextUnit vectors"
            )
        try:
            routed = await self._require_passage_router().route(
                question=need.question,
                units=units,
                embeddings=self._embeddings,
                stored=self._vector_store,
            )
        except PassageRoutingError as exc:
            if exc.category == "irrelevant_relation":
                source_uri = compose_canonical_uri(canonical_uri, pinpoint)
                title = display_source_title(
                    uri=source_uri,
                    identifier=hit.identifier,
                    title=(document.title if document is not None else None) or hit.title,
                )
                return research_evidence(
                    research_need_id=need.id,
                    source_type=self.source_type,
                    status="not_found",
                    title=title,
                    source_id=source_uri,
                    source_url=source_uri,
                    provider=self.provider_id,
                    metadata=self._provenance(
                        budget,
                        reason="passage_router_empty",
                        failure_category="irrelevant_relation",
                        fetch_success=True,
                        canonical_uri=source_uri,
                        reused_text_units=reused_units,
                        canonical_document_id=units[0].document_id,
                        document_version_id=units[0].document_version_id,
                        passage_candidate_ids=list(exc.seed_ids),
                        detail=str(exc),
                    ),
                )
            raise
        raw_document = routed.interpreter_text.strip()
        if not raw_document:
            raise LegalDomainExtractionError(
                "retrieved document has no text", category="unsupported_source_shape"
            )
        # Interpret ingested TextUnits before choosing display text. A rejected
        # display passage must never erase an otherwise fetchable document.
        source_uri = compose_canonical_uri(canonical_uri, pinpoint)
        title = display_source_title(
            uri=source_uri,
            identifier=hit.identifier,
            title=(document.title if document is not None else None) or hit.title,
        )
        kind = {
            "swedish_case_law": "case_law",
            "swedish_preparatory_works": "preparatory_work",
            "swedish_law": "statute",
        }[self.source_type]
        cached = await self._cached_domain_result(
            need=need, source_uri=source_uri, raw_text=raw_document
        )
        legal_result = (
            cached[1]
            if cached is not None
            else await self._interpreter.interpret(
                source=LegalSourceIdentity(
                    kind=kind,
                    title=title,
                    canonical_uri=source_uri,
                    identifier=hit.identifier,
                    publisher_url=(document.publisher_source_url if document is not None else None),
                ),
                question=need.question,
                raw_text=raw_document,
                truncated=(
                    (bool(document.truncated) if document is not None else False)
                    or routed.interpreter_clipped
                ),
                context=context,
            )
        )
        if cached is None and reused_units:
            logger.info(
                "domain_result_recomputed_from_text_units provider=%s source=%s",
                self.provider_id,
                source_uri,
            )
        if legal_result.relation.relation == "irrelevant":
            return research_evidence(
                research_need_id=need.id,
                source_type=self.source_type,
                status="not_found",
                title=title,
                source_id=source_uri,
                source_url=source_uri,
                provider=self.provider_id,
                metadata=self._provenance(
                    budget,
                    reason="domain_relation_irrelevant",
                    failure_category="irrelevant_relation",
                    fetch_success=True,
                    domain_extraction_success=True,
                    canonical_uri=source_uri,
                    selection_why=legal_result.relation.explanation,
                ),
            )
        analysis = legal_result.case_law or legal_result.preparatory_work or legal_result.statute
        assert analysis is not None
        excerpt = analysis.citations[0].quote[:MAX_EVIDENCE_CHARS]
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
                source=(document.source if document is not None else None) or hit.source,
                kind=(document.kind if document is not None else None) or hit.kind,
                identifier=hit.identifier,
                publisher_source_url=(
                    document.publisher_source_url if document is not None else None
                ),
                pinpoint=pinpoint,
                truncated=bool(document.truncated) if document is not None else False,
                inbound_count=document.inbound_count if document is not None else None,
                retrieval_origins=list(candidate.origins),
                search_rank=candidate.search_rank,
                citation_rank=candidate.citation_rank,
                direct_rank=candidate.direct_rank,
                query_term_overlap=_term_overlap(terms, _highlight_text(hit)),
                selection_role=("named_citation" if candidate.direct_rank is not None else None),
                selection_why="verified_domain_citation",
                fetch_success=True,
                domain_extraction_success=True,
                reused_domain_result_id=cached[0] if cached is not None else None,
                reused_text_units=reused_units,
                canonical_document_id=units[0].document_id,
                document_version_id=units[0].document_version_id,
                text_unit_ids=list(routed.expanded_ids),
                passage_candidate_ids=list(routed.candidate_ids),
                passage_kept_ids=list(routed.kept_ids),
                passage_router=routed.router,
                passage_jev_clipped=routed.jev_clipped,
                passage_interpreter_clipped=routed.interpreter_clipped,
            ),
        )

    def _failure(
        self,
        need: ResearchNeed,
        budget: _CallBudget,
        category: FailureCategory,
        uri: str | None,
        detail: str,
        *,
        fetch_success: bool = False,
    ) -> ResearchEvidence:
        logger.warning(
            "research_failure provider=%s need=%s source=%s category=%s detail=%s",
            self.provider_id,
            need.id,
            uri,
            category,
            detail,
        )
        return research_evidence(
            research_need_id=need.id,
            source_type=self.source_type,
            status="not_found" if category == "resolve_no_document" else "error",
            source_id=uri,
            source_url=uri,
            provider=self.provider_id,
            metadata=self._provenance(
                budget,
                reason=category,
                failure_category=category,
                detail=detail,
                fetch_success=fetch_success,
                domain_extraction_success=False if fetch_success else None,
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
            excerpt=reason,
            provider=self.provider_id,
            metadata=self._provenance(budget, reason=reason, failure_category=reason),
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
    return pinpoint


def _fetch_target(
    hit: LagenNuSearchHit,
    terms: frozenset[str],
    *,
    source_type: ResearchSourceType,
) -> tuple[str | None, str | None]:
    if source_type == "swedish_case_law":
        return _document_identity(hit) or None, None
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
        return document_uri, _usable_fetch_pinpoint(pinpoint or None, source_type=source_type)
    return hit.uri, None
