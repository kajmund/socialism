#!/usr/bin/env python3
"""The verification arms (docs/architecture/gliner2-jevspan-evaluation
.md, D5): A generic / B need-specific / C need-specific with clause
context / D need-specific with CONTRASTIVE rules — all over the same
frozen candidate population, only the prompt changes. New prompt
versions add entries to the JEV fixture (the generic arm's answers are
replayed). Measures recall on the unique findings, FP rate on hard
negatives, precision, False Resolution Rate, solved needs and the S2
cost — on the WHOLE candidate population.

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_verification_arms.py
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_gliner_testset import spans_of  # noqa: E402
from eval_gliner_challenge import env_value, normalize  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
CANDIDATES = B / "gliner_candidates.json"
OUT = B / "verification_arms.json"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}

# General contrast rules per concept type — not written for specific
# golden cases, but for the concept class.
CONTRASTS = {
    "Uppsägningstid": "En uppsägningstid är inte samma sak som avtalstid, förlängningsperiod eller betalningsfrist.",
    "Avgångsvederlag": "Ett avgångsvederlag är inte samma sak som lön, pension eller skadestånd.",
    "Ersättning": "En ersättningsrätt är inte samma sak som lön, arvode eller skadestånd.",
    "Uppsägningsvillkor": "Ett uppsägningsvillkor är inte samma sak som uppsägningstid, avtalstid eller partsbeskrivning.",
    "Förlängning": "En förlängningsperiod är inte samma sak som uppsägningstid, avtalstid eller betalningsfrist.",
    "Vite": "Ett vite är inte samma sak som pris, avgift eller skadestånd.",
    "Ansvarstak": "Ett ansvarstak är inte samma sak som vite, garanti eller försäkringsskydd.",
    "Undantag": "Ett undantag är inte samma sak som en skyldighet, en definition eller en hänvisning.",
    "Avtalspart": "En avtalspart är inte samma sak som en roll, en titel eller en adress.",
    "Belopp": "Ett belopp är inte samma sak som ett datum, en procentsats eller ett antal.",
    "Datum": "Ett datum är inte samma sak som en tidsperiod, en tidsfrist eller en ålder.",
    "Tidsperiod": "En tidsperiod är inte samma sak som ett datum, en tidsfrist eller en ålder.",
}

ARMS = {
    "A_generell": {
        "version": "span-verify-v1",
        "prompt": lambda clause, span, need, heading: (
            f"Utgör det exakta spannet '{span}' i klausulen ett juridiskt "
            "sakförhållande (tidsfrist, ersättning, villkor, begränsning, "
            "undantag, belopp, datum eller part)? Bedöm enbart spannet."
        ),
    },
    "B_behovsspecifik": {
        "version": "span-need-v1",
        "prompt": lambda clause, span, need, heading: (
            f"Utgör det exakta spannet '{span}' ett {need} för det angivna avtalet?"
        ),
    },
    "C_behovsspecifik_kontext": {
        "version": "span-need-ctx-v1",
        "prompt": lambda clause, span, need, heading: (
            f"Anger detta spann '{span}', läst tillsammans med klausulens rubrik "
            f"'{heading}' och omgivande text, ett {need}?"
        ),
    },
    "D_behovsspecifik_kontrast": {
        "version": "span-need-contrast-v1",
        "prompt": lambda clause, span, need, heading: (
            f"Utgör det exakta spannet '{span}' ett {need} för det angivna avtalet? "
            f"{CONTRASTS.get(need, 'Bedöm enbart spannet.')}"
        ),
    },
}


def fixture_key(case_id, span, prompt_version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{prompt_version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


class JevRecorder:
    def __init__(self, api_key, base, model):
        self.api_key = api_key
        self.base = base
        self.model = model
        self.store = {}
        self.new_calls = 0
        if FIXTURE.exists():
            data = json.load(open(FIXTURE, encoding="utf-8"))
            for entry in data.get("entries", []):
                self.store[entry["key"]] = entry

    def verify(self, case_id, clause, span, version, instructions):
        key = fixture_key(case_id, span, version)
        if key in self.store:
            entry = self.store[key]
            return entry["choice"], False
        body = json.dumps({
            "model": self.model,
            "state": {"text": clause},
            "questions": {
                "evidence": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": {
                        "YES": "Spannet utgör exakt det efterfrågade sakförhållandet.",
                        "NO": "Spannet utgör inte det efterfrågade sakförhållandet.",
                        "UNCERTAIN": "Går inte att avgöra.",
                    },
                }
            },
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        row = payload["answers"]["evidence"]
        entry = {
            "key": key,
            "case_id": case_id,
            "span": span,
            "clause": clause,
            "prompt_version": version,
            "model": self.model,
            "choice": row.get("choice"),
            "score_bp": row.get("score_bp"),
            "ts": int(time.time()),
        }
        self.store[key] = entry
        self.new_calls += 1
        return entry["choice"], True

    def save(self):
        data = {"version": 1, "entries": sorted(self.store.values(), key=lambda e: e["key"])}
        json.dump(data, open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def hard_distractors(case, gold_norm):
    """Hard negatives: same-clause spans of a nearby but WRONG concept —
    the confusion class the user described (notice period vs renewal)."""
    out = []
    # The deterministic generator's spans that are NOT gold, same clause:
    det = [(t, normalize(s)) for t, s in spans_of(case["clause"])]
    for t, s in det:
        if s not in gold_norm:
            out.append(s)
    return out


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]

    # Frozen candidate population: GLiNER2 candidates (regenerate once,
    # then frozen) + gold spans + hard-negative distractors.
    from gliner2 import AutoExtractor
    extractor = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")
    population = {}
    if CANDIDATES.exists():
        pop_data = json.load(open(CANDIDATES, encoding="utf-8"))
        for case in cases:
            population[case["case_id"]] = set(pop_data[case["case_id"]])
    else:
        pop_data = {}
        for case in cases:
            labels = [NEED_LABELS[t] for t in {g["type"] for g in case["gold"]}][:3]
            raw = extractor.extract_entities(case["clause"], entity_types=labels,
                                             threshold=0.3, format_results=False)
            spans = set()
            for entry in raw.get("entities", []):
                for label, ss in entry.items():
                    for span in ss:
                        spans.add(normalize(span))
            for g in case["gold"]:
                spans.add(normalize(g["span"]))
            for d in hard_distractors(case, {normalize(g["span"]) for g in case["gold"]}):
                spans.add(d)
            population[case["case_id"]] = spans
            pop_data[case["case_id"]] = sorted(spans)
        json.dump(pop_data, open(CANDIDATES, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"kandidatpopulation fryst: {sum(len(v) for v in population.values())} spann")

    # Raw spans per case (for the JEV calls we need the raw text).
    raw_spans = {}
    for case in cases:
        cid = case["case_id"]
        clause_norm = {normalize(g["span"]): g["span"] for g in case["gold"]}
        for t, s in spans_of(case["clause"]):
            clause_norm.setdefault(normalize(s), s)
        raw_spans[cid] = clause_norm

    recorder = JevRecorder(api_key, base, model)
    results = {}
    for arm_name, arm in ARMS.items():
        verdicts = {}  # case_id -> {span_norm: choice}
        for case in cases:
            cid = case["case_id"]
            need_sv = NEED_LABELS[case["need"]]
            heading = case["clause"].splitlines()[0][:60] if case["clause"] else ""
            verdicts[cid] = {}
            for span_norm in population[cid]:
                raw_span = raw_spans[cid].get(span_norm, span_norm)
                instructions = arm["prompt"](case["clause"], raw_span, need_sv, heading)
                choice, is_new = recorder.verify(
                    cid, case["clause"], raw_span, arm["version"], instructions
                )
                verdicts[cid][span_norm] = choice
        recorder.save()

        # Metrics over the whole population.
        gold = {
            c["case_id"]: {normalize(g["span"]): g["span_id"] for g in c["gold"]}
            for c in cases
        }
        unique_verified = 0
        unique_total = 0
        fp = 0
        tp = 0
        frr_needs = 0
        solved = 0
        for case in cases:
            cid = case["case_id"]
            det = {normalize(s) for _, s in spans_of(case["clause"])}
            g = gold[cid]
            all_gold_ok = True
            for gs in g:
                if gs in det:
                    continue  # generator span: counted in tp/fp below
                unique_total += 1
                if verdicts[cid].get(gs) == "YES":
                    unique_verified += 1
                    tp += 1
                else:
                    all_gold_ok = False
            if not all_gold_ok:
                continue
            solved += 1
            # FRR: the need is deemed resolved, but the verifier also
            # approved same-clause distractor spans of a WRONG type.
            wrong_approved = any(
                v == "YES" and s not in g
                for s, v in verdicts[cid].items()
            )
            if wrong_approved:
                frr_needs += 1
            for s, v in verdicts[cid].items():
                if v == "YES" and s not in g:
                    fp += 1
                if v == "YES" and s in g:
                    tp += 1
        prec = tp / (tp + fp) if tp + fp else 0.0
        results[arm_name] = {
            "unique_recall": f"{unique_verified}/{unique_total}",
            "false_positives": fp,
            "precision": round(prec, 3),
            "frr_needs": frr_needs,
            "solved_needs": solved,
        }
        print(f"{arm_name:<30} unik {unique_verified}/{unique_total}  fp {fp:>3}  "
              f"prec {prec:.2f}  FRR {frr_needs:>2}  lösta {solved}/50  "
              f"({recorder.new_calls} nya anrop hittills)")
    recorder.save()
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
