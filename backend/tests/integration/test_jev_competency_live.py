"""Live check: Jev ranks domain competence for one consult question.

Opt-in. Default pytest skips it, including CI.

    RUN_JEV_INTEGRATION=1 uv run pytest tests/integration/test_jev_competency_live.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import settings
from app.services.consult_competence import rank_consult_competence

pytestmark = pytest.mark.integration

_ENV_FLAG = "RUN_JEV_INTEGRATION"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_QUESTION = (
    "Vilka svårigheter uppstår vid bedömning av kultur, IT och "
    "operativa integrationer vid ett företagsförvärv?"
)


def _opted_in() -> bool:
    return os.environ.get(_ENV_FLAG) == "1"


def _dotenv_values() -> dict[str, str]:
    path = _BACKEND_ROOT / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _live_api_key(env_file: dict[str, str]) -> str:
    current = settings.typesafe_api_key.strip()
    if current:
        return current
    return env_file.get("TYPESAFE_API_KEY", "").strip()


async def test_jev_ranks_integration_competence_above_criminal_law() -> None:
    if not _opted_in():
        pytest.skip(f"set {_ENV_FLAG}=1 to call Jev for a competence ranking")
    env_file = _dotenv_values()
    api_key = _live_api_key(env_file)
    if not api_key:
        pytest.skip("TYPESAFE_API_KEY is missing")
    previous = settings.typesafe_api_key
    settings.typesafe_api_key = api_key
    try:
        scores = await rank_consult_competence(
            question=_QUESTION,
            experts=(
                (
                    "integration",
                    "Integrationsriskbedömare. Bedömer kultur, IT och "
                    "operativa integrationer vid företagsförvärv. "
                    "Yrkesbakgrund: integrationsledare i förvärv.",
                ),
                (
                    "straffratt",
                    "Straffrättsjurist. Försvarar klienter i brottmål. "
                    "Yrkesbakgrund: advokat med inriktning på straffrätt.",
                ),
            ),
        )
    finally:
        settings.typesafe_api_key = previous

    integration = scores["integration"]
    criminal = scores["straffratt"]
    assert integration >= 0.5
    assert criminal < 0.5
    assert integration > criminal
