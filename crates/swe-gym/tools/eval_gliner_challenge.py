#!/usr/bin/env python3
"""The three challenge-set measurements (docs/architecture/
gliner2-jevspan-evaluation.md, D3): unique candidate recall, JEV
verification survival, and actual task utility — with a per-span
diagnosis table (candidate-generation gap / verification gap /
complete finding / false positive).

Live: JEV span verification over the union of gold-span candidates
(bounded, env-gated via backend/.env).

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_gliner_challenge.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_gliner_testset import spans_of, LABEL_MAP  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
OUT = B / "gliner_challenge_eval.json"


def env_value(name, dotenv, fallback=""):
    import os
    v = os.environ.get(name)
    if v:
        return v
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, raw = line.partition("=")
            if k.strip() == name:
                return raw.strip().strip('"')
    return fallback


def normalize(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def jev_verify(api_key, base, model, clause, span):
    """Span-level JEV verification: does this exact span state the
    fact? Mirrors the swe-gym HttpJevProvider request shape."""
    body = json.dumps({
        "model": model,
        "state": {"text": clause},
        "questions": {
            "evidence": {
                "type": "choice",
                "instructions": (
                    f"Utgör det exakta spannet '{span}' i klausulen ett juridiskt "
                    "sakförhållande (tidsfrist, ersättning, villkor, begränsning, "
                    "undantag, belopp, datum eller part)? Bedöm enbart spannet."
                ),
                "criteria": {
                    "YES": "Spannet utgör exakt ett juridiskt sakförhållande.",
                    "NO": "Spannet utgör inte ett juridiskt sakförhållande.",
                    "UNCERTAIN": "Går inte att avgöra.",
                },
            }
        },
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/v1/systemone",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    row = payload["answers"]["evidence"]
    return row.get("choice"), row.get("score_bp")


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]

    from gliner2 import AutoExtractor
    extractor = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")

    rows = []
    unique_recall = {"found_by_gliner_only": 0, "total_gold": 0}
    survival = {"unique_verified": 0, "unique_total": 0}
    needs = {}
    for case in cases:
        gold = {normalize(g["span"]): g["type"] for g in case["gold"]}
        det = {normalize(s) for _, s in spans_of(case["clause"])}
        NEED_LABELS = {
            "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
            "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
            "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
            "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
            "DATE": "Datum", "PERIOD": "Tidsperiod",
        }
        labels = [NEED_LABELS[t] for t in set(gold.values())][:3]
        raw = extractor.extract_entities(case["clause"], entity_types=labels,
                                         threshold=0.3, format_results=False)
        glin = set()
        for entry in raw.get("entities", []):
            for label, spans in entry.items():
                for span in spans:
                    glin.add(normalize(span))

        # Three measurements per gold span + diagnosis.
        span_rows = []
        need_solved = True
        for gold_span, gold_type in gold.items():
            unique_recall["total_gold"] += 1
            gen_hit = gold_span in det
            glin_hit = gold_span in glin
            verdict = None
            if glin_hit and not gen_hit:
                # Unique GLiNER2 span: does it survive JEV verification?
                unique_recall["found_by_gliner_only"] += 1
                survival["unique_total"] += 1
                verdict, score = jev_verify(api_key, base, model,
                                            case["clause"], gold_span)
                if verdict == "YES":
                    survival["unique_verified"] += 1
            elif gen_hit:
                verdict, score = jev_verify(api_key, base, model,
                                            case["clause"], gold_span)
            if verdict != "YES":
                need_solved = False
            if not gen_hit and not glin_hit:
                diagnosis = "candidate-generation gap"
            elif (gen_hit or glin_hit) and verdict != "YES":
                diagnosis = "recognition/verification gap"
            elif verdict == "YES":
                diagnosis = "fullständigt fynd"
            else:
                diagnosis = "okänd"
            span_rows.append({
                "span": gold_span,
                "type": gold_type,
                "generator": gen_hit,
                "gliner2": glin_hit,
                "jev_verdict": verdict,
                "diagnosis": diagnosis,
            })
        needs[case["source"]] = need_solved
        rows.append({"case": case["source"], "spans": span_rows})

    total_needs = len(cases)
    solved_needs = sum(needs.values())

    # Task utility: how many needs reach RESOLVED under each pipeline.
    # (a) generator alone (gen_hit and JEV YES), (b) + GLiNER2.
    def needs_solved(use_gliner):
        count = 0
        for case, span_rows in zip(cases, [r["spans"] for r in rows]):
            ok = all(
                (s["generator"] or (use_gliner and s["gliner2"]))
                and s["jev_verdict"] == "YES"
                for s in span_rows
            )
            if ok:
                count += 1
        return count

    util_base = needs_solved(False)
    util_plus = needs_solved(True)

    print(f"utmaningsset: {len(cases)} klausuler, {unique_recall['total_gold']} guldspann")
    print(f"\n1. unik kandidat-recall: GLiNER2 hittade {unique_recall['found_by_gliner_only']} "
          f"korrekta spann som generatorn missar (av {unique_recall['total_gold']})")
    print(f"2. verifieringsöverlevnad: {survival['unique_verified']}/{survival['unique_total']} "
          f"unika spann godkända av JEV")
    print(f"3. faktisk uppgiftsnytta: {util_base}/{total_needs} behov lösta med generatorn, "
          f"{util_plus}/{total_needs} med GLiNER2 tillagd")
    gap_counts = {}
    for r in rows:
        for s in r["spans"]:
            gap_counts[s["diagnosis"]] = gap_counts.get(s["diagnosis"], 0) + 1
    print(f"\ndiagnos per guldspann: {gap_counts}")

    json.dump({
        "unique_recall": unique_recall,
        "survival": survival,
        "task_utility": {"generator_only": util_base, "with_gliner2": util_plus,
                         "total_needs": total_needs},
        "gap_counts": gap_counts,
        "cases": rows,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
