"""Durable run-store contract shared by the SWE adapter and its implementations.

`app.swe.runtime` writes one `RunRecord` per transition and replays
`InvocationRecord`s on resume. `app.services.overgraph.workflows` implements the
contract, so the runtime stays independent of any persistence backend.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RunRecord:
    """Durable run snapshot as of one transition boundary."""

    run_id: str
    definition_sha256: str
    status: str
    input: Mapping[str, Any]
    output: Any
    error: Mapping[str, Any] | None
    started_at_ms: int
    updated_at_ms: int
    finished_at_ms: int | None
    last_seq: int


@dataclass(frozen=True)
class InvocationRecord:
    """Persisted handler outcome; replayed instead of running the handler again."""

    invocation_id: str
    node_id: str
    ok: bool
    value: Any
    error: str | None


class RunStore(Protocol):
    """Durable run sink, implemented by `app.services.overgraph.workflows`."""

    async def record(
        self,
        run: RunRecord,
        *,
        events: Sequence[Mapping[str, Any]] = (),
        invocation: InvocationRecord | None = None,
    ) -> None: ...

    async def load_run(self, run_id: str) -> RunRecord | None: ...

    async def replay_results(self, run_id: str) -> Mapping[str, InvocationRecord]: ...

    async def events(self, run_id: str) -> list[dict[str, Any]]: ...
