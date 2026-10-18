"""Deterministic tag extraction from stored document text."""

from __future__ import annotations

import re

from overgraph_ingest.doctags.catalog import (
    BILLING_MODEL,
    CONFIDENTIALITY,
    EMPLOYMENT_TYPE,
    FIXED_PRICE,
    FIXED_TERM,
    HOURLY,
    NON_COMPETE,
    NON_COMPETE_VALUE,
    NOTICE_PERIOD,
    NINE_MONTHS,
    ONE_MONTH,
    PERMANENT,
    PROBATIONARY,
    REMOTE,
    SECRECY,
    SIX_MONTHS,
    STOCKHOLM,
    THIRTY_DAYS,
    TIME_AND_MATERIALS,
    TWO_WEEKS,
    WORK_LOCATION,
    value_label,
)
from overgraph_ingest.doctags.schema import ORIGIN_STRUCTURE
from overgraph_ingest.doctags.source import TagSource, validate_source
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.jev_io import SENTENCE_RE

Proposal = dict[str, object]


def extract_a(
    *,
    relative_path: str,
    document_id: str,
    units: list[StoredUnit],
) -> list[Proposal]:
    proposals = []
    for unit in units:
        text = unit.text
        low = text.casefold()
        for tag_class, value, needle in _hits(text, low):
            source = validate_source(
                _excerpt(text, needle),
                unit=unit,
                document_id=document_id,
            )
            proposals.append(
                _proposal(
                    relative_path,
                    document_id,
                    tag_class,
                    value,
                    source,
                    method="structure",
                )
            )
    return _unique(proposals)


def _hits(text: str, low: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    if "provanställ" in low:
        rows.append((EMPLOYMENT_TYPE, PROBATIONARY, "provanställ"))
    if "tillsvidareanställ" in low:
        rows.append((EMPLOYMENT_TYPE, PERMANENT, "tillsvidareanställ"))
    elif "gäller tills vidare" in low:
        rows.append((EMPLOYMENT_TYPE, PERMANENT, "gäller tills vidare"))
    if "visstidsanställ" in low:
        rows.append((EMPLOYMENT_TYPE, FIXED_TERM, "visstidsanställ"))
    elif "särskild visstids" in low:
        rows.append((EMPLOYMENT_TYPE, FIXED_TERM, "särskild visstids"))
    if "timanställ" in low:
        rows.append((EMPLOYMENT_TYPE, HOURLY, "timanställ"))
    elif "behovsanställ" in low:
        rows.append((EMPLOYMENT_TYPE, HOURLY, "behovsanställ"))
    if "två veckors" in low:
        rows.append((NOTICE_PERIOD, TWO_WEEKS, "två veckors"))
    if re.search(r"30.?\s*dagars uppsägningstid", low):
        rows.append((NOTICE_PERIOD, THIRTY_DAYS, "dagars uppsägningstid"))
    if "nio (9)" in low and "månader" in low:
        rows.append((NOTICE_PERIOD, NINE_MONTHS, "nio (9)"))
    elif "sex (6) månader" in low and "uppsägning" in low:
        rows.append((NOTICE_PERIOD, SIX_MONTHS, "sex (6) månader"))
    elif re.search(r"en \(1\) månad", low) and "uppsägning" in low:
        rows.append((NOTICE_PERIOD, ONE_MONTH, "en (1) månad"))
    if "tystnadsplikt" in low:
        rows.append((CONFIDENTIALITY, SECRECY, "tystnadsplikt"))
    elif "konfidentiell information" in low:
        rows.append((CONFIDENTIALITY, SECRECY, "konfidentiell information"))
    elif "konfidentiella handlingar" in low:
        rows.append((CONFIDENTIALITY, SECRECY, "konfidentiella handlingar"))
    elif "följa sekretess" in low:
        rows.append((CONFIDENTIALITY, SECRECY, "följa sekretess"))
    elif "hålla" in low and "hemlig" in low:
        rows.append((CONFIDENTIALITY, SECRECY, "hemlig"))
    if "konkurrensförbud" in low and "separat avtal" not in low:
        rows.append((NON_COMPETE, NON_COMPETE_VALUE, "konkurrensförbud"))
    elif "verksamhet som konkurrerar" in low:
        rows.append((NON_COMPETE, NON_COMPETE_VALUE, "verksamhet som konkurrerar"))
    if "löpande räkning" in low:
        rows.append((BILLING_MODEL, TIME_AND_MATERIALS, "löpande räkning"))
    if "fast pris" in low and "[" not in text:
        rows.append((BILLING_MODEL, FIXED_PRICE, "fast pris"))
    if "per timme" in low:
        rows.append((BILLING_MODEL, HOURLY, "per timme"))
    elif "timpris" in low:
        rows.append((BILLING_MODEL, HOURLY, "timpris"))
    if "arbeta på distans" in low:
        rows.append((WORK_LOCATION, REMOTE, "arbeta på distans"))
    elif "distansarbetsplats" in low:
        rows.append((WORK_LOCATION, REMOTE, "distansarbetsplats"))
    if "placeringsort är stockholm" in low:
        rows.append((WORK_LOCATION, STOCKHOLM, "placeringsort är stockholm"))
    return rows


def _excerpt(text: str, needle: str) -> str:
    for part in SENTENCE_RE.split(text):
        if needle.casefold() in part.casefold():
            return part.strip()[:240]
    index = text.casefold().find(needle.casefold())
    if index >= 0:
        start = max(0, index - 40)
        return text[start : index + len(needle) + 80].strip()[:240]
    return text.strip()[:240]


def _proposal(
    relative_path: str,
    document_id: str,
    tag_class: str,
    value: str,
    source: TagSource,
    *,
    method: str,
    model: str = "",
    confidence: float | None = None,
    probabilities: dict[str, object] | None = None,
) -> Proposal:
    return {
        "relative_path": relative_path,
        "document_id": document_id,
        "tag_class": tag_class,
        "value": value,
        "display_value": value_label(tag_class, value),
        "origin": ORIGIN_STRUCTURE if method == "structure" else "jev",
        "method": method,
        "model": model,
        "confidence": confidence,
        "probabilities": probabilities,
        "source": {
            "unit_id": source.unit_id,
            "excerpt": source.excerpt,
            "start": source.start,
            "end": source.end,
            "validated": source.validated,
        },
    }


def _unique(rows: list[Proposal]) -> list[Proposal]:
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for row in rows:
        key = (str(row["relative_path"]), str(row["tag_class"]), str(row["value"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique
