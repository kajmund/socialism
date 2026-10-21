"""GraphRecord → view mappers shared by research, grounding and navigation."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import TEXT_UNIT
from app.services.overgraph.model import GraphFactView, GraphRecord, TextUnitView


def _dt(ms: object) -> datetime | None:
    value = int(ms or 0)
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _json_dict(raw: object) -> dict[str, object]:
    if not raw:
        return {}
    parsed = json.loads(str(raw))
    return dict(parsed) if isinstance(parsed, dict) else {}


def _scope_customer(scope_key: str) -> int | None:
    if scope_key == "shared" or ":" not in scope_key:
        return None
    return int(scope_key.split(":", 1)[1])


def _text_unit_refs(props: dict[str, object]) -> tuple[str, ...]:
    parsed = json.loads(str(props.get("source_refs_json") or "[]"))
    return tuple(
        str(item["ref"]) for item in parsed if item.get("kind") == "text_unit" and item.get("ref")
    )


def fact_view(row: GraphRecord) -> GraphFactView:
    props = row.props
    scope_key = str(props.get("scope_key") or "")
    context = str(props.get("context_key") or "")
    return GraphFactView(
        id=row.key,
        scope_key=scope_key,
        customer_id=_scope_customer(scope_key),
        source_id=str(props.get("source_key") or ""),
        target_id=str(props.get("target_key") or ""),
        context_id=context or None,
        predicate=str(props.get("predicate") or ""),
        fact_text=str(props.get("fact_text") or ""),
        status=str(props.get("status") or ""),
        valid_at=_dt(props.get("valid_at_ms")),
        invalid_at=_dt(props.get("invalid_at_ms")),
        attributes=_json_dict(props.get("attributes_json")),
        text_unit_refs=_text_unit_refs(props),
    )


def text_unit_view(row: GraphRecord) -> TextUnitView:
    props = row.props
    scope_key = str(props.get("scope_key") or "")
    locator = str(props.get("locator") or "")
    page_start = int(props.get("page_start") or -1)
    page_end = int(props.get("page_end") or -1)
    return TextUnitView(
        id=row.key,
        document_id=str(props.get("document_id") or ""),
        document_version_id=str(props.get("document_version_id") or ""),
        scope_key=scope_key,
        scope_type="shared" if scope_key == "shared" else "customer",
        customer_id=_scope_customer(scope_key),
        text=str(props.get("text") or ""),
        content_hash=str(props.get("content_hash") or ""),
        ordinal=int(props.get("ordinal") or 0),
        section_id=str(props.get("section_id") or "") or None,
        locator=locator or None,
        page_start=None if page_start < 0 else page_start,
        page_end=None if page_end < 0 else page_end,
        valid_from=_dt(props.get("valid_from_ms")),
        valid_to=_dt(props.get("valid_to_ms")),
        extra=_json_dict(props.get("extra_json")),
    )


def load_text_units(catalog: Catalog, unit_ids: list[str]) -> list[TextUnitView | None]:
    return [
        text_unit_view(row) if (row := catalog.get_by_key(TEXT_UNIT, identity)) is not None else None
        for identity in unit_ids
    ]


def supporting_units(catalog: Catalog, fact: GraphFactView) -> list[TextUnitView | None]:
    return load_text_units(catalog, list(fact.text_unit_refs))
