from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.owner import OvergraphOwner
from app.services.overgraph.owner_writer import (
    build_text_unit_batch,
    mutation_id_for,
    write_text_unit_embeddings_via_owner,
)
from app.services.overgraph.owner import OwnerClient


@pytest.fixture
async def owner():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    instance = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


def _unit() -> TextUnit:
    text = "Uppsägningstid tre månader."
    return TextUnit(
        id="unit-1", document_version_id="ver-1", document_id="doc-1",
        section_id=None, ordinal=0, text=text, content_hash=hash_text(text),
        locator="stycke 1", page_start=2, page_end=2,
    )


async def test_embedding_update_writes_vector_and_rejects_stale_hash(owner):
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    unit = _unit()
    batch = build_text_unit_batch([unit], scope=customer_scope(1), embeddings=[None])
    await client.mutate(mutation_id_for(batch, catalog_id=owner.catalog_id, scope_key=customer_scope(1).scope_key), batch, kind="batch")

    result = await write_text_unit_embeddings_via_owner(client, [unit], [[1.0, 0.0, 0.0, 0.0]])
    assert result["ok"] is True
    row = owner.catalog.get_by_key("TextUnit", "unit-1")
    assert list(row.dense_vector) == [1.0, 0.0, 0.0, 0.0]

    stale = TextUnit(**{**unit.__dict__, "content_hash": "different"})
    rejected = await write_text_unit_embeddings_via_owner(client, [stale], [[0.0, 1.0, 0.0, 0.0]])
    assert rejected["error"] == "stale_embedding"
    assert list(owner.catalog.get_by_key("TextUnit", "unit-1").dense_vector) == [1.0, 0.0, 0.0, 0.0]


async def test_embedding_via_owner_is_idempotent(owner):
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    unit = _unit()
    batch = build_text_unit_batch([unit], scope=customer_scope(1), embeddings=[None])
    await client.mutate(mutation_id_for(batch, catalog_id=owner.catalog_id, scope_key=customer_scope(1).scope_key), batch, kind="batch")
    first = await write_text_unit_embeddings_via_owner(client, [unit], [[1.0, 0.0, 0.0, 0.0]], mutation_id="embed-fixed")
    second = await write_text_unit_embeddings_via_owner(client, [unit], [[1.0, 0.0, 0.0, 0.0]], mutation_id="embed-fixed")
    assert first["ok"] is True
    assert second["duplicate"] is True


async def test_embedding_after_delete_cannot_resurrect_text_unit(owner):
    from app.services.overgraph.owner import OwnerClient
    from app.services.overgraph.owner_writer import delete_text_units_via_owner

    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    unit = _unit()
    batch = build_text_unit_batch([unit], scope=customer_scope(1), embeddings=[None])
    await client.mutate("seed", batch, kind="batch")
    await delete_text_units_via_owner(client, [unit], mutation_id="delete-before-embedding")
    result = await write_text_unit_embeddings_via_owner(client, [unit], [[1.0, 0.0, 0.0, 0.0]], mutation_id="late-embedding")
    assert result["error"] == "text_unit_not_found"
    assert owner.catalog.get_by_key("TextUnit", "unit-1") is None
