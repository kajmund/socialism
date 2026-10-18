"""Tag gold. Locked before any tag-extraction Jev run."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.doctags.catalog import (
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
    BILLING_MODEL,
    value_label,
)

GOLD_ID = "document-tags-gold-v1"

DOCUMENTS = (
    "Avtal_01_Tillsvidareanstallningsavtal.docx",
    "Avtal_02_Provanstallningsavtal.docx",
    "Avtal_03_Visstidsanstallning.docx",
    "Avtal_04_Timanstallning_behovsanstallning.docx",
    "Avtal_05_Konsultavtal.docx",
    "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
    "Avtal_07_Sekretessavtal_omsesidigt.docx",
    "Avtal_08_Konkurrensforbudsavtal.docx",
    "Avtal_11_Distansarbetsavtal.docx",
    "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
    "Avtal_13_Avgangsvederlagsavtal.docx",
    "Avtal_17_Hyresavtal_lokal.docx",
    "Avtal_36_Underleverantorsavtal.docx",
    "Avtal_38_Projektavtal_fast_pris.docx",
    "Avtal_59_Agilt_IT_konsultavtal.docx",
    "Avtal_81_VD_anstallningsavtal.docx",
)


@dataclass(frozen=True)
class TagGold:
    relative_path: str
    tag_class: str
    value: str
    contains: str
    display_value: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.relative_path, self.tag_class, self.value)


def _tag(path: str, tag_class: str, value: str, contains: str) -> TagGold:
    return TagGold(path, tag_class, value, contains, value_label(tag_class, value))


TAG_GOLDS = (
    _tag("Avtal_01_Tillsvidareanstallningsavtal.docx", EMPLOYMENT_TYPE, PERMANENT, "tillsvidareanställning"),
    _tag("Avtal_01_Tillsvidareanstallningsavtal.docx", NOTICE_PERIOD, ONE_MONTH, "en (1) månad"),
    _tag("Avtal_01_Tillsvidareanstallningsavtal.docx", CONFIDENTIALITY, SECRECY, "konfidentiell information"),
    _tag("Avtal_02_Provanstallningsavtal.docx", EMPLOYMENT_TYPE, PROBATIONARY, "Provanställning"),
    _tag("Avtal_02_Provanstallningsavtal.docx", EMPLOYMENT_TYPE, PERMANENT, "tillsvidareanställning"),
    _tag("Avtal_02_Provanstallningsavtal.docx", NOTICE_PERIOD, TWO_WEEKS, "två veckors"),
    _tag("Avtal_02_Provanstallningsavtal.docx", CONFIDENTIALITY, SECRECY, "tystnadsplikt"),
    _tag("Avtal_03_Visstidsanstallning.docx", EMPLOYMENT_TYPE, FIXED_TERM, "visstidsanställning"),
    _tag("Avtal_03_Visstidsanstallning.docx", NOTICE_PERIOD, ONE_MONTH, "en (1) månads"),
    _tag("Avtal_03_Visstidsanstallning.docx", CONFIDENTIALITY, SECRECY, "tystnadsplikt"),
    _tag("Avtal_04_Timanstallning_behovsanstallning.docx", EMPLOYMENT_TYPE, HOURLY, "Timanställning"),
    _tag("Avtal_04_Timanstallning_behovsanstallning.docx", EMPLOYMENT_TYPE, FIXED_TERM, "särskild visstidsanställning"),
    _tag("Avtal_04_Timanstallning_behovsanstallning.docx", CONFIDENTIALITY, SECRECY, "tystnadsplikt"),
    _tag("Avtal_05_Konsultavtal.docx", BILLING_MODEL, HOURLY, "kronor per timme"),
    _tag("Avtal_05_Konsultavtal.docx", NOTICE_PERIOD, THIRTY_DAYS, "30] dagars uppsägningstid"),
    _tag("Avtal_05_Konsultavtal.docx", CONFIDENTIALITY, SECRECY, "hålla Konfidentiell information hemlig"),
    _tag("Avtal_06_Sekretessavtal_ensidigt_NDA.docx", CONFIDENTIALITY, SECRECY, "hålla Konfidentiell Information hemlig"),
    _tag("Avtal_07_Sekretessavtal_omsesidigt.docx", CONFIDENTIALITY, SECRECY, "hålla Konfidentiell Information hemlig"),
    _tag("Avtal_08_Konkurrensforbudsavtal.docx", NON_COMPETE, NON_COMPETE_VALUE, "Konkurrensförbud"),
    _tag("Avtal_11_Distansarbetsavtal.docx", WORK_LOCATION, REMOTE, "arbeta på distans"),
    _tag("Avtal_11_Distansarbetsavtal.docx", NOTICE_PERIOD, ONE_MONTH, "en (1)] månads uppsägningstid"),
    _tag("Avtal_11_Distansarbetsavtal.docx", CONFIDENTIALITY, SECRECY, "Konfidentiella handlingar"),
    _tag("Avtal_13_Avgangsvederlagsavtal.docx", CONFIDENTIALITY, SECRECY, "tystnadsplikt"),
    _tag("Avtal_17_Hyresavtal_lokal.docx", NOTICE_PERIOD, NINE_MONTHS, "nio (9)] månader"),
    _tag("Avtal_36_Underleverantorsavtal.docx", BILLING_MODEL, HOURLY, "kronor per timme"),
    _tag("Avtal_36_Underleverantorsavtal.docx", CONFIDENTIALITY, SECRECY, "hålla information om DevBrains"),
    _tag("Avtal_38_Projektavtal_fast_pris.docx", BILLING_MODEL, FIXED_PRICE, "fast pris"),
    _tag("Avtal_59_Agilt_IT_konsultavtal.docx", BILLING_MODEL, TIME_AND_MATERIALS, "löpande räkning"),
    _tag("Avtal_59_Agilt_IT_konsultavtal.docx", CONFIDENTIALITY, SECRECY, "följa sekretess"),
    _tag("Avtal_81_VD_anstallningsavtal.docx", EMPLOYMENT_TYPE, PERMANENT, "gäller tills vidare"),
    _tag("Avtal_81_VD_anstallningsavtal.docx", NOTICE_PERIOD, SIX_MONTHS, "sex (6) månader"),
    _tag("Avtal_81_VD_anstallningsavtal.docx", WORK_LOCATION, STOCKHOLM, "Placeringsort är Stockholm"),
    _tag("Avtal_81_VD_anstallningsavtal.docx", CONFIDENTIALITY, SECRECY, "tystnadsplikt"),
    _tag("Avtal_81_VD_anstallningsavtal.docx", NON_COMPETE, NON_COMPETE_VALUE, "verksamhet som konkurrerar"),
)


def golds_for(relative_path: str) -> tuple[TagGold, ...]:
    return tuple(item for item in TAG_GOLDS if item.relative_path == relative_path)


def gold_keys() -> set[tuple[str, str, str]]:
    return {item.key() for item in TAG_GOLDS}


def assert_tag_gold_complete() -> None:
    if len(DOCUMENTS) != 16:
        raise ValueError(f"tag gold needs 16 documents, got {len(DOCUMENTS)}")
    if {item.relative_path for item in TAG_GOLDS} - set(DOCUMENTS):
        raise ValueError("tag gold paths are outside the locked sample")
    if golds_for("Avtal_02_Provanstallningsavtal.docx").__len__() < 2:
        raise ValueError("probationary documents must allow several employment_type values")
    if golds_for("Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx"):
        raise ValueError("placeholder notice periods are not gold values")
    keys = [item.key() for item in TAG_GOLDS]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate tag gold keys")
