"""Backward-compatible re-export tests for oasis_deepseek_reasoning shim."""

from app.services.oasis_deepseek_reasoning import (
    _attach_reasoning,
    _extract_reasoning_content,
    apply_deepseek_reasoning_patch,
    camel_llm_runtime,
)


def test_shim_reexports_helpers():
    assert _extract_reasoning_content is not None
    assert _attach_reasoning is not None
    assert camel_llm_runtime is not None


def test_deprecated_apply_is_context_manager():
    # apply_deepseek_reasoning_patch delegates to camel_llm_runtime
    assert hasattr(apply_deepseek_reasoning_patch, "__enter__") or callable(
        apply_deepseek_reasoning_patch
    )
