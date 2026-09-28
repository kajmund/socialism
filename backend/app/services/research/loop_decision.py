"""Pure stop/continue decisions for the research loop. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.execution.models import ResearchStopReason
from app.services.research.assessment import ASSESSMENT_RESULTS, AssessmentResult
from app.services.research.completeness import COMPLETENESS_RESULTS, CompletenessResult

LoopAction = Literal["stop", "review_completeness", "plan_global", "plan_follow_up"]


@dataclass(frozen=True)
class LoopDecision:
    action: LoopAction
    stop_reason: ResearchStopReason | None = None

    def __post_init__(self) -> None:
        if self.action == "stop":
            if self.stop_reason is None:
                raise ValueError("stop requires stop_reason")
            return
        if self.stop_reason is not None:
            raise ValueError("stop_reason is only valid for stop")

    def require_stop_reason(self) -> ResearchStopReason:
        if self.stop_reason is None:
            raise ValueError("stop_reason is required")
        return self.stop_reason


def decide_after_assessment(
    *,
    assessment_result: AssessmentResult,
    existing_completeness_passes: int,
    latest_completeness_result: CompletenessResult | None,
    max_completeness_passes: int,
    wave: int,
    max_follow_up_waves: int,
) -> LoopDecision:
    """Choose the next loop step after local sufficiency is persisted."""
    if assessment_result not in ASSESSMENT_RESULTS:
        raise ValueError(f"Unknown assessment result: {assessment_result}")
    if assessment_result == "sufficient":
        if existing_completeness_passes >= max_completeness_passes:
            if latest_completeness_result is None:
                raise ValueError(
                    "latest_completeness_result is required when existing "
                    "completeness passes meet the cap"
                )
            if latest_completeness_result not in COMPLETENESS_RESULTS:
                raise ValueError(f"Unknown completeness result: {latest_completeness_result}")
            if latest_completeness_result == "complete":
                return LoopDecision(action="stop", stop_reason="sufficient")
            return LoopDecision(action="stop", stop_reason="max_completeness_passes")
        return LoopDecision(action="review_completeness")
    if wave >= max_follow_up_waves:
        return LoopDecision(action="stop", stop_reason="max_iterations")
    return LoopDecision(action="plan_follow_up")


def decide_after_completeness(
    *,
    completeness_result: CompletenessResult,
    completeness_pass: int,
    max_completeness_passes: int,
    wave: int,
    max_follow_up_waves: int,
) -> LoopDecision:
    """Choose the next loop step after a global completeness review."""
    if completeness_result not in COMPLETENESS_RESULTS:
        raise ValueError(f"Unknown completeness result: {completeness_result}")
    if completeness_result == "complete":
        return LoopDecision(action="stop", stop_reason="sufficient")
    if completeness_pass >= max_completeness_passes:
        return LoopDecision(action="stop", stop_reason="max_completeness_passes")
    if wave >= max_follow_up_waves:
        return LoopDecision(action="stop", stop_reason="max_iterations")
    return LoopDecision(action="plan_global")
