"""In-process fan-out for expert library-thread updates."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

LibraryChatSubscriber = Callable[[dict[str, Any]], Awaitable[None]]
PersonaKey = tuple[int, str]


class LibraryChatBroadcastRegistry:
    def __init__(self) -> None:
        self._customers: dict[int, set[LibraryChatSubscriber]] = {}
        self._personas: dict[PersonaKey, set[LibraryChatSubscriber]] = {}
        self._lock = asyncio.Lock()

    async def subscribe_customer(
        self,
        customer_id: int,
        subscriber: LibraryChatSubscriber,
    ) -> None:
        async with self._lock:
            self._customers.setdefault(customer_id, set()).add(subscriber)

    async def subscribe_persona(
        self,
        customer_id: int,
        persona_id: str,
        subscriber: LibraryChatSubscriber,
    ) -> None:
        async with self._lock:
            self._personas.setdefault((customer_id, persona_id), set()).add(subscriber)

    async def unsubscribe(self, subscriber: LibraryChatSubscriber) -> None:
        async with self._lock:
            for rooms in (self._customers, self._personas):
                empty = []
                for key, subscribers in rooms.items():
                    subscribers.discard(subscriber)
                    if not subscribers:
                        empty.append(key)
                for key in empty:
                    rooms.pop(key, None)

    async def publish(
        self,
        customer_id: int,
        persona_id: str,
        event: dict[str, Any],
    ) -> None:
        async with self._lock:
            subscribers = set(self._customers.get(customer_id, ()))
            subscribers.update(self._personas.get((customer_id, persona_id), ()))
        if subscribers:
            await asyncio.gather(
                *(subscriber(event) for subscriber in subscribers),
                return_exceptions=True,
            )


library_chat_broadcast = LibraryChatBroadcastRegistry()
