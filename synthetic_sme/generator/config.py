"""SPEC Synthetic SME Benchmark – generator configuration.

Single source of truth for environment constants. Every generated number,
document and export derives from the canonical model built with these values.
"""
from __future__ import annotations

from datetime import date

BENCHMARK_ID = "SPEC-SME-1.0"
VERSION = "1.0.0"
SEED = 20261018  # fixed random seed; never change without bumping VERSION

# Analysis window
ANALYSIS_DATE = date(2026, 10, 18)
HIST_START = date(2024, 10, 1)
HIST_END = date(2026, 9, 30)

# Fiscal years: broken fiscal year, 1 Oct – 30 Sep (documented in README).
FISCAL_YEARS = {
    "FY2025": (date(2024, 10, 1), date(2025, 9, 30)),
    "FY2026": (date(2025, 10, 1), date(2026, 9,30)),
}
PRIMARY_ANALYSIS_YEAR = "FY2026"

# Company (fictional; any resemblance to real companies is coincidental)
COMPANY = {
    "name": "Nordviken Digital AB",
    "org_no": "559245-1673",
    "address": "Kajplatsen 4, 115 27 Stockholm",
    "phone": "08-555 014 27",
    "email": "info@nordvikendigital.se",
    "website": "www.nordvikendigital.se",
    "vat_no": "SE559245167301",
    "bankgiro": "5561-8892",
    "founded": date(2018, 3, 12),
    "seat": "Stockholm",
    "share_capital": 250000,  # SEK
    "shares": 2500,
    "auditor": "Revision & Tal AB",
    "accounting_firm": "Lön & Redo AB",
    "bank": "Norrvidden Bank AB",
    "bank_account": "9951 12 345 67",  # fictional clearing/account
    "insurance": "Tryggast Försäkring AB",
}

# Bank facilities (fictional bank)
BANK = {
    "checking_account": "1930",
    "overdraft_account": "2380",
    "overdraft_limit": 3_000_000,
    "overdraft_rate_pct": 5.40,   # annual
    "loan_account": "2350",
    "loan_rate_pct": 4.15,        # annual
    "loan_monthly_payment": 68_000,  # interest + amortization, fixed annuity-ish split
    "loan_start": date(2023, 4, 1),
    "loan_original": 2_000_000,
}

# Tax & social fees (Sweden, rates applicable 2024–2026)
TAX = {
    "vat_rate": "0.25",                       # services, 25 %
    "employer_fee_pct": 31.42,                # arbetsgivaravgift full
    "corporate_tax_pct": 20.6,
    "vacation_accrual_pct": 12.0,             # semesterlöneskuld % av bruttolön
    "pension_premium_pct": 4.5,               # ITP1-style: 4.5 % upp t.o.m. 7,5 IBB
    "pension_premium_above_pct": 30.0,        # 30 % på lönedel över 7,5 IBB
    "ibb": {  # inkomstbasbelopp, annual (SEK); external reference, snapshot
        "2024": 76_200,
        "2025": 80_600,
        "2026": 82_400,
    },
    "withholding_tax_default_pct": 31.0,      # per-employee override in story
    "friskvard_per_year": 4_000,
}

# KPI index snapshot (SCB KPI, 1980=100, monthly) – external reference set used by
# index clauses in contracts. Calibrated to realistic Swedish levels; stored as a
# fixed snapshot so the benchmark is reproducible offline.
KPI_INDEX = {
    "2023-10": 407.8, "2024-04": 411.6,
    "2024-10": 412.9, "2024-11": 413.5, "2024-12": 413.9,
    "2025-01": 413.2, "2025-02": 414.0, "2025-03": 414.8,
    "2025-04": 415.4, "2025-05": 415.9, "2025-06": 416.3,
    "2025-07": 416.7, "2025-08": 417.2, "2025-09": 417.6,
    "2025-10": 418.1, "2025-11": 418.6, "2025-12": 419.0,
    "2026-01": 418.4, "2026-02": 419.1, "2026-03": 419.7,
    "2026-04": 420.2, "2026-05": 420.7, "2026-06": 421.1,
    "2026-07": 421.5, "2026-08": 421.9, "2026-09": 422.3,
}

# VAT reporting: monthly
VAT_PERIOD = "monthly"

# Billing / revenue parameters
BILLING = {
    "default_credit_days": 30,
    "invoice_date_day": 28,     # customer invoices issued on the 28th
    "standard_terms_days": 30,  # betalningsvillkor
    "late_interest_rate_pct": 8.0 + 8.0,  # dröjsmålsränta ref räntelagen (ref 8% + 8%)
}

# Depreciation (planenlig, K2-style)
DEPRECIATION = {
    "computers": {"account": "1250", "acc_account": "1259", "cost_account": "7832",
                  "years": 3},
    "equipment": {"account": "1220", "acc_account": "1229", "cost_account": "7831",
                  "years": 5},
}

# Document generation
DOC_LANGUAGE = "sv-SE"
PDF_CONVERT = True  # batch LibreOffice conversion after DOCX generation

# Deliverable packages
PACKAGES = {
    "ingest": "socialism_ingest.zip",
    "ground_truth": "socialism_ground_truth.zip",
    "generator": "socialism_generator.zip",
}
