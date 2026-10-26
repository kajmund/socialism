"""Owner-backed memory catalog: insert/update/search/list/delete + links."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.overgraph.owner_memory import (
    delete,
    get,
    list_records,
    memory_kind,
    search,
    update,
    upsert,
)

DIMENSION = 4
VECTOR_A = [1.0, 0.0, 0.0, 0.0]
VECTOR_B = [0.0, 1.0, 0.0, 0.0]
PAYLOAD = {"user_id": "u1", "agent_id": "a1", "data": "first"}


async def _start() -> tuple[OvergraphOwner, OwnerClient, OwnerClient, str]:
    root = Path(tempfile.mkdtemp(prefix="owner-mem-"))
    catalog = open_catalog(root / "memory", kind="memory", dimension=DIMENSION)
    owner = OvergraphOwner(
        root / "memory", dimension=DIMENSION, socket_path=root / "owner.sock",
        catalog=catalog,
    )
    await owner.start()
    first = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    second = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    return owner, first, second, "expert_memories"


async def test_memory_insert_get_search_and_delete():
    owner, first, second, collection = await _start()
    try:
        kind = memory_kind(collection)
        await upsert(
            first, kind=kind, memory_id="m1", vector=VECTOR_A,
            payload=PAYLOAD, collection=collection,
        )
        loaded = await get(second, kind, "m1")
        assert loaded is not None and loaded.payload["data"] == "first"
        hits = await search(
            second, kind=kind, vector=VECTOR_A, top_k=5,
            filters={"user_id": "u1", "agent_id": "a1"},
        )
        assert [hit.id for hit in hits] == ["m1"]
        assert await search(
            second, kind=kind, vector=VECTOR_A, top_k=5, filters={"user_id": "other"},
        ) == []
        await update(second, kind=kind, memory_id="m1", payload={"data": "second"},
                     collection=collection)
        updated = await get(second, kind, "m1")
        assert updated.payload["data"] == "second"
        # The vector survives a payload-only update.
        again = await search(
            first, kind=kind, vector=VECTOR_A, top_k=5, filters={"user_id": "u1"},
        )
        assert [hit.id for hit in again] == ["m1"]
        await delete(second, kind, "m1")
        assert await get(first, kind, "m1") is None
    finally:
        await owner.close()


async def test_memory_links_and_listing_stay_in_the_catalog():
    owner, first, second, collection = await _start()
    try:
        kind = memory_kind(collection)
        await upsert(first, kind=kind, memory_id="m1", vector=VECTOR_A,
                     payload=PAYLOAD, collection=collection)
        await upsert(first, kind=kind, memory_id="m2", vector=VECTOR_B,
                     payload={**PAYLOAD, "linked_memory_ids": ["m1"]},
                     collection=collection)
        hits = await search(second, kind=kind, vector=VECTOR_B, top_k=5)
        linked = next(hit for hit in hits if hit.id == "m2")
        assert linked.payload["linked_count"] == 1
        listed = await list_records(second, kind=kind, filters={"user_id": "u1"})
        assert {record.id for record in listed} == {"m1", "m2"}
        entities = await list_records(second, kind=memory_kind("expert_memories_entities"))
        assert entities == []
    finally:
        await owner.close()
