"""Scripted Jev for offline golden cases. Not a live model and not a fallback."""

from __future__ import annotations


from app.jev.system import JevSystemOneResult, JevUsage
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.fast_controller import ASSESSMENT_QUESTIONS
from app.services.research.sufficiency_experiment.golden import (
    CONTRADICTION_SIGNAL,
    SUPPORT_PHRASE,
)

_HIGH = 0.95
_LOW = 0.05


class ScriptedSufficiencyJev:
    """Closed NOUL judge used by CI. Scores are not model quality."""

    model = "scripted-jev"

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, object],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        if set(EVIDENCE_SCREEN_QUESTIONS).issubset(questions):
            answers = _screen_answers(state)
        elif set(ASSESSMENT_QUESTIONS).issubset(questions):
            answers = _route_answers(state)
        else:
            raise ValueError("scripted Jev expected evidence-screen or assessment NOUL")
        passage = ""
        if isinstance(state, dict):
            passage = str(state.get("passage") or "")
        return JevSystemOneResult(
            answers=answers,
            model=self.model,
            latency_ms=0.0,
            input_chars=len(passage),
            usage=JevUsage(),
            raw={"answers": answers},
        )


def _noul(flag: bool) -> dict[str, float]:
    return {"noul": _HIGH if flag else _LOW}


def _screen_answers(state: object) -> dict[str, object]:
    passage = ""
    if isinstance(state, dict):
        passage = str(state.get("passage") or "")
    support = SUPPORT_PHRASE in passage
    contradict = CONTRADICTION_SIGNAL in passage
    relevant = support or contradict
    return {
        "relevant_to_question": _noul(relevant),
        "directly_supports_answer": _noul(support),
        "contradicts_current_evidence": _noul(contradict),
        "material_new_information": _noul(relevant),
        "likely_duplicate_or_redundant": _noul(False),
        "primary_or_high_authority_for_question": _noul(support),
    }


def _route_answers(state: object) -> dict[str, object]:
    payload = state if isinstance(state, dict) else {}
    verified = bool(payload.get("obligations_verified"))
    unknown = bool(payload.get("unknown_requirements"))
    unresolved = bool(payload.get("unresolved_conflicts"))
    if unknown or unresolved:
        return {
            "answerable_now": _noul(False),
            "material_gap": _noul(unknown),
            "contradiction": _noul(unresolved),
            "follow_up_change": _noul(True),
            "additional_source": _noul(unknown),
        }
    return {
        "answerable_now": _noul(verified),
        "material_gap": _noul(not verified),
        "contradiction": _noul(False),
        "follow_up_change": _noul(not verified),
        "additional_source": _noul(not verified),
    }
