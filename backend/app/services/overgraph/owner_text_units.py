"""Owner-backed TextUnit reads for bounded read paths."""

from __future__ import annotations

from app.services.overgraph.labels import TEXT_UNIT
from app.services.overgraph.model import GraphRecord, TextUnitView
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.views import text_unit_view

PAGE_LIMIT = 1000


def _record(row: dict) -> GraphRecord:
    return GraphRecord(
        key=str(row["key"]), labels=tuple(row.get("labels") or (TEXT_UNIT,)),
        props=dict(row.get("props") or {}), engine_id=row.get("id"),
    )


def _sort_key(row: GraphRecord) -> tuple[int, int, str]:
    return (
        int(row.props.get("section_ordinal") or -1),
        int(row.props.get("ordinal") or 0),
        row.key,
    )


async def load_version_units(
    client: OwnerClient, document_version_id: str,
) -> list[TextUnitView]:
    rows: list[GraphRecord] = []
    cursor: int | None = None
    while True:
        page = await client.query_nodes(
            TEXT_UNIT, props={"document_version_id": document_version_id},
            limit=PAGE_LIMIT, after=cursor,
        )
        rows.extend(_record(row) for row in page["nodes"])
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    rows.sort(key=_sort_key)
    return [text_unit_view(row) for row in rows]


async def load_version_vectors(
    client: OwnerClient, document_version_id: str,
) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    cursor: int | None = None
    while True:
        page = await client.query_nodes(
            TEXT_UNIT, props={"document_version_id": document_version_id},
            include_vectors=True, limit=PAGE_LIMIT, after=cursor,
        )
        for row in page["nodes"]:
            vector = row.get("dense_vector")
            if vector:
                vectors[str(row["key"])] = list(vector)
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    return vectors


async def get_unit(client: OwnerClient, unit_id: str) -> TextUnitView | None:
    response = await client.read(
        [{"label": TEXT_UNIT, "key": unit_id}], include_vectors=True,
    )
    props = response.get("values", {}).get(f"{TEXT_UNIT}:{unit_id}")
    if props is None:
        return None
    return text_unit_view(GraphRecord(
        key=unit_id, labels=(TEXT_UNIT,), props=dict(props),
        engine_id=response.get("ids", {}).get(f"{TEXT_UNIT}:{unit_id}"),
    ))
