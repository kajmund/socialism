"""Speculative read-only tool execution on stable partial transcripts (§6)."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from openai import OpenAIError

from app.config import settings
from app.services.expert_workspace_tool_run import run_workspace_tool_call
from app.services.speculative_results import (
    normalize_query,
    permission_version,
    query_extends,
    query_fingerprint,
    scope_key,
)

logger = logging.getLogger(__name__)

# Query-based, read-only tools. Nothing here writes or acts externally.
READ_ONLY_QUERY_TOOLS = ("find_documents", "search_knowledge")


class SpeculativeReader:
    """Prefetch read-only results while the user is still speaking.

    Only the latest stable partial runs; a newer partial cancels the previous
    task. Independent read-only tools run in parallel with a concurrency cap.
    Results are reusable when the final question is the same normalized
    query, a freshly loaded workspace state still matches the prefetch
    permission version, and the entry has not expired. Search results are
    not reused for a longer query: extra constraints are not monotonic.
    """

    def __init__(
        self,
        *,
        workspace_id: str | None,
        user_id: str,
        workspace_state: object,
        min_chars: int,
        enabled: bool,
        customer_id: int = 0,
    ) -> None:
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._workspace_state = workspace_state
        self._min_chars = min_chars
        self._enabled = enabled
        self._scope = scope_key(
            customer_id=customer_id, workspace_id=workspace_id, user_id=user_id,
        )
        self._version = permission_version(workspace_state)
        self._ttl_s = settings.live_speech_speculation_ttl_ms / 1000
        self._concurrency = settings.live_speech_speculation_concurrency
        self._task: asyncio.Task[None] | None = None
        self._query = ""
        self._fingerprint = ""
        self._ready_at: float | None = None
        self._results: dict[tuple[str, str], str] = {}
        self.stats: dict[str, int | list[float]] = {
            "cache_hits": 0,
            "wasted": 0,
            "incorrect": 0,
            "rejected_mismatch": 0,
            "latency_gain_ms": [],
        }

    def on_partial(self, text: str) -> None:
        if not self._enabled:
            return
        query = normalize_query(text)
        if len(query) < self._min_chars or query == self._query:
            return
        self._query = query
        self._fingerprint = query_fingerprint(
            query, scope=self._scope, version=self._version,
        )
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._bump("wasted")
        self._ready_at = None
        self._task = asyncio.create_task(self._run(query))

    def matches(
        self,
        final_text: str,
        workspace_state: object | None = None,
    ) -> dict[tuple[str, str], str] | None:
        if not self._enabled or not self._results:
            return None
        if not self._reuse_allowed(final_text, workspace_state):
            return None
        self._bump("cache_hits")
        if self._ready_at is not None:
            gains = self.stats["latency_gain_ms"]
            assert isinstance(gains, list)
            gains.append((monotonic() - self._ready_at) * 1000)
        return self._results

    async def aclose(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            self._bump("wasted")
            await asyncio.gather(task, return_exceptions=True)

    def _reuse_allowed(
        self,
        final_text: str,
        workspace_state: object | None,
    ) -> bool:
        final_query = normalize_query(final_text)
        current_state = workspace_state if workspace_state is not None else self._workspace_state
        if permission_version(current_state) != self._version:
            self._bump("rejected_mismatch")
            return False
        if self._ready_at is not None and monotonic() - self._ready_at > self._ttl_s:
            self._bump("wasted")
            return False
        if not self._query or final_query != self._query:
            if final_query and query_extends(final_query, self._query):
                self._bump("incorrect")
            else:
                self._bump("rejected_mismatch")
            return False
        return True

    def _bump(self, name: str) -> None:
        current = self.stats[name]
        if isinstance(current, int):
            self.stats[name] = current + 1

    async def _run(self, query: str) -> None:
        try:
            results = await self._prefetch(query)
        except asyncio.CancelledError:
            raise
        except (ValueError, RuntimeError, TimeoutError, OSError, OpenAIError):
            logger.warning("live_speech.speculation_failed query=%r", query)
            self._bump("wasted")
            return
        if query == self._query:
            self._results = results
            self._ready_at = monotonic()

    async def _prefetch(self, query: str) -> dict[tuple[str, str], str]:
        limit = asyncio.Semaphore(self._concurrency)

        async def one(name: str) -> tuple[tuple[str, str], str]:
            async with limit:
                return await self._read_only(name, query)

        gathered = await asyncio.gather(*(one(name) for name in READ_ONLY_QUERY_TOOLS))
        return dict(gathered)

    async def _read_only(self, name: str, query: str) -> tuple[tuple[str, str], str]:
        if name not in READ_ONLY_QUERY_TOOLS:
            raise RuntimeError("speculative_write_forbidden")
        call = SimpleNamespace(
            name=name, arguments={"query": query}, id=f"spec-{uuid4().hex}",
        )
        work = SimpleNamespace(
            workspace_id=self._workspace_id,
            actor_user_id=self._user_id,
            workspace_state=self._workspace_state,
            workspace_intent=None,
        )
        return (name, query), await run_workspace_tool_call(call, work)
