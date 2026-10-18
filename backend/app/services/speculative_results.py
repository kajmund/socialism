"""Context-bound speculative read-only tool results for reuse within a turn."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_results: ContextVar[dict[tuple[str, str], str] | None] = ContextVar(
    "speculative_tool_results", default=None
)


@contextmanager
def speculative_results(mapping: dict[tuple[str, str], str] | None) -> Iterator[None]:
    token = _results.set(mapping)
    try:
        yield
    finally:
        _results.reset(token)


def bind_speculative_results(mapping: dict[tuple[str, str], str] | None) -> Token:
    return _results.set(mapping)


def reset_speculative_results(token: Token) -> None:
    _results.reset(token)


def speculative_result_for(name: str, arguments: dict[str, Any]) -> str | None:
    """Return a cached read-only result for the same tool and query, if any."""
    mapping = _results.get()
    if not mapping:
        return None
    query = normalize_query(arguments.get("query"))
    if not query:
        return None
    return mapping.get((name, query))


def normalize_query(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().split())
