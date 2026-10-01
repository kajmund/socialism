"""Shared immutable text keeps separate document, temporal and scoped occurrences."""

import asyncio

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.database.models import DocumentVersionRecord, TextUnitRecord
from app.database.text_units import SharedTextChunkRecord
from app.services.knowledge.persistence import text_units_for_version
from app.services.knowledge.shared_chunks import resolve_shared_chunks
from app.services.knowledge.units import hash_text
from tests.research_reuse.test_03_chunk_sha import TEXT, URI_A, URI_B, lab as lab

pytestmark = pytest.mark.research_reuse


async def test_two_documents_share_one_text_with_two_provenance_occurrences(lab):
    first = await lab.ingest(URI_A)
    second = await lab.ingest(URI_B)
    chunks = await lab.rows(SharedTextChunkRecord)
    units = await lab.rows(TextUnitRecord)
    assert len(chunks) == 1 and chunks[0].text == TEXT
    assert chunks[0].content_hash == hash_text(TEXT)
    assert len(units) == 2 and units[0].id != units[1].id
    assert {row.document_version_id for row in units} == {
        first.document_version_id, second.document_version_id,
    }
    assert {row.document_id for row in units} == {first.document_id, second.document_id}
    assert all(row.content_hash == chunks[0].content_hash and row.text == TEXT for row in units)
    assert "text" not in TextUnitRecord.__table__.columns
    assert len(lab.inner.calls) == 1


async def test_partial_overlap_stores_only_unique_chunk_texts(lab):
    await lab.ingest(URI_A, TEXT + "\n\n# A\n\nDet första dokumentet.")
    await lab.ingest(URI_B, TEXT + "\n\n# B\n\nDet andra dokumentet.")
    assert len(await lab.rows(SharedTextChunkRecord)) == 3
    assert len(await lab.rows(TextUnitRecord)) == 4
    assert [len(batch) for batch in lab.inner.calls] == [2, 1]


async def test_recurring_text_reuses_content_but_creates_a_new_temporal_occurrence(lab):
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
    units = await lab.rows(TextUnitRecord)
    old = next(row for row in units if row.document_version_id == first.document_version_id)
    new = next(row for row in units if row.document_version_id == third.document_version_id)
    assert old.id != new.id and old.content_hash == new.content_hash
    assert old.text == new.text == TEXT
    assert len(await lab.rows(SharedTextChunkRecord)) == 2
    assert len(lab.inner.calls) == 2


async def test_shared_text_is_materialized_before_session_closes(lab):
    result = await lab.ingest(URI_A)
    async with lab.factory() as session:
        rows = await text_units_for_version(session, result.document_version_id)
    assert [row.text for row in rows] == [TEXT]


async def test_wrong_sha_is_rejected_before_any_shared_content_write(lab):
    async with lab.factory() as session:
        with pytest.raises(ValueError, match="SHA does not match"):
            await resolve_shared_chunks(session, [(hash_text(TEXT), TEXT), ("wrong", "Other")])
        assert list(await session.scalars(select(SharedTextChunkRecord))) == []


async def test_concurrent_writers_reuse_one_shared_content_row(lab):
    async def resolve():
        async with lab.factory.begin() as session:
            return (await resolve_shared_chunks(session, [(hash_text(TEXT), TEXT)]))[hash_text(TEXT)].content_hash

    assert await asyncio.gather(resolve(), resolve()) == [hash_text(TEXT), hash_text(TEXT)]
    assert len(await lab.rows(SharedTextChunkRecord)) == 1


async def test_shared_content_cannot_be_overwritten(lab):
    await lab.ingest(URI_A)
    with pytest.raises(IntegrityError, match="immutable"):
        async with lab.factory.begin() as session:
            await session.execute(update(SharedTextChunkRecord).values(text="Changed"))
    assert (await lab.rows(SharedTextChunkRecord))[0].text == TEXT


async def test_existing_occurrence_cannot_be_repointed_to_different_text(lab):
    first = await lab.ingest(URI_A)
    await lab.ingest(URI_B, TEXT + " Changed.")
    with pytest.raises(IntegrityError, match="immutable"):
        async with lab.factory.begin() as session:
            await session.execute(update(TextUnitRecord).where(
                TextUnitRecord.document_version_id == first.document_version_id,
            ).values(content_hash=hash_text(TEXT + " Changed.")))
    original = next(row for row in await lab.rows(TextUnitRecord) if row.document_id == first.document_id)
    assert original.text == TEXT


async def test_removing_an_occurrence_keeps_shared_content_and_other_provenance(lab):
    first = await lab.ingest(URI_A)
    second = await lab.ingest(URI_B)
    async with lab.factory.begin() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        row = await session.scalar(select(TextUnitRecord).where(TextUnitRecord.document_id == first.document_id))
        await session.delete(row)
    remaining = await lab.rows(TextUnitRecord)
    assert len(remaining) == 1 and remaining[0].document_id == second.document_id
    assert remaining[0].text == TEXT
    assert len(await lab.rows(SharedTextChunkRecord)) == 1
    with pytest.raises(IntegrityError):
        async with lab.factory.begin() as session:
            await session.delete(await session.get(SharedTextChunkRecord, hash_text(TEXT)))
