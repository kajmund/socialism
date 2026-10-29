#!/usr/bin/env python3
"""Staged verification arms E/F/G (docs/architecture/gliner2-jevspan
-evaluation.md, D6): entity type -> relation -> evidence relevance as
separate decisions, with deterministic shortcuts where the code is
unambiguous. Every candidate's drop-out point is captured (type /
relation / relevance / approved), and false RESOLVED is counted per
unique need_id (a need whose resolution would use a wrong value).
Arm D stays the comparison; the same frozen candidate population.

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_verification_stages.py
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
NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}
from eval_gliner_challenge import env_value, normalize  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
CANDIDATES = B / "gliner_candidates.json"
OUT = B / "verification_stages.json"

DURATION_RE = re.compile(
    r"\[?\s*(?:([a-zåäö]+)\s*\(?(\d{1,2})\)?|(\d{1,2}))\s*\]?\s*"
    r"(månad(?:er|s)?|dag(?:ar|s)?|veck(?:or|a)?|år)\b",
    re.IGNORECASE,
)
MONEY_RE = re.compile(r"kronor|procent av|månadsarvod|arvode", re.IGNORECASE)
DATE_RE = re.compile(r"\[\d{4}-\d{2}-\d{2}\]|\d{4}-\d{2}-\d{2}")
TERM_RE = re.compile(r"upps(ä|a)g|s(ä|a)ger upp|s(ä|a)gs upp|s(ä|a)gas upp|varsel|frånträda|bringa att upphöra", re.IGNORECASE)
RENEW_RE = re.compile(r"förl(ä|a)ng|förny|fortlöper", re.IGNORECASE)
DURATION_CONTRACT = {
    "Uppsägningstid": ("TIDSPERIOD", "UPPSÄGNING"),
    "Förlängning": ("TIDSPERIOD", "FÖRLÄNGNING"),
    "Avgångsvederlag": ("VILLKOR", "ERSÄTTNING"),
    "Ersättning": ("VILLKOR", "ERSÄTTNING"),
    "Vite": ("VILLKOR", "FÖRSENING"),
    "Ansvarstak": ("VILLKOR", "ANSVAR"),
    "Undantag": ("VILLKOR", "UNDANTAG"),
    "Uppsägningsvillkor": ("VILLKOR", "UPPSÄGNING"),
    "Belopp": ("BELOPP", "BELOPP"),
    "Datum": ("DATUM", "DATUM"),
    "Avtalspart": ("PART", "PART"),
    "Tidsperiod": ("TIDSPERIOD", "ANNAT"),
}
CONTRASTS = {
    "Uppsägningstid": "En uppsägningstid är inte samma sak som avtalstid, förlängningsperiod eller betalningsfrist.",
    "Förlängning": "En förlängningsperiod är inte samma sak som uppsägningstid eller avtalstid.",
}


def det_type(span):
    if DURATION_RE.search(span):
        return "TIDSPERIOD", True
    if DATE_RE.search(span):
        return "DATUM", True
    if MONEY_RE.search(span):
        return "BELOPP", True
    return None, False


def det_relation(span, clause):
    text = clause.lower()
    if TERM_RE.search(text):
        return "UPPSÄGNING", True
    if RENEW_RE.search(text):
        return "FÖRLÄNGNING", True
    if re.search(r"betal|frist", text, re.IGNORECASE):
        return "BETALNING", True
    if re.search(r"ansvar|begräns", text, re.IGNORECASE):
        return "ANSVAR", True
    if re.search(r"undantag", text, re.IGNORECASE):
        return "UNDANTAG", True
    return None, False


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


def jev_type(rec, cid, clause, span):
    return rec.ask(
        cid, clause, span, "stage-type-v1",
        f"Vilken typ av sakförhållande utgör det exakta spannet '{span}'? "
        "Svara med ett av alternativen.",
        ["TIDSPERIOD", "BELOPP", "DATUM", "PART", "VILLKOR", "ANNAT"],
    )


def jev_relation(rec, cid, clause, span):
    return rec.ask(
        cid, clause, span, "stage-relation-v1",
        f"Vad är spannet '{span}' i klausulen kopplat till? Svara med ett av alternativen.",
        ["UPPSÄGNING", "AVTALSTID", "FÖRLÄNGNING", "BETALNING", "ANSVAR", "UNDANTAG", "ERSÄTTNING", "FÖRSENING", "BELOPP", "DATUM", "PART", "ANNAT"],
    )


def jev_relevance(rec, cid, clause, span, need):
    contrast = CONTRASTS.get(need, "Bedöm enbart spannet.")
    return rec.ask(
        cid, clause, span, "stage-relevance-v1",
        f"Uppfyller klausulen informationsbehovet '{need}' med just detta spann? {contrast}",
        ["YES", "NO", "UNCERTAIN"],
    )


def main():
    api_key = env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("TYPESAFE_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    base = env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")

    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]
    pop = json.load(open(CANDIDATES, encoding="utf-8"))
    raw_spans = {}
    for case in cases:
        cid = case["case_id"]
        clause_norm = {normalize(g["span"]): g["span"] for g in case["gold"]}
        for t, s in spans_of(case["clause"]):
            clause_norm.setdefault(normalize(s), s)
        raw_spans[cid] = clause_norm

    rec = JevRecorder(api_key, base, model)
    results = {}
    calls_before = rec.new_calls
    for arm in ["E_full_jev", "F_dettyp_jevrel", "G_maxdet"]:
        verdicts = {}   # cid -> {span_norm: ("ok"|dropout-step, choice)}
        for case in cases:
            cid = case["case_id"]
            need = NEED_LABELS[case["need"]]
            contract_type, contract_rel = DURATION_CONTRACT.get(need, ("ANNAT", "ANNAT"))
            verdicts[cid] = {}
            for span_norm in pop[cid]:
                raw = raw_spans[cid].get(span_norm, span_norm)
                # --- Type stage ---
                if arm == "E_full_jev":
                    typ, _ = jev_type(rec, cid, case["clause"], raw)
                    typ_known = True
                else:
                    typ, typ_known = det_type(raw)
                    if not typ_known and arm == "F_dettyp_jevrel":
                        typ, _ = jev_type(rec, cid, case["clause"], raw)
                        typ_known = True
                if typ != contract_type:
                    verdicts[cid][span_norm] = ("typ", typ)
                    continue
                # --- Relation stage ---
                if arm == "E_full_jev":
                    rel, _ = jev_relation(rec, cid, case["clause"], raw)
                    rel_known = True
                else:
                    rel, rel_known = det_relation(raw, case["clause"])
                    if not rel_known:
                        rel, _ = jev_relation(rec, cid, case["clause"], raw)
                        rel_known = True
                if rel != contract_rel:
                    verdicts[cid][span_norm] = ("relation", rel)
                    continue
                # --- Relevance stage (only when needed) ---
                if rel == contract_rel and typ == contract_type:
                    # F/G: relation already satisfies the need contract —
                    # relevance call only at uncertainty or for VILLKOR.
                    if contract_type == "VILLKOR" or arm == "E_full_jev":
                        ok, _ = jev_relevance(rec, cid, case["clause"], raw, need)
                        if ok == "YES":
                            verdicts[cid][span_norm] = ("godkänd", None)
                        else:
                            verdicts[cid][span_norm] = ("relevans", ok)
                    else:
                        verdicts[cid][span_norm] = ("godkänd", None)
                else:
                    verdicts[cid][span_norm] = ("relation", rel)
        rec.save()

        # Metrics per unique need_id.
        gold = {
            c["case_id"]: {normalize(g["span"]): g["span_id"] for g in c["gold"]}
            for c in cases
        }
        det = {
            c["case_id"]: {normalize(s) for _, s in spans_of(c["clause"])}
            for c in cases
        }
        solved = 0
        false_resolved = 0
        correct_resolved = 0
        fp = 0
        tp = 0
        unique_ok = 0
        unique_total = 0
        dropouts = {"typ": 0, "relation": 0, "relevans": 0}
        for case in cases:
            cid = case["case_id"]
            g = gold[cid]
            all_ok = True
            for gs in g:
                if gs in det[cid]:
                    continue
                unique_total += 1
                step, choice = verdicts[cid].get(gs, ("relation", None))
                if step == "godkänd":
                    unique_ok += 1
                else:
                    dropouts[step] = dropouts.get(step, 0) + 1
                    all_ok = False
            if not all_ok:
                continue
            solved += 1
            # False RESOLVED per need_id: the need is resolved but a
            # wrong-type span was also approved (the conclusion could
            # use the wrong value).
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
            "correctly_resolved_needs": correct_resolved,
            "false_resolved_needs": false_resolved,
            "solved_needs": solved,
            "dropouts": dropouts,
            "new_jev_calls": rec.new_calls - calls_before,
        }
        calls_before = rec.new_calls
        print(f"{arm:<16} unik {unique_ok}/{unique_total}  prec {prec:.2f}  fp {fp:>3}  "
              f"rätt lösta {correct_resolved:>2}  FALSKT lösta {false_resolved:>2}  "
              f"nedfall {dropouts}  (nya JEV {rec.new_calls})")
    rec.save()
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()
