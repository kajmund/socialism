"""Persist and seed prompt catalog rows. Insert-only — never overwrite existing text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration, Kund, PromptField, PromptOverride
from app.serializers import utcnow


class MissingPromptCustomerError(RuntimeError):
    """Raised when the requested kund does not exist."""


class MissingPromptCatalogError(RuntimeError):
    """Raised when no active prompt fields exist for the requested module."""


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


async def _require_kund(session: AsyncSession, customer_id: int) -> Kund:
    kund = await session.get(Kund, customer_id)
    if kund is None:
        raise MissingPromptCustomerError(f"Kund {customer_id} saknas")
    return kund


async def filled_prompts(
    session: AsyncSession,
    *,
    customer_id: int,
    language: str,
    module: str | None = None,
) -> dict[str, str]:
    """Catalog defaults for ``module`` (or all modules) overlaid with sparse overrides.

    Does not read or write ``Configuration.prompts``.
    """
    await _require_kund(session, customer_id)
    fields = await get_prompt_fields(session, module, active_only=True)
    if not fields:
        scope = module if module is not None else "alla moduler"
        raise MissingPromptCatalogError(f"Inga aktiva promptfält för {scope}")
    field_ids = [field.id for field in fields]
    stmt = select(PromptOverride).where(
        PromptOverride.customer_id == customer_id,
        PromptOverride.language == language,
        PromptOverride.prompt_field_id.in_(field_ids),
    )
    overrides = {
        row.prompt_field_id: row.text
        for row in (await session.execute(stmt)).scalars().all()
    }
    out: dict[str, str] = {}
    for field in fields:
        override = overrides.get(field.id)
        if override is not None and override.strip():
            out[field.key] = override
        else:
            out[field.key] = field_default_text(field, language)
    return out


async def replace_prompt_overrides(
    session: AsyncSession,
    *,
    customer_id: int,
    language: str,
    prompts: Mapping[str, str],
) -> None:
    """Replace overrides for ``customer_id`` × ``language`` with sparse deviations.

    Keys equal to the catalog default (or empty) drop any existing override.
    Caller commits.
    """
    await _require_kund(session, customer_id)
    fields = await get_prompt_fields(session, active_only=True)
    if not fields:
        raise MissingPromptCatalogError("Inga aktiva promptfält")
    existing = (
        await session.execute(
            select(PromptOverride).where(
                PromptOverride.customer_id == customer_id,
                PromptOverride.language == language,
            )
        )
    ).scalars().all()
    by_field_id = {row.prompt_field_id: row for row in existing}
    incoming = {str(key): str(value) for key, value in prompts.items()}
    now = utcnow()
    for field in fields:
        body = incoming.get(field.key, "").strip()
        current = by_field_id.get(field.id)
        if not body or body == field_default_text(field, language):
            if current is not None:
                await session.delete(current)
            continue
        if current is None:
            session.add(
                PromptOverride(
                    customer_id=customer_id,
                    prompt_field_id=field.id,
                    language=language,
                    text=body,
                    updated_at=now,
                )
            )
        else:
            current.text = body
            current.updated_at = now
    await session.flush()
