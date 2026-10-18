"""Structured workspace intent locked before expert tool execution.

IntentDecision is a logical contract shared by find_documents, continuation
routing, and client presentation. It is derived from the user message and the
active workspace state without an extra model call.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.schemas.workspace import WorkspaceState
from app.services.document_find.taxonomy import type_from_user_phrase

Operation = Literal["replace", "filter", "within", "extend"]
Presentation = Literal["gallery", "none", "uncertain"]
Scope = Literal["catalog", "active_document_set"]

_COUNT = re.compile(
    r"(hur många|antalet|räkna|svara bara hur många|visa inget galleri)",
    re.IGNORECASE,
)
_ANALYZE = re.compile(
    r"(analysera|analys|underlag för en senare analys|visa dem inte nu)",
    re.IGNORECASE,
)
_GALLERY = re.compile(
    r"(visa dem som ett galleri|dokumentgalleri|presentera träffarna|"
    r"visa de hittade dokumenten|jag vill se dokumentmängden|"
    r"öppna resultatet|visa .*galleri|som ett galleri)",
    re.IGNORECASE,
)
_SHOW = re.compile(
    r"\b(visa|öppna|presentera)\b",
    re.IGNORECASE,
)
_AMBIGUOUS = re.compile(
    r"(vad har vi|vilka .+ har vi|har vi egentligen|för sådana dokument)",
    re.IGNORECASE,
)
_FILTER = re.compile(
    r"(filtrera|visa bara|bara dem|inom den aktuella dokumentmängden till)",
    re.IGNORECASE,
)
_WITHIN = re.compile(
    r"(sök inom|inom den aktuella dokumentmängden efter|undersök .+ inom)",
    re.IGNORECASE,
)
_EXTEND = re.compile(
    r"(lägg till|utöka|inklusive)",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"\b("
    r"filtrera|sök|inom|den|aktuella|dokumentmängden|efter|till|lägg|till|"
    r"hitta|ta|fram|sök|fram|identifiera|hämta|visa|dem|som|ett|galleri|"
    r"öppna|resultatet|dokumentgalleri|jag|vill|se|presentera|träffarna|i|"
    r"de|hittade|dokumenten|tillsammans|alla|bara|svara|svar|bara|hur|många|"
    r"det|är|och|inget|detta|är|underlag|för|en|senare|analys|visa|"
    r"dem|inte|nu|vad|har|vi|för|sådana|dokument"
    r")\b|[.?!,;:]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentDecision:
    operation: Operation
    presentation: Presentation
    scope: Scope
    query: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def allows_gallery(self) -> bool:
        return self.presentation == "gallery"


def decide_workspace_intent(
    message: str,
    workspace_state: WorkspaceState | dict[str, Any] | None,
) -> IntentDecision:
    text = (message or "").strip()
    has_set = _has_active_document_set(workspace_state)
    operation = _operation(text, has_set=has_set)
    presentation = _presentation(text)
    scope: Scope = (
        "active_document_set"
        if operation in {"filter", "within", "extend"} and has_set
        else "catalog"
    )
    return IntentDecision(
        operation=operation,
        presentation=presentation,
        scope=scope,
        query=_query(text),
    )


def apply_intent_to_find_arguments(
    arguments: dict[str, Any],
    intent: IntentDecision | None,
) -> dict[str, Any]:
    """Force find_documents mode and, when the message names a type, the query.

    filter and within share the same search scope (active set) but keep
    distinct operations so callers can treat selection mutation differently.
    Query is taken from the user message when it names a document type so a
    channel model cannot rewrite a Swedish type label into an English phrase
    that misses the taxonomy. A message without a type label (for example the
    context-dependent follow-up "Filtrera ner dokumenten", whose
    filler-stripped remainder is just "ner") is not a search phrase; the
    model's own query is kept for those turns.
    """
    if intent is None:
        return dict(arguments)
    payload = dict(arguments)
    payload["mode"] = intent.operation
    if intent.query and type_from_user_phrase(intent.query) is not None:
        payload["query"] = intent.query
    return payload


def presentation_tools_allowed(intent: IntentDecision | None) -> bool:
    return intent is None or intent.allows_gallery


def filter_specs_for_intent(
    specs: list[dict[str, Any]],
    intent: IntentDecision | None,
) -> list[dict[str, Any]]:
    if presentation_tools_allowed(intent):
        return list(specs)
    blocked = {"show_document", "show_document_set"}
    return [
        spec
        for spec in specs
        if str(spec.get("function", {}).get("name") or "") not in blocked
    ]


def _presentation(text: str) -> Presentation:
    if _COUNT.search(text):
        return "none"
    if _ANALYZE.search(text) and not _GALLERY.search(text):
        return "none"
    if _GALLERY.search(text):
        return "gallery"
    if _AMBIGUOUS.search(text) and not _SHOW.search(text):
        return "uncertain"
    if _SHOW.search(text):
        return "gallery"
    return "uncertain"


def _operation(text: str, *, has_set: bool) -> Operation:
    # within before filter: gold "Sök inom ... efter" also mentions aktuella.
    if _WITHIN.search(text):
        return "within"
    if _FILTER.search(text):
        return "filter"
    if _EXTEND.search(text):
        return "extend"
    return "replace"


def _query(text: str) -> str:
    cleaned = _FILLER.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or text.strip()


def _has_active_document_set(
    workspace_state: WorkspaceState | dict[str, Any] | None,
) -> bool:
    if workspace_state is None:
        return False
    payload = (
        workspace_state.model_dump()
        if isinstance(workspace_state, WorkspaceState)
        else workspace_state
    )
    active = payload.get("active_document_set_id")
    if not active:
        return False
    for row in payload.get("document_sets") or []:
        if not isinstance(row, dict):
            continue
        if row.get("id") == active and row.get("source_ids"):
            return True
    return False
