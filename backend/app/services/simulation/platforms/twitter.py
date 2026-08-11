"""Stock Twitter path via oasis.make."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from app.services.oasis_profiles import (
    OasisAgentProfile,
    write_twitter_profile_csv,
)
from app.services.simulation.platforms.base import PlatformDriver, PlatformSetup


class TwitterPlatformDriver(PlatformDriver):
    name = "twitter"

    def write_profiles(
        self,
        profiles: list[OasisAgentProfile],
        art: Path,
    ) -> tuple[Path, str | None, str | None]:
        profile_path = write_twitter_profile_csv(profiles, art / "profiles.csv")
        return profile_path, str(profile_path), None

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
        import oasis
        from oasis import generate_twitter_agent_graph

        profile_path, profile_csv, profile_json = self.write_profiles(profiles, art)
        agent_graph = await generate_twitter_agent_graph(
            profile_path=str(profile_path),
            model=model,
            available_actions=available_actions,
        )
        env = oasis.make(
            agent_graph=agent_graph,
            platform=oasis.DefaultPlatformType.TWITTER,
            database_path=str(db_path),
        )
        return PlatformSetup(
            env=env,
            agent_graph=agent_graph,
            scenario_clock=None,
            profile_path=profile_path,
            profile_csv=profile_csv,
            profile_json=profile_json,
        )
