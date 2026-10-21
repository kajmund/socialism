"""BM25 comparison arms, frozen rankings, metrics, and manifest.

Step A is model-free: dense/sparse use the already-stored vectors and the
same query embedding is reused in every arm. Gold is loaded only for scoring.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from statistics import mean

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.metrics import environment_metadata
from overgraph_ingest.pipeline import _peak_rss_bytes
from overgraph_ingest.retrieval.bm25 import (
    ANALYZERS,
    Bm25Index,
    Bm25Profile,
    build_index,
    build_profile,
    hydrate_hits,
    units_metadata,
)
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evaluate import judge_units
from overgraph_ingest.retrieval.evidence_gold import (
    ANSWERABLE,
    NEGATIVE,
    NOT_EVALUATED,
    CellEvidenceGold,
    EvidenceGroup,
    ceiling_at,
    document_gold_without_evidence,
    first_group_ranks,
    group_evidence_keys,
    inventory_groups,
    load_question_gold,
    required_group_count,
    validate_cell_gold,
    validate_groups_against_units,
)
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.gold_map import locate_contains
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import (
    RRF_K,
    SearchHit,
    encode_query,
    exhaustive_rank,
    rrf_fuse,
    search_units,
)

ARM_IDS = (
    "dense",
    "sparse",
    "hybrid_current",
    "hybrid_rrf_control",
    "hybrid_rrf_positive",
    "bm25",
    "dense_bm25",
)
GLOBAL_KS = (5, 10, 20, 50)
LOCAL_KS = (1, 3, 5, 10)
BRANCH_DEPTH = 100
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 0
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_OVERLAY = DEFAULT_GOLD_DIR / "question_gold" / "evidence-groups-v1.json"
DEFAULT_INDEX_DIR = ROOT / "data" / "bm25-index"


@dataclass(frozen=True)
class FrozenQuery:
    query_id: str
    query: str
    scope: str
    relative_path: str | None
    branches: dict[str, list[SearchHit]]
    arms: dict[str, list[SearchHit]]
    branch_meta: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class GroupObservation:
    cluster: str
    left: float
    right: float


def run_bm25_experiment(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    question_gold_path: Path | None = None,
    scope: str = "both",
    analyzers: tuple[str, ...] = ("sv_stem_v1",),
    index_dir: Path | None = None,
    branch_depth: int = BRANCH_DEPTH,
    global_ks: tuple[int, ...] = GLOBAL_KS,
    local_ks: tuple[int, ...] = LOCAL_KS,
    repeats: int = 20,
    units: list[StoredUnit] | None = None,
    golds: list[RetrievalGold] | None = None,
    cells: list[CellEvidenceGold] | None = None,
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]] | None = None,
    bm25_indexes: dict[str, Bm25Index] | None = None,
) -> dict[str, object]:
    if scope not in {"global", "document", "both"}:
        raise ValueError(f"unsupported BM25 scope {scope!r}")
    if not analyzers:
        raise ValueError("at least one BM25 analyzer is required")
    for analyzer in analyzers:
        if analyzer not in ANALYZERS:
            raise ValueError(f"unsupported BM25 analyzer {analyzer!r}")
    loaded_units = units if units is not None else _load_units(config)
    db_manifest_start = _file_hash(config.db_path / "manifest.current")
    gold_rows = golds if golds is not None else _load_golds(gold_dir)
    if cells is not None:
        cell_rows = list(cells)
    elif scope == "global":
        cell_rows = []
    else:
        overlay = question_gold_path
        if overlay is None and DEFAULT_OVERLAY.is_file():
            overlay = DEFAULT_OVERLAY
        cell_rows = load_question_gold(overlay)
    validate_cell_gold(cell_rows, loaded_units)
    query_timings: dict[str, float] = {}
    if queries is None:
        query_vectors, query_timings = _encode_all_queries(
            config, loaded_units, gold_rows, cell_rows
        )
    else:
        query_vectors = queries
    profile_payloads: dict[str, object] = {}
    for analyzer in analyzers:
        profile = build_profile(analyzer)
        bm25 = (bm25_indexes or {}).get(analyzer)
        if bm25 is None:
            bm25 = build_index(
                loaded_units,
                profile=profile,
                index_dir=index_dir or DEFAULT_INDEX_DIR,
                rebuild=False,
            )
        profile_payloads[analyzer] = _run_one_profile(
            config,
            units=loaded_units,
            golds=gold_rows,
            cells=cell_rows,
            queries=query_vectors,
            bm25=bm25,
            profile=profile,
            scope=scope,
            branch_depth=branch_depth,
            global_ks=global_ks,
            local_ks=local_ks,
            repeats=repeats,
            query_timings=query_timings,
        )
    db_manifest_end = _file_hash(config.db_path / "manifest.current")
    if db_manifest_start != db_manifest_end:
        raise RuntimeError(
            "OverGraph manifest changed during the BM25 measurement; "
            "the run did not read an immutable snapshot"
        )
    manifest = _manifest(
        config,
        units=loaded_units,
        golds=gold_rows,
        cells=cell_rows,
        profiles=profile_payloads,
        gold_dir=gold_dir,
        scope=scope,
        branch_depth=branch_depth,
        global_ks=global_ks,
        local_ks=local_ks,
        repeats=repeats,
    )
    manifest["corpus"]["db_manifest_hash_start"] = db_manifest_start
    manifest["corpus"]["db_manifest_hash_end"] = db_manifest_end
    manifest["corpus"]["db_unchanged"] = True
    payload: dict[str, object] = {
        "operation": "bm25_compare",
        "experiment": "tantivy_bm25_v1",
        "status": "completed",
        "claim_scope": "improved_retrieval_only",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "profiles": profile_payloads,
        "manifest": manifest,
        "limitations": _limitations(),
        "answer_test": {"status": "not_run"},
        "paging": {"status": "not_run"},
    }
    payload["summary"] = _summary(profile_payloads)
    payload["verdict"] = _verdict(payload)
    return payload


def _run_one_profile(
    config: RetrievalConfig,
    *,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    cells: list[CellEvidenceGold],
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]],
    bm25: Bm25Index,
    profile: Bm25Profile,
    scope: str,
    branch_depth: int,
    global_ks: tuple[int, ...],
    local_ks: tuple[int, ...],
    repeats: int,
    query_timings: dict[str, float],
) -> dict[str, object]:
    result: dict[str, object] = {
        "query_encoding": {
            "seconds": sum(query_timings.values()),
            "queries": len(query_timings),
            "per_query": query_timings,
        },
        "analyzer": profile.describe(),
        "bm25_index": bm25.manifest,
        "global": {"status": "not_run"},
        "document": {"status": "not_run"},
    }
    global_payload = None
    document_payload = None
    if scope in {"global", "both"}:
        global_payload = _run_global(
            config,
            units=units,
            golds=golds,
            queries=queries,
            bm25=bm25,
            profile=profile,
            branch_depth=branch_depth,
            ks=global_ks,
            repeats=repeats,
            query_timings=query_timings,
        )
        result["global"] = global_payload
    if scope in {"document", "both"}:
        document_payload = _run_document(
            units=units,
            cells=cells,
            queries=queries,
            bm25=bm25,
            profile=profile,
            ks=local_ks,
            repeats=repeats,
            query_timings=query_timings,
        )
        result["document"] = document_payload
    result["comparisons"] = _comparisons(global_payload, document_payload)
    return result


def _run_global(
    config: RetrievalConfig,
    *,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]],
    bm25: Bm25Index,
    profile: Bm25Profile,
    branch_depth: int,
    ks: tuple[int, ...],
    repeats: int,
    query_timings: dict[str, float],
) -> dict[str, object]:
    dimension = _dimension(config, units)
    db = open_database(config.db_path, dimension)
    try:
        rows = []
        for gold in golds:
            dense_query, sparse_query = queries[f"global:{gold.id}"]
            frozen = _global_frozen(
                db,
                units,
                gold=gold,
                dense_query=dense_query,
                sparse_query=sparse_query,
                bm25=bm25,
                profile=profile,
                branch_depth=branch_depth,
                fusion_mode=config.fusion_mode,
            )
            groups = inventory_groups(gold)
            validate_groups_against_units(
                tuple(group for values in groups.values() for group in values), units
            )
            relevant, negatives, absent = judge_units(units, gold)
            group_keys = group_evidence_keys(
                tuple(group for values in groups.values() for group in values), units
            )
            arms = {}
            for arm in ARM_IDS:
                arms[arm] = _score_inventory(
                    arm,
                    frozen.arms[arm],
                    groups=groups,
                    relevant=group_keys or relevant,
                    negatives=negatives,
                    absent=absent,
                    gold=gold,
                    ks=ks,
                    branch_ranks=frozen.branch_meta,
                )
            rows.append(
                {
                    "gold_id": gold.id,
                    "split": gold.split,
                    "query": gold.query,
                    "units": len(units),
                    "documents_with_evidence": len(groups),
                    "documents_expected": len(gold.relevant_documents),
                    "document_gold_without_evidence": list(
                        document_gold_without_evidence(gold)
                    ),
                    "required_groups": required_group_count(groups),
                    "absent_from_graph": [item.__dict__ for item in absent],
                    "hard_negatives": sorted(negatives),
                    "branch_meta": frozen.branch_meta,
                    "arms": arms,
                }
            )
    finally:
        db.close()
    latency = _measure_global_latency(
        config,
        units=units,
        golds=golds,
        queries=queries,
        bm25=bm25,
        profile=profile,
        branch_depth=branch_depth,
        repeats=repeats,
        query_timings=query_timings,
    )
    return {
        "status": "completed",
        "ks": list(ks),
        "branch_depth": branch_depth,
        "rows": rows,
        "macro": _inventory_macro(rows, ks),
        "twenty_vs_fifty": _twenty_vs_fifty(rows, ks),
        "latency": latency,
    }


def _run_document(
    *,
    units: list[StoredUnit],
    cells: list[CellEvidenceGold],
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]],
    bm25: Bm25Index,
    profile: Bm25Profile,
    ks: tuple[int, ...],
    repeats: int,
    query_timings: dict[str, float],
) -> dict[str, object]:
    by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.relative_path].append(unit)
    rows = []
    for cell in cells:
        local = by_path.get(cell.relative_path, [])
        if not local:
            raise RuntimeError(f"question gold document is not in the graph: {cell.relative_path}")
        dense_query, sparse_query = queries[f"doc:{cell.question_id}"]
        frozen = _document_frozen(
            local,
            cell=cell,
            dense_query=dense_query,
            sparse_query=sparse_query,
            bm25=bm25,
            profile=profile,
        )
        relevant = group_evidence_keys(cell.groups, local)
        arms = {}
        for arm in ARM_IDS:
            arms[arm] = _score_cell(
                arm,
                frozen.arms[arm],
                groups=cell.groups,
                relevant=relevant,
                ks=ks,
                branch_meta=frozen.branch_meta,
            )
        rows.append(
            {
                "question_id": cell.question_id,
                "relative_path": cell.relative_path,
                "split": cell.split,
                "answerability": cell.answerability,
                "positive_property": cell.positive_property,
                "required_groups": len(cell.groups),
                "document_units": len(local),
                "branch_meta": frozen.branch_meta,
                "arms": arms,
            }
        )
    return {
        "status": "completed",
        "ks": list(ks),
        "branch_depth": "all_document_units",
        "rows": rows,
        "macro": _cell_macro(rows, ks),
        "latency": _measure_document_latency(
            units=units,
            cells=cells,
            queries=queries,
            bm25=bm25,
            profile=profile,
            repeats=repeats,
            query_timings=query_timings,
        ),
    }


def _global_frozen(
    db,
    units: list[StoredUnit],
    *,
    gold: RetrievalGold,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    bm25: Bm25Index,
    profile: Bm25Profile,
    branch_depth: int,
    fusion_mode: str,
) -> FrozenQuery:
    dense = _dedupe_branch(
        search_units(
            db,
            units,
            mode="dense",
            k=branch_depth,
            dense_query=dense_query,
            sparse_query=sparse_query,
        )
    )
    sparse = _dedupe_branch(
        search_units(
            db,
            units,
            mode="sparse",
            k=branch_depth,
            dense_query=dense_query,
            sparse_query=sparse_query,
        )
    )
    hybrid_current = _dedupe_branch(
        search_units(
            db,
            units,
            mode="hybrid",
            k=branch_depth,
            dense_query=dense_query,
            sparse_query=sparse_query,
            fusion_mode=fusion_mode,
        )
    )
    sparse_positive = [hit for hit in sparse if hit.score > 0]
    bm25_search = bm25.search(gold.query, limit=branch_depth)
    bm25_hits = _dedupe_branch(hydrate_hits(bm25, bm25_search.hits, by_key=_by_key(units)))
    arms = {
        "dense": dense,
        "sparse": sparse,
        "hybrid_current": hybrid_current,
        "hybrid_rrf_control": rrf_fuse([dense, sparse]),
        "hybrid_rrf_positive": rrf_fuse([dense, sparse_positive]),
        "bm25": bm25_hits,
        "dense_bm25": rrf_fuse([dense, bm25_hits]),
    }
    return FrozenQuery(
        query_id=gold.id,
        query=gold.query,
        scope="global",
        relative_path=None,
        branches={"dense": dense, "sparse": sparse, "bm25": bm25_hits},
        arms=arms,
        branch_meta={
            "dense": _ranks(dense),
            "sparse": _ranks(sparse),
            "bm25": _ranks(bm25_hits),
            "dense_scores": _scores(dense),
            "sparse_scores": _scores(sparse),
            "bm25_scores": _scores(bm25_hits),
            "sparse_positive_count": len(sparse_positive),
            "sparse_zero_score_count": len(sparse) - len(sparse_positive),
            "bm25_terms": list(bm25_search.terms),
            "bm25_tie": bm25_search.tie.__dict__,
            "bm25_empty": not bm25_hits,
        },
    )


def _document_frozen(
    local: list[StoredUnit],
    *,
    cell: CellEvidenceGold,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    bm25: Bm25Index,
    profile: Bm25Profile,
) -> FrozenQuery:
    dense = _dedupe_branch(
        exhaustive_rank(
            local,
            mode="dense",
            dense_query=dense_query,
            sparse_query=sparse_query,
        )
    )
    sparse = _dedupe_branch(
        exhaustive_rank(
            local,
            mode="sparse",
            dense_query=dense_query,
            sparse_query=sparse_query,
        )
    )
    hybrid_current = rrf_fuse([dense, sparse])
    sparse_positive = [hit for hit in sparse if hit.score > 0]
    document_id = local[0].document_id
    bm25_search = bm25.search(
        _query_for_cell(cell),
        limit=max(len(local), 1),
        document_id=document_id,
    )
    bm25_hits = _dedupe_branch(hydrate_hits(bm25, bm25_search.hits, by_key=_by_key(local)))
    arms = {
        "dense": dense,
        "sparse": sparse,
        "hybrid_current": hybrid_current,
        "hybrid_rrf_control": rrf_fuse([dense, sparse]),
        "hybrid_rrf_positive": rrf_fuse([dense, sparse_positive]),
        "bm25": bm25_hits,
        "dense_bm25": rrf_fuse([dense, bm25_hits]),
    }
    return FrozenQuery(
        query_id=f"{cell.question_id}:{cell.relative_path}",
        query=_query_for_cell(cell),
        scope="document",
        relative_path=cell.relative_path,
        branches={"dense": dense, "sparse": sparse, "bm25": bm25_hits},
        arms=arms,
        branch_meta={
            "dense": _ranks(dense),
            "sparse": _ranks(sparse),
            "bm25": _ranks(bm25_hits),
            "dense_scores": _scores(dense),
            "sparse_scores": _scores(sparse),
            "bm25_scores": _scores(bm25_hits),
            "sparse_positive_count": len(sparse_positive),
            "sparse_zero_score_count": len(sparse) - len(sparse_positive),
            "bm25_terms": list(bm25_search.terms),
            "bm25_tie": bm25_search.tie.__dict__,
            "bm25_empty": not bm25_hits,
            "scope": "document",
            "document_id": document_id,
        },
    )


def _query_for_cell(cell: CellEvidenceGold) -> str:
    from overgraph_ingest.tabular.gold import USER_QUESTIONS

    return USER_QUESTIONS[cell.question_id]


def _score_inventory(
    arm: str,
    hits: list[SearchHit],
    *,
    groups: dict[str, tuple[EvidenceGroup, ...]],
    relevant: set[str],
    negatives: set[str],
    absent: list,
    gold: RetrievalGold,
    ks: tuple[int, ...],
    branch_ranks: dict[str, object],
) -> dict[str, object]:
    all_groups = tuple(group for values in groups.values() for group in values)
    at_k = {}
    for k in ks:
        at_k[str(k)] = _inventory_metrics(
            hits,
            groups=groups,
            all_groups=all_groups,
            relevant=relevant,
            negatives=negatives,
            absent=absent,
            k=k,
            branch_ranks=branch_ranks,
        )
    return {
        "arm": arm,
        "at_k": at_k,
        "k_to_90": _k_to(hits, all_groups, threshold=0.9, complete=False),
        "k_to_100": _k_to(hits, all_groups, threshold=1.0, complete=False),
        "k_to_90_complete": _k_to(hits, all_groups, threshold=0.9, complete=True),
        "k_to_100_complete": _k_to(hits, all_groups, threshold=1.0, complete=True),
        "evaluated_depth": len(hits),
        "candidates": [
            _hit_payload(hit, relevant, negatives, branch_ranks)
            for hit in hits[:50]
        ],
    }


def _score_cell(
    arm: str,
    hits: list[SearchHit],
    *,
    groups: tuple[EvidenceGroup, ...],
    relevant: set[str],
    ks: tuple[int, ...],
    branch_meta: dict[str, object],
) -> dict[str, object]:
    at_k = {}
    for k in ks:
        at_k[str(k)] = _cell_metrics(hits, groups=groups, relevant=relevant, k=k)
    return {
        "arm": arm,
        "at_k": at_k,
        "k_to_90": _k_to_cell(hits, groups, threshold=0.9),
        "k_to_100": _k_to_cell(hits, groups, threshold=1.0),
        "evaluated_depth": len(hits),
        "candidates": [
            _hit_payload(hit, relevant, set(), branch_meta)
            for hit in (hits if arm == "dense_bm25" else hits[:20])
        ],
    }


def _inventory_metrics(
    hits: list[SearchHit],
    *,
    groups: dict[str, tuple[EvidenceGroup, ...]],
    all_groups: tuple[EvidenceGroup, ...],
    relevant: set[str],
    negatives: set[str],
    absent: list,
    k: int,
    branch_ranks: dict[str, object],
) -> dict[str, object]:
    top = hits[:k]
    covered = first_group_ranks(all_groups, top)
    covered_ids = set(covered)
    docs_with_groups = len(groups)
    covered_docs = {
        path
        for path, values in groups.items()
        if any(group.id in covered_ids for group in values)
    }
    complete_docs = {
        path
        for path, values in groups.items()
        if values and all(group.id in covered_ids for group in values)
    }
    relevant_hits = [hit for hit in top if hit.key in relevant]
    gains = _group_gains(top, all_groups)
    return {
        "arm": "",
        "k": k,
        "retrieved": len(top),
        "relevant_in_top": len(relevant_hits),
        "precision": (len(relevant_hits) / len(top)) if top else 0.0,
        "hit": 1.0 if covered_ids else 0.0,
        "evidence_recall": (len(covered_ids) / len(all_groups)) if all_groups else None,
        "complete_evidence": (len(complete_docs) / docs_with_groups) if docs_with_groups else None,
        "documents_with_groups": docs_with_groups,
        "documents_found": len(covered_docs),
        "document_recall": (len(covered_docs) / docs_with_groups) if docs_with_groups else None,
        "documents_expected": len(groups),
        "mrr": _mrr(covered.values()),
        "ndcg": _ndcg(gains, len(all_groups), k),
        "first_group_rank": min(covered.values()) if covered else None,
        "hard_negatives_in_topk": sum(1 for hit in top if hit.key in negatives),
        "hard_negative_ranks": [
            {"key": hit.key, "rank": hit.rank, "relative_path": hit.relative_path}
            for hit in top
            if hit.key in negatives
        ],
        "absent": [item.__dict__ for item in absent],
        "groups_covered": sorted(covered_ids),
        "groups_missing": sorted(group.id for group in all_groups if group.id not in covered_ids),
        "documents_covered": sorted(covered_docs),
        "documents_complete": sorted(complete_docs),
        "hits": [_hit_payload(hit, relevant, negatives, branch_ranks) for hit in top],
    }


def _cell_metrics(
    hits: list[SearchHit],
    *,
    groups: tuple[EvidenceGroup, ...],
    relevant: set[str],
    k: int,
) -> dict[str, object]:
    top = hits[:k]
    covered = first_group_ranks(groups, top)
    covered_ids = set(covered)
    relevant_hits = [hit for hit in top if hit.key in relevant]
    gains = _group_gains(top, groups)
    return {
        "k": k,
        "retrieved": len(top),
        "relevant_in_top": len(relevant_hits),
        "precision": (len(relevant_hits) / len(top)) if top else 0.0,
        "hit": 1.0 if covered_ids else 0.0,
        "evidence_recall": (len(covered_ids) / len(groups)) if groups else None,
        "complete_evidence": 1.0 if groups and len(covered_ids) == len(groups) else (0.0 if groups else None),
        "mrr": _mrr(covered.values()),
        "ndcg": _ndcg(gains, len(groups), k),
        "first_group_rank": min(covered.values()) if covered else None,
        "groups_covered": sorted(covered_ids),
        "groups_missing": sorted(group.id for group in groups if group.id not in covered_ids),
        "hits": [_hit_payload(hit, relevant, set(), {}) for hit in top],
    }


def _group_gains(hits: list[SearchHit], groups: tuple[EvidenceGroup, ...]) -> list[float]:
    seen: set[str] = set()
    gains: list[float] = []
    for hit in hits:
        newly = False
        for group in groups:
            if group.id in seen:
                continue
            if any(_hit_matches(hit, alt) for alt in group.alternatives):
                seen.add(group.id)
                newly = True
        gains.append(1.0 if newly else 0.0)
    return gains


def _ndcg(gains: list[float], relevant_count: int, k: int) -> float:
    if not gains or relevant_count <= 0:
        return 0.0
    ideal = [1.0] * min(relevant_count, k, len(gains))
    dcg = sum(gain / math.log2(index + 1) for index, gain in enumerate(gains, start=1))
    idcg = sum(gain / math.log2(index + 1) for index, gain in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def _mrr(ranks) -> float:
    first = min(ranks, default=None)
    return (1.0 / first) if first else 0.0


def _k_to(
    hits: list[SearchHit],
    groups: tuple[EvidenceGroup, ...],
    *,
    threshold: float,
    complete: bool,
) -> dict[str, object]:
    total = len(groups)
    if total == 0:
        return {"status": "not_evaluated", "value": None, "evaluated_depth": len(hits)}
    for k in range(1, len(hits) + 1):
        covered = first_group_ranks(groups, hits[:k])
        if complete:
            value = 1.0 if len(covered) == total else len(covered) / total
        else:
            value = len(covered) / total
        if value >= threshold:
            return {"status": "reached", "value": k, "evaluated_depth": len(hits)}
    return {"status": "not_reached", "value": None, "evaluated_depth": len(hits)}


def _k_to_cell(
    hits: list[SearchHit],
    groups: tuple[EvidenceGroup, ...],
    *,
    threshold: float,
) -> dict[str, object]:
    return _k_to(hits, groups, threshold=threshold, complete=False)


def _hit_payload(
    hit: SearchHit,
    relevant: set[str],
    negatives: set[str],
    branch_meta: dict[str, object],
) -> dict[str, object]:
    label = "relevant" if hit.key in relevant else "hard_negative" if hit.key in negatives else "other"
    branch = {}
    for name in ("dense", "sparse", "bm25"):
        ranks = branch_meta.get(name)
        if isinstance(ranks, dict) and hit.key in ranks:
            scores = branch_meta.get(f"{name}_scores")
            branch[name] = {
                "rank": ranks[hit.key],
                "score": (scores or {}).get(hit.key) if isinstance(scores, dict) else None,
            }
    return {
        "rank": hit.rank,
        "key": hit.key,
        "relative_path": hit.relative_path,
        "document_id": hit.document_id,
        "score": hit.score,
        "label": label,
        "branch": branch,
    }


def _ranks(hits: list[SearchHit]) -> dict[str, int]:
    return {hit.key: hit.rank for hit in hits}


def _scores(hits: list[SearchHit]) -> dict[str, float]:
    return {hit.key: hit.score for hit in hits}


def _hit_matches(hit: SearchHit, alternative) -> bool:
    if hit.relative_path != alternative.relative_path:
        return False
    return bool(locate_contains(hit.text, alternative.contains))


def _dedupe_branch(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[str] = set()
    result: list[SearchHit] = []
    for hit in hits:
        if hit.key in seen:
            continue
        seen.add(hit.key)
        result.append(
            SearchHit(
                node_id=hit.node_id,
                key=hit.key,
                score=hit.score,
                rank=len(result) + 1,
                document_id=hit.document_id,
                relative_path=hit.relative_path,
                text=hit.text,
            )
        )
    return result


def _by_key(units: list[StoredUnit]) -> dict[str, StoredUnit]:
    return {unit.key: unit for unit in units}


def _load_units(config: RetrievalConfig) -> list[StoredUnit]:
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    db = open_database(config.db_path, dimension)
    try:
        return load_published_units(GraphWriter(db, batch_size=config.write_batch_size))
    finally:
        db.close()


def _load_golds(gold_dir: Path | None) -> list[RetrievalGold]:
    return load_gold_suite(gold_dir or DEFAULT_GOLD_DIR)


def _encode_all_queries(
    config: RetrievalConfig,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    cells: list[CellEvidenceGold],
) -> tuple[dict[str, tuple[list[float], list[tuple[int, float]]]], dict[str, float]]:
    if any(unit.dense is None or unit.sparse is None for unit in units):
        raise RuntimeError("TextUnits are missing vectors; rerun with --embed")
    dimension = _dimension(config, units)
    dense = _dense_encoder(config, dimension)
    sparse = LexicalSparseEncoder()
    sparse.fit([unit.text for unit in units])
    encoded: dict[str, tuple[list[float], list[tuple[int, float]]]] = {}
    timings: dict[str, float] = {}
    for gold in golds:
        key = f"global:{gold.id}"
        started = _now()
        encoded[key] = encode_query(gold.query, dense=dense, sparse=sparse)
        timings[key] = _now() - started
    from overgraph_ingest.tabular.gold import USER_QUESTIONS

    for cell in cells:
        question = USER_QUESTIONS[cell.question_id]
        key = f"doc:{cell.question_id}"
        if key not in encoded:
            started = _now()
            encoded[key] = encode_query(question, dense=dense, sparse=sparse)
            timings[key] = _now() - started
    return encoded, timings


def _dimension(config: RetrievalConfig, units: list[StoredUnit]) -> int:
    if config.dense_dimension is not None:
        return config.dense_dimension
    if units and units[0].dense:
        return len(units[0].dense)
    return 3072


def _measure_global_latency(
    config: RetrievalConfig,
    *,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]],
    bm25: Bm25Index,
    profile: Bm25Profile,
    branch_depth: int,
    repeats: int,
    query_timings: dict[str, float],
) -> dict[str, object]:
    rows = []
    dimension = _dimension(config, units)
    by_key = _by_key(units)
    db = open_database(config.db_path, dimension)
    try:
        for gold in golds:
            dense_query, sparse_query = queries[f"global:{gold.id}"]
            terms = bm25.analyze(gold.query)
            stages = {
                "query_analysis": [],
                "dense_engine": [],
                "sparse_engine": [],
                "bm25": [],
                "fusion": [],
                "hydrate": [],
            }
            for _ in range(repeats):
                started = _now()
                bm25.analyze(gold.query)
                stages["query_analysis"].append(_now() - started)

                started = _now()
                dense = search_units(
                    db,
                    units,
                    mode="dense",
                    k=branch_depth,
                    dense_query=dense_query,
                    sparse_query=sparse_query,
                )
                stages["dense_engine"].append(_now() - started)

                started = _now()
                search_units(
                    db,
                    units,
                    mode="sparse",
                    k=branch_depth,
                    dense_query=dense_query,
                    sparse_query=sparse_query,
                )
                stages["sparse_engine"].append(_now() - started)

                started = _now()
                bm25_result = bm25.search(gold.query, limit=branch_depth, terms=terms)
                stages["bm25"].append(_now() - started)

                started = _now()
                hydrated = hydrate_hits(bm25, bm25_result.hits, by_key=by_key)
                stages["hydrate"].append(_now() - started)

                started = _now()
                rrf_fuse([dense, hydrated])
                stages["fusion"].append(_now() - started)
            retrieval = sum(_stats_mean(values) for values in stages.values())
            query_encode = float(query_timings.get(f"global:{gold.id}") or 0.0)
            rows.append(
                {
                    "gold_id": gold.id,
                    "stages": {name: _stats(values) for name, values in stages.items()},
                    "retrieval_seconds": retrieval,
                    "query_encode_seconds": query_encode,
                    "end_to_end_seconds": retrieval + query_encode,
                    "engine": "dense and sparse OverGraph; bm25 Tantivy",
                }
            )
    finally:
        db.close()
    return {
        "repeats": repeats,
        "sample_policy": "all_global_golds",
        "rows": rows,
        "index_build": bm25.manifest.get("index"),
        "latency_scope": (
            "Warm retrieval stages plus one measured query encoding. "
            "End-to-end is their sum; no model call is hidden."
        ),
    }


def _measure_document_latency(
    *,
    units: list[StoredUnit],
    cells: list[CellEvidenceGold],
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]],
    bm25: Bm25Index,
    profile: Bm25Profile,
    repeats: int,
    query_timings: dict[str, float],
) -> dict[str, object]:
    by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.relative_path].append(unit)
    seen_questions: set[str] = set()
    rows = []
    for cell in cells:
        if cell.question_id in seen_questions:
            continue
        seen_questions.add(cell.question_id)
        local = by_path.get(cell.relative_path, [])
        if not local:
            continue
        dense_query, sparse_query = queries[f"doc:{cell.question_id}"]
        by_key = _by_key(local)
        terms = bm25.analyze(_query_for_cell(cell))
        stages = {
            "query_analysis": [],
            "dense_python": [],
            "sparse_python": [],
            "bm25": [],
            "fusion": [],
            "hydrate": [],
        }
        for _ in range(repeats):
            started = _now()
            bm25.analyze(_query_for_cell(cell))
            stages["query_analysis"].append(_now() - started)

            started = _now()
            dense = exhaustive_rank(
                local,
                mode="dense",
                dense_query=dense_query,
                sparse_query=sparse_query,
            )
            stages["dense_python"].append(_now() - started)

            started = _now()
            exhaustive_rank(
                local,
                mode="sparse",
                dense_query=dense_query,
                sparse_query=sparse_query,
            )
            stages["sparse_python"].append(_now() - started)

            started = _now()
            bm25_result = bm25.search(
                _query_for_cell(cell),
                limit=max(len(local), 1),
                document_id=local[0].document_id,
                terms=terms,
            )
            stages["bm25"].append(_now() - started)

            started = _now()
            hydrated = hydrate_hits(bm25, bm25_result.hits, by_key=by_key)
            stages["hydrate"].append(_now() - started)

            started = _now()
            rrf_fuse([dense, hydrated])
            stages["fusion"].append(_now() - started)
        retrieval = sum(_stats_mean(values) for values in stages.values())
        query_encode = float(query_timings.get(f"doc:{cell.question_id}") or 0.0)
        rows.append(
            {
                "question_id": cell.question_id,
                "relative_path": cell.relative_path,
                "stages": {name: _stats(values) for name, values in stages.items()},
                "retrieval_seconds": retrieval,
                "query_encode_seconds": query_encode,
                "end_to_end_seconds": retrieval + query_encode,
                "label": "python_doc_local_not_engine_latency",
            }
        )
    return {
        "repeats": repeats,
        "sample_policy": "first_cell_per_question",
        "rows": rows,
        "index_build": bm25.manifest.get("index"),
        "latency_scope": (
            "Document-local dense/sparse are Python rankings, not engine latency. "
            "Query encoding is separate; end-to-end is their sum."
        ),
    }


def _stats_mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    from overgraph_ingest.metrics import percentile

    return {
        "count": len(values),
        "mean": mean(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "min": min(values),
        "max": max(values),
    }


def _now() -> float:
    import time

    return time.perf_counter()


def _inventory_macro(rows: list[dict[str, object]], ks: tuple[int, ...]) -> dict[str, object]:
    out: dict[str, object] = {}
    for arm in ARM_IDS:
        at_k = {}
        for k in ks:
            values = [row["arms"][arm]["at_k"][str(k)] for row in rows]
            key = str(k)
            at_k[key] = {
                "document_recall": _mean_optional([v["document_recall"] for v in values]),
                "evidence_recall": _mean_optional([v["evidence_recall"] for v in values]),
                "complete_evidence": _mean_optional([v["complete_evidence"] for v in values]),
                "ndcg": _mean_optional([v["ndcg"] for v in values]),
                "mrr": _mean_optional([v["mrr"] for v in values]),
                "precision": _mean_optional([v["precision"] for v in values]),
                "hit": _mean_optional([v["hit"] for v in values]),
                "hard_negatives_in_topk": _mean_optional(
                    [v["hard_negatives_in_topk"] for v in values]
                ),
            }
        out[arm] = {"at_k": at_k}
    return out


def _cell_macro(rows: list[dict[str, object]], ks: tuple[int, ...]) -> dict[str, object]:
    out: dict[str, object] = {}
    for arm in ARM_IDS:
        out[arm] = {"at_k": {}}
        for k in ks:
            values = [row["arms"][arm]["at_k"][str(k)] for row in rows]
            positive = [
                v
                for row, v in zip(rows, values)
                if row["answerability"] == ANSWERABLE and v["complete_evidence"] is not None
            ]
            negative = [
                v
                for row, v in zip(rows, values)
                if row["answerability"] == NEGATIVE and v["complete_evidence"] is not None
            ]
            out[arm]["at_k"][str(k)] = {
                "positive_complete_evidence": _mean_optional(
                    [v["complete_evidence"] for v in positive]
                ),
                "positive_hit": _mean_optional([v["hit"] for v in positive]),
                "positive_mrr": _mean_optional([v["mrr"] for v in positive]),
                "positive_ndcg": _mean_optional([v["ndcg"] for v in positive]),
                "negative_complete_evidence": _mean_optional(
                    [v["complete_evidence"] for v in negative]
                ),
                "negative_hit": _mean_optional([v["hit"] for v in negative]),
                "negative_cells": sum(1 for row in rows if row["answerability"] == NEGATIVE),
                "not_evaluated_cells": sum(
                    1 for row in rows if row["answerability"] == NOT_EVALUATED
                ),
                "retrieved_mean": _mean_optional([v["retrieved"] for v in values]),
            }
    return out


def _mean_optional(values: list[object]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return mean(numbers) if numbers else None


def _twenty_vs_fifty(rows: list[dict[str, object]], ks: tuple[int, ...]) -> dict[str, object]:
    out = {}
    for row in rows:
        required = int(row["required_groups"])
        applicable = required <= 20
        out[row["gold_id"]] = {
            "required": required,
            "applicable": applicable,
            "ceiling_at_20": ceiling_at(20, required),
            "dense_bm25_at_20": row["arms"]["dense_bm25"]["at_k"].get("20"),
            "hybrid_current_at_50": row["arms"]["hybrid_current"]["at_k"].get("50"),
            "dense_at_50": row["arms"]["dense"]["at_k"].get("50"),
        }
    return out


def _comparisons(
    global_payload: dict[str, object] | None,
    document_payload: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "global": _global_comparisons(global_payload) if global_payload else None,
        "document": _document_comparisons(document_payload) if document_payload else None,
    }


def _global_comparisons(payload: dict[str, object]) -> dict[str, object]:
    rows = payload["rows"]
    differs = any(
        [hit["key"] for hit in row["arms"]["hybrid_current"]["at_k"]["20"]["hits"]]
        != [hit["key"] for hit in row["arms"]["hybrid_rrf_control"]["at_k"]["20"]["hits"]]
        for row in rows
    )
    return {
        "hybrid_current_differs_from_control": differs,
        "hybrid_current_note": (
            "Historical OverGraph reciprocal_rank contract; not rewritten."
            if differs
            else "Same ranking as the locked RRF control on these golds."
        ),
        "dense_bm25_vs_dense": _arm_delta(rows, "dense_bm25", "dense", "20"),
        "dense_bm25_vs_hybrid_current": _arm_delta(
            rows, "dense_bm25", "hybrid_current", "20"
        ),
        "control_vs_positive": _control_delta(rows, "20"),
        "additions_displacements": _additions(rows, "dense_bm25", "dense", "20"),
        "bootstrap": {
            "dense_bm25_vs_dense_document_recall20": _bootstrap_gold(
                rows, "dense_bm25", "dense", "20", "document_recall"
            ),
            "dense_bm25_vs_hybrid_document_recall20": _bootstrap_gold(
                rows, "dense_bm25", "hybrid_current", "20", "document_recall"
            ),
        },
    }


def _document_comparisons(payload: dict[str, object]) -> dict[str, object]:
    rows = payload["rows"]
    differs = any(
        [hit["key"] for hit in row["arms"]["hybrid_current"]["at_k"]["5"]["hits"]]
        != [hit["key"] for hit in row["arms"]["hybrid_rrf_control"]["at_k"]["5"]["hits"]]
        for row in rows
    )
    return {
        "hybrid_current_differs_from_control": differs,
        "dense_bm25_vs_dense": _cell_delta(rows, "dense_bm25", "dense", "5"),
        "dense_bm25_vs_hybrid_current": _cell_delta(
            rows, "dense_bm25", "hybrid_current", "5"
        ),
        "control_vs_positive": _control_cell_delta(rows, "5"),
        "bootstrap": {
            "dense_bm25_vs_dense_complete5": _bootstrap_cells(
                rows, "dense_bm25", "dense", "5", "complete_evidence"
            ),
            "dense_bm25_vs_hybrid_complete5": _bootstrap_cells(
                rows, "dense_bm25", "hybrid_current", "5", "complete_evidence"
            ),
        },
    }


def _arm_delta(
    rows: list[dict[str, object]],
    treatment: str,
    baseline: str,
    k: str,
) -> dict[str, object]:
    deltas = []
    for row in rows:
        left = row["arms"][treatment]["at_k"][k]
        right = row["arms"][baseline]["at_k"][k]
        deltas.append(
            {
                "gold_id": row["gold_id"],
                "document_recall": _delta(left["document_recall"], right["document_recall"]),
                "evidence_recall": _delta(left["evidence_recall"], right["evidence_recall"]),
                "complete_evidence": _delta(left["complete_evidence"], right["complete_evidence"]),
                "ndcg": _delta(left["ndcg"], right["ndcg"]),
                "mrr": _delta(left["mrr"], right["mrr"]),
            }
        )
    return {"treatment": treatment, "baseline": baseline, "rows": deltas, "macro": _macro_delta(deltas)}


def _cell_delta(
    rows: list[dict[str, object]],
    treatment: str,
    baseline: str,
    k: str,
) -> dict[str, object]:
    deltas = []
    for row in rows:
        left = row["arms"][treatment]["at_k"][k]
        right = row["arms"][baseline]["at_k"][k]
        deltas.append(
            {
                "question_id": row["question_id"],
                "relative_path": row["relative_path"],
                "split": row["split"],
                "complete_evidence": _delta(left["complete_evidence"], right["complete_evidence"]),
                "hit": _delta(left["hit"], right["hit"]),
                "ndcg": _delta(left["ndcg"], right["ndcg"]),
                "mrr": _delta(left["mrr"], right["mrr"]),
            }
        )
    return {"treatment": treatment, "baseline": baseline, "rows": deltas, "macro": _macro_delta(deltas)}


def _control_delta(rows: list[dict[str, object]], k: str) -> dict[str, object]:
    identical = all(
        row["arms"]["hybrid_rrf_control"]["at_k"][k]["hits"]
        == row["arms"]["hybrid_rrf_positive"]["at_k"][k]["hits"]
        for row in rows
    )
    return {
        "k": k,
        "arms_identical": identical,
        "zero_score_sparse_hits": {
            row["gold_id"]: int(
                (row.get("branch_meta") or {}).get("sparse_zero_score_count") or 0
            )
            for row in rows
        },
        "delta": _arm_delta(rows, "hybrid_rrf_positive", "hybrid_rrf_control", k),
    }


def _control_cell_delta(rows: list[dict[str, object]], k: str) -> dict[str, object]:
    identical = all(
        row["arms"]["hybrid_rrf_control"]["at_k"][k]["hits"]
        == row["arms"]["hybrid_rrf_positive"]["at_k"][k]["hits"]
        for row in rows
    )
    return {
        "k": k,
        "arms_identical": identical,
        "zero_score_sparse_hits": {
            f'{row["question_id"]}:{row["relative_path"]}': int(
                (row.get("branch_meta") or {}).get("sparse_zero_score_count") or 0
            )
            for row in rows
        },
        "delta": _cell_delta(rows, "hybrid_rrf_positive", "hybrid_rrf_control", k),
    }


def _additions(
    rows: list[dict[str, object]],
    treatment: str,
    baseline: str,
    k: str,
) -> list[dict[str, object]]:
    out = []
    for row in rows:
        left = row["arms"][treatment]["at_k"][k]["hits"]
        right = row["arms"][baseline]["at_k"][k]["hits"]
        left_keys = {hit["key"] for hit in left}
        right_keys = {hit["key"] for hit in right}
        out.append(
            {
                "gold_id": row["gold_id"],
                "added": [hit for hit in left if hit["key"] not in right_keys],
                "displaced": [hit for hit in right if hit["key"] not in left_keys],
            }
        )
    return out


def _macro_delta(rows: list[dict[str, object]]) -> dict[str, object]:
    names = ("document_recall", "evidence_recall", "complete_evidence", "ndcg", "mrr", "hit")
    return {
        name: _mean_optional([row.get(name) for row in rows])
        for name in names
    }


def _bootstrap_cells(
    rows: list[dict[str, object]],
    treatment: str,
    baseline: str,
    k: str,
    metric: str,
) -> dict[str, object]:
    observations = []
    for row in rows:
        if row["answerability"] != ANSWERABLE:
            continue
        left = row["arms"][treatment]["at_k"][k].get(metric)
        right = row["arms"][baseline]["at_k"][k].get(metric)
        if left is None or right is None:
            continue
        observations.append(GroupObservation(str(row["relative_path"]), float(left), float(right)))
    return _bootstrap(observations)


def _bootstrap_gold(
    rows: list[dict[str, object]],
    treatment: str,
    baseline: str,
    k: str,
    metric: str,
) -> dict[str, object]:
    observations = []
    for row in rows:
        left = row["arms"][treatment]["at_k"].get(k, {}).get(metric)
        right = row["arms"][baseline]["at_k"].get(k, {}).get(metric)
        if left is None or right is None:
            continue
        observations.append(
            GroupObservation(str(row["gold_id"]), float(left), float(right))
        )
    result = _bootstrap(observations)
    result["cluster_unit"] = "gold"
    return result


def _bootstrap(observations: list[GroupObservation]) -> dict[str, object]:
    if not observations:
        return {"status": "not_evaluated", "n": 0}
    clusters: dict[str, list[GroupObservation]] = defaultdict(list)
    for observation in observations:
        clusters[observation.cluster].append(observation)
    names = sorted(clusters)
    rng = random.Random(BOOTSTRAP_SEED)
    deltas = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        picked = [clusters[names[rng.randrange(len(names))]] for _ in names]
        flat = [item for group in picked for item in group]
        deltas.append(mean(item.left - item.right for item in flat))
    deltas.sort()
    return {
        "status": "estimated",
        "n_observations": len(observations),
        "n_clusters": len(names),
        "mean_delta": mean(deltas),
        "ci95": [deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas)) - 1]],
        "iterations": BOOTSTRAP_ITERATIONS,
        "seed": BOOTSTRAP_SEED,
        "cluster_unit": "document",
    }


def _summary(profiles: dict[str, object]) -> dict[str, object]:
    summary = {}
    for name, payload in profiles.items():
        global_payload = payload.get("global") or {}
        document_payload = payload.get("document") or {}
        summary[name] = {
            "global_macro": (global_payload.get("macro") or {}),
            "document_macro": (document_payload.get("macro") or {}),
            "comparisons": payload.get("comparisons"),
        }
    return summary


def _verdict(payload: dict[str, object]) -> dict[str, object]:
    profiles = payload.get("profiles") or {}
    if not profiles:
        return {"verdict": "no_measurement", "production_changed": False}
    first = next(iter(profiles.values()))
    global_payload = first.get("global") or {}
    document_payload = first.get("document") or {}
    rows = global_payload.get("rows") or []
    dense20 = _arm_value(rows, "dense_bm25", "20", "document_recall")
    hybrid20 = _arm_value(rows, "hybrid_current", "20", "document_recall")
    baseline20 = _arm_value(rows, "dense", "20", "document_recall")
    dense50 = _arm_value(rows, "dense_bm25", "50", "document_recall")
    baseline50 = _arm_value(rows, "dense", "50", "document_recall")
    doc_rows = document_payload.get("rows") or []
    doc_delta = _cell_mean_delta(doc_rows, "dense_bm25", "dense", "5", "complete_evidence")
    global_delta = _cell_mean_delta(rows, "dense_bm25", "dense", "20", "document_recall")
    hybrid_delta = _cell_mean_delta(rows, "dense_bm25", "hybrid_current", "20", "document_recall")
    coverage_loss = (
        dense50 is not None and baseline50 is not None and dense50 < baseline50
    )
    better_than_dense = (global_delta or 0) > 0 or (doc_delta or 0) > 0
    better_than_hybrid = (hybrid_delta or 0) > 0
    control = ((first.get("comparisons") or {}).get("global") or {}).get(
        "control_vs_positive"
    ) or {}
    control_positive_differs = not bool(control.get("arms_identical"))
    gains = [
        delta
        for delta in (global_delta, doc_delta)
        if delta is not None and delta > 0
    ]
    losses = [
        delta
        for delta in (global_delta, doc_delta)
        if delta is not None and delta < 0
    ]
    if coverage_loss:
        verdict = "coverage_loss_at_50"
    elif better_than_hybrid and better_than_dense:
        verdict = "candidate_for_answer_test"
    elif better_than_hybrid and not better_than_dense:
        verdict = "lexical_or_fusion_gain_not_beyond_dense"
    elif gains and losses:
        verdict = "mixed"
    elif control_positive_differs and gains:
        verdict = "control_explains_gain"
    else:
        verdict = "no_quality_gain_keep_current"
    return {
        "verdict": verdict,
        "production_changed": False,
        "default_retriever_unchanged": True,
        "claim_scope": "improved_retrieval_only",
        "holdout_status": "not_blind",
        "generalisation_status": "insufficient",
        "dense_bm25_document_recall_at_20": dense20,
        "hybrid_current_document_recall_at_20": hybrid20,
        "dense_document_recall_at_20": baseline20,
        "dense_bm25_document_recall_at_50": dense50,
        "dense_document_recall_at_50": baseline50,
        "dense_bm25_vs_dense_delta_at_20": global_delta,
        "dense_bm25_vs_hybrid_delta_at_20": hybrid_delta,
        "complete_evidence_delta_at_5": doc_delta,
        "control_and_positive_identical": not control_positive_differs,
        "critical_case_review_required": True,
    }


def _arm_value(
    rows: list[dict[str, object]],
    arm: str,
    k: str,
    metric: str,
) -> float | None:
    values = [
        row["arms"][arm]["at_k"].get(k, {}).get(metric)
        for row in rows
        if arm in row.get("arms", {})
    ]
    numbers = [float(value) for value in values if value is not None]
    return mean(numbers) if numbers else None


def _cell_mean_delta(
    rows: list[dict[str, object]],
    treatment: str,
    baseline: str,
    k: str,
    metric: str,
) -> float | None:
    values = []
    for row in rows:
        left = row.get("arms", {}).get(treatment, {}).get("at_k", {}).get(k, {}).get(metric)
        right = row.get("arms", {}).get(baseline, {}).get("at_k", {}).get(k, {}).get(metric)
        if left is None or right is None:
            continue
        values.append(float(left) - float(right))
    return mean(values) if values else None


def _manifest(
    config: RetrievalConfig,
    *,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    cells: list[CellEvidenceGold],
    profiles: dict[str, object],
    gold_dir: Path | None,
    scope: str,
    branch_depth: int,
    global_ks: tuple[int, ...],
    local_ks: tuple[int, ...],
    repeats: int,
) -> dict[str, object]:
    source_gold_dir = gold_dir or DEFAULT_GOLD_DIR
    gold_files = [
        source_gold_dir / "index.json",
        *sorted(source_gold_dir.glob("*.json")),
    ]
    gold_hashes = {
        str(path.relative_to(ROOT)): _file_hash(path)
        for path in gold_files
        if path.is_file()
    }
    overlay = DEFAULT_OVERLAY if DEFAULT_OVERLAY.is_file() else None
    if overlay is not None:
        gold_hashes[str(overlay.relative_to(ROOT))] = _file_hash(overlay)
    return {
        "run_id": "phase2-tantivy-bm25-v1",
        "code_revision": _code_revision(),
        "created_at": _utc_now(),
        "command": _safe_command(),
        "corpus": {
            "db": str(config.db_path),
            "db_manifest_hash": _file_hash(config.db_path / "manifest.current"),
            "dense_dimension": _dimension(config, units),
            "units": len(units),
            "documents": len({unit.relative_path for unit in units}),
            "units_metadata": units_metadata(units),
        },
        "gold": {
            "files": gold_hashes,
            "golds": [gold.id for gold in golds],
            "splits": sorted({gold.split for gold in golds} | {cell.split for cell in cells}),
            "question_cells": len(cells),
            "written_before_bm25_results": True,
        },
        "encoders": {
            "dense_model": config.dense_model,
            "dense_dimension": _dimension(config, units),
            "sparse_encoder": "lexical-tfidf-hash-v1",
        },
        "tantivy": {
            name: {
                "analyzer": payload.get("analyzer"),
                "index": payload.get("bm25_index"),
            }
            for name, payload in profiles.items()
        },
        "scope": scope,
        "branch_depth": branch_depth,
        "final_ks": list(global_ks),
        "local_ks": list(local_ks),
        "rrf": {"k": RRF_K, "equal_weight": True, "tie_break": "stable_key"},
        "budgets": {
            "global_branch_depth": branch_depth,
            "global_final": list(global_ks),
            "document_branch_depth": "all_document_units",
            "document_final": list(local_ks),
        },
        "repeats": repeats,
        "environment": {
            **environment_metadata(),
            "tantivy": _tantivy_version(),
            "cpu_count": __import__("os").cpu_count(),
            "peak_rss_mb": _peak_rss_bytes() / (1024 * 1024),
        },
    }


def _limitations() -> list[str]:
    return [
        "The Swedish Tantivy stemmer maps förlängs to förläng but leaves förlängning unchanged; the result is pipeline-level, not a pure BM25 formula test.",
        "HOLD_OUT_CELLS is locked but not blind: it was used for the tabular holdout. Generalisation is insufficient without a new independent corpus.",
        "OverGraph vector_search has no property filter; document-local dense/sparse arms use Python ranking and must not be reported as engine latency.",
        "Governing-law has 75 relevant documents, so full coverage at 20 is mathematically impossible and is marked not_applicable.",
        "The experiment does not change production retrieval, add a router, or tune BM25 parameters.",
    ]


def _safe_command() -> list[str]:
    import sys

    secret_flags = {
        "--openai-api-key",
        "--typesafe-api-key",
        "--cerebras-api-key",
    }
    result: list[str] = []
    redact_next = False
    for value in sys.argv:
        if redact_next:
            result.append("***")
            redact_next = False
            continue
        if value in secret_flags:
            result.append(value)
            redact_next = True
            continue
        if any(value.startswith(f"{flag}=") for flag in secret_flags):
            flag = value.split("=", 1)[0]
            result.append(f"{flag}=***")
            continue
        result.append(value)
    return result


def _code_revision() -> dict[str, object]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return {"head": revision, "dirty": dirty}
    except (subprocess.CalledProcessError, OSError):
        return {"head": "unknown", "dirty": None}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def _tantivy_version() -> str:
    import tantivy

    return str(tantivy.__version__)


def _delta(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


BM25_BASELINE_ID = "phase2-tantivy-bm25-v1"
BM25_BASELINE_PATH = ROOT / "baselines" / f"{BM25_BASELINE_ID}.json"
BM25_REPORT_PATH = ROOT / "eval" / "tantivy-bm25-v1.md"


def freeze_bm25_baseline(payload: dict[str, object]) -> dict[str, object]:
    compact = _compact_payload(payload)
    return {
        "id": BM25_BASELINE_ID,
        "label": (
            "Frozen experimental Tantivy BM25 comparison. Step A is model-free "
            "retrieval; Step B is optional. Production retrieval and the default "
            "strategy are unchanged. Existing baselines are not overwritten."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "default_retriever_unchanged": True,
        "production_changed": False,
        "claim_scope": payload.get("claim_scope"),
        "verdict": payload.get("verdict"),
        "summary": payload.get("summary"),
        "manifest": payload.get("manifest"),
        "limitations": payload.get("limitations"),
        "profiles": compact.get("profiles"),
        "answer_test": compact.get("answer_test"),
        "paging": compact.get("paging"),
    }


def write_bm25_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or BM25_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            freeze_bm25_baseline(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def write_bm25_report(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or BM25_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_report_markdown(payload), encoding="utf-8")
    return target


def run_paging_test(
    payload: dict[str, object],
    *,
    page_size: int = 20,
    profile: str | None = None,
) -> dict[str, object]:
    from overgraph_ingest.retrieval.bm25_answer import candidate_lists_from_payload
    from overgraph_ingest.retrieval.bm25_paging import consume_all

    lists = candidate_lists_from_payload(payload, profile=profile)
    rows = []
    for (question_id, relative_path, arm), frozen in sorted(lists.items()):
        if arm != "dense_bm25":
            continue
        relevant = {
            str(entry.get("relative_path") or "")
            for entry in frozen.entries
            if entry.get("label") == "relevant"
        }
        stats, processed, reason = consume_all(
            frozen,
            page_size=page_size,
            relevant_paths=relevant,
        )
        rows.append(
            {
                "question_id": question_id,
                "relative_path": relative_path,
                "arm": arm,
                "pages": [row.__dict__ for row in stats],
                "processed_text_units": len(processed),
                "duplicates": 0,
                "stop_reason": reason,
                "replay": True,
                "end_of_list_is_not_completeness": True,
                "lexical_matches_exhausted_is_not_absence": True,
            }
        )
    return {
        "status": "completed" if rows else "not_run",
        "page_size": page_size,
        "replay": True,
        "rows": rows,
        "note": (
            "Replay over a frozen list measures incremental consumption, not "
            "streaming database latency. The initial search is not hidden."
        ),
    }


def _compact_payload(payload: dict[str, object]) -> dict[str, object]:
    profiles = payload.get("profiles") or {}
    compact_profiles = {}
    if isinstance(profiles, dict):
        for name, profile in profiles.items():
            compact_profiles[name] = _compact_profile(profile)
    return {**payload, "profiles": compact_profiles}


def _compact_profile(profile: dict[str, object]) -> dict[str, object]:
    return {
        **profile,
        "global": _compact_scope(profile.get("global")),
        "document": _compact_scope(profile.get("document")),
    }


def _compact_scope(scope: object) -> object:
    if not isinstance(scope, dict):
        return scope
    if scope.get("branch_depth") == "all_document_units":
        return {
            **scope,
            "rows": [],
            "rows_omitted": len(scope.get("rows") or []),
            "note": "Per-cell rows stay in the run JSON; this baseline keeps macro aggregates.",
        }
    rows = []
    for row in scope.get("rows") or []:
        arms = {}
        is_document = "document_units" in row
        for arm, arm_payload in (row.get("arms") or {}).items():
            at_k = {
                k: {key: value for key, value in payload.items() if key != "hits"}
                for k, payload in (arm_payload.get("at_k") or {}).items()
            }
            drop = {
                "groups_covered",
                "groups_missing",
                "documents_covered",
                "documents_complete",
                "hard_negative_ranks",
                "absent",
            }
            at_k = {
                k: {key: value for key, value in payload.items() if key not in drop}
                for k, payload in at_k.items()
            }
            if is_document:
                keep = {"complete_evidence", "hit", "mrr", "ndcg"}
                at_k = {
                    k: {key: value for key, value in payload.items() if key in keep}
                    for k, payload in at_k.items()
                    if k in {"1", "3", "5", "10"}
                }
                arms[arm] = {"arm": arm, "at_k": at_k}
            else:
                arms[arm] = {
                    "arm": arm,
                    "at_k": at_k,
                    "k_to_90": arm_payload.get("k_to_90"),
                    "k_to_100": arm_payload.get("k_to_100"),
                    "k_to_90_complete": arm_payload.get("k_to_90_complete"),
                    "k_to_100_complete": arm_payload.get("k_to_100_complete"),
                    "evaluated_depth": arm_payload.get("evaluated_depth"),
                }
        compact_row = {key: value for key, value in row.items() if key != "branch_meta"}
        compact_row["arms"] = arms
        rows.append(compact_row)
    return {**scope, "rows": rows}


def _report_markdown(payload: dict[str, object]) -> str:
    profiles = payload.get("profiles") or {}
    lines = [
        "# Tantivy BM25 v1",
        "",
        "Experimental comparison. Production retrieval is unchanged.",
        f"Status: **{payload.get('status')}**.",
        f"Claim scope: **{payload.get('claim_scope')}**.",
        "",
        "## Verdict",
        "",
        "```json",
        json.dumps(payload.get("verdict") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Global macro",
        "",
        "| Profil | Arm | DocumentRecall@20 | EvidenceRecall@20 | NDCG@20 | Precision@20 | HN@20 | DocumentRecall@50 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, profile in (profiles.items() if isinstance(profiles, dict) else []):
        global_payload = (profile or {}).get("global") or {}
        macro = global_payload.get("macro") or {}
        for arm in ARM_IDS:
            at = (macro.get(arm) or {}).get("at_k") or {}
            row20 = at.get("20") or {}
            row50 = at.get("50") or {}
            lines.append(
                f"| {name} | {arm} | {_fmt(row20.get('document_recall'))} | "
                f"{_fmt(row20.get('evidence_recall'))} | {_fmt(row20.get('ndcg'))} | "
                f"{_fmt(row20.get('precision'))} | {_fmt(row20.get('hard_negatives_in_topk'))} | "
                f"{_fmt(row50.get('document_recall'))} |"
            )
    lines.extend(
        [
            "",
            "## Document-local macro",
            "",
            "| Profil | Arm | CompleteEvidence@5 | Hit@5 | NDCG@5 | MRR@5 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for name, profile in (profiles.items() if isinstance(profiles, dict) else []):
        macro = ((profile or {}).get("document") or {}).get("macro") or {}
        for arm in ARM_IDS:
            at = (macro.get(arm) or {}).get("at_k") or {}
            row5 = at.get("5") or {}
            lines.append(
                f"| {name} | {arm} | {_fmt(row5.get('positive_complete_evidence'))} | "
                f"{_fmt(row5.get('positive_hit'))} | {_fmt(row5.get('positive_ndcg'))} | "
                f"{_fmt(row5.get('positive_mrr'))} |"
            )
    lines.extend(
        [
            "",
            "## Twenty versus fifty",
            "",
            "| Gold | Required | Applicable | Ceiling@20 | DenseBM25 R@20 | Hybrid R@50 | Dense R@50 |",
            "|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    first_profile = next(iter(profiles.values()), {}) if isinstance(profiles, dict) else {}
    for row in ((first_profile or {}).get("global") or {}).get("rows") or []:
        tvf = ((first_profile or {}).get("global") or {}).get("twenty_vs_fifty") or {}
        entry = tvf.get(row.get("gold_id")) or {}
        dense20 = entry.get("dense_bm25_at_20") or {}
        hybrid50 = entry.get("hybrid_current_at_50") or {}
        dense50 = entry.get("dense_at_50") or {}
        lines.append(
            f"| {row.get('gold_id')} | {entry.get('required')} | {entry.get('applicable')} | "
            f"{entry.get('ceiling_at_20')} | {_fmt(dense20.get('document_recall'))} | "
            f"{_fmt(hybrid50.get('document_recall'))} | {_fmt(dense50.get('document_recall'))} |"
        )
    lines.extend(
        [
            "",
            "## Coverage depth",
            "",
            "| Gold | DenseBM25 K90 | DenseBM25 K100 | DenseBM25 K90 complete | DenseBM25 K100 complete |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in ((first_profile or {}).get("global") or {}).get("rows") or []:
        arm = (row.get("arms") or {}).get("dense_bm25") or {}
        def depth(name: str, arm=arm):
            value = arm.get(name) or {}
            return value.get("value") if value.get("status") == "reached" else "not_reached"
        lines.append(
            f"| {row.get('gold_id')} | {depth('k_to_90')} | {depth('k_to_100')} | "
            f"{depth('k_to_90_complete')} | {depth('k_to_100_complete')} |"
        )
    lines.extend(
        [
            "",
            "## Additions and displacements",
            "",
            "| Gold | Added relevant | Displaced relevant |",
            "|---|---:|---:|",
        ]
    )
    additions = (
        ((first_profile or {}).get("comparisons") or {}).get("global") or {}
    ).get("additions_displacements") or []
    for item in additions:
        added = sum(1 for hit in item.get("added") or [] if hit.get("label") == "relevant")
        displaced = sum(1 for hit in item.get("displaced") or [] if hit.get("label") == "relevant")
        lines.append(f"| {item.get('gold_id')} | {added} | {displaced} |")
    lines.extend(
        [
            "",
            "## Per-query global",
            "",
            "| Gold | Required | DenseBM25 R@20 | Hybrid R@20 | Dense R@20 | DenseBM25 R@50 | Dense R@50 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in ((first_profile or {}).get("global") or {}).get("rows") or []:
        arms = row.get("arms") or {}
        def value(arm: str, k: str, metric: str, arms=arms):
            return ((arms.get(arm) or {}).get("at_k") or {}).get(k, {}).get(metric)
        lines.append(
            f"| {row.get('gold_id')} | {row.get('required_groups')} | "
            f"{_fmt(value('dense_bm25','20','document_recall'))} | "
            f"{_fmt(value('hybrid_current','20','document_recall'))} | "
            f"{_fmt(value('dense','20','document_recall'))} | "
            f"{_fmt(value('dense_bm25','50','document_recall'))} | "
            f"{_fmt(value('dense','50','document_recall'))} |"
        )
    lines.extend(
        [
            "",
            "## Per-question document-local",
            "",
            "| Fråga | Split | DenseBM25 CE@5 | Hybrid CE@5 | Dense CE@5 | Positive control CE@5 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    by_question: dict[tuple[str, str], dict[str, list[float]]] = {}
    for row in ((first_profile or {}).get("document") or {}).get("rows") or []:
        key = (str(row.get("question_id")), str(row.get("split")))
        bucket = by_question.setdefault(key, {})
        for arm in ARM_IDS:
            value = (
                ((row.get("arms") or {}).get(arm) or {})
                .get("at_k", {})
                .get("5", {})
                .get("complete_evidence")
            )
            if value is not None:
                bucket.setdefault(arm, []).append(float(value))
    for (question_id, split), values in sorted(by_question.items()):
        def mean_arm(arm: str, values=values):
            items = values.get(arm) or []
            return mean(items) if items else None
        lines.append(
            f"| {question_id} | {split} | {_fmt(mean_arm('dense_bm25'))} | "
            f"{_fmt(mean_arm('hybrid_current'))} | {_fmt(mean_arm('dense'))} | "
            f"{_fmt(mean_arm('hybrid_rrf_positive'))} |"
        )
    control = (
        ((first_profile or {}).get("comparisons") or {}).get("global") or {}
    ).get("control_vs_positive") or {}
    comparisons = (first_profile or {}).get("comparisons") or {}
    lines.extend(
        [
            "",
            "## Uncertainty",
            "",
            "```json",
            json.dumps(
                {
                    "global": (comparisons.get("global") or {}).get("bootstrap"),
                    "document": (comparisons.get("document") or {}).get("bootstrap"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Control",
            "",
            f"Control and positive sparse arms identical at k=20 globally: **{control.get('arms_identical')}**.",
            (
                "Historical hybrid differs from the locked RRF control at k=20: "
                f"**{(comparisons.get('global') or {}).get('hybrid_current_differs_from_control')}**. "
                f"{(comparisons.get('global') or {}).get('hybrid_current_note') or ''}"
            ),
            f"Global zero-score sparse hits: `{json.dumps(control.get('zero_score_sparse_hits') or {}, ensure_ascii=False)}`",
            (
                "Document-locally the positive sparse control differs: compare "
                "hybrid_rrf_positive and hybrid_rrf_control in the macro table. "
                "That gain is not attributable to BM25."
            ),
            "",
            "## Latency",
            "",
            "| Profil | Stage | p50 s | p95 s |",
            "|---|---|---:|---:|",
        ]
    )
    for name, profile in (profiles.items() if isinstance(profiles, dict) else []):
        latency = (profile or {}).get("global", {}).get("latency") or {}
        rows = latency.get("rows") or []
        for stage in (
            "query_analysis",
            "dense_engine",
            "sparse_engine",
            "bm25",
            "fusion",
            "hydrate",
        ):
            p50 = _stage_mean(rows, stage, "p50")
            p95 = _stage_mean(rows, stage, "p95")
            lines.append(
                f"| {name} | {stage} | {_fmt(p50)} | {_fmt(p95)} |"
            )
        for metric in ("query_encode_seconds", "retrieval_seconds", "end_to_end_seconds"):
            values = [
                float(row[metric])
                for row in rows
                if row.get(metric) is not None
            ]
            stats = _stats(values)
            lines.append(
                f"| {name} | {metric} | {_fmt(stats.get('p50'))} | {_fmt(stats.get('p95'))} |"
            )
    lines.extend(
        [
            "",
            "Python document-local ranking is reported separately from Tantivy/OverGraph latency.",
            "",
            "## Paging and answer test",
            "",
            (
                f"Paging: **{(payload.get('paging') or {}).get('status')}**, page size "
                f"{(payload.get('paging') or {}).get('page_size')}."
            ),
            (
                f"Answer test: **{(payload.get('answer_test') or {}).get('status')}**. "
                "Without a completed answer test the claim remains improved retrieval only."
            ),
            "",
            "## Error analysis",
            "",
            (
                "Full candidate lists, branch ranks/scores, additions/displacements, and "
                "per-cell misses are in the run JSON. This report shows the macro and "
                "per-query decision layer only."
            ),
            "",
            "## Limitations",
            "",
        ]
    )
    for limitation in payload.get("limitations") or []:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def _stage_mean(rows: list[dict[str, object]], stage: str, field: str) -> float | None:
    values = [
        ((row.get("stages") or {}).get(stage) or {}).get(field)
        for row in rows
    ]
    numbers = [float(value) for value in values if value is not None]
    return mean(numbers) if numbers else None


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)
