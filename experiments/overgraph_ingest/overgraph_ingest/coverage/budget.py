"""Coverage v3: per-document budget and proof-kind stop. Classify is unchanged."""

from __future__ import annotations

from overgraph_ingest.coverage.controller import (
    ControllerResult,
    NextUnit,
    SECTION_HOP_RELATIONS,
    _apply_batch,
    _counts,
    _next_ranked,
    _record,
)
from overgraph_ingest.coverage.proof import COMPOSITE, V2_BEST_JEV_YES, required_parts
from overgraph_ingest.coverage.state import (
    BUDGET_EXHAUSTED,
    EVIDENCE_FOUND,
    VERIFIED_ABSENT,
    DocumentState,
    is_open,
    resolve_status,
)
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.jev.client import JevClient
from overgraph_ingest.navigation.hop import (
    PUNKT_RE,
    child_clause_hops,
    is_heading_unit,
    referenced_clause_hops,
    section_hops,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


def run_budget_controller(
    *,
    ranked: list[SearchHit],
    context: GraphContext,
    gold: RetrievalGold,
    client: JevClient,
    cache: dict,
    question: str,
    model: str,
    timeout_seconds: float,
    concurrency: int,
    global_k: int,
    budget: int | None,
) -> ControllerResult:
    units_by_path: dict[str, list[StoredUnit]] = {}
    for unit in context.units:
        units_by_path.setdefault(unit.relative_path, []).append(unit)
    documents = {
        path: DocumentState(
            relative_path=path,
            document_units=len(group),
            required_parts=required_parts(gold, path),
        )
        for path, group in units_by_path.items()
    }
    by_key = context.by_key()
    classified: set[str] = set()
    judgments = []
    timeline: list[dict[str, object]] = []
    jev_calls = 0
    cache_hits = 0
    hop_fetches = 0
    action_counts: dict[str, int] = {}

    seed = _seed_hits(ranked, documents, global_k=global_k, budget=budget)
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
    action_counts["global"] = len(first)
    _refresh(documents, gold.proof_kind, budget)
    _record(timeline, documents, gold, judgments, phase="global")

    rounds = budget if budget is not None else 32
    for pass_index in range(1, rounds + 1):
        nxt = select_round(
            documents,
            ranked,
            context,
            classified=classified,
            by_key=by_key,
            proof_kind=gold.proof_kind,
            budget=budget,
        )
        if not nxt:
            break
        hop_fetches += sum(1 for item in nxt if item.reason.startswith("hop:"))
        for item in nxt:
            action_counts[item.reason] = action_counts.get(item.reason, 0) + 1
        batch, cached_n, live_n = _apply_batch(
            [item.hit for item in nxt],
            [item.reason for item in nxt],
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
        _refresh(documents, gold.proof_kind, budget)
        _record(timeline, documents, gold, judgments, phase=f"pass_{pass_index}")

    return ControllerResult(
        variant=f"B{budget if budget is not None else 'inf'}",
        documents=documents,
        judgments=judgments,
        timeline=timeline,
        jev_calls=jev_calls,
        cache_hits=cache_hits,
        hop_fetches=hop_fetches,
        action_counts=action_counts,
    )


def select_round(
    documents: dict[str, DocumentState],
    ranked: list[SearchHit],
    context: GraphContext,
    *,
    classified: set[str],
    by_key: dict[str, StoredUnit],
    proof_kind: str,
    budget: int | None,
) -> list[NextUnit]:
    chosen: list[NextUnit] = []
    for path, doc in sorted(documents.items()):
        if not is_open(doc) or not _under_budget(doc, budget):
            continue
        action = _select_action(
            doc,
            ranked,
            context,
            classified=classified,
            by_key=by_key,
            proof_kind=proof_kind,
        )
        if action is not None:
            chosen.append(action)
    return chosen


def _select_action(
    doc: DocumentState,
    ranked: list[SearchHit],
    context: GraphContext,
    *,
    classified: set[str],
    by_key: dict[str, StoredUnit],
    proof_kind: str,
) -> NextUnit | None:
    hop = _motivated_hop(doc, context, by_key, classified, proof_kind)
    if hop is not None:
        return hop
    return _next_ranked(doc.relative_path, ranked, classified)


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
            found = _first_unused_hop(
                referenced_clause_hops(unit, context.units, context.structures)[1],
                by_key,
                classified,
            )
            if found is not None:
                return found
        if row.predicted == "UNCERTAIN" and is_heading_unit(unit, context.structures):
            found = _first_unused_hop(
                child_clause_hops(unit, context.units, context.structures),
                by_key,
                classified,
            )
            if found is not None:
                return found
        if proof_kind == COMPOSITE and row.predicted == "YES":
            hops = [
                hop
                for hop in section_hops(unit, context.units, context.structures)
                if hop.relation in SECTION_HOP_RELATIONS
            ]
            found = _first_unused_hop(hops, by_key, classified)
            if found is not None:
                return found
    return None


def _first_unused_hop(hops, by_key: dict[str, StoredUnit], classified: set[str]) -> NextUnit | None:
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
    return None


def _seed_hits(
    ranked: list[SearchHit],
    documents: dict[str, DocumentState],
    *,
    global_k: int,
    budget: int | None,
) -> list[SearchHit]:
    chosen: list[SearchHit] = []
    used: dict[str, int] = {}
    for hit in ranked:
        if hit.rank > global_k:
            break
        taken = used.get(hit.relative_path, 0)
        if budget is not None and taken >= budget:
            continue
        chosen.append(hit)
        used[hit.relative_path] = taken + 1
    return chosen


def _under_budget(doc: DocumentState, budget: int | None) -> bool:
    return budget is None or doc.classified_count() < budget


def _refresh(documents: dict[str, DocumentState], proof_kind: str, budget: int | None) -> None:
    for doc in documents.values():
        doc.status = resolve_status(doc, proof_kind=proof_kind, budget=budget)


def budget_metrics(result: ControllerResult, gold: RetrievalGold, *, budget: int | None) -> dict[str, object]:
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
    budget_exhausted = [
        path
        for path, doc in result.documents.items()
        if doc.status == BUDGET_EXHAUSTED
    ]
    v2_target = V2_BEST_JEV_YES.get(gold.id)
    jev_yes_recall = (len(jev_yes) / len(relevant)) if relevant else 0.0
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
        "budget": budget,
        "variant": result.variant,
        "proof_kind": gold.proof_kind,
        "jev_calls": result.jev_calls,
        "cache_hits": result.cache_hits,
        "classified": len(result.judgments),
        "hop_fetches": result.hop_fetches,
        "document_recall": (len(found) / len(relevant)) if relevant else 0.0,
        "jev_yes_document_recall": jev_yes_recall,
        "documents_found": len(found),
        "documents_expected": len(relevant),
        "unresolved_documents": sum(1 for doc in result.documents.values() if not is_resolved_or_absent(doc)),
        "unresolved_relevant_documents": unresolved_relevant,
        "false_negative_documents": false_negative,
        "budget_exhausted_documents": len(budget_exhausted),
        "budget_exhausted_relevant": [path for path in budget_exhausted if path in relevant],
        "matched_v2_recall": v2_target is not None and jev_yes_recall + 1e-9 >= v2_target,
        "v2_target_jev_yes": v2_target,
        "first_complete_phase": None if complete is None else complete.get("phase"),
        "first_complete_classified": None if complete is None else complete.get("classified"),
        "status_counts": _counts(result.documents),
        "composite_groups": _composite_groups(result.documents, gold),
        "timeline": result.timeline,
        "would_be_jev_calls_if_uncached": result.jev_calls + result.cache_hits,
        "action_counts": result.action_counts,
    }


def is_resolved_or_absent(doc: DocumentState) -> bool:
    return doc.status in {EVIDENCE_FOUND, VERIFIED_ABSENT}


def _composite_groups(documents: dict[str, DocumentState], gold: RetrievalGold) -> list[dict[str, object]]:
    rows = []
    for group in gold.coverage_groups:
        doc = documents[group.relative_path]
        return_row = {
            "relative_path": group.relative_path,
            "required": len(group.contains),
            "found": doc.parts_found(),
            "complete": doc.parts_complete(),
            "status": doc.status,
            "yes_count": doc.yes_count(),
        }
        rows.append(return_row)
    return rows
