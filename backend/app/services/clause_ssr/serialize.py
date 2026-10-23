"""JSON shapes for the isolated clause SSR API."""

from __future__ import annotations

from app.services.clause_ssr.types import (
    Anchor,
    AnchorSet,
    CategoryScore,
    ClassificationDefinition,
    MatchHit,
    MatchResult,
    QueueCard,
    QueuePage,
    ReviewSession,
    Verification,
)


def classification_json(item: ClassificationDefinition) -> dict[str, object]:
    return {
        "id": item.id,
        "slug": item.slug,
        "version": item.version,
        "question": item.question,
        "level": item.level,
        "category": item.category,
        "active": item.active,
        "scope_key": item.scope_key,
    }


def verification_json(item: Verification) -> dict[str, object]:
    return {
        "id": item.id,
        "source_unit_id": item.source_unit_id,
        "source_document_id": item.source_document_id,
        "content_hash": item.content_hash,
        "classification_id": item.classification_id,
        "classification_version": item.classification_version,
        "question": item.question,
        "category": item.category,
        "answer": item.answer,
        "polarity": item.polarity,
        "reviewer_id": item.reviewer_id,
        "decided_at_ms": item.decided_at_ms,
        "source": item.source,
        "revision": item.revision,
        "status": item.status,
        "scope_key": item.scope_key,
        "is_label": item.polarity is not None,
    }


def session_json(item: ReviewSession) -> dict[str, object]:
    return {
        "id": item.id,
        "reviewer_id": item.reviewer_id,
        "classification_id": item.classification_id,
        "document_id": item.document_id,
        "last_unit_id": item.last_unit_id,
        "last_verification_id": item.last_verification_id,
        "decided_yes": item.decided_yes,
        "decided_no": item.decided_no,
        "skipped": item.skipped,
        "unsure": item.unsure,
        "answered": item.decided_yes + item.decided_no,
        "scope_key": item.scope_key,
    }


def card_json(item: QueueCard) -> dict[str, object]:
    return {
        "unit_id": item.unit_id,
        "document_id": item.document_id,
        "document_version_id": item.document_version_id,
        "text": item.text,
        "locator": item.locator,
        "ordinal": item.ordinal,
        "section_title": item.section_title,
        "content_hash": item.content_hash,
        "classification": classification_json(item.classification),
        "similarity": item.similarity,
        "similarity_kind": "cosine" if item.similarity is not None else None,
    }


def queue_json(page: QueuePage) -> dict[str, object]:
    return {
        "cards": [card_json(card) for card in page.cards],
        "session": session_json(page.session),
        "remaining": page.remaining,
        "total_eligible": page.total_eligible,
    }


def anchor_json(item: Anchor) -> dict[str, object]:
    return {
        "id": item.id,
        "verification_id": item.verification_id,
        "source_unit_id": item.source_unit_id,
        "classification_id": item.classification_id,
        "category": item.category,
        "polarity": item.polarity,
        "content_hash": item.content_hash,
        "status": item.status,
        "embedding_model": item.embedding.model,
        "embedding_revision": item.embedding.revision,
        "embedding_dimension": item.embedding.dimension,
        "has_vector": item.vector is not None,
        "scope_key": item.scope_key,
        "provenance": item.provenance,
    }


def set_json(item: AnchorSet) -> dict[str, object]:
    return {
        "id": item.id,
        "version": item.version,
        "category": item.category,
        "status": item.status,
        "selection_method": item.selection_method,
        "embedding_model": item.embedding.model,
        "embedding_revision": item.embedding.revision,
        "embedding_dimension": item.embedding.dimension,
        "holdout_ids": list(item.holdout_ids),
        "member_ids": list(item.member_ids),
        "scope_key": item.scope_key,
        "created_at_ms": item.created_at_ms,
    }


def match_json(result: MatchResult) -> dict[str, object]:
    return {
        "top_k": [_hit_json(hit) for hit in result.top_k],
        "category_scores": [_score_json(score) for score in result.category_scores],
        "labels": list(result.labels),
        "abstained": result.abstained,
        "abstain_reason": result.abstain_reason,
        "embedding_model": result.embedding.model,
        "embedding_revision": result.embedding.revision,
        "embedding_dimension": result.embedding.dimension,
        "score_kind": "cosine_similarity",
        "not_a_probability": True,
    }


def _hit_json(hit: MatchHit) -> dict[str, object]:
    return {
        "anchor_id": hit.anchor_id,
        "classification_id": hit.classification_id,
        "category": hit.category,
        "polarity": hit.polarity,
        "cosine_similarity": hit.cosine_similarity,
        "source_unit_id": hit.source_unit_id,
        "content_hash": hit.content_hash,
    }


def _score_json(score: CategoryScore) -> dict[str, object]:
    return {
        "category": score.category,
        "score": score.score,
        "margin": score.margin,
        "support_count": score.support_count,
        "independent_support": score.independent_support,
        "negative_signal": score.negative_signal,
        "top_similarity": score.top_similarity,
        "score_kind": "cosine_similarity",
        "not_a_probability": True,
    }
