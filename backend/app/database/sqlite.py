"""SQLite connection pragmas for local development and tests.

WAL, foreign_keys, and busy timeout are a defensive complement to short
write transactions — not a substitute. Non-SQLite engines are unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

SQLITE_BUSY_TIMEOUT_MS = 5000


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def sqlite_connect_args(url: str) -> dict[str, Any]:
    """Busy timeout plus memory-DB thread flags. Empty for non-SQLite URLs."""
    if not is_sqlite_url(url):
        return {}
    args: dict[str, Any] = {"timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}
    if ":memory:" in url or url.rstrip("/").endswith("://"):
        args["check_same_thread"] = False
    return args


def _pragma_statements() -> tuple[str, ...]:
    return (
        "PRAGMA journal_mode=WAL",
        "PRAGMA foreign_keys=ON",
        f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}",
    )


def _sqlite3_connection(dbapi_connection: Any) -> Any:
    """Unwrap SQLAlchemy/aiosqlite adapters to the stdlib sqlite3 connection."""
    aio = getattr(dbapi_connection, "_connection", dbapi_connection)
    raw = getattr(aio, "_conn", None) or getattr(aio, "_connection", None)
    return raw if raw is not None else dbapi_connection


def _execute_pragmas(dbapi_connection: Any) -> None:
    raw = _sqlite3_connection(dbapi_connection)
    cursor = raw.cursor()
    try:
        for statement in _pragma_statements():
            cursor.execute(statement)
    finally:
        cursor.close()


def register_sqlite_pragmas(engine: AsyncEngine, url: str) -> None:
    if not is_sqlite_url(url):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _on_sqlite_connect(dbapi_connection: Any, _connection_record: object) -> None:
        _execute_pragmas(dbapi_connection)


def async_engine_kwargs(url: str, **extra: Any) -> Mapping[str, Any]:
    kwargs: dict[str, Any] = dict(extra)
    if is_sqlite_url(url):
        connect_args = dict(kwargs.get("connect_args") or {})
        connect_args.update(sqlite_connect_args(url))
        kwargs["connect_args"] = connect_args
    return kwargs
