#!/usr/bin/env python3
"""Blindtest v2 — the FINAL frozen GLiNER2/JEV chain on NEW unseen contracts.

This measures the finished version that PR #448 integrates: the frozen
E1-E3 span contract (backend/app/services/research/gliner/contract.py,
imported read-only), the arm-D / span-date-v1 Jev prompts and the same
GLiNER2 model as blindtest v1 — on documents that v1, D10 and E1-E3 never
touched. The instrument is frozen BEFORE the first run; the first run is the
honest generalization measurement.

Strategies (same cost definition as v1, all calls counted):
  - baseline: deterministic extractor + Jev on gold spans
  - S1: GLiNER2 everywhere + the frozen contract
  - S2 (frozen choice): GLiNER2 only where a REQUIRED gap remains after the
    deterministic extractor, + the frozen contract

The committed facit/fixtures under benchmarks/ are REDACTED: the repository
is public, so no contract files, clause texts or span values are committed —
only SHA-256 digests, types and aggregated results. Running the test needs the
full facit and fixture kept locally outside the repository; never commit the
runnable full artifacts.

Run (isolated venv, against the LOCAL full facit):
  /tmp/gliner_venv/bin/python crates/swe-gym/tools/run_blindtest_v2.py \
      --facit /path/without/repo/blindtest_facit_v2.json [--selftest]
"""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))

from gen_gliner_testset import spans_of  # noqa: E402
from eval_gliner_challenge import env_value  # noqa: E402

# Load the frozen E1-E3 contract module by path: importing the backend package
# would pull SQLAlchemy etc. into the isolated inference venv, while the
# contract itself is stdlib-only (re + dataclasses).
_contract_path = (
    REPO / "backend" / "app" / "services" / "research" / "gliner" / "contract.py"
)
_spec = importlib.util.spec_from_file_location("frozen_gliner_contract", _contract_path)
contract = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = contract
_spec.loader.exec_module(contract)

AMBIGUOUS = contract.AMBIGUOUS
NEED_LABELS = contract.NEED_LABELS
SpanVerdict = contract.SpanVerdict
derive_findings = contract.derive_findings
operational_role = contract.operational_role
verification_question = contract.verification_question

B = REPO / "crates" / "swe-gym" / "benchmarks"
FIXTURE = B / "jev_span_fixtures_v2.json"
MODEL = "fastino/gliner2.5-multi-v1"
THRESHOLD = 0.3


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def canon(s: str) -> str:
    return contract.canon(s)


def canon_value(s: str) -> str:
    return contract.canon_value(s)


def fixture_key(case_id, span, prompt_version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{prompt_version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


class JevRecorder:
    """Freeze every Jev answer for the v2 chain; replay on exact key hit."""

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
        question = verification_question(need_type, span)
        version = question["prompt_version"]
        key = fixture_key(case_id, span, version)
        if key in self.store:
            return self.store[key]["choice"], version
        body = json.dumps(
            {
                "model": self.model,
                "state": {"text": clause},
                "questions": question["question"],
            },
            ensure_ascii=False,
        ).encode("utf-8")
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
        choice = str(row.get("choice") or "").upper()
        if choice not in {"YES", "NO", "UNCERTAIN"}:
            raise SystemExit(f"ogiltigt Jev-svar: {row!r}")
        entry = {
            "key": key,
            "case_id": case_id,
            "span": span,
            "clause": clause,
            "need_type": need_type,
            "prompt_version": version,
            "model": self.model,
            "choice": choice,
            "score_bp": row.get("score_bp"),
            "ts": int(time.time()),
        }
        self.store[key] = entry
        self.new_calls += 1
        return choice, version

    def save(self):
        data = {
            "version": 2,
            "entries": sorted(self.store.values(), key=lambda e: e["key"]),
        }
        json.dump(data, open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def verdicts_for(case, spans, recorder):
    """Jev-verify every span against the case's need type; frozen contract."""
    need = case["needs"][0]
    out = []
    for span in spans:
        choice, version = recorder.verify(case["case_id"], case["clause"], span, need["type"])
        out.append(
            SpanVerdict(
                span=span,
                need_type=need["type"],
                prompt_version=version,
                choice=choice,
                unit_id=case["case_id"],
                unit_text=case["clause"],
                role=operational_role(span, case["clause"]),
                role_locked=True,
            )
        )
    return derive_findings(out, need_type=need["type"], need_role=need.get("role") or "")


def outcome(findings, gold_values):
    """Map frozen-contract findings to the v1 metric vocabulary."""
    gold_values = set(gold_values)
    verified = {f.value for f in findings if f.state == "VERIFIED"}
    ambiguous = [f for f in findings if f.state == AMBIGUOUS]
    if ambiguous:
        return "ambiguous", verified
    if gold_values and gold_values <= verified and not (verified - gold_values):
        return "resolved", verified
    # False RESOLVED means a WRONG value was verified; an incomplete gold set
    # without a competing verified value is plain unsolved (v1 semantics).
    if verified - gold_values:
        return "false_resolved", verified
    return "unsolved", verified


def load_extractor():
    from gliner2 import AutoExtractor

    return AutoExtractor.from_pretrained(MODEL)


def gliner_candidates(extractor, clause, labels):
    raw = extractor.extract_entities(
        clause, entity_types=labels, threshold=THRESHOLD, format_results=False
    )
    spans = set()
    for entry in raw.get("entities", []):
        for _, found in entry.items():
            for span in found:
                spans.add(canon(span))
    return spans


def selftest():
    """Offline check of the metric mapping — no model, no network."""
    ContractFinding = contract.ContractFinding

    def finding(value, state):
        return ContractFinding(
            span=value, value=value, need_type="PERIOD", state=state
        )

    assert outcome([finding("30 dagar", "VERIFIED")], ["30 dagar"])[0] == "resolved"
    assert outcome([finding("30 dagar", "VERIFIED")], ["60 dagar"])[0] == "false_resolved"
    assert outcome([finding("30 dagar", AMBIGUOUS), finding("60 dagar", AMBIGUOUS)],
                   ["30 dagar"])[0] == "ambiguous"
    assert outcome([finding("30 dagar", "REJECTED")], ["30 dagar"])[0] == "unsolved"
    assert outcome([], ["30 dagar"])[0] == "unsolved"
    print("selftest: OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facit", default=str(B / "blindtest_facit_v2.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    facit = json.load(open(args.facit, encoding="utf-8"))
    cases = facit["cases"]
    assert all(len(c["needs"]) == 1 for c in cases), "v2-facit har exakt ett behov per fall"
    assert all(n["type"] in NEED_LABELS for c in cases for n in c["needs"])

    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")
    recorder = JevRecorder(api_key, base, model)

    det = {c["case_id"]: spans_of(c["clause"]) for c in cases}
    gold = {c["case_id"]: [canon(g["span"]) for g in c["gold"]] for c in cases}
    gold_values = {c["case_id"]: [canon_value(g["span"]) for g in c["gold"]] for c in cases}
    det_by_type = {}
    for c in cases:
        cid, need_type = c["case_id"], c["needs"][0]["type"]
        det_by_type[cid] = {
            canon(span) for label, span in det[cid] if label == need_type
        }

    # Phase 1: GLiNER2 candidates (all cases for S1; gap cases for S2).
    candidates = {}
    s1_runs = s2_runs = 0
    extractor = load_extractor()
    for c in cases:
        cid = c["case_id"]
        need = c["needs"][0]
        gap = any(g not in det_by_type[cid] for g in gold[cid])
        labels = [NEED_LABELS[need["type"]]]
        candidates[cid] = gliner_candidates(extractor, c["clause"], labels)
        s1_runs += 1
        if gap:
            s2_runs += 1

    # Phase 2: frozen contract on baseline gold, S1 and S2 verdict sets.
    per_case = []
    per_type = {}
    unique_total = unique_survived = 0
    baseline_solved = s1_solved = s2_solved = 0
    s1_jev = s2_jev = 0
    false_ids, ambiguous_ids = [], []
    for c in cases:
        cid = c["case_id"]
        need = c["needs"][0]
        qt = c.get("question_type", "okänd")
        per_type.setdefault(
            qt,
            {"unique_total": 0, "unique_survived": 0, "needs": 0,
             "solved": 0, "false_resolved": 0, "ambiguous": 0},
        )
        per_type[qt]["needs"] += 1
        gap_spans = [g for g in gold[cid] if g not in det_by_type[cid]]
        # baseline: extractor + Jev on gold only
        base_verdicts = verdicts_for(c, [g["span"] for g in c["gold"]], recorder)
        base_state, _ = outcome(base_verdicts, gold_values[cid])
        base_ok = base_state == "resolved" and not gap_spans
        if base_ok:
            baseline_solved += 1

        # S1: everything GLiNER2 proposes + gold
        all_spans = sorted({g["span"] for g in c["gold"]} | set(candidates[cid]))
        s1_verdicts = verdicts_for(c, all_spans, recorder)
        s1_state, s1_verified = outcome(s1_verdicts, gold_values[cid])
        s1_jev += len(all_spans)
        if s1_state == "resolved":
            s1_solved += 1
        # S2: GLiNER2 only for gap cases; otherwise gold-only verdicts
        if gap_spans:
            s2_verdicts = s1_verdicts
            s2_jev += len(all_spans)
        else:
            s2_verdicts = base_verdicts
            s2_state, _ = outcome(s2_verdicts, gold_values[cid])
        state = s1_state if gap_spans else s2_state
        if state == "resolved":
            s2_solved += 1
        if state == "false_resolved":
            false_ids.append(need["need_id"])
            per_type[qt]["false_resolved"] += 1
        if state == "ambiguous":
            ambiguous_ids.append(need["need_id"])
            per_type[qt]["ambiguous"] += 1
        if state == "resolved":
            per_type[qt]["solved"] += 1

        # Unique coverage: gold spans the extractor missed, found by GLiNER2,
        # surviving the frozen contract.
        for g in c["gold"]:
            gs = canon(g["span"])
            if gs in det_by_type[cid] or gs not in candidates[cid]:
                continue
            unique_total += 1
            per_type[qt]["unique_total"] += 1
            if canon_value(g["span"]) in s1_verified:
                unique_survived += 1
                per_type[qt]["unique_survived"] += 1

        per_case.append({
            "case_id": cid,
            "need_id": need["need_id"],
            "question_type": qt,
            "need_type": need["type"],
            "role": need.get("role") or "",
            "state": state,
            "gold": sorted(gold[cid]),
            "gliner_candidates": sorted(candidates[cid]),
            "extracted_same_type": sorted(det_by_type[cid]),
            "approved_values": sorted(s1_verified),
            "baseline_state": base_state,
        })

    total = len(cases)
    delta = s2_solved - baseline_solved
    out = args.out or str(B / "blindtest_facit_v2_eval.json")
    json.dump(
        {
            "facit": str(args.facit),
            "facit_provenance": facit.get("provenance"),
            "chain": "E1-E3 frozen contract + arm D / span-date-v1",
            "contract_module": "backend/app/services/research/gliner/contract.py",
            "model": model,
            "prompt_versions": {
                "arm_d": "span-need-contrast-v1",
                "date": "span-date-v1",
            },
            "material": facit.get("material"),
            "unique_verified": unique_survived,
            "unique_total": unique_total,
            "false_resolved_need_ids": false_ids,
            "ambiguous_need_ids": ambiguous_ids,
            "needs_total": total,
            "needs_solved_s2": s2_solved,
            "strategies": {
                "baseline": {"needs": baseline_solved},
                "s1": {"needs": s1_solved, "gliner_runs": s1_runs, "jev_calls": s1_jev},
                "s2": {"needs": s2_solved, "gliner_runs": s2_runs, "jev_calls": s2_jev},
            },
            "per_question_type": per_type,
            "per_case": per_case,
            "jev_new_calls": recorder.new_calls,
            "scope_note": (
                "Answer-level contamination is not measured at clause level; "
                "D10 procedure follows after this run."
            ),
        },
        open(out, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    json.dump(
        {cid: sorted(spans) for cid, spans in candidates.items()},
        open(str(B / "blindtest_facit_v2_candidates.json"), "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    recorder.save()

    print(f"\n1. unik kandidattäckning (verifierad): {unique_survived}/{unique_total}")
    print(f"2. lösta behov (S2): {s2_solved}/{total}")
    print(f"3. falskt RESOLVED per need_id: {len(false_ids)} {false_ids} — AMBIGUOUS: {len(ambiguous_ids)}")
    print("\nstrategier:")
    print(f"  baslinje (extraktor+Jev): {baseline_solved}/{total}")
    print(f"  S1 GLiNER2 överallt: {s1_solved}/{total}, {s1_runs} inferenser, {s1_jev} Jev")
    print(f"  S2 GLiNER2 vid gap:   {s2_solved}/{total}, {s2_runs} inferenser, {s2_jev} Jev")
    print(f"  kostnad per ytterligare löst behov (S2): "
          f"{s2_runs} inferenser + {s2_jev} Jev för {delta} extra behov")
    print("\nper frågetyp:")
    for qt, m in sorted(per_type.items()):
        print(f"  {qt}: unik {m['unique_survived']}/{m['unique_total']}, "
              f"lösta {m['solved']}/{m['needs']}, falskt RESOLVED {m['false_resolved']}, "
              f"AMBIGUOUS {m['ambiguous']}")
    print(f"\nskrivet: {out}")
    print(f"Jev: {recorder.new_calls} nya anrop (övriga återspelade från {FIXTURE.name})")


if __name__ == "__main__":
    main()
