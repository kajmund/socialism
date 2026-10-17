"""Development set and reserved holdout for structure-aware embeddings."""

from __future__ import annotations

from overgraph_ingest.tabular.gold import SELECTED_DOCUMENTS
from overgraph_ingest.tabular.holdout import (
    HOLD_OUT_DOCUMENTS,
    SEEN_OUTSIDE_DIAGNOSTIC,
    published_contracts,
)
from overgraph_ingest.tabular.holdout_gold import HOLD_OUT_CELLS
from overgraph_ingest.tabular.user_gold import USER_CELLS, UserCellGold

ENRICH_ID = "tabular-enrich-v1"
DEV_ID = "tabular-enrich-dev-v1"
RESERVED_ID = "tabular-enrich-holdout-v1"
RESERVED_N = 20
RESERVED_STRIDE = 2

DEV_DOCUMENTS = tuple(list(SELECTED_DOCUMENTS) + list(HOLD_OUT_DOCUMENTS))

# The four Dense k=5 misses on the spent holdout. Development
# material only. Do not retune heading format to these cells.
DO_NOT_TUNE_CELLS = (
    ("Avtal_24_Kopeavtal_fastighet.docx", "liability-cap"),
    ("Avtal_40_Laneavtal_revers.docx", "auto-renewal"),
    ("Avtal_43_Leasingavtal_utrustning.docx", "auto-renewal"),
    ("Avtal_58_IT_policy_BYOD.docx", "confidentiality"),
)


def reserved_pool(documents: tuple[str, ...] | None = None) -> tuple[str, ...]:
    blocked = set(SELECTED_DOCUMENTS) | set(SEEN_OUTSIDE_DIAGNOSTIC) | set(HOLD_OUT_DOCUMENTS)
    return tuple(path for path in (documents or published_contracts()) if path not in blocked)


def select_reserved(documents: tuple[str, ...] | None = None) -> tuple[str, ...]:
    pool = reserved_pool(documents)
    picked = pool[0::RESERVED_STRIDE][:RESERVED_N]
    if len(picked) != RESERVED_N:
        raise ValueError(f"reserved holdout needs {RESERVED_N}, got {len(picked)}")
    if set(picked) & set(DEV_DOCUMENTS):
        raise ValueError("reserved holdout overlaps development documents")
    if set(picked) & set(SEEN_OUTSIDE_DIAGNOSTIC):
        raise ValueError("reserved holdout includes status-v2 documents")
    if set(picked) & {path for path, _question in DO_NOT_TUNE_CELLS}:
        raise ValueError("reserved holdout was tuned to known misses")
    return picked


# Mechanical stride 2 on the 46 leftovers after diagnostic, status-v2,
# and the spent tabular holdout. Not tuned to a representation.
RESERVED_DOCUMENTS = (
    "Avtal_16_Praktikavtal.docx",
    "Avtal_26_Stiftelseurkund.docx",
    "Avtal_29_Samarbetsavtal.docx",
    "Avtal_37_Allmanna_villkor_B2B.docx",
    "Avtal_41_Borgensforbindelse.docx",
    "Avtal_44_Avbetalningsplan.docx",
    "Avtal_49_IT_drift_hostingavtal.docx",
    "Avtal_53_Overlatelse_immateriella_rattigheter.docx",
    "Avtal_56_Bidragsavtal_CLA.docx",
    "Avtal_59_Agilt_IT_konsultavtal.docx",
    "Avtal_62_PUB_GDPR_databehandlingsavtal.docx",
    "Avtal_65_Sponsringsavtal.docx",
    "Avtal_68_Hyresavtal_fordon.docx",
    "Avtal_72_Utbildningsavtal.docx",
    "Avtal_75_Visselblasarfunktion.docx",
    "Avtal_79_Hyresavtal_lokal_Goteborg.docx",
    "Avtal_82_Uppdragsavtal_styrelseledamot.docx",
    "Avtal_85_Konvertibelt_laneavtal.docx",
    "Avtal_88_Teckningsavtal_nyemission.docx",
    "Avtal_91_Inkramsoverlatelse.docx",
)


def development_cells() -> tuple[UserCellGold, ...]:
    return tuple(USER_CELLS) + tuple(HOLD_OUT_CELLS)


def development_cell_map() -> dict[tuple[str, str], UserCellGold]:
    cells = development_cells()
    mapping = {(cell.relative_path, cell.question_id): cell for cell in cells}
    if len(mapping) != len(cells):
        raise ValueError("development gold has duplicate cells")
    return mapping


def spanned_cells() -> tuple[UserCellGold, ...]:
    return tuple(cell for cell in development_cells() if cell.answers)
