"""Report locale: Swedish/English copy helpers for snabbrapport."""

from __future__ import annotations

from typing import Literal

from app.services.ssr.anchors import TONE_LABELS_EN, TONE_LABELS_SV

ReportLocale = Literal["sv", "en"]

DEFAULT_LOCALE: ReportLocale = "sv"


def normalize_locale(value: str | None) -> ReportLocale:
    if value == "en":
        return "en"
    return "sv"


def download_filename(locale: ReportLocale) -> str:
    return "report.html" if locale == "en" else "rapport.html"


def default_report_title(
    *,
    locale: ReportLocale,
    ab_source: bool,
    source_label: str,
    n_sources: int,
) -> str:
    if locale == "en":
        if ab_source:
            return f"A/B report — {source_label}"
        unit = "run" if n_sources == 1 else "runs"
        return f"Report ({n_sources} {unit})"
    if ab_source:
        return f"A/B-rapport — {source_label}"
    return f"Rapport ({n_sources} körning{'ar' if n_sources != 1 else ''})"


def other_topic_label(locale: ReportLocale) -> str:
    return "Other" if locale == "en" else "Övrigt"


def tone_labels(locale: ReportLocale) -> tuple[str, ...]:
    """Five-level SSR tone scale (Semantic Similarity Rating)."""
    return TONE_LABELS_EN if locale == "en" else TONE_LABELS_SV


# Internal style keys stay Swedish (SSR anchor labels); display may be English.
_STYLE_LABEL_EN: dict[str, str] = {
    "Sarkastisk + konkret kritik": "Sarcastic + concrete criticism",
    "Uppgiven + vardagsmetafor": "Resigned + everyday metaphor",
    "Fakta + yrkesauktoritet": "Facts + professional authority",
    "Personlig + hjärtlig berättelse": "Personal + warm story",
    "Optimistisk / lösningsfokuserad": "Optimistic / solution-focused",
    "Provocerande / konfronterande": "Provocative / confrontational",
    "Oklassad": "Unclassified",
}


def display_style_label(label: str, locale: ReportLocale) -> str:
    if locale == "en":
        return _STYLE_LABEL_EN.get(label, label)
    return label
