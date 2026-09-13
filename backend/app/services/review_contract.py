"""Review session output contract: language lock, moderator role, ownership.

Code-owned. These rules are not customer-editable prompt text.
"""

from __future__ import annotations

import re
from typing import Literal

OutputLocale = Literal["sv", "en", "nb"]

MODERATOR_LABEL = "Moderator"

_MODERATOR_ALIASES = frozenset(
    {
        "moderator",
        "moderator (jag)",
        "moderator (i)",
        "the moderator",
    }
)
_MODERATOR_PAREN_RE = re.compile(r"^moderator\s*\([^)]*\)\s*$", re.IGNORECASE)
_MODERATOR_OWNER_PREFIX_RE = re.compile(
    r"^(?P<owner>Moderator(?:\s*\((?:Jag|jag|I)\))?)\s+"
    r"(?P<verb>bör|ska|kan|måste|should|must|will|can)\b",
    re.IGNORECASE,
)


def normalize_output_locale(value: str | None) -> OutputLocale:
    raw = (value or "").strip().casefold()
    if raw == "en":
        return "en"
    if raw == "nb":
        return "nb"
    return "sv"


def output_language_instruction(locale: str) -> str:
    """Hard language lock for user-visible LLM prose."""
    loc = normalize_output_locale(locale)
    if loc == "en":
        return (
            "Hard output-language contract: write all user-visible prose in English. "
            "This includes moderator questions, research-need and research-plan text, "
            "expert answers, comments, rewrite suggestions, and the final report. "
            "Do not switch to Swedish or any other language mid-review. "
            "Technical identifiers and source-type enums stay machine-readable."
        )
    return (
        "Hårt utdataspråkskontrakt: skriv all användarsynlig prosa på svenska. "
        "Det gäller moderatorfrågor, researchbehov och researchplan, "
        "expertsvar, kommentarer, omskrivningsförslag och slutrapport. "
        "Byt inte till engelska eller något annat språk under granskningen. "
        "Tekniska identifierare och källtyps-enum ska förbli maskinläsbara."
    )


def moderator_role_instruction(locale: str) -> str:
    loc = normalize_output_locale(locale)
    if loc == "en":
        return (
            "User-visible role label is Moderator — never Moderator (I) or Moderator (Jag). "
            "You may write from the requested party perspective; first person such as "
            "we/our is valid when that is the reviewer's side. "
            "Narrative perspective must not turn the AI moderator into a real-world actor. "
            "You may summarize and recommend actions but must not own actions such as "
            "contacting the counterparty, sending proposals, or negotiating. "
            "For real-world next-step ownership, use the ActorContext party when it is "
            "clear; otherwise leave ownership unassigned. Never assign ownership to Moderator."
        )
    return (
        "Den synliga rollbeteckningen är Moderator — aldrig Moderator (Jag) eller Moderator (I). "
        "Du får skriva ur den begärda partsställningen; vi/vår är giltigt när det är "
        "granskarens sida. "
        "Berättarperspektivet får inte göra AI-moderatorn till en verklig aktör. "
        "Du får sammanfatta och rekommendera åtgärder men inte äga åtgärder som att "
        "kontakta motparten, skicka förslag eller förhandla. "
        "Verkligt ägarskap för nästa steg ska vara aktören från aktörskontexten när den "
        "är tydlig; annars lämna ägarskapet oassignerat. Tilldela aldrig Moderator ägarskap."
    )


def review_output_contract(locale: str) -> str:
    return f"{output_language_instruction(locale)}\n\n{moderator_role_instruction(locale)}"


def compose_review_system_context(
    *,
    locale: str,
    actor_context: str = "",
) -> str:
    contract = review_output_contract(locale)
    extra = (actor_context or "").strip()
    if not extra:
        return contract
    return f"{contract}\n\n{extra}"


def messages_with_output_contract(
    messages: list[dict[str, str]],
    locale: str,
) -> list[dict[str, str]]:
    """Insert the output contract as an early system message."""
    contract = review_output_contract(locale)
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
