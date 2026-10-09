"""Process-local ownership and deterministic replacement of live audio sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

CloseSession = Callable[[str], Awaitable[None]]
SessionKey = tuple[str, str]


@dataclass(slots=True)
class LiveSpeechLease:
    id: str
    generation: int
    user_id: str
    customer_id: int
    workspace_id: str
    expert_id: str
    language: str
    created_at: datetime
    close: CloseSession
    closed: asyncio.Event = field(default_factory=asyncio.Event)


class LiveSpeechRegistry:
    def __init__(self) -> None:
        self._leases: dict[SessionKey, LiveSpeechLease] = {}
        self._generations: dict[SessionKey, int] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        *,
        user_id: str,
        customer_id: int,
        workspace_id: str,
        expert_id: str,
        language: str,
        close: CloseSession,
    ) -> LiveSpeechLease:
        key = (user_id, workspace_id)
        async with self._lock:
            previous = self._leases.get(key)
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation
            lease = LiveSpeechLease(
                id=str(uuid4()),
                generation=generation,
                user_id=user_id,
                customer_id=customer_id,
                workspace_id=workspace_id,
                expert_id=expert_id,
                language=language,
                created_at=datetime.now(UTC),
                close=close,
            )
            self._leases[key] = lease
        if previous is not None:
            await asyncio.gather(previous.close("replaced"), return_exceptions=True)
        return lease

    async def release(self, lease: LiveSpeechLease) -> None:
        key = (lease.user_id, lease.workspace_id)
        async with self._lock:
            if self._leases.get(key) is lease:
                self._leases.pop(key, None)
        lease.closed.set()

    async def close_all(self) -> None:
        async with self._lock:
            leases = list(self._leases.values())
            self._leases.clear()
        await asyncio.gather(
            *(lease.close("shutdown") for lease in leases),
            return_exceptions=True,
        )

