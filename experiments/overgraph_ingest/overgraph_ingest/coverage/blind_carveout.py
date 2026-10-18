"""Blind-gold E quotes versus the frozen detectors. No new Jev. No controller."""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from pathlib import Path

from overgraph_ingest.coverage.proof_link import LINKED_RELATION, evaluate_passage
from overgraph_ingest.coverage.proof_logic import CLAIM_FORM, read_logic

ROOT = Path(__file__).resolve().parents[2]
GOLD_ZIP = ROOT / "data" / "corpus_blind" / "contracts_v2_gold.zip"
PROPERTY = "E_sekretessundantag_fran_ansvarsbegransning"
BLIND_BASELINE_ID = "phase2-blind-carveout-gold-v1"
BLIND_BASELINE_PATH = ROOT / "baselines" / f"{BLIND_BASELINE_ID}.json"


def load_e_rows(zip_path: Path | None = None) -> list[dict[str, object]]:
    rows = []
    with zipfile.ZipFile(zip_path or GOLD_ZIP) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("gold/avtal_") or not name.endswith(".json"):
                continue
            doc = json.loads(archive.read(name))
            e = doc["properties"][PROPERTY]
            quotes = [
                str(item.get("quote") or "")
                for item in list(e.get("relation_established_by") or []) + list(e.get("evidence") or [])
                if item.get("quote")
            ]
            traps = [
                str(item.get("trap_type") or "")
                for item in (doc.get("expected_hard_negatives") or [])
                if str(item.get("property") or "").startswith("E")
            ]
            rows.append(
                {
                    "id": doc["document_id"],
                    "classification": e.get("classification"),
                    "supported_relation": e.get("supported_relation"),
                    "pattern": e.get("evidence_pattern"),
                    "scope": e.get("evidence_scope"),
                    "traps": traps,
                    "quotes": quotes,
                    "link": any(evaluate_passage(text)["status"] == LINKED_RELATION for text in quotes),
                    "form": read_logic("\n".join(quotes)).form if quotes else "undecided",
                }
            )
    return rows


def run_blind_carveout(*, zip_path: Path | None = None) -> dict[str, object]:
    rows = load_e_rows(zip_path)
    yes = [row for row in rows if row["classification"] == "YES"]
    no = [row for row in rows if row["classification"] == "NO"]
    unc = [row for row in rows if row["classification"] == "UNCERTAIN"]
    return {
        "operation": "coverage",
        "experiment": "blind_carveout_gold_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_looser_verified_rule": True,
        "gold_is_synthetic": True,
        "yes_count": len(yes),
        "no_count": len(no),
        "uncertain_count": len(unc),
        "yes_link": sum(1 for row in yes if row["link"]),
        "yes_claim_form": sum(1 for row in yes if row["form"] == CLAIM_FORM),
        "no_link": sum(1 for row in no if row["link"]),
        "uncertain_link": [row["id"] for row in unc if row["link"]],
        "yes_multi_clause": sum(1 for row in yes if row["scope"] == "multi_clause"),
        "yes_relations": dict(Counter(str(row["supported_relation"]) for row in yes)),
        "no_relations": dict(Counter(str(row["supported_relation"]) for row in no)),
        "no_traps": dict(Counter(trap for row in no for trap in (row["traps"] or ["none"]))),
        "uncertain_relations": dict(Counter(str(row["supported_relation"]) for row in unc)),
        "yes_wording": {
            "no_secrecy_word": sum(
                1
                for row in yes
                if not any(
                    token in " ".join(row["quotes"]).lower()
                    for token in ("sekretess", "konfidentiell", "förtrolig", "tystnadsplikt")
                )
            ),
            "has_sekretess": sum(1 for row in yes if "sekretess" in " ".join(row["quotes"]).lower()),
            "has_defined_term": sum(
                1
                for row in yes
                if any(token in " ".join(row["quotes"]).lower() for token in ("konfidentiell", "förtrolig"))
            ),
            "has_tystnadsplikt": sum(1 for row in yes if "tystnadsplikt" in " ".join(row["quotes"]).lower()),
            "anaphor": sum(
                1
                for row in yes
                if any(token in " ".join(row["quotes"]).lower() for token in ("detsamma gäller", "samma sak gäller"))
            ),
        },
        "yes_samples": [
            {
                "id": "avtal_103",
                "quote": "Inget i denna punkt ska begränsa parts ansvar för brott mot avsnitt 4.",
                "why_missed": "heading reference, no secrecy word, no LINK_RE lexicon",
            },
            {
                "id": "avtal_106",
                "quote": "Detsamma gäller skada som uppkommer till följd av att part åsidosätter sin tystnadsplikt.",
                "why_missed": "anaphor plus tystnadsplikt; LINK_RE wants sekretess in the same span",
            },
            {
                "id": "avtal_121",
                "quote": "Ansvarsbegränsningen ovan gäller inte i följande fall: / brott mot klausul 7",
                "why_missed": "letter list; secrecy lives in the resolved heading",
            },
            {
                "id": "avtal_140",
                "quote": "skada till följd av obehörigt röjande av Förtrolig Information",
                "why_missed": "defined term, not the word sekretess",
            },
        ],
        "no_samples": [
            {
                "id": "avtal_101",
                "trap": "co_occurrence_without_relation",
                "quote": "Begränsningarna enligt ovan gäller inte om part har orsakat skadan uppsåtligen eller genom grov vårdslöshet.",
            },
            {
                "id": "avtal_132",
                "trap": "wrong_reference",
                "quote": "Begränsningen gäller inte heller vid brott mot § 12.",
            },
            {
                "id": "avtal_156",
                "trap": "negation",
                "quote": "Det förhållandet att en skada har uppkommit genom röjande av information som omfattas av tystnadsplikten medför inte att begränsningen i klausul 8.2 upphör att gälla.",
            },
            {
                "id": "avtal_162",
                "trap": "relation_present_but_inverse",
                "quote": "Begränsningarna gäller även för skada till följd av brott mot sekretessåtagandet.",
            },
            {
                "id": "avtal_119",
                "trap": "precedence_override",
                "quote": "Med ändring av punkt 2.4 i Bilaga 2 gäller ansvarsbegränsningen även vid brott mot sekretess.",
            },
            {
                "id": "avtal_109",
                "trap": "topical_similarity",
                "quote": "Begränsningen gäller inte heller för ansvar enligt artikel 82 i dataskyddsförordningen",
            },
        ],
        "uncertain_samples": [
            {
                "id": "avtal_138",
                "quote": "Begränsningen gäller inte heller vid brott mot sekretessåtagandet i punkt 12.",
                "why": "LINK_RE matches, gold leaves UNCERTAIN: the number points elsewhere",
            },
            {
                "id": "avtal_173",
                "quote": "Begränsningen gäller inte heller vid brott mot sekretessåtagandet i punkt 8.",
                "why": "same falsa demonstratio as avtal_138",
            },
        ],
        "error_layers": {
            "retrieval": "not measured here; Recall@50 is capped by candidate budget",
            "classification": "Jev C@8 is a candidate filter, not a proof",
            "proof_evaluation": "LINK_RE and claim-form miss every gold YES quote",
        },
        "live_false_completes_not_in_workspace": True,
    }


def freeze_blind_carveout_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": BLIND_BASELINE_ID,
        "label": (
            "Frozen: blind gold E versus the seen-corpus detectors. "
            "Do not loosen verified. Gold is synthetic."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "gold_is_synthetic": True,
        "headline": {
            "yes_count": payload.get("yes_count"),
            "yes_link": payload.get("yes_link"),
            "yes_claim_form": payload.get("yes_claim_form"),
            "no_link": payload.get("no_link"),
            "uncertain_link": payload.get("uncertain_link"),
            "yes_multi_clause": payload.get("yes_multi_clause"),
            "no_secrecy_word": (payload.get("yes_wording") or {}).get("no_secrecy_word")
            if isinstance(payload.get("yes_wording"), dict)
            else None,
        },
        "yes_relations": payload.get("yes_relations"),
        "yes_wording": payload.get("yes_wording"),
        "yes_samples": payload.get("yes_samples"),
        "no_relations": payload.get("no_relations"),
        "no_traps": payload.get("no_traps"),
        "no_samples": payload.get("no_samples"),
        "uncertain_relations": payload.get("uncertain_relations"),
        "uncertain_samples": payload.get("uncertain_samples"),
        "error_layers": payload.get("error_layers"),
        "live_false_completes_not_in_workspace": payload.get(
            "live_false_completes_not_in_workspace"
        ),
    }


def write_blind_carveout_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or BLIND_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_blind_carveout_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
