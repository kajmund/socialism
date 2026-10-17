"""Frozen 20-document selection and user questions. Gold is never model input."""

from __future__ import annotations

from pathlib import Path

from overgraph_ingest.cerebras.evaluate import relevant_keys
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.index import StoredUnit

QUESTION_IDS = (
    "auto-renewal",
    "notice-period",
    "liability-cap",
    "confidentiality",
    "liability-secrecy-carveout",
)
USER_QUESTIONS = {
    "auto-renewal": "Förlängs avtalet automatiskt?",
    "notice-period": "Vilken uppsägningstid gäller enligt avtalet?",
    "liability-cap": "Finns det en begränsning av parternas skadeståndsansvar?",
    "confidentiality": "Finns det en sekretessplikt i avtalet?",
    "liability-secrecy-carveout": "Undantas brott mot sekretess från ansvarsbegränsningen?",
}
# Chosen from gold-map v2 before any Tabular model run. Two gold
# documents per question first, then published leftovers. Not tuned
# to a variant. Diagnostic first run only; not a general quality
# sample for Tabular Review. The 100-document run is separate.
SELECTED_DOCUMENTS = (
    "Avtal_17_Hyresavtal_lokal.docx",
    "Avtal_18_Hyresavtal_bostad.docx",
    "Avtal_01_Tillsvidareanstallningsavtal.docx",
    "Avtal_05_Konsultavtal.docx",
    "Avtal_22_Kontorshotell_coworking.docx",
    "Avtal_25_Fastighetsservice_stadning.docx",
    "Avtal_02_Provanstallningsavtal.docx",
    "Avtal_03_Visstidsanstallning.docx",
    "Avtal_30_Ramavtal_tjanster.docx",
    "Avtal_36_Underleverantorsavtal.docx",
    "Avtal_04_Timanstallning_behovsanstallning.docx",
    "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
    "Avtal_07_Sekretessavtal_omsesidigt.docx",
    "Avtal_08_Konkurrensforbudsavtal.docx",
    "Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx",
    "Avtal_100_Djurkopeavtal.docx",
    "Avtal_10_Arbetstidsavtal_flextid.docx",
    "Avtal_11_Distansarbetsavtal.docx",
    "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
    "Avtal_13_Avgangsvederlagsavtal.docx",
)


def load_tabular_golds(gold_dir: Path) -> list[RetrievalGold]:
    wanted = set(QUESTION_IDS)
    golds = [
        gold
        for gold in load_gold_suite(gold_dir)
        if gold.id in wanted and gold.split == "seen"
    ]
    if {gold.id for gold in golds} != wanted:
        raise ValueError("tabular gold set is incomplete")
    return golds


def cell_relevant_keys(
    units: list[StoredUnit],
    gold: RetrievalGold,
    relative_path: str,
) -> set[str]:
    local = [unit for unit in units if unit.relative_path == relative_path]
    return {key for key in relevant_keys(local, gold)}


def document_short_id(relative_path: str) -> str:
    return Path(relative_path).stem
