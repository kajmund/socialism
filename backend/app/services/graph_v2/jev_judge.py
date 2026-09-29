"""Semantic fact judge. Structural candidate guards run before this model call."""

import json

from app.config import settings
from app.jev.system import HttpJevSystemOne, JevSystemOne
from app.services.graph_v2.errors import JevMalformedResponseError
from app.services.graph_v2.types import Decision, FactInput, NodeInput


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
            raise JevMalformedResponseError("semantic fact judge returned an invalid decision")
        return choice


class JevNodeJudge:
    def __init__(self, prompt: str, client: JevSystemOne | None = None) -> None:
        self.question = json.loads(prompt)
        self.client = client or HttpJevSystemOne()

    async def same_node(self, proposed: NodeInput, candidate_name: str) -> bool:
        result = await self.client.ask(
            state={"proposed_value": proposed.name, "existing_value": candidate_name,
                   "value_type": proposed.node_type},
            questions={"relation": self.question},
            model=settings.jev_model,
            timeout_seconds=settings.jev_timeout_seconds,
        )
        answer = result.answers.get("relation")
        choice = answer.get("choice") if isinstance(answer, dict) else None
        if choice not in {"SAME", "DISTINCT"}:
            raise JevMalformedResponseError("semantic node judge returned an invalid decision")
        return choice == "SAME"
