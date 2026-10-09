"""Persistence and response helpers shared by persona chat turns."""

from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PersonaMessage
from app.services.expert_reasoning_episode import attach_reply_reasoning
from app.services.library_chat_fifo import trim_and_commit_library_chat

LibraryTurnWriteGuard = Callable[[AsyncSession], Awaitable[bool]]


class ChatTurnError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


async def discard_user_message(
    session: AsyncSession,
    user_row: PersonaMessage,
) -> None:
    if user_row.id is None:
        return
    existing = await session.get(PersonaMessage, user_row.id)
    if existing is None:
        return
    await session.delete(existing)
    await session.commit()


async def commit_library_message(
    session: AsyncSession,
    row: PersonaMessage,
    *,
    sme_expert_turn_request_id: str | None,
    persist_guard: LibraryTurnWriteGuard | None,
) -> None:
    if persist_guard is not None and not await persist_guard(session):
        raise ChatTurnError("stale_expert_turn", status_code=409)
    attach_reply_reasoning(row)
    row.sme_expert_turn_request_id = sme_expert_turn_request_id
    session.add(row)
    await trim_and_commit_library_chat(session, row.persona_id, row.mode)


def history_rows(
    rows: list[PersonaMessage],
) -> list[tuple[str, str, str | None, str | None]]:
    return [
        (row.role, row.content, row.image_sha256, row.reasoning_content)
        for row in rows
    ]


def append_configured_system_prompt(
    current: str,
    prompts: Mapping[str, str],
    key: str | None,
) -> str:
    if key is None:
        return current
    configured = prompts[key].strip()
    return f"{current}\n\n{configured}".strip() if current else configured


def transform_assistant_reply(
    reply: str,
    transform: Callable[[str], str] | None,
) -> str:
    return transform(reply) if transform is not None else reply
