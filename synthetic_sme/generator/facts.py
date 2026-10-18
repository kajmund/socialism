"""Generate the story factsheet (facts.md / facts.json) from the truth model.

Used by the question author, facit builder and document authors as the single
overview of entities, events and key figures. Regenerated on every run so the
numbers can never go stale.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator import config  # noqa: E402
from generator import compute as C  # noqa: E402
from generator.model import Model  # noqa: E402


def _d(x):
    return x if isinstance(x, str) else x.isoformat()


def _name(m, persons, pid):
    for p in persons:
        if getattr(p, "id", None) == pid:
            return f"{p.first} {p.last}"
    return pid or ""


def build_facts(m: Model) -> dict:
    out = {}
    out["company"] = config.COMPANY
    out["period"] = {"history": ["2024-10-01", "2026-09-30"], "analysis_date": "2026-10-18",
                     "fiscal_years": {"FY2025": ["2024-10-01", "2025-09-30"],
                                      "FY2026": ["2025-10-01", "2026-09-30"]}}
    out["employees"] = [
        {"id": e.id, "person_id": e.person_id, "name": _name(m, m.persons, e.person_id),
         "emp_no": e.emp_no, "title": e.title, "dept": e.dept, "level": e.level,
         "hired": _d(e.hired), "left": _d(e.left) if e.left else None,
         "salary": (e.salary[-1]["amount"] if isinstance(e.salary[-1], dict) else e.salary[-1].amount), "billing_rate": e.billing_rate,
         "current": e.current, "note": e.note}
        for e in m.employees]
    out["customers"] = [
        {"id": c.id, "name": c.name, "segment": c.segment, "industry": c.industry,
         "status": c.status, "is_key": c.is_key, "payment_profile": c.payment_profile,
         "credit_days": c.credit_days, "note": c.note}
        for c in m.customers]
    out["suppliers"] = [
        {"id": s.id, "name": s.name, "category": s.category,
         "is_subcontractor": s.is_subcontractor, "note": s.note}
        for s in m.suppliers]
    out["projects"] = [
        {"id": p.id, "code": p.code, "customer_id": p.customer_id, "name": p.name,
         "ptype": p.ptype, "start": _d(p.start), "end": _d(p.end) if p.end else None,
         "status": p.status, "contract_id": p.contract_id, "billing_model": p.billing_model,
         "fixed_amount": p.fixed_amount, "note": p.note}
        for p in m.projects]
    out["events"] = [
        {"id": e.id, "date": _d(e.date), "etype": e.etype, "title": e.title,
         "description": e.description, "note": e.note}
        for e in m.events]
    # key figures
    rev = {fy: str(C.total_revenue(m.customer_invoices, fy)) for fy in ("FY2025", "FY2026")}
    out["key_figures"] = {
        "revenue_net": rev,
        "seab_share_pct": {"FY2025": str(C.seab_share(m.customer_invoices, "FY2025")),
                           "FY2026": str(C.seab_share(m.customer_invoices, "FY2026"))},
        "net_results": {"FY2025": m.secret["net_result_2025"], "FY2026": m.secret["net_result_2026"]},
        "tax": m.secret.get("tax_FY2026", {}),
        "cash_at_end": str(C.cash_at(m.postings, "2026-09-30")),
        "overdraft_drawn_at_end": str(C.overdraft_at(m.postings, "2026-09-30")),
        "max_overdraft_drawn": None,
        "bad_debt": m.secret.get("bad_debt_amount", "0"),
        "bank_loan_balance_at_end": "0.00 (slutamorterat)",
        "max_overdraft_drawn": str(max(
            (C.overdraft_at(m.postings, f"{mk}-30") for mk in
             [f"{y:04d}-{mo:02d}" for (y, mo) in
              __import__("generator.util", fromlist=["month_range"]).month_range(
                  __import__("generator.config", fromlist=["HIST_START"]).HIST_START,
                  __import__("generator.config", fromlist=["HIST_END"]).HIST_END)]),
            default=__import__("decimal").Decimal("0"))),
        "open_ar_total": str(sum(C.open_ar(m.customer_invoices).values(), __import__("decimal").Decimal("0"))),
        "open_ap_total": None,
    }
    # anomalies
    out["anomalies"] = [
        {"id": "KF-UNDERBILLING",
         "description": "KF-Biljettsystem (CUS-005): indexhöjning 1 050 -> 1 150 kr/h gällde fr.o.m. 2025-11-01 men debiterades först fr.o.m. 2026-02-01. Eftersläpningsfaktura utfärdad 2026-02-28.",
         "computed": {"catchup_net": str(C.underbilling_total(m.schedule("SCH-008"), ["2025-11", "2025-12", "2026-01"], 100))}},
        {"id": "GV-MISSED-INDEX",
         "description": "Gråvikens kommun (CUS-002, CTR-2022-007): KPI-uppräkning per 2025-10-01 (bas 2023-10) har inte tillämpats i faktureringen.",
         "computed": {"correct_rate": C.index_adjusted_rate(1050, "2023-10", "2025-10"),
                      "missed_net": str(C.missed_index_total(m.schedule("SCH-004"), "2025-10", "2023-10",
                                                             C.index_adjusted_rate(1050, "2023-10", "2025-10")))}},
        {"id": "BV-MISSED-INDEX",
         "description": "Blåklintens Vård (CUS-007, CTR-2023-018): KPI-uppräkning per 2026-04-01 (bas 2024-04) har inte tillämpats i faktureringen.",
         "computed": {"correct_rate": C.index_adjusted_rate(990, "2024-04", "2026-04"),
                      "missed_net": str(C.missed_index_total(m.schedule("SCH-010"), "2026-04", "2024-04",
                                                             C.index_adjusted_rate(990, "2024-04", "2026-04")))}},
        {"id": "TS-CREDIT-NOTE", "description": "Timmervikens Såg: viteförlikning, kreditnota 90 000 kr (inkl. moms) 2026-06-30."},
        {"id": "SB-BAD-DEBT", "description": "Sjöstadens Bryggeri i konkurs 2025-12-08; september- och novemberfakturorna (totalt 220 065,00 kr inkl. moms) avskrivna som kundförlust 2025-12-31 (septemberfakturan hölls inne p.g.a. reklamation; oktoberfakturan betalades sent 2025-11-20)."},
        {"id": "OH-DISPUTE", "description": "Örby Handel: tvist om slutfaktura; 96 800 kr (inkl. moms) hålls inne, fordran tvistig."},
        {"id": "FS-ACCRUAL", "description": "FS-Intranät slutfaktura 300 000 kr ex moms fakturerades efter periodens slut (2025-10-10); 240 000 kr periodiserades som upplupen intäkt 2025-09-30."},
    ]
    return out


def main() -> None:
    m = Model().load(ROOT / "ground_truth" / "truth_model.json")
    facts = build_facts(m)
    import json
    (ROOT / "generator" / "data" / "facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# Story factsheet – Nordviken Digital AB (generated, do not edit)",
             f"Analysis date: 2026-10-18 | History: 2024-10-01 – 2026-09-30 | "
             f"Fiscal years: FY2025 (2024-10-01–2025-09-30), FY2026 (2025-10-01–2026-09-30)", ""]
    for sec in ("employees", "customers", "suppliers", "projects", "events", "anomalies"):
        lines.append(f"## {sec}")
        for item in facts[sec]:
            lines.append("  " + str(item))
        lines.append("")
    lines.append("## key_figures")
    lines.append("  " + str(facts["key_figures"]))
    (ROOT / "generator" / "data" / "facts.md").write_text("\n".join(lines), encoding="utf-8")
    print("factsheet written")


if __name__ == "__main__":
    main()
