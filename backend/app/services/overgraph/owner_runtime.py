"""Backend lifecycle binding for the external Overgraph owner.

The owner can start after a backend or restart while backends are running. The
client is therefore kept once a socket is configured: every request opens its
own connection, so an owner that appears later becomes usable without a backend
restart. Readiness is refreshed explicitly (health endpoint) and write calls
fail loudly while the owner is unreachable - there is no direct fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.overgraph.owner import OwnerClient, OwnerProtocolError, OwnerUnavailable


class OwnerRuntime:
    def __init__(self) -> None:
        self.client: OwnerClient | None = None
        self.status: dict[str, object] = {"status": "disabled", "write_paths_ready": False}

    async def connect(self, socket_path: str, *, catalog_id: str | None = None) -> None:
        if not socket_path.strip():
            self.client = None
            self.status = {"status": "disabled", "write_paths_ready": False}
            return
        self.client = OwnerClient(Path(socket_path), catalog_id=catalog_id or None)
        await self.refresh()

    async def refresh(self) -> dict[str, Any]:
        """Re-check the configured owner and update readiness.

        Never raises: readiness is reported in ``status`` and the next write
        attempt surfaces the concrete error.
        """
        if self.client is None:
            self.status = {"status": "disabled", "write_paths_ready": False}
            return dict(self.status)
        try:
            health = await self.client.health()
        except (OwnerUnavailable, OwnerProtocolError) as exc:
            self.status = {
                "status": "unavailable",
                "error": type(exc).__name__,
                "write_paths_ready": False,
            }
            return dict(self.status)
        self.status = {
            "status": "ready",
            "catalog_id": health.get("catalog_id"),
            "write_paths_ready": False,
        }
        return dict(self.status)

    async def close(self) -> None:
        self.client = None
        self.status = {"status": "closed", "write_paths_ready": False}

    def require_client(self) -> OwnerClient:
        if self.client is None:
            raise OwnerUnavailable("Overgraph owner is not configured")
        return self.client


_runtime = OwnerRuntime()


def get_owner_runtime() -> OwnerRuntime:
    return _runtime
