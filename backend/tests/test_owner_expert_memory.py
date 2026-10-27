"""Async expert-memory port over the Memory Owner with mem0 staging."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.config import settings
from app.services.expertgranskning.memory_staging import StagedHit, root
from app.services.expertgranskning.owner_memory_service import OwnerExpertMemory
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.overgraph.owner_memory import get as get_memory, upsert

DIMENSION = 4
VECTOR = [1.0, 0.0, 0.0, 0.0]
PAYLOAD = {
    "data": "Kunden vill ha kortare avtal.",
    "source": "chat",
    "user_id": "kund:1",
    "agent_id": "expert:e1",
}


class FakeEmbedder:
    model = "test"
    dimension = DIMENSION

    async def embed(self, texts):
        return [list(VECTOR) for _ in texts]


class FakeMem0:
    """Stands in for mem0: it mutates the active staging collection."""

    def add(self, messages, **kwargs):
        collection = root()[settings.mem0_collection_name]
        collection["mem-1"] = StagedHit(
            id="mem-1", score=None,
            payload={
                "data": "Extraherat minne.",
                "user_id": kwargs["user_id"],
                "agent_id": kwargs["agent_id"],
                "metadata": kwargs["metadata"],
            },
            vector=tuple(VECTOR),
        )
        return [{
            "id": "mem-1", "memory": "Extraherat minne.", "event": "ADD",
            "user_id": kwargs["user_id"], "agent_id": kwargs["agent_id"],
            "metadata": kwargs["metadata"],
        }]


async def _start():
    root_dir = Path(tempfile.mkdtemp(prefix="owner-expert-"))
    catalog = open_catalog(root_dir / "memory", kind="memory", dimension=DIMENSION)
    owner = OvergraphOwner(
        root_dir / "memory", dimension=DIMENSION,
        socket_path=root_dir / "owner.sock", catalog=catalog,
    )
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    return owner, client


async def test_owner_expert_memory_read_write_surface():
    owner, client = await _start()
    service = OwnerExpertMemory(
        client_factory=lambda: client, embedder=FakeEmbedder(),
    )
    try:
        await upsert(
            client, kind="Memory", memory_id="existing", vector=VECTOR,
            payload=PAYLOAD, collection=settings.mem0_collection_name,
        )
        hit = await service.get(memory_id="existing")
        assert hit is not None and hit.text == PAYLOAD["data"]
        assert [item.id for item in await service.list_all(
            customer_id=1, expert_id="e1",
        )] == ["existing"]
        found = await service.search(
            customer_id=1, expert_id="e1", query="avtal", sources=frozenset({"chat"}),
        )
        assert [item.id for item in found] == ["existing"]
        updated = await service.update(memory_id="existing", text="Nytt minne.")
        assert updated.text == "Nytt minne."
        stored = await get_memory(client, "Memory", "existing")
        assert stored is not None and stored.payload["data"] == "Nytt minne."
        await service.delete(memory_id="existing")
        assert await service.get(memory_id="existing") is None
    finally:
        await owner.close()


async def test_add_chat_turn_applies_the_staged_diff_through_the_owner():
    owner, client = await _start()
    service = OwnerExpertMemory(
        client_factory=lambda: client, embedder=FakeEmbedder(),
        text_client=FakeMem0(), vision_client=FakeMem0(),
    )
    try:
        hits = await service.add_chat_turn(
            customer_id=1, expert_id="e1", user_message="Hej",
            assistant_message="Hej igen", source="chat",
        )
        assert [hit.id for hit in hits] == ["mem-1"]
        stored = await get_memory(client, "Memory", "mem-1")
        assert stored is not None and stored.payload["data"] == "Extraherat minne."
        assert stored.payload["metadata"]["source"] == "chat"
    finally:
        await owner.close()
