"""Speculative read-only tool execution on stable partial transcripts (§6)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from uuid import uuid4

from openai import OpenAIError

from app.services.expert_workspace_tool_run import run_workspace_tool_call
from app.services.speculative_results import normalize_query

logger = logging.getLogger(__name__)

# Query-based, read-only tools. Nothing here writes or acts externally.
READ_ONLY_QUERY_TOOLS = ("find_documents", "search_knowledge")


class SpeculativeReader:
    """Prefetch read-only results while the user is still speaking.

    Only the latest stable partial runs; a newer partial cancels the previous
    task. Results are keyed by (tool, normalized query) and are reusable only
    when the final question matches the preliminary query exactly.
    """

    def __init__(
        self,
        *,
        workspace_id: str | None,
        user_id: str,
        workspace_state: object,
        min_chars: int,
        enabled: bool,
    ) -> None:
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._workspace_state = workspace_state
        self._min_chars = min_chars
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None
        self._query = ""
        self._results: dict[tuple[str, str], str] = {}

    def on_partial(self, text: str) -> None:
        if not self._enabled:
            return
        query = normalize_query(text)
        if len(query) < self._min_chars or query == self._query:
            return
        self._query = query
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._run(query))

    def matches(self, final_text: str) -> dict[tuple[str, str], str] | None:
        if not self._enabled or not self._results:
            return None
        if self._query and normalize_query(final_text) == self._query:
            return self._results
        return None

    async def aclose(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self, query: str) -> None:
        results: dict[tuple[str, str], str] = {}
        try:
            for name in READ_ONLY_QUERY_TOOLS:
                call = SimpleNamespace(
                    name=name, arguments={"query": query}, id=f"spec-{uuid4().hex}",
                )
                work = SimpleNamespace(
                    workspace_id=self._workspace_id,
                    actor_user_id=self._user_id,
                    workspace_state=self._workspace_state,
                    workspace_intent=None,
                )
                results[(name, query)] = await run_workspace_tool_call(call, work)
        except asyncio.CancelledError:
            raise
        except (ValueError, RuntimeError, TimeoutError, OSError, OpenAIError):
            logger.warning("live_speech.speculation_failed query=%r", query)
        if query == self._query:
            self._results = results
