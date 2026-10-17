"""Speech-to-text hints. Document terms come from text units; the base list is the prompt field."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.database.text_units import SharedTextChunkRecord, TextUnitRecord
from app.schemas.workspace import WorkspaceState

TRANSCRIPTION_PROMPT_KEY = "chat.expert.live_speech_transcription"
TRANSCRIPTION_KEYWORDS_KEY = "chat.expert.live_speech_transcription_keywords"
_WORD = re.compile(r"[^\W\d_]{6,}", re.UNICODE)
_STOP = frozenset(
    {
        "denna", "detta", "dessa", "eller", "efter", "innan", "mellan", "genom",
        "under", "redan", "mycket", "andra", "annat", "skulle", "samtliga",
        "which", "their", "there", "about", "would", "could", "should", "other",
    }
)


def parse_keyword_field(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def shown_source_ids(state: WorkspaceState) -> list[str]:
    if len(state.split_source_ids) == 2:
        return [item for item in state.split_source_ids if item][:2]
    active = state.active_source_id
    if active and any(tab.source_id == active for tab in state.documents):
        return [active]
    if state.documents:
        return [state.documents[0].source_id]
    return []


def keywords_from_text_units(
    texts: Iterable[str],
    *,
    base: Sequence[str] = (),
    limit: int = 24,
) -> list[str]:
    counts: Counter[str] = Counter()
    surfaces: dict[str, str] = {}
    for text in texts:
        for match in _WORD.finditer(text):
            word = match.group(0)
            key = word.casefold()
            if key in _STOP:
                continue
            counts[key] += 1
            current = surfaces.get(key)
            if current is None or (word[:1].isupper() and not current[:1].isupper()):
                surfaces[key] = word
    ranked = [
        surfaces[key]
        for key, count in counts.most_common()
        if count >= 2 or len(key) >= 10
    ]
    chosen: list[str] = []
    seen: set[str] = set()
    for word in (*ranked, *base):
        text = " ".join(word.split())
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        chosen.append(text)
        if len(chosen) >= limit:
            break
    return chosen


async def text_unit_texts(
    session: AsyncSession,
    *,
    customer_id: int,
    source_ids: Sequence[str],
) -> list[str]:
    ids = [item.strip() for item in source_ids if item.strip()][:4]
    if not ids:
        return []
    statement = (
        select(SharedTextChunkRecord.text)
        .join(TextUnitRecord, TextUnitRecord.content_hash == SharedTextChunkRecord.content_hash)
        .join(DocumentVersionRecord, DocumentVersionRecord.id == TextUnitRecord.document_version_id)
        .join(CanonicalDocumentRecord, CanonicalDocumentRecord.id == TextUnitRecord.document_id)
        .where(
            CanonicalDocumentRecord.source_object_id.in_(ids),
            CanonicalDocumentRecord.customer_id == customer_id,
            DocumentVersionRecord.superseded_at.is_(None),
        )
        .order_by(TextUnitRecord.ordinal)
        .limit(300)
    )
    return [row for row in (await session.scalars(statement)).all() if row]
