"""Staging vector store for one mem0 extraction before an Owner write."""

from __future__ import annotations

from app.services.expertgranskning.memory_staging import (
    StagingVectorStore,
    begin,
    end,
    install_mem0_staging,
)


def test_staging_store_supports_the_mem0_surface():
    install_mem0_staging()
    token = begin({})
    try:
        store = StagingVectorStore("expert_memories", 4)
        store.insert([[1.0, 0.0, 0.0, 0.0]], [{"data": "one", "user_id": "u1"}], ["m1"])
        store.insert([[0.0, 1.0, 0.0, 0.0]], [{"data": "two", "user_id": "u1"}], ["m2"])
        hits = store.search("q", [1.0, 0.0, 0.0, 0.0], top_k=1)
        assert [hit.id for hit in hits] == ["m1"]
        assert store.get("m2").memory == "two"
        store.update("m1", payload={"data": "first"})
        assert store.get("m1").memory == "first"
        store.delete("m2")
        assert store.get("m2") is None
        assert store.list(filters={"user_id": "u1"})[0].id == "m1"
    finally:
        end(token)
