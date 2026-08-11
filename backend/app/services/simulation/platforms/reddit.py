"""Reddit path with custom Platform + scenario clock."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.oasis_clock import OasisScenarioClock
from app.services.oasis_profiles import (
    OasisAgentProfile,
    write_reddit_profile_json,
)
from app.services.simulation.platforms.base import PlatformDriver, PlatformSetup


class RedditPlatformDriver(PlatformDriver):
    name = "reddit"

    def write_profiles(
        self,
        profiles: list[OasisAgentProfile],
        art: Path,
    ) -> tuple[Path, str | None, str | None]:
        profile_path = write_reddit_profile_json(profiles, art / "profiles.json")
        return profile_path, None, str(profile_path)

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
        from oasis import generate_reddit_agent_graph
        from oasis.environment.env import OasisEnv
        from oasis.social_platform.channel import Channel
        from oasis.social_platform.platform import Platform

        profile_path, profile_csv, profile_json = self.write_profiles(profiles, art)
        agent_graph = await generate_reddit_agent_graph(
            profile_path=str(profile_path),
            model=model,
            available_actions=available_actions,
        )
        channel = Channel()
        clock = OasisScenarioClock(sim_start)
        sim_start_dt = datetime.combine(sim_start, datetime.min.time())
        platform = Platform(
            db_path=str(db_path),
            channel=channel,
            sandbox_clock=clock,
            start_time=sim_start_dt,
            recsys_type="reddit",
            allow_self_rating=True,
            show_score=True,
            max_rec_post_len=100,
            refresh_rec_post_count=5,
        )
        env = OasisEnv(
            agent_graph=agent_graph,
            platform=platform,
            database_path=str(db_path),
        )
        scenario_clock = (
            env.platform.sandbox_clock
            if isinstance(env.platform.sandbox_clock, OasisScenarioClock)
            else None
        )
        return PlatformSetup(
            env=env,
            agent_graph=agent_graph,
            scenario_clock=scenario_clock,
            profile_path=profile_path,
            profile_csv=profile_csv,
            profile_json=profile_json,
        )
