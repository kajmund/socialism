"""Asterisk footnotes and per-section definitions for snabbrapport HTML."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from html import escape

from app.services.report.locale import ReportLocale

_CURRENT: contextvars.ContextVar[FootnoteTracker | None] = contextvars.ContextVar(
    "quick_footnote_tracker",
    default=None,
)


@dataclass(frozen=True)
class GlossaryEntry:
    id: str
    term_sv: str
    term_en: str
    body_sv: str
    body_en: str


# Short operator-facing explanations only — no formulas, no implementation jargon.
ENTRIES: tuple[GlossaryEntry, ...] = (
    GlossaryEntry(
        id="likes-injection",
        term_sv="Likes på testbudskap",
        term_en="Likes on test message",
        body_sv="Likes på partipostens inlägg i simuleringen.",
        body_en="Likes on the party account's injected post in the simulation.",
    ),
    GlossaryEntry(
        id="engagement-score",
        term_sv="Engagemangspoäng",
        term_en="Engagement score",
        body_sv="Sammansatt mått på hur mycket aktivitet simuleringen gav.",
        body_en="Combined measure of how much activity the simulation produced.",
    ),
    GlossaryEntry(
        id="segment-score",
        term_sv="Segmentpoäng",
        term_en="Segment score",
        body_sv="Aktivitetsmått för målgruppen — räknas annorlunda än tabellen ovan.",
        body_en="Activity measure for the target group — counted differently from the table above.",
    ),
    GlossaryEntry(
        id="ab-relative",
        term_sv="Relativa staplar",
        term_en="Relative bars",
        body_sv="Stapelns längd jämför armarna inom samma mått — inte statistisk signifikans.",
        body_en="Bar length compares arms within each metric — not statistical significance.",
    ),
)

_ENTRY_BY_ID: dict[str, GlossaryEntry] = {entry.id: entry for entry in ENTRIES}


class FootnoteTracker:
    """Collects asterisk markers and renders definitions for one report section."""

    def __init__(self, locale: ReportLocale) -> None:
        self.locale = locale
        self._used: list[str] = []

    def mark(self, entry_id: str) -> str:
        entry = _ENTRY_BY_ID.get(entry_id)
        if entry is None:
            return ""
        if entry_id not in self._used:
            self._used.append(entry_id)
        stars = "*" * (self._used.index(entry_id) + 1)
        return f'<span class="fn">{stars}</span>'

    def render_block(self) -> str:
        if not self._used:
            return ""
        items: list[str] = []
        for idx, entry_id in enumerate(self._used):
            entry = _ENTRY_BY_ID[entry_id]
            term = entry.term_en if self.locale == "en" else entry.term_sv
            body = entry.body_en if self.locale == "en" else entry.body_sv
            stars = "*" * (idx + 1)
            items.append(
                f'<p class="fn-item">'
                f'<span class="fn-mark">{stars}</span> '
                f"<strong>{escape(term)}</strong> — "
                f"<span>{escape(body)}</span></p>"
            )
        return f'<div class="fn-block">{"".join(items)}</div>'


class FootnoteContext:
    """Activate a section-local footnote tracker for nested render helpers."""

    def __init__(self, locale: ReportLocale) -> None:
        self.tracker = FootnoteTracker(locale)
        self._token: contextvars.Token[FootnoteTracker | None] | None = None

    def __enter__(self) -> FootnoteTracker:
        self._token = _CURRENT.set(self.tracker)
        return self.tracker

    def __exit__(self, *_exc: object) -> None:
        if self._token is not None:
            _CURRENT.reset(self._token)


def footnote(entry_id: str) -> str:
    """Inline asterisk marker using the active section tracker."""
    tracker = _CURRENT.get()
    if tracker is None:
        return ""
    return tracker.mark(entry_id)
