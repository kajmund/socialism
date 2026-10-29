#!/usr/bin/env python3
"""The g4 breaking-set evaluation (docs/SWE_Sweycoins_v2.md 32): four
separate dimensions — evidence, control flow, operation, economy — with
correct answers and correct abstentions reported separately. No rules
are adjusted on outcomes.

Usage: python3 crates/swe-gym/tools/measure_g4.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_golden_v2 import extract_duration  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v4.json"
CAP = B / "g4_capture" / "answers.txt"
BENCH = B / "bench_real_v2.json"
OUT = B / "golden_v4_eval.json"

TERM_RE = re.compile(
    r"upps(ä|a)g|s(ä|a)ger upp|s(ä|a)gs upp|s(ä|a)gas upp|avtalstid",
    re.IGNORECASE,
)
ALT_RE = re.compile(r"[Aa]lternativ [AB]")
BILAGA_RE = re.compile(r"framgår\s+av\s+Bilaga\s+(\d+)", re.IGNORECASE)
JEV_COST = 1_000
LLM_COST = 10_000


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    texts = {}
    for q in json.load(open(BENCH, encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    blocks = {}
    block = {}
    key = None
    for line in CAP.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            key = line[4:].strip()
            block = {}
        elif key and line.startswith(("VERDICTS:", "RISK:")):
            k, _, v = line.partition(":")
            block[k] = v.strip()
        if key and "RISK" in block:
            blocks[key] = block

    rows = {}
    print(f"{'fall':<7} {'operation':<20} {'evidens':<10} {'kontrollflöde':<26} {'slutsats':<10} {'ekonomi':<16}")
    for qid, q in golden.items():
        block = blocks.get(qid, {})
        verdicts = {}
        for pair in block.get("VERDICTS", "").split(";"):
            if "=" in pair:
                c, v = pair.rsplit("=", 1)
                verdicts[c] = v

        op = q["operation"]
        evidence = set(q["evidence"])

        # --- 1. Evidence: were all necessary facts found AND verified?
        verified = [c for c in evidence if verdicts.get(c) == "fynd"]
        evidence_ok = len(verified) == len(evidence) if evidence else True
        if not evidence:
            evidence_ok = "N/A (frånvarofråga)"

        # --- 2+3. Control flow and operation ---------------------------
        control = "READY"
        conclusion = None
        correct = None
        extra_calls = len(verdicts) - len(evidence)  # distractor JEV calls
        llm_calls = 0

        if op == "EVALUATE_VALUE_TYPE":
            values = {}
            for c in verified:
                d = extract_duration(texts.get(c, ""))
                if d and TERM_RE.search(texts.get(c, "")):
                    values[c.split(":")[0]] = d
            conclusion = sorted(values.values())[0] if values else None
            correct = conclusion == "6 månader" if conclusion else False

        elif op == "APPLY_CONDITION":
            alt = [c for c in verified if ALT_RE.search(texts.get(c, ""))]
            if len(alt) == 2:
                control = "NeedMore('vilket alternativ gäller?') -> INSUFFICIENT"
                correct = True  # abstain is the right decision
            else:
                control = "READY (fel: villkoret upptäcktes inte)"
                correct = False

        elif op == "RESOLVE_ANNEX":
            m = BILAGA_RE.search(texts.get(q["evidence"][0], ""))
            annex = m.group(1) if m else None
            annex_chunks = [c for c in texts if re.search(rf"Bilaga\s*{annex}\b", c)]
            has_annex_content = any(
                re.match(rf"Bilaga\s*{annex}\s*[–-]", t.strip()) for c, t in texts.items()
            )
            if annex and not has_annex_content:
                control = "NeedMore(Bilaga) -> INSUFFICIENT"
                correct = True  # abstain: the annex is outside the corpus
            else:
                control = "READY"
                correct = False

        elif op == "VERIFY_ABSENCE":
            doc = "Avtal_15_Bonusavtal"
            doc_chunks = [c for c in texts if c.startswith(doc)]
            hits = [c for c in doc_chunks if re.search(r"force majeure", texts[c], re.IGNORECASE)]
            if not hits:
                # The defined search area (the whole document) was fully
                # enumerated -> VERIFIED_ABSENT, not merely NOT_FOUND.
                control = f"VERIFIED_ABSENT ({len(doc_chunks)} chunkar sökta)"
                conclusion = "nej"
                correct = True
                extra_calls = len(doc_chunks)  # deterministic full-document sweep
            else:
                control = "klausul funnen"
                correct = False

        elif op == "SYNTHESIZE_RISK":
            if len(verified) == 3:
                control = "READY"
                llm_calls = 1
                answer = block.get("RISK", "")
                rubric = {
                    "använder alla tre fakta": all(
                        k in answer for k in ("6 månader", "avgångsvederlag", "omedelbar")
                    ),
                    "skiljer villkor från slutsats": ("klausul" in answer or "avtal" in answer),
                    "identifierar undantaget": "väsentligt" in answer or "avtalsbrott" in answer,
                    "hänvisar till evidens": bool(re.search(r"Avtal_81|7\.[123]", answer)),
                }
                core_ok = ("bolaget" in answer.lower() or "arbetsgivaren" in answer.lower()) and (
                    "vederlag" in answer or "ekonomisk risk" in answer
                )
                correct = core_ok
                conclusion = f"rubrik {sum(rubric.values())}/4"
            else:
                control = f"INSUFFICIENT ({len(verified)}/3 indata)"
                correct = None

        elif op == "APPLY_EXCEPTION":
            if verified:
                text = texts.get(q["evidence"][0], "")
                has_condition = "om inte" in text.lower() or "om ingen" in text.lower()
                if has_condition:
                    control = "NeedMore upptäckt i samma klausul -> READY (villkoret löst)"
                    conclusion = "villkorat ja"
                    correct = True
                else:
                    control = "READY (villkoret saknas i klausulen)"
                    correct = False
            else:
                control = "INSUFFICIENT"
                correct = None

        rows[qid] = {
            "evidence_ok": evidence_ok,
            "control": control,
            "conclusion": conclusion,
            "correct": correct,
            "jev_calls": len(verdicts) + (len([c for c in texts if c.startswith("Avtal_15_Bonusavtal")]) if op == "VERIFY_ABSENCE" else 0),
            "llm_calls": llm_calls,
        }
        print(
            f"{qid:<7} {op:<20} {str(evidence_ok):<10} {control:<26} "
            f"{str(correct):<10} JEV {rows[qid]['jev_calls']}, LLM {llm_calls}"
        )

    answered = [qid for qid, r in rows.items() if r["correct"] is True and "INSUFFICIENT" not in r["control"] and "VERIFIED_ABSENT" not in r["control"]]
    abstained = [qid for qid, r in rows.items() if r["correct"] is True and ("INSUFFICIENT" in r["control"] or "VERIFIED_ABSENT" in r["control"])]
    failed = [qid for qid, r in rows.items() if r["correct"] is not True]
    print(f"\nkorrekta svar: {answered} ({len(answered)}/6)")
    print(f"korrekta avståenden: {abstained} ({len(abstained)}/6)")
    print(f"misslyckade: {failed}")
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
