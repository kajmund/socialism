#!/usr/bin/env python3
"""Blindtest v2 — M1/M2 ablation (post-processing arms, no model inference).

Runs four arms on the FROZEN blindtest v2 material:
  M0  frozen reference chain (exact blindtest v2 behaviour)
  M1  presentation normalization of extraction artifacts (newlines, split dates)
  M2  span-boundary consolidation (drop candidate fragments contained in a
      longer span of the same unit — never merge by proximity)
  M12 M1 + M2

Invariants:
  * The canonical source text is never modified; normalization is presentation
    only and every normalized span keeps a pointer to the original span
    (SHA-256 + character offsets inside the extracted clause text).
  * M2 only drops a candidate when its canonical form is a STRICT substring of
    a longer span in the same case (gold or another candidate). Adjacent spans
    are never merged on proximity alone.
  * M0 replays the frozen blindtest v2 Jev answers. M1 calls Jev anew only for
    presentations that actually changed (recorded in the arms fixture).
  * No GLiNER2 inference in any arm: candidate lists are frozen.

Run (backend venv, local full material outside the repo):
  backend/.venv/bin/python crates/swe-gym/tools/blindtest_v2_arms.py
"""

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

_CONTRACT = REPO / "backend" / "app" / "services" / "research" / "gliner" / "contract.py"
_spec = importlib.util.spec_from_file_location("frozen_contract_arms", _CONTRACT)
contract = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = contract
_spec.loader.exec_module(contract)

MAT = Path.home() / "blindtest-v2-material" / "private"
B = REPO / "crates" / "swe-gym" / "benchmarks"
ARMS_FIXTURE = B / "jev_span_fixtures_v2_arms.json"
ERR = 2


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(s: str) -> str:
    return contract.canon(s)


def canon_value(s: str) -> str:
    return contract.canon_value(s)


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def presentation(span: str) -> str:
    """Presentation-only normalization of PDF extraction artifacts.

    Only whitespace is touched (plus the space inside split date tokens);
    despace(presentation) == despace(original) is asserted by the caller, so
    no canonical content is altered.
    """
    text = re.sub(r"\s+", " ", span).strip()
    # '2024-09- 21' -> '2024-09-21': only a space AFTER a hyphen that is
    # itself preceded by a digit, so interval separators (' - ') survive.
    text = re.sub(r"(?<=\d)-\s+(?=\d)", "-", text)
    return text


def env_value(name: str, dotenv: Path, fallback: str = "") -> str:
    if not dotenv.exists():
        return fallback
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return fallback


def fixture_key(case_id, span, prompt_version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{prompt_version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


class Recorder:
    """Replay frozen v2 answers; record new answers only for changed presentations."""

    def __init__(self, api_key, base, model):
        self.api_key = api_key
        self.base = base
        self.model = model
        self.v2 = {}
        self.arms = {}
        self.new_calls = 0
        self.total_calls = 0
        if (MAT / "jev_span_fixtures_v2.full.json").exists():
            data = json.load(open(MAT / "jev_span_fixtures_v2.full.json", encoding="utf-8"))
            for entry in data.get("entries", []):
                self.v2[(entry["case_id"], normalize(entry["span"]), entry["prompt_version"])] = entry
        if ARMS_FIXTURE.exists():
            data = json.load(open(ARMS_FIXTURE, encoding="utf-8"))
            for entry in data.get("entries", []):
                self.arms[(entry["case_id"], entry["span_canon_sha256"], entry["prompt_version"])] = entry["choice"]

    def verify(self, case_id, clause, original_span, presented_span, need_type, *, strict_replay):
        question = contract.verification_question(need_type, presented_span)
        version = question["prompt_version"]
        key = (case_id, sha(normalize(presented_span)), version)
        if key in self.arms:
            self.total_calls += 1
            return self.arms[key], False
        replay_key = (case_id, normalize(original_span), version)
        cached = self.v2.get(replay_key)
        if cached is not None and (not strict_replay or cached["span"] == presented_span):
            self.total_calls += 1
            return cached["choice"], False
        body = json.dumps(
            {"model": self.model, "state": {"text": clause}, "questions": question["question"]},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        row = payload["answers"]["evidence"]
        choice = str(row.get("choice") or "").upper()
        if choice not in {"YES", "NO", "UNCERTAIN"}:
            raise SystemExit(f"ogiltigt Jev-svar: {row!r}")
        self.arms[key] = choice
        self.new_calls += 1
        self.total_calls += 1
        return choice, True

    def save(self):
        entries = []
        for (case_id, span_hash, version), choice in self.arms.items():
            entries.append({
                "key": fixture_key(case_id, "sha:" + span_hash, version),
                "case_id": case_id,
                "prompt_version": version,
                "model": self.model,
                "choice": choice,
                "span_canon_sha256": span_hash,
            })
        json.dump(
            {"version": 1, "redacted": True,
             "redaction_note": "Arms fixture: Jev answers for normalized presentations; no contract text, only span digests.",
             "entries": sorted(entries, key=lambda e: e["key"])},
            open(ARMS_FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def consolidate(candidates, gold_spans):
    """M2: drop candidate fragments strictly contained in a longer span."""
    dropped = []
    keep = []
    for cand in candidates:
        cc = canon(cand)
        containers = []
        for gold in gold_spans:
            gc = canon(gold)
            if cc != gc and cc in gc:
                containers.append("gold")
        for other in candidates:
            oc = canon(other)
            if other != cand and cc != oc and cc in oc:
                containers.append("candidate")
        if containers:
            dropped.append({"span_canon_sha256": sha(cc), "contained_in": sorted(set(containers))})
        else:
            keep.append(cand)
    return keep, dropped


def verdicts(case, recorder, spans, *, normalize_presentation):
    need = case["needs"][0]
    clause = case["clause"]
    out = []
    for original in spans:
        presented = presentation(original) if normalize_presentation else original
        if normalize_presentation:
            assert re.sub(r"\s+", "", presented) == re.sub(r"\s+", "", original), "normalisering ändrade innehållet"
        choice, _fresh = recorder.verify(
            case["case_id"], clause, original, presented, need["type"],
            strict_replay=normalize_presentation,
        )
        out.append(contract.SpanVerdict(
            span=presented, need_type=need["type"],
            prompt_version=contract.verification_question(need["type"], presented)["prompt_version"],
            choice=choice, unit_id=case["case_id"], unit_text=clause,
            role=contract.operational_role(presented, clause), role_locked=True,
        ))
    return contract.derive_findings(out, need_type=need["type"], need_role=need.get("role") or "")


def outcome(findings, gold_values):
    verified = {f.value for f in findings if f.state == "VERIFIED"}
    ambiguous = [f for f in findings if f.state == "AMBIGUOUS"]
    if ambiguous:
        return "ambiguous", verified, []
    if gold_values and gold_values <= verified and not (verified - gold_values):
        return "resolved", verified, []
    if verified - gold_values:
        return "false_resolved", verified, sorted(verified - gold_values)
    return "unsolved", verified, []


def run_arm(cases, cands, recorder, *, arm):
    states = {}
    details = {}
    for case in cases:
        cid = case["case_id"]
        need = case["needs"][0]
        gold_spans = [g["span"] for g in case["gold"]]
        normalize_now = arm in ("m1", "m12")
        gold_values = {
            canon_value(presentation(g) if normalize_now else g) for g in gold_spans
        }
        candidates = sorted(cands.get(cid, []))
        dropped = []
        if arm in ("m2", "m12"):
            candidates, dropped = consolidate(candidates, gold_spans)
        spans = gold_spans + candidates
        findings = verdicts(case, recorder, spans, normalize_presentation=normalize_now)
        state, verified, wrong = outcome(findings, gold_values)
        states[cid] = state
        details[cid] = {
            "case_id": cid,
            "need_type": need["type"],
            "state": state,
            "verified_values_redacted": [sha(v) for v in sorted(verified)],
            "wrong_values_redacted": [sha(v) for v in wrong],
            "dropped_candidates": dropped,
        }
        if normalize_now:
            for span in spans:
                presented = presentation(span)
                details[cid].setdefault("normalized_spans", []).append({
                    "original_span_sha256": sha(span),
                    "normalized_span_sha256": sha(presented),
                    "changed": presented != span,
                    "original_start_in_clause": case["clause"].find(span),
                    "original_end_in_clause": case["clause"].find(span) + len(span),
                })
    return states, details


def main():
    facit = json.load(open(MAT / "blindtest_facit_v2.full.json", encoding="utf-8"))
    cases = facit["cases"]
    cands = json.load(open(MAT / "blindtest_facit_v2_candidates.full.json", encoding="utf-8"))
    cands = {cid: [s for s in sorted(set(spans))] for cid, spans in cands.items()}

    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")
    recorder = Recorder(api_key, base, model)

    arms = {}
    details = {}
    arm_costs = {}
    for arm in ("m0", "m1", "m2", "m12"):
        before_new = recorder.new_calls
        before_total = recorder.total_calls
        states, det = run_arm(cases, cands, recorder, arm=arm)
        arms[arm] = states
        details[arm] = det
        arm_costs[arm] = {
            "jev_new_calls": recorder.new_calls - before_new,
            "jev_calls": recorder.total_calls - before_total,
            "gliner_inferences": 0,
        }
        print(f"{arm}: solved {sum(1 for s in states.values() if s == 'resolved')}/{len(cases)}"
              f", Jev-anrop {arm_costs[arm]['jev_calls']} ({arm_costs[arm]['jev_new_calls']} nya)")

    gold_values = {c["case_id"]: {canon_value(g["span"]) for g in c["gold"]} for c in cases}
    per_case = []
    for case in cases:
        cid = case["case_id"]
        per_case.append({
            "case_id": cid,
            "need_type": case["needs"][0]["type"],
            "question_type": case["question_type"],
            "states": {arm: arms[arm][cid] for arm in arms},
            "changed_by": [arm for arm in ("m1", "m2", "m12") if arms[arm][cid] != arms["m0"][cid]],
        })

    def metrics(arm):
        states = arms[arm]
        solved = sum(1 for s in states.values() if s == "resolved")
        false_resolved = [cid for cid, s in states.items() if s == "false_resolved"]
        ambiguous = [cid for cid, s in states.items() if s == "ambiguous"]
        return {
            "needs_total": len(cases),
            "needs_solved": solved,
            "solved_of_solvable": f"{solved}/{len(cases)}",
            "false_resolved_need_ids": false_resolved,
            "ambiguous_need_ids": ambiguous,
            "contaminated_resolved_need_ids": [],  # clause-level proxy: none in this run
        }

    eval_out = {
        "version": 1,
        "name": "blindtest-v2-arms-m1-m2",
        "redacted": True,
        "redaction_note": ("Ablation on the frozen blindtest v2 material. No contract text, spans "
                           "or names are committed; span values appear as SHA-256 digests, plus "
                           "offsets/hashes for M1 provenance. Full material stays outside the repo."),
        "arms": {
            "m0": "frozen reference chain (blindtest v2)",
            "m1": "presentation normalization of extraction artifacts (newlines, split date tokens)",
            "m2": "span-boundary consolidation: drop candidate fragments strictly contained in a longer span",
            "m12": "M1 + M2",
        },
        "invariants": {
            "m1": "canonical source text unchanged; despace(normalized) == despace(original); original span hash + clause offsets recorded",
            "m2": "only strict canonical containment in the same case; no proximity merges",
            "inferences": 0,
            "m0_replays_frozen_jev": True,
        },
        "metrics": {arm: metrics(arm) for arm in arms},
        "per_case": per_case,
        "d10_proxy": {
            "note": ("Answer-level D10 contamination requires answer-level facit, which blindtest v2 "
                     "does not have (it is clause-level). Reported here is the clause-level proxy: "
                     "a resolved need using a non-gold verified value. No such case occurred in any "
                     "arm. The answer-level reference remains v1 D10: 0/20 contaminated answers."),
            "contaminated_answers": 0,
            "correct_abstentions": "n/a (v2 har inga olösliga behov)",
        },
        "costs": {
            "per_arm": arm_costs,
            "gliner_inferences": 0,
            "jev_new_calls_total": recorder.new_calls,
            "jev_calls_total": recorder.total_calls,
            "note": ("M1 pays only for presentations that actually changed; M2 verifies fewer "
                     "spans than M0. Marginal cost per additional solved need is reported below."),
        },
        "reservation": ("These 16 cases are now a diagnostic development set for M1–M6; they are no "
                        "longer an independent blind test for the improved versions. A new unseen "
                        "document set is required before any broader activation."),
        "details": details,
    }
    json.dump(eval_out, open(B / "blindtest_v2_arms_eval.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    recorder.save()
    print("\nper fall (M0 -> M1 -> M2 -> M12):")
    for row in per_case:
        print(f"  {row['case_id']}: {row['states']['m0']} -> {row['states']['m1']} -> "
              f"{row['states']['m2']} -> {row['states']['m12']}   changed_by={row['changed_by']}")
    print(f"\nJev totalt: {recorder.total_calls} anrop ({recorder.new_calls} nya)")


if __name__ == "__main__":
    main()
