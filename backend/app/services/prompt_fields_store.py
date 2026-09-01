"""Persist and seed prompt catalog rows. Insert-only — never overwrite existing text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration, PromptField, PromptOverride
from app.serializers import utcnow


def _row_modules(row: PromptField) -> list[str]:
    raw = row.modules
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def row_belongs_to_module(row: PromptField, module: str) -> bool:
    return module in _row_modules(row)


def field_default_text(row: PromptField, language: str) -> str:
    mapping = {
        "sv": row.default_sv,
        "en": row.default_en,
        "nb": row.default_nb,
    }
    return (mapping.get(language) or row.default_sv or "").strip()


def _as_str_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


async def get_prompt_fields(
    session: AsyncSession,
    module: str | None = None,
    *,
    active_only: bool = True,
) -> list[PromptField]:
    stmt = select(PromptField)
    if active_only:
        stmt = stmt.where(PromptField.active.is_(True))
    stmt = stmt.order_by(PromptField.key.asc())
    rows = list((await session.execute(stmt)).scalars().all())
    if module is None:
        return rows
    return [row for row in rows if row_belongs_to_module(row, module)]


async def get_prompt_field_by_key(session: AsyncSession, key: str) -> PromptField | None:
    stmt = select(PromptField).where(PromptField.key == key)
    return (await session.execute(stmt)).scalar_one_or_none()


async def ensure_prompt_field_defaults(
    session: AsyncSession,
    module: str,
    defaults: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> int:
    """Insert missing keys, or attach ``module`` to an existing shared row.

    Fields on an existing row are never overwritten.
    """
    result = await session.execute(select(PromptField))
    existing_rows = list(result.scalars().all())
    by_key = {row.key: row for row in existing_rows}
    changed = 0
    for default in defaults:
        key = str(default["key"])
        row = by_key.get(key)
        if row is None:
            labels = _as_str_map(default.get("label"))
            hints = _as_str_map(default.get("hint"))
            bodies = _as_str_map(default.get("defaults"))
            row = PromptField(
                key=key,
                modules=[module],
                section=str(default.get("section") or "panel"),
                label_sv=labels.get("sv") or "",
                label_en=labels.get("en") or "",
                hint_sv=hints.get("sv") or "",
                hint_en=hints.get("en") or "",
                default_sv=bodies.get("sv") or "",
                default_en=bodies.get("en") or "",
                default_nb=bodies.get("nb") or bodies.get("sv") or "",
                active=True,
                updated_at=utcnow(),
            )
            session.add(row)
            by_key[key] = row
            changed += 1
        elif module not in _row_modules(row):
            row.modules = [*_row_modules(row), module]
            changed += 1
    if not changed:
        return 0
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return 0
    return changed


async def ensure_prompt_overrides_from_configurations(session: AsyncSession) -> int:
    """Copy Configuration.prompts deviations into sparse override rows.

    Existing override rows are never overwritten. Matching default text is skipped.
    """
    fields = {
        row.key: row
        for row in (await session.execute(select(PromptField))).scalars().all()
    }
    if not fields:
        return 0
    existing = (await session.execute(select(PromptOverride))).scalars().all()
    seen = {(row.customer_id, row.prompt_field_id, row.language) for row in existing}
    configs = (await session.execute(select(Configuration))).scalars().all()
    added = 0
    for config in configs:
        language = str(config.language)
        stored = dict(config.prompts or {})
        for key, raw in stored.items():
            field = fields.get(str(key))
            if field is None:
                continue
            body = str(raw or "").strip()
            if not body or body == field_default_text(field, language):
                continue
            triple = (config.customer_id, field.id, language)
            if triple in seen:
                continue
            session.add(
                PromptOverride(
                    customer_id=config.customer_id,
                    prompt_field_id=field.id,
                    language=language,
                    text=body,
                    updated_at=utcnow(),
                )
            )
            seen.add(triple)
            added += 1
    if not added:
        return 0
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return 0
    return added
