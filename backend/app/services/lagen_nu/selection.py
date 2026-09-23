"""Structured hit/excerpt selection for lagen.nu. No MCP and no LLM here."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.services.research.models import ResearchContext, ResearchNeed, ResearchSourceType

LagenNuSelectorFactory = Callable[[], "LagenNuPassageSelector"]
_selector_factory: LagenNuSelectorFactory | None = None

MAX_SELECTOR_DOCUMENT_CHARS = 24000

HitRole = Literal[
    "potentially_relevant",
    "named_citation",
    "travaux",
    "ratio",
    "peripheral",
    "wrong_number",
    "wrong_subject",
]
HIT_ROLES: frozenset[str] = frozenset(
    {
        "potentially_relevant",
        "named_citation",
        "travaux",
        "ratio",
        "peripheral",
        "wrong_number",
        "wrong_subject",
    }
)


class LagenNuSelectionError(Exception):
    """Selector missing, invalid, or returned a span outside the document."""


@dataclass(frozen=True)
class SelectableHit:
    candidate_id: str
    uri: str
    title: str | None
    identifier: str | None
    highlight: str
    pinpoint: str | None


@dataclass(frozen=True)
class SelectableDocument:
    uri: str
    title: str | None
    identifier: str | None
    pinpoint: str | None
    text: str
    highlight: str
    truncated: bool


@dataclass(frozen=True)
class HitDecision:
    candidate_id: str
    keep: bool
    role: HitRole
    pinpoint: str | None = None
    excerpt_query: str = ""
    why: str = ""


@dataclass(frozen=True)
class ExcerptDecision:
    excerpt: str
    pinpoint: str | None = None
    why: str = ""


class LagenNuPassageSelector(Protocol):
    async def select_hits(
        self,
        *,
        need: ResearchNeed,
        source_type: ResearchSourceType,
        candidates: Sequence[SelectableHit],
        context: ResearchContext,
    ) -> list[HitDecision]: ...

    async def select_excerpt(
        self,
        *,
        need: ResearchNeed,
        source_type: ResearchSourceType,
        document: SelectableDocument,
        context: ResearchContext,
    ) -> ExcerptDecision: ...


def clip_selector_document(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= MAX_SELECTOR_DOCUMENT_CHARS:
        return stripped
    return stripped[:MAX_SELECTOR_DOCUMENT_CHARS]


def verify_excerpt_span(
    document_text: str,
    excerpt: str,
    *,
    max_chars: int,
    allowed_extra: str = "",
) -> str:
    text = excerpt.strip()
    if not text:
        raise LagenNuSelectionError("selector returned an empty excerpt")
    haystacks = [document_text, allowed_extra]
    if any(
        candidate and (text in candidate or _compact(text) in _compact(candidate))
        for candidate in haystacks
    ):
        return text[:max_chars]
    raise LagenNuSelectionError(
        "selector excerpt is not a span of the retrieved document"
    )


def set_passage_selector_factory(
    factory: LagenNuSelectorFactory | None,
) -> None:
    global _selector_factory
    _selector_factory = factory


def resolve_passage_selector(
    injected: LagenNuPassageSelector | None,
) -> LagenNuPassageSelector:
    if injected is not None:
        return injected
    if _selector_factory is not None:
        return _selector_factory()
    raise LagenNuSelectionError("lagen.nu passage selector is required")


def apply_hit_decisions(
    candidates: Sequence[SelectableHit],
    decisions: Sequence[HitDecision],
) -> list[HitDecision]:
    expected = {item.candidate_id for item in candidates}
    chosen: dict[str, HitDecision] = {}
    for item in decisions:
        if item.candidate_id not in expected:
            continue
        chosen[item.candidate_id] = item
    applied: list[HitDecision] = []
    for candidate in candidates:
        decision = chosen.get(candidate.candidate_id)
        if decision is None:
            applied.append(
                HitDecision(
                    candidate_id=candidate.candidate_id,
                    keep=False,
                    role="peripheral",
                    why="omitted_by_selector",
                )
            )
            continue
        applied.append(decision)
    return applied


def require_hit_decisions(
    candidates: Sequence[SelectableHit],
    decisions: Sequence[HitDecision],
) -> list[HitDecision]:
    return apply_hit_decisions(candidates, decisions)


def _compact(value: str) -> str:
    return " ".join(value.split())
