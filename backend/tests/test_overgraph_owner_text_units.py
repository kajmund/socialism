from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.owner import OvergraphOwner
from app.services.overgraph.owner_writer import build_text_unit_batch, write_text_units_via_owner


def _unit(index: int) -> TextUnit:
    text = f"Klausul {index}: tre månaders uppsägningstid."
    return TextUnit(
        id=f"unit-{index}", document_version_id="ver-1", document_id="doc-1",
        section_id="sec-1", ordinal=index, text=text, content_hash=hash_text(text),
        locator=f"stycke {index + 1}", page_start=3, page_end=3,
        char_start=index * 10, char_end=index * 10 + len(text),
    )


@pytest.fixture
async def owner():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    instance = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


async def test_text_units_via_owner_preserve_content_embedding_and_position(owner):
    units = [_unit(0), _unit(1)]
    embeddings = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    batch = build_text_unit_batch(
        units, scope=customer_scope(1), embeddings=embeddings,
        section_titles={"sec-1": "Uppsägning"}, section_ordinals={"sec-1": 2},
    )
    from app.services.overgraph.owner import OwnerClient
    from app.services.overgraph.owner_writer import mutation_id_for

    owner_client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    result = await owner_client.mutate(mutation_id_for(batch), batch, kind="batch")
    assert result["ok"] is True
    row = owner.catalog.get_by_key("TextUnit", "unit-0")
    assert row is not None
    assert row.props["text"] == units[0].text
    assert row.props["content_hash"] == units[0].content_hash
    assert row.props["locator"] == "stycke 1"
    assert row.props["page_start"] == 3
    assert row.props["char_start"] == 0
    assert row.props["section_title"] == "Uppsägning"
    assert list(row.dense_vector) == embeddings[0]
    assert owner.catalog.count_edges_by_label("CONTAINS") == 2
    assert owner.catalog.count_edges_by_label("NEXT") == 0

    duplicate = await owner_client.mutate(mutation_id_for(batch), batch, kind="batch")
    assert duplicate["duplicate"] is True


async def test_write_text_units_via_owner_is_idempotent(owner):
    from app.services.overgraph.owner import OwnerClient
    from app.services.knowledge.scope import customer_scope

    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    units = [_unit(0)]
    first = await write_text_units_via_owner(client, units, scope=customer_scope(1), embeddings=[[1.0, 0.0, 0.0, 0.0]])
    second = await write_text_units_via_owner(client, units, scope=customer_scope(1), embeddings=[[1.0, 0.0, 0.0, 0.0]])
    assert first["ok"] is True
    assert second["duplicate"] is True
    assert owner.catalog.get_by_key("TextUnit", "unit-0") is not None
