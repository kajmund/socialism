#!/usr/bin/env python3
"""Date-representation experiment (isolated, own version): a new date-specific
JEV prompt version `span-date-v1` that accepts partial dates and date
intervals WITHOUT a year — the representation never pads a year.

Frozen parts (unchanged): GLiNER2 model and its candidates (reused from
blindtest_facit_v1_candidates.json), JEV arm D for all non-date needs.
Changed (new version only): the verification question for DATE needs.

Only the four DATE cases of blindtest v1 run here (bt-02, bt-06, bt-07,
bt-18); bt-07/bt-18 are the regression controls (already solved by arm D —
they must stay solved). New JEV answers are frozen into
jev_span_fixtures.json under prompt_version `span-date-v1` (append-only;
the arm-D entries stay untouched).

Run: python3 crates/swe-gym/tools/exp_dates.py   (live JEV calls, env-gated)
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_gliner_challenge import env_value  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
FACIT = json.load(open(B / "blindtest_facit_v1.json", encoding="utf-8"))
CANDIDATES = json.load(open(B / "blindtest_facit_v1_candidates.json", encoding="utf-8"))
FIXTURE = B / "jev_span_fixtures.json"
PROMPT_VERSION = "span-date-v1"


def canon(s):
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip().lower()


def date_instructions(span):
    return (
        f"Utgör det exakta spannet '{span}' ett datum eller ett datumintervall — "
        "även utan årtal, som '12 maj' eller '10-11 juni'? Bedöm enbart spannet. "
        "Lägg inte till ett årtal som inte står i spannet."
    )


def fixture_key(case_id, span, version):
    d = hashlib.sha256(f"{case_id}\0{canon(span)}\0{version}".encode()).hexdigest()[:16]
    return d


class Recorder:
    def __init__(self, api_key, base, model):
        self.api_key, self.base, self.model = api_key, base, model
        self.store, self.new_calls = {}, 0
        data = json.load(open(FIXTURE, encoding="utf-8"))
        for e in data.get("entries", []):
            self.store[e["key"]] = e

    def verify(self, case_id, clause, span):
        key = fixture_key(case_id, span, PROMPT_VERSION)
        if key in self.store:
            return self.store[key]["choice"], False
        body = json.dumps({
            "model": self.model,
            "state": {"text": clause},
            "questions": {"evidence": {
                "type": "choice",
                "instructions": date_instructions(span),
                "criteria": {
                    "YES": "Spannet är ett datum eller datumintervall; årtal krävs inte.",
                    "NO": "Spannet är inget datum eller datumintervall.",
                    "UNCERTAIN": "Går inte att avgöra.",
                },
            }},
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        row = payload["answers"]["evidence"]
        entry = {"key": key, "case_id": case_id, "span": span, "clause": clause,
                 "prompt_version": PROMPT_VERSION, "model": self.model,
                 "choice": row.get("choice"), "score_bp": row.get("score_bp"),
                 "ts": int(time.time())}
        self.store[key] = entry
        self.new_calls += 1
        return entry["choice"], True

    def save(self):
        data = {"version": 1,
                "entries": sorted(self.store.values(), key=lambda e: e["key"])}
        json.dump(data, open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False,
                  indent=2)


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env",
                     "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    date_cases = [c for c in FACIT["cases"]
                  if any(n["type"] == "DATE" for n in c["needs"])]
    recorder = Recorder(api_key, base, model)
    rows = []
    for c in date_cases:
        cid = c["case_id"]
        gold = {canon(g["span"]) for g in c["gold"] if g["type"] == "DATE"}
        cands = {canon(s) for s in CANDIDATES.get(cid, [])}
        approved = set()
        for span in sorted(cands | gold):
            choice, _ = recorder.verify(cid, c["clause"], span)
            if choice == "YES":
                approved.add(span)
        solved = bool(gold) and all(g in approved for g in gold)
        rows.append({"case_id": cid, "solved": solved,
                     "gold": sorted(gold), "approved": sorted(approved)})
    recorder.save()
    print(f"JEV span-date-v1: {recorder.new_calls} nya anrop (frysta i fixturen)\n")
    for r in rows:
        print(f"  {r['case_id']}: {'löst' if r['solved'] else 'EJ löst'}  "
              f"gold={r['gold']} approved={r['approved']}")
    solved_n = sum(r["solved"] for r in rows)
    print(f"\ndatumfall lösta: {solved_n}/{len(rows)} "
          f"(frusen arm D löste 2/4: bt-07, bt-18)")
    out = B / "blindtest_date_v1.json"
    json.dump({"version": 1, "prompt_version": PROMPT_VERSION,
               "new_calls": recorder.new_calls, "rows": rows},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"skrivet: {out}")


if __name__ == "__main__":
    main()
