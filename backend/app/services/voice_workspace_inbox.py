"""Canvas-local native transcript previews and durable private read cursors."""

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, case, func, or_, select, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import CTE

from app.database.models import Persona, PersonaMessage, SmeReadCursor
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace, WorkspaceExpertThread
from app.services.workspace.service import require_expert


def cursor_thread_id(canvas_id: str, expert_id: str) -> str:
    return sha256(f"{canvas_id}:{expert_id}".encode()).hexdigest()


def _native_messages(canvas: VoiceWorkspace) -> CTE:
    return (select(PersonaMessage.id, PersonaMessage.persona_id.label("expert_id"), PersonaMessage.role,
                   func.substr(PersonaMessage.content, 1, 240).label("preview"), PersonaMessage.created_at)
            .join(WorkspaceConversationEvent, WorkspaceConversationEvent.message_id == PersonaMessage.id)
            .join(WorkspaceConversationSession, WorkspaceConversationSession.id == WorkspaceConversationEvent.session_id)
            .join(Persona, Persona.id == PersonaMessage.persona_id)
            .where(WorkspaceConversationSession.workspace_id == canvas.id,
                   WorkspaceConversationSession.user_id == canvas.owner_user_id,
                   WorkspaceConversationSession.customer_id == canvas.customer_id,
                   WorkspaceConversationSession.expert_id == PersonaMessage.persona_id,
                   Persona.customer_id == canvas.customer_id, Persona.kind == "expert",
                   PersonaMessage.mode == "workspace",
                   or_(and_(WorkspaceConversationEvent.kind == "user", PersonaMessage.role == "user"),
                       and_(WorkspaceConversationEvent.kind == "agent", PersonaMessage.role == "assistant")))
            .distinct().cte("native_messages"))


async def _expert_cursors(session: AsyncSession, canvas: VoiceWorkspace, messages: CTE) -> dict[str, int]:
    threads = select(WorkspaceExpertThread.expert_id).join(Persona, Persona.id == WorkspaceExpertThread.expert_id).where(
        WorkspaceExpertThread.workspace_id == canvas.id, Persona.customer_id == canvas.customer_id, Persona.kind == "expert")
    expert_ids = list(await session.scalars(union(threads, select(messages.c.expert_id))))
    thread_ids = {cursor_thread_id(canvas.id, expert_id): expert_id for expert_id in expert_ids}
    rows = await session.execute(select(SmeReadCursor.thread_id, SmeReadCursor.last_read_message_id).where(
        SmeReadCursor.user_id == canvas.owner_user_id, SmeReadCursor.thread_type == "voice_expert",
        SmeReadCursor.thread_id.in_(thread_ids)))
    cursors = dict.fromkeys(expert_ids, 0)
    cursors.update({thread_ids[thread_id]: message_id or 0 for thread_id, message_id in rows})
    return cursors


async def list_voice_inbox(session: AsyncSession, canvas: VoiceWorkspace) -> list[dict]:
    messages = _native_messages(canvas)
    cursors = await _expert_cursors(session, canvas, messages)
    if not cursors:
        return []
    read_id = case(*[(messages.c.expert_id == expert_id, message_id) for expert_id, message_id in cursors.items()], else_=0)
    unread = case((and_(messages.c.role == "assistant", messages.c.id > read_id), 1), else_=0)
    ranked = select(messages, func.row_number().over(partition_by=messages.c.expert_id, order_by=messages.c.id.desc()).label("rank"),
                    func.sum(unread).over(partition_by=messages.c.expert_id).label("unread_count")).subquery()
    rows = await session.execute(select(ranked).where(ranked.c.rank == 1))
    items = {expert_id: {"expert_id": expert_id, "preview": "", "last_message_at": None, "unread_count": 0}
             for expert_id in cursors}
    for row in rows.mappings():
        created_at = row["created_at"]
        items[row["expert_id"]].update(preview=row["preview"], unread_count=row["unread_count"],
            last_message_at=created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at.astimezone(UTC))
    return sorted(items.values(), key=lambda item: (item["last_message_at"] or datetime.min.replace(tzinfo=UTC),
                                                   item["expert_id"]), reverse=True)


async def mark_voice_expert_read(session: AsyncSession, canvas: VoiceWorkspace, expert_id: str) -> int | None:
    await require_expert(session, canvas, expert_id)
    messages = _native_messages(canvas)
    last_id = await session.scalar(select(func.max(messages.c.id)).where(messages.c.expert_id == expert_id))
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    statement = insert(SmeReadCursor).values(user_id=canvas.owner_user_id, thread_type="voice_expert",
        thread_id=cursor_thread_id(canvas.id, expert_id), last_read_message_id=last_id, updated_at=datetime.now(UTC))
    newest = case((func.coalesce(statement.excluded.last_read_message_id, 0) > func.coalesce(SmeReadCursor.last_read_message_id, 0),
                   statement.excluded.last_read_message_id), else_=SmeReadCursor.last_read_message_id)
    result = await session.execute(statement.on_conflict_do_update(index_elements=["user_id", "thread_type", "thread_id"],
        set_={"last_read_message_id": newest, "updated_at": datetime.now(UTC)}).returning(SmeReadCursor.last_read_message_id))
    return result.scalar_one()
