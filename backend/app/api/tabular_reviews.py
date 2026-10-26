"""Opt-in SSR Tabular Review API. No Jev or value extraction."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.services.clause_ssr.select import get_anchor_set, list_anchor_sets
from app.database.session import get_session
from app.database.tabular_review import TabularReview, TabularReviewCell, TabularReviewVerificationLabel
from app.schemas.tabular_review import (
    TabularReviewCellAction,
    TabularReviewColumnWrite,
    TabularReviewCreate,
    TabularReviewUpdate,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.owner_text_units import load_version_vectors
from app.services.overgraph.text_units import load_text_units
from app.services.tabular_review.access import require_tabular_review_kund
from app.services.tabular_review.run import fill_review
from app.services.tabular_review.serialize import (
    cell_out,
    event_out,
    label_out,
    review_out,
    review_summary,
)
from app.services.tabular_review.store import (
    TabularReviewError,
    add_column,
    create_review,
    create_verification_label,
    list_customer_documents,
    list_reviews,
    remove_column,
    require_review,
    set_cell_state,
    set_documents,
    update_review,
)
from app.services.tabular_review.types import ColumnSpec

router = APIRouter(prefix="/tabular-reviews", tags=["tabular-reviews"])


def _error(exc: TabularReviewError) -> HTTPException:
    status = 404 if str(exc) in {"review_not_found", "column_not_found", "document_not_found"} else 400
    return HTTPException(status_code=status, detail=str(exc))


async def _embeddings_from_catalog(document_version_id: str) -> dict[str, list[float]]:
    owner = get_owner_runtime().client
    if owner is not None:
        return await load_version_vectors(owner, document_version_id)
    rows = await asyncio.to_thread(
        load_text_units, require_knowledge(), document_version_id=document_version_id,
    )
    return {row.key: list(row.dense_vector) for row in rows if row.dense_vector}


async def _gated_review(session: AsyncSession, user: UserAccount, review_id: int):
    kund = await require_tabular_review_kund(session, user)
    try:
        review = await require_review(session, review_id, customer_id=kund.id)
    except TabularReviewError as exc:
        raise _error(exc) from exc
    return kund, review


async def _validate_clause_column(anchor_set_id: str, label: str) -> None:
    catalog = require_knowledge()
    anchor_set = await asyncio.to_thread(get_anchor_set, catalog, anchor_set_id)
    if anchor_set.status != "active":
        raise HTTPException(status_code=400, detail="anchor_set_not_active")
    if anchor_set.category != label:
        raise HTTPException(status_code=400, detail="label_not_in_anchor_set")


@router.get("/documents")
async def list_documents(
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    kund = await require_tabular_review_kund(session, user)
    return await list_customer_documents(session, customer_id=kund.id)


@router.get("/clause-anchors")
async def list_clause_anchors(
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    kund = await require_tabular_review_kund(session, user)
    catalog = require_knowledge()
    rows = await asyncio.to_thread(
        list_anchor_sets, catalog, customer_id=kund.id, active_only=True
    )
    return [
        {
            "id": row.id,
            "name": row.category,
            "category": row.category,
            "labels": [row.category],
            "version": str(row.version),
        }
        for row in rows
    ]


@router.get("")
async def list_tabular_reviews(
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    kund = await require_tabular_review_kund(session, user)
    rows = await list_reviews(session, customer_id=kund.id)
    return [review_summary(row) for row in rows]


@router.post("", status_code=201)
async def create_tabular_review(
    body: TabularReviewCreate,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    kund = await require_tabular_review_kund(session, user)
    try:
        review = await create_review(
            session,
            customer_id=kund.id,
            created_by_user_id=user.id,
            name=body.name,
            score_threshold=body.score_threshold,
        )
        if body.document_ids:
            await set_documents(session, review, body.document_ids)
        for index, column in enumerate(body.columns):
            await _validate_clause_column(column.anchor_set_id, column.label)
            await add_column(
                session,
                review,
                ColumnSpec(
                    column_id=None,
                    title=column.title,
                    anchor_set_id=column.anchor_set_id,
                    label=column.label,
                    polarity=column.polarity,
                    allow_abstain=column.allow_abstain,
                    abstain_margin=column.abstain_margin,
                    sort_order=index,
                ),
            )
        await session.commit()
        loaded = await require_review(session, review.id, customer_id=kund.id)
    except TabularReviewError as exc:
        raise _error(exc) from exc
    return review_out(loaded)


@router.get("/{review_id}")
async def get_tabular_review(
    review_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _kund, review = await _gated_review(session, user, review_id)
    return review_out(review, include_candidates=True)


@router.patch("/{review_id}")
async def patch_tabular_review(
    review_id: int,
    body: TabularReviewUpdate,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    kund, review = await _gated_review(session, user, review_id)
    try:
        await update_review(
            session,
            review,
            name=body.name,
            score_threshold=body.score_threshold,
            sort_key=body.sort_key,
            sort_dir=body.sort_dir,
            filter_json=body.filter_json,
        )
        if body.document_ids is not None:
            await set_documents(session, review, body.document_ids)
        await session.commit()
        loaded = await require_review(session, review.id, customer_id=kund.id)
    except TabularReviewError as exc:
        raise _error(exc) from exc
    return review_out(loaded, include_candidates=True)


@router.delete("/{review_id}", status_code=204)
async def delete_tabular_review(
    review_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    _kund, review = await _gated_review(session, user, review_id)
    await session.delete(review)
    await session.commit()


@router.post("/{review_id}/columns", status_code=201)
async def add_review_column(
    review_id: int,
    body: TabularReviewColumnWrite,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    kund, review = await _gated_review(session, user, review_id)
    try:
        await add_column(
            session,
            review,
            ColumnSpec(
                column_id=None,
                title=body.title,
                anchor_set_id=body.anchor_set_id,
                label=body.label,
                polarity=body.polarity,
                allow_abstain=body.allow_abstain,
                abstain_margin=body.abstain_margin,
                sort_order=len(review.columns),
            ),
        )
        await session.commit()
        loaded = await require_review(session, review.id, customer_id=kund.id)
    except TabularReviewError as exc:
        raise _error(exc) from exc
    return review_out(loaded, include_candidates=True)


@router.delete("/{review_id}/columns/{column_id}", status_code=204)
async def delete_review_column(
    review_id: int,
    column_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    _kund, review = await _gated_review(session, user, review_id)
    try:
        await remove_column(session, review, column_id)
    except TabularReviewError as exc:
        raise _error(exc) from exc
    await session.commit()


@router.post("/{review_id}/run")
async def run_tabular_review(
    review_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    kund, review = await _gated_review(session, user, review_id)
    embeddings = {}
    for row in review.rows:
        embeddings[row.document_id] = await _embeddings_from_catalog(
            row.document_version_id,
        )
    factory = async_sessionmaker(session.bind, expire_on_commit=False, class_=AsyncSession)
    await session.commit()
    try:
        await fill_review(
            factory,
            review_id,
            catalog=require_knowledge(),
            embeddings_by_document=embeddings,
            customer_id=kund.id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    async with factory() as loaded_session:
        loaded = await require_review(loaded_session, review_id, customer_id=kund.id)
        return review_out(loaded, include_candidates=True)


async def _cell_for_review(session: AsyncSession, review_id: int, cell_id: int) -> TabularReviewCell:
    cell = await session.get(TabularReviewCell, cell_id)
    if cell is None or cell.review_id != review_id:
        raise HTTPException(status_code=404, detail="cell_not_found")
    return cell


@dataclass
class LoadedReviewCell:
    review: TabularReview
    cell: TabularReviewCell
    user: UserAccount
    session: AsyncSession


async def loaded_review_cell(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LoadedReviewCell:
    _kund, review = await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    return LoadedReviewCell(review=review, cell=cell, user=user, session=session)


@router.get("/{review_id}/cells/{cell_id}")
async def get_review_cell(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    await session.refresh(cell, attribute_names=["candidates", "events"])
    return {
        **cell_out(cell, include_candidates=True),
        "history": [event_out(event) for event in cell.events],
    }


@router.post("/{review_id}/cells/{cell_id}/approve")
async def approve_cell(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    kund, review = await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    column = next((item for item in review.columns if item.id == cell.column_id), None)
    if column is None:
        raise HTTPException(status_code=404, detail="column_not_found")
    await set_cell_state(session, cell, actor_user_id=user.id, review_state="approved")
    try:
        label = await create_verification_label(
            session,
            review=review,
            cell=cell,
            column=column,
            actor_user_id=user.id,
            verdict="match",
        )
    except TabularReviewError as exc:
        raise _error(exc) from exc
    await session.commit()
    await session.refresh(cell, attribute_names=["candidates"])
    return {**cell_out(cell, include_candidates=True), "verification_label": label_out(label)}


@router.post("/{review_id}/cells/{cell_id}/reject")
async def reject_cell(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    kund, review = await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    column = next((item for item in review.columns if item.id == cell.column_id), None)
    if column is None:
        raise HTTPException(status_code=404, detail="column_not_found")
    await set_cell_state(session, cell, actor_user_id=user.id, review_state="rejected")
    try:
        label = await create_verification_label(
            session,
            review=review,
            cell=cell,
            column=column,
            actor_user_id=user.id,
            verdict="not_match",
        )
    except TabularReviewError as exc:
        raise _error(exc) from exc
    await session.commit()
    await session.refresh(cell, attribute_names=["candidates"])
    return {**cell_out(cell, include_candidates=True), "verification_label": label_out(label)}


@router.post("/{review_id}/cells/{cell_id}/flag")
async def flag_cell(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    await set_cell_state(session, cell, actor_user_id=user.id, flagged=not cell.flagged)
    await session.commit()
    await session.refresh(cell, attribute_names=["candidates"])
    return cell_out(cell)


@router.post("/{review_id}/cells/{cell_id}/lock")
async def lock_cell(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    await set_cell_state(session, cell, actor_user_id=user.id, locked=not cell.locked)
    await session.commit()
    await session.refresh(cell, attribute_names=["candidates"])
    return cell_out(cell)


@router.post("/{review_id}/cells/{cell_id}/note")
async def note_cell(
    body: TabularReviewCellAction,
    loaded: LoadedReviewCell = Depends(loaded_review_cell),
) -> dict:
    await set_cell_state(
        loaded.session,
        loaded.cell,
        actor_user_id=loaded.user.id,
        note=body.note or "",
    )
    await loaded.session.commit()
    await loaded.session.refresh(loaded.cell, attribute_names=["candidates"])
    return cell_out(loaded.cell)


@router.get("/{review_id}/cells/{cell_id}/history")
async def cell_history(
    review_id: int,
    cell_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _gated_review(session, user, review_id)
    cell = await _cell_for_review(session, review_id, cell_id)
    await session.refresh(cell, attribute_names=["events"])
    return [event_out(event) for event in cell.events]


@router.get("/{review_id}/labels")
async def list_labels(
    review_id: int,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    kund, _review = await _gated_review(session, user, review_id)
    stmt = select(TabularReviewVerificationLabel).where(
        TabularReviewVerificationLabel.review_id == review_id,
        TabularReviewVerificationLabel.customer_id == kund.id,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [label_out(row) for row in rows]
