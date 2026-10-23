"""Scripted Jev for offline golden cases. Not a live model and not a fallback."""

from __future__ import annotations


from app.jev.system import JevSystemOneResult, JevUsage
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.fast_controller import ASSESSMENT_QUESTIONS
from app.services.research.sufficiency_experiment.pair_eval import (
    PAIR_CONFLICT_QUESTIONS,
)
from app.services.research.sufficiency_experiment.golden import (
    CONTRADICTION_SIGNAL,
    SUPPORT_PHRASE,
)

_HIGH = 0.95
_LOW = 0.05

# Fixture-only score overrides keyed by evidence id. The scripted judge cannot
# express high redundancy or a compatible pair otherwise. Not model quality.
SCRIPTED_SCORE_OVERRIDES: dict[str, dict[str, float]] = {
    "dup-contra": {"likely_duplicate_or_redundant": 0.89},
    "period-old": {
        "relevant_to_question": _HIGH,
        "directly_supports_answer": _HIGH,
    },
    "period-new": {
        "relevant_to_question": _HIGH,
        "contradicts_current_evidence": _HIGH,
    },
    "entity-a": {
        "relevant_to_question": _HIGH,
        "directly_supports_answer": _HIGH,
    },
    "entity-b": {
        "relevant_to_question": _HIGH,
        "contradicts_current_evidence": _HIGH,
    },
}


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
        if set(questions) == set(PAIR_CONFLICT_QUESTIONS):
            answers = _pair_answers(state)
        elif set(EVIDENCE_SCREEN_QUESTIONS).issubset(questions):
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


def _pair_answers(state: object) -> dict[str, object]:
    payload = state if isinstance(state, dict) else {}
    left = payload.get("left") or {}
    right = payload.get("right") or {}
    texts = (
        f"{left.get('claim', '')} {right.get('claim', '')}".lower()
    )
    if "motbevis" in texts and "tillämpar" in texts:
        choice = "CONTRADICTS"
    elif "uppsägningstid" in texts:
        choice = "SCOPE_DIFFERENCE"
    else:
        choice = "COMPATIBLE"
    return {"relation": {"choice": choice}}


def _screen_answers(state: object) -> dict[str, object]:
    passage = ""
    evidence_id = ""
    if isinstance(state, dict):
        passage = str(state.get("passage") or "")
        evidence_id = str(state.get("evidence_id") or "")
    support = SUPPORT_PHRASE in passage
    contradict = CONTRADICTION_SIGNAL in passage
    relevant = support or contradict
    answers: dict[str, object] = {
        "relevant_to_question": _noul(relevant),
        "directly_supports_answer": _noul(support),
        "contradicts_current_evidence": _noul(contradict),
        "material_new_information": _noul(relevant),
        "likely_duplicate_or_redundant": _noul(False),
        "primary_or_high_authority_for_question": _noul(support),
    }
    for key, value in SCRIPTED_SCORE_OVERRIDES.get(evidence_id, {}).items():
        answers[key] = {"noul": value}
    return answers


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
