"""Speech-to-text hints. Document terms come from text units; the base list is the prompt field."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, StoredObject
from app.database.text_units import SharedTextChunkRecord, TextUnitRecord
from app.database.workspace_models import VoiceWorkspace
from app.schemas.workspace import WorkspaceState
from app.services.workspaces import resolve_readable_workspace_ids

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


async def readable_focus_source_ids(
    session: AsyncSession,
    *,
    customer_id: int,
    source_ids: Sequence[str],
    workspace_ids: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Split requested STT focus sources into readable ids and ids to drop.

    Fail closed per id: unknown sources and sources without a stored object in
    one of the readable org workspaces are dropped, never sent to the STT.
    """
    ids = [item.strip() for item in source_ids if item.strip()][:4]
    if not ids:
        return [], []
    readable = set(workspace_ids)
    rows = (await session.scalars(select(StoredObject).where(
        StoredObject.id.in_(ids),
        StoredObject.customer_id == customer_id,
    ))).all()
    by_id = {row.id: row for row in rows}
    allowed, dropped = [], []
    for source_id in ids:
        row = by_id.get(source_id)
        if row is not None and row.workspace_id in readable:
            allowed.append(source_id)
        else:
            dropped.append(source_id)
    return allowed, dropped


async def readable_focus_texts(
    session: AsyncSession,
    *,
    customer_id: int,
    user_id: str,
    canvas_workspace_id: str,
    source_ids: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Texts for readable STT focus sources; unreadable ids returned as dropped.

    The session canvas is revalidated against the user, and every requested id
    is reauthorized against the canvas's organisation workspace and the user's
    readable workspace memberships before text is loaded. Fail closed: unknown
    ids and foreign workspace ids are dropped, never sent to the STT.
    """
    canvas = await session.get(VoiceWorkspace, canvas_workspace_id)
    if (
        canvas is None
        or canvas.owner_user_id != user_id
        or canvas.customer_id != customer_id
    ):
        raise RuntimeError("voice_workspace_access_lost")
    readable_ids = await resolve_readable_workspace_ids(
        session,
        customer_id=customer_id,
        user_id=user_id,
        workspace_id=canvas.workspace_id,
    )
    allowed, dropped = await readable_focus_source_ids(
        session,
        customer_id=customer_id,
        source_ids=source_ids,
        workspace_ids=readable_ids,
    )
    texts = await text_unit_texts(session, customer_id=customer_id, source_ids=allowed)
    return texts, dropped


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
