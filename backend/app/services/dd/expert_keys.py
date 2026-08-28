"""Shared slug helpers for DD expert role / persona keys."""

from __future__ import annotations

import re

_EXPERT_KEY_RE = re.compile(r"[^a-z0-9]+")


def expert_role_key(label: str) -> str:
    slug = _EXPERT_KEY_RE.sub("_", label.strip().casefold()).strip("_")
    return slug or "expert"
