"""Panel turns must not hold a DB connection across external expert work."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, Persona, SmeExpertTurn, UserAccount
from app.database.sqlite import async_engine_kwargs, register_sqlite_pragmas
from app.serializers import utcnow
from app.services.persona_chat_turn_support import commit_library_message
from app.services.sme_expert_turns import accept_expert_turn, renew_expert_turn_lease


@pytest.fixture
async def file_sessions(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'panel-tx.db'}"
    engine = create_async_engine(
        database_url,
        **async_engine_kwargs(database_url, pool_size=1, max_overflow=0, pool_timeout=0.3),
    )
    register_sqlite_pragmas(engine, database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Benchmark", slug="benchmark", available_modules=[]))
        session.add(
            UserAccount(
                id="user-1",
                email="panel-tx@example.invalid",
                role="admin",
                kund_id=1,
            )
        )
        session.add(
            Persona(
                id="exp-panel-tx",
                customer_id=1,
                kind="expert",
                name="Klas",
                age=45,
                occ="Analytiker",
                district="Stockholm",
                profile={"name": "Klas", "age": "45"},
                tools=[],
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_panel_lease_guard_releases_connection_before_external_work(
    file_sessions,
) -> None:
    async with file_sessions() as session:
        turn, should_run = await accept_expert_turn(
            session,
            request_id="panel-tx-1",
            customer_id=1,
            user_id="user-1",
            persona_id="exp-panel-tx",
            message="Visa alla hyresavtal.",
            image_sha256=None,
        )
        await session.commit()
        assert should_run
        token = turn.lease_token
        fence = turn.fence
        assert token is not None

    async with file_sessions() as session:
        async def guard(active: AsyncSession) -> bool:
            return await renew_expert_turn_lease(
                active,
                "panel-tx-1",
                token=token,
                fence=fence,
            )

        await commit_library_message(
            session,
            None,
            sme_expert_turn_request_id="panel-tx-1",
            persist_guard=guard,
        )
        assert session.in_transaction() is False

        # One-connection pool: another client can write only when this session
        # has released its connection before the external expert phase.
        async with file_sessions() as other:
            await other.execute(
                text("UPDATE sme_expert_turns SET updated_at = :now"),
                {"now": utcnow()},
            )
            await other.commit()

    async with file_sessions() as session:
        row = await session.get(SmeExpertTurn, "panel-tx-1")
        assert row is not None
        assert row.lease_expires_at is not None
