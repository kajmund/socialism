"""Owner-backed Q&A review, archive and purge."""

from __future__ import annotations

from typing import Any

from app.services.document_qa.access import QaPermissionError, Viewer
from app.services.document_qa.labels import (
    ANSWER,
    ANSWER_POST,
    CANONICAL_DOCUMENT,
    CONTAINS,
    DOCUMENT_VERSION,
    HAS_ANSWER,
    HAS_POST,
    HAS_QUESTION,
    HAS_REVIEW,
    HAS_VERSION,
    QUESTION,
    REVIEW_EVENT,
    TEXT_UNIT,
)
from app.services.document_qa.normalize import review_key
from app.services.document_qa.owner_qa import load_answer
from app.services.overgraph.owner_graph import (
    OwnerGraphError,
    apply_batch,
    make_edge,
    neighbors_of,
    make_node,
    id_of,
    props_of,
    read_nodes,
    vector_of,
)
from app.services.document_qa.types import LoadedAnswer
from app.services.overgraph.owner import OwnerClient


_REVIEW_ACTIONS = {"approve": "user_verified", "reject": "rejected"}


async def review_answer(
    client: OwnerClient,
    viewer: Viewer,
    answer_key_value: str,
    *,
    action: str,
    reviewed_at: str,
    reviewer: str,
) -> LoadedAnswer:
    status = _REVIEW_ACTIONS.get(action)
    if status is None:
        raise ValueError(f"unsupported review action: {action}")
    response = await read_nodes(client, [(ANSWER, answer_key_value)])
    props = props_of(response, ANSWER, answer_key_value)
    answer_id = id_of(response, ANSWER, answer_key_value)
    if props is None or answer_id is None:
        raise KeyError(answer_key_value)
    _require_answer_access(viewer, props)
    updated = dict(props)
    updated["review_status"] = status
    key = review_key(viewer.customer_id, answer_key_value, reviewed_at, action)
    nodes = [
        make_node(ANSWER, answer_key_value, updated),
        make_node(
            REVIEW_EVENT,
            key,
            {
                "answer_key": answer_key_value,
                "action": action,
                "reviewed_at": reviewed_at,
                "reviewer": reviewer,
            },
        ),
    ]
    edges = [make_edge((ANSWER, answer_key_value), (REVIEW_EVENT, key), HAS_REVIEW)]
    await apply_batch(client, "qa:review", nodes=nodes, edges=edges)
    loaded = await load_answer(client, answer_key_value)
    if loaded is None:
        raise OwnerGraphError("reviewed answer is missing after owner write")
    return loaded


async def review_history(
    client: OwnerClient,
    answer_key_value: str,
) -> tuple[dict[str, str], ...]:
    response = await read_nodes(client, [(ANSWER, answer_key_value)])
    answer_id = id_of(response, ANSWER, answer_key_value)
    if answer_id is None:
        return ()
    events = [
        {
            "action": str(row["props"].get("action") or ""),
            "reviewed_at": str(row["props"].get("reviewed_at") or ""),
            "reviewer": str(row["props"].get("reviewer") or ""),
        }
        for row in await neighbors_of(client, answer_id, HAS_REVIEW)
        if REVIEW_EVENT in row.get("labels", [])
    ]
    return tuple(sorted(events, key=lambda item: item["reviewed_at"]))


def _require_answer_access(viewer: Viewer, props: dict[str, Any]) -> None:
    document_id = str(props.get("document_id") or "")
    version_id = str(props.get("document_version_id") or "")
    if not viewer.can_read(document_id, version_id):
        raise QaPermissionError("workspace or document is not readable")


async def archive_document(
    client: OwnerClient,
    viewer: Viewer,
    document_id: str,
) -> None:
    if document_id not in viewer.readable_document_ids:
        raise QaPermissionError("workspace or document is not readable")
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    props = props_of(response, CANONICAL_DOCUMENT, document_id)
    document_id_value = id_of(response, CANONICAL_DOCUMENT, document_id)
    if props is None or document_id_value is None:
        return
    archived = dict(props)
    archived["archived"] = 1
    refs = [
        (QUESTION, str(row["key"]))
        for row in await neighbors_of(client, document_id_value, HAS_QUESTION)
        if QUESTION in row.get("labels", [])
    ]
    question_rows = await read_nodes(client, refs, include_vectors=True)
    nodes = [make_node(CANONICAL_DOCUMENT, document_id, archived)]
    nodes.extend(
        make_node(
            QUESTION,
            key,
            {**dict(props_of(question_rows, QUESTION, key) or {}), "archived": 1},
            dense_vector=vector_of(question_rows, QUESTION, key),
        )
        for _, key in refs
    )
    await apply_batch(client, "qa:archive", nodes=nodes, edges=[])


async def purge_document(
    client: OwnerClient,
    viewer: Viewer,
    document_id: str,
) -> None:
    if document_id not in viewer.readable_document_ids:
        raise QaPermissionError("workspace or document is not readable")
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    document_id_value = id_of(response, CANONICAL_DOCUMENT, document_id)
    if document_id_value is None:
        return
    questions = await neighbors_of(client, document_id_value, HAS_QUESTION)
    versions = await neighbors_of(client, document_id_value, HAS_VERSION)
    deletes: list[dict[str, str]] = []
    for row in questions:
        await _collect_question_deletes(client, row, deletes)
    for row in versions:
        await _collect_version_deletes(client, row, deletes)
    deletes.append({"label": CANONICAL_DOCUMENT, "key": document_id})
    await apply_batch(client, "qa:purge", nodes=[], edges=[], deletes=deletes)


async def _collect_question_deletes(
    client: OwnerClient,
    row: dict[str, Any],
    deletes: list[dict[str, str]],
) -> None:
    if QUESTION not in row.get("labels", []):
        return
    for answer in await neighbors_of(client, int(row["node_id"]), HAS_ANSWER):
        if ANSWER not in answer.get("labels", []):
            continue
        for post in await neighbors_of(client, int(answer["node_id"]), HAS_POST):
            deletes.append({"label": ANSWER_POST, "key": str(post["key"])})
        for review in await neighbors_of(client, int(answer["node_id"]), HAS_REVIEW):
            deletes.append({"label": REVIEW_EVENT, "key": str(review["key"])})
        deletes.append({"label": ANSWER, "key": str(answer["key"])})
    deletes.append({"label": QUESTION, "key": str(row["key"])})


async def _collect_version_deletes(
    client: OwnerClient,
    row: dict[str, Any],
    deletes: list[dict[str, str]],
) -> None:
    if DOCUMENT_VERSION not in row.get("labels", []):
        return
    for unit in await neighbors_of(client, int(row["node_id"]), CONTAINS):
        if TEXT_UNIT in unit.get("labels", []):
            deletes.append({"label": TEXT_UNIT, "key": str(unit["key"])})
    deletes.append({"label": DOCUMENT_VERSION, "key": str(row["key"])})


async def document_is_archived(client: OwnerClient, document_id: str) -> bool:
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    props = props_of(response, CANONICAL_DOCUMENT, document_id)
    return bool(int((props or {}).get("archived") or 0))


async def document_exists(client: OwnerClient, document_id: str) -> bool:
    response = await read_nodes(client, [(CANONICAL_DOCUMENT, document_id)])
    return props_of(response, CANONICAL_DOCUMENT, document_id) is not None
