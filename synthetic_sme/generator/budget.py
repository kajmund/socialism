"""Budget and forecast data (authored, deterministic).

Budget FY26 (decided 2025-09-25): 47.0 MSEK net revenue, EBIT target 7 %.
The budget deliberately underestimates revenue (SEAB scale-up, SU and TR deals
were not in the plan) – that is what GQ-021 tests.
Forecast (2026-06-01): base 52.5 / worst 48.5 / best 55.0 MSEK.
"""
from __future__ import annotations

from . import config
from .model import Model
from .util import month_key, month_range


def _season(m: int) -> float:
    return {1: 0.98, 2: 1.0, 3: 1.02, 4: 0.98, 5: 1.0, 6: 0.95, 7: 0.62,
            8: 0.8, 9: 1.0, 10: 1.0, 11: 1.0, 12: 0.88}[m]


def build_budgets(m: Model) -> None:
    fy26_start, fy26_end = config.FISCAL_YEARS["FY2026"]
    months = [(y, mo) for (y, mo) in month_range(fy26_start, fy26_end)]
    total_w = sum(_season(mo) for _, mo in months)
    budget_rev = 47_000_000
    budget = {"fiscal_year": "FY2026", "decided": "2025-09-25", "currency": "SEK",
              "assumptions": [
                  "SE-Integration fakturerad 550-600 h/mån (faktiskt utfall 800 h/mån fr.o.m. 2025-10).",
                  "Mossbackens Mekaniska (MM-Underhållssystem) räknas hela året (kunden sade upp 2026-03, slutade 2026-06).",
                  "SU-Produktionssystem och TR-Skogsportal ingick inte i budgeten (avtal tecknade efter budgetbeslutet).",
                  "Två planerade rekryteringar (senior utvecklare, support) genomfördes inte.",
                  "Indexuppräkningar enligt avtalen antogs tillämpade (faktiskt missades två).",
              ],
              "revenue_total_net": budget_rev,
              "ebit_target_pct": 7.0,
              "monthly": {}}
    for (y, mo) in months:
        mk = month_key(__import__("datetime").date(y, mo, 1))
        w = _season(mo)
        rev = round(budget_rev * w / total_w)
        # cost profile: personnel-heavy every month, seasonal marketing spikes
        costs = round(rev * 0.93)  # -> EBIT ≈ 7 %
        budget["monthly"][mk] = {"revenue_net": rev, "costs": costs,
                                 "ebit": round(rev - costs)}
    m.budgets = budget

    forecast = {
        "made": "2026-06-01", "fiscal_year": "FY2026",
        "scenarios": {
            "base": {"revenue_net": 52_500_000, "ebit_pct": 11.0,
                     "assumptions": ["SE-Integration fortsätter på 800 h/mån",
                                     "Ingen ny stor kundförlust", "SU levererar enligt plan"]},
            "worst": {"revenue_net": 48_500_000, "ebit_pct": 8.5,
                      "assumptions": ["SEAB drar ned integration till 500 h/mån fr.o.m. september",
                                      "Blåklintens Vård säger upp avtalet per 2026-09-30",
                                      "Vite i SU-Produktionssystemet faller ut (10 % av avtalsvärdet)"]},
            "best": {"revenue_net": 55_000_000, "ebit_pct": 13.0,
                     "assumptions": ["Två pipeline-affärer vinns i Q4 (2,5 MSEK)",
                                     "Fullt beläggning utan underkonsulter i Q4"]},
        },
        "key_uncertainties": [
            "SEAB:s framtida volym (34 % av omsättningen).",
            "Mossbackens-förlustens helårseffekt.",
            "Utfallet av tvisten med Örby Handel (96 800 kr).",
            "Rekryteringen av supportansvarig (Klara Månsson slutar 2026-09-30).",
        ],
    }
    m.forecasts = forecast
