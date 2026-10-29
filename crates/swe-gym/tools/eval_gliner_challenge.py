#!/usr/bin/env python3
"""Challenge evaluation v2 (docs/architecture/gliner2-jevspan-evaluation
.md, D4): unique case_id/span_id identities, JEV raw results FROZEN to a
fixture (candidate, clause, prompt, model, verdict, score, timestamp) so
evaluations can be recomputed deterministically without paying for the
same verification twice. Verifies ALL GLiNER2 candidates — positive and
negative — so JEV's false-approval rate is measured, not assumed.
Compares the two strategies (GLiNER2 everywhere vs only at remaining
REQUIRED gaps) with cost per additional solved need.

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_gliner_challenge.py
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

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
OUT = B / "gliner_challenge_eval.json"

PROMPT_VERSION = "span-verify-v1"
JEV_COST = 1_000  # one coin per verification call

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}


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


def verification_prompt(clause, span):
    return (
        f"Utgör det exakta spannet '{span}' i klausulen ett juridiskt "
        "sakförhållande (tidsfrist, ersättning, villkor, begränsning, "
        "undantag, belopp, datum eller part)? Bedöm enbart spannet."
    )


def fixture_key(case_id, span, prompt_version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{prompt_version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


class JevRecorder:
    """Freeze every JEV verification result; replay on exact key hit."""

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

    def verify(self, case_id, clause, span):
        key = fixture_key(case_id, span, PROMPT_VERSION)
        if key in self.store:
            entry = self.store[key]
            return entry["choice"], entry["score_bp"], False
        body = json.dumps({
            "model": self.model,
            "state": {"text": clause},
            "questions": {
                "evidence": {
                    "type": "choice",
                    "instructions": verification_prompt(clause, span),
                    "criteria": {
                        "YES": "Spannet utgör exakt ett juridiskt sakförhållande.",
                        "NO": "Spannet utgör inte ett juridiskt sakförhållande.",
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
            "prompt_version": PROMPT_VERSION,
            "model": self.model,
            "choice": row.get("choice"),
            "score_bp": row.get("score_bp"),
            "ts": int(time.time()),
        }
        self.store[key] = entry
        self.new_calls += 1
        return entry["choice"], entry["score_bp"], True

    def save(self):
        data = {"version": 1, "entries": sorted(self.store.values(), key=lambda e: e["key"])}
        json.dump(data, open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]
    # Regression: unique identities — fail loudly, never silently merge.
    case_ids = [c["case_id"] for c in cases]
    assert len(set(case_ids)) == len(cases) == 50, "case_id måste vara unika"
    span_ids = [g["span_id"] for c in cases for g in c["gold"]]
    assert len(set(span_ids)) == len(span_ids), "span_id måste vara unika"

    from gliner2 import AutoExtractor
    extractor = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")
    recorder = JevRecorder(api_key, base, model)

    # Phase 1: run GLiNER2 everywhere, capture all candidates (for the
    # two-strategy comparison and the negative-candidate measurement).
    gliner_candidates = {}  # case_id -> {normalized span: raw span}
    for case in cases:
        gold_types = {g["type"] for g in case["gold"]}
        labels = [NEED_LABELS[t] for t in gold_types][:3]
        raw = extractor.extract_entities(case["clause"], entity_types=labels,
                                         threshold=0.3, format_results=False)
        cands = {}
        for entry in raw.get("entities", []):
            for label, spans in entry.items():
                for span in spans:
                    cands.setdefault(normalize(span), span)
        gliner_candidates[case["case_id"]] = cands

    # Phase 2: verify every GLiNER2 candidate (positive AND negative)
    # plus every gold span, frozen to the fixture.
    approved = {}  # case_id -> set of approved spans (normalized)
    for case in cases:
        cid = case["case_id"]
        approved[cid] = set()
        spans_to_verify = set(gliner_candidates[cid].values())
        for g in case["gold"]:
            spans_to_verify.add(g["span"])
        for span in spans_to_verify:
            choice, score, is_new = recorder.verify(cid, case["clause"], span)
            if choice == "YES":
                approved[cid].add(normalize(span))
    recorder.save()
    print(f"JEV-verifikationer: {recorder.new_calls} nya (resten återanvända från {FIXTURE.name})")

    # Three measurements with unique identities.
    unique_total = 0
    unique_survived = 0
    needs = {}  # case_id -> solved?
    for case in cases:
        cid = case["case_id"]
        det = {normalize(s) for _, s in spans_of(case["clause"])}
        gold = {normalize(g["span"]): g["span_id"] for g in case["gold"]}
        solved = True
        for gold_span, span_id in gold.items():
            gen_hit = gold_span in det
            glin_hit = gold_span in gliner_candidates[cid]
            if glin_hit and not gen_hit:
                unique_total += 1
                if gold_span in approved[cid]:
                    unique_survived += 1
            if gold_span not in approved[cid]:
                solved = False
        needs[cid] = solved

    # JEV false-approval rate: approvals of non-gold GLiNER2 spans.
    fa = 0
    fa_total = 0
    for case in cases:
        cid = case["case_id"]
        gold = {normalize(g["span"]) for g in case["gold"]}
        for span in approved[cid]:
            if span not in gold:
                fa_total += 1
                if span in gliner_candidates[cid]:
                    fa += 1
    print(f"\n1. unik kandidat-recall (verifierad): {unique_survived}/{unique_total}")
    print(f"2. JEV falskt-godkända GLiNER2-kandidater: {fa} (av {fa_total} godkända icke-guldspann)")
    print(f"3. uppgiftsnytta: {sum(needs.values())}/50 behov lösta (hybrid)")

    # Two strategies: S1 = GLiNER2 everywhere; S2 = only at remaining gaps.
    s1_needs = 0
    s2_needs = 0
    s1_gliner_runs = 0
    s2_gliner_runs = 0
    s1_jev = 0
    s2_jev = 0
    for case in cases:
        cid = case["case_id"]
        gold = {normalize(g["span"]) for g in case["gold"]}
        det = {normalize(s) for _, s in spans_of(case["clause"])}
        gap = any(gs not in det for gs in gold)
        s1_gliner_runs += 1
        s1_jev += len(gliner_candidates[cid]) + len(gold)
        if all(gs in approved[cid] for gs in gold):
            s1_needs += 1
        if gap:
            s2_gliner_runs += 1
            s2_jev += len(gliner_candidates[cid]) + len(gold)
            if all(gs in approved[cid] for gs in gold):
                s2_needs += 1
        else:
            if all(gs in approved[cid] for gs in gold):
                s2_needs += 1
    print(f"\nstrategier:")
    print(f"  S1 GLiNER2 överallt: {s1_needs}/50 behov, {s1_gliner_runs} inferenser, "
          f"{s1_jev} JEV-anrop")
    print(f"  S2 GLiNER2 vid gap:  {s2_needs}/50 behov, {s2_gliner_runs} inferenser, "
          f"{s2_jev} JEV-anrop")

    base_needs = sum(
        1 for case in cases
        if all(normalize(g["span"]) in {normalize(s) for _, s in spans_of(case["clause"])}
               and normalize(g["span"]) in approved[case["case_id"]]
               for g in case["gold"])
    )
    delta = s2_needs - base_needs
    print(f"  baslinje (generator+JEV): {base_needs}/50 behov")
    print(f"  kostnad per ytterligare löst behov (S2): "
          f"{s2_gliner_runs} inferenser + {s2_jev} JEV-anrop för {delta} extra behov")

    json.dump({
        "unique_verified": unique_survived,
        "unique_total": unique_total,
        "jev_false_approvals": fa,
        "needs_solved": sum(needs.values()),
        "strategies": {
            "baseline": base_needs,
            "s1": {"needs": s1_needs, "gliner_runs": s1_gliner_runs, "jev_calls": s1_jev},
            "s2": {"needs": s2_needs, "gliner_runs": s2_gliner_runs, "jev_calls": s2_jev},
        },
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
