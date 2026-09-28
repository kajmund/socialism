"""Unit tests for research-loop stop/continue decisions."""

from __future__ import annotations

import pytest

from app.services.research.assessment import ASSESSMENT_RESULTS
from app.services.research.completeness import COMPLETENESS_RESULTS
from app.services.research.loop_decision import (
    LoopDecision,
    decide_after_assessment,
    decide_after_completeness,
)

MAX_COMPLETENESS = 3
MAX_WAVES = 2
WAVE_VALUES = (1, 2, 3)
EXISTING_VALUES = (2, 3, 4)
PASS_VALUES = (2, 3, 4)


def test_loop_decision_stop_requires_reason():
    with pytest.raises(ValueError, match="stop requires stop_reason"):
        LoopDecision(action="stop")


def test_loop_decision_non_stop_rejects_reason():
    with pytest.raises(ValueError, match="only valid for stop"):
        LoopDecision(action="plan_follow_up", stop_reason="sufficient")


@pytest.mark.parametrize("assessment_result", ASSESSMENT_RESULTS)
@pytest.mark.parametrize("existing", EXISTING_VALUES)
@pytest.mark.parametrize("latest", (*COMPLETENESS_RESULTS, None))
@pytest.mark.parametrize("wave", WAVE_VALUES)
def test_decide_after_assessment_covers_every_combination(
    assessment_result: str,
    existing: int,
    latest: str | None,
    wave: int,
) -> None:
    kwargs = {
        "assessment_result": assessment_result,
        "existing_completeness_passes": existing,
        "latest_completeness_result": latest,
        "max_completeness_passes": MAX_COMPLETENESS,
        "wave": wave,
        "max_follow_up_waves": MAX_WAVES,
    }
    if assessment_result == "sufficient" and existing >= MAX_COMPLETENESS and latest is None:
        with pytest.raises(ValueError, match="latest_completeness_result"):
            decide_after_assessment(**kwargs)
        return

    decision = decide_after_assessment(**kwargs)
    if assessment_result == "sufficient":
        if existing >= MAX_COMPLETENESS:
            assert decision.action == "stop"
            assert decision.stop_reason == (
                "sufficient" if latest == "complete" else "max_completeness_passes"
            )
            return
        assert decision == LoopDecision(action="review_completeness")
        return
    if wave >= MAX_WAVES:
        assert decision == LoopDecision(action="stop", stop_reason="max_iterations")
        return
    assert decision == LoopDecision(action="plan_follow_up")


@pytest.mark.parametrize("completeness_result", COMPLETENESS_RESULTS)
@pytest.mark.parametrize("completeness_pass", PASS_VALUES)
@pytest.mark.parametrize("wave", WAVE_VALUES)
def test_decide_after_completeness_covers_every_combination(
    completeness_result: str,
    completeness_pass: int,
    wave: int,
) -> None:
    decision = decide_after_completeness(
        completeness_result=completeness_result,
        completeness_pass=completeness_pass,
        max_completeness_passes=MAX_COMPLETENESS,
        wave=wave,
        max_follow_up_waves=MAX_WAVES,
    )
    if completeness_result == "complete":
        assert decision == LoopDecision(action="stop", stop_reason="sufficient")
        return
    if completeness_pass >= MAX_COMPLETENESS:
        assert decision == LoopDecision(action="stop", stop_reason="max_completeness_passes")
        return
    if wave >= MAX_WAVES:
        assert decision == LoopDecision(action="stop", stop_reason="max_iterations")
        return
    assert decision == LoopDecision(action="plan_global")


def test_decide_after_assessment_rejects_unknown_result():
    with pytest.raises(ValueError, match="Unknown assessment result"):
        decide_after_assessment(
            assessment_result="maybe",  # type: ignore[arg-type]
            existing_completeness_passes=0,
            latest_completeness_result=None,
            max_completeness_passes=MAX_COMPLETENESS,
            wave=0,
            max_follow_up_waves=MAX_WAVES,
        )


def test_decide_after_completeness_rejects_unknown_result():
    with pytest.raises(ValueError, match="Unknown completeness result"):
        decide_after_completeness(
            completeness_result="maybe",  # type: ignore[arg-type]
            completeness_pass=1,
            max_completeness_passes=MAX_COMPLETENESS,
            wave=0,
            max_follow_up_waves=MAX_WAVES,
        )
