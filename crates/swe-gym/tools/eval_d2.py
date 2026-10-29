#!/usr/bin/env python3
"""D vs D2 paired run (docs/architecture/gliner2-jevspan-evaluation.md,
D12): the same candidates, clause context and one-JEV-call budget —
only the question changes. D = 'supports the information need?';
D2 = 'states the ACTUAL value/commitment the operation needs, given
conditions and context?'. All answers frozen by prompt version.

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_d2.py
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_gliner_challenge import env_value, normalize  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
CANDIDATES_V2 = B / "gliner_candidates_v2.json"
OUT = B / "d2_comparison.json"

D2_VERSION = "span-operative-role-v1"
D_VERSION = "span-need-contrast-v1"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}
CONTRASTS = {
    "Uppsägningstid": "En uppsägningstid är inte samma sak som avtalstid, förlängningsperiod eller betalningsfrist.",
    "Förlängning": "En förlängningsperiod är inte samma sak som uppsägningstid eller avtalstid.",
}


def canonical(s):
    return re.sub(r"[\[\]]", "", normalize(s))


def fixture_key(case_id, span, version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


class Recorder:
    def __init__(self, api_key, base, model):
        self.api_key = api_key
        self.base = base
        self.model = model
        self.store = {}
        self.new = 0
        data = json.load(open(FIXTURE, encoding="utf-8"))
        for e in data["entries"]:
            self.store[e["key"]] = e

    def ask(self, cid, clause, span, version, instructions):
        key = fixture_key(cid, span, version)
        if key in self.store:
            return self.store[key]["choice"], False
        body = json.dumps({
            "model": self.model,
            "state": {"text": clause},
            "questions": {"evidence": {
                "type": "choice",
                "instructions": instructions,
                "criteria": {
                    "YES": "Spannet anger det efterfrågade värdet eller åtagandet.",
                    "NO": "Spannet anger inte det efterfrågade värdet eller åtagandet.",
                    "UNCERTAIN": "Går inte att avgöra.",
                },
            }},
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            row = json.loads(resp.read().decode("utf-8"))["answers"]["evidence"]
        self.store[key] = {"key": key, "case_id": cid, "span": span, "clause": clause,
                           "prompt_version": version, "model": self.model,
                           "choice": row.get("choice"), "score_bp": row.get("score_bp"),
                           "ts": int(time.time())}
        self.new += 1
        return self.store[key]["choice"], True

    def save(self):
        data = {"version": 1, "entries": sorted(self.store.values(), key=lambda e: e["key"])}
        json.dump(data, open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")
    cases = {c["case_id"]: c for c in json.load(open(CHALLENGE, encoding="utf-8"))["cases"]}
    pop = json.load(open(CANDIDATES_V2, encoding="utf-8"))
    rec = Recorder(api_key, base, model)

    for cid, case in cases.items():
        need = NEED_LABELS[case["need"]]
        contrast = CONTRASTS.get(need, "Bedöm enbart spannet.")
        for s, info in pop[cid].items():
            span = info["raw"]
            instructions = (
                f"Anger detta spann '{span}' det faktiska värde eller åtagande som "
                f"behovet '{need}' kräver för den aktuella operationen, med hänsyn "
                f"till villkor och sammanhang? {contrast}"
            )
            rec.ask(cid, case["clause"], span, D2_VERSION, instructions)
    rec.save()
    print(f"D2 fångad: {rec.new} nya anrop (version {D2_VERSION})")

    # The comparison: per-case conclusions under D vs D2, same counting.
    def evaluate(version):
        correct = wrong = abstained = 0
        trans = {}
        for cid, case in cases.items():
            gold = [canonical(g["span"]) for g in case["gold"]]
            approved = [canonical(info["raw"]) for s, info in pop[cid].items()
                        if rec.store.get(fixture_key(cid, info["raw"], version), {}).get("choice") == "YES"]
            resolved = all(g in approved for g in gold) if gold else True
            wrong_ev = [a for a in approved if a not in set(gold)]
            if not resolved:
                outcome = "avstod"
            elif wrong_ev:
                outcome = "kontaminerad"
            else:
                outcome = "korrekt"
            trans.setdefault(outcome, []).append(cid)
            if outcome == "korrekt": correct += 1
            elif outcome == "kontaminerad": wrong += 1
            else: abstained += 1
        return correct, wrong, abstained, trans

    d = evaluate(D_VERSION)
    d2 = evaluate(D2_VERSION)
    print(f"\nD  (nuvarande): korrekt {d[0]}, kontaminerad {d[1]}, avstod {d[2]}")
    print(f"D2 (operativ roll): korrekt {d2[0]}, kontaminerad {d2[1]}, avstod {d2[2]}")
    print(f"\nförändring: kontaminerade {d[1]} -> {d2[1]}, korrekta {d[0]} -> {d2[0]}, avstod {d[2]} -> {d2[2]}")
    json.dump({"D": {"correct": d[0], "contaminated": d[1], "abstained": d[2]},
               "D2": {"correct": d2[0], "contaminated": d2[1], "abstained": d2[2]},
               "D_cases": d[3], "D2_cases": d2[3]},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
