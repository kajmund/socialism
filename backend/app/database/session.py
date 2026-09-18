from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database.sqlite import (
    async_engine_kwargs,
    is_sqlite_url,
    register_sqlite_pragmas,
)


def _ensure_sqlite_parent(url: str) -> None:
    if not is_sqlite_url(url):
        return
    # sqlite+aiosqlite:///./data/file.db → ./data/file.db
    raw = url.split(":///", 1)[-1]
    if raw.startswith(":memory:"):
        return
    Path(raw).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent(settings.database_url)

engine = create_async_engine(
    settings.database_url,
    **async_engine_kwargs(settings.database_url, echo=False),
)
register_sqlite_pragmas(engine, settings.database_url)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
