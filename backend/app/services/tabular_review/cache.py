"""Score cache keyed by TextUnit + AnchorSet version + embedding model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.tabular_review.types import CellPolarity


@dataclass(frozen=True)
class ScoreCacheIdentity:
    text_unit_id: str
    content_hash: str
    anchor_set_id: int
    anchor_set_version: str
    pool_revision: int
    embedding_model: str
    label: str
    polarity: CellPolarity


def score_cache_key(identity: ScoreCacheIdentity) -> str:
    payload = "\0".join(
        (
            identity.text_unit_id,
            identity.content_hash,
            str(identity.anchor_set_id),
            identity.anchor_set_version,
            str(identity.pool_revision),
            identity.embedding_model,
            identity.label,
            identity.polarity,
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()
