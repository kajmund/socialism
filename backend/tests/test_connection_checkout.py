"""A held pool connection is reported before the waiter times out."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.checkout import register_connection_checkout
from app.observability.events import EVENT_PAYLOAD_ATTR
from app.observability.research import research_obs_scope


def _payloads(records: list[logging.LogRecord], phase: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for record in records:
        payload = getattr(record, EVENT_PAYLOAD_ATTR, None)
        if isinstance(payload, dict) and payload.get("checkout_phase") == phase:
            found.append(payload)
    return found


@pytest.mark.asyncio
async def test_held_checkout_is_logged_before_release(caplog: pytest.LogCaptureFixture):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    register_connection_checkout(engine, warn_after_s=0.05)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with caplog.at_level(logging.WARNING, logger="app.db.checkout"):
        with research_obs_scope() as stats:
            async with factory() as session:
                await session.execute(text("select 1"))
                await asyncio.sleep(0.15)
                held = _payloads(caplog.records, "held")
                assert held
                assert float(held[0]["db_connection_checkout_ms"]) >= 50
                assert "test_held_checkout_is_logged_before_release" in str(
                    held[0]["checkout_stack"]
                )
            released = _payloads(caplog.records, "released")
            assert released
            assert float(released[-1]["db_connection_checkout_ms"]) >= 50
            assert stats.db_connection_checkout_count >= 1
            assert stats.db_connection_checkout_ms >= 50
    await engine.dispose()


@pytest.mark.asyncio
async def test_short_checkout_is_not_warned(caplog: pytest.LogCaptureFixture):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    register_connection_checkout(engine, warn_after_s=30)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with caplog.at_level(logging.WARNING, logger="app.db.checkout"):
        async with factory() as session:
            await session.execute(text("select 1"))
        assert _payloads(caplog.records, "held") == []
        assert _payloads(caplog.records, "released") == []
    await engine.dispose()
