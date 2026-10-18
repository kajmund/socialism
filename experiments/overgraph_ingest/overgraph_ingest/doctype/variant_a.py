"""Deterministic document type from title, opening, headings, and stored metadata."""

from __future__ import annotations

import re
import unicodedata

from overgraph_ingest.doctype.taxonomy import (
    CONSULTING,
    DPA,
    EMPLOYMENT,
    LEASE,
    NDA,
    OTHER,
    SUPPLY,
    TERMINATION,
)
from overgraph_ingest.doctype.view import DocumentView

NDA_RE = re.compile(r"\bnda\b")


def classify_a(view: DocumentView) -> str:
    title = _fold(f"{view.relative_path} {view.title}")
    opening = _fold(view.opening)
    headings = _fold(" ".join(view.headings))
    allow_lease = not _has_any(title, ("kontorshotell", "coworking"))
    for blob in (title, opening, headings):
        matched = _match(blob, allow_lease=allow_lease)
        if matched is not None:
            return matched
    return OTHER


def _match(blob: str, *, allow_lease: bool) -> str | None:
    if _has_any(blob, (
        "uppsagningsbesked",
        "avgangsvederlag",
        "overenskommelse om avslut",
        "avslut av anstallning",
        "anstallningens upphorande",
    )):
        return TERMINATION
    if _has_any(blob, (
        "personuppgiftsbitraedesavtal",
        "databehandlingsavtal",
        "pub-avtal",
        "pub_avtal",
        "pub avtal",
    )):
        return DPA
    if "sekretessavtal" in blob or NDA_RE.search(blob):
        return NDA
    if _has_any(blob, (
        "anstallningsavtal",
        "tillsvidareanstallning",
        "provanstallning",
        "visstidsanstallning",
        "timanstallning",
        "behovsanstallning",
    )):
        return EMPLOYMENT
    if allow_lease and _has_any(blob, (
        "hyresavtal",
        "arrendeavtal",
        "leasingavtal",
        "parkeringsavtal",
        "andrahandsuthyrning",
    )):
        return LEASE
    if "styrelseledamot" not in blob and _has_any(blob, (
        "konsultavtal",
        "redovisningsuppdrag",
        "byraavtal",
        "uppdragsavtal",
    )):
        return CONSULTING
    if _has_any(blob, (
        "leveransavtal",
        "inkopsavtal",
        "ramavtal",
        "saas",
        "hostingavtal",
        "it-drift",
        "support- och underhall",
        "mjukvaruutvecklingsavtal",
        "fastighetsservice",
        "projektavtal",
        "appavtal",
    )):
        return SUPPLY
    return None


def _has_any(blob: str, needles: tuple[str, ...]) -> bool:
    return any(needle in blob for needle in needles)


def _fold(text: str) -> str:
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return stripped.replace("_", " ")
