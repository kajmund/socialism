"""Lagen.nu MCP client protocol. Mock vs live is an explicit settings switch."""

from __future__ import annotations

from typing import Protocol

from app.config import settings
from app.services.rattsunderlag.schemas import ForarbeteRef, LagtextRef, PraxisRef


class LagenNuError(RuntimeError):
    pass


class LagenNuNotFoundError(LagenNuError):
    pass


class LagenNuClient(Protocol):
    async def search_law(self, query: str) -> list[LagtextRef]: ...

    async def get_sfs(self, sfs_id: str) -> LagtextRef: ...

    async def search_case_law(self, query: str) -> list[PraxisRef]: ...

    async def get_forarbete(self, referens: str) -> ForarbeteRef: ...


def build_lagen_nu_client() -> LagenNuClient:
    """Empty URL → mock. Set URL → live MCP, fail loud if unreachable."""
    url = settings.lagen_nu_mcp_url.strip()
    if not url:
        from app.services.rattsunderlag.lagen_nu_mock import MockLagenNuClient

        return MockLagenNuClient()
    from app.services.rattsunderlag.lagen_nu_live import LiveLagenNuClient

    return LiveLagenNuClient(url=url)
