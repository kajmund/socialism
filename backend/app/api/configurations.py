"""Standalone named prompt configurations (name + language + prompt text)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration
from app.database.session import get_session
from app.schemas.domain import (
    ConfigurationCreate,
    ConfigurationOut,
    ConfigurationUpdate,
)
from app.serializers import utcnow

router = APIRouter(prefix="/configurations", tags=["configurations"])


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _serialize(row: Configuration) -> ConfigurationOut:
    return ConfigurationOut(
        id=row.id,
        name=row.name,
        language=row.language,  # type: ignore[arg-type]
        prompt_text=row.prompt_text,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


async def _get_configuration(session: AsyncSession, configuration_id: int) -> Configuration:
    row = await session.get(Configuration, configuration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return row


@router.get("", response_model=list[ConfigurationOut])
async def list_configurations(
    session: AsyncSession = Depends(get_session),
) -> list[ConfigurationOut]:
    stmt = select(Configuration).order_by(Configuration.updated_at.desc())
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
    now = utcnow()
    row = Configuration(
        name=body.name,
        language=body.language,
        prompt_text=body.prompt_text,
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
    if "prompt_text" in data and data["prompt_text"] is not None:
        row.prompt_text = data["prompt_text"]
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.delete("/{configuration_id}", status_code=204)
async def delete_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_configuration(session, configuration_id)
    await session.delete(row)
    await session.commit()
