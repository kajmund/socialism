"""Named prompt configurations (language + map of prompt key → text)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration
from app.database.session import get_session
from app.schemas.domain import (
    ConfigurationCreate,
    ConfigurationLanguage,
    ConfigurationOut,
    ConfigurationUpdate,
    PromptCatalogOut,
    PromptFieldOut,
)
from app.serializers import utcnow
from app.services.prompt_catalog import (
    PROMPT_FIELDS,
    PROMPT_SECTIONS,
    default_prompts,
    normalize_prompts,
)
from app.services.prompt_store import ensure_default_configurations, set_active_configuration

router = APIRouter(prefix="/configurations", tags=["configurations"])


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _serialize(row: Configuration) -> ConfigurationOut:
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    prompts = normalize_prompts(dict(row.prompts or {}), language=language, fill_missing=True)
    return ConfigurationOut(
        id=row.id,
        name=row.name,
        language=language,
        prompts=prompts,
        is_active=bool(row.is_active),
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


async def _get_configuration(session: AsyncSession, configuration_id: int) -> Configuration:
    row = await session.get(Configuration, configuration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return row


async def _deactivate_others(
    session: AsyncSession,
    *,
    language: str,
    keep_id: int | None,
) -> None:
    stmt = select(Configuration).where(
        Configuration.language == language,
        Configuration.is_active.is_(True),
    )
    if keep_id is not None:
        stmt = stmt.where(Configuration.id != keep_id)
    result = await session.execute(stmt)
    for row in result.scalars().all():
        row.is_active = False


@router.get("/catalog", response_model=PromptCatalogOut)
async def prompt_catalog(
    language: ConfigurationLanguage = Query(default="sv"),
    label_locale: ConfigurationLanguage = Query(default="sv"),
) -> PromptCatalogOut:
    ui = "en" if label_locale == "en" else "sv"
    fields = [
        PromptFieldOut(
            key=field["key"],
            section=field["section"],
            label=field["label"].get(ui) or field["label"]["sv"],
            hint=field["hint"].get(ui) or field["hint"]["sv"],
            default=field["defaults"].get(language) or field["defaults"]["sv"],
        )
        for field in PROMPT_FIELDS
    ]
    sections = [
        {"id": section_id, "label": labels.get(ui) or labels["sv"]}
        for section_id, labels in PROMPT_SECTIONS
    ]
    return PromptCatalogOut(
        sections=sections,
        fields=fields,
        defaults=default_prompts(language),
    )


@router.get("", response_model=list[ConfigurationOut])
async def list_configurations(
    session: AsyncSession = Depends(get_session),
) -> list[ConfigurationOut]:
    await ensure_default_configurations(session)
    stmt = select(Configuration).order_by(
        Configuration.is_active.desc(),
        Configuration.updated_at.desc(),
    )
    result = await session.execute(stmt)
    return [_serialize(row) for row in result.scalars().all()]


@router.get("/{configuration_id}", response_model=ConfigurationOut)
async def get_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    return _serialize(await _get_configuration(session, configuration_id))


@router.post("", response_model=ConfigurationOut, status_code=201)
async def create_configuration(
    body: ConfigurationCreate,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    prompts = normalize_prompts(body.prompts, language=body.language, fill_missing=True)
    now = utcnow()
    if body.is_active:
        await _deactivate_others(session, language=body.language, keep_id=None)
    row = Configuration(
        name=body.name,
        language=body.language,
        prompts=prompts,
        is_active=body.is_active,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.patch("/{configuration_id}", response_model=ConfigurationOut)
async def update_configuration(
    configuration_id: int,
    body: ConfigurationUpdate,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    row = await _get_configuration(session, configuration_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        row.name = data["name"]
    if "language" in data and data["language"] is not None:
        row.language = data["language"]
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    if "prompts" in data and data["prompts"] is not None:
        row.prompts = normalize_prompts(
            data["prompts"],
            language=language,
            fill_missing=True,
        )
    if data.get("is_active") is True:
        await _deactivate_others(session, language=row.language, keep_id=row.id)
        row.is_active = True
    elif data.get("is_active") is False:
        row.is_active = False
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.post("/{configuration_id}/activate", response_model=ConfigurationOut)
async def activate_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    try:
        row = await set_active_configuration(session, configuration_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize(row)


@router.delete("/{configuration_id}", status_code=204)
async def delete_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_configuration(session, configuration_id)
    await session.delete(row)
    await session.commit()
