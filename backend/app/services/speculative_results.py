"""Context-bound speculative read-only tool results for reuse within a turn."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_READ_ONLY = frozenset({"find_documents", "search_knowledge"})
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
    """Return a cached read-only result when the final query extends a prefetch."""
    mapping = _results.get()
    if not mapping or name not in _READ_ONLY:
        return None
    query = normalize_query(arguments.get("query"))
    if not query:
        return None
    exact = mapping.get((name, query))
    if exact is not None:
        return exact
    return _longest_prefix_result(mapping, name, query)


def normalize_query(value: object) -> str:
    if not isinstance(value, str):
        return ""
    folded = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in value.casefold())
    return " ".join(folded.split())


def query_extends(partial: str, final: str) -> bool:
    """True when the final question is the same as, or a token extension of, partial."""
    start = normalize_query(partial)
    complete = normalize_query(final)
    if not start or not complete:
        return False
    if complete == start:
        return True
    start_tokens = start.split()
    complete_tokens = complete.split()
    return complete_tokens[: len(start_tokens)] == start_tokens


def permission_version(workspace_state: object) -> str:
    payload = workspace_state.model_dump() if hasattr(workspace_state, "model_dump") else workspace_state
    blob = repr(payload) if not isinstance(payload, str) else payload
    if isinstance(payload, dict):
        blob = "|".join(f"{key}={payload[key]!r}" for key in sorted(payload))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def scope_key(*, customer_id: int, workspace_id: str | None, user_id: str) -> str:
    return f"{customer_id}:{workspace_id or ''}:{user_id}"


def query_fingerprint(query: str, *, scope: str, version: str) -> str:
    return hashlib.sha256(f"{scope}|{version}|{query}".encode()).hexdigest()[:24]


def _longest_prefix_result(
    mapping: dict[tuple[str, str], str],
    name: str,
    query: str,
) -> str | None:
    best: str | None = None
    best_len = -1
    for (tool, prefetch), result in mapping.items():
        if tool != name:
            continue
        if query_extends(prefetch, query) and len(prefetch) > best_len:
            best = result
            best_len = len(prefetch)
    return best
