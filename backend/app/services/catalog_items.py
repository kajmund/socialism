"""Normalize catalog list items (legacy strings → CatalogItem)."""

from __future__ import annotations

from typing import Any

from app.schemas.domain import CatalogItem, GeoBounds

# ~800 m half-width when upgrading a legacy lat/lng pin to a rectangle.
_LEGACY_PIN_DELTA = 0.007


def coerce_catalog_item(raw: Any) -> CatalogItem | None:
    """Normalize legacy strings / lat-lng pins / rich objects to CatalogItem."""
    if isinstance(raw, CatalogItem):
        label = raw.label.strip()
        if not label:
            return None
        return CatalogItem(
            label=label,
            description=raw.description.strip(),
            bounds=raw.bounds,
        )
    if isinstance(raw, str):
        label = raw.strip()
        if not label:
            return None
        return CatalogItem(label=label)
    if not isinstance(raw, dict):
        return None

    label = str(raw.get("label") or raw.get("name") or "").strip()
    if not label:
        return None
    description = str(raw.get("description") or "").strip()

    bounds: GeoBounds | None = None
    raw_bounds = raw.get("bounds")
    if isinstance(raw_bounds, dict):
        try:
            bounds = GeoBounds.model_validate(raw_bounds)
        except Exception:  # noqa: BLE001 — invalid stored bounds become None
            bounds = None
    elif raw.get("lat") is not None and raw.get("lng") is not None:
        try:
            lat = float(raw["lat"])
            lng = float(raw["lng"])
            bounds = GeoBounds(
                south=lat - _LEGACY_PIN_DELTA,
                west=lng - _LEGACY_PIN_DELTA,
                north=lat + _LEGACY_PIN_DELTA,
                east=lng + _LEGACY_PIN_DELTA,
            )
        except (TypeError, ValueError):
            bounds = None

    return CatalogItem(label=label, description=description, bounds=bounds)


def coerce_catalog_items(raw_items: Any) -> list[CatalogItem]:
    if not isinstance(raw_items, list):
        return []
    cleaned: list[CatalogItem] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = coerce_catalog_item(raw)
        if item is None or item.label in seen:
            continue
        seen.add(item.label)
        cleaned.append(item)
    return cleaned


def catalog_items_as_json(items: list[CatalogItem]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]
