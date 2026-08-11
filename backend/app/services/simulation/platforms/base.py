"""Shared types for platform drivers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.services.oasis_clock import OasisScenarioClock
from app.services.oasis_profiles import OasisAgentProfile


@dataclass(frozen=True)
class PlatformSetup:
    env: Any
    agent_graph: Any
    scenario_clock: OasisScenarioClock | None
    profile_path: Path
    profile_csv: str | None
    profile_json: str | None


class PlatformDriver:
    """Build profiles, agent graph, and OasisEnv for one OASIS platform."""

    name: str

    def write_profiles(
        self,
        profiles: list[OasisAgentProfile],
        art: Path,
    ) -> tuple[Path, str | None, str | None]:
        """Write agent profiles under art/; return path and optional csv/json rel paths."""

    async def setup(
        self,
        *,
        profiles: list[OasisAgentProfile],
        art: Path,
        db_path: Path,
        model: Any,
        available_actions: list[Any],
        sim_start: date,
    ) -> PlatformSetup:
        """Write profiles and construct agent graph + OasisEnv."""
