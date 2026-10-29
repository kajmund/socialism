#!/usr/bin/env python3
"""E3 — operational-role check (isolated, own version): normalization must
never make two different operational roles equivalent.

The unambiguity check compares candidates that share the need's OPERATIONAL
ROLE, not just the normalized type. Candidate roles are derived
deterministically from the clause context (closest role cue to the span;
tie -> undeterminable). A candidate whose role cannot be determined is
treated as competing — the conflict never disappears silently.

Frozen inputs: blindtest v1 artifacts, E1 span-date-v1 verdicts (fixture),
E2 canonical values. No model calls.

Run: python3 crates/swe-gym/tools/exp_role_check.py
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
FACIT = json.load(open(B / "blindtest_facit_v1.json", encoding="utf-8"))
EVAL = json.load(open(B / "blindtest_facit_v1_eval.json", encoding="utf-8"))
E3 = json.load(open(B / "blindtest_e3_facit_v1.json", encoding="utf-8"))
FIXTURE = {e["key"]: e for e in
           json.load(open(B / "jev_span_fixtures.json", encoding="utf-8"))["entries"]}

LEADING = {"inom", "i", "under", "senast", "den", "det", "de", "en", "ett"}
GENITIVE = {"dagars": "dagar", "veckors": "veckor", "månaders": "månader",
            "års": "år", "timmars": "timmar"}

# Closed role-cue vocabulary. Roles are coarse operational classes; a span
# gets the role of the nearest cue word in the clause (tie -> unknown).
CUES = {
    "NOTICE": ["uppsägningstid", "uppsägning", "varsel", "frånträda", "upphöra"],
    "DURATION": ["gäller", "löper", "längd", "avtalstid"],
    "DEADLINE": ["inom", "senast", "efter", "betalning", "betalningsvillkor",
                 "faktura", "fakturan", "frist", "tillhanda", "erläggs",
                 "förfallodatum", "utbetalning", "utbetala"],
    "MONEY": ["belopp", "kr", "arvode", "arvodet", "ersättning", "pris",
              "timpris", "lön", "garanterar", "betalar", "sponsorbidrag",
              "procent"],
    "PARTY": ["benämnd", "kallas", "parter", "mellan", "aktiebolag", "klubb",
              "ab"],
    "LIABILITY": ["ansvar", "begränsat", "begräns"],
    "SEMESTER": ["semester"],
    "EVENT": ["startdatum", "tillträdesdag", "simning", "exponerad", "nuss"],
}


def canon(s):
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip().lower()


def despace(s):
    """Remove ALL whitespace — robust against the whitespace artifacts
    embedded in the extracted Konsulttjänst text (e.g. 'upps ä gningstid')."""
    return re.sub(r"\s+", "", canon(s))


def canon_value(s):
    words = canon(s).split()
    while words and words[0] in LEADING:
        words = words[1:]
    words = [GENITIVE.get(w, w) for w in words]
    return " ".join(words)


def role_of(original_span, clause):
    """Closest-role-cue rule: cues are matched on the de-spaced text (robust
    against the whitespace artifacts in the extracted text) but must satisfy
    word boundaries in the ORIGINAL text — so 'senast' never matches inside
    'senaste' and 'kr' never matches inside '45000kr'. The role of the cue
    with minimal character distance to the span wins; a tie between two
    different roles -> undeterminable (fail-safe downstream)."""
    ctext = despace(clause)
    otext = canon(clause)
    jmap = []  # de-spaced index -> original index
    for j, ch in enumerate(otext):
        if not ch.isspace():
            jmap.append(j)
    sval = despace(original_span)
    pos = ctext.find(sval)
    if pos < 0:
        return None
    span_end = pos + len(sval)
    best_role, best_dist = None, None
    for role, words in CUES.items():
        for w in words:
            wd = despace(w)
            idx = ctext.find(wd)
            while idx >= 0:
                ob = jmap[idx] if idx < len(jmap) else len(otext)
                oe = jmap[idx + len(wd)] if idx + len(wd) < len(jmap) else len(otext)
                before_ok = ob == 0 or not otext[ob - 1].isalnum()
                after_ok = oe >= len(otext) or not otext[oe].isalnum()
                if before_ok and after_ok:
                    d = max(pos - (idx + len(wd)), idx - span_end, 0)
                    if best_dist is None or d < best_dist:
                        best_role, best_dist = role, d
                    elif d == best_dist and role != best_role:
                        return None  # tie -> undeterminable
                idx = ctext.find(wd, idx + 1)
    return best_role


def date_approved(case_id):
    return {canon_value(e["span"]) for e in FIXTURE.values()
            if e["case_id"] == case_id and e["prompt_version"] == "span-date-v1"
            and e["choice"] == "YES"}


def main():
    clauses = {c["case_id"]: c["clause"] for c in FACIT["cases"]}
    date_cases = {c["case_id"] for c in FACIT["cases"]
                  if any(n["type"] == "DATE" for n in c["needs"])}
    per_case = {r["case_id"]: r for r in EVAL["per_case"]}
    rows = []
    for cid, r in per_case.items():
        need_role = E3["roles"][cid]
        gold = {canon_value(g) for g in r["gold"]}
        extracted = {canon_value(s) for s in r["extracted_same_type"]}
        approved = date_approved(cid) if cid in date_cases else \
            {canon_value(s) for s in r["approved"]}
        glin = {canon_value(s) for s in r["gliner_candidates"]}
        cands = {}  # canonical value -> original span form (for location)
        for s in r["approved"]:
            cv = canon_value(s)
            if cv in glin and cv not in gold:
                cands[cv] = canon(s)
        for s in r["extracted_same_type"]:
            cv = canon_value(s)
            if cv not in gold:
                cands[cv] = canon(s)
        competing = set()
        role_map = {}
        for cv, orig in cands.items():
            role = role_of(orig, clauses[cid])
            role_map[cv] = role
            if role is None or role == need_role:
                competing.add(cv)  # unknown role -> conflict stays visible
        resolved = bool(gold) and all(g in approved or g in extracted for g in gold)
        if resolved and len(competing) >= 2:
            verdict = "ambiguous"
        elif resolved:
            verdict = "resolved"
        elif len(competing) >= 2:
            verdict = "ambiguous"
        elif competing:
            verdict = "false_resolved"
        else:
            verdict = "unsolved"
        rows.append({"case_id": cid, "verdict": verdict,
                     "need_role": need_role,
                     "competing": sorted(competing),
                     "role_of_competing": role_map})
    flips = []
    for row in rows:
        old = per_case[row["case_id"]]["verdict"]
        if old != row["verdict"]:
            flips.append(f"{row['case_id']}: {old} -> {row['verdict']}")
    print("E3 — operativ roll-kontroll (inga modellanrop)\n")
    for f in flips:
        print("  FLIP:", f)
    if not flips:
        print("  inga flippar mot D10 v2-verdicts")
    bt17 = next(r for r in rows if r["case_id"] == "bt-17")
    print(f"\nbt-17: verdict={bt17['verdict']} competing={bt17['competing']} "
          f"roller={bt17['role_of_competing']}")
    out = B / "blindtest_e3_v1.json"
    json.dump({"version": 1, "need_roles": E3["roles"], "rows": rows,
               "flips": flips}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"skrivet: {out}")


if __name__ == "__main__":
    main()
