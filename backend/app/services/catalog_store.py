"""Persist and seed catalog lists per configuration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CatalogList, Configuration
from app.schemas.domain import CatalogItem, GeoBounds
from app.serializers import utcnow
from app.services.catalog_defaults import (
    CATALOG_DEFAULTS,
    ORT_DEFAULTS_BY_LABEL,
)
from app.services.catalog_items import catalog_items_as_json, coerce_catalog_items


def enrich_ort_items(items: list[CatalogItem]) -> list[CatalogItem]:
    """Fill missing ort description/bounds from defaults without overwriting edits."""
    out: list[CatalogItem] = []
    for item in items:
        default = ORT_DEFAULTS_BY_LABEL.get(item.label)
        if default is None:
            out.append(item)
            continue
        description = item.description
        bounds = item.bounds
        if not description and default.get("description"):
            description = str(default["description"])
        if bounds is None and default.get("bounds"):
            try:
                bounds = GeoBounds.model_validate(default["bounds"])
            except Exception:  # noqa: BLE001
                bounds = item.bounds
        out.append(
            CatalogItem(
                label=item.label,
                description=description,
                bounds=bounds,
            )
        )
    return out


async def get_catalog_list(
    session: AsyncSession,
    configuration_id: int,
    key: str,
) -> CatalogList | None:
    result = await session.execute(
        select(CatalogList).where(
            CatalogList.configuration_id == configuration_id,
            CatalogList.key == key,
        )
    )
    return result.scalar_one_or_none()


async def list_catalog_lists(
    session: AsyncSession,
    configuration_id: int,
) -> list[CatalogList]:
    result = await session.execute(
        select(CatalogList).where(CatalogList.configuration_id == configuration_id)
    )
    return list(result.scalars().all())


async def ensure_catalog_defaults(session: AsyncSession, configuration_id: int) -> int:
    """Insert missing catalog keys for one configuration. Returns rows added."""
    result = await session.execute(
        select(CatalogList).where(CatalogList.configuration_id == configuration_id)
    )
    by_key = {row.key: row for row in result.scalars().all()}
    added = 0
    dirty = False
    for default in CATALOG_DEFAULTS:
        existing = by_key.get(default["key"])
        default_items = coerce_catalog_items(list(default["items"]))
        if default["key"] == "ort":
            default_items = enrich_ort_items(default_items)
        if existing is None:
            session.add(
                CatalogList(
                    configuration_id=configuration_id,
                    key=default["key"],
                    section=default["section"],
                    title=default["title"],
                    items=catalog_items_as_json(default_items),
                    updated_at=utcnow(),
                )
            )
            added += 1
            dirty = True
            continue

        if existing.title != default["title"] or existing.section != default["section"]:
            existing.title = default["title"]
            existing.section = default["section"]
            dirty = True

        raw_was_legacy = any(isinstance(x, str) for x in (existing.items or []))
        if raw_was_legacy:
            coerced = coerce_catalog_items(existing.items)
            existing.items = catalog_items_as_json(coerced)
            dirty = True

    if dirty:
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
    return added


async def ensure_catalogs_for_all_configurations(session: AsyncSession) -> int:
    """Seed missing catalog keys for every configuration. Returns total rows added."""
    result = await session.execute(select(Configuration.id))
    ids = list(result.scalars().all())
    total = 0
    for configuration_id in ids:
        total += await ensure_catalog_defaults(session, configuration_id)
    return total
