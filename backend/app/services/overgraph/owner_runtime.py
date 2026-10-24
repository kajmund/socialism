"""Backend lifecycle binding for the external Overgraph owner."""

from __future__ import annotations

from pathlib import Path

from app.services.overgraph.owner import OwnerClient, OwnerProtocolError, OwnerUnavailable


class OwnerRuntime:
    def __init__(self) -> None:
        self.client: OwnerClient | None = None
        self.status: dict[str, object] = {"status": "disabled", "write_paths_ready": False}

    async def connect(self, socket_path: str, *, catalog_id: str | None = None) -> None:
        if not socket_path.strip():
            self.status = {"status": "disabled", "write_paths_ready": False}
            return
        client = OwnerClient(Path(socket_path), catalog_id=catalog_id or None)
        try:
            health = await client.health()
        except (OwnerUnavailable, OwnerProtocolError) as exc:
            self.client = None
            self.status = {
                "status": "unavailable",
                "error": type(exc).__name__,
                "write_paths_ready": False,
            }
            return
        self.client = client
        self.status = {
            "status": "ready",
            "catalog_id": health.get("catalog_id"),
            "write_paths_ready": False,
        }

    async def close(self) -> None:
        self.client = None
        self.status = {"status": "closed", "write_paths_ready": False}

    def require_client(self) -> OwnerClient:
        if self.client is None:
            raise OwnerUnavailable("Overgraph owner is not ready")
        return self.client


_runtime = OwnerRuntime()


def get_owner_runtime() -> OwnerRuntime:
    return _runtime
