"""contracts_v2 gold as RetrievalGold. Measurement only. Not a proof rule."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from overgraph_ingest.coverage.blind_carveout import GOLD_ZIP
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold

PROPERTY_SPECS = {
    "A_automatisk_forlangning": {
        "id": "auto-renewal",
        "kind": "unit",
        "proof_kind": "EXISTS",
        "query": "Vilka avtal innehåller bestämmelser om automatisk förlängning?",
        "classify_question": (
            "Innehåller texten en bestämmelse där avtalet förlängs automatiskt "
            "utan ett nytt uttryckligt godkännande från båda parterna?"
        ),
    },
    "B_uppsagningstid": {
        "id": "notice-period",
        "kind": "unit",
        "proof_kind": "EXISTS",
        "query": "Vilka avtal innehåller en uppsägningstid?",
        "classify_question": "Innehåller texten en stående uppsägningstid för att avsluta avtalet?",
    },
    "C_ansvarsbegransning": {
        "id": "liability-cap",
        "kind": "unit",
        "proof_kind": "EXISTS",
        "query": "Vilka avtal begränsar ansvaret för skada?",
        "classify_question": (
            "Innehåller texten en avtalsenlig ansvarsbegränsning, till exempel "
            "ett takbelopp eller ett undantag för indirekt skada?"
        ),
    },
    "D_sekretess": {
        "id": "confidentiality",
        "kind": "unit",
        "proof_kind": "EXISTS",
        "query": "Vilka avtal innehåller en sekretessplikt?",
        "classify_question": (
            "Innehåller texten en skyldighet att hålla information hemlig eller "
            "att inte röja konfidentiella uppgifter?"
        ),
    },
    "E_sekretessundantag_fran_ansvarsbegransning": {
        "id": "liability-secrecy-carveout",
        "kind": "multi_clause",
        "proof_kind": "COMPOSITE",
        "query": "Vilka avtal undantar brott mot sekretess från ansvarsbegränsningen?",
        "classify_question": (
            "Innehåller texten att ansvarsbegränsningen inte gäller vid brott mot sekretess?"
        ),
    },
}


def load_blind_property(
    property_id: str,
    *,
    zip_path: Path | None = None,
) -> tuple[RetrievalGold, dict[str, str], dict[str, str]]:
    spec = PROPERTY_SPECS[property_id]
    yes: list[GoldSpan] = []
    document_gold: list[str] = []
    classes: dict[str, str] = {}
    traps: dict[str, str] = {}
    with zipfile.ZipFile(zip_path or GOLD_ZIP) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("gold/avtal_") or not name.endswith(".json"):
                continue
            doc = json.loads(archive.read(name))
            path = str(doc.get("filename") or f"{doc['document_id']}.docx")
            prop = doc["properties"][property_id]
            classification = str(prop.get("classification") or "")
            if not classification:
                continue
            classes[path] = classification
            if classification == "YES":
                document_gold.append(path)
                quotes = [
                    str(item.get("quote") or "")
                    for item in list(prop.get("relation_established_by") or [])
                    + list(prop.get("evidence") or [])
                    if item.get("quote")
                ]
                if quotes:
                    yes.append(GoldSpan(relative_path=path, contains=quotes[0]))
            for item in doc.get("expected_hard_negatives") or []:
                marked = str(item.get("property") or "")
                if marked == property_id or marked.startswith(property_id[0] + "_") or marked == property_id[0]:
                    trap = str(item.get("trap_type") or "")
                    if trap:
                        traps[path] = trap
    gold = RetrievalGold(
        id=str(spec["id"]),
        query=str(spec["query"]),
        notes=(
            "Synthetic contracts_v2 gold. Not legally reviewed. UNCERTAIN is not NO. "
            "Gold tests prevailing terms of the document, not mere formulation presence."
        ),
        classify_question=str(spec["classify_question"]),
        kind=str(spec["kind"]),
        proof_kind=str(spec["proof_kind"]),
        relevant_units=yes,
        hard_negatives=[],
        document_gold=tuple(document_gold),
        coverage_groups=[],
        split="seen",
    )
    return gold, classes, traps


def write_blind_gold(
    property_id: str,
    path: Path,
    *,
    zip_path: Path | None = None,
) -> Path:
    gold, _classes, _traps = load_blind_property(property_id, zip_path=zip_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": gold.id,
        "kind": gold.kind,
        "proof_kind": gold.proof_kind,
        "query": gold.query,
        "classify_question": gold.classify_question,
        "notes": gold.notes,
        "relevant_documents": list(gold.relevant_documents),
        "relevant_units": [
            {"relative_path": span.relative_path, "contains": span.contains}
            for span in gold.relevant_units
        ],
        "hard_negatives": [],
        "coverage_groups": [],
        "split": gold.split,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
