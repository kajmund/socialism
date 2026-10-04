"""Private workspace results require current access after every external wait."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from app.database.models import Job, UserAccount
from app.database.workspaces import WorkspaceChat, WorkspaceChatMessage, WorkspaceMembership
from tests.test_workspace_chat_documents import (
    USER_ID,
    _tool_reply,
    _turn,
    document_chat as document_chat,
)


async def _revoke_access(fixture, change: str) -> None:
    async with fixture.factory.begin() as session:
        if change == "membership":
            await session.execute(delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == fixture.active,
                WorkspaceMembership.user_id == USER_ID,
            ))
        elif change == "customer":
            user = await session.get(UserAccount, USER_ID)
            user.kund_id = 2
        else:
            chat = await session.get(WorkspaceChat, fixture.chat_id)
            chat.owner_user_id = "foreign-user"


def _suspended_model(fixture, stage: str, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait():
        assert fixture.engine.pool.checkedout() == 0
        entered.set()
        await release.wait()

    async def with_tools(*_args, **_kwargs):
        if stage != "tool_final":
            await wait()
        if stage == "ordinary":
            return SimpleNamespace(content="Privat inventering: parking_receipt_3157386478.pdf", tool_calls=[])
        return _tool_reply({"question": "Vad står på kvittot?", "source_object_ids": ["receipt"]})

    async def complete(*_args, **_kwargs):
        assert stage == "tool_final", "Revoked actor reached another external model call"
        await wait()
        return "Privat inventering: parking_receipt_3157386478.pdf"

    monkeypatch.setattr("app.services.workspace_chat_turn.complete_with_tools", with_tools)
    monkeypatch.setattr("app.services.workspace_chat_turn.complete_text", complete)
    return entered, release


@pytest.mark.parametrize("stage", ["ordinary", "tool_initial", "tool_final"])
@pytest.mark.parametrize("change", ["membership", "customer", "chat_owner"])
async def test_chat_revalidates_after_model_wait(document_chat, monkeypatch, *, stage, change):
    entered, release = _suspended_model(document_chat, stage, monkeypatch)
    task = asyncio.create_task(_turn(document_chat))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with document_chat.factory() as other:
            assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 1) == 1
        await _revoke_access(document_chat, change)
    finally:
        release.set()
    with pytest.raises(HTTPException) as failure:
        await task
    assert failure.value.status_code == 404
    async with document_chat.factory() as session:
        assistant_count = await session.scalar(select(func.count()).select_from(WorkspaceChatMessage).where(
            WorkspaceChatMessage.chat_id == document_chat.chat_id, WorkspaceChatMessage.role == "assistant",
        ))
        user_count = await session.scalar(select(func.count()).select_from(WorkspaceChatMessage).where(
            WorkspaceChatMessage.chat_id == document_chat.chat_id, WorkspaceChatMessage.role == "user",
        ))
        job_count = await session.scalar(select(func.count()).select_from(Job))
    assert assistant_count == 0 and user_count == (2 if stage == "tool_final" else 1)
    assert job_count == (1 if stage == "tool_final" else 0)
