"""Build human-review candidates for clause localization from synthetic SME.

Generator metadata is only a hint for selecting review cases; it is NOT facit.
Every card is pending human review. The output is a candidate manifest consumed
by the admin verification queue, not a learned anchor library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import zipfile
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "synthetic_sme" / "contracts"
TRUTH = ROOT / "synthetic_sme" / "ground_truth" / "truth_model.json"
DEFAULT_OUT = ROOT / "synthetic_sme" / "ground_truth" / "clause_review_candidates_v1.json"

CATEGORIES = {
    "termination_notice": {
        "field": "notice_months",
        "keywords": ("uppsägning", "sägas upp", "uppsägs", "varsel"),
    },
    "automatic_renewal": {
        "field": "auto_renew_months",
        "keywords": ("förlängs automatiskt", "automatisk förlängning", "förlängs därefter"),
    },
    "price": {
        "field": "pricing_model",
        "keywords": ("pris", "ersättning", "arvode", "timpris", "index"),
    },
    "liability_limitation": {
        "field": "liability_cap",
        "keywords": ("ansvar", "ansvarsbegränsning", "skadestånd", "begränsat ansvar"),
    },
}


def _path_for(contract_id: str) -> Path | None:
    hits = sorted(CONTRACTS.glob(f"**/{contract_id}_*.docx"))
    return hits[0] if hits else None


def _paragraphs(path: Path) -> list[str]:
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    texts = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if text:
            texts.append(text)
    return texts


def _candidate(paragraphs: list[str], keywords: tuple[str, ...]) -> tuple[int, str]:
    lowered = [item.lower() for item in paragraphs]
    for index, item in enumerate(lowered):
        if any(keyword in item for keyword in keywords):
            return index, paragraphs[index]
    for index, item in enumerate(paragraphs):
        if len(item) > 40:
            return index, item
    return 0, paragraphs[0]


def _present(contract: dict, field: str) -> bool:
    value = contract.get(field)
    return value not in (None, "", False, 0)


def _split(contract_id: str) -> str:
    digest = int(hashlib.sha256(contract_id.encode()).hexdigest()[:8], 16)
    return "anchor" if digest % 2 == 0 else "test"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=int, default=35)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    rows = []
    selected = 0
    for contract in truth["contracts"]:
        contract_id = contract["id"]
        path = _path_for(contract_id)
        if path is None:
            continue
        if selected >= args.contracts:
            break
        selected += 1
        paragraphs = _paragraphs(path)
        for category, spec in CATEGORIES.items():
            index, text = _candidate(paragraphs, spec["keywords"])
            rows.append(
                {
                    "case_id": f"{contract_id}:{category}",
                    "facit_version": "v1-candidates",
                    "not_facit": True,
                    "review_status": "pending_human_review",
                    "contract_id": contract_id,
                    "kind": contract.get("kind"),
                    "title": contract.get("title"),
                    "source_path": str(path.relative_to(ROOT)),
                    "document_title": path.stem,
                    "category": category,
                    "split": _split(contract_id),
                    "generator_hint": {
                        "field": spec["field"],
                        "present": _present(contract, spec["field"]),
                        "value": contract.get(spec["field"]),
                    },
                    "candidate": {
                        "paragraph_index": index,
                        "text": text,
                        "locator": f"stycke {index + 1}",
                    },
                    "review": {
                        "verifier": None,
                        "reviewed_at": None,
                        "method": None,
                        "verdict": None,
                        "clause_text": None,
                        "note": "",
                    },
                }
            )
    payload = {
        "version": "v1-candidates",
        "not_facit": True,
        "description": "Human-review candidates. Generator metadata is only a selection hint; no entry is verified.",
        "categories": list(CATEGORIES),
        "contracts": selected,
        "cards": len(rows),
        "rows": rows,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"contracts": selected, "cards": len(rows), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
