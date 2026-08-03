"""Persist and seed catalog lists."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CatalogList
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


async def ensure_catalog_defaults(session: AsyncSession) -> int:
    """Insert missing catalog keys and upgrade ort item shape. Returns rows added."""
    result = await session.execute(select(CatalogList))
    by_key = {row.key: row for row in result.scalars().all()}
    added = 0
    dirty = False
    for default in CATALOG_DEFAULTS:
        existing = by_key.get(default["key"])
        default_items = coerce_catalog_items(list(default["items"]))
        if existing is None:
            session.add(
                CatalogList(
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

        coerced = coerce_catalog_items(existing.items)
        raw_was_legacy = any(isinstance(x, str) for x in (existing.items or []))
        if default["key"] == "ort":
            coerced = enrich_ort_items(coerced)
        new_json = catalog_items_as_json(coerced)
        if raw_was_legacy or new_json != existing.items:
            existing.items = new_json
            dirty = True

    if dirty:
        await session.commit()
    return added
