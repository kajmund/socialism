"""Mock only remote decisions; exercise the actual result reader and traversal."""

from unittest.mock import AsyncMock

from sqlalchemy import text

from app.jev.system import JevSystemOneResult, JevUsage
from app.services.graph_v2.result_prompts import result_reuse_prompt_fields
from tests.research_reuse.helpers import MAIN


def reuse_prompts():
    return {field["key"]: field["defaults"]["sv"] for field in result_reuse_prompt_fields()}


def mock_result_jev(monkeypatch, factory, *, outcome="FULL", confidence=0.99):
    async def ask(*, state, questions, model, timeout_seconds):
        async with factory() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
        if "coverage" in questions:
            decision = outcome if state["saved_question"] == MAIN else "PARTIAL"
            answers = {"coverage": {"choice": decision, "confidence": confidence}}
        else:
            answers = {key: {"noul": 0.9} for key in questions}
        return JevSystemOneResult(answers, model, 1.0, len(str(state)), JevUsage(), {})

    client = AsyncMock(side_effect=ask)
    monkeypatch.setattr("app.jev.system.HttpJevSystemOne.ask", client)
    monkeypatch.setattr(
        "app.services.research.result_search.require_active_prompts",
        AsyncMock(return_value=reuse_prompts()),
    )
    return client
