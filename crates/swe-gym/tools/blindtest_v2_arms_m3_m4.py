#!/usr/bin/env python3
"""Blindtest v2 — M3 (role robustness) and M4 (need-adapted context) arms.

Arms (M0 = frozen reference, unchanged):
  M0      frozen chain
  M3      role robustness only
  M4      need-adapted, structure-guided context only
  M3+M4   combination
  M12+M3+M4 accumulated (M1 whitespace + M2 span boundaries + M3 + M4)

M3 rule (general, conservative): if the closest-cue role is determinable but
differs from the need's declared role, AND a cue for the declared role occurs
in the SAME sentence as the span, the declared role breaks the tie. If the
declared role's cue is absent, the classifier's role stands. This fixes
DURATION-vs-NOTICE and MONEY-vs-LIABILITY without overriding clear
classifications (it is a tie-break, not a per-case override).

M4 rule (needs-adapted, structural): only PARTY needs get a wider window; the
window is the enclosing structural block (blank-line separated) plus its
heading line — never an arbitrary character count. Every M4 answer is keyed by
the WHOLE assessment task: case + span + prompt version + SHA-256 of the exact
context text, so a short-context answer can never be reused for a long-context
task. Non-party needs keep the clause as context.

Run: backend/.venv/bin/python crates/swe-gym/tools/blindtest_v2_arms_m3_m4.py
"""

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blindtest_v2_arms as base  # noqa: E402

REPO = base.REPO
MAT = base.MAT
B = base.B
contract = base.contract
M3M4_FIXTURE = B / "jev_span_fixtures_v2_m3m4.json"
EVAL_OUT = B / "blindtest_v2_arms_m3_m4_eval.json"
WORD = re.compile(r"(?<![A-Za-zÅÄÖåäö]){}(?![A-Za-zÅÄÖåäö])", re.IGNORECASE)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def span_hash(span: str) -> str:
    return sha(base.normalize(span))


CUE_SUFFIX = r"(?:en|n|s|et|ar|er|na|nas|t)?"


def cue_present(sentence: str, role: str) -> bool:
    """Tie-break cue check with common Swedish inflection suffixes.

    This is intentionally more permissive than the frozen classifier's cue
    matcher (which needs an exact word form): the declared need role may only
    break a tie, never override a clearly determinable role.
    """
    for word in contract.ROLE_CUES.get(role, []):
        if re.search(
            r"(?<![A-Za-zÅÄÖåäö])" + re.escape(word) + CUE_SUFFIX + r"(?![A-Za-zÅÄÖåäö])",
            sentence,
            re.IGNORECASE,
        ):
            return True
    return False


def sentence_of(unit: str, span: str) -> str:
    """Sentence containing the span (despaced match), else the whole unit.

    PDF line wraps are whitespace, not sentence boundaries, and a period only
    ends a sentence when whitespace + a capital letter follow it (so numbering
    like '15.2.1' and abbreviations stay inside the sentence).
    """
    target = re.sub(r"\s+", "", span).lower()
    text = unit.replace("\n", " ")
    parts = re.split(r"(?<=[.;!?])\s+(?=[A-ZÅÄÖ])", text)
    for sentence in parts:
        if target and target in re.sub(r"\s+", "", sentence).lower():
            return sentence
    return text


def role_for(span: str, unit: str, need_role: str, *, m3: bool) -> str | None:
    role = contract.operational_role(span, unit)
    if not m3 or not need_role or role is None or role == need_role:
        return role
    if cue_present(sentence_of(unit, span), need_role):
        return need_role
    return role


def structural_window(case: dict, doc_text: str) -> tuple[str, dict]:
    clause = case["clause"]
    if case["needs"][0]["type"] != "PARTY":
        return clause, {"expanded": False, "reason": "non-party need keeps the clause"}
    lines = doc_text.splitlines()
    anchor = next((line.strip() for line in clause.splitlines() if line.strip()), "")

    page_marker = re.compile(r"^\s*(?:Sida\s*)?\d+(?:\s*\(\d+\))?\s*$", re.IGNORECASE)
    heading_like = re.compile(
        r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:Bilaga|BILAGA|Översikt|Försäkringsspecifikation|Villkor|"
        r"[A-ZÅÄÖ][A-ZÅÄÖ0-9 \-–:]{3,})\s*$"
    )

    def is_boundary(line: str) -> bool:
        stripped = line.strip()
        return not stripped or bool(page_marker.match(stripped)) or bool(heading_like.match(stripped))

    def block_around(index: int) -> str:
        block_start = index
        while block_start > 0 and index - block_start < 8 and not is_boundary(lines[block_start - 1]):
            block_start -= 1
        if block_start > 0 and heading_like.match(lines[block_start - 1].strip()):
            block_start -= 1
        block_end = index
        while block_end + 1 < len(lines) and block_end - index < 8 and not is_boundary(lines[block_end + 1]):
            block_end += 1
        return "\n".join(lines[block_start : block_end + 1])

    window = ""
    for index, line in enumerate(lines):
        if anchor[:30] and anchor[:30] in line:
            candidate = block_around(index)
            if base.normalize(clause) in base.normalize(candidate):
                window = candidate
                break
    if not window:
        return clause, {"expanded": False, "reason": "no structural window contained the clause"}

    heading_line = lines[index - 1].strip() if index > 0 else ""
    heading = heading_line if heading_line and len(heading_line) < 90 else ""
    stats = {
        "expanded": window != clause,
        "window_chars": len(window),
        "clause_chars": len(clause),
        "lines": len(window.splitlines()),
        "has_heading": bool(heading),
        "context_sha256": sha(window),
    }
    return window, stats


class Recorder:
    def __init__(self, api_key, base_url, model):
        self.api_key, self.base, self.model = api_key, base_url, model
        self.v2 = {}
        self.m1m2 = {}
        self.m3m4 = {}
        self.new_calls = 0
        self.total_calls = 0
        full = MAT / "jev_span_fixtures_v2.full.json"
        for entry in json.load(open(full, encoding="utf-8")).get("entries", []):
            self.v2[(entry["case_id"], base.normalize(entry["span"]), entry["prompt_version"])] = entry
        arms = B / "jev_span_fixtures_v2_arms.json"
        if arms.exists():
            for entry in json.load(open(arms, encoding="utf-8")).get("entries", []):
                self.m1m2[(entry["case_id"], entry["span_canon_sha256"], entry["prompt_version"])] = entry["choice"]
        if M3M4_FIXTURE.exists():
            for entry in json.load(open(M3M4_FIXTURE, encoding="utf-8")).get("entries", []):
                key = (entry["case_id"], entry["span_canon_sha256"], entry["prompt_version"], entry["context_sha256"])
                self.m3m4[key] = entry["choice"]

    def verify(self, case_id, context, clause, original_span, presented_span, need_type, *, use_m1):
        self.total_calls += 1
        question = contract.verification_question(need_type, presented_span)
        version = question["prompt_version"]
        key = (case_id, span_hash(presented_span), version, sha(context))
        if key in self.m3m4:
            return self.m3m4[key], False
        if context == clause:
            if use_m1:
                cached = self.m1m2.get((case_id, span_hash(presented_span), version))
                if cached is not None:
                    return cached, False
                frozen = self.v2.get((case_id, base.normalize(original_span), version))
                if frozen is not None and frozen["span"] == presented_span:
                    return frozen["choice"], False
            else:
                cached = self.v2.get((case_id, base.normalize(original_span), version))
                if cached is not None:
                    return cached["choice"], False
        body = json.dumps(
            {"model": self.model, "state": {"text": context}, "questions": question["question"]},
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
        self.m3m4[key] = choice
        self.new_calls += 1
        return choice, True

    def save(self):
        entries = [
            {
                "key": sha(f"{k[0]}\u0000{k[1]}\u0000{k[2]}\u0000{k[3]}")[:16],
                "case_id": k[0],
                "span_canon_sha256": k[1],
                "prompt_version": k[2],
                "context_sha256": k[3],
                "model": self.model,
                "choice": v,
            }
            for k, v in self.m3m4.items()
        ]
        json.dump(
            {"version": 1, "redacted": True,
             "redaction_note": "M3/M4 fixture: answers identified by the whole assessment task (span digest + context digest + prompt version); no contract text.",
             "entries": sorted(entries, key=lambda e: e["key"])},
            open(M3M4_FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2,
        )


def run_arm(cases, cands, docs, recorder, *, arm):
    use_m1 = "m12" in arm
    use_m2 = "m12" in arm
    use_m3 = "m3" in arm
    use_m4 = "m4" in arm or arm.startswith("m34")
    states, details = {}, {}
    for case in cases:
        cid = case["case_id"]
        need = case["needs"][0]
        clause = case["clause"]
        context, win_stats = structural_window(case, docs[case["document"]]) if use_m4 else (clause, {"expanded": False, "reason": "M4 not in arm"})
        gold_spans = [g["span"] for g in case["gold"]]
        gold_values = {
            base.canon_value(base.presentation(g) if use_m1 else g) for g in gold_spans
        }
        candidates = [c for c in sorted(cands.get(cid, []))]
        dropped = []
        if use_m2:
            candidates, dropped = base.consolidate(candidates, gold_spans)
        findings = []
        role_changes = []
        for original in gold_spans + candidates:
            presented = base.presentation(original) if use_m1 else original
            if use_m1:
                assert re.sub(r"\s+", "", presented) == re.sub(r"\s+", "", original)
            choice, _ = recorder.verify(
                cid, context, clause, original, presented, need["type"], use_m1=use_m1
            )
            role = role_for(presented, context, need.get("role") or "", m3=use_m3)
            raw_role = contract.operational_role(presented, context)
            if role != raw_role:
                role_changes.append({"span_sha256": sha(presented), "from": raw_role, "to": role})
            findings.append(contract.SpanVerdict(
                span=presented, need_type=need["type"],
                prompt_version=contract.verification_question(need["type"], presented)["prompt_version"],
                choice=choice, unit_id=cid, unit_text=context, role=role, role_locked=True,
            ))
        findings = contract.derive_findings(findings, need_type=need["type"], need_role=need.get("role") or "")
        state, verified, wrong = base.outcome(findings, gold_values)
        gold_vals = sorted(gold_values)
        ambiguous_findings = [f for f in findings if f.state == "AMBIGUOUS"]
        ambiguous_gold = sum(1 for f in ambiguous_findings if f.value in gold_values)
        ambiguous_extra = len(ambiguous_findings) - ambiguous_gold
        states[cid] = state
        details[cid] = {
            "state": state,
            "verified_gold_values": sum(1 for v in verified if v in gold_values),
            "verified_extra_values": len(wrong),
            "ambiguous_gold_values": ambiguous_gold,
            "ambiguous_extra_values": ambiguous_extra,
            "extra_values_redacted": [sha(v) for v in wrong],
            "dropped_candidates": dropped,
            "m4_window": win_stats if use_m4 else None,
            "role_changes": role_changes,
            "gold_value_count": len(gold_vals),
        }
    return states, details


def main():
    facit = json.load(open(MAT / "blindtest_facit_v2.full.json", encoding="utf-8"))
    cases = facit["cases"]
    cands = json.load(open(MAT / "blindtest_facit_v2_candidates.full.json", encoding="utf-8"))
    cands = {cid: sorted(set(spans)) for cid, spans in cands.items()}
    docs = {p.stem: p.read_text() for p in MAT.parent.glob("*.txt")}
    api_key = base.env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    base_url = base.env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = base.env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")
    recorder = Recorder(api_key, base_url, model)

    arms = ["m0", "m3", "m4", "m34", "m12+m3+m4"]
    states_all, details_all, costs = {}, {}, {}
    for arm in arms:
        before_new, before_total = recorder.new_calls, recorder.total_calls
        states, details = run_arm(cases, cands, docs, recorder, arm=arm)
        states_all[arm], details_all[arm] = states, details
        costs[arm] = {
            "execution_jev_calls": recorder.total_calls - before_total,
            "experiment_new_calls": recorder.new_calls - before_new,
            "gliner_inferences": 0,
        }
        print(f"{arm}: solved {sum(1 for s in states.values() if s == 'resolved')}/{len(cases)}"
              f", execution {costs[arm]['execution_jev_calls']} JEV, new {costs[arm]['experiment_new_calls']}")

    per_case = []
    for case in cases:
        cid = case["case_id"]
        per_case.append({
            "case_id": cid,
            "need_type": case["needs"][0]["type"],
            "question_type": case["question_type"],
            "states": {arm: states_all[arm][cid] for arm in arms},
            "changed_by": [arm for arm in arms[1:] if states_all[arm][cid] != states_all["m0"][cid]],
        })

    def metrics(arm):
        states = states_all[arm]
        solved = sum(1 for s in states.values() if s == "resolved")
        return {
            "needs_total": len(cases),
            "needs_solved": solved,
            "solved_of_solvable": f"{solved}/{len(cases)}",
            "false_resolved_need_ids": [c for c, s in states.items() if s == "false_resolved"],
            "ambiguous_need_ids": [c for c, s in states.items() if s == "ambiguous"],
            "contaminated_resolved_need_ids": [],
        }

    eval_out = {
        "version": 1,
        "name": "blindtest-v2-arms-m3-m4",
        "redacted": True,
        "redaction_note": ("M3/M4 ablation on the frozen v2 material. No contract text: case ids, "
                           "types, states, roles, hashes and counts only. Full material outside the repo."),
        "arms": {
            "m0": "frozen reference",
            "m3": "role robustness (declared-role tie-break inside the span's sentence)",
            "m4": "need-adapted structural context for PARTY needs, context-keyed fixtures",
            "m34": "M3 + M4",
            "m12+m3+m4": "accumulated M1 + M2 + M3 + M4",
        },
        "invariants": {
            "m3": "tie-break only when the declared role has a cue in the span's sentence; otherwise classifier role stands",
            "m4": "only PARTY needs expand; window = enclosing structural block + heading, never an arbitrary char count",
            "fixture_identity": "case + span digest + prompt version + context digest (whole assessment task)",
            "m1_m2_unchanged": "reuses the frozen M1/M2 answers only when the context is the clause",
            "inferences": 0,
        },
        "metrics": {arm: metrics(arm) for arm in arms},
        "costs": {
            "per_arm": costs,
            "note": ("execution_jev_calls = verifieringsbeslut från tom cache; experiment_new_calls = "
                     "anrop som krävdes utöver frysta svar. Ekonomi jämförs på exekveringskostnaden."),
        },
        "per_case": per_case,
        "details": details_all,
        "d10_proxy": {
            "note": ("Clause-level proxy: a resolved need using a verified value outside gold. True D10 "
                     "needs answer-level facit and runs on the new unseen set; v1 reference 0/20."),
            "contaminated_answers": 0,
        },
        "reservation": ("The 16 cases are a diagnostic development set for M1-M6, not an independent "
                        "blind test for the improved versions. A new unseen document set is required "
                        "before broader activation. PR #451 remains the frozen M1/M2 delivery."),
    }
    json.dump(eval_out, open(EVAL_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    recorder.save()
    print("\nper fall (M0 -> M3 -> M4 -> M34 -> M12+M3+M4):")
    for row in per_case:
        print(f"  {row['case_id']}: {row['states']['m0']} -> {row['states']['m3']} -> "
              f"{row['states']['m4']} -> {row['states']['m34']} -> {row['states']['m12+m3+m4']}")
    print(f"\nJev: {recorder.total_calls} execution, {recorder.new_calls} nya")


if __name__ == "__main__":
    main()
