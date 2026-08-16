"""Global SSR label vocabulary CRUD (tone/style labels shared across sets)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SsrLabelVocabulary
from app.database.session import get_session
from app.schemas.domain import (
    AnchorKind,
    AnchorLocale,
    LabelVocabularyEntry,
    LabelVocabularyOut,
    LabelVocabularyPatch,
)
from app.services.label_vocabulary import (
    LabelVocabularyError,
    add_label,
    ensure_vocabularies_seeded,
    get_vocabulary,
    list_vocabularies,
    remove_label,
    rename_label,
    usage_by_key,
)

router = APIRouter(prefix="/label-vocabularies", tags=["label-vocabularies"])


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


async def _serialize(
    session: AsyncSession,
    row: SsrLabelVocabulary,
) -> LabelVocabularyOut:
    kind: AnchorKind = row.kind  # type: ignore[assignment]
    locale: AnchorLocale = row.locale  # type: ignore[assignment]
    entries = await get_vocabulary(session, kind, locale)
    usage = await usage_by_key(session, kind, locale)
    return LabelVocabularyOut(
        kind=kind,
        locale=locale,
        entries=[LabelVocabularyEntry(key=e["key"], label=e["label"]) for e in entries],
        usage=usage,
        updated_at=_dt(row.updated_at),
    )


@router.get("", response_model=list[LabelVocabularyOut])
async def list_label_vocabularies(
    kind: AnchorKind | None = Query(default=None),
    locale: AnchorLocale | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[LabelVocabularyOut]:
    await ensure_vocabularies_seeded(session)
    rows = await list_vocabularies(session, kind=kind, locale=locale)
    return [await _serialize(session, row) for row in rows]


@router.get("/{kind}/{locale}", response_model=LabelVocabularyOut)
async def get_label_vocabulary(
    kind: AnchorKind,
    locale: AnchorLocale,
    session: AsyncSession = Depends(get_session),
) -> LabelVocabularyOut:
    await ensure_vocabularies_seeded(session)
    try:
        await get_vocabulary(session, kind, locale)
    except LabelVocabularyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row = await session.get(SsrLabelVocabulary, {"kind": kind, "locale": locale})
    if row is None:
        raise HTTPException(status_code=404, detail="Vocabulary not found")
    return await _serialize(session, row)


@router.patch("/{kind}/{locale}", response_model=LabelVocabularyOut)
async def patch_label_vocabulary(
    kind: AnchorKind,
    locale: AnchorLocale,
    body: LabelVocabularyPatch,
    session: AsyncSession = Depends(get_session),
) -> LabelVocabularyOut:
    await ensure_vocabularies_seeded(session)
    has_ops = bool(body.rename or body.add or body.remove)
    if not has_ops:
        raise HTTPException(
            status_code=400,
            detail="PATCH body must include at least one of: rename, add, remove",
        )
    try:
        if body.rename:
            for op in body.rename:
                await rename_label(session, kind, locale, op.key, op.new_label)
        if body.add:
            for op in body.add:
                await add_label(session, kind, locale, op.label)
        if body.remove:
            for op in body.remove:
                await remove_label(session, kind, locale, op.key)
    except LabelVocabularyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    row = await session.get(SsrLabelVocabulary, {"kind": kind, "locale": locale})
    if row is None:
        raise HTTPException(status_code=404, detail="Vocabulary not found")
    return await _serialize(session, row)
