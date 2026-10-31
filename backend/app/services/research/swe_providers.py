"""Built-in SWE decision providers.

`jev` wraps the existing System One research surface: the rendered prompt becomes
the Jev state, the fixed research assessment Noul questions decide
sufficient / insufficient / uncertain, and `classify_research_decision` maps the
answer to the declared choice. No fallback: a disabled Jev, a schema-invalid
answer or a choice outside the workflow's declared choices fails the run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.config import settings
from app.jev.system import HttpJevSystemOne, JevClientError, JevSystemOne, noul_confidence, parse_noul
from app.services.research.fast_controller import (
    ASSESSMENT_QUESTIONS,
    classify_research_decision,
    research_jev_available,
    research_jev_model,
)

JEV_PROVIDER_NAME = "jev"


def make_jev_provider(*, client: JevSystemOne | None = None) -> Any:
    """Return an async provider callable plus its cache params."""
    system = client or HttpJevSystemOne()

    async def jev_provider(request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not research_jev_available():
            raise JevClientError(
                "Jev provider requires research_jev_enabled and TYPESAFE_API_KEY",
                category="auth",
            )
        choices = tuple(str(choice) for choice in request["choices"])
        result = await system.ask(
            state={"prompt": request["prompt"]},
            questions=ASSESSMENT_QUESTIONS,
            model=research_jev_model(),
            timeout_seconds=settings.research_jev_timeout_seconds,
        )
        answerable = parse_noul(result.answers, "answerable_now")
        gap = parse_noul(result.answers, "material_gap")
        contradiction = parse_noul(result.answers, "contradiction")
        follow_up = parse_noul(result.answers, "follow_up_change")
        additional = parse_noul(result.answers, "additional_source")
        confidence = min(
            noul_confidence(value)
            for value in (answerable, gap, contradiction, follow_up, additional)
        )
        choice = classify_research_decision(
            answerable_now=answerable,
            material_gap=gap,
            contradiction=contradiction,
            follow_up_change=follow_up,
            additional_source=additional,
            confidence=confidence,
            sufficient_threshold=settings.research_jev_sufficient_threshold,
            incomplete_threshold=settings.research_jev_incomplete_threshold,
            confidence_threshold=settings.research_jev_confidence_threshold,
        )
        if choice not in choices:
            raise JevClientError(
                f"Jev decided {choice!r}, which is not a declared choice",
                category="invalid_response",
            )
        return {
            "choice": choice,
            "provider": JEV_PROVIDER_NAME,
            "model": result.model,
            "confidence": confidence,
            "latency_ms": result.latency_ms,
        }

    jev_provider.cache_params = {
        "provider": JEV_PROVIDER_NAME,
        "model": research_jev_model(),
    }
    return jev_provider
