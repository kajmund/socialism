"""SQLite file engine uses WAL so concurrent reads do not lock writers."""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database.session import _apply_sqlite_file_pragmas, _sqlite_connect_args


def test_sqlite_connect_args_set_busy_timeout() -> None:
    assert _sqlite_connect_args("sqlite+aiosqlite:///./data/x.db") == {"timeout": 30.0}
    assert _sqlite_connect_args("postgresql+asyncpg://localhost/app") == {}


@pytest.mark.asyncio
async def test_sqlite_file_connect_enables_wal(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'wal.db'}"
    engine = create_async_engine(url, connect_args=_sqlite_connect_args(url))

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:
        _apply_sqlite_file_pragmas(dbapi_connection)

    async with engine.connect() as connection:
        mode = (await connection.execute(text("PRAGMA journal_mode"))).scalar()
        timeout = (await connection.execute(text("PRAGMA busy_timeout"))).scalar()
    await engine.dispose()
    assert str(mode).lower() == "wal"
    assert int(timeout) == 30000
