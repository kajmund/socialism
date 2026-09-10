"""JA/NEJ raise-hand parsing shared by generic_panel and structured_scoring."""

from __future__ import annotations

import re

_RAISE_YES = frozenset({"JA", "YES"})
_RAISE_NO = frozenset({"NEJ", "NO"})
_RAISE_TOKEN = re.compile(r"[A-Za-zÅÄÖåäö]+")

# If a JA reply still disclaims competence, it is a NEJ.
_COMPETENCE_DISCLAIMERS = (
    "utanför mitt kompetensområde",
    "utanför mitt kompetens",
    "faller utanför",
    "inte mitt mandat",
    "inte min kompetens",
    "saknar kompetens",
    "allmän orientering",
    "allman orientering",
    "inte jurist inom",
    "avstår i sakfrågan",
    "avstar i sakfragan",
    "outside my competence",
    "outside my area",
    "not my mandate",
    "not my brief",
    "general orientation",
    "i lack competence",
    "i abstain on the substance",
)


def parse_raise_hand_reply(raw: str) -> tuple[bool, str]:
    """First token JA/YES vs NEJ/NO; keep the rest as the competence reason."""
    text = raw.strip()
    if not text:
        return False, "NEJ"
    first_line = text.split("\n", 1)[0]
    token_match = _RAISE_TOKEN.search(first_line)
    token = token_match.group(0).upper() if token_match else ""
    if token in _RAISE_YES:
        return True, text
    if token in _RAISE_NO:
        return False, text
    return False, text


def has_competence_disclaimer(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _COMPETENCE_DISCLAIMERS)


def raise_hand_is_yes(raw: str) -> bool:
    """True only for a competence-backed JA/YES, not a helpful aside."""
    wants, visible = parse_raise_hand_reply(raw)
    if not wants:
        return False
    return not has_competence_disclaimer(visible)
