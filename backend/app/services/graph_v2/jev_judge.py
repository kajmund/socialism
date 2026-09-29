"""Semantic fact judge. Structural candidate guards run before this model call."""

import json

from app.config import settings
from app.jev.system import HttpJevSystemOne, JevSystemOne
from app.services.graph_v2.types import Decision, FactInput


class JevFactJudge:
    def __init__(self, prompt: str, client: JevSystemOne | None = None) -> None:
        self.question = json.loads(prompt)
        self.client = client or HttpJevSystemOne()

    async def compare(self, proposed: FactInput, candidate_text: str) -> Decision:
        result = await self.client.ask(
            state={"proposed_fact": proposed.fact_text, "existing_fact": candidate_text},
            questions={"relation": self.question},
            model=settings.jev_model,
            timeout_seconds=settings.jev_timeout_seconds,
        )
        answer = result.answers.get("relation")
        choice = answer.get("choice") if isinstance(answer, dict) else None
        if choice not in {"SAME", "DISTINCT", "CONTRADICTS"}:
            raise ValueError("semantic fact judge returned an invalid decision")
        return choice
