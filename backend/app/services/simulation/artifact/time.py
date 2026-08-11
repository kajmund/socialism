"""Normalize OASIS created_at values for sorting."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def created_at_to_sort_key(value: Any) -> int | None:
    """Normalize OASIS created_at (timestep int or ISO datetime) to a sortable int."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if "-" not in text and "T" not in text and ":" not in text:
        try:
            return int(float(text))
        except ValueError:
            return None
    try:
        # OASIS often stores "YYYY-MM-DD HH:MM:SS.ffffff"
        normalized = text.replace(" ", "T", 1)
        dt = datetime.fromisoformat(normalized)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None
