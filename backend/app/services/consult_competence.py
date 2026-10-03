"""Jev domain-competence ranking for one expert consult.

One System One request scores every profile. The colleague reply stays on the chat model.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.config import settings
from app.jev.system import HttpJevSystemOne, JevSystemOne, parse_noul

COMPETENCE_NOUL_THRESHOLD = 0.5

_COMPETENCE = {
    "type": "noul",
    "instructions": (
        "Does this expert's stated role give actual domain competence for a "
        "substantial expert assessment of this exact question?"
    ),
    "criteria": {
        "true": (
            "The stated role covers this exact question as core competence. "
            "Analogies, general orientation, a method perspective, recommending "
            "another expert, or available source material are not competence."
        ),
        "false": (
            "The stated role does not cover this question. A strong profile "
            "in a neighbouring field is still not competence."
        ),
    },
}


async def rank_consult_competence(
    *,
    question: str,
    experts: Sequence[tuple[str, str]],
    jev: JevSystemOne | None = None,
) -> dict[str, float]:
    """Return a noul per expert id. Callers compare against COMPETENCE_NOUL_THRESHOLD."""
    if not experts:
        return {}
    client = jev or HttpJevSystemOne()
    result = await client.ask(
        state={
            "question": question,
            "experts": [
                {"id": expert_id, "profile": profile} for expert_id, profile in experts
            ],
        },
        questions={
            expert_id: {
                **_COMPETENCE,
                "instructions": f"{_COMPETENCE['instructions']} Expert {expert_id}.",
            }
            for expert_id, _profile in experts
        },
        model=settings.jev_model,
        timeout_seconds=settings.jev_timeout_seconds,
    )
    return {
        expert_id: parse_noul(result.answers, expert_id) for expert_id, _profile in experts
    }
