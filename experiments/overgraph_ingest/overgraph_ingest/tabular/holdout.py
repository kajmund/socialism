"""Independent holdout for Tabular Review. Gold before any model run."""

from __future__ import annotations

import re
from pathlib import Path

from overgraph_ingest.tabular.gold import SELECTED_DOCUMENTS
from overgraph_ingest.tabular.status_v2_cases import HARD_NEG, HARD_POS, HOLDOUT_NEG

ROOT = Path(__file__).resolve().parents[2]
EXTRA_CORPUS = ROOT / "data" / "extra_corpus"
HOLD_OUT_ID = "tabular-holdout-v1"
HOLD_OUT_N = 20
HOLD_OUT_STRIDE = 3
AVTAL_RE = re.compile(r"Avtal_(\d+)_")

# Read for a different experiment against retrieval gold.
# They have never had D/E/K tabular cells, but they are not unseen to us.
SEEN_OUTSIDE_DIAGNOSTIC = frozenset(
    case.relative_path for case in (*HARD_POS, *HARD_NEG, *HOLDOUT_NEG)
)


def avtal_number(relative_path: str) -> int:
    match = AVTAL_RE.match(relative_path)
    if match is None:
        raise ValueError(f"unnumbered contract: {relative_path}")
    return int(match.group(1))


def published_contracts(directory: Path | None = None) -> tuple[str, ...]:
    folder = directory or EXTRA_CORPUS
    return tuple(sorted((path.name for path in folder.glob("Avtal_*.docx")), key=avtal_number))


def holdout_pool(documents: tuple[str, ...]) -> tuple[str, ...]:
    blocked = set(SELECTED_DOCUMENTS) | set(SEEN_OUTSIDE_DIAGNOSTIC)
    return tuple(path for path in documents if path not in blocked)


def select_holdout(documents: tuple[str, ...] | None = None) -> tuple[str, ...]:
    pool = holdout_pool(documents or published_contracts())
    picked = pool[0::HOLD_OUT_STRIDE][:HOLD_OUT_N]
    if len(picked) != HOLD_OUT_N:
        raise ValueError(f"holdout needs {HOLD_OUT_N} documents, got {len(picked)}")
    if set(picked) & set(SELECTED_DOCUMENTS):
        raise ValueError("holdout overlaps the diagnostic twenty")
    if set(picked) & set(SEEN_OUTSIDE_DIAGNOSTIC):
        raise ValueError("holdout includes documents already read for status v2")
    return picked


# Frozen by the stride rule on the 66 unseen leftovers. Not tuned
# to a variant or to retrieval gold. Gold is written before models.
HOLD_OUT_DOCUMENTS = (
    "Avtal_15_Bonusavtal.docx",
    "Avtal_24_Kopeavtal_fastighet.docx",
    "Avtal_28_Aktieagaravtal.docx",
    "Avtal_33_Agentavtal.docx",
    "Avtal_40_Laneavtal_revers.docx",
    "Avtal_43_Leasingavtal_utrustning.docx",
    "Avtal_48_Mjukvaruutvecklingsavtal.docx",
    "Avtal_51_Anvandarvillkor_webbplats_app.docx",
    "Avtal_55_Overlatelse_domannamn.docx",
    "Avtal_58_IT_policy_BYOD.docx",
    "Avtal_61_PUB_avtal_DevBrains_ansvarig.docx",
    "Avtal_64_Byraavtal_reklam.docx",
    "Avtal_67_Evenemangsavtal.docx",
    "Avtal_71_Konstnarsavtal.docx",
    "Avtal_74_Forsakringsavtal.docx",
    "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
    "Avtal_81_VD_anstallningsavtal.docx",
    "Avtal_84_Villkorat_aktieagartillskott.docx",
    "Avtal_87_Investeringsavtal.docx",
    "Avtal_90_Anslutningsavtal.docx",
)
