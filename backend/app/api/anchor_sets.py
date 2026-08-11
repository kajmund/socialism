"""SSR anchor library CRUD, calibration corpus, and test bench."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration, SsrAnchorCalibrationItem, SsrAnchorPoolItem, SsrAnchorSet
from app.database.session import get_session
from app.schemas.domain import (
    SsrAnchorCalibrationItemCreate,
    SsrAnchorCalibrationItemOut,
    SsrAnchorCalibrationItemUpdate,
    SsrAnchorPoolItemCreate,
    SsrAnchorPoolItemOut,
    SsrAnchorPublishGateDetail,
    SsrAnchorPublishRequest,
    SsrAnchorSetCreate,
    SsrAnchorSetOut,
    SsrAnchorSetUpdate,
    SsrAnchorTestRequest,
    format_date,
)
from app.serializers import utcnow
from app.services.anchor_calibration import (
    PublishGateError,
    assert_publish_allowed,
    calibration_validation_status,
    clear_calibration_results,
    finalize_publish_calibration,
    run_calibration_test,
    validation_snapshot,
)
from app.services.anchor_pool import (
    AnchorPoolError,
    add_pool_item,
    centroid_vectors_for_set,
    pool_items_for_set,
    remove_pool_item,
)
from app.services.anchor_store import (
    calibration_items,
    ensure_default_anchor_sets,
    row_to_anchor_set,
    validate_anchor_payload,
)
from app.services.playground import rate_case
from app.services.prompt_store import get_active_configuration
from app.services.ssr import rate_texts

router = APIRouter(prefix="/anchor-sets", tags=["anchor-sets"])


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


async def _serialize(
    session: AsyncSession,
    row: SsrAnchorSet,
) -> SsrAnchorSetOut:
    items = await calibration_items(session, row.id)
    count = len(items)
    return SsrAnchorSetOut(
        id=row.id,
        name=row.name,
        kind=row.kind,  # type: ignore[arg-type]
        locale=row.locale,  # type: ignore[arg-type]
        version=row.version,
        labels=[str(x) for x in (row.labels or [])],
        statements=[str(x) for x in (row.statements or [])],
        status=row.status,  # type: ignore[arg-type]
        pool_revision=int(row.pool_revision or 0),
        calibration_accuracy=row.calibration_accuracy,
        calibration_tested_at=_dt(row.calibration_tested_at) or None,
        calibration_pool_revision=row.calibration_pool_revision,
        calibration_n_at_test=row.calibration_n_at_test,
        calibration_publish_override=bool(row.calibration_publish_override),
        calibration_item_count=count,
        validation_status=calibration_validation_status(row, calibration_count=count),
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


async def _active_ssr_temperature(session: AsyncSession) -> float:
    config = await get_active_configuration(session)
    if config is None:
        return 0.1
    return float(config.ssr_temperature)


def _publish_gate_http(exc: PublishGateError) -> HTTPException:
    status = 409 if exc.requires_acknowledgement else 400
    return HTTPException(
        status_code=status,
        detail=SsrAnchorPublishGateDetail(
            code=exc.code,
            detail=str(exc),
            accuracy=exc.accuracy,
            missing_labels=exc.missing_labels,
            calibration_count=exc.calibration_count,
            requires_acknowledgement=exc.requires_acknowledgement,
        ).model_dump(),
    )


def _serialize_pool_item(row: SsrAnchorPoolItem) -> SsrAnchorPoolItemOut:
    return SsrAnchorPoolItemOut(
        id=row.id,
        anchor_set_id=row.anchor_set_id,
        label=row.label,
        text=row.text,
        source_type=row.source_type,  # type: ignore[arg-type]
        source_run_id=row.source_run_id,
        source_attempt_id=row.source_attempt_id,
        source_variant_id=row.source_variant_id,
        source_ref=dict(row.source_ref or {}),
        created_at=_dt(row.created_at),
    )


def _serialize_calibration(row: SsrAnchorCalibrationItem) -> SsrAnchorCalibrationItemOut:
    return SsrAnchorCalibrationItemOut(
        id=row.id,
        text=row.text,
        human_label=row.human_label,
        sort_order=int(row.sort_order),
        created_at=format_date(row.created_at) if row.created_at else "",
    )


async def _get_row(session: AsyncSession, anchor_set_id: int) -> SsrAnchorSet:
    row = await session.get(SsrAnchorSet, anchor_set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Anchor set not found")
    return row


async def _assert_not_referenced(session: AsyncSession, anchor_set_id: int) -> None:
    result = await session.execute(select(Configuration))
    for config in result.scalars().all():
        refs = dict(config.anchor_sets or {})
        for block in refs.values():
            if not isinstance(block, dict):
                continue
            if int(block.get("tone") or 0) == anchor_set_id or int(block.get("style") or 0) == anchor_set_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Anchor set {anchor_set_id} is referenced by configuration "
                        f"'{config.name}' (id={config.id})"
                    ),
                )


@router.get("", response_model=list[SsrAnchorSetOut])
async def list_anchor_sets(
    kind: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[SsrAnchorSetOut]:
    await ensure_default_anchor_sets(session)
    stmt = select(SsrAnchorSet).order_by(
        SsrAnchorSet.status.desc(),
        SsrAnchorSet.kind.asc(),
        SsrAnchorSet.locale.asc(),
        SsrAnchorSet.updated_at.desc(),
    )
    if kind is not None:
        stmt = stmt.where(SsrAnchorSet.kind == kind)
    if locale is not None:
        stmt = stmt.where(SsrAnchorSet.locale == locale)
    if status is not None:
        stmt = stmt.where(SsrAnchorSet.status == status)
    result = await session.execute(stmt)
    return [await _serialize(session, row) for row in result.scalars().all()]


@router.get("/{anchor_set_id}", response_model=SsrAnchorSetOut)
async def get_anchor_set(
    anchor_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorSetOut:
    return await _serialize(session, await _get_row(session, anchor_set_id))


@router.post("", response_model=SsrAnchorSetOut, status_code=201)
async def create_anchor_set(
    body: SsrAnchorSetCreate,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorSetOut:
    try:
        validate_anchor_payload(
            kind=body.kind,
            locale=body.locale,
            labels=body.labels,
            statements=body.statements,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = utcnow()
    row = SsrAnchorSet(
        name=body.name,
        kind=body.kind,
        locale=body.locale,
        version=body.version,
        labels=list(body.labels),
        statements=list(body.statements),
        status=body.status,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return await _serialize(session, row)


@router.patch("/{anchor_set_id}", response_model=SsrAnchorSetOut)
async def update_anchor_set(
    anchor_set_id: int,
    body: SsrAnchorSetUpdate,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorSetOut:
    row = await _get_row(session, anchor_set_id)
    if row.status == "published":
        raise HTTPException(
            status_code=409,
            detail="Published anchor sets are immutable — duplicate to edit",
        )
    data = body.model_dump(exclude_unset=True)
    labels = data.get("labels", row.labels)
    statements = data.get("statements", row.statements)
    if "labels" in data or "statements" in data:
        try:
            validate_anchor_payload(
                kind=row.kind,  # type: ignore[arg-type]
                locale=row.locale,  # type: ignore[arg-type]
                labels=list(labels),
                statements=list(statements),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return await _serialize(session, row)


@router.post("/{anchor_set_id}/publish", response_model=SsrAnchorSetOut)
async def publish_anchor_set(
    anchor_set_id: int,
    body: SsrAnchorPublishRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorSetOut:
    row = await _get_row(session, anchor_set_id)
    try:
        validate_anchor_payload(
            kind=row.kind,  # type: ignore[arg-type]
            locale=row.locale,  # type: ignore[arg-type]
            labels=[str(x) for x in (row.labels or [])],
            statements=[str(x) for x in (row.statements or [])],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    acknowledge = bool(body.acknowledge_warnings) if body is not None else False
    temperature = await _active_ssr_temperature(session)
    try:
        await assert_publish_allowed(
            session,
            row,
            temperature=temperature,
            acknowledge_warnings=acknowledge,
        )
    except PublishGateError as exc:
        raise _publish_gate_http(exc) from exc

    await finalize_publish_calibration(
        session,
        row,
        temperature=temperature,
        acknowledge_warnings=acknowledge,
    )
    row.status = "published"
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return await _serialize(session, row)


@router.post("/{anchor_set_id}/calibration/run")
async def run_anchor_calibration(
    anchor_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Run calibration test against centroid anchors and persist metrics."""
    row = await _get_row(session, anchor_set_id)
    temperature = await _active_ssr_temperature(session)
    try:
        result = await run_calibration_test(
            session,
            row,
            temperature=temperature,
            persist=True,
        )
    except PublishGateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.updated_at = utcnow()
    await session.commit()
    return result


@router.post("/{anchor_set_id}/duplicate", response_model=SsrAnchorSetOut, status_code=201)
async def duplicate_anchor_set(
    anchor_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorSetOut:
    source = await _get_row(session, anchor_set_id)
    now = utcnow()
    row = SsrAnchorSet(
        name=f"{source.name} (kopia)",
        kind=source.kind,
        locale=source.locale,
        version=source.version,
        labels=list(source.labels or []),
        statements=list(source.statements or []),
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    for item in await calibration_items(session, source.id):
        session.add(
            SsrAnchorCalibrationItem(
                anchor_set_id=row.id,
                text=item.text,
                human_label=item.human_label,
                sort_order=item.sort_order,
                created_at=now,
            )
        )
    await session.commit()
    await session.refresh(row)
    return await _serialize(session, row)


@router.delete("/{anchor_set_id}", status_code=204)
async def delete_anchor_set(
    anchor_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_row(session, anchor_set_id)
    await _assert_not_referenced(session, anchor_set_id)
    await session.delete(row)
    await session.commit()


@router.get(
    "/{anchor_set_id}/calibration",
    response_model=list[SsrAnchorCalibrationItemOut],
)
async def list_calibration(
    anchor_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[SsrAnchorCalibrationItemOut]:
    await _get_row(session, anchor_set_id)
    rows = await calibration_items(session, anchor_set_id)
    return [_serialize_calibration(r) for r in rows]


@router.post(
    "/{anchor_set_id}/calibration",
    response_model=SsrAnchorCalibrationItemOut,
    status_code=201,
)
async def create_calibration_item(
    anchor_set_id: int,
    body: SsrAnchorCalibrationItemCreate,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorCalibrationItemOut:
    row = await _get_row(session, anchor_set_id)
    allowed = {str(x) for x in (row.labels or [])}
    if body.human_label not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"human_label must be one of: {', '.join(sorted(allowed))}",
        )
    item = SsrAnchorCalibrationItem(
        anchor_set_id=anchor_set_id,
        text=body.text,
        human_label=body.human_label,
        sort_order=body.sort_order,
        created_at=utcnow(),
    )
    session.add(item)
    clear_calibration_results(row)
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(item)
    return _serialize_calibration(item)


@router.patch(
    "/{anchor_set_id}/calibration/{item_id}",
    response_model=SsrAnchorCalibrationItemOut,
)
async def update_calibration_item(
    anchor_set_id: int,
    item_id: int,
    body: SsrAnchorCalibrationItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorCalibrationItemOut:
    row = await _get_row(session, anchor_set_id)
    item = await session.get(SsrAnchorCalibrationItem, item_id)
    if item is None or item.anchor_set_id != anchor_set_id:
        raise HTTPException(status_code=404, detail="Calibration item not found")
    data = body.model_dump(exclude_unset=True)
    if "human_label" in data:
        allowed = {str(x) for x in (row.labels or [])}
        if data["human_label"] not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"human_label must be one of: {', '.join(sorted(allowed))}",
            )
    for key, value in data.items():
        setattr(item, key, value)
    clear_calibration_results(row)
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(item)
    return _serialize_calibration(item)


@router.delete("/{anchor_set_id}/calibration/{item_id}", status_code=204)
async def delete_calibration_item(
    anchor_set_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    await _get_row(session, anchor_set_id)
    item = await session.get(SsrAnchorCalibrationItem, item_id)
    if item is None or item.anchor_set_id != anchor_set_id:
        raise HTTPException(status_code=404, detail="Calibration item not found")
    row = await _get_row(session, anchor_set_id)
    await session.delete(item)
    clear_calibration_results(row)
    row.updated_at = utcnow()
    await session.commit()


@router.post("/{anchor_set_id}/test")
async def test_anchor_set(
    anchor_set_id: int,
    body: SsrAnchorTestRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await _get_row(session, anchor_set_id)
    texts = [t.strip() for t in body.texts if t.strip()]
    if not texts:
        raise HTTPException(status_code=400, detail="texts must contain non-empty strings")

    human_labels: list[str] | None = None
    if body.use_calibration:
        items = await calibration_items(session, anchor_set_id)
        if not items:
            raise HTTPException(status_code=400, detail="No calibration items on this anchor set")
        texts = [i.text for i in items]
        human_labels = [i.human_label for i in items]

    anchor = row_to_anchor_set(row)
    anchor_vectors = await centroid_vectors_for_set(session, row)
    if human_labels is not None:
        result = await rate_case(
            texts,
            dimension=row.kind,  # type: ignore[arg-type]
            locale=row.locale,
            labels=list(anchor.labels),
            statements=list(anchor.statements),
            temperature=body.temperature,
            human_labels=human_labels,
            anchor_vectors=anchor_vectors,
        )
        return result

    result = await rate_texts(
        texts,
        anchor,
        temperature=body.temperature,
        anchor_vectors=anchor_vectors,
    )
    per_text = [
        {
            "text": text,
            "pmf": pmf,
            "predicted_label": max(pmf.items(), key=lambda kv: kv[1])[0] if pmf else "",
        }
        for text, pmf in zip(texts, result.per_text_pmfs, strict=True)
    ]
    return {
        "anchor_set_id": row.id,
        "anchor_set_name": result.anchor_set_name,
        "anchor_set_version": result.anchor_set_version,
        "labels": list(result.labels),
        "shares": result.shares,
        "per_text": per_text,
    }


@router.get("/{anchor_set_id}/pool", response_model=list[SsrAnchorPoolItemOut])
async def list_pool_items(
    anchor_set_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[SsrAnchorPoolItemOut]:
    """List pool items. Published sets allow append/remove on the pool only."""
    await _get_row(session, anchor_set_id)
    rows = await pool_items_for_set(session, anchor_set_id)
    return [_serialize_pool_item(r) for r in rows]


@router.post(
    "/{anchor_set_id}/pool",
    response_model=SsrAnchorPoolItemOut,
    status_code=201,
)
async def create_pool_item(
    anchor_set_id: int,
    body: SsrAnchorPoolItemCreate,
    session: AsyncSession = Depends(get_session),
) -> SsrAnchorPoolItemOut:
    """Append a pool anchor. Live immediately on published sets (base statements stay locked)."""
    try:
        item = await add_pool_item(
            session,
            anchor_set_id=anchor_set_id,
            label=body.label,
            text=body.text,
            source_type=body.source_type,
            source_run_id=body.source_run_id,
            source_attempt_id=body.source_attempt_id,
            source_variant_id=body.source_variant_id,
            source_ref=body.source_ref,
            add_to_calibration=body.add_to_calibration,
        )
    except AnchorPoolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(item)
    return _serialize_pool_item(item)


@router.delete("/{anchor_set_id}/pool/{item_id}", status_code=204)
async def delete_pool_item(
    anchor_set_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await remove_pool_item(session, anchor_set_id=anchor_set_id, item_id=item_id)
    except AnchorPoolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
