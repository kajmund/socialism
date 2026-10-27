"""Owner-backed read models for AnchorSets and their usable members."""

from __future__ import annotations

from typing import Any

from app.services.clause_ssr.labels import ANCHOR, ANCHOR_SET, MEMBER_OF, VERIFICATION
from app.services.clause_ssr.types import (
    LABEL_ANSWERS,
    Anchor,
    AnchorSet,
    EmbeddingSpec,
)
from app.services.overgraph.labels import visible_scope_keys
from app.services.overgraph.owner import OwnerClient

PAGE_LIMIT = 1000


def _str(props: dict[str, Any], name: str) -> str:
    return str(props.get(name) or "")


def _int(props: dict[str, Any], name: str, default: int = 0) -> int:
    value = props.get(name)
    return int(value) if isinstance(value, (int, float, str)) and str(value) else default


def _verification_usable(verification: dict[str, Any] | None, polarity: str) -> bool:
    if verification is None:
        return False
    return (
        _str(verification, "status") == "active"
        and _str(verification, "answer") in LABEL_ANSWERS
        and _str(verification, "polarity") == polarity
    )


def _anchor_set(
    row: dict[str, Any],
    members: list[dict[str, Any]],
    verifications: dict[str, dict[str, Any] | None],
) -> AnchorSet:
    props = dict(row.get("props") or {})
    member_ids = []
    for member in members:
        member_props = dict(member.get("props") or {})
        if _str(member_props, "status") not in {"draft", "active"}:
            continue
        if not _verification_usable(
            verifications.get(_str(member_props, "verification_id")),
            _str(member_props, "polarity"),
        ):
            continue
        member_ids.append(str(member["key"]))
    holdout = tuple(part for part in _str(props, "holdout_ids").split(",") if part)
    return AnchorSet(
        id=str(row["key"]),
        version=_int(props, "version", 1),
        category=_str(props, "category"),
        status=_str(props, "status") or "draft",
        selection_method="deterministic_diversity",
        embedding=EmbeddingSpec(
            model=_str(props, "embedding_model"),
            revision=_str(props, "embedding_revision"),
            dimension=_int(props, "embedding_dimension"),
        ),
        holdout_ids=holdout,
        member_ids=tuple(sorted(member_ids)),
        scope_key=_str(props, "scope_key"),
        created_at_ms=_int(props, "created_at_ms"),
    )


async def _anchor_set_from_row(
    client: OwnerClient, row: dict[str, Any],
) -> AnchorSet:
    members = await client.neighbors(
        int(row["id"]), direction="incoming", labels=[MEMBER_OF], limit=200,
    )
    verification_ids = [
        _str(dict(member.get("props") or {}), "verification_id") for member in members
    ]
    unique = [key for key in dict.fromkeys(verification_ids) if key]
    response = await client.read([{"label": VERIFICATION, "key": key} for key in unique])
    verifications = {
        key: response["values"].get(f"{VERIFICATION}:{key}") for key in unique
    }
    return _anchor_set(row, members, verifications)


async def list_anchor_sets(
    client: OwnerClient, *, customer_id: int | None, active_only: bool = False,
) -> list[AnchorSet]:
    visible = visible_scope_keys(customer_id)
    rows: list[dict[str, Any]] = []
    for scope_key in visible:
        cursor: int | None = None
        while True:
            page = await client.query_nodes(
                ANCHOR_SET, props={"scope_key": scope_key},
                limit=PAGE_LIMIT, after=cursor,
            )
            rows.extend(page["nodes"])
            cursor = page.get("next_cursor")
            if cursor is None:
                break
    items = [await _anchor_set_from_row(client, row) for row in rows]
    if active_only:
        items = [item for item in items if item.status == "active"]
    items.sort(key=lambda item: (item.category, item.version))
    return items


async def get_anchor_set(client: OwnerClient, set_id: str) -> AnchorSet:
    response = await client.read([{"label": ANCHOR_SET, "key": set_id}])
    props = response["values"].get(f"{ANCHOR_SET}:{set_id}")
    node_id = response["ids"].get(f"{ANCHOR_SET}:{set_id}")
    if props is None or node_id is None:
        raise KeyError(f"missing graph node {ANCHOR_SET}:{set_id}")
    return await _anchor_set_from_row(
        client, {"key": set_id, "id": node_id, "props": props},
    )


__all__ = ["ANCHOR", "get_anchor_set", "list_anchor_sets"]


async def list_anchors(
    client: OwnerClient,
    *,
    customer_id: int | None,
    classification_id: str | None = None,
    statuses: tuple[str, ...] = ("draft", "active"),
) -> list[Anchor]:
    allowed = set(statuses)
    anchors: list[Anchor] = []
    for scope_key in visible_scope_keys(customer_id):
        props = {"scope_key": scope_key}
        if classification_id is not None:
            props["classification_id"] = classification_id
        cursor: int | None = None
        while True:
            page = await client.query_nodes(
                ANCHOR, props=props, include_vectors=True,
                limit=PAGE_LIMIT, after=cursor,
            )
            for row in page["nodes"]:
                item = dict(row.get("props") or {})
                if _str(item, "status") not in allowed:
                    continue
                vector = row.get("dense_vector")
                anchors.append(Anchor(
                    id=str(row["key"]),
                    verification_id=_str(item, "verification_id"),
                    source_unit_id=_str(item, "source_unit_id"),
                    classification_id=_str(item, "classification_id"),
                    category=_str(item, "category"),
                    polarity=_str(item, "polarity"),
                    content_hash=_str(item, "content_hash"),
                    status=_str(item, "status") or "draft",
                    embedding=EmbeddingSpec(
                        model=_str(item, "embedding_model"),
                        revision=_str(item, "embedding_revision"),
                        dimension=_int(item, "embedding_dimension"),
                    ),
                    vector=tuple(vector) if vector else None,
                    scope_key=_str(item, "scope_key"),
                    provenance={
                        "reviewer_id": _str(item, "reviewer_id"),
                        "question": _str(item, "question"),
                    },
                ))
            cursor = page.get("next_cursor")
            if cursor is None:
                break
    anchors.sort(key=lambda item: (item.category, item.id))
    return anchors
