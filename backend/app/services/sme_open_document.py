"""Open agreement text for an expert panel, loaded before any model call."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.schemas.workspace import DocumentMention, WorkspaceState
from app.services.workspace_document_context import (
    artifact_for_open_request,
    source_for_open_request,
    voice_document_context,
)


def _id_lines(rows: list[dict], *, title_key: str, id_key: str, id_label: str) -> list[str]:
    return [
        f"{row.get(title_key) or 'dokument'} ({id_label} {row.get(id_key) or ''})"
        for row in rows
    ]


def format_open_documents(excerpts: list[dict]) -> str:
    """Open source tabs, by id. Their text is not part of the turn."""
    lines = _id_lines(excerpts, title_key="filename", id_key="source_id", id_label="source_id")
    if not lines:
        return ""
    return (
        "Öppna källflikar. Bara de här dokumenten finns i kontexten, med id. "
        "Dokumenttexten ingår inte.\n\n"
        + "\n".join(lines)
    )


_SHOWN_NOW = "Dokument som visas i vyn just nu är "
_SHOWN_MAP = "Relationskartan som visas i vyn just nu är "
_REMINDER_BOUNDARIES = (
    "\n\nÖvriga skapade dokument",
    "\n\nÖvriga relationskartor",
    "\n\nAndra öppna relationskartor",
    "\n\nRelationskartan som visas",
    "\n\nAndra öppna flikar",
    "\n\nDokument som visas i arbetsytan",
    "\n\nDokument som pekats ut",
)


def attach_shown_reminder(user_text: str, workspace_note: str) -> str:
    """Repeat the on-screen document after the chat, where the model reads last."""
    start = workspace_note.find(_SHOWN_NOW)
    if start < 0:
        start = workspace_note.find(_SHOWN_MAP)
    if start < 0:
        return user_text
    block = workspace_note[start:]
    for boundary in _REMINDER_BOUNDARIES:
        stop = block.find(boundary)
        if stop > 0:
            block = block[:stop]
            break
    block = block.strip()[:8000]
    if not block:
        return user_text
    return (
        f"{block}\n\n"
        "Det här är dokumentet i vyn, inte en ny fråga. "
        "Tidigare svar som säger att det saknas är inaktuella. "
        "Svara på meddelandet nedan. "
        "Gå inte igenom dokumentet om meddelandet inte ber om det, "
        "och upprepa inte en genomgång som redan finns i samtalet.\n\n"
        f"{user_text}"
    )


def format_created_documents(rows: list[dict]) -> str:
    """Open created-document tabs, by id. Their text is not part of the turn."""
    lines = _id_lines(rows, title_key="title", id_key="artifact_id", id_label="artifact_id")
    if not lines:
        return ""
    return (
        "Öppna skapade dokument. Bara de här finns i kontexten, med id. "
        "Dokumenttexten ingår inte.\n\n"
        + "\n".join(lines)
    )


def format_shown_relations(rows: list[dict]) -> str:
    """The relation map on screen, by id. Its graph is not part of the turn."""
    lines = _id_lines(rows, title_key="title", id_key="artifact_id", id_label="artifact_id")
    if not lines:
        return ""
    title = rows[0].get("title") or "relationskartan"
    return (
        f"{_SHOWN_MAP}{title}. "
        "Kartans noder och kanter ingår inte.\n\n"
        + "\n".join(lines)
    )


def format_relation_maps(rows: list[dict]) -> str:
    """Open relation-map tabs, by id. A map that is not a tab is omitted."""
    if not rows:
        return ""
    shown = [row for row in rows if row.get("shown")]
    rest = [row for row in rows if row not in shown]
    parts = []
    if shown:
        parts.append(format_shown_relations(shown))
    if rest:
        parts.append(
            "Andra öppna relationskartor. De är inte det som visas just nu.\n\n"
            + "\n".join(_id_lines(rest, title_key="title", id_key="artifact_id", id_label="artifact_id"))
        )
    return "\n\n".join(parts)


def format_shown_document_set(document_set: dict | None) -> str:
    """The search-result gallery currently visible to the user."""
    if not document_set:
        return ""
    title = str(document_set.get("title") or "").strip()
    lines = [
        f"{row.get('filename') or 'dokument'} (source_id {row.get('source_id') or ''})"
        for row in document_set.get("documents") or []
    ]
    if not title or not lines:
        return ""
    return (
        f"Dokumentsamlingen som visas i vyn just nu är {title}. "
        "Detta är ett sökresultat som användaren ser; dokumentens text är inte öppnad av galleriet.\n\n"
        + "\n".join(lines)
    )


def format_workspace_documents(documents: dict) -> str:
    parts = [
        format_open_documents(list(documents.get("open_documents") or [])),
        format_created_documents(list(documents.get("created_documents") or [])),
        format_relation_maps(documents.get("relation_maps") or []),
        format_shown_document_set(documents.get("shown_document_set")),
    ]
    return "\n\n".join(part for part in parts if part)


def with_open_document(note: str, document: str) -> str:
    text = document.strip()
    if not text:
        return note
    return f"{note}\n\n{text}".strip()


async def load_open_workspace(
    factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: str | None,
    user_id: str,
    customer_id: int,
    expert_id: str | None = None,
    mentions: list[DocumentMention] | None = None,
) -> tuple[WorkspaceState, str] | None:
    """Read the open document, then return the connection before any model call."""
    if not workspace_id:
        return None
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, workspace_id)
        user = await session.get(UserAccount, user_id)
        if (
            workspace is None
            or user is None
            or workspace.owner_user_id != user_id
            or workspace.customer_id != customer_id
        ):
            await session.rollback()
            raise RuntimeError("voice_workspace_access_lost")
        state = WorkspaceState.model_validate(workspace.state)
        if mentions is not None:
            state.document_mentions = mentions[:8]
        if expert_id:
            state.expert_id = expert_id
        documents = await voice_document_context(session, workspace, user, state=state)
        await session.rollback()
    return state, format_workspace_documents(documents)


def workspace_tool_delivery_key(name: str, arguments: dict, expert_id: str | None = None) -> tuple[str, ...]:
    """Opening a document happens once. Each passage mark is its own delivery."""
    source = str(arguments.get("source_id") or arguments.get("artifact_id") or "")
    if name == "show_document_set":
        sources = ",".join(str(row) for row in arguments.get("source_ids") or [])
        return (name, str(arguments.get("title") or ""), sources)
    if name == "focus_anchor":
        quote = " ".join(str(arguments.get("quote") or "").casefold().split())
        reference = str(arguments.get("reference_id") or "")
        comment = " ".join(str(arguments.get("comment") or "").casefold().split())
        return (name, source, reference, quote, expert_id or "", comment)
    return (name, source)


async def publish_speaker_tools(
    *,
    customer_id: int,
    user_id: str,
    panel_id: int,
    calls: list[dict],
    sent: set[tuple[str, ...]],
    expert_id: str | None = None,
) -> None:
    """Workspace tools from a typed reply. Passage marks stay with the speaker."""
    for call in calls:
        arguments = dict(call.get("arguments") or {})
        name = str(call.get("name") or "")
        key = workspace_tool_delivery_key(name, arguments, expert_id)
        if not name or key in sent:
            continue
        sent.add(key)
        if name == "focus_anchor" and expert_id:
            arguments["expert_id"] = expert_id
        await library_chat_broadcast.publish(customer_id, str(panel_id), {
            "type": "workspace_tool",
            "thread_type": "panel",
            "thread_id": str(panel_id),
            "name": name,
            "arguments": arguments,
            "target_user_id": user_id,
        })


async def publish_document_open(
    factory: async_sessionmaker[AsyncSession],
    *,
    customer_id: int,
    user_id: str,
    panel_id: int,
    workspace_id: str | None,
    message: str,
    history: list[tuple[str, str, str | None]],
) -> str | None:
    """Open one requested file or created document, then release the connection."""
    if not workspace_id:
        return None
    async with factory() as session:
        source_id = await source_for_open_request(
            session,
            workspace_id=workspace_id,
            actor_user_id=user_id,
            message=message,
            history=history,
        )
        artifact_id = None if source_id else await artifact_for_open_request(
            session,
            workspace_id=workspace_id,
            actor_user_id=user_id,
            message=message,
            history=history,
        )
        await session.rollback()
    if source_id:
        name, arguments, opened = "show_document", {"source_id": source_id}, source_id
    elif artifact_id:
        name, arguments, opened = "show_artifact", {"artifact_id": artifact_id}, artifact_id
    else:
        return None
    await library_chat_broadcast.publish(customer_id, str(panel_id), {
        "type": "workspace_tool",
        "thread_type": "panel",
        "thread_id": str(panel_id),
        "name": name,
        "arguments": arguments,
        "target_user_id": user_id,
    })
    return opened
