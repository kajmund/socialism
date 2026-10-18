"""Accounting exports: CSV/JSON views derived from the truth model.

Every file in accounting/ is derived from the same postings and registers –
never generated independently.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from . import config
from .model import Model
from .util import month_key, month_range

ROOT = Path(__file__).resolve().parent.parent
ACCT = ROOT / "accounting"

MONTHS = [month_key(d) for (y, m) in month_range(config.HIST_START, config.HIST_END)
          for d in [__import__("datetime").date(y, m, 1)]]


def _w(path: Path, rows: list[list], header: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


def export_all(m: Model) -> dict:
    out: dict[str, str] = {}
    out.update(export_gl(m))
    out.update(export_ar(m))
    out.update(export_ap(m))
    out.update(export_banking(m))
    out.update(export_payroll(m))
    out.update(export_tax(m))
    out.update(export_reports(m))
    out.update(export_projects(m))
    out.update(export_time(m))
    return out


def _fy(datestr: str) -> str:
    return "FY2025" if datestr <= "2025-09-30" else "FY2026"


# ------------------------------------------------------------------ GL
def export_gl(m: Model) -> dict:
    rows = []
    for p in m.postings:
        rows.append([p["date"], p["voucher_id"], p["account"],
                     next((a["name"] for a in m.accounts if a["number"] == p["account"]), ""),
                     p["amount"], p.get("event_id", "") or ""])
    _w(ACCT / "general_ledger" / "huvudbok.csv", rows,
       ["Datum", "Verifikation", "Konto", "Kontonamn", "Belopp", "Händelse"])
    rows2 = []
    for v in m.vouchers:
        rows2.append([v["id"], v["series"], v["date"], v["text"], len(v["rows"]),
                      sum(float(b) for _, b in v["rows"]), v.get("event_id", "") or ""])
    _w(ACCT / "general_ledger" / "verifikationsregister.csv", rows2,
       ["Verifikation", "Serie", "Datum", "Text", "Rader", "Kontrollsumma", "Händelse"])
    # trial balance per month end
    tb = []
    for mk in MONTHS:
        last = f"{mk}-28"
        bal = defaultdict(Decimal)
        for p in m.postings:
            if p["date"] <= last:
                bal[p["account"]] += Decimal(p["amount"])
        for acc in sorted(bal):
            if bal[acc] != 0:
                tb.append([mk, acc, str(bal[acc])])
    _w(ACCT / "general_ledger" / "saldo_per_manad.csv", tb, ["Månad", "Konto", "Saldo"])
    return {"general_ledger/huvudbok.csv": "Huvudbok (samtliga bokföringsposter)",
            "general_ledger/verifikationsregister.csv": "Verifikationsregister",
            "general_ledger/saldo_per_manad.csv": "Kontosaldon per månadsslut"}


# ------------------------------------------------------------------ AR
def export_ar(m: Model) -> dict:
    rows = []
    for inv in m.customer_invoices:
        cus = next((c for c in m.customers if getattr(c, "id", None) == inv["customer_id"]), None)
        rows.append([inv["id"], inv["date"], inv.get("due_date", ""), inv["customer_id"],
                     getattr(cus, "name", "") if cus else "",
                     inv["net"], inv["vat"], inv["gross"], inv["status"],
                     inv.get("paid_date", "") or "", inv.get("paid_amount", "") or "",
                     inv.get("project_id", "") or "", inv.get("contract_id", "") or "",
                     inv.get("note", "") or ""])
    _w(ACCT / "accounts_receivable" / "kundreskontra.csv", rows,
       ["Faktura", "Fakturadatum", "Förfallodatum", "Kund", "Kundnamn", "Netto", "Moms",
        "Brutto", "Status", "Betalningsdatum", "Betalt belopp", "Projekt", "Avtal", "Not"])
    # open items at analysis date
    open_rows = [r for r in rows if r[7] in ("OPEN", "PARTIAL", "CREDIT_NOTE")]
    _w(ACCT / "accounts_receivable" / "kundreskontra_oppna.csv", open_rows,
       ["Faktura", "Fakturadatum", "Förfallodatum", "Kund", "Kundnamn", "Netto", "Moms",
        "Brutto", "Status", "Betalningsdatum", "Betalt belopp", "Projekt", "Avtal", "Not"])
    return {"accounts_receivable/kundreskontra.csv": "Kundreskontra (alla fakturor)",
            "accounts_receivable/kundreskontra_oppna.csv": "Öppna kundfordringar per 2026-10-18"}


# ------------------------------------------------------------------ AP
def export_ap(m: Model) -> dict:
    rows = []
    for inv in m.supplier_invoices:
        sup = next((s for s in m.suppliers if getattr(s, "id", None) == inv["supplier_id"]), None)
        rows.append([inv["id"], inv["date"], inv["due_date"], inv["supplier_id"],
                     getattr(sup, "name", "") if sup else "",
                     inv["account"], inv["label"], inv["net"], inv["vat"], inv["gross"],
                     inv["status"], inv.get("paid_date", "") or "",
                     inv["reverse_charge"], inv.get("stream_id", "") or ""])
    _w(ACCT / "accounts_payable" / "leverantorsreskontra.csv", rows,
       ["Faktura", "Fakturadatum", "Förfallodatum", "Leverantör", "Leverantörsnamn",
        "Konto", "Avser", "Netto", "Moms", "Brutto", "Status", "Betald", "Omvänd skattskyldighet", "Ström"])
    return {"accounts_payable/leverantorsreskontra.csv": "Leverantörsreskontra"}


# ------------------------------------------------------------------ banking
def export_banking(m: Model) -> dict:
    rows = [[t["date"], t["text"], t["amount"], t["ref"]] for t in m.bank_txns]
    _w(ACCT / "banking" / "banktransaktioner.csv", rows, ["Datum", "Text", "Belopp", "Referens"])
    # monthly statements with running balance
    stmt = []
    run = Decimal("2600000.00")
    cur = None
    for t in m.bank_txns:
        mk = t["date"][:7]
        if mk != cur:
            cur = mk
            stmt.append([mk, "Ingående saldo", "", str(run)])
        run += Decimal(t["amount"])
        stmt.append([mk, t["date"], t["text"], t["amount"], str(run)])
    _w(ACCT / "banking" / "bankkontoutdrag.csv", stmt,
       ["Månad", "Datum", "Text", "Belopp", "Saldo"])
    return {"banking/banktransaktioner.csv": "Samtliga banktransaktioner (1930)",
            "banking/bankkontoutdrag.csv": "Bankkontoutdrag per månad med löpande saldo"}


# ------------------------------------------------------------------ payroll
def export_payroll(m: Model) -> dict:
    rows = []
    for r in m.payroll_runs:
        rows.append([r["month"], r["pay_date"], r["employees"], r["gross"], r["severance"],
                     r["vacation_pay"], r["pension_premium"], r["employer_fee"],
                     r["withholding"], r["net_pay"], r["voucher_id"]])
    _w(ACCT / "payroll" / "loneunderlag.csv", rows,
       ["Månad", "Utbetalningsdag", "Antal anställda", "Bruttolön", "Avgångsvederlag",
        "Semesterlön (juni)", "Pensionspremie", "Arbetsgivaravgift", "Källskatt", "Nettolön", "Verifikation"])
    # per employee annual summary
    emp_rows = []
    for e in m.employees:
        if not e.current:
            continue
        emp_rows.append([e.emp_no, next((p.first + " " + p.last for p in m.persons if p.id == e.person_id), ""),
                         e.title, e.hired.isoformat(), e.salary[-1].amount])
    _w(ACCT / "payroll" / "lonelista_aktuell.csv", emp_rows,
       ["Anstnr", "Namn", "Befattning", "Anställd", "Månadslön"])
    # all employees incl. former (supports GQ-071: the lönelistan counts every person
    # with a paid salary; the HR report may use another window)
    all_rows = []
    for e in m.employees:
        all_rows.append([e.emp_no, next((p.first + " " + p.last for p in m.persons if p.id == e.person_id), ""),
                         e.title, e.hired.isoformat(), e.left.isoformat() if e.left else "",
                         "JA" if e.current else "NEJ"])
    _w(ACCT / "payroll" / "lonelista_alla.csv", all_rows,
       ["Anstnr", "Namn", "Befattning", "Anställd", "Slutade", "Aktiv"])
    return {"payroll/loneunderlag.csv": "Löneunderlag per månad",
            "payroll/lonelista_aktuell.csv": "Lönelista (aktuella anställda)",
            "payroll/lonelista_alla.csv": "Lönelista samtliga anställda inkl. avgångna (anställnings- och slutdatum)"}


# ------------------------------------------------------------------ tax
def export_tax(m: Model) -> dict:
    # VAT per month from postings
    by_month = defaultdict(lambda: defaultdict(Decimal))
    for p in m.postings:
        if p["account"] in (2611, 2614, 2641, 2645):
            by_month[p["date"][:7]][p["account"]] += Decimal(p["amount"])
    rows = []
    for mk in MONTHS:
        b = by_month[mk]
        rows.append([mk, str(-b[2611]), str(-b[2614]), str(b[2641]), str(b[2645]),
                     str(-b[2611] - b[2614] + b[2641] + b[2645])])
    _w(ACCT / "tax" / "momsunderlag.csv", rows,
       ["Månad", "Utgående moms", "Utgående moms omvänd", "Ingående moms",
        "Ingående moms omvänd", "Att betala (netto)"])
    # skattekonto movements
    rows2 = [[p["date"], p["voucher_id"], p["amount"]] for p in m.postings if p["account"] == 1630]
    _w(ACCT / "tax" / "skattekonto.csv", rows2, ["Datum", "Verifikation", "Belopp"])
    return {"tax/momsunderlag.csv": "Momsunderlag per månad",
            "tax/skattekonto.csv": "Skattekontorörelser (1630)"}


# ------------------------------------------------------------------ reports
def export_reports(m: Model) -> dict:
    # monthly P&L (result accounts, excluding closing vouchers)
    zero = {v["id"] for v in m.vouchers if v["text"].startswith(("Resultatöverföring", "Överföring till balanserat"))}
    pl_rows = [["Månad", "Konto", "Kontonamn", "Belopp"]]
    bs_rows = [["Månad", "Konto", "Kontonamn", "Belopp"]]
    for mk in MONTHS:
        bal = defaultdict(Decimal)
        for p in m.postings:
            if p["date"] <= f"{mk}-28" and p["voucher_id"] not in zero:
                bal[p["account"]] += Decimal(p["amount"])
        name = {a["number"]: a["name"] for a in m.accounts}
        for acc in sorted(bal):
            if acc in (3011, 4520, 5010, 5020, 5060, 5420, 5615, 5616, 5800, 5910,
                       6072, 6110, 6210, 6310, 6351, 6420, 6540, 6570, 6991, 6992,
                       7210, 7290, 7410, 7510, 7610, 7699, 7831, 7832, 8313, 8410, 8910):
                if bal[acc] != 0:
                    pl_rows.append([mk, acc, name.get(acc, ""), str(bal[acc])])
            elif acc not in (1630, 2650, 2099):
                if bal[acc] != 0:
                    bs_rows.append([mk, acc, name.get(acc, ""), str(bal[acc])])
    _w(ACCT / "financial_reports" / "resultat_per_manad.csv", pl_rows,
       ["Månad", "Konto", "Kontonamn", "Belopp (ackumulerat räkenskapsår)"])
    _w(ACCT / "financial_reports" / "balans_per_manad.csv", bs_rows,
       ["Månad", "Konto", "Kontonamn", "Belopp"])
    # annual reports
    for fy, (lo, hi) in config.FISCAL_YEARS.items():
        bal = defaultdict(Decimal)
        for v in m.vouchers:
            if lo.isoformat() <= v["date"] <= hi.isoformat() and v["id"] not in zero:
                for acc, amt in v["rows"]:
                    bal[int(acc)] += Decimal(amt)
        name = {a["number"]: a["name"] for a in m.accounts}
        rows = [[acc, name.get(acc, ""), str(bal[acc])] for acc in sorted(bal) if bal[acc] != 0]
        _w(ACCT / "financial_reports" / f"resultatrakning_{fy}.csv", rows,
           ["Konto", "Kontonamn", "Belopp"])
    return {"financial_reports/resultat_per_manad.csv": "Resultaträkning per månad (ackumulerat)",
            "financial_reports/balans_per_manad.csv": "Balansräkning per månadsslut",
            "financial_reports/resultatrakning_FY2025.csv": "Resultaträkning FY2025",
            "financial_reports/resultatrakning_FY2026.csv": "Resultaträkning FY2026"}


# ------------------------------------------------------------------ projects
def export_projects(m: Model) -> dict:
    rows = []
    for inv in m.customer_invoices:
        if inv.get("project_id"):
            rows.append([inv["project_id"], inv["date"], inv["id"], inv["customer_id"],
                         inv["net"], inv["hours"] or ""])
    _w(ACCT / "financial_reports" / "projektintakter.csv", rows,
       ["Projekt", "Datum", "Faktura", "Kund", "Netto", "Timmar"])
    return {"financial_reports/projektintakter.csv": "Projektintäkter (fakturarader)"}


# ------------------------------------------------------------------ time
def export_time(m: Model) -> dict:
    """Tidrapporter: distribute scheduled hours over team members (alloc-prorated,
    seeded rounding) + internal/non-billable time."""
    from .story_finance import _time_month_hours
    from .util import rng
    r = rng("time")
    rows = []
    sch_by_id = {s.id: s for s in m.schedules}
    for s in m.schedules:
        proj = next((p for p in m.projects if p.id == s.project_id), None)
        if proj is None:
            continue
        for mk, hours in sorted(s.monthly_hours.items()):
            members = [tm for tm in proj.team
                       if tm.from_date <= __import__("datetime").date(int(mk[:4]), int(mk[5:7]), 28)
                       and (tm.to_date is None or tm.to_date >= __import__("datetime").date(int(mk[:4]), int(mk[5:7]), 1))]
            if not members:
                continue
            tot_alloc = sum(tm.alloc_pct for tm in members) or 100
            assigned = 0.0
            for i, tm in enumerate(members):
                if i == len(members) - 1:
                    hrs = round(hours - assigned, 1)
                else:
                    hrs = round(hours * tm.alloc_pct / tot_alloc, 1)
                    assigned += hrs
                rows.append([mk, tm.person_id, s.project_id, str(hrs), "debiterbar"])
    # internal projects: fixed monthly internal hours
    for (mk) in MONTHS:
        rows.append([mk, "P-026", "PRJ-091", "50", "intern"])
        rows.append([mk, "P-023", "PRJ-091", "30", "intern"])
        if mk >= "2025-06":
            rows.append([mk, "P-002", "PRJ-090", "20", "intern"])
    _w(ROOT / "projects" / "tidrapporter.csv", rows,
       ["Månad", "Person", "Projekt", "Timmar", "Typ"])
    return {"projects/tidrapporter.csv": "Tidrapporter (per person, projekt och månad)"}
