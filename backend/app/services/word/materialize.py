"""Code-owned WordAction materializers. LLM never writes application state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult, WordAction
from app.serializers import utcnow
from app.services.word.actions import (
    SOURCE_TYPE_EXPERT_REVIEW_RESULT,
    persist_word_action,
)
from app.services.word.anchors import WordAnchor, word_anchor_from_job_request
from app.services.word.schemas import WordActionType
from app.services.word.tasks import paragraph_is_actionable


@dataclass(frozen=True)
class MaterializedWordAction:
    action_type: WordActionType
    content: str
    explanation: str | None


def format_expert_review_comment_content(
    *,
    kommentar: str,
    expert_namn: str,
    is_heading_suggestion: bool,
) -> str:
    text = kommentar.strip()
    if is_heading_suggestion or not expert_namn.strip():
        return text
    return f"{expert_namn.strip()}: {text}"


def expert_review_word_action_spec(
    row: ExpertgranskningResult,
) -> MaterializedWordAction | None:
    if row.is_rewrite_suggestion:
        content = (row.foreslagen_text or "").strip()
        if not content:
            return None
        explanation = format_expert_review_comment_content(
            kommentar=row.kommentar,
            expert_namn=row.expert_namn,
            is_heading_suggestion=row.is_heading_suggestion,
        ).strip() or None
        return MaterializedWordAction(
            action_type="replace",
            content=content,
            explanation=explanation,
        )
    if not (row.kommentar or "").strip():
        return None
    content = format_expert_review_comment_content(
        kommentar=row.kommentar,
        expert_namn=row.expert_namn,
        is_heading_suggestion=row.is_heading_suggestion,
    )
    if not content:
        return None
    return MaterializedWordAction(
        action_type="comment",
        content=content,
        explanation=None,
    )


async def materialize_word_action(
    session: AsyncSession,
    row: ExpertgranskningResult,
    *,
    request: dict | None = None,
    source_ordinal: int = 0,
    anchor: WordAnchor | None = None,
) -> WordAction | None:
    spec = expert_review_word_action_spec(row)
    if spec is None:
        return None
    if not paragraph_is_actionable(request, row.paragraph_index):
        return None
    frozen_anchor = (
        anchor
        if anchor is not None
        else word_anchor_from_job_request(request, row.paragraph_index)
    )
    return await persist_word_action(
        session,
        customer_id=row.customer_id,
        job_id=row.job_id,
        source_type=SOURCE_TYPE_EXPERT_REVIEW_RESULT,
        source_id=row.id,
        source_ordinal=source_ordinal,
        action_type=spec.action_type,
        content=spec.content,
        explanation=spec.explanation,
        anchor=frozen_anchor,
        created_at=row.created_at or utcnow(),
    )
