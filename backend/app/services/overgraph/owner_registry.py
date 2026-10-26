"""Owner routing by catalog kind and tenant.

One logical Owner per active catalog. Process placement is external; this registry
only holds the verified client/endpoint for each catalog.
"""

from __future__ import annotations

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


def parse_tenant_owner_sockets(raw: str) -> list[OwnerRoute]:
    """Parse ``customer_id=socket`` entries into tenant Knowledge Owner routes.

    Empty config means no tenant owner is configured; using one then fails
    explicitly instead of silently opening a local catalog.
    """
    routes: list[OwnerRoute] = []
    seen: set[int] = set()
    for entry in raw.split(","):
        item = entry.strip()
        if not item:
            continue
        customer, separator, socket = item.partition("=")
        if not separator or not customer.strip() or not socket.strip():
            raise ValueError(f"invalid tenant owner route: {item!r}")
        try:
            customer_id = int(customer.strip())
        except ValueError as exc:
            raise ValueError(f"invalid tenant customer id: {customer!r}") from exc
        if customer_id < 1:
            raise ValueError(f"tenant customer id must be positive: {customer_id}")
        if customer_id in seen:
            raise ValueError(f"duplicate tenant owner route for customer {customer_id}")
        seen.add(customer_id)
        routes.append(OwnerRoute(
            kind="tenant_knowledge",
            socket_path=Path(socket.strip()),
            customer_id=customer_id,
        ))
    return routes


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
    await _registry.close()


def tenant_owner_client(customer_id: int) -> OwnerClient:
    """Route one verified tenant to its Knowledge Owner, or fail explicitly."""
    return _registry.client_for("tenant_knowledge", customer_id=customer_id)
