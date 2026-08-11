"""Manual live OASIS smoke test — run with ``pytest -m smoke``.

Requires ``uv sync --extra oasis`` and a real ``DEEPSEEK_API_KEY``. Default
``uv run pytest`` excludes smoke tests (see pyproject ``addopts``).
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.oasis_run import simulate_run

from tests.smoke.helpers import seed_smoke_run

pytestmark = [pytest.mark.smoke]


async def test_oasis_simulation_smoke(
    smoke_oasis_extra,
    smoke_deepseek_key: str,
    smoke_session,
) -> None:
    settings.deepseek_api_key = smoke_deepseek_key
    settings.simulation_engine = "oasis"
    settings.apply_oasis_env()

    async with smoke_session() as session:
        run = await seed_smoke_run(session)
        results = await simulate_run(session, run)

    attempt = results["attempts"][0]
    assert attempt["engine"] == "oasis"
    assert attempt["id"]
    assert attempt["error"] is None

    variants = attempt["variants"]
    assert len(variants) == 1
    variant = variants[0]
    assert variant["error"] is None
    assert variant["ticks_run"] == 2
    assert variant["agent_count"] == 6  # 5 population + 1 injector
    assert variant["configured_ticks"] == 2
    assert len(variant["posts"]) >= 1
    assert len(variant["trace"]) > 0
    assert len(variant["action_histogram"]) > 0
    assert variant["tick_markers"]
    assert len(variant["tick_markers"]) == 2
