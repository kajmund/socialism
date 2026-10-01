"""TextUnit fixtures with real SHA keys and the shared-content representation."""

from app.database.text_units import SharedTextChunkRecord, TextUnitRecord
from app.services.knowledge.shared_chunks import resolve_shared_chunks
from app.services.knowledge.units import hash_text


def text_unit_record(*, text: str, **fields) -> TextUnitRecord:
    digest = hash_text(text)
    return TextUnitRecord(
        content_hash=digest, chunk=SharedTextChunkRecord(content_hash=digest, text=text), **fields,
    )


async def persisted_text_unit(session, *, text: str, **fields) -> TextUnitRecord:
    digest = hash_text(text)
    chunks = await resolve_shared_chunks(session, [(digest, text)])
    return TextUnitRecord(content_hash=digest, chunk=chunks[digest], **fields)
