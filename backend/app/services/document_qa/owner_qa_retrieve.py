"""Owner-backed Q&A reuse. Exact reuse is a hit; similarity is only candidates."""

from __future__ import annotations

from app.services.document_qa.access import Viewer
from app.services.document_qa.labels import QUESTION
from app.services.document_qa.normalize import normalize_question, question_key, reuse_digest
from app.services.document_qa.owner_qa import load_question
from app.services.document_qa.owner_qa_lifecycle import document_is_archived
from app.services.document_qa.types import (
    AnalysisContract,
    CacheDecision,
    ExactHit,
    LoadedAnswer,
    LoadedQuestion,
    SemanticCandidate,
)
from app.services.overgraph.owner import OwnerClient


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


async def exact_reuse(
    client: OwnerClient,
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
    loaded = await load_question(client, question_key(viewer.customer_id, digest))
    if loaded is None:
        return None
    if loaded.document_version_id != document_version_id:
        return None
    if not await _usable_question(client, viewer, loaded, include_archived):
        return None
    answer = preferred_answer(loaded)
    if answer is None:
        return None
    return ExactHit(question=loaded, answer=answer)


async def semantic_candidates(
    client: OwnerClient,
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
    hits = await client.vector_search(QUESTION, list(embedding), k=k)
    candidates: list[SemanticCandidate] = []
    for hit in hits:
        if QUESTION not in hit.get("labels", []):
            continue
        loaded = await load_question(client, str(hit["key"]))
        if loaded is None or loaded.document_id != document_id:
            continue
        if not await _usable_question(client, viewer, loaded, include_archived):
            continue
        candidates.append(
            SemanticCandidate(
                question=loaded,
                score=float(hit.get("score") or 0.0),
                current_version=loaded.document_version_id == document_version_id,
            )
        )
    return tuple(candidates)


def cache_decision(
    exact: ExactHit | None,
    candidates: tuple[SemanticCandidate, ...],
) -> CacheDecision:
    if exact is not None:
        return CacheDecision(reuse="exact", exact=exact, candidates=candidates)
    return CacheDecision(reuse="none", exact=None, candidates=candidates)


async def _usable_question(
    client: OwnerClient,
    viewer: Viewer,
    question: LoadedQuestion,
    include_archived: bool,
) -> bool:
    if not viewer.can_read(question.document_id, question.document_version_id):
        return False
    if include_archived:
        return True
    if question.archived:
        return False
    return not await document_is_archived(client, question.document_id)
