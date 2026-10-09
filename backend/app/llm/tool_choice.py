"""Tool-choice overrides that a provider cannot express directly."""

from __future__ import annotations

from app.llm.runtime_override import LlmRuntimeView


def reasoning_effort_for_tool_choice(
    tool_choice: str,
    runtime: LlmRuntimeView,
) -> str | None:
    # DeepSeek thinking rejects forced tool_choice. The tools stay; thinking
    # turns off for this request so the model can still be required to call one.
    if (
        tool_choice != "auto"
        and runtime.provider == "deepseek"
        and runtime.reasoning_effort not in {None, "none"}
    ):
        return "none"
    return None
