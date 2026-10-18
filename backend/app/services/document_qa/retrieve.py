"""Exact reuse is a cache hit. Semantic similarity is only a candidate list."""

from __future__ import annotations

from app.services.document_qa.access import Viewer
from app.services.document_qa.labels import CANONICAL_DOCUMENT, QUESTION
from app.services.document_qa.normalize import normalize_question, question_key, reuse_digest
from app.services.document_qa.store import load_question
from app.services.document_qa.types import (
    AnalysisContract,
    CacheDecision,
    ExactHit,
    LoadedAnswer,
    LoadedQuestion,
    SemanticCandidate,
)
from app.services.overgraph.catalogs import Catalog


def exact_reuse(
    catalog: Catalog,
    viewer: Viewer,
    *,
    question_text: str,
    document_id: str,
    document_version_id: str,
    contract: AnalysisContract,
    include_archived: bool = False,
) -> ExactHit | None:
    if not viewer.can_read(document_id, document_version_id):
        return None
    digest = reuse_digest(normalize_question(question_text), document_version_id, contract)
    loaded = load_question(catalog, question_key(viewer.customer_id, digest))
    if loaded is None:
        return None
    if not _usable_question(catalog, viewer, loaded, include_archived):
        return None
    if loaded.document_version_id != document_version_id:
        return None
    answer = preferred_answer(loaded)
    if answer is None:
        return None
    return ExactHit(question=loaded, answer=answer)


def semantic_candidates(
    catalog: Catalog,
    viewer: Viewer,
    *,
    embedding: tuple[float, ...],
    document_id: str,
    document_version_id: str,
    include_archived: bool = False,
    k: int = 5,
) -> tuple[SemanticCandidate, ...]:
    if not viewer.can_read(document_id, document_version_id):
        return ()
    hits = catalog.vector_search(
        "dense",
        {
            "k": k,
            "dense_query": embedding,
            "label_filter": {"labels": [QUESTION], "mode": "all"},
        },
    )
    return tuple(
        candidate
        for engine_id, score in hits
        if (candidate := _candidate(
            catalog,
            viewer,
            engine_id=engine_id,
            score=score,
            document_id=document_id,
            version_id=document_version_id,
            include_archived=include_archived,
        )) is not None
    )


def cache_decision(
    exact: ExactHit | None,
    candidates: tuple[SemanticCandidate, ...],
) -> CacheDecision:
    if exact is not None:
        return CacheDecision(reuse="exact", exact=exact, candidates=candidates)
    return CacheDecision(reuse="none", exact=None, candidates=candidates)


def preferred_answer(question: LoadedQuestion) -> LoadedAnswer | None:
    usable = [
        answer
        for answer in question.answers
        if answer.status == "ANSWERED" and answer.review_status != "rejected"
    ]
    if not usable:
        return None
    verified = [answer for answer in usable if answer.review_status == "user_verified"]
    pool = verified or usable
    return max(pool, key=lambda answer: answer.created_at)


def _usable_question(
    catalog: Catalog,
    viewer: Viewer,
    question: LoadedQuestion,
    include_archived: bool,
) -> bool:
    if not viewer.can_read(question.document_id, question.document_version_id):
        return False
    if include_archived:
        return True
    document = catalog.get_by_key(CANONICAL_DOCUMENT, question.document_id)
    archived = bool(int((document.props if document else {}).get("archived") or 0))
    return not archived and not question.archived


def _candidate(
    catalog: Catalog,
    viewer: Viewer,
    *,
    engine_id: int,
    score: float,
    document_id: str,
    version_id: str,
    include_archived: bool,
) -> SemanticCandidate | None:
    row = catalog.get(engine_id)
    if row is None or QUESTION not in row.labels:
        return None
    loaded = load_question(catalog, row.key)
    if loaded is None or loaded.document_id != document_id:
        return None
    if not _usable_question(catalog, viewer, loaded, include_archived):
        return None
    return SemanticCandidate(
        question=loaded,
        score=score,
        current_version=loaded.document_version_id == version_id,
    )
