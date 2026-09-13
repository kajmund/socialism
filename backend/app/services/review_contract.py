"""Review session output contract: language lock, moderator role, ownership.

Runtime prompt text lives in ``review.output_contract``. Code owns labels,
ownership sanitizing, and how the rendered contract is attached.
"""

from __future__ import annotations

import re
from typing import Literal

from app.services.prompt_catalog import default_prompts, render_prompt

OUTPUT_CONTRACT_KEY = "review.output_contract"
OutputLocale = Literal["sv", "en", "nb"]

MODERATOR_LABEL = "Moderator"

_MODERATOR_ALIASES = frozenset(
    {
        "moderator",
        "moderator (jag)",
        "moderator (i)",
        "moderator (jeg)",
        "the moderator",
    }
)
_MODERATOR_PAREN_RE = re.compile(r"^moderator\s*\([^)]*\)\s*$", re.IGNORECASE)
_MODERATOR_OWNER_PREFIX_RE = re.compile(
    r"^(?P<owner>Moderator(?:\s*\((?:Jag|jag|I|Jeg|jeg)\))?)\s+"
    r"(?P<verb>bör|ska|kan|måste|should|must|will|can|bør|må)\b",
    re.IGNORECASE,
)


def normalize_output_locale(value: str | None) -> OutputLocale:
    raw = (value or "").strip().casefold()
    if raw in {"en", "nb", "sv"}:
        return raw  # type: ignore[return-value]
    raise ValueError(f"unsupported review locale: {value!r}")


def render_output_contract(prompts: dict[str, str]) -> str:
    return render_prompt(prompts, OUTPUT_CONTRACT_KEY)


def output_contract_for_locale(locale: str) -> str:
    """Load the catalog default for an explicit locale. Does not remap nb→sv."""
    return render_output_contract(default_prompts(normalize_output_locale(locale)))


def compose_review_system_context(
    *,
    prompts: dict[str, str],
    actor_context: str = "",
) -> str:
    contract = render_output_contract(prompts)
    extra = (actor_context or "").strip()
    if not extra:
        return contract
    return f"{contract}\n\n{extra}"


def messages_with_output_contract(
    messages: list[dict[str, str]],
    prompts: dict[str, str],
) -> list[dict[str, str]]:
    """Insert the rendered output contract as an early system message."""
    contract = render_output_contract(prompts)
    if any(item.get("role") == "system" and item.get("content") == contract for item in messages):
        return list(messages)
    inserted = [{"role": "system", "content": contract}]
    inserted.extend(messages)
    return inserted


def is_moderator_label(value: str) -> bool:
    folded = (value or "").strip().casefold()
    if not folded:
        return False
    if folded in _MODERATOR_ALIASES:
        return True
    return bool(_MODERATOR_PAREN_RE.match(folded))


def display_speaker_label(speaker: str) -> str:
    if is_moderator_label(speaker):
        return MODERATOR_LABEL
    return speaker


def real_world_action_owner(
    claimed: str,
    actor: object | None,
) -> str:
    """Moderator must not own real-world next steps."""
    text = (claimed or "").strip()
    if not is_moderator_label(text):
        return text
    if actor is not None and bool(getattr(actor, "perspective_known", False)):
        role = str(getattr(actor, "user_role", "") or "").strip()
        if role and not is_moderator_label(role):
            return role
    return ""


def sanitize_recommended_action_owner(
    text: str,
    actor: object | None,
) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _MODERATOR_OWNER_PREFIX_RE.match(raw)
    if match is None:
        return raw
    owner = real_world_action_owner(match.group("owner"), actor)
    rest = raw[match.end() :].strip()
    verb = match.group("verb")
    if owner:
        return f"{owner} {verb} {rest}".strip()
    return f"{verb} {rest}".strip()
