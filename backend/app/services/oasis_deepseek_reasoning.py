"""Backward-compatible re-exports for DeepSeek reasoning helpers.

Runtime patching lives in app.services.simulation.llm_runtime.camel_llm_runtime.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Generator

from app.services.simulation.llm_runtime import (
    _attach_reasoning,
    _extract_reasoning_content,
    camel_llm_runtime,
)


@contextmanager
def apply_deepseek_reasoning_patch() -> Generator[None, None, None]:
    """Deprecated: use camel_llm_runtime() instead."""
    with camel_llm_runtime():
        yield
