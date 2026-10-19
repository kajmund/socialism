"""Assemble the canonical story into a Model."""
from __future__ import annotations

from . import config
from .model import Model
from .story_events import events
from .story_finance import contracts, schedules, streams
from .story_persons import employees, persons
from .story_world import customers, projects, suppliers


def build_model() -> Model:
    m = Model()
    m.company = dict(config.COMPANY)
    m.persons = persons()
    m.employees = employees()
    m.customers = customers()
    m.suppliers = suppliers()
    m.projects = projects()
    m.contracts = contracts(m.employees)
    m.schedules = schedules()
    m.streams = streams()
    m.events = events()
    m.secret = {
        "story_version": config.VERSION,
        "fiscal_years": "brutna räkenskapsår: 2024-10-01–2025-09-30 (FY2025) och 2025-10-01–2026-09-30 (FY2026)",
        "analysis_date": "2026-10-18",
        "notes": [
            "Sanningsmodell – hålls utanför ingestpaketet.",
            "Alla bolag/personer är fiktiva.",
            "KPI-indexserien är en fast kalibrerad snapshot (SCB-nivå) för reproducerbarhet.",
            "Semesterlöner före 2024-10 är skattade från lönenivån 2024-10 (dokumenterat antagande).",
        ],
    }
    return m
