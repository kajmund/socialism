"""Native inboxes and read markers never cross private canvas boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, Persona, PersonaMessage, SmeReadCursor
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import WorkspaceExpertThread
from app.database.workspaces import WorkspaceMembership
from app.services.voice_workspace_inbox import cursor_thread_id
from tests.conftest import ADMIN_USER_ID, USER_USER_ID


async def create_canvas(client, *, headers=None, parent=None):
    response = await client.post("/voice-workspaces?customer_id=1", headers=headers, json={
        "title": "Inbox canvas", "idempotency_key": str(uuid4()), "workspace_id": parent})
    assert response.status_code == 201, response.text
    return response.json()


async def provider_session(factory, canvas, expert_id, *, owner=ADMIN_USER_ID, customer=1, generation=1):
    async with factory() as session:
        provider = WorkspaceConversationSession(id=str(uuid4()), workspace_id=canvas["id"], user_id=owner,
            customer_id=customer, expert_id=expert_id, mode="text", generation=generation, status="revoked",
            expires_at=datetime.now(UTC) + timedelta(hours=1), prompt_version="p", agent_version="a", agent_id="a")
        session.add(provider)
        await session.commit()
        return provider.id


async def native_message(factory, provider_id, text, *, role="assistant", mode="workspace"):
    async with factory() as session:
        provider = await session.get(WorkspaceConversationSession, provider_id)
        message = PersonaMessage(persona_id=provider.expert_id, mode=mode, role=role, content=text)
        session.add(message)
        await session.flush()
        session.add(WorkspaceConversationEvent(session_id=provider.id, event_key=str(uuid4()),
            kind="user" if role == "user" else "agent", message_id=message.id, payload={"text": text}))
        await session.commit()
        return message.id


@pytest.fixture
async def inbox_context(client_db):
    client, factory = client_db
    async with factory() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        assert await session.scalar(text("PRAGMA foreign_keys")) == 1
        await session.commit()
    canvas = await create_canvas(client)
    async with factory() as session:
        expert_id = await session.scalar(select(Persona.id).where(Persona.customer_id == 1, Persona.kind == "expert").limit(1))
        session.add(WorkspaceExpertThread(workspace_id=canvas["id"], expert_id=expert_id))
        await session.commit()
    provider_id = await provider_session(factory, canvas, expert_id)
    return client, factory, canvas, expert_id, provider_id


async def get_inbox(client, canvas, *, headers=None):
    response = await client.get(f"/voice-workspaces/{canvas['id']}/inbox", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_private_preview_and_unread_survive_read_and_stable_correction(inbox_context):
    client, factory, canvas, expert, provider = inbox_context
    await native_message(factory, provider, "Question", role="user")
    answer = await native_message(factory, provider, "Native answer")
    await native_message(factory, provider, "Legacy answer must stay separate", mode="interview")
    async with factory() as session:
        session.add(SmeReadCursor(user_id=ADMIN_USER_ID, thread_type="expert", thread_id=expert, last_read_message_id=9999))
        session.add(WorkspaceConversationEvent(session_id=provider, event_key="duplicate-link", kind="agent", message_id=answer, payload={}))
        await session.commit()
    assert (await get_inbox(client, canvas))[0]["preview"] == "Native answer"
    assert (await get_inbox(client, canvas))[0]["unread_count"] == 1
    read_url = f"/voice-workspaces/{canvas['id']}/experts/{expert}/read"
    assert (await client.post(read_url)).json() == {"last_read_message_id": answer}
    assert (await client.post(read_url)).json() == {"last_read_message_id": answer}
    async with factory() as session:
        (await session.get(PersonaMessage, answer)).content = "Corrected answer"
        session.add(WorkspaceConversationEvent(session_id=provider, event_key="correction", kind="correction", message_id=answer, payload={}))
        await session.commit()
    corrected = (await get_inbox(client, canvas))[0]
    assert corrected["preview"] == "Corrected answer" and corrected["unread_count"] == 0
    async with factory() as session:
        cursors = list(await session.scalars(select(SmeReadCursor)))
        assert {(row.thread_type, row.thread_id, row.last_read_message_id) for row in cursors} == {
            ("expert", expert, 9999), ("voice_expert", cursor_thread_id(canvas["id"], expert), answer)}
    await native_message(factory, provider, "New answer")
    assert (await get_inbox(client, canvas))[0]["unread_count"] == 1


@pytest.mark.asyncio
async def test_sibling_canvas_read_state_and_preview_are_separate(inbox_context):
    client, factory, first, expert, provider = inbox_context
    first_message = await native_message(factory, provider, "First canvas")
    second = await create_canvas(client)
    sibling_provider = await provider_session(factory, second, expert)
    sibling_message = await native_message(factory, sibling_provider, "Second canvas")
    assert (await get_inbox(client, first))[0]["preview"] == "First canvas"
    assert (await get_inbox(client, second))[0]["preview"] == "Second canvas"
    marked = await client.post(f"/voice-workspaces/{first['id']}/experts/{expert}/read")
    assert marked.json()["last_read_message_id"] == first_message < sibling_message
    assert (await get_inbox(client, first))[0]["unread_count"] == 0
    assert (await get_inbox(client, second))[0]["unread_count"] == 1


@pytest.mark.asyncio
async def test_sibling_owner_cannot_read_or_mark_even_as_admin(inbox_context, user_token):
    client, factory, admin_canvas, expert, _ = inbox_context
    user_headers = {"Authorization": f"Bearer {user_token}"}
    user_canvas = await create_canvas(client, headers=user_headers)
    provider = await provider_session(factory, user_canvas, expert, owner=USER_USER_ID)
    await native_message(factory, provider, "Private user answer")
    for canvas, headers in ((admin_canvas, user_headers), (user_canvas, None)):
        assert (await client.get(f"/voice-workspaces/{canvas['id']}/inbox", headers=headers)).status_code == 404
        assert (await client.post(f"/voice-workspaces/{canvas['id']}/experts/{expert}/read", headers=headers)).status_code == 404
    assert (await get_inbox(client, user_canvas, headers=user_headers))[0]["preview"] == "Private user answer"


@pytest.mark.asyncio
async def test_cross_customer_expert_and_misbound_sessions_never_enter_inbox(inbox_context):
    client, factory, canvas, expert, _ = inbox_context
    async with factory() as session:
        session.add(Kund(id=999, slug="inbox-other-customer", name="Other", available_modules=[]))
        await session.flush()
        other_expert = Persona(id=str(uuid4()), customer_id=999, kind="expert", name="Other expert", occ="Expert", district="")
        session.add(other_expert)
        await session.commit()
        other_id = other_expert.id
    other = await provider_session(factory, canvas, other_id, customer=999, generation=2)
    wrong_owner = await provider_session(factory, canvas, expert, owner=USER_USER_ID, generation=3)
    wrong_customer = await provider_session(factory, canvas, expert, customer=999, generation=4)
    for provider in (other, wrong_owner, wrong_customer):
        await native_message(factory, provider, "Must not leak")
    assert await get_inbox(client, canvas) == [{"expert_id": expert, "preview": "", "last_message_at": None, "unread_count": 0}]
    assert (await client.post(f"/voice-workspaces/{canvas['id']}/experts/{other_id}/read")).status_code == 404


@pytest.mark.asyncio
async def test_current_parent_membership_required_for_inbox_and_read(inbox_context, user_token):
    client, factory, _, expert, _ = inbox_context
    headers = {"Authorization": f"Bearer {user_token}"}
    parent = (await client.post("/workspaces", headers=headers, json={"name": "Private client"})).json()["id"]
    canvas = await create_canvas(client, headers=headers, parent=parent)
    provider = await provider_session(factory, canvas, expert, owner=USER_USER_ID)
    await native_message(factory, provider, "Member answer")
    assert (await get_inbox(client, canvas, headers=headers))[0]["unread_count"] == 1
    async with factory() as session:
        await session.delete(await session.get(WorkspaceMembership, (parent, USER_USER_ID)))
        await session.commit()
    assert (await client.get(f"/voice-workspaces/{canvas['id']}/inbox", headers=headers)).status_code == 404
    assert (await client.post(f"/voice-workspaces/{canvas['id']}/experts/{expert}/read", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_cursor_upsert_uses_returned_id_without_rowcount_and_preview_is_bounded(inbox_context, monkeypatch):
    client, factory, canvas, expert, provider = inbox_context
    original = AsyncSession.execute
    class NoRowcount:
        def __init__(self, result):
            self.result = result
        def __getattr__(self, name):
            assert name != "rowcount", "PostgreSQL cursor rowcount is not reliable"
            return getattr(self.result, name)
    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        return NoRowcount(result) if getattr(statement, "is_insert", False) else result
    monkeypatch.setattr(AsyncSession, "execute", execute)
    read_url = f"/voice-workspaces/{canvas['id']}/experts/{expert}/read"
    assert (await client.post(read_url)).json() == {"last_read_message_id": None}
    message_id = await native_message(factory, provider, "a" * 10000)
    assert len((await get_inbox(client, canvas))[0]["preview"]) == 240
    assert (await client.post(read_url)).json() == {"last_read_message_id": message_id}
    assert (await client.post(read_url)).json() == {"last_read_message_id": message_id}
    assert (await get_inbox(client, canvas))[0]["unread_count"] == 0
