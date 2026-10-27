"""Owner-backed document type index for a tenant knowledge catalog."""

from __future__ import annotations

from typing import Any

from app.services.document_find.category_index import category_key_for_type
from app.services.document_find.labels import DOCUMENT_CATEGORY, IN_CATEGORY
from app.services.document_find.taxonomy import require_type
from app.services.document_qa.labels import CANONICAL_DOCUMENT
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_graph import (
    apply_batch,
    make_edge,
    make_node,
    props_of,
    read_nodes,
)

PAGE_LIMIT = 200


async def classify_and_index(
    client: OwnerClient, *, document_id: str, document_type: str,
) -> None:
    """Write effective_type and category membership through the Owner."""
    document_type = require_type(document_type)
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    document = props_of(response, CANONICAL_DOCUMENT, document_id)
    if document is None:
        raise ValueError(f"document is missing from the tenant catalog: {document_id}")
    previous = str(document.get("effective_type") or "")
    props = dict(document)
    props["effective_type"] = document_type
    props["document_id"] = document_id
    if previous and previous != document_type:
        kept = [
            doc for doc in await documents_for_type(client, previous)
            if doc != document_id
        ]
        await apply_batch(
            client, "index:classify", nodes=[], edges=[],
            deletes=[{
                "label": DOCUMENT_CATEGORY,
                "key": category_key_for_type(previous),
            }],
        )
        await _write_category(
            client, document_id=document_id, document_type=document_type,
            props=props, kept=kept,
        )
        return
    await _write_category(
        client, document_id=document_id, document_type=document_type,
        props=props, kept=[],
    )


async def _write_category(
    client: OwnerClient, *, document_id: str, document_type: str,
    props: dict[str, Any], kept: list[str],
) -> None:
    key = category_key_for_type(document_type)
    nodes = [
        make_node(CANONICAL_DOCUMENT, document_id, props),
        make_node(DOCUMENT_CATEGORY, key, {"kind": "type", "value": document_type}),
    ]
    edges = [make_edge(
        (DOCUMENT_CATEGORY, key), (CANONICAL_DOCUMENT, document_id), IN_CATEGORY,
    )]
    for member in kept:
        edges.append(make_edge(
            (DOCUMENT_CATEGORY, key), (CANONICAL_DOCUMENT, member), IN_CATEGORY,
        ))
    await apply_batch(client, "index:classify", nodes=nodes, edges=edges)


async def documents_for_type(client: OwnerClient, document_type: str) -> list[str]:
    """Read every non-archived document of one type through paginated Owner reads."""
    document_type = require_type(document_type)
    document_ids: list[str] = []
    cursor: int | None = None
    while True:
        page = await client.query_nodes(
            CANONICAL_DOCUMENT,
            props={"effective_type": document_type},
            limit=PAGE_LIMIT,
            after=cursor,
        )
        for row in page["nodes"]:
            props = dict(row.get("props") or {})
            if int(props.get("archived") or 0):
                continue
            document_ids.append(str(props.get("document_id") or row["key"]))
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    return sorted(set(document_ids))


async def document_effective_type(
    client: OwnerClient, document_id: str,
) -> str:
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    return str((props_of(response, CANONICAL_DOCUMENT, document_id) or {}).get(
        "effective_type") or "")


async def archived_document_ids(
    client: OwnerClient, document_ids: list[str],
) -> set[str]:
    """Filter documents whose archived flag is set, without scanning the corpus."""
    if not document_ids:
        return set()
    response = await read_nodes(
        client, [(CANONICAL_DOCUMENT, document_id) for document_id in document_ids],
    )
    archived: set[str] = set()
    for document_id in document_ids:
        props = props_of(response, CANONICAL_DOCUMENT, document_id)
        if props is None:
            continue
        if int(props.get("archived") or 0):
            archived.add(document_id)
    return archived


__all__ = [
    "archived_document_ids",
    "classify_and_index",
    "document_effective_type",
    "documents_for_type",
]
