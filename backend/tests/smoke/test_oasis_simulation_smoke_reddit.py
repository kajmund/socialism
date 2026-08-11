"""Manual live OASIS Reddit smoke — run with ``pytest -m smoke``.

Same fixture as Twitter smoke but uses Reddit platform driver (custom Platform
+ scenario clock). Requires ``uv sync --extra oasis`` and ``DEEPSEEK_API_KEY``.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.oasis_run import simulate_run

from tests.smoke.helpers import seed_smoke_run

pytestmark = [pytest.mark.smoke]


async def test_oasis_simulation_smoke_reddit(
    smoke_oasis_extra,
    smoke_deepseek_key: str,
    smoke_session,
) -> None:
    settings.deepseek_api_key = smoke_deepseek_key
    settings.simulation_engine = "oasis"
    settings.apply_oasis_env()

    async with smoke_session() as session:
        run = await seed_smoke_run(session, platform="reddit")
        results = await simulate_run(session, run)

    attempt = results["attempts"][0]
    assert attempt["engine"] == "oasis"
    assert attempt["error"] is None

    variant = attempt["variants"][0]
    assert variant["error"] is None
    assert variant["ticks_run"] == 2
    assert variant["agent_count"] == 6
    assert len(variant["posts"]) >= 1
    assert len(variant["trace"]) > 0
    assert variant["profile_json"]
    assert variant["profile_csv"] is None
