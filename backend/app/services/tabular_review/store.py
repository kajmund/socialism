"""Persist and load Tabular Review objects. No external calls."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, SsrAnchorSet
from app.database.tabular_review import (
    TabularReview,
    TabularReviewCandidate,
    TabularReviewCell,
    TabularReviewCellEvent,
    TabularReviewColumn,
    TabularReviewRow,
    TabularReviewScoreCache,
    TabularReviewVerificationLabel,
)
from app.serializers import utcnow
from app.services.document_find.group import dedupe_document_ids
from app.services.knowledge.persistence import get_current_document_version
from app.services.tabular_review.locators import locator_payload
from app.services.tabular_review.types import (
    DEFAULT_SCORE_THRESHOLD,
    CellDecision,
    ColumnSpec,
    DocumentRow,
    ReviewInputs,
    ReviewState,
)


class TabularReviewError(ValueError):
    """Invalid review mutation."""


async def list_reviews(session: AsyncSession, *, customer_id: int) -> list[TabularReview]:
    stmt = (
        select(TabularReview)
        .where(TabularReview.customer_id == customer_id)
        .options(selectinload(TabularReview.columns), selectinload(TabularReview.rows))
        .order_by(TabularReview.updated_at.desc(), TabularReview.id.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_review(session: AsyncSession, review_id: int) -> TabularReview | None:
    stmt = (
        select(TabularReview)
        .where(TabularReview.id == review_id)
        .options(
            selectinload(TabularReview.columns),
            selectinload(TabularReview.rows),
            selectinload(TabularReview.cells).selectinload(TabularReviewCell.candidates),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def require_review(
    session: AsyncSession, review_id: int, *, customer_id: int
) -> TabularReview:
    review = await get_review(session, review_id)
    if review is None or review.customer_id != customer_id:
        raise TabularReviewError("review_not_found")
    return review


async def create_review(
    session: AsyncSession,
    *,
    customer_id: int,
    created_by_user_id: str,
    name: str,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> TabularReview:
    title = name.strip()
    if not title:
        raise TabularReviewError("name_required")
    review = TabularReview(
        customer_id=customer_id,
        created_by_user_id=created_by_user_id,
        name=title,
        score_threshold=score_threshold,
        filter_json={},
    )
    session.add(review)
    await session.flush()
    return review


async def update_review(
    session: AsyncSession,
    review: TabularReview,
    *,
    name: str | None = None,
    score_threshold: float | None = None,
    sort_key: str | None = None,
    sort_dir: str | None = None,
    filter_json: dict | None = None,
) -> TabularReview:
    if name is not None:
        title = name.strip()
        if not title:
            raise TabularReviewError("name_required")
        review.name = title
    if score_threshold is not None:
        review.score_threshold = score_threshold
    if sort_key is not None:
        review.sort_key = sort_key
    if sort_dir is not None:
        if sort_dir not in ("asc", "desc"):
            raise TabularReviewError("invalid_sort_dir")
        review.sort_dir = sort_dir
    if filter_json is not None:
        review.filter_json = filter_json
    review.updated_at = utcnow()
    return review


async def add_column(session: AsyncSession, review: TabularReview, spec: ColumnSpec) -> TabularReviewColumn:
    anchor = await session.get(SsrAnchorSet, spec.anchor_set_id)
    if anchor is None:
        raise TabularReviewError("anchor_set_not_found")
    labels = [str(item) for item in (anchor.labels or [])]
    if spec.label not in labels:
        raise TabularReviewError("label_not_in_anchor_set")
    current = await _columns_for_review(session, review.id)
    order = spec.sort_order if spec.sort_order else len(current)
    column = TabularReviewColumn(
        review_id=review.id,
        title=spec.title.strip() or spec.label,
        anchor_set_id=spec.anchor_set_id,
        label=spec.label,
        polarity=spec.polarity,
        allow_abstain=spec.allow_abstain,
        abstain_margin=spec.abstain_margin,
        sort_order=order,
    )
    session.add(column)
    review.updated_at = utcnow()
    await session.flush()
    return column


async def remove_column(session: AsyncSession, review: TabularReview, column_id: int) -> None:
    current = await _columns_for_review(session, review.id)
    column = next((item for item in current if item.id == column_id), None)
    if column is None:
        raise TabularReviewError("column_not_found")
    await session.delete(column)
    review.updated_at = utcnow()


async def _document_row(
    session: AsyncSession, document_id: str, *, customer_id: int
) -> DocumentRow:
    document = await session.get(CanonicalDocumentRecord, document_id)
    if document is None:
        raise TabularReviewError("document_not_found")
    if document.customer_id not in (None, customer_id):
        raise TabularReviewError("document_not_found")
    version = await get_current_document_version(session, document_id)
    if version is None:
        raise TabularReviewError("document_version_missing")
    return DocumentRow(
        document_id=document.id,
        document_version_id=version.id,
        title=document.title,
        source_object_id=document.source_object_id,
    )


async def _rows_for_review(session: AsyncSession, review_id: int) -> list[TabularReviewRow]:
    stmt = select(TabularReviewRow).where(TabularReviewRow.review_id == review_id)
    return list((await session.execute(stmt)).scalars().all())


async def _columns_for_review(session: AsyncSession, review_id: int) -> list[TabularReviewColumn]:
    stmt = (
        select(TabularReviewColumn)
        .where(TabularReviewColumn.review_id == review_id)
        .order_by(TabularReviewColumn.sort_order.asc(), TabularReviewColumn.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def set_documents(
    session: AsyncSession,
    review: TabularReview,
    document_ids: Sequence[str],
) -> list[TabularReviewRow]:
    ordered = dedupe_document_ids(document_ids)
    existing = {row.document_id: row for row in await _rows_for_review(session, review.id)}
    keep = set(ordered)
    for document_id, row in existing.items():
        if document_id not in keep:
            await session.delete(row)
    created: list[TabularReviewRow] = []
    for document_id in ordered:
        if document_id in existing:
            created.append(existing[document_id])
            continue
        spec = await _document_row(session, document_id, customer_id=review.customer_id)
        row = TabularReviewRow(
            review_id=review.id,
            document_id=spec.document_id,
            document_version_id=spec.document_version_id,
            title=spec.title,
            source_object_id=spec.source_object_id,
        )
        session.add(row)
        created.append(row)
    review.updated_at = utcnow()
    await session.flush()
    return created


async def list_customer_documents(
    session: AsyncSession, *, customer_id: int
) -> list[dict[str, object]]:
    stmt = (
        select(CanonicalDocumentRecord, DocumentVersionRecord)
        .join(
            DocumentVersionRecord,
            DocumentVersionRecord.document_id == CanonicalDocumentRecord.id,
        )
        .where(
            CanonicalDocumentRecord.customer_id == customer_id,
            DocumentVersionRecord.superseded_at.is_(None),
        )
        .order_by(CanonicalDocumentRecord.title.asc(), CanonicalDocumentRecord.id.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "document_id": document.id,
            "title": document.title,
            "document_version_id": version.id,
            "source_object_id": document.source_object_id,
            "mime_type": version.mime_type,
        }
        for document, version in rows
    ]


async def load_inputs(session: AsyncSession, review: TabularReview, *, embedding_model: str) -> ReviewInputs:
    rows_by_id = {row.id: row for row in review.rows}
    locked = frozenset(
        (rows_by_id[cell.row_id].document_id, cell.column_id)
        for cell in review.cells
        if cell.locked and cell.row_id in rows_by_id
    )
    columns = tuple(
        ColumnSpec(
            column_id=column.id,
            title=column.title,
            anchor_set_id=column.anchor_set_id,
            label=column.label,
            polarity=column.polarity,  # type: ignore[arg-type]
            allow_abstain=column.allow_abstain,
            abstain_margin=column.abstain_margin,
            sort_order=column.sort_order,
        )
        for column in review.columns
    )
    documents = tuple(
        DocumentRow(
            document_id=row.document_id,
            document_version_id=row.document_version_id,
            title=row.title,
            source_object_id=row.source_object_id,
        )
        for row in review.rows
    )
    return ReviewInputs(
        review_id=review.id,
        customer_id=review.customer_id,
        name=review.name,
        score_threshold=review.score_threshold,
        columns=columns,
        documents=documents,
        locked_cell_keys=locked,
        embedding_model=embedding_model,
    )


async def cached_scores(session: AsyncSession, keys: Sequence[str]) -> dict[str, float]:
    if not keys:
        return {}
    stmt = select(TabularReviewScoreCache).where(TabularReviewScoreCache.cache_key.in_(list(keys)))
    rows = (await session.execute(stmt)).scalars().all()
    return {row.cache_key: float(row.similarity) for row in rows}


async def put_cached_scores(
    session: AsyncSession,
    entries: Sequence[TabularReviewScoreCache],
) -> None:
    for entry in entries:
        await session.merge(entry)


def _cell_for(review: TabularReview, row_id: int, column_id: int) -> TabularReviewCell | None:
    return next(
        (cell for cell in review.cells if cell.row_id == row_id and cell.column_id == column_id),
        None,
    )


async def persist_decision(
    session: AsyncSession,
    *,
    review: TabularReview,
    row: TabularReviewRow,
    column: TabularReviewColumn,
    decision: CellDecision,
) -> TabularReviewCell:
    cell = _cell_for(review, row.id, column.id)
    if cell is not None and cell.locked:
        return cell
    selected = decision.selected
    if cell is None:
        cell = TabularReviewCell(review_id=review.id, row_id=row.id, column_id=column.id)
        session.add(cell)
        await session.flush()
    cell.status = decision.status
    cell.similarity = selected.similarity if selected else None
    cell.text_unit_id = selected.text_unit_id if selected else None
    cell.exact_text = selected.exact_text if selected else None
    cell.source_json = locator_payload(selected.source) if selected else {}
    cell.computed_at = utcnow()
    await session.execute(
        delete(TabularReviewCandidate).where(TabularReviewCandidate.cell_id == cell.id)
    )
    for rank, candidate in enumerate(decision.candidates, start=1):
        session.add(
            TabularReviewCandidate(
                cell_id=cell.id,
                rank=rank,
                text_unit_id=candidate.text_unit_id,
                exact_text=candidate.exact_text,
                similarity=candidate.similarity,
                polarity=candidate.polarity,
                source_json=locator_payload(candidate.source),
            )
        )
    return cell


async def record_event(
    session: AsyncSession,
    cell: TabularReviewCell,
    *,
    actor_user_id: str,
    action: str,
    payload: dict | None = None,
) -> TabularReviewCellEvent:
    event = TabularReviewCellEvent(
        cell_id=cell.id,
        actor_user_id=actor_user_id,
        action=action,
        payload=payload or {},
    )
    session.add(event)
    return event


async def set_cell_state(
    session: AsyncSession,
    cell: TabularReviewCell,
    *,
    actor_user_id: str,
    review_state: ReviewState | None = None,
    locked: bool | None = None,
    flagged: bool | None = None,
    note: str | None = None,
) -> TabularReviewCell:
    payload: dict[str, object] = {}
    if review_state is not None:
        cell.review_state = review_state
        payload["review_state"] = review_state
    if locked is not None:
        cell.locked = locked
        payload["locked"] = locked
    if flagged is not None:
        cell.flagged = flagged
        payload["flagged"] = flagged
    if note is not None:
        cell.note = note
        payload["note"] = note
    action = next(iter(payload), "update")
    await record_event(session, cell, actor_user_id=actor_user_id, action=action, payload=payload)
    return cell


async def create_verification_label(
    session: AsyncSession,
    *,
    review: TabularReview,
    cell: TabularReviewCell,
    column: TabularReviewColumn,
    actor_user_id: str,
    verdict: str,
) -> TabularReviewVerificationLabel:
    if not cell.text_unit_id:
        raise TabularReviewError("text_unit_required")
    label = TabularReviewVerificationLabel(
        customer_id=review.customer_id,
        created_by_user_id=actor_user_id,
        review_id=review.id,
        cell_id=cell.id,
        anchor_set_id=column.anchor_set_id,
        label=column.label,
        text_unit_id=cell.text_unit_id,
        verdict=verdict,
        activated_as_ssr_anchor=False,
    )
    session.add(label)
    await record_event(
        session,
        cell,
        actor_user_id=actor_user_id,
        action="verification_label",
        payload={"verdict": verdict, "text_unit_id": cell.text_unit_id, "activated_as_ssr_anchor": False},
    )
    return label
