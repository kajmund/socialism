"""Scripted Jev for offline golden cases. Not a production fallback."""

from __future__ import annotations

from app.jev.system import JevSystemOneResult, JevUsage
from app.services.research.sufficiency_experiment.golden import (
    CONTRADICTION_SIGNAL,
    SUPPORT_PHRASE,
)


class ScriptedSufficiencyJev:
    """Closed judge used by CI and the default benchmark harness."""

    model = "scripted-jev"

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, object],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        if "verdict" not in questions:
            raise ValueError("scripted Jev expected a verdict question")
        passage = ""
        if isinstance(state, dict):
            passage = str(state.get("passage") or "")
        choice = _verdict(passage)
        return JevSystemOneResult(
            answers={"verdict": {"choice": choice}},
            model=self.model,
            latency_ms=0.0,
            input_chars=len(passage),
            usage=JevUsage(),
            raw={"answers": {"verdict": {"choice": choice}}},
        )


def _verdict(passage: str) -> str:
    if CONTRADICTION_SIGNAL in passage:
        return "CONTRADICTS"
    if SUPPORT_PHRASE in passage:
        return "SUPPORTED"
    return "UNSUPPORTED"
