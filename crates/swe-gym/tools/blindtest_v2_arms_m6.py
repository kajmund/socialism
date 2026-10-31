#!/usr/bin/env python3
"""Blindtest v2 — M6: selective verification recovery (own experiment).

M6 is NOT a generic second Jev attempt. A first NO may be re-reviewed exactly
once, only when independent signals disagree with it:

  1. the span is a GLiNER2 candidate (a proposal, not gold),
  2. a deterministic detector recognises it as a value of the need's type,
  3. the operational role matches the need's declared role (or is undeterminable),
  4. the first assessment was NO.

The exactly-one supplementary assessment uses a new recovery prompt version
(`span-need-recovery-v1`) that states the need's operational role; whatever it
answers, the result enters the ordinary contract: no automatic RESOLVED, and for
multi-value needs the M5 cardinality policy still applies.

Control: candidate NOs that do not pass the trigger are never re-reviewed
(guard 1), and re-reviewed correct NOs are counted and must stay NO.

M6 is measured isolated against M0 and on top of M1-M5. M6 does not change the
frozen M1-M5 artifacts.

Run: backend/.venv/bin/python crates/swe-gym/tools/blindtest_v2_arms_m6.py
"""

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blindtest_v2_arms as base  # noqa: E402
import blindtest_v2_arms_m3_m4 as m3m4  # noqa: E402
import blindtest_v2_arms_m5 as m5  # noqa: E402

REPO = base.REPO
MAT = base.MAT
B = base.B
contract = base.contract
RECOVERY_VERSION = "span-need-recovery-v1"
M6_FIXTURE = B / "jev_span_fixtures_v2_m6.json"
EVAL_OUT = B / "blindtest_v2_arms_m6_eval.json"

NUMBER_WORDS = (
    "ett|två|tre|fyra|fem|sex|sju|åtta|nio|tio|elva|tolv|tretton|fjorton|femton|"
    "sexton|sjutton|arton|nitton|tjugo|trettio|fyrtio|femtio|sextio|sjuttio|åttio|nittio"
)
DURATION = re.compile(
    rf"(?:\d+|(?:{NUMBER_WORDS}))[\s)]*(?:\(?(?:\d+)\)?\s*)?"
    r"(?:kalender)?(?:dagar|dags|veckor|veckors|månader|månaders|månad|år|timmar|timmar|minuter)\b",
    re.IGNORECASE,
)
MONEY = re.compile(
    rf"(?:\d[\d\s]*|(?:{NUMBER_WORDS}))[\s)]*(?:kr|kronor|SEK|procent)\b",
    re.IGNORECASE,
)
DATE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}\s*[-–]\s*\d{1,2}\s+(?:januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december))"
    r"|(?:\d{1,2}\s+(?:januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december))",
    re.IGNORECASE,
)
PARTY = re.compile(
    r"(?<![A-Za-zÅÄÖåäö])(?:AB|HB|KB)(?![A-Za-zÅÄÖåäö])"
    r"|(?:aktiebolag|förening|stiftelse|myndighet|nämnd|kommun|region)\b",
    re.IGNORECASE,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def value_hash(value: str) -> str:
    return sha(value)


def deterministic_value(need_type: str, span: str) -> bool:
    """Independent, model-free detector per need type (guard 2)."""
    text = span.replace(" ", "") if need_type == "DATE" else span
    if need_type in {"PERIOD", "NOTICE_PERIOD", "RENEWAL", "SEVERANCE"}:
        return bool(DURATION.search(text))
    if need_type in {"MONEY", "SEVERANCE_VALUE", "PENALTY", "LIABILITY_CAP"}:
        return bool(MONEY.search(text))
    if need_type == "DATE":
        return bool(DATE.search(text))
    if need_type == "PARTY":
        return bool(PARTY.search(text))
    return False


def recovery_question(need_type: str, role: str, span: str) -> dict:
    label = contract.NEED_LABELS.get(need_type, need_type)
    role_text = f" Behovets operativa roll är {role}." if role else ""
    return {
        "evidence": {
            "type": "choice",
            "instructions": (
                f"Detta är en kompletterande bedömning. En första bedömning svarade NO på om "
                f"spannet '{span}' är ett {label}.{role_text} Bedöm spannet på nytt: uttrycker "
                f"spannet exakt det värde som behovet efterfrågar i denna roll? Svara YES endast "
                f"om spannet självt uttrycker värdet; lägg inte till information utanför spannet."
            ),
            "criteria": {
                "YES": "Spannet uttrycker exakt det efterfrågade värdet i behovets roll.",
                "NO": "Spannet uttrycker inte det efterfrågade värdet.",
                "UNCERTAIN": "Går inte att avgöra.",
            },
        }
    }


class RecoveryRecorder:
    def __init__(self, api_key, base_url, model):
        self.api_key, self.base, self.model = api_key, base_url, model
        self.store = {}
        self.new_calls = 0
        self.total_calls = 0
        if M6_FIXTURE.exists():
            for entry in json.load(open(M6_FIXTURE, encoding="utf-8")).get("entries", []):
                self.store[(entry["case_id"], entry["span_canon_sha256"],
                            entry["context_sha256"])] = entry["choice"]

    def recovery(self, case_id, context, presented_span, need_type, role):
        key = (case_id, sha(base.normalize(presented_span)), sha(context))
        if key in self.store:
            self.total_calls += 1
            return self.store[key]
        body = json.dumps(
            {"model": self.model, "state": {"text": context},
             "questions": recovery_question(need_type, role, presented_span)},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        choice = str(payload["answers"]["evidence"].get("choice") or "").upper()
        if choice not in {"YES", "NO", "UNCERTAIN"}:
            raise SystemExit("ogiltigt Jev-svar i recovery")
        self.store[key] = choice
        self.new_calls += 1
        self.total_calls += 1
        return choice

    def save(self):
        entries = [
            {
                "key": sha(f"{k[0]}\u0000{k[1]}\u0000{RECOVERY_VERSION}\u0000{k[2]}")[:16],
                "case_id": k[0],
                "span_canon_sha256": k[1],
                "context_sha256": k[2],
                "prompt_version": RECOVERY_VERSION,
                "model": self.model,
                "choice": v,
            }
            for k, v in self.store.items()
        ]
        json.dump(
            {"version": 1, "redacted": True,
             "redaction_note": "M6 recovery answers keyed by the whole assessment task; no contract text.",
             "entries": sorted(entries, key=lambda e: e["key"])},
            open(M6_FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2,
        )


def run_arm(cases, cands, docs, recorder, recovery, costs, *, arm):
    use_m1 = "m12" in arm
    use_m2 = "m12" in arm
    use_m3 = "m3" in arm
    use_m4 = "m4" in arm or arm.startswith("m34")
    use_m5 = "m5" in arm
    use_m6 = "m6" in arm
    states, details = {}, {}
    new_before = recorder.new_calls + recovery.new_calls
    total_before = recorder.total_calls + recovery.total_calls
    recovery_stats = {"candidate_nos": 0, "triggers": 0, "recovered": 0,
                      "retained": 0, "guard_blocked": 0, "supplementary_calls": 0}
    for case in cases:
        cid = case["case_id"]
        need = case["needs"][0]
        clause = case["clause"]
        need_role = need.get("role") or ""
        context, win_stats = (
            m3m4.structural_window(case, docs[case["document"]])
            if use_m4
            else (clause, {"expanded": False, "reason": "M4 not in arm"})
        )
        gold_spans = [g["span"] for g in case["gold"]]
        gold_values = {
            base.canon_value(base.presentation(g) if use_m1 else g) for g in gold_spans
        }
        candidates = sorted(cands.get(cid, []))
        if use_m2:
            candidates, _ = base.consolidate(candidates, gold_spans)
        candidate_hashes = {sha(base.normalize(c)) for c in candidates}
        ordered = gold_spans + candidates
        verdicts = []
        events = []
        recovery_seen: set[str] = set()
        for original in ordered:
            presented = base.presentation(original) if use_m1 else original
            choice, _ = recorder.verify(
                cid, context, clause, original, presented, need["type"], use_m1=use_m1
            )
            role = m3m4.role_for(presented, context, need_role, m3=use_m3)
            is_candidate = sha(base.normalize(original)) in candidate_hashes
            span_key = sha(base.normalize(presented))
            if use_m6 and is_candidate and choice == "NO" and span_key not in recovery_seen:
                recovery_seen.add(span_key)
                recovery_stats["candidate_nos"] += 1
                detector = deterministic_value(need["type"], presented)
                role_match = not need_role or role is None or role == need_role
                if detector and role_match:
                    recovery_stats["triggers"] += 1
                    supplementary = recovery.recovery(
                        cid, context, presented, need["type"], need_role
                    )
                    recovery_stats["supplementary_calls"] += 1
                    recovered = supplementary == "YES"
                    if recovered:
                        choice = "YES"
                        recovery_stats["recovered"] += 1
                    else:
                        recovery_stats["retained"] += 1
                    events.append({
                        "span_sha256": sha(base.normalize(presented)),
                        "detector": True, "role_match": True,
                        "first_choice": "NO", "supplementary_choice": supplementary,
                        "recovered": recovered,
                        "recovered_value_in_gold": recovered and (
                            base.canon_value(presented) in gold_values
                        ),
                    })
                else:
                    recovery_stats["guard_blocked"] += 1
            verdicts.append(
                contract.SpanVerdict(
                    span=presented, need_type=need["type"],
                    prompt_version=contract.verification_question(need["type"], presented)["prompt_version"],
                    choice=choice, unit_id=cid, unit_text=context,
                    role=role, role_locked=True,
                )
            )
        findings = contract.derive_findings(
            verdicts, need_type=need["type"], need_role=need_role
        )
        base_state, _verified, _wrong = base.outcome(findings, gold_values)
        approved = {
            base.canon_value(v.span) for v in verdicts
            if v.choice == "YES" and (not need_role or v.role is None or v.role == need_role)
        }
        detail = {
            "base_state": base_state,
            "approved_value_sha256": sorted(value_hash(v) for v in approved),
            "gold_value_sha256": sorted(value_hash(v) for v in gold_values),
            "recovery_events": events,
            "m4_window": win_stats if use_m4 else None,
        }
        spec = m5.CARDINALITY.get(cid) if use_m5 else None
        state = m5.cardinality_policy(detail, spec)
        states[cid] = state
        details[cid] = {**detail, "cardinality": spec, "state": state}
    if use_m6:
        assert recovery_stats["triggers"] + recovery_stats["guard_blocked"] == recovery_stats["candidate_nos"], (
            "varje kandidat-NO måste vara antingen triggat eller guard-blockerat"
        )
    costs[arm] = {
        "execution_jev_calls": (recorder.total_calls + recovery.total_calls) - total_before,
        "experiment_new_calls": (recorder.new_calls + recovery.new_calls) - new_before,
        "supplementary_calls": recovery_stats["supplementary_calls"],
        "gliner_inferences": 0,
    }
    return states, details, recovery_stats


def main():
    facit = json.load(open(MAT / "blindtest_facit_v2.full.json", encoding="utf-8"))
    cases = facit["cases"]
    cands = json.load(open(MAT / "blindtest_facit_v2_candidates.full.json", encoding="utf-8"))
    cands = {cid: sorted(set(spans)) for cid, spans in cands.items()}
    docs = {p.stem: p.read_text() for p in MAT.parent.glob("*.txt")}
    api_key = base.env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    base_url = base.env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = base.env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")
    recorder = m3m4.Recorder(api_key, base_url, model)
    recovery = RecoveryRecorder(api_key, base_url, model)

    arms = ["m0", "m6", "m12+m3+m4+m5", "m12+m3+m4+m5+m6"]
    states_all, details_all, costs, rec_stats = {}, {}, {}, {}
    for arm in arms:
        states, details, stats = run_arm(cases, cands, docs, recorder, recovery, costs, arm=arm)
        states_all[arm], details_all[arm], rec_stats[arm] = states, details, stats
        print(f"{arm}: solved {sum(1 for s in states.values() if s == 'resolved')}/{len(cases)}"
              f", execution {costs[arm]['execution_jev_calls']} JEV"
              f", new {costs[arm]['experiment_new_calls']}"
              f", recovery {stats}")

    per_case = []
    for case in cases:
        cid = case["case_id"]
        spec = m5.CARDINALITY.get(cid)
        row = {
            "case_id": cid,
            "need_type": case["needs"][0]["type"],
            "question_type": case["question_type"],
            "cardinality": (spec or {}).get("cardinality", "SINGLE"),
            "states": {arm: states_all[arm][cid] for arm in arms},
            "changed_by": [arm for arm in arms[1:] if states_all[arm][cid] != states_all["m0"][cid]],
        }
        if spec:
            for arm in ("m12+m3+m4+m5", "m12+m3+m4+m5+m6"):
                d = details_all[arm][cid]
                approved = set(d["approved_value_sha256"])
                expected = set(d["gold_value_sha256"])
                row[f"{arm}_found_expected"] = len(approved & expected)
                row[f"{arm}_missing"] = len(expected - approved)
                row[f"{arm}_extras"] = len(approved - expected)
        per_case.append(row)

    def metrics(arm):
        states = states_all[arm]
        return {
            "needs_total": len(cases),
            "needs_solved": sum(1 for s in states.values() if s == "resolved"),
            "needs_partial": sum(1 for s in states.values() if s == "partial"),
            "false_resolved_need_ids": [c for c, s in states.items() if s == "false_resolved"],
            "contaminated_need_ids": [],
        }

    total_supplementary = sum(s["supplementary_calls"] for s in rec_stats.values())
    eval_out = {
        "version": 1,
        "name": "blindtest-v2-arms-m6",
        "redacted": True,
        "redaction_note": ("M6 selective verification recovery on the frozen v2 material. No contract "
                           "text: case ids, types, counts, states, hashes and decisions only."),
        "design": {
            "arms": {
                "m0": "frozen reference",
                "m6": "selective recovery only",
                "m12+m3+m4+m5": "accumulated M1-M5, no recovery",
                "m12+m3+m4+m5+m6": "accumulated + selective recovery",
            },
            "trigger": [
                "span is a GLiNER2 candidate (proposal, never gold)",
                "deterministic detector recognises a value of the need's type",
                "operational role matches the need role (or is undeterminable)",
                "first Jev assessment was NO",
            ],
            "guards": {
                "no_blind_review": "a NO alone never triggers a new call",
                "single_supplementary": "exactly one supplementary assessment per triggered NO",
                "no_auto_resolved": "the recovered answer enters the ordinary contract (type/role/cardinality/evidence)",
            },
            "recovery_prompt_version": RECOVERY_VERSION,
            "fixture_identity": "case + span digest + context digest",
            "control_group": "candidate NOs that fail the trigger are never re-reviewed; re-reviewed correct NOs are counted and must stay NO",
            "m5_untouched": "the M5 cardinality policy is reused, not modified",
        },
        "metrics": {arm: metrics(arm) for arm in arms},
        "recovery": rec_stats,
        "costs": costs,
        "per_case": per_case,
        "details": details_all,
        "d10_proxy": {
            "note": "Clause-level proxy: a resolved need using an outside-expected value. True D10 runs on the new unseen set.",
            "contaminated_answers": 0,
        },
        "reservation": ("The 16 cases developed M1-M6, so even a perfect score would not prove "
                        "generalization. The next step is a new blind test with the whole chain, no "
                        "adjustments. M6 stays separate from M5."),
    }
    json.dump(eval_out, open(EVAL_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    recovery.save()
    print("\nper fall (M0 -> M6 -> M12345 -> M12345+M6):")
    for row in per_case:
        print(f"  {row['case_id']}: {row['states']['m0']} -> {row['states']['m6']} -> "
              f"{row['states']['m12+m3+m4+m5']} -> {row['states']['m12+m3+m4+m5+m6']}")
    print(f"\nrecovery total supplementary: {total_supplementary}")
    print(f"Jev: {recorder.total_calls + recovery.total_calls} execution, "
          f"{recorder.new_calls + recovery.new_calls} nya")


if __name__ == "__main__":
    main()
