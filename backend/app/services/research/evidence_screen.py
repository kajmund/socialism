"""Shadow Jev scoring of retrieved evidence. Never deletes or mutates evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.jev.system import (
    HttpJevSystemOne,
    JevSystemOne,
    parse_noul,
)
from app.observability.research import (
    emit_jev_evidence_scored,
    record_jev_call,
    record_jev_screen_cache_hit,
    record_relevance_jev_call,
    record_relevance_llm_fallback,
)
from app.services.research.assessment import AssessableEvidence
from app.services.research.fast_controller import (
    JEV_PROVIDER,
    research_jev_available,
    research_jev_mode,
    research_jev_model,
)
from app.services.research.fast_state import compact_evidence_item_state
from app.services.research.knowledge_question import normalize_research_question
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import ResearchObjective
from app.services.research.quality import (
    EvidenceRelevanceAssessor,
    EvidenceRelevanceJudgment,
    QualityEvidenceInput,
    RelevanceLevel,
)

EVIDENCE_SCREEN_QUESTIONS: dict[str, Any] = {
    "relevant_to_question": {
        "type": "noul",
        "instructions": "Is this evidence relevant to the research question?",
        "criteria": {
            "true": "It bears on the question.",
            "false": "It is off-topic.",
        },
    },
    "directly_supports_answer": {
        "type": "noul",
        "instructions": "Does this evidence directly support an answer?",
        "criteria": {
            "true": "It supports a concrete answer.",
            "false": "It does not support an answer.",
        },
    },
    "contradicts_current_evidence": {
        "type": "noul",
        "instructions": "Does this evidence contradict other supplied facts?",
        "criteria": {
            "true": "It conflicts with other evidence.",
            "false": "It is consistent or standalone.",
        },
    },
    "material_new_information": {
        "type": "noul",
        "instructions": "Does this evidence add material new information?",
        "criteria": {
            "true": "It adds a new material fact.",
            "false": "It repeats already known information.",
        },
    },
    "likely_duplicate_or_redundant": {
        "type": "noul",
        "instructions": "Is this evidence a likely duplicate or redundant copy?",
        "criteria": {
            "true": "It restates the same source or fact.",
            "false": "It is an independent item.",
        },
    },
    "primary_or_high_authority_for_question": {
        "type": "noul",
        "instructions": "Is this a primary or high-authority source for the question?",
        "criteria": {
            "true": "It is an authoritative source for this question.",
            "false": "It is secondary, informal, or low authority.",
        },
    },
}


@dataclass(frozen=True)
class EvidenceJevScores:
    evidence_id: str
    source_type: str
    content_hash: str
    relevant_to_question: float
    directly_supports_answer: float
    contradicts_current_evidence: float
    material_new_information: float
    likely_duplicate_or_redundant: float
    primary_or_high_authority_for_question: float
    latency_ms: float


def question_set_version(questions: Mapping[str, Any]) -> str:
    encoded = json.dumps(questions, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evidence_screen_cache_key(
    *,
    model: str,
    objective: str,
    content_hash: str,
    questions: Mapping[str, Any] = EVIDENCE_SCREEN_QUESTIONS,
) -> tuple[str, str, str, str]:
    return (
        model,
        question_set_version(questions),
        content_hash,
        hashlib.sha256(normalize_research_question(objective).encode("utf-8")).hexdigest(),
    )


class EvidenceScreenCache:
    """Per-Attempt Jev scores. Shared only when objective and questions match."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str, str], EvidenceJevScores] = {}
        self.hits = 0

    def __len__(self) -> int:
        return len(self._store)

    def get(self, key: tuple[str, str, str, str]) -> EvidenceJevScores | None:
        row = self._store.get(key)
        if row is None:
            return None
        self.hits += 1
        record_jev_screen_cache_hit()
        return row

    def put(self, key: tuple[str, str, str, str], row: EvidenceJevScores) -> None:
        self._store[key] = row
        while len(self._store) > 256:
            del self._store[next(iter(self._store))]


def relevance_from_jev_scores(scores: EvidenceJevScores) -> RelevanceLevel:
    if scores.relevant_to_question >= 0.8 and scores.directly_supports_answer >= 0.5:
        return "high"
    if scores.relevant_to_question >= 0.5:
        return "medium"
    return "low"


class JevEvidenceRelevanceAssessor:
    """Need-scoped Jev relevance. Does not reuse plan-wide screening scores."""

    def __init__(
        self,
        *,
        inner: EvidenceRelevanceAssessor | None = None,
        cache: EvidenceScreenCache | None = None,
        client: JevSystemOne | None = None,
    ) -> None:
        self._inner = inner
        self._cache = EvidenceScreenCache() if cache is None else cache
        self._client = client

    async def judge(
        self,
        need: ResearchNeed,
        item: QualityEvidenceInput,
    ) -> EvidenceRelevanceJudgment:
        scores = await _score_one(
            self._client or HttpJevSystemOne(),
            objective=need.question,
            item=_assessable_from_quality(item),
            slots=None,
            cache=self._cache,
            count_relevance_call=True,
        )
        if scores is not None:
            return EvidenceRelevanceJudgment(
                relevance=relevance_from_jev_scores(scores),
                model_provider="jev",
                model_name=research_jev_model(),
            )
        if self._inner is not None:
            record_relevance_llm_fallback()
            return await self._inner.judge(need, item)
        return EvidenceRelevanceJudgment(relevance="unknown", failed=True)


def bind_attempt_relevance(
    assessor: object,
    injected: EvidenceRelevanceAssessor | None,
    *,
    cache: EvidenceScreenCache | None = None,
) -> tuple[EvidenceScreenCache, EvidenceRelevanceAssessor | None]:
    """Share one Attempt cache between screening and Jev relevance."""
    screen_cache = EvidenceScreenCache() if cache is None else cache
    bind = getattr(assessor, "bind_screen_cache", None)
    if callable(bind):
        bind(screen_cache)
    if settings.research_relevance_source == "llm":
        return screen_cache, injected
    return screen_cache, JevEvidenceRelevanceAssessor(inner=injected, cache=screen_cache)


def _assessable_from_quality(item: QualityEvidenceInput) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=item.original_evidence_id or item.item_id,
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        score=None,
        provenance=item.provenance,
        retrieved_at=item.retrieved_at,
        content_hash=item.content_hash,
    )


async def screen_evidence(
    *,
    objective: str,
    evidence: Sequence[AssessableEvidence],
    client: JevSystemOne | None = None,
    cache: EvidenceScreenCache | None = None,
) -> list[EvidenceJevScores]:
    """Score items concurrently. Failures are omitted; evidence is unchanged."""
    if not research_jev_available() or not settings.research_jev_evidence_screen_enabled:
        return []
    system = client or HttpJevSystemOne()
    slots = asyncio.Semaphore(settings.research_jev_concurrency)
    tasks = [
        asyncio.create_task(
            _score_one(system, objective=objective, item=item, slots=slots, cache=cache)
        )
        for item in evidence
    ]
    scored: list[EvidenceJevScores] = []
    for task in asyncio.as_completed(tasks):
        row = await task
        if row is not None:
            scored.append(row)
    scored.sort(key=lambda row: row.evidence_id)
    return scored


def order_evidence_for_state(
    evidence: Sequence[AssessableEvidence],
    scores: Sequence[EvidenceJevScores],
) -> list[AssessableEvidence]:
    """Prefer material, relevant items in the clipped Jev state. No deletions."""
    by_id = {row.evidence_id: row for row in scores}

    def sort_key(item: AssessableEvidence) -> tuple[float, float, str]:
        row = by_id.get(item.evidence_id)
        if row is None:
            return (0.0, 0.0, item.evidence_id)
        usefulness = (
            row.relevant_to_question
            + row.directly_supports_answer
            + row.material_new_information
            - row.likely_duplicate_or_redundant
        )
        return (-usefulness, -row.primary_or_high_authority_for_question, item.evidence_id)

    return sorted(evidence, key=sort_key)


def screening_objective(
    *,
    objective: ResearchObjective | None,
    plan: ResearchPlan,
) -> str:
    if objective is not None and objective.objective.strip():
        return objective.objective.strip()
    return " ".join(need.question for need in plan.needs)


async def _ask_screen(
    client: JevSystemOne,
    *,
    payload: dict[str, Any],
    model: str,
) -> Any:
    return await client.ask(
        state=payload,
        questions=EVIDENCE_SCREEN_QUESTIONS,
        model=model,
        timeout_seconds=settings.research_jev_timeout_seconds,
    )


async def _score_one(
    client: JevSystemOne,
    *,
    objective: str,
    item: AssessableEvidence,
    slots: asyncio.Semaphore | None,
    cache: EvidenceScreenCache | None = None,
    count_relevance_call: bool = False,
) -> EvidenceJevScores | None:
    payload, input_chars, _digest = compact_evidence_item_state(
        objective=objective,
        item=item,
        max_state_chars=settings.research_jev_max_state_chars,
    )
    model = research_jev_model()
    cache_key = evidence_screen_cache_key(
        model=model,
        objective=objective,
        content_hash=item.content_hash,
        questions=EVIDENCE_SCREEN_QUESTIONS,
    )
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    try:
        if slots is None:
            result = await _ask_screen(client, payload=payload, model=model)
        else:
            async with slots:
                result = await _ask_screen(client, payload=payload, model=model)
    except Exception:  # noqa: BLE001 - shadow scores must not fail research
        if count_relevance_call:
            record_relevance_jev_call()
        return None
    if count_relevance_call:
        record_relevance_jev_call()
    try:
        scores = EvidenceJevScores(
            evidence_id=item.evidence_id,
            source_type=item.source_type,
            content_hash=item.content_hash,
            relevant_to_question=parse_noul(result.answers, "relevant_to_question"),
            directly_supports_answer=parse_noul(result.answers, "directly_supports_answer"),
            contradicts_current_evidence=parse_noul(
                result.answers, "contradicts_current_evidence"
            ),
            material_new_information=parse_noul(
                result.answers, "material_new_information"
            ),
            likely_duplicate_or_redundant=parse_noul(
                result.answers, "likely_duplicate_or_redundant"
            ),
            primary_or_high_authority_for_question=parse_noul(
                result.answers, "primary_or_high_authority_for_question"
            ),
            latency_ms=result.latency_ms,
        )
    except Exception:  # noqa: BLE001 - omit one bad score, keep the item
        return None
    if cache is not None:
        cache.put(cache_key, scores)
    record_jev_call(scores.latency_ms)
    emit_jev_evidence_scored(
        mode=research_jev_mode(),
        model=research_jev_model(),
        provider=JEV_PROVIDER,
        evidence_id=item.evidence_id,
        source_type=item.source_type,
        content_hash=item.content_hash,
        latency_ms=scores.latency_ms,
        input_chars=input_chars,
        scores={
            "relevant_to_question": scores.relevant_to_question,
            "directly_supports_answer": scores.directly_supports_answer,
            "contradicts_current_evidence": scores.contradicts_current_evidence,
            "material_new_information": scores.material_new_information,
            "likely_duplicate_or_redundant": scores.likely_duplicate_or_redundant,
            "primary_or_high_authority_for_question": (
                scores.primary_or_high_authority_for_question
            ),
        },
    )
    return scores
