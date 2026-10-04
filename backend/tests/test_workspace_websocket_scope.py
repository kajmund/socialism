"""Realtime deliveries recheck revocation and release SQL before socket sends."""

import pytest

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketState

from app.database.base import Base
from app.database.models import Job, Kund, UserAccount
from app.database.workspaces import WorkspaceMembership
from app.realtime.hub import EventHub
from app.realtime.research_progress_broadcast import ResearchProgressBroadcastRegistry
from app.services.execution.service import create_attempt, create_run
from app.services.workspace_ws_scope import workspace_event_authorizer
from app.services.workspaces import create_client_workspace


class Socket:
    client_state = WebSocketState.CONNECTED

    def __init__(self, engine, factory):
        self.engine = engine
        self.factory = factory
        self.events = []

    async def send_json(self, event):
        assert self.engine.pool.checkedout() == 0
        async with self.factory() as probe:
            assert await probe.get(Kund, 1) is not None
        self.events.append(event)


async def test_job_and_research_push_stop_after_membership_revocation(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'realtime.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="Firm", slug="firm", available_modules=[]))
        session.add(UserAccount(id="user", email="user@test.local", role="user", kund_id=1))
        await session.flush()
        workspace = await create_client_workspace(
            session, customer_id=1, user_id="user", name="Private"
        )
        workspace_id = workspace.id
        session.add(
            Job(
                id="job",
                customer_id=1,
                kind="workspace_research",
                status="pending",
                request={"workspace_id": workspace_id, "owner_user_id": "user"},
            )
        )
        run = await create_run(
            session,
            customer_id=1,
            module="dd",
            title="Private",
            context={"workspace_id": workspace_id},
        )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="test",
            configuration_snapshot={},
            input_snapshot={},
        )
        attempt_id = attempt.id
    jobs = EventHub(name="workspace-jobs-test")
    research = ResearchProgressBroadcastRegistry()
    job_socket, research_socket = Socket(engine, factory), Socket(engine, factory)
    await jobs.subscribe(
        job_socket, customer_id=1, authorize=workspace_event_authorizer(factory, "user")
    )
    await research.subscribe(
        attempt_id,
        research_socket,
        authorize=workspace_event_authorizer(factory, "user", attempt_id=attempt_id),
    )
    job_event = {"type": "job.updated", "job": {"id": "job", "customer_id": 1}}
    research_event = {"type": "research.progress", "attempt_id": attempt_id}
    try:
        await jobs.publish(job_event)
        await research.publish(attempt_id, research_event)
        assert job_socket.events == [job_event]
        assert research_socket.events == [research_event]
        async with factory.begin() as session:
            await session.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
            )
        await jobs.publish(job_event)
        await research.publish(attempt_id, research_event)
        assert job_socket.events == [job_event]
        assert research_socket.events == [research_event]
    finally:
        await jobs.unsubscribe(job_socket)
        await research.unsubscribe(research_socket)
        await engine.dispose()


@pytest.mark.parametrize("research", [False, True])
async def test_unsubscribe_cannot_remove_an_inflight_delivery_authorizer(research):
    class CapturingSocket:
        client_state = WebSocketState.CONNECTED

        def __init__(self):
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    hub = ResearchProgressBroadcastRegistry() if research else EventHub(name="race-test")
    first, second = CapturingSocket(), CapturingSocket()

    async def deny_first(_event):
        await hub.unsubscribe(second)
        return False

    async def deny_second(_event):
        await hub.unsubscribe(first)
        return False

    if research:
        await hub.subscribe("attempt", first, authorize=deny_first)
        await hub.subscribe("attempt", second, authorize=deny_second)
        await hub.publish("attempt", {"type": "research.progress"})
    else:
        await hub.subscribe(first, authorize=deny_first)
        await hub.subscribe(second, authorize=deny_second)
        await hub.publish({"type": "job.updated", "job": {"id": "job", "customer_id": 1}})
    assert first.events == second.events == []
