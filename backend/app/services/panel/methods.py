"""Registry of complete deliberation methods. Jobs dispatch by name, not if/elif."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.services.panel.engine import run_generic_panel
from app.services.panel.structured_scoring import run_structured_scoring

PanelMethod = Callable[
    [AsyncSession, PanelSession, dict[str, str]], Awaitable[PanelSession]
]

DELIBERATION_METHODS: dict[str, PanelMethod] = {
    "generic_panel": run_generic_panel,
    "structured_scoring": run_structured_scoring,
}

PROTOCOL_METHODS: dict[str, str] = {
    "generic_panel": "generic_panel",
    "dd_panel": "structured_scoring",
}


def deliberation_method(name: str) -> PanelMethod:
    method = DELIBERATION_METHODS.get(name)
    if method is None:
        raise RuntimeError(f"Unknown deliberation method: {name}")
    return method
