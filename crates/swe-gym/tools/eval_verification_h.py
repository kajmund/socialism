#!/usr/bin/env python3
"""Arms H1/H2 (docs/architecture/gliner2-jevspan-evaluation.md, D7):
GLiNER2's own labels as the type signal — H1 accepts them as candidate
types, H2 adds a JEV type check only at conflict/uncertainty. The
relation to the information need is JEV's job; the evidence contract
stays SWE's. D is recomputed with the same unique need_id false-
resolved definition as E/F/G.

The candidate population is frozen WITH GLiNER2 labels first (one
local GLiNER2 pass — the model is cached, no API cost).

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_verification_h.py
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
from eval_verification_stages import DURATION_RE, TERM_RE, RENEW_RE  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
CANDIDATES_V2 = B / "gliner_candidates_v2.json"
OUT = B / "verification_h.json"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}
# GLiNER2 label -> the contract's fact-type category.
LABEL_TO_CONTRACT = {
    "Uppsägningstid": "TIDSPERIOD", "Avgångsvederlag": "VILLKOR",
    "Ersättning": "VILLKOR", "Uppsägningsvillkor": "VILLKOR",
    "Förlängning": "TIDSPERIOD", "Vite": "VILLKOR", "Ansvarstak": "VILLKOR",
    "Undantag": "VILLKOR", "Avtalspart": "PART", "Belopp": "BELOPP",
    "Datum": "DATUM", "Tidsperiod": "TIDSPERIOD",
}
CONTRACT_REL = {
    "Uppsägningstid": "UPPSÄGNING", "Förlängning": "FÖRLÄNGNING",
    "Avgångsvederlag": "ERSÄTTNING", "Ersättning": "ERSÄTTNING",
    "Vite": "FÖRSENING", "Ansvarstak": "ANSVAR", "Undantag": "UNDANTAG",
    "Uppsägningsvillkor": "UPPSÄGNING", "Belopp": "BELOPP",
    "Datum": "DATUM", "Avtalspart": "PART", "Tidsperiod": "ANNAT",
}


def fixture_key(case_id, span, version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{version}".encode("utf-8")
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

    def ask(self, case_id, clause, span, version, instructions, options):
        key = fixture_key(case_id, span, version)
        if key in self.store:
            return self.store[key]["choice"], False
        criteria = {o: o for o in options}
        body = json.dumps({
            "model": self.model,
            "state": {"text": clause},
            "questions": {
                "evidence": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
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


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]

    # Freeze the candidate population WITH GLiNER2 labels (one local pass).
    from gliner2 import AutoExtractor
    extractor = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")
    if CANDIDATES_V2.exists():
        pop = json.load(open(CANDIDATES_V2, encoding="utf-8"))
    else:
        pop = {}
        for case in cases:
            cid = case["case_id"]
            labels = [NEED_LABELS[t] for t in {g["type"] for g in case["gold"]}][:3]
            raw = extractor.extract_entities(case["clause"], entity_types=labels,
                                             threshold=0.3, format_results=False)
            entries = {}
            for entry in raw.get("entities", []):
                for label, spans in entry.items():
                    for span in spans:
                        entries.setdefault(normalize(span), {"raw": span, "label": label})
            for g in case["gold"]:
                entries.setdefault(normalize(g["span"]), {"raw": g["span"], "label": None})
            for t, s in spans_of(case["clause"]):
                entries.setdefault(normalize(s), {"raw": s, "label": None})
            pop[cid] = entries
        json.dump(pop, open(CANDIDATES_V2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"kandidater med etiketter frysta: {sum(len(v) for v in pop.values())} spann")

    rec = JevRecorder(api_key, base, model)
    results = {}

    for arm in ["H1_typ_accepteras", "H2_konfliktkontroll"]:
        verdicts = {}
        calls_before = rec.new_calls
        for case in cases:
            cid = case["case_id"]
            need = NEED_LABELS[case["need"]]
            contract_type = LABEL_TO_CONTRACT.get(need, "ANNAT")
            contract_rel = CONTRACT_REL.get(need, "ANNAT")
            verdicts[cid] = {}
            for span_norm, info in pop[cid].items():
                raw = info["raw"]
                label = info["label"]
                # --- Type stage: GLiNER2's label is the proposal ---
                candidate_type = LABEL_TO_CONTRACT.get(label or "", None)
                if candidate_type is None:
                    candidate_type = "ANNAT"
                if arm == "H2_konfliktkontroll":
                    # Conflict/uncertainty: deterministic signals disagree
                    # with the label, or the label is missing.
                    conflict = False
                    if DURATION_RE.search(raw) and candidate_type not in ("TIDSPERIOD",):
                        conflict = True
                    if label is None:
                        conflict = True
                    if conflict:
                        typ_choice, _ = rec.ask(
                            cid, case["clause"], raw, "stage-type-v1",
                            f"Vilken typ av sakförhållande utgör det exakta spannet '{raw}'? "
                            "Svara med ett av alternativen.",
                            ["TIDSPERIOD", "BELOPP", "DATUM", "PART", "VILLKOR", "ANNAT"],
                        )
                        candidate_type = typ_choice
                if candidate_type != contract_type:
                    verdicts[cid][span_norm] = ("typ", candidate_type)
                    continue
                # --- Relation stage: JEV's semantic decision ---
                rel_choice, _ = rec.ask(
                    cid, case["clause"], raw, "stage-relation-v1",
                    f"Vad är spannet '{raw}' i klausulen kopplat till? Svara med ett av alternativen.",
                    ["UPPSÄGNING", "AVTALSTID", "FÖRLÄNGNING", "BETALNING", "ANSVAR",
                     "UNDANTAG", "ERSÄTTNING", "FÖRSENING", "BELOPP", "DATUM", "PART", "ANNAT"],
                )
                if rel_choice != contract_rel:
                    verdicts[cid][span_norm] = ("relation", rel_choice)
                    continue
                # --- Relevance: only for VILLKOR needs (the contract
                # needs the specific clause support), else relation
                # already satisfies the need ---
                if contract_type == "VILLKOR":
                    ok, _ = rec.ask(
                        cid, case["clause"], raw, "stage-relevance-v1",
                        f"Uppfyller klausulen informationsbehovet '{need}' med just detta spann?",
                        ["YES", "NO", "UNCERTAIN"],
                    )
                    if ok == "YES":
                        verdicts[cid][span_norm] = ("godkänd", None)
                    else:
                        verdicts[cid][span_norm] = ("relevans", ok)
                else:
                    verdicts[cid][span_norm] = ("godkänd", None)
        rec.save()

        gold = {c["case_id"]: {normalize(g["span"]) for g in c["gold"]} for c in cases}
        det = {c["case_id"]: {normalize(s) for _, s in spans_of(c["clause"])} for c in cases}
        unique_ok = 0
        unique_total = 0
        fp = 0
        tp = 0
        correct_resolved = 0
        false_resolved = 0
        dropouts = {"typ": 0, "relation": 0, "relevans": 0}
        for case in cases:
            cid = case["case_id"]
            g = gold[cid]
            all_ok = True
            for gs in g:
                if gs in det[cid]:
                    continue
                unique_total += 1
                step, _c = verdicts[cid].get(gs, ("relation", None))
                if step == "godkänd":
                    unique_ok += 1
                else:
                    dropouts[step] = dropouts.get(step, 0) + 1
                    all_ok = False
            if not all_ok:
                continue
            wrong_approved = any(
                step == "godkänd" and s not in g
                for s, (step, _c) in verdicts[cid].items()
            )
            if wrong_approved:
                false_resolved += 1
            else:
                correct_resolved += 1
            for s, (step, _c) in verdicts[cid].items():
                if step == "godkänd":
                    if s in g:
                        tp += 1
                    else:
                        fp += 1
        prec = tp / (tp + fp) if tp + fp else 0.0
        results[arm] = {
            "unique_recall": f"{unique_ok}/{unique_total}",
            "precision": round(prec, 3),
            "fp": fp,
            "correctly_resolved": correct_resolved,
            "false_resolved": false_resolved,
            "dropouts": dropouts,
            "jev_calls": rec.new_calls - calls_before,
        }
        print(f"{arm:<22} unik {unique_ok}/{unique_total}  prec {prec:.2f}  fp {fp:>3}  "
              f"rätt lösta {correct_resolved:>2}  FALSKT lösta {false_resolved:>2}  "
              f"nedfall {dropouts}  (JEV {results[arm]['jev_calls']})")

    # D recomputed with the SAME need_id definition.
    d_false = 0
    d_correct = 0
    d_fp = 0
    d_tp = 0
    d_unique_ok = 0
    d_unique_total = 0
    for case in cases:
        cid = case["case_id"]
        g = {normalize(gs["span"]) for gs in case["gold"]}
        d_det = {normalize(s) for _, s in spans_of(case["clause"])}
        verdicts_d = {}
        all_ok = True
        for gs in g:
            if gs in d_det:
                continue
            d_unique_total += 1
            key = fixture_key(cid, gs, "span-need-contrast-v1")
            choice = rec.store.get(key, {}).get("choice")
            if choice == "YES":
                d_unique_ok += 1
            else:
                all_ok = False
        if not all_ok:
            continue
        wrong_approved = False
        for span_norm, info in pop[cid].items():
            key = fixture_key(cid, info["raw"], "span-need-contrast-v1")
            choice = rec.store.get(key, {}).get("choice")
            if choice == "YES":
                if span_norm in g:
                    d_tp += 1
                else:
                    d_fp += 1
                    wrong_approved = True
        if wrong_approved:
            d_false += 1
        else:
            d_correct += 1
    print(f"\nD omräknad (samma need_id-definition): unik {d_unique_ok}/{d_unique_total}, "
          f"fp {d_fp}, rätt lösta {d_correct}, FALSKT lösta {d_false}")
    results["D_recomputed"] = {
        "unique_recall": f"{d_unique_ok}/{d_unique_total}",
        "fp": d_fp,
        "correctly_resolved": d_correct,
        "false_resolved": d_false,
    }

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
