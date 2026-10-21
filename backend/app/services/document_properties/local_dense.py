"""Document-local dense supplement for Jev verification.

Ranks a single document version's TextUnits by cosine similarity to the user's
question, reusing the ingest embeddings and the existing in-process reader.
Runs only when the first Jev verification is not SUPPORTED.
"""

from __future__ import annotations

from typing import Sequence

from app.services.document_properties.model import MaterializedUnit
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.vector_store import TextUnitEmbeddingReader, cosine_score


async def top_k_dense(
    *,
    question: str,
    units: Sequence[MaterializedUnit],
    embeddings: EmbeddingProvider,
    stored: TextUnitEmbeddingReader,
    exclude: set[str],
    k: int = 5,
) -> list[str]:
    """Return up to `k` TextUnit ids ranked by cosine, excluding `exclude`."""
    if not units or k < 1:
        return []
    document_ids = {unit.document_id for unit in units}
    version_ids = {unit.document_version_id for unit in units}
    if len(document_ids) != 1 or len(version_ids) != 1:
        return []
    query = (await embeddings.embed([question]))[0]
    stored_vectors = await stored.get_text_unit_embeddings(
        document_id=next(iter(document_ids)),
        document_version_id=next(iter(version_ids)),
        text_unit_ids=[unit.id for unit in units],
    )
    scored = [
        (cosine_score(query, stored_vectors[unit.id]), unit.id)
        for unit in units
        if unit.id not in exclude and unit.id in stored_vectors
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [unit_id for _score, unit_id in scored[:k]]
