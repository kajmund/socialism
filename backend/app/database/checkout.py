"""Log a pool checkout that is still held, with the caller that took it.

The pool timeout only says that every connection was busy. This records how
long each checkout lasted and emits ``db_connection_checkout_ms`` as soon as
one stays out past the threshold, before the waiter gives up.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import ConnectionPoolEntry

from app.observability.events import EVENT_DATASET_RESEARCH, log_event
from app.observability.research import record_db_connection_checkout

logger = logging.getLogger("app.db.checkout")

EVENT_DB_CONNECTION_CHECKOUT = "db.connection.checkout"
# A second is already past a normal statement. HTTP and embeddings held
# across a checkout show up here, not at the 30s pool timeout.
CHECKOUT_WARN_AFTER_S = 1.0
_STACK_FRAMES = 8

_INFO_AT = "db_checkout_at"
_INFO_STACK = "db_checkout_stack"
_INFO_GEN = "db_checkout_gen"
_INFO_WARNED = "db_checkout_warned"
_registered: set[int] = set()


def register_connection_checkout(
    engine: AsyncEngine,
    *,
    warn_after_s: float = CHECKOUT_WARN_AFTER_S,
) -> None:
    if warn_after_s <= 0:
        raise ValueError("warn_after_s must be > 0")
    key = id(engine.sync_engine)
    if key in _registered:
        return
    _registered.add(key)
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "checkout")
    def _on_checkout(
        _dbapi_connection: object,
        connection_record: ConnectionPoolEntry,
        _connection_proxy: object,
    ) -> None:
        generation = time.perf_counter_ns()
        connection_record.info[_INFO_AT] = time.perf_counter()
        connection_record.info[_INFO_STACK] = _app_stack()
        connection_record.info[_INFO_GEN] = generation
        connection_record.info[_INFO_WARNED] = False
        _arm_hold_warning(connection_record, generation, warn_after_s)

    @event.listens_for(sync_engine, "checkin")
    def _on_checkin(
        _dbapi_connection: object,
        connection_record: ConnectionPoolEntry,
    ) -> None:
        _finish(connection_record, warn_after_s)


def _arm_hold_warning(
    connection_record: ConnectionPoolEntry,
    generation: int,
    warn_after_s: float,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.call_later(warn_after_s, _warn_if_held, connection_record, generation)


def _warn_if_held(
    connection_record: ConnectionPoolEntry,
    generation: int,
) -> None:
    if connection_record.info.get(_INFO_GEN) != generation:
        return
    started = connection_record.info.get(_INFO_AT)
    if not isinstance(started, float):
        return
    connection_record.info[_INFO_WARNED] = True
    stack = connection_record.info.get(_INFO_STACK)
    _emit(
        (time.perf_counter() - started) * 1000,
        stack if isinstance(stack, str) else "",
        phase="held",
    )


def _finish(connection_record: ConnectionPoolEntry, warn_after_s: float) -> None:
    started = connection_record.info.pop(_INFO_AT, None)
    stack = connection_record.info.pop(_INFO_STACK, None)
    connection_record.info.pop(_INFO_GEN, None)
    connection_record.info.pop(_INFO_WARNED, None)
    if not isinstance(started, float):
        return
    duration_ms = (time.perf_counter() - started) * 1000
    record_db_connection_checkout(duration_ms)
    if duration_ms >= warn_after_s * 1000:
        _emit(duration_ms, stack if isinstance(stack, str) else "", phase="released")


def _emit(duration_ms: float, stack: str, *, phase: str) -> None:
    log_event(
        logger,
        EVENT_DB_CONNECTION_CHECKOUT,
        dataset=EVENT_DATASET_RESEARCH,
        outcome="failure" if phase == "held" else "success",
        duration_ms=duration_ms,
        level=logging.WARNING,
        fields={
            "db_connection_checkout_ms": duration_ms,
            "checkout_phase": phase,
            "checkout_stack": stack,
        },
    )


def _app_stack() -> str:
    lines: list[str] = []
    task = asyncio.current_task()
    frames = task.get_stack(limit=40) if task is not None else []
    for frame in frames:
        code = frame.f_code
        formatted = _format_frame(code.co_filename, frame.f_lineno, code.co_name)
        if formatted is not None:
            lines.append(formatted)
    if not lines:
        for frame in traceback.extract_stack(limit=40):
            formatted = _format_frame(frame.filename, frame.lineno, frame.name)
            if formatted is not None:
                lines.append(formatted)
    return " < ".join(lines[-_STACK_FRAMES:])


def _format_frame(filename: str, lineno: int, name: str) -> str | None:
    path = Path(filename)
    if "site-packages" in path.parts or path.name == "checkout.py":
        return None
    if "app" not in path.parts and not path.name.startswith("test_"):
        return None
    return f"{path.name}:{lineno} {name}"
