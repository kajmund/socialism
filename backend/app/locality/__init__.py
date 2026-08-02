"""Norrköping pilot locality brief for grounded persona prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_BRIEF_PATH = Path(__file__).with_name("norrkoping.md")


@lru_cache(maxsize=1)
def load_norrkoping_brief() -> str:
    return _BRIEF_PATH.read_text(encoding="utf-8")
