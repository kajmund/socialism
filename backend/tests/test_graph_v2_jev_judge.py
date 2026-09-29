"""The configured graph decision is validated before it can affect knowledge."""

import json
from types import SimpleNamespace

import pytest

from app.services.graph_v2.jev_judge import JevFactJudge
from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.graph_v2.prompts import graph_fact_prompt_fields


class FakeJev:
    def __init__(self, choice):
        self.choice = choice
        self.calls = []

    async def ask(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(answers={"relation": {"choice": self.choice}})


@pytest.mark.parametrize("choice", ["SAME", "DISTINCT", "CONTRADICTS"])
async def test_fact_decision_comes_from_seeded_question(choice):
    prompt = graph_fact_prompt_fields()[0]["defaults"]["sv"]
    client = FakeJev(choice)
    judge = JevFactJudge(prompt, client)
    proposed = FactInput(
        source_id="a", target_id="b", scope=customer_scope(1),
        predicate="core.relates_to", fact_text="A gäller B",
        sources=(SourceRef("episode", "episode-1"),),
    )
    assert await judge.compare(proposed, "A omfattar B") == choice
    assert client.calls[0]["questions"]["relation"] == json.loads(prompt)


async def test_invalid_model_decision_cannot_be_stored():
    judge = JevFactJudge(graph_fact_prompt_fields()[0]["defaults"]["en"], FakeJev("MAYBE"))
    with pytest.raises(ValueError, match="invalid decision"):
        await judge.compare(FactInput(
            source_id="a", target_id="b", scope=customer_scope(1),
            predicate="core.relates_to", fact_text="A gäller B",
            sources=(SourceRef("episode", "episode-1"),),
        ), "B")
