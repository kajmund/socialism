"""Build source locators from existing TextUnit positions only."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.knowledge.units import TextUnit
from app.services.tabular_review.types import SourceLocator


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _rects_from_metadata(metadata: Mapping[str, object] | None) -> tuple[dict[str, float], ...]:
    if not metadata:
        return ()
    raw = metadata.get("rects")
    if not isinstance(raw, list):
        return ()
    rects: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            rects.append(
                {
                    "x": float(item["x"]),
                    "y": float(item["y"]),
                    "width": float(item["width"]),
                    "height": float(item["height"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(rects)


def source_locator(unit: TextUnit) -> SourceLocator:
    """Copy stored page/clause positions. Do not invent missing geometry."""
    return SourceLocator(
        text_unit_id=unit.id,
        document_id=unit.document_id,
        document_version_id=unit.document_version_id,
        exact_text=unit.text,
        page_start=_positive_int(unit.page_start),
        page_end=_positive_int(unit.page_end),
        locator=unit.locator or None,
        section_id=unit.section_id or None,
        rects=_rects_from_metadata(unit.metadata),
    )


def locator_payload(source: SourceLocator) -> dict[str, object]:
    payload: dict[str, object] = {
        "text_unit_id": source.text_unit_id,
        "document_id": source.document_id,
        "document_version_id": source.document_version_id,
        "exact_text": source.exact_text,
    }
    if source.page_start is not None:
        payload["page_start"] = source.page_start
    if source.page_end is not None:
        payload["page_end"] = source.page_end
    if source.locator:
        payload["locator"] = source.locator
    if source.section_id:
        payload["section_id"] = source.section_id
    if source.rects:
        payload["rects"] = [dict(rect) for rect in source.rects]
    return payload
