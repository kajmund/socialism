"""Document text the voice agent can answer from in the same turn."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.stored_objects import StoredObject
from app.database.workspace_models import VoiceWorkspace
from app.schemas.workspace import WorkspaceState
from app.services.workspace_parent_documents import voice_document_inventory

EXCERPT_CHARS = 8000
_OPEN_REQUEST = re.compile(r"(?i)(?<!\w)(?:öppna|visa|open|show)(?!\w)")
_TERM = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_STOP_TERMS = frozenset({
    "öppna", "visa", "open", "show", "avtal", "avtalet", "dokument", "dokumentet",
    "filen", "filer", "kunden", "kund", "underlag", "arbetsytan", "detta", "denna",
    "bara", "inte", "finns", "öppet",
})


def select_excerpt_ids(inventory: list[dict], open_ids: list[str]) -> list[str]:
    known = {row["source_object_id"] for row in inventory}
    opened = [source_id for source_id in open_ids if source_id in known]
    if opened:
        return opened
    ready = [row["source_object_id"] for row in inventory if row["knowledge_status"] == "ready"]
    return ready if len(ready) == 1 else []


def build_excerpts(chosen: list[str], inventory: dict[str, dict], texts: dict[str, str], *, limit: int) -> list[dict]:
    excerpts = []
    remaining = limit
    for source_id in chosen:
        meta = inventory[source_id]
        text = texts.get(source_id, "").strip()
        readable = meta["knowledge_status"] == "ready" and bool(text) and remaining > 0
        chunk = text[:remaining] if readable else ""
        excerpts.append({
            "source_id": source_id,
            "filename": meta["filename"],
            "knowledge_status": meta["knowledge_status"],
            "text": chunk,
            "truncated": readable and len(text) > len(chunk),
        })
        remaining -= len(chunk)
    return excerpts


def distinctive_terms(text: str) -> list[str]:
    terms: list[str] = []
    for word in _TERM.findall(text):
        term = word.casefold()
        if term in _STOP_TERMS or term in terms:
            continue
        terms.append(term)
    return terms


def open_request_terms(message: str, earlier_user_messages: list[str]) -> list[str] | None:
    if _OPEN_REQUEST.search(message) is None:
        return None
    own = distinctive_terms(message)
    if own:
        return own
    for earlier in reversed(earlier_user_messages):
        terms = distinctive_terms(earlier)
        if terms:
            return terms
    return []


def matching_source_id(
    inventory: list[dict],
    texts: dict[str, str],
    terms: list[str],
    assistant_text: str,
) -> str | None:
    with_text = [row for row in inventory if texts.get(row["source_object_id"], "").strip()]
    if terms:
        hits = [row["source_object_id"] for row in with_text if _contains_all(row, texts, terms)]
        return hits[0] if len(hits) == 1 else None
    folded = assistant_text.casefold()
    named = [
        row["source_object_id"]
        for row in inventory
        if row.get("filename") and str(row["filename"]).casefold() in folded
    ]
    return named[0] if len(set(named)) == 1 else None


def _contains_all(row: dict, texts: dict[str, str], terms: list[str]) -> bool:
    haystack = f"{row.get('filename', '')}\n{texts.get(row['source_object_id'], '')}".casefold()
    return all(term in haystack for term in terms)


async def source_for_open_request(
    session: AsyncSession,
    *,
    workspace_id: str | None,
    actor_user_id: str | None,
    message: str,
    history: list[tuple[str, str, str | None]],
) -> str | None:
    earlier = [text for role, text, _image in history if role == "user"]
    terms = open_request_terms(message, earlier)
    if terms is None or actor_user_id is None or workspace_id is None:
        return None
    actor = await session.get(UserAccount, actor_user_id)
    workspace = await session.get(VoiceWorkspace, workspace_id) if actor is not None else None
    if actor is None or workspace is None or workspace.owner_user_id != actor.id:
        return None
    inventory = await voice_document_inventory(session, workspace, actor)
    ids = [row["source_object_id"] for row in inventory]
    rows = list(await session.scalars(select(StoredObject).where(StoredObject.id.in_(ids)))) if ids else []
    texts = {row.id: row.extracted_text or "" for row in rows}
    assistant_text = "\n".join(text for role, text, _image in history if role == "assistant")
    return matching_source_id(inventory, texts, terms, assistant_text)


async def voice_document_context(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount) -> dict:
    inventory = await voice_document_inventory(session, workspace, user)
    by_id = {row["source_object_id"]: row for row in inventory}
    state = WorkspaceState.model_validate(workspace.state)
    chosen = select_excerpt_ids(inventory, [tab.source_id for tab in state.documents])
    rows = list(await session.scalars(select(StoredObject).where(StoredObject.id.in_(chosen)))) if chosen else []
    texts = {row.id: row.extracted_text or "" for row in rows}
    return {
        "available_documents": inventory,
        "open_documents": build_excerpts(chosen, by_id, texts, limit=EXCERPT_CHARS),
    }
