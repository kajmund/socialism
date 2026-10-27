"""Safe, bounded failure reasons for persisted research diagnostics."""

from __future__ import annotations

_SAFE_FAILURE_TYPES = (
    "ResearchAssessmentError", "ResearchCompletenessError", "FollowUpPlannerError",
    "ResearchPlannerError", "StructuredOutputError", "TimeoutError", "ResearchExecutionError",
)
_SAFE_FAILURE_CODES = ("context_length_exceeded", "output_length_exceeded", "timeout", "model_call_failed")


def safe_failure_reason(exc: BaseException) -> str:
    """Exception type plus a safe category; never provider payloads or secrets."""
    message = str(exc)
    name = next((item for item in _SAFE_FAILURE_TYPES if item in message), type(exc).__name__)
    code = next((item for item in _SAFE_FAILURE_CODES if item in message), None)
    return f"{name}:{code}" if code else name
