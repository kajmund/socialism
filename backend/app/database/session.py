from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _ensure_sqlite_parent(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    # sqlite+aiosqlite:///./data/file.db → ./data/file.db
    raw = url.split(":///", 1)[-1]
    if raw.startswith(":memory:"):
        return
    Path(raw).parent.mkdir(parents=True, exist_ok=True)


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def _sqlite_connect_args(url: str) -> dict[str, object]:
    if not _is_sqlite_url(url):
        return {}
    # sqlite3.connect timeout is the busy-wait, in seconds.
    return {"timeout": 30.0}


def _apply_sqlite_file_pragmas(dbapi_connection: object) -> None:
    """WAL so readers do not block writers. busy_timeout is per connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _register_sqlite_pragmas(engine) -> None:
    if not _is_sqlite_url(settings.database_url):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, _connection_record) -> None:
        _apply_sqlite_file_pragmas(dbapi_connection)


_ensure_sqlite_parent(settings.database_url)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=_sqlite_connect_args(settings.database_url),
)
_register_sqlite_pragmas(engine)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def ensure_sqlite_wal() -> None:
    """Force WAL on the file so a leftover DELETE-mode DB is upgraded."""
    if not _is_sqlite_url(settings.database_url):
        return
    async with engine.connect() as connection:
        await connection.execute(text("PRAGMA journal_mode=WAL"))
        await connection.execute(text("PRAGMA busy_timeout=30000"))
        await connection.commit()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
