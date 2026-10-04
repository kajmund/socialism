import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, Persona, PersonaMessage
from app.services import expert_consult
from app.services.expertgranskning.memory import set_expert_memory_factory
from app.services.prompt_catalog import default_prompts
from app.services.workspace_memory_scope import WORKSPACE_MEMORY_SOURCE, workspace_memory_expert_id
from tests.test_expert_consult import RecordingMemory, _expert


async def _consult_database(source_factory, tmp_path):
    async with source_factory() as source:
        customer = await source.get(Kund, 1)
        customer_copy = Kund(**{column.name: getattr(customer, column.name) for column in Kund.__table__.columns})
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/consult.db", pool_size=1, max_overflow=0, pool_timeout=0.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    asker = _expert("consult-asker", "Daniel Nilsson", "Kommunikation")
    colleague = _expert("consult-colleague", "Roger Björnsson", "Skatterätt")
    async with factory() as session:
        session.add_all([customer_copy, asker, colleague])
        await session.commit()
    return engine, factory, asker, colleague


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
async def test_consult_memory_and_broadcast_release_connection_and_private_scope(client_db, tmp_path, monkeypatch, private):
    engine, factory, asker, colleague = await _consult_database(client_db[1], tmp_path)
    waiting, release = asyncio.Event(), asyncio.Event()
    memory = RecordingMemory()
    events = []
    active = {}

    async def add(**kwargs):
        assert not active["session"].in_transaction()
        memory.adds.append(kwargs)
        waiting.set()
        await release.wait()
        return []

    async def publish(*args):
        assert not active["session"].in_transaction()
        events.append(args)

    async def rank(**_kwargs):
        return {asker.id: 0.1, colleague.id: 0.9}

    async def answer(*_args, **_kwargs):
        return "Privat avtalsutdrag"

    async def no_evidence(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(memory, "add_chat_turn", add)
    set_expert_memory_factory(lambda: memory)
    monkeypatch.setattr(expert_consult, "rank_consult_competence", rank)
    monkeypatch.setattr(expert_consult, "reply_as_persona", answer)
    monkeypatch.setattr(expert_consult, "reusable_expert_chat_evidence_context", no_evidence)
    monkeypatch.setattr(expert_consult.library_chat_broadcast, "publish", publish)

    async def run():
        async with factory() as session:
            active["session"] = session
            loaded = await session.get(Persona, asker.id)
            return await expert_consult.expert_consult_handler_for_chat(
                session, asker=loaded, mode="interview", prompts=default_prompts("sv"),
                workspace_owner_id="owner" if private else None,
                workspace_parent_id="parent" if private else None,
            )({"question": "Vad innebär detta privata villkor?"})

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        async with factory() as reader:
            assert await reader.get(Persona, colleague.id) is not None
        release.set()
        result = await task
        async with factory() as reader:
            messages = list((await reader.scalars(select(PersonaMessage))).all())
        assert "Privat avtalsutdrag" in result
        assert len(memory.adds) == 2
        if private:
            assert not events and not messages
            assert {row["source"] for row in memory.adds} == {WORKSPACE_MEMORY_SOURCE}
            assert {row["expert_id"] for row in memory.adds} == {
                workspace_memory_expert_id(asker, "owner", workspace_parent_id="parent"), workspace_memory_expert_id(colleague, "owner", workspace_parent_id="parent"),
            }
        else:
            assert len(events) == 2 and len(messages) == 1
            assert {row["source"] for row in memory.adds} == {"expert_consult"}
    finally:
        release.set()
        if not task.done():
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_consult_evidence_finishes_db_phase_before_memory_read(client_db, tmp_path, monkeypatch):
    engine, factory, asker, colleague = await _consult_database(client_db[1], tmp_path)
    evidence_entered, release_evidence = asyncio.Event(), asyncio.Event()
    memory_entered, release_memory = asyncio.Event(), asyncio.Event()
    memory = RecordingMemory()

    async def evidence(*_args, **_kwargs):
        async with factory() as reader:
            assert await reader.get(Persona, colleague.id)
            evidence_entered.set()
            await release_evidence.wait()
        return ""

    async def search(**_kwargs):
        assert engine.pool.checkedout() == 0
        memory_entered.set()
        await release_memory.wait()
        return []

    async def rank(**_kwargs):
        return {asker.id: 0.1, colleague.id: 0.9}

    async def reply(*_args, **_kwargs):
        return "Answer"

    monkeypatch.setattr(memory, "search", search)
    set_expert_memory_factory(lambda: memory)
    monkeypatch.setattr(expert_consult, "reusable_expert_chat_evidence_context", evidence)
    monkeypatch.setattr(expert_consult, "rank_consult_competence", rank)
    monkeypatch.setattr(expert_consult, "reply_as_persona", reply)

    async def run():
        async with factory() as session:
            loaded = await session.get(Persona, asker.id)
            return await expert_consult.expert_consult_handler_for_chat(session, asker=loaded, mode="interview",
                prompts=default_prompts("sv"), workspace_owner_id="owner", workspace_parent_id="parent")({"question": "Private question"})

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(evidence_entered.wait(), 2)
        assert not memory_entered.is_set()
        release_evidence.set()
        await asyncio.wait_for(memory_entered.wait(), 2)
        async with factory() as reader:
            assert await reader.get(Persona, colleague.id)
        release_memory.set()
        assert "Answer" in await task
    finally:
        release_evidence.set()
        release_memory.set()
        if not task.done():
            await task
        await engine.dispose()
