"""Request/job correlation fields attached to structured log events."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Iterator
from uuid import uuid4


@dataclass(frozen=True)
class LogContext:
    trace_id: str | None = None
    run_id: str | None = None
    attempt_id: str | None = None
    research_question_id: str | None = None
    child_attempt_id: str | None = None
    research_need_id: str | None = None
    customer_id: str | None = None
    module: str | None = None
    wave_number: int | None = None
    job_id: str | None = None


_log_context: ContextVar[LogContext] = ContextVar(
    "observability_log_context", default=LogContext()
)


def current_log_context() -> LogContext:
    return _log_context.get()


def bind_log_context(
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    research_question_id: str | None = None,
    child_attempt_id: str | None = None,
    research_need_id: str | None = None,
    customer_id: str | None = None,
    module: str | None = None,
    wave_number: int | None = None,
    job_id: str | None = None,
    ensure_trace_id: bool = False,
) -> Token[LogContext]:
    current = _log_context.get()
    updates: dict[str, object] = {}
    if trace_id is not None:
        updates["trace_id"] = trace_id
    elif ensure_trace_id and not current.trace_id:
        updates["trace_id"] = uuid4().hex
    if run_id is not None:
        updates["run_id"] = run_id
    if attempt_id is not None:
        updates["attempt_id"] = attempt_id
    if research_question_id is not None:
        updates["research_question_id"] = research_question_id
    if child_attempt_id is not None:
        updates["child_attempt_id"] = child_attempt_id
    if research_need_id is not None:
        updates["research_need_id"] = research_need_id
    if customer_id is not None:
        updates["customer_id"] = customer_id
    if module is not None:
        updates["module"] = module
    if wave_number is not None:
        updates["wave_number"] = wave_number
    if job_id is not None:
        updates["job_id"] = job_id
    return _log_context.set(replace(current, **updates))


def reset_log_context(token: Token[LogContext]) -> None:
    _log_context.reset(token)


@contextmanager
def log_context(**kwargs: object) -> Iterator[LogContext]:
    token = bind_log_context(**kwargs)  # type: ignore[arg-type]
    try:
        yield _log_context.get()
    finally:
        reset_log_context(token)


def context_fields(context: LogContext | None = None) -> dict[str, object]:
    """ECS-shaped identifiers. Omit empty values so Kibana stays sparse."""
    row = context or _log_context.get()
    payload: dict[str, object] = {}
    if row.trace_id:
        payload["trace"] = {"id": row.trace_id}
    if row.run_id:
        payload["run"] = {"id": row.run_id}
    if row.attempt_id:
        payload["attempt"] = {"id": row.attempt_id}
    if row.job_id:
        payload["job"] = {"id": row.job_id}
    if row.customer_id:
        payload["customer"] = {"id": row.customer_id}
    research: dict[str, object] = {}
    if row.research_question_id:
        research["question_id"] = row.research_question_id
    if row.child_attempt_id:
        research["child_attempt_id"] = row.child_attempt_id
    if row.research_need_id:
        research["need_id"] = row.research_need_id
    if row.module:
        research["module"] = row.module
    if row.wave_number is not None:
        research["wave_number"] = row.wave_number
    if research:
        payload["research"] = research
    return payload
