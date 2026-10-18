"""Canonical calculators – the single source of computed answers.

Both the facit builder and the validation suite use these functions, so the
expected answers and the checks can never drift apart.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from . import config
from .util import D, M, pct


def fy(datestr: str) -> str:
    return "FY2025" if datestr <= "2025-09-30" else "FY2026"


def balances_at(postings, upto: str) -> dict[int, Decimal]:
    bal = defaultdict(Decimal)
    for p in postings:
        if p["date"] <= upto:
            bal[p["account"]] += Decimal(p["amount"])
    return bal


def revenue_by_customer(invoices, fy_key: str | None = None) -> dict[str, Decimal]:
    out = defaultdict(Decimal)
    for inv in invoices:
        if inv["id"].startswith("KIN") or inv["id"].endswith("-IB"):
            continue
        if fy_key and fy(inv["date"]) != fy_key:
            continue
        out[inv["customer_id"]] += Decimal(inv["net"])
    return out


def revenue_by_month(invoices, fy_key: str) -> dict[str, Decimal]:
    out = defaultdict(Decimal)
    for inv in invoices:
        if inv["id"].startswith("KIN") or inv["id"].endswith("-IB"):
            continue
        if fy(inv["date"]) != fy_key:
            continue
        out[inv["date"][:7]] += Decimal(inv["net"])
    return out


def total_revenue(invoices, fy_key: str) -> Decimal:
    return M(sum(revenue_by_month(invoices, fy_key).values(), Decimal("0")))


def seab_share(invoices, fy_key: str) -> Decimal:
    rev = revenue_by_customer(invoices, fy_key)
    total = sum(rev.values(), Decimal("0"))
    if total == 0:
        return M(0)
    return M(rev.get("CUS-001", Decimal("0")) / total * 100)


def customer_share(invoices, fy_key: str, cid: str) -> Decimal:
    rev = revenue_by_customer(invoices, fy_key)
    total = sum(rev.values(), Decimal("0"))
    if total == 0:
        return M(0)
    return M(rev.get(cid, Decimal("0")) / total * 100)


def cash_at(postings, upto: str) -> Decimal:
    return balances_at(postings, upto)[1930]


def overdraft_at(postings, upto: str) -> Decimal:
    """Drawn amount (positive)."""
    return M(-balances_at(postings, upto)[2380])


def open_ar(invoices, upto: str = "2026-09-30") -> dict[str, Decimal]:
    out = defaultdict(Decimal)
    for inv in invoices:
        if inv["id"].startswith("KIN"):
            continue
        if inv.get("status") in ("OPEN", "PARTIAL") and inv["date"] <= upto:
            out[inv["customer_id"]] += Decimal(inv["gross"])
        if inv.get("status") == "PARTIAL":
            out[inv["customer_id"]] -= Decimal(inv.get("paid_amount", "0"))
    return {k: M(v) for k, v in out.items() if v != 0}


def overdue_ar(invoices, upto: str = "2026-09-30") -> dict[str, Decimal]:
    """Invoices past due at the given date, per customer."""
    out = defaultdict(Decimal)
    for inv in invoices:
        if inv["id"].startswith("KIN") or inv["id"].endswith("-IB"):
            continue
        if inv.get("status") not in ("OPEN", "PARTIAL"):
            continue
        if inv.get("due_date", "") and inv["due_date"] < upto:
            gross = Decimal(inv["gross"]) - Decimal(inv.get("paid_amount", "0"))
            out[inv["customer_id"]] += gross
    return {k: M(v) for k, v in out.items() if v != 0}


def kpi_index(mk: str) -> Decimal:
    return D(config.KPI_INDEX[mk])


def index_adjusted_rate(base_rate: int, base_month: str, apply_month: str) -> int:
    """KPI index clause: new rate = base × KPI(month before apply) / KPI(base)."""
    factor = kpi_index(_prev_month(apply_month)) / kpi_index(base_month)
    return int(round(base_rate * float(factor)))


def _prev_month(mk: str) -> str:
    y, m = int(mk[:4]), int(mk[5:7])
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f"{y:04d}-{m:02d}"


def missed_index_total(schedule, from_mk: str, base_month: str,
                       correct_rate: int) -> Decimal:
    """Sum of hours × (correct − billed) for a MISSED_INDEX schedule."""
    billed = schedule.rate
    total = Decimal("0")
    for mk, hours in sorted(schedule.monthly_hours.items()):
        if mk >= from_mk:
            total += M(Decimal(str(hours)) * (correct_rate - billed))
    return total


def underbilling_total(schedule, months: list[str], diff: int) -> Decimal:
    total = Decimal("0")
    for mk in months:
        total += M(Decimal(str(schedule.monthly_hours.get(mk, 0))) * diff)
    return total


def pnl_by_vouchers(vouchers, fy_key: str) -> dict[int, Decimal]:
    """Per-account P&L for a fiscal year, excluding closing zeroing vouchers."""
    lo = "2024-10-01" if fy_key == "FY2025" else "2025-10-01"
    hi = "2025-09-30" if fy_key == "FY2025" else "2026-09-30"
    out = defaultdict(Decimal)
    for v in vouchers:
        if not (lo <= v["date"] <= hi):
            continue
        if v["text"].startswith(("Resultatöverföring", "Överföring till balanserat")):
            continue
        for acc, amt in v["rows"]:
            out[int(acc)] += Decimal(amt)
    return dict(out)


def net_result(m, fy_key: str) -> Decimal:
    key = "net_result_2025" if fy_key == "FY2025" else "net_result_2026"
    return D(m.secret[key])


def month_of(datestr: str) -> str:
    return datestr[:7]
