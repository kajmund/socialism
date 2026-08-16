"""SSR misclassification flags: wrong predictions → pool calibration workflow."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SsrMisclassificationFlag
from app.serializers import utcnow
from app.services.anchor_pool import (
    AnchorPoolError,
    AnchorPoolSourceType,
    add_pool_item,
    resolve_active_anchor_set_ids,
    validate_label,
)
from app.services.anchor_store import require_anchor_set_row
from app.services.report.locale import ReportLocale, normalize_locale

MisclassificationStatus = Literal["open", "dismissed", "resolved"]
MisclassificationKind = Literal["tone", "style"]


class MisclassificationFlagError(RuntimeError):
    """Raised when flag create/update fails validation."""


def serialize_flag(flag: SsrMisclassificationFlag) -> dict[str, Any]:
    return {
        "id": flag.id,
        "anchor_set_id": flag.anchor_set_id,
        "kind": flag.kind,
        "text": flag.text,
        "predicted_label": flag.predicted_label,
        "expected_label": flag.expected_label,
        "source_type": flag.source_type,
        "source_ref": dict(flag.source_ref or {}),
        "source_run_id": flag.source_run_id,
        "source_attempt_id": flag.source_attempt_id,
        "source_variant_id": flag.source_variant_id,
        "status": flag.status,
        "pool_item_id": flag.pool_item_id,
        "created_at": flag.created_at.isoformat() if flag.created_at else "",
        "resolved_at": flag.resolved_at.isoformat() if flag.resolved_at else None,
    }


async def create_flag(
    session: AsyncSession,
    *,
    kind: MisclassificationKind,
    text: str,
    predicted_label: str,
    expected_label: str,
    source_type: AnchorPoolSourceType,
    source_ref: dict[str, Any],
    source_run_id: int,
    source_attempt_id: str,
    source_variant_id: str,
    locale: ReportLocale,
) -> SsrMisclassificationFlag:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise MisclassificationFlagError("text must be non-empty")
    if predicted_label.strip() == expected_label.strip():
        raise MisclassificationFlagError(
            "predicted_label and expected_label must differ"
        )

    loc = normalize_locale(locale)
    refs = await resolve_active_anchor_set_ids(session, loc)

    anchor_set_id = refs[kind]
    row = await require_anchor_set_row(session, anchor_set_id)
    if row.kind != kind:
        raise MisclassificationFlagError(
            f"Active {kind} anchor set {anchor_set_id} has kind {row.kind!r}"
        )
    try:
        validate_label(row, expected_label)
        validate_label(row, predicted_label)
    except AnchorPoolError as exc:
        raise MisclassificationFlagError(str(exc)) from exc

    flag = SsrMisclassificationFlag(
        anchor_set_id=anchor_set_id,
        kind=kind,
        text=cleaned,
        predicted_label=predicted_label.strip(),
        expected_label=expected_label.strip(),
        source_type=source_type,
        source_ref=source_ref,
        source_run_id=source_run_id,
        source_attempt_id=source_attempt_id,
        source_variant_id=source_variant_id,
        status="open",
        created_at=utcnow(),
    )
    session.add(flag)
    await session.flush()
    return flag


async def list_flags(
    session: AsyncSession,
    *,
    anchor_set_id: int,
    status: MisclassificationStatus | None = "open",
) -> list[SsrMisclassificationFlag]:
    await require_anchor_set_row(session, anchor_set_id)
    stmt = (
        select(SsrMisclassificationFlag)
        .where(SsrMisclassificationFlag.anchor_set_id == anchor_set_id)
        .order_by(SsrMisclassificationFlag.id.desc())
    )
    if status is not None:
        stmt = stmt.where(SsrMisclassificationFlag.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_flag(
    session: AsyncSession,
    *,
    anchor_set_id: int,
    flag_id: int,
) -> SsrMisclassificationFlag:
    flag = await session.get(SsrMisclassificationFlag, flag_id)
    if flag is None or flag.anchor_set_id != anchor_set_id:
        raise MisclassificationFlagError("Misclassification flag not found")
    return flag


async def dismiss_flag(
    session: AsyncSession,
    *,
    anchor_set_id: int,
    flag_id: int,
) -> SsrMisclassificationFlag:
    flag = await get_flag(session, anchor_set_id=anchor_set_id, flag_id=flag_id)
    if flag.status != "open":
        raise MisclassificationFlagError(
            f"Flag status is {flag.status!r}; only open flags can be dismissed"
        )
    flag.status = "dismissed"
    flag.resolved_at = utcnow()
    await session.flush()
    return flag


async def resolve_flag(
    session: AsyncSession,
    *,
    anchor_set_id: int,
    flag_id: int,
    add_to_calibration: bool = False,
) -> SsrMisclassificationFlag:
    flag = await get_flag(session, anchor_set_id=anchor_set_id, flag_id=flag_id)
    if flag.status != "open":
        raise MisclassificationFlagError(
            f"Flag status is {flag.status!r}; only open flags can be resolved"
        )
    try:
        item = await add_pool_item(
            session,
            anchor_set_id=anchor_set_id,
            label=flag.expected_label,
            text=flag.text,
            source_type=flag.source_type,  # type: ignore[arg-type]
            source_run_id=flag.source_run_id,
            source_attempt_id=flag.source_attempt_id,
            source_variant_id=flag.source_variant_id,
            source_ref=dict(flag.source_ref or {}),
            add_to_calibration=add_to_calibration,
        )
    except AnchorPoolError as exc:
        raise MisclassificationFlagError(str(exc)) from exc

    flag.pool_item_id = item.id
    flag.status = "resolved"
    flag.resolved_at = utcnow()
    await session.flush()
    return flag


__all__ = [
    "MisclassificationFlagError",
    "MisclassificationKind",
    "MisclassificationStatus",
    "create_flag",
    "dismiss_flag",
    "get_flag",
    "list_flags",
    "resolve_flag",
    "serialize_flag",
]
