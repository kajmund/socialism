"""Configurable tag classes. Injected at runtime, not baked into a Jev prompt."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.doctags.schema import KIND_EXTRACTED, KIND_USER_LABEL
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

CATALOG_VERSION = "document-tags-v1"

EMPLOYMENT_TYPE = "employment_type"
NOTICE_PERIOD = "notice_period"
CONFIDENTIALITY = "confidentiality"
NON_COMPETE = "non_compete"
BILLING_MODEL = "billing_model"
WORK_LOCATION = "work_location"

PERMANENT = "permanent"
PROBATIONARY = "probationary"
FIXED_TERM = "fixed_term"
HOURLY = "hourly"
ONE_MONTH = "1_month"
TWO_WEEKS = "2_weeks"
SIX_MONTHS = "6_months"
NINE_MONTHS = "9_months"
THIRTY_DAYS = "30_days"
SECRECY = "secrecy_obligation"
NON_COMPETE_VALUE = "non_compete"
FIXED_PRICE = "fixed_price"
TIME_AND_MATERIALS = "time_and_materials"
REMOTE = "remote"
STOCKHOLM = "stockholm"


@dataclass(frozen=True)
class TagValue:
    value: str
    display_value: str
    criteria: str


@dataclass(frozen=True)
class TagClass:
    class_id: str
    label: str
    values: tuple[TagValue, ...]
    needles: tuple[str, ...]


TAG_CLASSES = {
    EMPLOYMENT_TYPE: TagClass(
        EMPLOYMENT_TYPE,
        "Anställningsform",
        (
            TagValue(PERMANENT, "Tillsvidare", "The document creates a permanent employment."),
            TagValue(PROBATIONARY, "Provanställning", "The document creates or starts a probationary employment."),
            TagValue(FIXED_TERM, "Visstid", "The document creates a fixed-term employment."),
            TagValue(HOURLY, "Timanställning", "The document is an on-call or hourly employment."),
        ),
        ("tillsvidare", "provanställ", "visstid", "timanställ", "behovsanställ"),
    ),
    NOTICE_PERIOD: TagClass(
        NOTICE_PERIOD,
        "Uppsägningstid",
        (
            TagValue(TWO_WEEKS, "14 dagar", "A two-week or 14-day notice period."),
            TagValue(THIRTY_DAYS, "30 dagar", "A 30-day notice period."),
            TagValue(ONE_MONTH, "1 månad", "A one-month notice period."),
            TagValue(SIX_MONTHS, "6 månader", "A six-month notice period."),
            TagValue(NINE_MONTHS, "9 månader", "A nine-month notice period."),
        ),
        ("uppsägningstid", "sägas upp", "varsels"),
    ),
    CONFIDENTIALITY: TagClass(
        CONFIDENTIALITY,
        "Sekretess",
        (
            TagValue(SECRECY, "Sekretessåtagande", "The document imposes a duty of secrecy."),
        ),
        ("sekretess", "tystnadsplikt", "konfidentiell"),
    ),
    NON_COMPETE: TagClass(
        NON_COMPETE,
        "Konkurrensförbud",
        (
            TagValue(NON_COMPETE_VALUE, "Konkurrensförbud", "The document imposes a non-compete."),
        ),
        ("konkurrensförbud", "konkurrerande"),
    ),
    BILLING_MODEL: TagClass(
        BILLING_MODEL,
        "Ersättningsmodell",
        (
            TagValue(HOURLY, "Timarvode", "Pay is an hourly fee."),
            TagValue(FIXED_PRICE, "Fast pris", "Pay is a fixed price."),
            TagValue(TIME_AND_MATERIALS, "Löpande räkning", "Pay is time and materials."),
        ),
        ("per timme", "timpris", "fast pris", "löpande räkning"),
    ),
    WORK_LOCATION: TagClass(
        WORK_LOCATION,
        "Arbetsplats",
        (
            TagValue(REMOTE, "Distans", "The principal workplace is remote work."),
            TagValue(STOCKHOLM, "Stockholm", "The principal workplace is Stockholm."),
        ),
        ("distans", "placeringsort"),
    ),
}

CLASSES_FOR_TYPE = {
    EMPLOYMENT: (EMPLOYMENT_TYPE, NOTICE_PERIOD, CONFIDENTIALITY, NON_COMPETE, WORK_LOCATION),
    CONSULTING: (BILLING_MODEL, NOTICE_PERIOD, CONFIDENTIALITY, NON_COMPETE),
    NDA: (CONFIDENTIALITY,),
    DPA: (CONFIDENTIALITY,),
    LEASE: (NOTICE_PERIOD,),
    SUPPLY: (BILLING_MODEL, CONFIDENTIALITY),
    TERMINATION: (NOTICE_PERIOD, CONFIDENTIALITY, NON_COMPETE),
    OTHER: (CONFIDENTIALITY, NON_COMPETE, BILLING_MODEL, WORK_LOCATION, NOTICE_PERIOD),
}

USER_LABEL = "user_label"


def classes_for_type(document_type: str) -> tuple[str, ...]:
    return CLASSES_FOR_TYPE.get(document_type, CLASSES_FOR_TYPE[OTHER])


def kind_for_class(tag_class: str) -> str:
    if tag_class in TAG_CLASSES:
        return KIND_EXTRACTED
    return KIND_USER_LABEL


def value_label(tag_class: str, value: str) -> str:
    if tag_class not in TAG_CLASSES:
        return value
    for item in TAG_CLASSES[tag_class].values:
        if item.value == value:
            return item.display_value
    return value


def display_for(tag_class: str, value: str, display_value: str = "") -> str:
    if display_value:
        return display_value
    return value_label(tag_class, value)


def value_criteria(tag_class: str) -> dict[str, str]:
    rows = {item.value: item.criteria for item in TAG_CLASSES[tag_class].values}
    rows["none"] = "The document does not contain this tag class, or there is no further value."
    return rows
