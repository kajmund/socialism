"""Owner routing by catalog kind and tenant.

One logical Owner per active catalog. Process placement is external; this registry
only holds the verified client/endpoint for each catalog.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.services.overgraph.owner import OwnerClient, OwnerProtocolError, OwnerUnavailable


@dataclass(frozen=True)
class OwnerRoute:
    kind: str
    socket_path: Path
    customer_id: int | None = None

    def key(self) -> tuple[str, int | None]:
        return (self.kind, self.customer_id)


class OwnerRegistry:
    def __init__(self) -> None:
        self._clients: dict[tuple[str, int | None], OwnerClient] = {}

    async def connect(self, routes: list[OwnerRoute]) -> dict[str, object]:
        connected: dict[str, object] = {}
        for route in routes:
            client = OwnerClient(route.socket_path)
            await client.health()
            self._clients[route.key()] = client
            connected[f"{route.kind}:{route.customer_id or 'shared'}"] = str(route.socket_path)
        return connected

    def client_for(self, kind: str, *, customer_id: int | None = None) -> OwnerClient:
        client = self._clients.get((kind, customer_id))
        if client is None:
            raise OwnerUnavailable(
                f"no owner for kind={kind!r} customer_id={customer_id!r}"
            )
        return client

    async def close(self) -> None:
        self._clients.clear()

    async def health(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for (kind, customer_id), client in self._clients.items():
            try:
                await client.health()
                result[f"{kind}:{customer_id or 'shared'}"] = True
            except (OwnerUnavailable, OwnerProtocolError):
                result[f"{kind}:{customer_id or 'shared'}"] = False
        return result


_registry = OwnerRegistry()


def get_owner_registry() -> OwnerRegistry:
    return _registry


async def connect_owner_registry(routes: list[OwnerRoute]) -> dict[str, object]:
    return await _registry.connect(routes)


async def close_owner_registry() -> None:
    await asyncio.to_thread(_registry.close)
