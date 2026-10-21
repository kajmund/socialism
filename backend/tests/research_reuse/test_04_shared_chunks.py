"""TextUnit occurrences stay separate per document, version and scope in OverGraph."""

import pytest

from app.database.models import DocumentVersionRecord
from app.services.knowledge.units import hash_text
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import (
    delete_text_units_for_document,
    text_unit_ids_for_document,
)
from tests.research_reuse.test_03_chunk_sha import TEXT, URI_A, URI_B, lab as lab

pytestmark = pytest.mark.research_reuse


async def test_two_documents_keep_two_occurrences_of_the_same_text(lab):
    first = await lab.ingest(URI_A)
    second = await lab.ingest(URI_B)
    units = await lab.units()
    assert len(units) == 2 and units[0].id != units[1].id
    assert {unit.document_version_id for unit in units} == {
        first.document_version_id, second.document_version_id,
    }
    assert {unit.document_id for unit in units} == {first.document_id, second.document_id}
    assert all(unit.content_hash == hash_text(unit.text) and unit.text == TEXT for unit in units)
    assert len(lab.inner.calls) == 1


async def test_partial_overlap_stores_only_unique_texts(lab):
    await lab.ingest(URI_A, TEXT + "\n\n# A\n\nDet första dokumentet.")
    await lab.ingest(URI_B, TEXT + "\n\n# B\n\nDet andra dokumentet.")
    units = await lab.units()
    assert len(units) == 4
    assert len({unit.content_hash for unit in units}) == 3
    assert all(unit.content_hash == hash_text(unit.text) for unit in units)
    assert [len(batch) for batch in lab.inner.calls] == [2, 1]


async def test_recurring_text_creates_a_new_temporal_occurrence(lab):
    first = await lab.ingest(URI_A)
    second = await lab.ingest(URI_A, TEXT + " Ny regel.")
    third = await lab.ingest(URI_A)
    versions = await lab.rows(DocumentVersionRecord)
    assert len({row.id for row in versions}) == 3
    assert first.document_version_id != third.document_version_id
    by_id = {row.id: row for row in versions}
    assert by_id[first.document_version_id].superseded_at is not None
    assert by_id[second.document_version_id].superseded_at is not None
    assert by_id[third.document_version_id].superseded_at is None
    units = await lab.units()
    old = next(unit for unit in units if unit.document_version_id == first.document_version_id)
    new = next(unit for unit in units if unit.document_version_id == third.document_version_id)
    assert old.id != new.id and old.content_hash == new.content_hash
    assert old.text == new.text == TEXT
    assert len(lab.inner.calls) == 2


async def test_removing_one_document_keeps_the_other_occurrence(lab):
    first = await lab.ingest(URI_A)
    second = await lab.ingest(URI_B)
    catalog = require_knowledge()
    removed = delete_text_units_for_document(catalog, document_id=first.document_id)
    assert removed == 1
    assert text_unit_ids_for_document(catalog, document_id=first.document_id) == []
    remaining = await lab.units()
    assert len(remaining) == 1 and remaining[0].document_id == second.document_id
    assert remaining[0].text == TEXT
