"""Canonical truth model: entity schemas + in-memory registry.

The truth model is the single source of truth. All documents, invoices, SIE
files and facit derive from it. It is kept OUT of the ingest package.

Every entity has a stable `id`. Relations use these IDs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import date
from typing import Any

from .util import read_json, write_json


def _ser(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _ser(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_ser(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


@dataclass
class Person:
    id: str
    first: str
    last: str
    birth: date
    email: str
    phone: str
    city: str
    note: str = ""


@dataclass
class SalaryStep:
    from_date: date
    amount: int  # SEK gross per month
    reason: str = ""


@dataclass
class Employee:
    id: str
    person_id: str
    emp_no: int
    title: str
    dept: str            # LED/STAB/FORS/SALJ/LEV
    level: str           # JUN/REG/SEN/EXP
    hired: date
    left: date | None
    salary: list[SalaryStep] = field(default_factory=list)
    billing_rate: int | None = None   # kr/h if billable
    skills: list[str] = field(default_factory=list)
    sick_days: list[tuple[str, int]] = field(default_factory=list)  # (month_key, days)
    current: bool = True
    note: str = ""


@dataclass
class Customer:
    id: str
    name: str
    org_no: str
    city: str
    industry: str
    segment: str          # OFFENTLIG / ENTERPRISE / SMB
    contact_id: str
    credit_days: int
    status: str           # ACTIVE / CHURNED / BANKRUPT
    is_key: bool = False
    payment_profile: str = "normal"   # normal / slow / very_slow / prepay
    note: str = ""


@dataclass
class Supplier:
    id: str
    name: str
    org_no: str
    city: str
    category: str
    contact_id: str | None
    payment_days: int
    vat_type: str = "SE"  # SE / EU / NON_EU
    is_subcontractor: bool = False
    note: str = ""


@dataclass
class TeamMember:
    person_id: str
    role: str
    from_date: date
    to_date: date | None
    alloc_pct: int = 100


@dataclass
class Project:
    id: str
    code: str
    customer_id: str
    name: str
    ptype: str           # UTV / MIGR / FORV / SUPP / DATA
    start: date
    end: date
    status: str          # ACTIVE / DONE / ON_HOLD
    contract_id: str
    billing_model: str   # FIXED / TIME / MANAGED
    fixed_amount: int | None = None       # SEK ex VAT for FIXED
    budget_hours: int | None = None
    budget_amount: int | None = None
    team: list[TeamMember] = field(default_factory=list)
    note: str = ""


@dataclass
class ContractVersion:
    version: int
    date: date
    summary: str


@dataclass
class Contract:
    id: str
    kind: str            # RAMAVTAL / PROJEKTAVTAL / KONSULTAVTAL / LEVERANTORSAVTAL /
                         # ANSTALLNING / NDA / DPA / SAAS / HYRA / LEASING / AKTIEAGARE / UPPDRAGSBEKR
    title: str
    counterparty_type: str  # customer / supplier / employee / corporate
    counterparty_id: str | None
    counterparty_extra: str | None  # e.g. second party for corporate
    signed: date
    effective_from: date
    expires: date | None
    auto_renew_months: int | None = None   # 0/None = no auto renewal
    notice_months: int | None = None
    payment_days: int | None = None
    pricing_model: str | None = None       # TIMPRIS / FAST / ABONNEMANG / INDEXTIM
    rate: int | None = None                # kr/h
    amount: int | None = None              # SEK ex VAT for FAST/ABONNEMANG
    index: dict | None = None              # {"type": "KPI", "base_month": "2025-10", "applied": [...], "due": [...], "applied_in_invoicing": bool}
    liability_cap: str | None = None       # e.g. "1 prisbasbelopp", "50% av årsarvode", "OBEGRÄNSAT"
    exclusivity: str | None = None
    change_of_control: bool = False
    versions: list[ContractVersion] = field(default_factory=list)
    status: str = "ACTIVE"   # ACTIVE / TERMINATED / EXPIRED / RENEGOTIATED
    finance_link: str | None = None        # schedule_id or stream_id or None
    project_ids: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    doc_id: str | None = None
    note: str = ""


@dataclass
class Event:
    """Business event (affärshändelse) – ties documents and postings together."""
    id: str
    date: date
    etype: str           # HIRE / LEAVE / RAISE / CONTRACT_SIGN / CONTRACT_END /
                         # PRICE_CHANGE / INDEX_MISSED / UNDERBILLING / CREDIT_NOTE /
                         # COMPLAINT / PAYMENT_DELAY / BANKRUPTCY / SETTLEMENT /
                         # BOARD / MGMT / DECISION / INCIDENT / OTHER
    title: str
    description: str
    entity_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    voucher_ids: list[str] = field(default_factory=list)
    invoice_ids: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class InvoiceSchedule:
    """Customer billing plan: one per (contract, project) with monthly amounts."""
    id: str
    contract_id: str
    project_id: str | None
    customer_id: str
    billing_model: str     # TIME / FIXED / MANAGED
    rate: int              # kr/h (for TIME)
    monthly_hours: dict[str, float] = field(default_factory=dict)  # "YYYY-MM" -> hours
    monthly_amount: dict[str, int] = field(default_factory=dict)   # "YYYY-MM" -> SEK ex VAT (FIXED/MANAGED)
    rate_changes: dict[str, int] = field(default_factory=dict)     # "YYYY-MM" -> new rate (applies from that month)
    anomalies: dict[str, str] = field(default_factory=dict)        # month_key -> anomaly id (UNDERBILL_RATE etc.)
    note: str = ""


@dataclass
class SupplierStream:
    """Recurring supplier cost: monthly amounts by account."""
    id: str
    supplier_id: str
    account: str
    label: str
    monthly_amount: dict[str, int] = field(default_factory=dict)   # month_key -> SEK ex VAT
    vat_rate: str = "0.25"
    reverse_charge: bool = False
    note: str = ""


@dataclass
class DocumentMeta:
    """Provenance metadata for one generated document."""
    id: str              # DOC-xxxx
    path: str            # relative to synthetic_sme/
    dtype: str           # AVTAL / FAKTURA / PROTOKOLL / MAIL / RAPPORT / POLICY / ...
    title: str
    created: date
    author_id: str       # person id or "SYSTEM"
    entities: list[str]
    version: str = "1.0"
    valid_from: date | None = None
    valid_to: date | None = None
    event_ids: list[str] = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: str | None = None
    language: str = "sv-SE"
    is_ground_truth_only: bool = False
    note: str = ""


class Model:
    """In-memory registry; serialized to truth_model.json (secret)."""

    def __init__(self) -> None:
        self.company: dict = {}
        self.persons: list[Person] = []
        self.employees: list[Employee] = []
        self.customers: list[Customer] = []
        self.suppliers: list[Supplier] = []
        self.projects: list[Project] = []
        self.contracts: list[Contract] = []
        self.events: list[Event] = []
        self.schedules: list[InvoiceSchedule] = []
        self.streams: list[SupplierStream] = []
        self.documents: list[DocumentMeta] = []
        # Finance results (filled by finance engine)
        self.accounts: list[dict] = []
        self.vouchers: list[dict] = []
        self.postings: list[dict] = []
        self.customer_invoices: list[dict] = []
        self.supplier_invoices: list[dict] = []
        self.payments_in: list[dict] = []
        self.payments_out: list[dict] = []
        self.bank_txns: list[dict] = []
        self.payroll_runs: list[dict] = []
        self.assets: list[dict] = []
        self.budgets: dict = {}
        self.forecasts: dict = {}
        self.secret: dict = {}   # truth-only annotations; NEVER shipped to ingest

    # -- lookups -----------------------------------------------------------
    def person(self, pid: str) -> Person:
        return next(p for p in self.persons if p.id == pid)

    def employee(self, eid: str) -> Employee:
        return next(e for e in self.employees if e.id == eid)

    def customer(self, cid: str) -> Customer:
        return next(c for c in self.customers if c.id == cid)

    def supplier(self, sid: str) -> Supplier:
        return next(s for s in self.suppliers if s.id == sid)

    def project(self, pid: str) -> Project:
        return next(p for p in self.projects if p.id == pid)

    def contract(self, cid: str) -> Contract:
        return next(c for c in self.contracts if c.id == cid)

    def schedule(self, sid: str) -> InvoiceSchedule:
        return next(s for s in self.schedules if s.id == sid)

    def stream(self, sid: str) -> SupplierStream:
        return next(s for s in self.streams if s.id == sid)

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "meta": {"benchmark": "SPEC-SME-1.0", "seed": 20261018,
                     "analysis_date": "2026-10-18"},
            "company": self.company,
            "persons": _ser(self.persons),
            "employees": _ser(self.employees),
            "customers": _ser(self.customers),
            "suppliers": _ser(self.suppliers),
            "projects": _ser(self.projects),
            "contracts": _ser(self.contracts),
            "events": _ser(self.events),
            "schedules": _ser(self.schedules),
            "streams": _ser(self.streams),
            "documents": _ser(self.documents),
            "accounts": self.accounts,
            "vouchers": self.vouchers,
            "postings": self.postings,
            "customer_invoices": self.customer_invoices,
            "supplier_invoices": self.supplier_invoices,
            "payments_in": self.payments_in,
            "payments_out": self.payments_out,
            "bank_txns": self.bank_txns,
            "payroll_runs": self.payroll_runs,
            "assets": self.assets,
            "budgets": self.budgets,
            "forecasts": self.forecasts,
            "secret": self.secret,
        }

    def save(self, path) -> None:
        write_json(path, self.to_dict())

    def load(self, path) -> "Model":
        d = read_json(path)
        # Rebuild only the authored entities; finance outputs stay as dicts.
        self.company = d["company"]
        self.persons = [Person(**p) for p in d["persons"]]
        self.employees = [Employee(**e) for e in d["employees"]]
        self.customers = [Customer(**c) for c in d["customers"]]
        self.suppliers = [Supplier(**s) for s in d["suppliers"]]
        self.projects = [Project(**p) for p in d["projects"]]
        self.contracts = [Contract(**c) for c in d["contracts"]]
        self.events = [Event(**e) for e in d["events"]]
        self.schedules = [InvoiceSchedule(**s) for s in d["schedules"]]
        self.streams = [SupplierStream(**s) for s in d["streams"]]
        self.documents = [DocumentMeta(**x) for x in d["documents"]]
        self.accounts = d.get("accounts", [])
        self.vouchers = d.get("vouchers", [])
        self.postings = d.get("postings", [])
        self.customer_invoices = d.get("customer_invoices", [])
        self.supplier_invoices = d.get("supplier_invoices", [])
        self.payments_in = d.get("payments_in", [])
        self.payments_out = d.get("payments_out", [])
        self.bank_txns = d.get("bank_txns", [])
        self.payroll_runs = d.get("payroll_runs", [])
        self.assets = d.get("assets", [])
        self.budgets = d.get("budgets", {})
        self.forecasts = d.get("forecasts", {})
        self.secret = d.get("secret", {})
        return self
