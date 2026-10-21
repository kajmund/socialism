"""Local dense ranks a document version's units by cosine to the question."""

from __future__ import annotations

import pytest

from app.services.document_properties.local_dense import top_k_dense
from app.services.document_properties.pipeline import MaterializedUnit


class FakeEmbeddings:
    def __init__(self, vector):
        self.vector = vector

    async def embed(self, texts):
        return [list(self.vector) for _ in texts]


class FakeStored:
    def __init__(self, vectors):
        self.vectors = vectors

    async def get_text_unit_embeddings(self, *, document_id, document_version_id, text_unit_ids):
        return {unit_id: self.vectors[unit_id] for unit_id in text_unit_ids if unit_id in self.vectors}


def _unit(unit_id: str, vector) -> MaterializedUnit:
    return MaterializedUnit(
        id=unit_id,
        text=unit_id,
        document_id="doc-a",
        document_version_id="ver-a",
        section_title="",
    )


@pytest.mark.asyncio
async def test_top_k_ranks_by_cosine_and_excludes():
    units = [
        _unit("u1", [1.0, 0.0]),
        _unit("u2", [0.0, 1.0]),
        _unit("u3", [1.0, 0.0]),
    ]
    result = await top_k_dense(
        question="ignored",
        units=units,
        embeddings=FakeEmbeddings([1.0, 0.0]),
        stored=FakeStored({"u1": [1.0, 0.0], "u2": [0.0, 1.0], "u3": [1.0, 0.0]}),
        exclude={"u3"},
        k=2,
    )
    assert result == ["u1", "u2"]


@pytest.mark.asyncio
async def test_top_k_returns_empty_for_mixed_documents():
    units = [
        _unit("u1", [1.0, 0.0]),
        MaterializedUnit(
            id="u2", text="u2", document_id="doc-b", document_version_id="ver-a", section_title="",
        ),
    ]
    result = await top_k_dense(
        question="ignored",
        units=units,
        embeddings=FakeEmbeddings([1.0, 0.0]),
        stored=FakeStored({}),
        exclude=set(),
        k=5,
    )
    assert result == []
