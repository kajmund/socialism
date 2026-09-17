"""SME product shell API coverage."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database.models import (
    Persona,
    PersonaMessage,
    Population,
    PopulationMember,
    SmeExpertTurn,
    SmePanelMessage,
)
from app.serializers import utcnow
from app.services.sme_expert_turns import (
    SmeExpertTurnConflict,
    accept_expert_turn,
    reclaim_expired_expert_turn,
    renew_expert_turn_lease,
)
from app.services.sme_panel_chat import run_panel_message
import app.services.sme_panel_lease as panel_lease_mod
from app.services.sme_panel_lease import (
    panel_lease_still_held,
    release_panel_lease,
    renew_panel_lease,
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


@pytest.mark.asyncio
async def test_stale_panel_lease_cannot_renew_after_losing_fence(client_db) -> None:
    _client, factory = client_db
    panel_id, _expert = await _create_panel(factory, name="Renew-fence")

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
        renewed = await renew_panel_lease(
            stale, panel_id, token="old-token", fence=1
        )
        await stale.commit()
    assert renewed is False


@pytest.mark.asyncio
async def test_panel_lease_heartbeat_blocks_second_session_after_ttl(
    client_db, monkeypatch
) -> None:
    client, factory = client_db
    await _enable_sme(client)
    panel_id, _expert = await _create_panel(factory, name="Heartbeat-panel")
    me = await client.get("/me")
    user_id = me.json()["id"]
    monkeypatch.setattr(panel_lease_mod, "PANEL_TURN_LEASE_SECONDS", 0.15)

    started = asyncio.Event()
    release_first = asyncio.Event()
    seen_histories: list[list[str]] = []
    second_started_during_first = False

    async def fake_reply(_profile, _mode, history, message, **_kwargs):
        nonlocal second_started_during_first
        seen_histories.append([row[1] for row in history] + [message])
        if message == "första":
            started.set()
            await release_first.wait()
        else:
            second_started_during_first = True
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
    await asyncio.sleep(0.4)
    async with factory() as other:
        stolen = await try_acquire_panel_lease(other, panel_id, token="thief")
        await other.commit()
    assert stolen is None
    assert second_started_during_first is False
    async with factory() as session_a, factory() as session_b:
        assert session_a is not session_b
    release_first.set()
    await asyncio.gather(task_a, task_b)

    assert seen_histories[0] == ["första"]
    assert "första" in seen_histories[1]
    assert seen_histories[1][-1] == "andra"
    assert second_started_during_first is True

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


async def _first_expert_id(factory) -> str:
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
        expert.tools = []
        await session.commit()
        return expert.id


async def _seed_expert_turn(
    session,
    *,
    request_id: str,
    persona_id: str,
    message: str,
    expired: bool = True,
) -> SmeExpertTurn:
    now = utcnow()
    turn = SmeExpertTurn(
        request_id=request_id,
        customer_id=TEST_CUSTOMER_ID,
        user_id=USER_USER_ID,
        persona_id=persona_id,
        message=message,
        image_sha256=None,
        status="running",
        fence=1,
        lease_token="dead-worker",
        lease_expires_at=(
            now - timedelta(seconds=1) if expired else now + timedelta(seconds=60)
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(turn)
    await session.flush()
    return turn


@pytest.mark.asyncio
async def test_expert_turn_request_id_payload_mismatch_conflicts(
    client_db,
) -> None:
    _client, factory = client_db
    persona_id = await _first_expert_id(factory)
    async with factory() as first:
        turn, should_run = await accept_expert_turn(
            first,
            request_id="req-payload",
            customer_id=TEST_CUSTOMER_ID,
            user_id=USER_USER_ID,
            persona_id=persona_id,
            message="första frågan",
            image_sha256=None,
        )
        await first.commit()
    assert should_run is True
    assert turn.status == "accepted"

    async with factory() as second:
        assert second is not first
        with pytest.raises(SmeExpertTurnConflict):
            await accept_expert_turn(
                second,
                request_id="req-payload",
                customer_id=TEST_CUSTOMER_ID,
                user_id=USER_USER_ID,
                persona_id=persona_id,
                message="annan fråga",
                image_sha256=None,
            )
        with pytest.raises(SmeExpertTurnConflict):
            await accept_expert_turn(
                second,
                request_id="req-payload",
                customer_id=TEST_CUSTOMER_ID,
                user_id=USER_USER_ID,
                persona_id=persona_id,
                message="första frågan",
                image_sha256="a" * 64,
            )


@pytest.mark.asyncio
async def test_stale_expert_turn_cannot_renew_after_reclaim(client_db) -> None:
    _client, factory = client_db
    persona_id = await _first_expert_id(factory)
    async with factory() as first:
        await _seed_expert_turn(
            first,
            request_id="req-stale-renew",
            persona_id=persona_id,
            message="Hej",
        )
        await first.commit()

    async with factory() as second:
        turn = await second.get(SmeExpertTurn, "req-stale-renew")
        assert turn is not None
        outcome = await reclaim_expired_expert_turn(second, turn)
        await second.commit()
    assert outcome == "rerun"

    async with factory() as stale:
        renewed = await renew_expert_turn_lease(
            stale,
            "req-stale-renew",
            token="dead-worker",
            fence=1,
        )
        await stale.commit()
    assert renewed is False


@pytest.mark.asyncio
async def test_expired_expert_turn_reclaims_saved_messages_without_duplicates(
    client_db,
) -> None:
    client, factory = client_db
    await _enable_sme(client)
    persona_id = await _first_expert_id(factory)
    request_id = "req-after-save"
    async with factory() as first:
        await _seed_expert_turn(
            first,
            request_id=request_id,
            persona_id=persona_id,
            message="Fråga efter sparning",
        )
        first.add(
            PersonaMessage(
                persona_id=persona_id,
                mode="interview",
                role="user",
                content="Fråga efter sparning",
                created_at=utcnow(),
            )
        )
        first.add(
            PersonaMessage(
                persona_id=persona_id,
                mode="interview",
                role="assistant",
                content="Sparat svar",
                created_at=utcnow(),
            )
        )
        await first.commit()

    async with factory() as second:
        assert second is not first
        lookup = await client.get(f"/sme/expert-turns/{request_id}")
        assert lookup.status_code == 200
        body = lookup.json()
        assert body["status"] == "succeeded"
        assistants = [row for row in body["messages"] if row["role"] == "assistant"]
        assert [row["content"] for row in assistants] == ["Sparat svar"]

    again = await client.get(f"/sme/expert-turns/{request_id}")
    assert again.status_code == 200
    assert again.json()["status"] == "succeeded"
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(PersonaMessage)
                    .where(
                        PersonaMessage.persona_id == persona_id,
                        PersonaMessage.mode == "interview",
                    )
                    .order_by(PersonaMessage.id.asc())
                )
            )
            .scalars()
            .all()
        )
    assert [row.content for row in rows if row.role == "assistant"] == ["Sparat svar"]
    stored = await _wait_expert_status(factory, request_id, {"succeeded"})
    assert stored.status == "succeeded"


@pytest.mark.asyncio
async def test_expired_expert_turn_reruns_after_process_loss_before_save(
    client_db,
) -> None:
    client, factory = client_db
    await _enable_sme(client)
    persona_id = await _first_expert_id(factory)
    request_id = "req-before-save"
    async with factory() as first:
        await _seed_expert_turn(
            first,
            request_id=request_id,
            persona_id=persona_id,
            message="Fråga före sparning",
        )
        await first.commit()

    async with factory() as second:
        assert second is not first
        lookup = await client.get(f"/sme/expert-turns/{request_id}")
        assert lookup.status_code == 200
        assert lookup.json()["status"] != "succeeded"
        assert lookup.json()["status"] in {"accepted", "running"}

    body = await _wait_expert_lookup(client, request_id, {"succeeded", "failed"})
    assert body["status"] == "succeeded"
    assistants = [row for row in body["messages"] if row["role"] == "assistant"]
    assert len(assistants) == 1
    users = [row for row in body["messages"] if row["role"] == "user"]
    assert [row["content"] for row in users] == ["Fråga före sparning"]

    stored = await _wait_expert_status(factory, request_id, {"succeeded"})
    assert stored.status == "succeeded"


@pytest.mark.asyncio
async def test_expired_expert_turn_fails_when_rerun_is_unsafe(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)
    persona_id = await _first_expert_id(factory)
    request_id = "req-unsafe"
    async with factory() as first:
        await _seed_expert_turn(
            first,
            request_id=request_id,
            persona_id=persona_id,
            message="Ofärdig fråga",
        )
        first.add(
            PersonaMessage(
                persona_id=persona_id,
                mode="interview",
                role="user",
                content="Ofärdig fråga",
                created_at=utcnow(),
            )
        )
        first.add(
            PersonaMessage(
                persona_id=persona_id,
                mode="interview",
                role="user",
                content="Senare fråga",
                created_at=utcnow(),
            )
        )
        await first.commit()

    async with factory() as second:
        assert second is not first
        lookup = await client.get(f"/sme/expert-turns/{request_id}")
        assert lookup.status_code == 200
        assert lookup.json()["status"] == "failed"
        assert lookup.json()["error"] == "expert_turn_unrecoverable"

    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(PersonaMessage)
                    .where(PersonaMessage.persona_id == persona_id)
                    .order_by(PersonaMessage.id.asc())
                )
            )
            .scalars()
            .all()
        )
    assert [row.content for row in rows] == ["Ofärdig fråga", "Senare fråga"]


async def _wait_expert_status(
    factory, request_id: str, statuses: set[str]
) -> SmeExpertTurn:
    for _ in range(80):
        async with factory() as session:
            turn = await session.get(SmeExpertTurn, request_id)
            if turn is not None and turn.status in statuses:
                return turn
        await asyncio.sleep(0.05)
    raise AssertionError(f"expert turn {request_id} never reached {statuses}")


async def _wait_expert_lookup(client, request_id: str, statuses: set[str]) -> dict:
    for _ in range(80):
        response = await client.get(f"/sme/expert-turns/{request_id}")
        if response.status_code == 200 and response.json()["status"] in statuses:
            return response.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"expert turn {request_id} lookup never reached {statuses}")
