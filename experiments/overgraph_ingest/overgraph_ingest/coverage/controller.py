"""Deterministic coverage v2. Classify contract is unchanged."""

from __future__ import annotations

from dataclasses import dataclass, field

from overgraph_ingest.coverage.cache import CachedAnswer
from overgraph_ingest.coverage.proof import COMPOSITE
from overgraph_ingest.coverage.state import (
    EVIDENCE_FOUND,
    NEEDS_ANALYSIS,
    NO_EVIDENCE_YET,
    UNEXAMINED,
    VERIFIED_ABSENT,
    DocumentState,
    UnitRecord,
    is_open,
    resolve_status,
)
from overgraph_ingest.jev.candidates import ClassifiedCandidate, GraphContext
from overgraph_ingest.jev.classify import Judgment, classify_candidates, expected_label
from overgraph_ingest.jev.client import JevClient
from overgraph_ingest.navigation.hop import PUNKT_RE, referenced_clause_hops, section_hops
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit

SECTION_HOP_RELATIONS = frozenset({"PREVIOUS", "SAME_SECTION", "SAME_STRUCTURE"})
TOUCHED = "touched"
FAIR = "fair"


@dataclass
class NextUnit:
    hit: SearchHit
    unit: StoredUnit
    reason: str


@dataclass
class ControllerResult:
    variant: str
    documents: dict[str, DocumentState]
    judgments: list[Judgment]
    timeline: list[dict[str, object]]
    jev_calls: int
    cache_hits: int
    hop_fetches: int
    wall_seconds: float = 0.0
    action_counts: dict[str, int] = field(default_factory=dict)


def run_controller(
    *,
    variant: str,
    ranked: list[SearchHit],
    context: GraphContext,
    gold: RetrievalGold,
    client: JevClient,
    cache: dict[str, CachedAnswer],
    question: str,
    model: str,
    timeout_seconds: float,
    concurrency: int,
    global_k: int,
    max_passes: int,
) -> ControllerResult:
    units_by_path: dict[str, list[StoredUnit]] = {}
    for unit in context.units:
        units_by_path.setdefault(unit.relative_path, []).append(unit)
    documents = {
        path: DocumentState(relative_path=path, document_units=len(group))
        for path, group in units_by_path.items()
    }
    by_key = context.by_key()
    classified: set[str] = set()
    judgments: list[Judgment] = []
    timeline: list[dict[str, object]] = []
    jev_calls = 0
    cache_hits = 0
    hop_fetches = 0

    seed = [hit for hit in ranked if hit.rank <= global_k][:global_k]
    first, cached_n, live_n = _apply_batch(
        seed,
        ["global"] * len(seed),
        documents=documents,
        context=context,
        gold=gold,
        client=client,
        cache=cache,
        classified=classified,
        question=question,
        model=model,
        timeout_seconds=timeout_seconds,
        concurrency=concurrency,
        by_key=by_key,
    )
    judgments.extend(first)
    cache_hits += cached_n
    jev_calls += live_n
    _refresh(documents, gold.proof_kind)
    _record(timeline, documents, gold, judgments, phase="global")

    for pass_index in range(1, max_passes + 1):
        nxt = select_next(
            documents,
            ranked,
            context,
            variant=variant,
            classified=classified,
            by_key=by_key,
            proof_kind=gold.proof_kind,
        )
        if not nxt:
            break
        hop_fetches += sum(1 for item in nxt if item.reason.startswith("hop:"))
        batch_hits = [item.hit for item in nxt]
        reasons = [item.reason for item in nxt]
        batch, cached_n, live_n = _apply_batch(
            batch_hits,
            reasons,
            documents=documents,
            context=context,
            gold=gold,
            client=client,
            cache=cache,
            classified=classified,
            question=question,
            model=model,
            timeout_seconds=timeout_seconds,
            concurrency=concurrency,
            by_key=by_key,
        )
        for item in nxt:
            if item.reason.startswith("hop:"):
                documents[item.hit.relative_path].hop_attempted = True
        judgments.extend(batch)
        cache_hits += cached_n
        jev_calls += live_n
        _refresh(documents, gold.proof_kind)
        _record(timeline, documents, gold, judgments, phase=f"pass_{pass_index}")
        if not any(is_open(doc) and _has_remaining(doc, ranked) for doc in documents.values()):
            break

    return ControllerResult(
        variant=variant,
        documents=documents,
        judgments=judgments,
        timeline=timeline,
        jev_calls=jev_calls,
        cache_hits=cache_hits,
        hop_fetches=hop_fetches,
    )


def select_next(
    documents: dict[str, DocumentState],
    ranked: list[SearchHit],
    context: GraphContext,
    *,
    variant: str,
    classified: set[str],
    by_key: dict[str, StoredUnit],
    proof_kind: str,
) -> list[NextUnit]:
    chosen: list[NextUnit] = []
    for path, doc in sorted(documents.items()):
        if not _should_deepen(doc, variant):
            continue
        hop = _motivated_hop(doc, context, by_key, classified, proof_kind)
        if hop is not None:
            chosen.append(hop)
            continue
        nxt = _next_ranked(path, ranked, classified)
        if nxt is not None:
            chosen.append(nxt)
    return chosen


def _should_deepen(doc: DocumentState, variant: str) -> bool:
    if not is_open(doc):
        return False
    if variant == TOUCHED:
        return doc.status in {NO_EVIDENCE_YET, NEEDS_ANALYSIS}
    return doc.status in {UNEXAMINED, NO_EVIDENCE_YET, NEEDS_ANALYSIS, "RETRIEVED"}


def _next_ranked(path: str, ranked: list[SearchHit], classified: set[str]) -> NextUnit | None:
    for hit in ranked:
        if hit.relative_path != path or hit.key in classified:
            continue
        return NextUnit(hit=hit, unit=_hit_unit_placeholder(hit), reason="in_document")
    return None


def _hit_unit_placeholder(hit: SearchHit) -> StoredUnit:
    return StoredUnit(
        hit.node_id,
        hit.key,
        hit.document_id,
        hit.relative_path,
        hit.text,
        None,
        None,
    )


def _motivated_hop(
    doc: DocumentState,
    context: GraphContext,
    by_key: dict[str, StoredUnit],
    classified: set[str],
    proof_kind: str,
) -> NextUnit | None:
    for row in doc.retrieved:
        unit = by_key.get(row.key)
        if unit is None:
            continue
        if row.predicted == "UNCERTAIN" and PUNKT_RE.search(unit.text):
            _ref, hops = referenced_clause_hops(unit, context.units, context.structures)
            for hop in hops:
                if hop.key in classified:
                    continue
                target = by_key[hop.key]
                return NextUnit(
                    hit=SearchHit(
                        target.node_id,
                        target.key,
                        0.0,
                        0,
                        target.document_id,
                        target.relative_path,
                        target.text,
                    ),
                    unit=target,
                    reason=f"hop:{hop.relation}",
                )
        if proof_kind == COMPOSITE and row.predicted == "YES":
            for hop in section_hops(unit, context.units, context.structures):
                if hop.relation not in SECTION_HOP_RELATIONS or hop.key in classified:
                    continue
                target = by_key[hop.key]
                return NextUnit(
                    hit=SearchHit(
                        target.node_id,
                        target.key,
                        0.0,
                        0,
                        target.document_id,
                        target.relative_path,
                        target.text,
                    ),
                    unit=target,
                    reason=f"hop:{hop.relation}",
                )
    return None


def _apply_batch(
    hits: list[SearchHit],
    reasons: list[str],
    *,
    documents: dict[str, DocumentState],
    context: GraphContext,
    gold: RetrievalGold,
    client: JevClient,
    cache: dict[str, CachedAnswer],
    classified: set[str],
    question: str,
    model: str,
    timeout_seconds: float,
    concurrency: int,
    by_key: dict[str, StoredUnit],
) -> tuple[list[Judgment], int, int]:
    fresh: list[ClassifiedCandidate] = []
    cached_rows: list[Judgment] = []
    reason_by_key = dict(zip((hit.key for hit in hits), reasons, strict=True))
    for hit in hits:
        if hit.key in classified:
            continue
        unit = by_key[hit.key]
        candidate = context.candidate(unit, gold, rank=hit.rank, score=hit.score)
        cached = cache.get(hit.key)
        if cached is not None:
            cached_rows.append(
                Judgment(
                    key=hit.key,
                    rank=hit.rank,
                    relative_path=hit.relative_path,
                    gold_label=candidate.gold_label,
                    expected=expected_label(candidate.gold_label),
                    predicted=cached.predicted,
                    confidence=cached.confidence,
                    latency_ms=0.0,
                    call_index=-1,
                    batch_size=1,
                    error=None,
                    text=candidate.text,
                )
            )
            classified.add(hit.key)
            continue
        fresh.append(candidate)
        classified.add(hit.key)
    live: list[Judgment] = []
    if fresh:
        live, _wall = classify_candidates(
            client,
            fresh,
            model=model,
            timeout_seconds=timeout_seconds,
            batch_size=1,
            context="none",
            concurrency=concurrency,
            question=question,
        )
    combined = cached_rows + live
    by_pred = {item.key: item for item in combined}
    for hit in hits:
        judged = by_pred.get(hit.key)
        if judged is None:
            continue
        documents[hit.relative_path].retrieved.append(
            UnitRecord(
                key=hit.key,
                predicted=judged.predicted,
                source=reason_by_key.get(hit.key, "global"),
                hop=reason_by_key.get(hit.key)
                if str(reason_by_key.get(hit.key) or "").startswith("hop:")
                else None,
                text=judged.text,
            )
        )
    return combined, len(cached_rows), len(live)


def _refresh(documents: dict[str, DocumentState], proof_kind: str) -> None:
    for doc in documents.values():
        doc.status = resolve_status(doc, proof_kind=proof_kind)


def _has_remaining(doc: DocumentState, ranked: list[SearchHit]) -> bool:
    seen = doc.retrieved_keys()
    return any(hit.relative_path == doc.relative_path and hit.key not in seen for hit in ranked)


def _record(
    timeline: list[dict[str, object]],
    documents: dict[str, DocumentState],
    gold: RetrievalGold,
    judgments: list[Judgment],
    *,
    phase: str,
) -> None:
    relevant = set(gold.relevant_documents)
    found = {
        path
        for path, doc in documents.items()
        if path in relevant and doc.yes_count()
    }
    timeline.append(
        {
            "phase": phase,
            "classified": sum(1 for doc in documents.values() for row in doc.retrieved if row.predicted),
            "jev_yes_document_recall": (len(found) / len(relevant)) if relevant else 0.0,
            "documents_found": len(found),
            "unresolved": sum(1 for doc in documents.values() if is_open(doc)),
            "unresolved_relevant": sorted(
                path for path in relevant if documents[path].status != EVIDENCE_FOUND
            ),
            "status_counts": _counts(documents),
            "judgments": len(judgments),
        }
    )


def _counts(documents: dict[str, DocumentState]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in documents.values():
        counts[doc.status] = counts.get(doc.status, 0) + 1
    return counts


def metrics_payload(result: ControllerResult, gold: RetrievalGold) -> dict[str, object]:
    relevant = set(gold.relevant_documents)
    found = [
        path
        for path, doc in result.documents.items()
        if path in relevant and doc.status == EVIDENCE_FOUND
    ]
    jev_yes = [
        path
        for path, doc in result.documents.items()
        if path in relevant and doc.yes_count()
    ]
    unresolved_relevant = [
        path
        for path in relevant
        if result.documents[path].status not in {EVIDENCE_FOUND, VERIFIED_ABSENT}
    ]
    false_negative = [
        path
        for path in relevant
        if result.documents[path].status == VERIFIED_ABSENT
    ]
    complete = next(
        (
            point
            for point in result.timeline
            if not point.get("unresolved_relevant")
            and float(point.get("jev_yes_document_recall") or 0) >= 1.0
        ),
        None,
    )
    return {
        "variant": result.variant,
        "proof_kind": gold.proof_kind,
        "jev_calls": result.jev_calls,
        "cache_hits": result.cache_hits,
        "classified": len(result.judgments),
        "hop_fetches": result.hop_fetches,
        "document_recall": (len(found) / len(relevant)) if relevant else 0.0,
        "jev_yes_document_recall": (len(jev_yes) / len(relevant)) if relevant else 0.0,
        "documents_found": len(found),
        "documents_expected": len(relevant),
        "unresolved_documents": sum(1 for doc in result.documents.values() if is_open(doc)),
        "unresolved_relevant_documents": unresolved_relevant,
        "false_negative_documents": false_negative,
        "verified_absent_relevant": false_negative,
        "first_complete_phase": None if complete is None else complete.get("phase"),
        "first_complete_classified": None if complete is None else complete.get("classified"),
        "status_counts": _counts(result.documents),
        "timeline": result.timeline,
        "would_be_jev_calls_if_uncached": result.jev_calls + result.cache_hits,
    }
