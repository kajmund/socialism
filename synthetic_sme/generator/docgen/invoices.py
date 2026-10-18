"""Invoice DOCX generation (outgoing customer invoices + incoming supplier invoices).

Both derive from the same invoice registers in the truth model; amounts are
never re-computed independently.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .. import config
from ..model import Model
from ..util import fmt_sek
from . import common as C

ROOT = Path(__file__).resolve().parent.parent.parent


def _name_of(m: Model, kind: str, eid: str | None) -> str:
    if not eid:
        return ""
    if kind == "customer":
        for c in m.customers:
            if getattr(c, "id", "") == eid:
                return c.name
    if kind == "supplier":
        for s in m.suppliers:
            if getattr(s, "id", "") == eid:
                return s.name
    return eid


def _project_code(m: Model, pid: str | None) -> str:
    if not pid:
        return ""
    for p in m.projects:
        if getattr(p, "id", "") == pid:
            return p.code
    return ""


def customer_invoice(m: Model, inv: dict, outdir: Path) -> Path:
    cus_name = _name_of(m, "customer", inv["customer_id"])
    doc = C.new_doc()
    C.heading(doc, config.COMPANY["name"], 0)
    C.para(doc, f"{config.COMPANY['address']} | {config.COMPANY['phone']} | {config.COMPANY['email']}")
    C.para(doc, f"Org.nr {config.COMPANY['org_no']} | Momsreg.nr {config.COMPANY['vat_no']} | Bankgiro {config.COMPANY['bankgiro']}")
    C.heading(doc, "FAKTURA", 1)
    C.kv(doc, "Fakturanummer", inv["id"])
    C.kv(doc, "Fakturadatum", C.fmt_d(inv["date"]))
    C.kv(doc, "Förfallodatum", C.fmt_d(inv["due_date"]))
    C.kv(doc, "Er referens", inv.get("month", "") or "")
    C.para(doc, "")
    C.para(doc, "Faktureras till:", bold=True)
    C.para(doc, cus_name)
    C.para(doc, f"Projekt: {_project_code(m, inv.get('project_id'))} " if inv.get("project_id") else " ")
    rows = []
    if inv.get("hours") is not None:
        desc = f"Konsulttjänster {inv['month']} ({inv['hours']} timmar à {inv['rate']} kr)"
    else:
        desc = f"Konsulttjänster {inv['month']}" + (f" – {inv.get('note', '')}" if inv.get("note") else "")
    rows.append([desc, "1", inv["net"], inv["vat"], inv["gross"]])
    C.table(doc, ["Beskrivning", "Antal", "Belopp (ex moms)", "Moms 25 %", "Belopp (inkl. moms)"],
            [[r[0], r[1], fmt_sek(r[2]), fmt_sek(r[3]), fmt_sek(r[4])] for r in rows])
    C.right(doc, f"ATT BETALA: {fmt_sek(inv['gross'])} SEK", bold=True)
    C.para(doc, f"Betalningsvillkor: {config.BILLING['standard_terms_days']} dagar netto. Vid sen betalning debiteras dröjsmålsränta enligt räntelagen.")
    path = outdir / f"{inv['date'][:4]}" / f"{inv['id']}_{cus_name.replace(' ', '_')}.docx"
    C.save(doc, path)
    return path


def supplier_invoice(m: Model, inv: dict, outdir: Path) -> Path:
    sup_name = _name_of(m, "supplier", inv["supplier_id"])
    doc = C.new_doc()
    C.heading(doc, sup_name, 0)
    C.para(doc, "LEVERANTÖRSFAKTURA", bold=True)
    C.kv(doc, "Fakturanummer", inv["id"])
    C.kv(doc, "Fakturadatum", C.fmt_d(inv["date"]))
    C.kv(doc, "Förfallodatum", C.fmt_d(inv["due_date"]))
    C.kv(doc, "Avser", inv["label"])
    C.kv(doc, "Konto", inv["account"])
    if inv.get("reverse_charge"):
        C.para(doc, "Omvänd skattskyldighet – moms redovisas av köparen.", italic=True)
    C.table(doc, ["Beskrivning", "Belopp (ex moms)", "Moms", "Belopp (inkl. moms)"],
            [[inv["label"], fmt_sek(inv["net"]), fmt_sek(inv["vat"]), fmt_sek(inv["gross"])]])
    C.right(doc, f"ATT BETALA: {fmt_sek(inv['gross'])} SEK", bold=True)
    path = outdir / f"{inv['date'][:4]}" / f"{inv['id']}_{sup_name.replace(' ', '_')}.docx"
    C.save(doc, path)
    return path


def generate_invoices(m: Model) -> dict:
    out = {}
    outdir = ROOT / "invoices" / "outgoing"
    for inv in m.customer_invoices:
        if inv["id"].startswith("KIN"):
            continue
        p = customer_invoice(m, inv, outdir)
        out[str(p.relative_to(ROOT))] = f"Kundfaktura {inv['id']}"
    indir = ROOT / "invoices" / "incoming"
    for inv in m.supplier_invoices:
        p = supplier_invoice(m, inv, indir)
        out[str(p.relative_to(ROOT))] = f"Leverantörsfaktura {inv['id']}"
    return out
