#!/usr/bin/env python3
"""Generalization blind test — the frozen GLiNER2/JEV combination on NEW
documents (docs/architecture/gliner2-generalization-protocol.md).

Frozen implementation (must not change during the test):
  - deterministic extractor: gen_gliner_testset.spans_of
  - GLiNER2: fastino/gliner2.5-multi-v1, threshold 0.3, CPU, isolated venv,
    need-driven label specs (labels from the case's `needs`, never from gold)
  - JEV: prompt arm D `span-need-contrast-v1` (need-specific + contrast rules)
  - contract: canonical span normalization (all brackets removed), type check
    on extractor spans, AMBIGUOUS derived from competing approved/extracted
    spans of the same operational role (never RESOLVED)

Strategies (same cost definition, all calls counted):
  - baseline: deterministic extractor + JEV on gold candidates
  - S1: GLiNER2 everywhere + JEV on all candidates and gold
  - S2 (frozen choice): GLiNER2 only where a REQUIRED gap remains after the
    extractor + JEV on all candidates and gold

Metrics (per protocol, per legal question type):
  1. unique candidate coverage (generator misses, GLiNER2 finds) + JEV survival
  2. solved needs (hybrid, S2)
  3. false RESOLVED per unique need_id (approved wrong-value span of the need's
     type when the gold value is absent; AMBIGUOUS needs are never RESOLVED)
  4. cost per additional solved need (S2 vs baseline; GLiNER2 inferences and
     JEV calls both counted, frozen in the fixture)
  Answer-level correctness (contamination follow-through) is NOT measured at
  clause level — it is the follow-up step after this run, as in D10.

Facit schema (gold-review-v3 procedure: annotated by READING the text,
independent of the regex generator and GLiNER2; provenance recorded):

{
  "version": 1,
  "name": "blindtest-<...>",
  "provenance": "who annotated, when, how independence was kept",
  "cases": [
    {
      "case_id": "bt-01",
      "document": "human-readable source reference",
      "clause": "raw clause text",
      "question_type": "uppsägningsvillkor",
      "needs": [{"need_id": "bt-01-n1", "type": "NOTICE_PERIOD"}],
      "gold": [{"span_id": "bt-01-s1", "type": "NOTICE_PERIOD", "span": "exact span"}]
    }
  ]
}

Run (isolated venv, no production impact):
  /tmp/gliner_venv/bin/python crates/swe-gym/tools/run_blindtest.py \
      --facit benchmarks/blindtest_<name>.json \
      [--candidates benchmarks/gliner_candidates.json]  # plumbing reuse only

First run is the honest generalization measurement: no adjustments during
the test. Improvements become a new, separate experiment.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_gliner_testset import spans_of  # noqa: E402
from eval_verification_arms import CONTRASTS  # noqa: E402
from eval_gliner_challenge import env_value  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
FIXTURE = B / "jev_span_fixtures.json"
PROMPT_VERSION = "span-need-contrast-v1"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def canon(s: str) -> str:
    """Canonical span normalization: all brackets removed, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip().lower()


def fixture_key(case_id, span, prompt_version):
    # Same keying as the frozen D4/D5 fixture (normalize, not canon), so
    # existing entries replay exactly.
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{prompt_version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


def arm_d_instructions(need_type: str, span: str) -> str:
    need = NEED_LABELS.get(need_type, need_type)
    return (
        f"Utgör det exakta spannet '{span}' ett {need} för det angivna avtalet? "
        f"{CONTRASTS.get(need, 'Bedöm enbart spannet.')}"
    )


class JevRecorder:
    """Freeze every JEV answer; replay on exact key hit (same as D4/D5)."""

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

    def verify(self, case_id, clause, span, need_type):
        key = fixture_key(case_id, span, PROMPT_VERSION)
        if key in self.store:
            return self.store[key]["choice"], False
        body = json.dumps({
            "model": self.model,
            "state": {"text": clause},
            "questions": {
                "evidence": {
                    "type": "choice",
                    "instructions": arm_d_instructions(need_type, span),
                    "criteria": {
                        "YES": "Spannet utgör exakt det efterfrågade sakförhållandet.",
                        "NO": "Spannet utgör inte det efterfrågade sakförhållandet.",
                        "UNCERTAIN": "Går inte att avgöra.",
                    },
                }
            },
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone", data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        row = payload["answers"]["evidence"]
        entry = {
            "key": key, "case_id": case_id, "span": span, "clause": clause,
            "prompt_version": PROMPT_VERSION, "model": self.model,
            "choice": row.get("choice"), "score_bp": row.get("score_bp"),
            "ts": int(time.time()),
        }
        self.store[key] = entry
        self.new_calls += 1
        return entry["choice"], True

    def save(self):
        data = {"version": 1, "entries": sorted(self.store.values(), key=lambda e: e["key"])}
        json.dump(data, open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_candidates(path):
    """case_id -> set of canonical candidate spans (frozen plumbing reuse)."""
    d = json.load(open(path, encoding="utf-8"))
    return {cid: {canon(s) for s in spans} for cid, spans in d.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facit", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--candidates", default=None,
                    help="reuse a frozen candidates file (plumbing only)")
    args = ap.parse_args()

    facit = json.load(open(args.facit, encoding="utf-8"))
    cases = facit["cases"]
    case_ids = [c["case_id"] for c in cases]
    assert len(set(case_ids)) == len(cases), "case_id måste vara unika"
    for c in cases:
        assert "needs" in c and c["needs"], f"{c['case_id']} saknar needs"
        span_ids = [g["span_id"] for g in c["gold"]]
        assert len(set(span_ids)) == len(span_ids), "span_id måste vara unika"

    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    # Phase 1: GLiNER2 candidates, need-driven labels from the QUESTION
    # (needs), never from gold.
    frozen_candidates = load_candidates(args.candidates) if args.candidates else {}
    gliner_candidates = {}
    s1_runs = 0
    if args.candidates:
        for c in cases:
            gliner_candidates[c["case_id"]] = set(frozen_candidates.get(c["case_id"], set()))
    else:
        from gliner2 import AutoExtractor
        extractor = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")
        for c in cases:
            labels = [NEED_LABELS[n["type"]] for n in c["needs"] if n["type"] in NEED_LABELS]
            raw = extractor.extract_entities(c["clause"], entity_types=labels[:3],
                                             threshold=0.3, format_results=False)
            cands = set()
            for entry in raw.get("entities", []):
                for _, spans in entry.items():
                    for span in spans:
                        cands.add(canon(span))
            gliner_candidates[c["case_id"]] = cands
            s1_runs += 1

    # Phase 2: JEV arm D on every GLiNER2 candidate plus every gold span
    # (gold verified against its own type; candidates against the primary need).
    recorder = JevRecorder(api_key, base, model)
    approved = {}  # case_id -> set of canonical approved spans
    for c in cases:
        cid = c["case_id"]
        approved[cid] = set()
        primary_type = c["needs"][0]["type"]
        for span in gliner_candidates[cid]:
            choice, _ = recorder.verify(cid, c["clause"], span, primary_type)
            if choice == "YES":
                approved[cid].add(span)
        for g in c["gold"]:
            span = canon(g["span"])
            choice, _ = recorder.verify(cid, c["clause"], span, g["type"])
            if choice == "YES":
                approved[cid].add(span)
    recorder.save()
    print(f"JEV: {recorder.new_calls} nya anrop (övriga återspelade från {FIXTURE.name})")

    # Phase 3: contract + metrics, per need and per question type.
    per_type = {}
    per_case = []
    unique_seen = set()
    unique_total = unique_survived = 0
    solved_needs = 0
    false_resolved = []  # need_ids
    ambiguous = []  # need_ids
    base_needs = s1_needs = s2_needs = 0
    s1_jev = s2_jev = 0
    s2_runs = 0

    for c in cases:
        cid = c["case_id"]
        qt = c.get("question_type", "okänd")
        per_type.setdefault(qt, {"unique_total": 0, "unique_survived": 0,
                                 "needs": 0, "solved": 0, "false_resolved": 0})
        det = {(label, canon(s)) for label, s in spans_of(c["clause"])}
        det_by_type = {}
        for label, s in det:
            det_by_type.setdefault(label, set()).add(s)
        gold_by_type = {}
        for g in c["gold"]:
            gold_by_type.setdefault(g["type"], set()).add(canon(g["span"]))
        glin = gliner_candidates[cid]

        # Unique coverage: per gold span the extractor missed (counted once).
        for g in c["gold"]:
            gs = canon(g["span"])
            key = (cid, g["span_id"])
            if key in unique_seen:
                continue
            unique_seen.add(key)
            if gs in glin and gs not in det_by_type.get(g["type"], set()):
                unique_total += 1
                per_type[qt]["unique_total"] += 1
                if gs in approved[cid]:
                    unique_survived += 1
                    per_type[qt]["unique_survived"] += 1

        for n in c["needs"]:
            nt = n["type"]
            need_id = n["need_id"]
            gold = gold_by_type.get(nt, set())
            extracted = det_by_type.get(nt, set())
            per_type[qt]["needs"] += 1
            gap = any(gs not in extracted for gs in gold)

            # Contract: RESOLVED only from the gold value itself (JEV-verified
            # or extractor type-checked); competing same-role spans make the
            # need AMBIGUOUS instead of RESOLVED (D11/D12 semantics).
            resolved = bool(gold) and all(
                gs in approved[cid] or gs in extracted for gs in gold)
            competing = {s for s in approved[cid] if s in glin and s not in gold}
            competing |= {s for s in extracted if s not in gold}
            verdict = "resolved"
            if resolved and len(competing) >= 2:
                resolved = False
                ambiguous.append(need_id)
                verdict = "ambiguous"
            elif resolved:
                solved_needs += 1
                per_type[qt]["solved"] += 1
            elif len(competing) >= 2:
                ambiguous.append(need_id)
                verdict = "ambiguous"
            elif competing:
                false_resolved.append(need_id)
                per_type[qt]["false_resolved"] += 1
                verdict = "false_resolved"
            else:
                verdict = "unsolved"
            per_case.append({
                "case_id": cid, "need_id": need_id, "question_type": qt,
                "verdict": verdict,
                "gold": sorted(gold),
                "gliner_candidates": sorted(glin),
                "approved": sorted(approved[cid]),
                "extracted_same_type": sorted(extracted),
                "competing": sorted(competing),
            })

            # Strategy accounting (same resolution, all calls counted).
            s1_jev += len(glin) + len(gold)
            if resolved:
                s1_needs += 1
            if gap:
                s2_runs += 1
                s2_jev += len(glin) + len(gold)
                if resolved:
                    s2_needs += 1
            else:
                if resolved:
                    s2_needs += 1
            if bool(gold) and all(gs in extracted for gs in gold) and \
                    all(gs in approved[cid] for gs in gold):
                base_needs += 1

    total = sum(m["needs"] for m in per_type.values())
    print(f"\n1. unik kandidattäckning (verifierad): {unique_survived}/{unique_total}")
    print(f"2. lösta behov (S2): {s2_needs}/{total}")
    print(f"3. falskt RESOLVED per need_id: {len(false_resolved)} "
          f"{false_resolved[:10]} — AMBIGUOUS: {len(ambiguous)}")
    delta = s2_needs - base_needs
    print(f"\nstrategier:")
    print(f"  baslinje (extraktor+JEV): {base_needs}/{total}")
    print(f"  S1 GLiNER2 överallt: {s1_needs}/{total}, {s1_runs} inferenser, {s1_jev} JEV")
    print(f"  S2 GLiNER2 vid gap:   {s2_needs}/{total}, {s2_runs} inferenser, {s2_jev} JEV")
    print(f"  kostnad per ytterligare löst behov (S2): "
          f"{s2_runs} inferenser + {s2_jev} JEV för {delta} extra behov")
    print(f"\nper frågetyp:")
    for qt, m in sorted(per_type.items()):
        print(f"  {qt}: unik {m['unique_survived']}/{m['unique_total']}, "
              f"lösta {m['solved']}/{m['needs']}, falskt RESOLVED {m['false_resolved']}")

    out = args.out or str(Path(args.facit).with_suffix("")) + "_eval.json"
    cand_out = str(Path(args.facit).with_suffix("")) + "_candidates.json"
    json.dump({cid: sorted(spans) for cid, spans in gliner_candidates.items()},
              open(cand_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({
        "facit": str(args.facit),
        "facit_provenance": facit.get("provenance"),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "candidates_reused": args.candidates is not None,
        "unique_verified": unique_survived,
        "unique_total": unique_total,
        "false_resolved_need_ids": false_resolved,
        "ambiguous_need_ids": ambiguous,
        "needs_total": total,
        "needs_solved_s2": s2_needs,
        "strategies": {
            "baseline": {"needs": base_needs},
            "s1": {"needs": s1_needs, "gliner_runs": s1_runs, "jev_calls": s1_jev},
            "s2": {"needs": s2_needs, "gliner_runs": s2_runs, "jev_calls": s2_jev},
        },
        "per_question_type": per_type,
        "per_case": per_case,
        "jev_new_calls": recorder.new_calls,
        "scope_note": ("answer-level contamination not measured at clause level; "
                       "follow-through step after this run (D10 procedure)"),
    }, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {out}")


if __name__ == "__main__":
    main()
