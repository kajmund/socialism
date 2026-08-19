"""Parse Spinndoktor [[ref:id]] markers from assistant replies."""

from __future__ import annotations

import re

REF_PATTERN = re.compile(r"\[\[ref:([a-z0-9_-]+)\]\]", re.IGNORECASE)


def strip_spindoctor_refs(text: str) -> str:
    return REF_PATTERN.sub("", text).strip()


def last_spindoctor_ref(text: str) -> str | None:
    matches = list(REF_PATTERN.finditer(text))
    if not matches:
        return None
    return matches[-1].group(1)
