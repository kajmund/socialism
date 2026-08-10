"""OKF manual corpus access for in-app help chat."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from app.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from integrations.okf.corpus import Guide, format_context, load_guides, search_guides

__all__ = ["Guide", "format_context", "get_guides", "search_manual"]


@lru_cache(maxsize=1)
def get_guides() -> tuple[Guide, ...]:
    root = settings.okf_manual_path
    return tuple(load_guides(root))


def search_manual(query: str, *, limit: int = 4) -> list[Guide]:
    return search_guides(list(get_guides()), query, limit=limit)


def manual_context(query: str, *, limit: int = 4) -> str:
    return format_context(search_manual(query, limit=limit))
