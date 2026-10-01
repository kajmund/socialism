"""Resolve exact chunk content without changing any document provenance."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.text_units import SharedTextChunkRecord
from app.services.knowledge.units import hash_text


async def resolve_shared_chunks(
    session: AsyncSession, texts: Sequence[tuple[str, str]],
) -> dict[str, SharedTextChunkRecord]:
    contents = {}
    for digest, text in texts:
        if hash_text(text) != digest:
            raise ValueError("Shared chunk SHA does not match its exact UTF-8 text")
        contents[digest] = text
    keys = sorted(contents)
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[session.bind.dialect.name]
    resolved = {}
    # Bound bind counts and lock order for concurrent batches sharing chunks.
    for start in range(0, len(keys), 200):
        batch = keys[start:start + 200]
        await session.execute(insert(SharedTextChunkRecord).values([
            {"content_hash": key, "text": contents[key]} for key in batch
        ]).on_conflict_do_nothing(index_elements=["content_hash"]))
        rows = await session.scalars(select(SharedTextChunkRecord).where(
            SharedTextChunkRecord.content_hash.in_(batch),
        ))
        for row in rows:
            if row.text != contents[row.content_hash]:
                raise ValueError("Stored shared chunk text conflicts with its SHA")
            resolved[row.content_hash] = row
    return resolved
