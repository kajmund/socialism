"""SME product shell API coverage."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.database.models import (
    Persona,
    PersonaMessage,
    Population,
    PopulationMember,
    SmePanelMessage,
)
from app.serializers import utcnow
from app.services.sme_panel_chat import run_panel_message
from app.services.sme_panel_lease import (
    panel_lease_still_held,
    release_panel_lease,
    try_acquire_panel_lease,
)
from tests.conftest import TEST_CUSTOMER_ID, USER_USER_ID, mint_access_token


async def _enable_sme(client) -> None:
    response = await client.patch(
        f"/kunder/{TEST_CUSTOMER_ID}",
        json={"product": "sme"},
    )
    assert response.status_code == 200
    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=USER_USER_ID, email='user@test.local')}"
    )


@pytest.mark.asyncio
async def test_sme_expert_inbox_and_read_cursor(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)

    me = await client.get("/me")
    assert me.status_code == 200
    assert me.json()["product"] == "sme"

    inbox = await client.get("/sme/inbox", params={"filter": "all"})
    assert inbox.status_code == 200
    expert = inbox.json()[0]
    assert expert["thread_type"] == "expert"

    async with factory() as session:
        session.add(
            PersonaMessage(
                persona_id=expert["thread_id"],
                mode="interview",
                role="assistant",
                content="Ett nytt expertsvar",
                created_at=utcnow(),
            )
        )
        await session.commit()

    unread = await client.get("/sme/inbox", params={"filter": "unread"})
    assert unread.status_code == 200
    assert unread.json()[0]["unread_count"] == 1

    marked = await client.post(f"/sme/threads/expert/{expert['thread_id']}/read")
    assert marked.status_code == 200
    unread = await client.get("/sme/inbox", params={"filter": "unread"})
    assert unread.json() == []


@pytest.mark.asyncio
async def test_sme_panel_chat_returns_each_expert_response(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)

    async with factory() as session:
        expert = (
            (
                await session.execute(
                    select(Persona).where(
                        Persona.customer_id == TEST_CUSTOMER_ID,
                        Persona.kind == "expert",
                    )
                )
            )
            .scalars()
            .first()
        )
        assert expert is not None
        panel = Population(
            customer_id=TEST_CUSTOMER_ID,
            kind="expert_panel",
            name="SME-panel",
            size=1,
            versions=1,
            fingerprint=[],
            recipe={},
            updated_at=utcnow(),
        )
        session.add(panel)
        await session.flush()
        session.add(
            PopulationMember(
                population_id=panel.id,
                persona_id=expert.id,
                kind="expert",
                name=expert.name,
                initials="EX",
                age=expert.age or 40,
                occ=expert.occ,
                district=expert.district,
                trait="",
            )
        )
        await session.commit()
        panel_id = panel.id

    groups = await client.get("/sme/inbox", params={"filter": "groups"})
    assert groups.status_code == 200
    assert groups.json()[0]["thread_id"] == str(panel_id)

    sent = await client.post(
        f"/sme/panels/{panel_id}/messages",
        json={"message": "Vad bör företaget prioritera?"},
    )
    assert sent.status_code == 200
    messages = sent.json()
    assert [row["role"] for row in messages] == ["user", "assistant"]
    assert messages[1]["persona_name"] == expert.name

    thread = await client.get(f"/sme/panels/{panel_id}/messages")
    assert thread.status_code == 200
    assert len(thread.json()) == 2


async def _create_panel(factory, *, name: str = "SME-panel") -> tuple[int, Persona]:
    async with factory() as session:
        expert = (
            (
                await session.execute(
                    select(Persona).where(
                        Persona.customer_id == TEST_CUSTOMER_ID,
                        Persona.kind == "expert",
                    )
                )
            )
            .scalars()
            .first()
        )
        assert expert is not None
        panel = Population(
            customer_id=TEST_CUSTOMER_ID,
            kind="expert_panel",
            name=name,
            size=1,
            versions=1,
            fingerprint=[],
            recipe={},
            updated_at=utcnow(),
        )
        session.add(panel)
        await session.flush()
        session.add(
            PopulationMember(
                population_id=panel.id,
                persona_id=expert.id,
                kind="expert",
                name=expert.name,
                initials="EX",
                age=expert.age or 40,
                occ=expert.occ,
                district=expert.district,
                trait="",
            )
        )
        await session.commit()
        return panel.id, expert


@pytest.mark.asyncio
async def test_sme_inbox_all_includes_experts_and_panels(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)
    panel_id, _expert = await _create_panel(factory, name="Inbox-panel")

    inbox = await client.get("/sme/inbox", params={"filter": "all"})
    assert inbox.status_code == 200
    types = {row["thread_type"] for row in inbox.json()}
    assert types == {"expert", "panel"}
    assert any(row["thread_id"] == str(panel_id) for row in inbox.json() if row["thread_type"] == "panel")

    groups = await client.get("/sme/inbox", params={"filter": "groups"})
    assert {row["thread_type"] for row in groups.json()} == {"panel"}

    unread = await client.get("/sme/inbox", params={"filter": "unread"})
    assert unread.json() == []


@pytest.mark.asyncio
async def test_sme_user_can_list_jobs(client_db) -> None:
    client, _factory = client_db
    await _enable_sme(client)
    listed = await client.get("/jobs")
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_panel_chat_uses_expert_tools_and_hides_start_research(
    client_db, monkeypatch
) -> None:
    client, factory = client_db
    await _enable_sme(client)
    panel_id, expert = await _create_panel(factory)
    async with factory() as session:
        stored = await session.get(Persona, expert.id)
        assert stored is not None
        stored.tools = ["search_wiki", "start_research"]
        await session.commit()

    captured: list[tuple[list[str] | None, object]] = []

    async def fake_reply(*_args, **kwargs):
        captured.append((kwargs.get("tools"), kwargs.get("research_tool_handler")))
        return "Verktygssvar"

    monkeypatch.setattr("app.services.sme_panel_chat.reply_as_persona", fake_reply)
    sent = await client.post(
        f"/sme/panels/{panel_id}/messages",
        json={"message": "Sök bakgrunden"},
    )
    assert sent.status_code == 200
    assert captured == [(["search_wiki"], None)]


@pytest.mark.asyncio
async def test_panel_chat_without_company_tools_does_not_enable_them(
    client_db, monkeypatch
) -> None:
    client, factory = client_db
    await _enable_sme(client)
    panel_id, expert = await _create_panel(factory)
    async with factory() as session:
        stored = await session.get(Persona, expert.id)
        assert stored is not None
        stored.tools = []
        await session.commit()

    captured: list[list[str] | None] = []

    async def fake_reply(*_args, **kwargs):
        captured.append(kwargs.get("tools"))
        return "Profilsvar"

    monkeypatch.setattr("app.services.sme_panel_chat.reply_as_persona", fake_reply)
    sent = await client.post(
        f"/sme/panels/{panel_id}/messages",
        json={"message": "Hej"},
    )
    assert sent.status_code == 200
    assert captured == [[]]


@pytest.mark.asyncio
async def test_concurrent_panel_turns_serialize_across_two_sessions(
    client_db, monkeypatch
) -> None:
    client, factory = client_db
    await _enable_sme(client)
    panel_id, _expert = await _create_panel(factory, name="Lease-panel")
    me = await client.get("/me")
    user_id = me.json()["id"]

    started = asyncio.Event()
    release_first = asyncio.Event()
    seen_histories: list[list[str]] = []

    async def fake_reply(_profile, _mode, history, message, **_kwargs):
        seen_histories.append([row[1] for row in history] + [message])
        if message == "första":
            started.set()
            await release_first.wait()
        return f"svar:{message}"

    monkeypatch.setattr("app.services.sme_panel_chat.reply_as_persona", fake_reply)

    class _User:
        id = user_id

    async def first_turn() -> None:
        await run_panel_message(
            factory,
            panel_id=panel_id,
            customer_id=TEST_CUSTOMER_ID,
            user=_User(),  # type: ignore[arg-type]
            message="första",
        )

    async def second_turn() -> None:
        await started.wait()
        await run_panel_message(
            factory,
            panel_id=panel_id,
            customer_id=TEST_CUSTOMER_ID,
            user=_User(),  # type: ignore[arg-type]
            message="andra",
        )

    task_a = asyncio.create_task(first_turn())
    task_b = asyncio.create_task(second_turn())
    await started.wait()
    async with factory() as session_a, factory() as session_b:
        assert session_a is not session_b
    release_first.set()
    await asyncio.gather(task_a, task_b)

    assert seen_histories[0] == ["första"]
    assert "första" in seen_histories[1]
    assert seen_histories[1][-1] == "andra"

    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(SmePanelMessage)
                    .where(SmePanelMessage.population_id == panel_id)
                    .order_by(SmePanelMessage.id.asc())
                )
            )
            .scalars()
            .all()
        )
    assert [row.content for row in rows if row.role == "user"] == ["första", "andra"]


@pytest.mark.asyncio
async def test_stale_panel_lease_cannot_overwrite_newer_turn(client_db) -> None:
    _client, factory = client_db
    panel_id, _expert = await _create_panel(factory, name="Fence-panel")

    async with factory() as first:
        fence = await try_acquire_panel_lease(first, panel_id, token="old-token")
        await first.commit()
    assert fence == 1

    async with factory() as second:
        await release_panel_lease(second, panel_id, token="old-token", fence=1)
        newer = await try_acquire_panel_lease(second, panel_id, token="new-token")
        await second.commit()
    assert newer == 2

    async with factory() as stale:
        held = await panel_lease_still_held(
            stale, panel_id, token="old-token", fence=1
        )
        await stale.commit()
    assert held is False
