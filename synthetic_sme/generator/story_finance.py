"""Story: contracts, invoice schedules, supplier streams (canonical truth).

Contracts define terms; schedules define billable volume; streams define
recurring costs. The finance engine consumes all three.
"""
from __future__ import annotations

from datetime import date

from . import config
from .model import Contract, ContractVersion, InvoiceSchedule, SupplierStream
from .util import month_key, month_range, rng

D = date
M = month_key


# ---------------------------------------------------------------- helpers
def _mk(prefix, n):
    return f"{prefix}-{n:03d}"


def _time_month_hours(base, y, m, r=None):
    """Seasonal + optional noise hours for a month."""
    season = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.95, 5: 1.0, 6: 0.9, 7: 0.4,
              8: 0.75, 9: 1.0, 10: 1.0, 11: 1.0, 12: 0.85}[m]
    if r is None:
        return round(base * season, 1)
    return round(base * season * (1 + r.uniform(-0.03, 0.03)), 1)


def _fill_hours(sched: InvoiceSchedule, start, end, base, ramp=None, r=None):
    if r is False:
        r = None
    elif r is None:
        r = rng(f"hours:{sched.id}")
    for (y, m) in month_range(start, end):
        h = _time_month_hours(base, y, m, r)
        if ramp and month_key(D(y, m, 1)) in ramp:
            h = ramp[month_key(D(y, m, 1))]
        sched.monthly_hours[month_key(D(y, m, 1))] = h
    return sched


# ---------------------------------------------------------------- contracts
def contracts(emps) -> list[Contract]:
    out: list[Contract] = []

    def add(c):
        out.append(c)
        return c

    # ---- Customer framework / project contracts (finance-driving) ---------
    add(Contract("CTR-2023-002", "PROJEKTAVTAL", "SE-Billing – ny faktureringsplattform", "customer", "CUS-001", None,
                 D(2023, 11, 20), D(2024, 10, 1), D(2026, 7, 15), None, None, 30,
                 "FAST", None, 9_400_000, None,
                 "Obegränsat vid grov vårdslöshet/uppsåt, i övrigt tak 50 % av kontraktsvärde.",
                 "Exklusiv leverantör av SEAB:s faktureringsplattform; förbud att i 12 mån efter avtalets slut utföra samma typ av uppdrag åt konkurrerande energibolag.",
                 True,
                 [ContractVersion(1, D(2023, 11, 20), "Ursprungligt avtal: 9,4 MSEK, slutdatum 2026-03-31."),
                  ContractVersion(2, D(2026, 2, 6), "Tilläggsavtal CTR-2026-004: slutdatum flyttat till 2026-07-15, +800 000 kr slutleveransmilestone.")],
                 "RENEGOTIATED", "SCH-001", ["PRJ-001"],
                 ["VITE_INGEN_FASTPRIS", "EXKLUSIVITET", "CONTROL_CHANGE"],
                 None, "Vårt största enskilda projekt."))
    add(Contract("CTR-2026-004", "UPPDRAGSBEKR", "Tilläggsavtal SE-Billing (slutleverans)", "customer", "CUS-001", None,
                 D(2026, 2, 6), D(2026, 2, 6), D(2026, 7, 15), None, None, 30,
                 "FAST", None, 800_000, None, None, None, False,
                 [], "ACTIVE", "SCH-001", ["PRJ-001"], [], None,
                 "Tillägg till CTR-2023-002 v2."))
    add(Contract("CTR-2026-002", "RAMAVTAL", "Ramavtal konsulttjänster SEAB (förlängning)", "customer", "CUS-001", None,
                 D(2026, 1, 15), D(2026, 2, 1), D(2028, 1, 31), 12, 3, 30,
                 "TIMPRIS", 1180, None, {"type": "KPI", "base_month": "2026-02", "applied": ["2026-02"], "applied_in_invoicing": True},
                 "Tak 2 ggr årsarvode.", None, True,
                 [], "ACTIVE", "SCH-002", ["PRJ-002"], [], None,
                 "Förlänger CTR-2023-022. Indexjusterad till 1 180 kr/h."))
    add(Contract("CTR-2023-022", "RAMAVTAL", "Ramavtal konsulttjänster SEAB (ursprungligt)", "customer", "CUS-001", None,
                 D(2023, 12, 5), D(2024, 1, 1), D(2026, 1, 31), 12, 3, 30,
                 "TIMPRIS", 1150, None, None, "Tak 2 ggr årsarvode.", None, True,
                 [ContractVersion(1, D(2023, 12, 5), "Ursprungligt: 1 150 kr/h.")],
                 "EXPIRED", "SCH-002", ["PRJ-002"], [], None,
                 "Ersatt av CTR-2026-002."))
    add(Contract("CTR-2024-010", "PROJEKTAVTAL", "SE-Förvaltning", "customer", "CUS-001", None,
                 D(2025, 3, 10), D(2025, 4, 1), D(2026, 12, 31), 12, 3, 30,
                 "ABONNEMANG", None, 320_000, None, "Tak 12 månaders avgift.", None, True,
                 [], "ACTIVE", "SCH-003", ["PRJ-003"], [], None, "Förvaltningsavtal 320 tkr/mån."))
    add(Contract("CTR-2022-007", "RAMAVTAL", "Ramavtal IT-tjänster Gråvikens kommun", "customer", "CUS-002", None,
                 D(2022, 9, 30), D(2022, 10, 1), D(2026, 12, 31), 12, 6, 30,
                 "INDEXTIM", 1050, None, {"type": "KPI", "base_month": "2023-10", "due": ["2025-10"], "applied_in_invoicing": False},
                 "Tak 20 prisbasbelopp.", None, False,
                 [ContractVersion(1, D(2022, 9, 30), "Ursprungligt: 990 kr/h."),
                  ContractVersion(2, D(2024, 6, 12), "Höjning till 1 050 kr/h.")],
                 "ACTIVE", "SCH-004", ["PRJ-004"],
                 ["MISSAD_INDEX"], None,
                 "KPI-klausul: uppräkning per 2025-10-01 (bas 2023-10). Uppräkningen har INTE tillämpats i faktureringen."))
    add(Contract("CTR-2024-021", "PROJEKTAVTAL", "FS-Intranät", "customer", "CUS-003", None,
                 D(2025, 1, 20), D(2025, 2, 2), D(2025, 9, 30), None, None, 45,
                 "FAST", None, 1_250_000, None, "Tak 100 % av avtalsvärdet.", None, False,
                 [], "DONE", "SCH-005", ["PRJ-005"], [], None,
                 "Fakturering efterskott; slutfaktura 2025-10-10."))
    add(Contract("CTR-2025-014", "PROJEKTAVTAL", "FS-Förvaltning", "customer", "CUS-003", None,
                 D(2025, 9, 12), D(2025, 10, 1), D(2026, 12, 31), 12, 3, 45,
                 "ABONNEMANG", None, 85_000, None, "Tak 12 månaders avgift.", None, False,
                 [], "ACTIVE", "SCH-006", ["PRJ-006"], [], None,
                 "Automatisk förlängning 12 mån om ej uppsagt senast 2026-09-30 – fristen har passerat utan uppsägning."))
    add(Contract("CTR-2024-014", "PROJEKTAVTAL", "KL-Vårdportal", "customer", "CUS-004", None,
                 D(2024, 10, 20), D(2024, 11, 4), D(2026, 3, 31), None, None, 30,
                 "TIMPRIS", 1090, None, None, "Tak 15 prisbasbelopp.", None, False,
                 [], "DONE", "SCH-007", ["PRJ-007"], [], None, ""))
    add(Contract("CTR-2023-015", "PROJEKTAVTAL", "KF-Biljettsystem", "customer", "CUS-005", None,
                 D(2023, 6, 15), D(2023, 7, 1), D(2026, 12, 31), 12, 3, 30,
                 "INDEXTIM", 1050, None, {"type": "KPI", "base_month": "2023-07", "due": ["2025-11"], "applied": ["2025-11"], "applied_in_invoicing": False},
                 "24 månaders funktionsgaranti (ovanligt långtgående).", None, False,
                 [ContractVersion(1, D(2023, 6, 15), "Ursprungligt: 1 050 kr/h.")],
                 "ACTIVE", "SCH-008", ["PRJ-008"],
                 ["UNDERBILLING"], None,
                 "Indexuppräkning till 1 150 kr/h gäller fr.o.m. 2025-11-01 men debiterades först fr.o.m. 2026-02-01 (fel i faktureringen nov 2025–jan 2026)."))
    add(Contract("CTR-2025-011", "PROJEKTAVTAL", "TS-Produktionsportal", "customer", "CUS-006", None,
                 D(2025, 9, 8), D(2025, 10, 1), D(2026, 5, 31), None, None, 30,
                 "FAST", None, 1_800_000, None,
                 "Tak 100 % av avtalsvärdet. Vite vid försening: 1 % av avtalsvärdet per påbörjad vecka, max 10 %.",
                 None, False,
                 [], "DONE", "SCH-009", ["PRJ-009"], ["VITE_FASTPRIS"], None,
                 "8 veckor försenad; förlikning: kreditnota 90 000 kr."))
    add(Contract("CTR-2023-018", "PROJEKTAVTAL", "BV-Journalsystem", "customer", "CUS-007", None,
                 D(2023, 8, 25), D(2023, 9, 1), D(2026, 12, 31), 12, 3, 45,
                 "INDEXTIM", 990, None, {"type": "KPI", "base_month": "2024-04", "due": ["2026-04"], "applied_in_invoicing": False},
                 "Tak 10 prisbasbelopp.", None, False,
                 [], "ACTIVE", "SCH-010", ["PRJ-010"], ["MISSAD_INDEX"], None,
                 "Indexklausul: uppräkning per 2026-04-01 (bas 2024-04) har INTE tillämpats i faktureringen. Kunden betalar långsamt."))
    add(Contract("CTR-2024-030", "PROJEKTAVTAL", "MM-Underhållssystem", "customer", "CUS-008", None,
                 D(2024, 12, 10), D(2025, 1, 6), D(2026, 6, 30), None, 3, 30,
                 "TIMPRIS", 1030, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "TERMINATED", "SCH-011", ["PRJ-011"], [], None,
                 "Kunden sade upp avtalet 2026-03-26 (3 mån uppsägning) och gick till konkurrent."))
    add(Contract("CTR-2024-016", "PROJEKTAVTAL", "ÖH-Webbplattform", "customer", "CUS-009", None,
                 D(2024, 9, 5), D(2024, 10, 1), D(2025, 2, 28), None, None, 30,
                 "FAST", None, 1_450_000, None,
                 "OBEGRÄNSAT ansvar (avvikelse från vår standardmall – risk).", None, False,
                 [], "TERMINATED", "SCH-012", ["PRJ-012"], ["OBEGRANSAT_ANSVAR"], None,
                 "Tvist om slutfaktura; 96 800 kr hålls inne av kunden."))
    add(Contract("CTR-2024-031", "PROJEKTAVTAL", "SB-E-handel", "customer", "CUS-010", None,
                 D(2025, 2, 17), D(2025, 3, 3), D(2025, 11, 30), None, 1, 30,
                 "TIMPRIS", 1020, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "TERMINATED", "SCH-013", ["PRJ-013"], ["MOTPART_KONKURS"], None,
                 "Motparten försatt i konkurs 2025-12-08."))
    add(Contract("CTR-2023-021", "PROJEKTAVTAL", "NH-Logistikportal", "customer", "CUS-011", None,
                 D(2023, 9, 18), D(2024, 10, 1), D(2025, 12, 31), None, 3, 30,
                 "TIMPRIS", 1120, None, None, "Tak 15 prisbasbelopp.", None, False,
                 [], "DONE", "SCH-014", ["PRJ-014"], [], None, ""))
    add(Contract("CTR-2025-020", "PROJEKTAVTAL", "NH-Förvaltning", "customer", "CUS-011", None,
                 D(2025, 12, 8), D(2026, 1, 1), D(2026, 12, 31), 12, 3, 30,
                 "ABONNEMANG", None, 95_000, None, "Tak 12 månaders avgift.", None, False,
                 [], "ACTIVE", "SCH-015", ["PRJ-015"], [], None, ""))
    add(Contract("CTR-2025-002", "PROJEKTAVTAL", "ÅB-Bostadsportal", "customer", "CUS-012", None,
                 D(2025, 2, 10), D(2025, 3, 3), D(2025, 11, 28), None, None, 30,
                 "FAST", None, 980_000, None, "Tak 100 % av avtalsvärdet.", None, False,
                 [], "DONE", "SCH-016", ["PRJ-016"], [], None, ""))
    add(Contract("CTR-2023-026", "RAMAVTAL", "Ramavtal GM-Bergdatasystem", "customer", "CUS-013", None,
                 D(2023, 5, 12), D(2023, 6, 1), D(2026, 12, 31), 12, 3, 30,
                 "TIMPRIS", 1150, None, None, "Tak 2 ggr årsarvode.", None, False,
                 [], "ACTIVE", "SCH-017", ["PRJ-017"], [], None, ""))
    add(Contract("CTR-2025-006", "PROJEKTAVTAL", "SV-Molnmigrering", "customer", "CUS-014", None,
                 D(2025, 5, 19), D(2025, 6, 2), D(2026, 3, 31), None, None, 30,
                 "FAST", None, 2_400_000, None, "Tak 100 % av avtalsvärdet.", None, False,
                 [], "DONE", "SCH-018", ["PRJ-018"], [], None, ""))
    add(Contract("CTR-2025-007", "RAMAVTAL", "Ramavtal PF-Kundportal", "customer", "CUS-015", None,
                 D(2025, 3, 10), D(2025, 4, 1), D(2026, 12, 31), 12, 6, 30,
                 "TIMPRIS", 1180, None, None, "Tak 25 prisbasbelopp.",
                 "Exklusivitet: får ej utföra motsvarande uppdrag åt konkurrerande försäkringsbolag under avtalstiden.",
                 True,
                 [], "ACTIVE", "SCH-019", ["PRJ-019"], ["EXKLUSIVITET", "CONTROL_CHANGE"], None, ""))
    add(Contract("CTR-2022-028", "RAMAVTAL", "Ramavtal KP-Fastighetssystem", "customer", "CUS-016", None,
                 D(2022, 11, 3), D(2023, 1, 1), D(2026, 12, 31), 12, 6, 30,
                 "TIMPRIS", 1080, None, None, "Tak 2 ggr årsarvode.", None, False,
                 [], "ACTIVE", "SCH-020", ["PRJ-020"], [], None,
                 "Automatisk förlängning 12 mån; uppsägningsfristen (senast 2026-06-30) har passerat."))
    add(Contract("CTR-2025-009", "PROJEKTAVTAL", "LL-Spårbarhet", "customer", "CUS-017", None,
                 D(2025, 7, 15), D(2025, 8, 4), D(2026, 1, 30), None, None, 30,
                 "FAST", None, 1_100_000, None, "Tak 100 % av avtalsvärdet.", None, False,
                 [], "DONE", "SCH-021", ["PRJ-021"], [], None, ""))
    add(Contract("CTR-2025-008", "PROJEKTAVTAL", "SM-Bokningssystem", "customer", "CUS-018", None,
                 D(2025, 4, 22), D(2025, 5, 5), D(2026, 4, 30), None, None, 30,
                 "TIMPRIS", 1040, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "DONE", "SCH-022", ["PRJ-022"], [], None, ""))
    add(Contract("CTR-2025-013", "PROJEKTAVTAL", "NE-Projektportal", "customer", "CUS-019", None,
                 D(2025, 8, 18), D(2025, 9, 1), D(2027, 1, 31), 12, 3, 30,
                 "TIMPRIS", 1060, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "ACTIVE", "SCH-023", ["PRJ-023"], [], None,
                 "Automatisk förlängning 12 mån fr.o.m. 2027-01-31."))
    add(Contract("CTR-2025-019", "PROJEKTAVTAL", "TR-Skogsportal", "customer", "CUS-020", None,
                 D(2025, 12, 9), D(2026, 1, 5), D(2026, 9, 30), None, None, 30,
                 "FAST", None, 850_000, None, "Tak 100 % av avtalsvärdet.", None, False,
                 [], "ACTIVE", "SCH-024", ["PRJ-024"], [], None, ""))
    add(Contract("CTR-2024-032", "PROJEKTAVTAL", "AR-Beställningsapp", "customer", "CUS-021", None,
                 D(2025, 1, 19), D(2025, 2, 3), D(2025, 10, 31), None, None, 30,
                 "TIMPRIS", 1010, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "DONE", "SCH-025", ["PRJ-025"], [], None, ""))
    add(Contract("CTR-2025-016", "PROJEKTAVTAL", "LM-Lärplattform", "customer", "CUS-022", None,
                 D(2025, 10, 13), D(2025, 11, 3), D(2026, 8, 31), None, None, 30,
                 "FAST", None, 1_600_000, None, "Tak 100 % av avtalsvärdet.", None, False,
                 [], "DONE", "SCH-026", ["PRJ-026"], [], None, ""))
    add(Contract("CTR-2025-004", "PROJEKTAVTAL", "FK-Miljödata", "customer", "CUS-023", None,
                 D(2025, 2, 17), D(2025, 3, 3), D(2026, 2, 27), None, None, 30,
                 "TIMPRIS", 1110, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "DONE", "SCH-027", ["PRJ-027"], [], None, ""))
    add(Contract("CTR-2025-022", "PROJEKTAVTAL", "FP-Bokningsplattform", "customer", "CUS-024", None,
                 D(2026, 1, 20), D(2026, 2, 2), D(2026, 12, 31), 12, 3, 30,
                 "TIMPRIS", 1030, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "ACTIVE", "SCH-028", ["PRJ-028"], [], None, ""))
    add(Contract("CTR-2026-001", "PROJEKTAVTAL", "SU-Produktionssystem", "customer", "CUS-025", None,
                 D(2026, 2, 24), D(2026, 3, 2), D(2026, 12, 31), None, None, 30,
                 "FAST", None, 1_950_000, None,
                 "Tak 100 % av avtalsvärdet. Vite 1 %/vecka, max 10 %. Källkodsdepå hos tredje part krävs.",
                 None, False,
                 [], "ACTIVE", "SCH-029", ["PRJ-029"], ["VITE_FASTPRIS"], None,
                 "Nytt avtal – innehåller ovanligt högt ansvarstak och källkodsdepåkrav jämfört med vår standardmall."))
    add(Contract("CTR-2025-015", "PROJEKTAVTAL", "KS-Skolplattform", "customer", "CUS-028", None,
                 D(2025, 7, 14), D(2025, 8, 4), D(2026, 12, 31), 12, 3, 30,
                 "TIMPRIS", 990, None, None, "Tak 10 prisbasbelopp.", None, False,
                 [], "ACTIVE", "SCH-030", ["PRJ-030"], [], None, ""))

    # ---- Small customer contracts (UPPDRAGSBEKR) --------------------------
    small = [
        ("CUS-026", 990, 60, D(2023, 4, 1), None), ("CUS-027", 1010, 75, D(2023, 8, 1), None),
        ("CUS-029", 950, 45, D(2022, 6, 1), None), ("CUS-030", 1020, 60, D(2023, 2, 1), None),
        ("CUS-031", 1000, 50, D(2022, 11, 1), None), ("CUS-032", 960, 40, D(2025, 1, 1), None),
        ("CUS-033", 990, 70, D(2023, 5, 1), None), ("CUS-034", 950, 35, D(2025, 3, 1), None),
        ("CUS-035", 1040, 55, D(2023, 10, 1), None), ("CUS-036", 950, 40, D(2022, 9, 1), D(2025, 12, 31)),
        ("CUS-037", 1010, 65, D(2025, 2, 1), None), ("CUS-038", 940, 30, D(2025, 4, 1), None),
        ("CUS-039", 990, 50, D(2023, 3, 1), None), ("CUS-040", 1030, 60, D(2025, 6, 1), None),
        ("CUS-041", 1000, 45, D(2023, 1, 1), None), ("CUS-042", 950, 40, D(2022, 12, 1), None),
        ("CUS-043", 950, 35, D(2025, 5, 1), None), ("CUS-044", 950, 25, D(2023, 6, 1), None),
        ("CUS-045", 1050, 80, D(2025, 1, 1), None), ("CUS-046", 980, 90, D(2025, 7, 1), None),
        ("CUS-047", 1020, 40, D(2023, 9, 1), None), ("CUS-048", 1000, 55, D(2026, 1, 1), None),
        ("CUS-049", 990, 70, D(2023, 7, 1), None), ("CUS-050", 950, 30, D(2023, 11, 1), None),
    ]
    for i, (cid, rate, hours, start, end) in enumerate(small):
        add(Contract(small_contract_id(i, start), "UPPDRAGSBEKR", f"Löpande konsultstöd {cid}", "customer", cid, None,
                     D(start.year, start.month, 1), start, end or D(2026, 12, 31),
                     12 if not end else None, 3, 30,
                     "TIMPRIS", rate, None, None, "Tak 10 prisbasbelopp.", None, False,
                     [], "ACTIVE" if not end or end >= D(2026, 9, 30) else "EXPIRED",
                     f"SCH-{51 + i:03d}", [], [], None,
                     f"Löpande konsultstöd, {rate} kr/h."))

    # ---- Supplier contracts -----------------------------------------------
    sup = [
        ("SUP-001", "HYRA", "Hyresavtal lokaler", D(2023, 9, 1), D(2023, 10, 1), None, 12, 9,
         "ABONNEMANG", None, 165_000, {"type": "KPI", "base_month": "2023-10", "due": ["2026-01"], "applied": ["2026-01"], "applied_in_invoicing": True},
         "Lokalhyra 165 000 kr/mån, indexreglerad; fr.o.m. 2026-01: 172 000 kr/mån.", "STR-001"),
        ("SUP-023", "LEVERANTORSAVTAL", "Elavtal", D(2024, 1, 1), D(2024, 1, 1), None, 12, 3, "ABONNEMANG", None, None, None, "Rörligt elpris.", "STR-002"),
        ("SUP-024", "LEVERANTORSAVTAL", "Städavtal", D(2023, 4, 1), D(2023, 4, 1), None, None, 1, "ABONNEMANG", None, 8_500, None, "Städning 8 500 kr/mån.", "STR-003"),
        ("SUP-003", "SAAS", "M365 och Azure (Cloudserve Ireland)", D(2024, 1, 1), D(2024, 1, 1), None, 12, 1,
         "ABONNEMANG", None, 95_000, None, "SLA 99,9 %; ersättning vid avbrott: 10 % av månadsavgiften per påbörjad 24 h. Omvänd skattskyldighet.", "STR-004"),
        ("SUP-004", "SAAS", "Hosting (Nordhost)", D(2023, 6, 1), D(2023, 6, 1), None, 12, 3, "ABONNEMANG", None, 22_000, None, "", "STR-005"),
        ("SUP-005", "SAAS", "Ärendehantering och wiki", D(2023, 2, 1), D(2023, 2, 1), None, 12, 3, "ABONNEMANG", None, 14_500, None, "14 500 kr/mån; höjt till 16 200 kr/mån fr.o.m. 2025-06.", "STR-006"),
        ("SUP-006", "SAAS", "Chattverktyg (Kanalen)", D(2022, 9, 1), D(2022, 9, 1), D(2026, 11, 30), 12, 3, "ABONNEMANG", None, 9_800, None,
         "Automatisk förlängning 12 mån fr.o.m. 2026-11-30 (uppsägningsfrist 2026-08-31 har passerat).", "STR-007"),
        ("SUP-007", "SAAS", "Designverktyg (Designsuiten)", D(2022, 5, 1), D(2022, 5, 1), D(2027, 1, 31), 12, 3,
         "ABONNEMANG", None, 11_200, None, "18 licenser; endast 9 används. Automatisk förlängning fr.o.m. 2027-01-31.", "STR-008"),
        ("SUP-008", "SAAS", "VPN och nätverkssäkerhet", D(2023, 11, 1), D(2023, 11, 1), None, 12, 3, "ABONNEMANG", None, 13_600, None, "", "STR-009"),
        ("SUP-009", "SAAS", "CRM (Pipeline)", D(2023, 1, 1), D(2023, 1, 1), None, 12, 3, "ABONNEMANG", None, 8_400, None, "", "STR-010"),
        ("SUP-010", "SAAS", "Lönesystem", D(2023, 1, 1), D(2023, 1, 1), None, 12, 3, "ABONNEMANG", None, 4_200, None, "", "STR-011"),
        ("SUP-011", "SAAS", "Ekonomisystem", D(2022, 10, 1), D(2022, 10, 1), None, 12, 3, "ABONNEMANG", None, 9_600, None, "", "STR-012"),
        ("SUP-012", "SAAS", "AI-modell-API:er (Modellfabriken)", D(2025, 3, 1), D(2025, 3, 1), D(2026, 10, 31), 12, 1,
         "ABONNEMANG", None, 18_500, None, "18 500 kr/mån; 24 500 kr/mån fr.o.m. 2026-01. Automatisk förlängning fr.o.m. 2026-10-31 (frist passerad).", "STR-013"),
        ("SUP-013", "SAAS", "Analysmolntjänst (Analytics Cloud Inc, USA)", D(2025, 5, 1), D(2025, 5, 1), None, 12, 1,
         "ABONNEMANG", None, 6_200, None, "Amerikansk leverantör; personuppgifter överförs utanför EU/EES (SCC). Omvänd skattskyldighet.", "STR-014"),
        ("SUP-014", "SAAS", "Analysverktyg (Datainsikt)", D(2023, 9, 1), D(2023, 9, 1), None, None, 3,
         "ABONNEMANG", None, 7_800, None, "10 licenser; endast 2 används. Löpande avtal, 3 mån uppsägning.", "STR-015"),
        ("SUP-015", "SAAS", "Digital samarbetsyta (Whiteboard)", D(2023, 3, 1), D(2023, 3, 1), None, None, 1,
         "ABONNEMANG", None, 6_400, None, "Löpande avtal, 1 mån uppsägning – kan sägas upp när som helst.", "STR-016"),
        ("SUP-016", "SAAS", "CI/CD (Bygglådan)", D(2023, 5, 1), D(2023, 5, 1), None, None, 1, "ABONNEMANG", None, 5_200, None, "Löpande, 1 mån uppsägning.", "STR-017"),
        ("SUP-017", "SAAS", "Monitoring (Vakthuset)", D(2023, 8, 1), D(2023, 8, 1), None, 12, 3, "ABONNEMANG", None, 6_800, None, "", "STR-018"),
        ("SUP-018", "SAAS", "E-signatur (Signera)", D(2023, 2, 1), D(2023, 2, 1), None, 12, 3, "ABONNEMANG", None, 3_400, None, "", "STR-019"),
        ("SUP-019", "LEVERANTORSAVTAL", "Telefoni", D(2023, 7, 1), D(2023, 7, 1), None, None, 3, "ABONNEMANG", None, 12_000, None, "Löpande, 3 mån uppsägning.", "STR-020"),
        ("SUP-020", "SAAS", "Dokumenthantering (Arkivet)", D(2023, 4, 1), D(2023, 4, 1), None, 12, 3, "ABONNEMANG", None, 5_600, None, "", "STR-021"),
        ("SUP-021", "SAAS", "Backup (Säkerhetskopian)", D(2023, 10, 1), D(2023, 10, 1), None, 12, 3, "ABONNEMANG", None, 7_200, None, "", "STR-022"),
        ("SUP-022", "SAAS", "HR-system (Personalen)", D(2023, 6, 1), D(2023, 6, 1), None, 12, 3, "ABONNEMANG", None, 3_800, None, "", "STR-023"),
        ("SUP-025", "LEVERANTORSAVTAL", "Pensionsplan (ITP-liknande)", D(2022, 1, 1), D(2022, 1, 1), None, 12, 3, "ABONNEMANG", None, None, None, "Premie beräknas per lönekörning.", "STR-024"),
        ("SUP-026", "LEVERANTORSAVTAL", "Marknadsföring", D(2024, 1, 1), D(2024, 1, 1), None, 12, 3, "ABONNEMANG", None, 35_000, None, "Löpande 35 000 kr/mån + kampanjer.", "STR-025"),
        ("SUP-027", "LEVERANTORSAVTAL", "Kontorsmaterial", D(2023, 1, 1), D(2023, 1, 1), None, None, 1, "ABONNEMANG", None, 9_000, None, "Löpande, 1 mån uppsägning.", "STR-026"),
        ("SUP-028", "LEVERANTORSAVTAL", "Resebokning", D(2023, 2, 1), D(2023, 2, 1), None, None, 1, "ABONNEMANG", None, None, None, "Löpande, 1 mån uppsägning; kostnad per resa.", "STR-027"),
        ("SUP-029", "LEASING", "Billeasing (2 tjänstebilar)", D(2023, 6, 1), D(2023, 6, 1), D(2026, 11, 30), None, None, "ABONNEMANG", None, 12_800, None, "2 bilar à 6 400 kr/mån. Avtalet löper ut 2026-11-30.", "STR-028"),
        ("SUP-030", "LEASING", "IT-utrustningsleasing (60 laptops)", D(2024, 1, 1), D(2024, 1, 1), D(2026, 12, 31), None, 3, "ABONNEMANG", None, 24_000, None, "60 laptops, 24 000 kr/mån.", "STR-029"),
        ("SUP-031", "LEVERANTORSAVTAL", "Rekrytering", D(2023, 5, 1), D(2023, 5, 1), None, None, None, "FAST", None, None, None, "Löpande, per uppdrag ca 85 000 kr.", "STR-030"),
        ("SUP-032", "LEVERANTORSAVTAL", "Utbildning", D(2023, 9, 1), D(2023, 9, 1), None, None, 1, "ABONNEMANG", None, 12_000, None, "Löpande 12 000 kr/mån + enskilda kurser.", "STR-031"),
        ("SUP-033", "LEVERANTORSAVTAL", "Juridiska tjänster", D(2024, 2, 1), D(2024, 2, 1), None, None, 1, "FAST", None, None, None, "Löpande 15 000 kr/mån fr.o.m. 2025-09 + per ärende.", "STR-032"),
        ("SUP-034", "KONSULTAVTAL", "Underkonsulter Kraftkod (2 utvecklare)", D(2024, 12, 10), D(2025, 1, 1), D(2026, 7, 31), None, 1, "INDEXTIM", 850, None, None, "850 kr/h, 160 h/mån.", "STR-033"),
        ("SUP-035", "KONSULTAVTAL", "Underkonsult Dataverket Nord", D(2025, 2, 10), D(2025, 3, 1), None, None, 1, "TIMPRIS", 980, None, None, "980 kr/h, ca 60 h/mån.", "STR-034"),
        ("SUP-036", "KONSULTAVTAL", "Underkonsult Testhuset", D(2025, 5, 15), D(2025, 6, 1), None, None, 1, "TIMPRIS", 900, None, None, "900 kr/h, ca 45 h/mån.", "STR-035"),
        ("SUP-037", "KONSULTAVTAL", "Underkonsult Pixel & Form (UX)", D(2024, 9, 15), D(2024, 10, 1), D(2026, 3, 31), None, 1, "TIMPRIS", 890, None, None, "890 kr/h, ca 50 h/mån.", "STR-036"),
        ("SUP-038", "LEVERANTORSAVTAL", "Företagsförsäkring", D(2023, 12, 1), D(2024, 1, 1), None, 12, 3, "ABONNEMANG", None, 21_000, None, "Årspremie 252 000 kr, faktureras i januari; periodiseras.", "STR-038"),
        ("SUP-039", "LEVERANTORSAVTAL", "Revision", D(2024, 1, 1), D(2024, 1, 1), None, None, None, "FAST", None, None, None, "Revision FY2025: 95 000 kr (fakturerad 2025-11).", "STR-039"),
        ("SUP-040", "LEVERANTORSAVTAL", "Löpande redovisning", D(2022, 4, 1), D(2022, 4, 1), None, 12, 3, "ABONNEMANG", None, 18_000, None, "18 000 kr/mån.", "STR-040"),
        ("SUP-002", "LEVERANTORSAVTAL", "IT-hårdvara (Datorlagret)", D(2023, 1, 1), D(2023, 1, 1), None, None, 1, "FAST", None, None, None, "Inköp per behov (aktiveras som datorer).", "STR-037"),
    ]
    for sid, kind, title, signed, eff, exp, auto, notice, pm, rate, amt, idx, note, stream in sup:
        add(Contract(f"CTR-SUP-{int(sid.split('-')[1]):03d}", kind, title, "supplier", sid, None, signed, eff, exp, auto, notice, 30,
                     pm, rate, amt, idx, None, None, False,
                     [], "ACTIVE" if not exp or exp >= D(2026, 9, 30) else "EXPIRED",
                     stream, [], [], None, note))

    # ---- Employment contracts ---------------------------------------------
    for i, e in enumerate(emps, start=1):
        confidential = e.hired >= D(2023, 2, 15)  # mallen uppdaterades 2023-02-15
        # konkurrensklausul: fanns i mall före 2024; efter 2024 endast för nyckelpersoner
        clause = (e.hired < D(2024, 1, 1))
        risk = []
        if not confidential:
            risk.append("GAMMAL_SEKRETESS")
        if clause:
            risk.append("KONKURRENSKLAUSUL")
        add(Contract(f"CTR-EMP-{e.emp_no:02d}", "ANSTALLNING",
                     f"Anställningsavtal {e.title}", "employee", e.person_id, None,
                     e.hired, e.hired, None, None, None, None,
                     "FAST", None, e.salary[-1].amount, None, None, None, False,
                     [], "ACTIVE" if e.current else "TERMINATED", None, [], risk, None,
                     f"Anställningsavtal. Sekretessbilaga enligt 2023-02-15-mallen: {'ja' if confidential else 'nej'}."))

    # ---- NDA (seeded list of counterparties) ------------------------------
    nda_parties = [("customer", c) for c in ["CUS-001", "CUS-002", "CUS-003", "CUS-005", "CUS-006", "CUS-007",
                                             "CUS-011", "CUS-013", "CUS-014", "CUS-015", "CUS-016", "CUS-018",
                                             "CUS-019", "CUS-022", "CUS-024", "CUS-025", "CUS-045"]] + \
                  [("supplier", s) for s in ["SUP-003", "SUP-012", "SUP-013", "SUP-034"]] + \
                  [("corporate", None)] * 2
    r = rng("nda")
    for i, (ptype, pid) in enumerate(nda_parties, start=1):
        signed = D(2023 + (i % 3), 1 + (i * 5) % 12, 1 + (i * 7) % 28)
        add(Contract(f"CTR-NDA-{i:03d}", "NDA", "Sekretessavtal (ömsesidigt)", ptype, pid, None,
                     signed, signed, None, None, None, None, None, None, None, None, None, None, False,
                     [], "ACTIVE", None, [], [], None,
                     "Ömsesidigt sekretessavtal."))

    # ---- DPA ---------------------------------------------------------------
    dpa_parties = [("customer", c) for c in ["CUS-002", "CUS-003", "CUS-004", "CUS-007", "CUS-011", "CUS-015",
                                             "CUS-016", "CUS-019", "CUS-022", "CUS-028", "CUS-045", "CUS-046"]] + \
                  [("supplier", s) for s in ["SUP-003", "SUP-009", "SUP-010", "SUP-011", "SUP-013",
                                             "SUP-014", "SUP-017", "SUP-020", "SUP-022"]]
    for i, (ptype, pid) in enumerate(dpa_parties, start=1):
        signed = D(2022 + (i % 4), 1 + (i * 3) % 12, 1 + (i * 11) % 28)
        old = signed < D(2024, 5, 25)  # GDPR-standardavtalsklausuler uppdaterades (SCC) 2021; intern mall 2024-05
        add(Contract(f"CTR-DPA-{i:03d}", "DPA", "Personuppgiftsbiträdesavtal", ptype, pid, None,
                     signed, signed, None, None, None, None, None, None, None, None, None, None, False,
                     [], "ACTIVE", None, [], ["GAMMAL_DPA_MALL"] if old else [], None,
                     "Personuppgiftsbiträdesavtal. Baserat på intern mall fr.o.m. 2024-05-25: " +
                     ("nej" if old else "ja") + "."))

    # ---- Corporate ---------------------------------------------------------
    add(Contract("CTR-AKT-001", "AKTIEAGARE", "Aktieägaravtal", "corporate", None,
                 "Maja Lindqvist, Jonas Sandberg, Anders Bergström, Sara Holm, Erik Norén",
                 D(2021, 5, 20), D(2021, 5, 20), None, None, None, None, None, None, None, None,
                 "Hembudsförbehåll, samtyckeskrav vid överlåtelse, drag-along/tag-along, förköpsrätt.",
                 "Styrelsen samtycker vid nyemission.", True,
                 [ContractVersion(1, D(2021, 5, 20), "Ursprungligt avtal.")],
                 "ACTIVE", None, [], ["HEMBUD", "CONTROL_CHANGE"], None,
                 "Ägarandelar: Maja 42 %, Jonas 28 %, Anders 12 %, Sara 8 %, Erik 5 %, övriga 5 %."))
    add(Contract("CTR-AKT-002", "AKTIEAGARE", "Optionsprogram för nyckelpersoner", "corporate", None,
                 "Styrelsen och nyckelpersoner", D(2025, 6, 12), D(2025, 6, 12), None, None, None,
                 None, None, None, None, None, None, None, False,
                 [], "ACTIVE", None, [], [], None,
                 "Teckningsoptioner motsvarande 3 % av aktierna; lösen 2028. Kopplat till GQ-147 (nytt delägarskap)."))
    add(Contract("CTR-BANK-001", "LEVERANTORSAVTAL", "Checkräkningskredit", "corporate", None,
                 "Norrvidden Bank AB", D(2023, 4, 1), D(2023, 4, 1), D(2026, 12, 31), 12, 3, None,
                 "ABONNEMANG", None, None, None, "Limit 3 000 000 kr, ränta 5,40 %.",
                 None, False, [], "ACTIVE", None, [], [], None,
                 "Förnyas 2026-12-31; banken kräver kvartalsvisa covenant-rapporter (soliditet >= 25 %, EBITDA > 0)."))
    add(Contract("CTR-BANK-002", "LEVERANTORSAVTAL", "Banklån", "corporate", None,
                 "Norrvidden Bank AB", D(2023, 4, 1), D(2023, 4, 1), D(2028, 3, 31), None, None, None,
                 "FAST", None, 6_000_000, None, "Ursprungligt lån 6,0 MSEK; månadsbetalning 68 000 kr (ränta 4,15 % + amortering).",
                 None, False, [], "ACTIVE", None, [], [], None, ""))
    add(Contract("CTR-HYRA-002", "HYRA", "Tilläggsavtal extra våningsplan", "corporate", None,
                 "Kapellbacken Fastigheter AB", D(2026, 3, 2), D(2026, 7, 1), D(2027, 6, 30), None, 3, None,
                 "ABONNEMANG", None, 48_000, None, "Extra plan fr.o.m. 2026-07-01: 48 000 kr/mån (tillväxt).",
                 None, False, [], "ACTIVE", "STR-041", [], [], None, ""))
    return out


# ---------------------------------------------------------------- schedules
def schedules() -> list[InvoiceSchedule]:
    out: list[InvoiceSchedule] = []

    def time_sch(cid, contract_id, project_id, customer_id, rate, base_hours, start, end,
                 ramp=None, rate_changes=None, anomalies=None, noise=None, stepdown=None):
        s = InvoiceSchedule(cid, contract_id, project_id, customer_id, "TIME", rate,
                            {}, {}, rate_changes or {}, anomalies or {}, "")
        _fill_hours(s, start, end, base_hours, ramp, noise if noise is not None else None)
        if stepdown:
            for mk, lvl in stepdown.items():
                r2 = rng(f"hours:{cid}:{mk}")
                d0 = D(int(mk[:4]), int(mk[5:7]), 1)
                for (y2, m2) in month_range(max(start, d0), end):
                    s.monthly_hours[M(D(y2, m2, 1))] = _time_month_hours(lvl, y2, m2, r2)
        out.append(s)
        return s

    def fixed_sch(cid, contract_id, project_id, customer_id, milestones: dict):
        s = InvoiceSchedule(cid, contract_id, project_id, customer_id, "FIXED", 0, {}, {}, {}, {},
                            "Milestones: " + ", ".join(f"{k}={v}" for k, v in milestones.items()))
        s.monthly_amount = dict(milestones)
        out.append(s)
        return s

    def managed_sch(cid, contract_id, project_id, customer_id, amount, start, end):
        s = InvoiceSchedule(cid, contract_id, project_id, customer_id, "MANAGED", 0, {}, {}, {}, {}, "")
        for (y, m) in month_range(start, end):
            s.monthly_amount[M(D(y, m, 1))] = amount
        out.append(s)
        return s

    # SEAB
    fixed_sch("SCH-001", "CTR-2023-002", "PRJ-001", "CUS-001",
              {"2024-11": 900_000, "2025-02": 1_100_000, "2025-05": 1_300_000, "2025-08": 1_500_000,
               "2025-11": 1_400_000, "2026-02": 1_400_000, "2026-05": 1_000_000, "2026-07": 800_000})
    time_sch("SCH-002", "CTR-2026-002", "PRJ-002", "CUS-001", 1180, 800, D(2025, 1, 12), D(2026, 9, 30),
             ramp={"2025-01": 200, "2025-02": 280, "2025-03": 360}, stepdown={"2025-04": 700, "2025-10": 800})
    managed_sch("SCH-003", "CTR-2024-010", "PRJ-003", "CUS-001", 320_000, D(2025, 4, 1), D(2026, 9, 30))

    # Gråviken / Fyrstaden / Kustlandet
    time_sch("SCH-004", "CTR-2022-007", "PRJ-004", "CUS-002", 1050, 240, D(2024, 10, 1), D(2026, 9, 30),
             stepdown={"2025-10": 200},
             anomalies={mk: "MISSED_INDEX" for mk in [M(D(y, m, 1)) for (y, m) in month_range(D(2025, 10, 1), D(2026, 9, 30))]})
    fixed_sch("SCH-005", "CTR-2024-021", "PRJ-005", "CUS-003",
              {"2025-03": 300_000, "2025-05": 350_000, "2025-08": 300_000})
    managed_sch("SCH-006", "CTR-2025-014", "PRJ-006", "CUS-003", 85_000, D(2025, 10, 1), D(2026, 9, 30))
    time_sch("SCH-007", "CTR-2024-014", "PRJ-007", "CUS-004", 1090, 195, D(2024, 11, 4), D(2026, 3, 31),
             stepdown={"2025-10": 145})

    # Kustbandets Färjor (underbilling)
    time_sch("SCH-008", "CTR-2023-015", "PRJ-008", "CUS-005", 1050, 220, D(2024, 10, 1), D(2026, 9, 30),
             stepdown={"2025-10": 190},
             rate_changes={"2025-11": 1150},
             anomalies={"2025-11": "UNDERBILL_RATE", "2025-12": "UNDERBILL_RATE", "2026-01": "UNDERBILL_RATE"})

    # Timmerviken (fast pris + kreditnota)
    fixed_sch("SCH-009", "CTR-2025-011", "PRJ-009", "CUS-006",
              {"2025-11": 450_000, "2026-01": 450_000, "2026-04": 450_000, "2026-05": 450_000})

    # Blåklinten (missad index)
    time_sch("SCH-010", "CTR-2023-018", "PRJ-010", "CUS-007", 990, 195, D(2024, 10, 1), D(2026, 9, 30),
             stepdown={"2025-10": 150},
             anomalies={mk: "MISSED_INDEX" for mk in [M(D(y, m, 1)) for (y, m) in month_range(D(2026, 4, 1), D(2026, 9, 30))]})

    time_sch("SCH-011", "CTR-2024-030", "PRJ-011", "CUS-008", 1030, 130, D(2025, 1, 6), D(2026, 6, 30),
             stepdown={"2025-10": 100})
    fixed_sch("SCH-012", "CTR-2024-016", "PRJ-012", "CUS-009",
              {"2024-11": 400_000, "2025-01": 550_000, "2025-02": 500_000})
    time_sch("SCH-013", "CTR-2024-031", "PRJ-013", "CUS-010", 1020, 86.3, D(2025, 3, 3), D(2025, 11, 30),
             noise=False)
    time_sch("SCH-014", "CTR-2023-021", "PRJ-014", "CUS-011", 1120, 175, D(2024, 10, 1), D(2025, 12, 31))
    managed_sch("SCH-015", "CTR-2025-020", "PRJ-015", "CUS-011", 95_000, D(2026, 1, 1), D(2026, 9, 30))
    fixed_sch("SCH-016", "CTR-2025-002", "PRJ-016", "CUS-012",
              {"2025-04": 250_000, "2025-06": 280_000, "2025-09": 250_000, "2025-11": 200_000})
    time_sch("SCH-017", "CTR-2023-026", "PRJ-017", "CUS-013", 1150, 205, D(2024, 10, 1), D(2026, 9, 30),
             stepdown={"2025-10": 160})
    fixed_sch("SCH-018", "CTR-2025-006", "PRJ-018", "CUS-014",
              {"2025-07": 400_000, "2025-10": 600_000, "2026-01": 700_000, "2026-03": 700_000})
    time_sch("SCH-019", "CTR-2025-007", "PRJ-019", "CUS-015", 1180, 215, D(2025, 4, 1), D(2026, 9, 30),
             stepdown={"2025-10": 170})
    time_sch("SCH-020", "CTR-2022-028", "PRJ-020", "CUS-016", 1080, 135, D(2024, 10, 1), D(2026, 9, 30),
             stepdown={"2025-10": 115})
    fixed_sch("SCH-021", "CTR-2025-009", "PRJ-021", "CUS-017",
              {"2025-09": 350_000, "2025-11": 400_000, "2026-01": 350_000})
    time_sch("SCH-022", "CTR-2025-008", "PRJ-022", "CUS-018", 1040, 100, D(2025, 5, 5), D(2026, 4, 30),
             stepdown={"2025-10": 85})
    time_sch("SCH-023", "CTR-2025-013", "PRJ-023", "CUS-019", 1060, 95, D(2025, 9, 1), D(2026, 9, 30),
             stepdown={"2025-10": 80})
    fixed_sch("SCH-024", "CTR-2025-019", "PRJ-024", "CUS-020",
              {"2026-02": 250_000, "2026-05": 300_000, "2026-08": 300_000})
    time_sch("SCH-025", "CTR-2024-032", "PRJ-025", "CUS-021", 1010, 85, D(2025, 2, 3), D(2025, 10, 31))
    fixed_sch("SCH-026", "CTR-2025-016", "PRJ-026", "CUS-022",
              {"2025-12": 400_000, "2026-03": 500_000, "2026-06": 400_000, "2026-08": 300_000})
    time_sch("SCH-027", "CTR-2025-004", "PRJ-027", "CUS-023", 1110, 125, D(2025, 3, 3), D(2026, 2, 27),
             stepdown={"2025-10": 108})
    time_sch("SCH-028", "CTR-2025-022", "PRJ-028", "CUS-024", 1030, 80, D(2026, 2, 2), D(2026, 9, 30))
    fixed_sch("SCH-029", "CTR-2026-001", "PRJ-029", "CUS-025",
              {"2026-04": 500_000, "2026-06": 600_000, "2026-09": 500_000})
    time_sch("SCH-030", "CTR-2025-015", "PRJ-030", "CUS-028", 990, 80, D(2025, 8, 4), D(2026, 9, 30))

    # Small customers (SCH-051..) – (fy25_hours, fy26_hours)
    small = [
        ("SCH-051", "CUS-026", 990, 36, 31, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-052", "CUS-027", 1010, 45, 39, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-053", "CUS-029", 950, 26, 23, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-054", "CUS-030", 1020, 36, 31, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-055", "CUS-031", 1000, 29, 25, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-056", "CUS-032", 960, 24, 21, D(2025, 1, 1), D(2026, 9, 30)),
        ("SCH-057", "CUS-033", 990, 43, 37, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-058", "CUS-034", 950, 21, 18, D(2025, 3, 1), D(2026, 9, 30)),
        ("SCH-059", "CUS-035", 1040, 33, 29, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-060", "CUS-036", 950, 24, 21, D(2024, 10, 1), D(2025, 12, 31)),
        ("SCH-061", "CUS-037", 1010, 39, 34, D(2025, 2, 1), D(2026, 9, 30)),
        ("SCH-062", "CUS-038", 940, 18, 16, D(2025, 4, 1), D(2026, 9, 30)),
        ("SCH-063", "CUS-039", 990, 29, 25, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-064", "CUS-040", 1030, 36, 31, D(2025, 6, 1), D(2026, 9, 30)),
        ("SCH-065", "CUS-041", 1000, 26, 23, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-066", "CUS-042", 950, 24, 21, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-067", "CUS-043", 950, 21, 18, D(2025, 5, 1), D(2026, 9, 30)),
        ("SCH-068", "CUS-044", 950, 15, 13, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-069", "CUS-045", 1050, 48, 42, D(2025, 1, 1), D(2026, 9, 30)),
        ("SCH-070", "CUS-046", 980, 53, 46, D(2025, 7, 1), D(2026, 9, 30)),
        ("SCH-071", "CUS-047", 1020, 24, 21, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-072", "CUS-048", 1000, 33, 29, D(2026, 1, 1), D(2026, 9, 30)),
        ("SCH-073", "CUS-049", 990, 43, 37, D(2024, 10, 1), D(2026, 9, 30)),
        ("SCH-074", "CUS-050", 950, 18, 16, D(2024, 10, 1), D(2026, 9, 30)),
    ]
    for i, (sid, cid, rate, fy25, fy26, start, end) in enumerate(small):
        time_sch(sid, small_contract_id(i, start), None, cid, rate, fy25, start, end,
                 stepdown={"2025-10": fy26})
    return out


def small_contract_id(i, start):
    """Shared mapping: contract id for the i-th small-customer contract."""
    return f"CTR-SM-{51 + i:03d}"


# ---------------------------------------------------------------- streams
def streams() -> list[SupplierStream]:
    out: list[SupplierStream] = []
    r = rng("streams")

    def add(sid, supplier, account, label, amount, start, end, vat="0.25", rc=False,
            noise_pct=0.0, changes=None):
        s = SupplierStream(sid, supplier, account, label, {}, vat, rc, "")
        amt = amount
        for (y, m) in month_range(start, end):
            v = amt
            if noise_pct:
                v = round(amt * (1 + r.uniform(-noise_pct, noise_pct)))
            if changes and M(D(y, m, 1)) in changes:
                v = changes[M(D(y, m, 1))]
            s.monthly_amount[M(D(y, m, 1))] = v
        out.append(s)
        return s

    add("STR-001", "SUP-001", "5010", "Lokalhyra", 165_000, D(2024, 10, 1), D(2026, 9, 30),
        changes={"2026-01": 172_000})
    add("STR-002", "SUP-023", "5020", "El", 13_500, D(2024, 10, 1), D(2026, 9, 30), noise_pct=0.20)
    add("STR-003", "SUP-024", "5060", "Städning", 8_500, D(2024, 10, 1), D(2026, 9, 30), noise_pct=0.05)
    add("STR-004", "SUP-003", "5420", "M365 och Azure", 95_000, D(2024, 10, 1), D(2026, 9, 30),
        rc=True, changes={"2025-01": 98_000, "2026-03": 102_000})
    add("STR-005", "SUP-004", "5420", "Hosting", 22_000, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-006", "SUP-005", "5420", "Ärendehantering och wiki", 14_500, D(2024, 10, 1), D(2026, 9, 30),
        changes={"2025-06": 16_200})
    add("STR-007", "SUP-006", "5420", "Chattverktyg", 9_800, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-008", "SUP-007", "5420", "Designverktyg", 11_200, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-009", "SUP-008", "5420", "VPN och säkerhet", 13_600, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-010", "SUP-009", "5420", "CRM", 8_400, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-011", "SUP-010", "5420", "Lönesystem", 4_200, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-012", "SUP-011", "5420", "Ekonomisystem", 9_600, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-013", "SUP-012", "5420", "AI-modell-API:er", 18_500, D(2024, 10, 1), D(2026, 9, 30),
        changes={"2026-01": 24_500})
    add("STR-014", "SUP-013", "5420", "Analysmolntjänst (USA)", 6_200, D(2024, 10, 1), D(2026, 9, 30), rc=True)
    add("STR-015", "SUP-014", "5420", "Analysverktyg Datainsikt", 7_800, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-016", "SUP-015", "5420", "Samarbetsyta Whiteboard", 6_400, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-017", "SUP-016", "5420", "CI/CD Bygglådan", 5_200, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-018", "SUP-017", "5420", "Monitoring Vakthuset", 6_800, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-019", "SUP-018", "5420", "E-signatur", 3_400, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-020", "SUP-019", "6210", "Telefoni", 12_000, D(2024, 10, 1), D(2026, 9, 30), noise_pct=0.08)
    add("STR-021", "SUP-020", "5420", "Dokumenthantering", 5_600, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-022", "SUP-021", "5420", "Backup", 7_200, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-023", "SUP-022", "5420", "HR-system", 3_800, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-024", "SUP-025", "7410", "Pensionspremier", 0, D(2024, 10, 1), D(2026, 9, 30))  # fylls av motorn
    add("STR-025", "SUP-026", "5910", "Marknadsföring löpande", 35_000, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-026", "SUP-027", "6110", "Kontorsmaterial", 9_000, D(2024, 10, 1), D(2026, 9, 30), noise_pct=0.25)
    add("STR-027", "SUP-028", "5800", "Resor", 26_000, D(2024, 10, 1), D(2026, 9, 30), noise_pct=0.35)
    add("STR-028", "SUP-029", "5615", "Billeasing", 12_800, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-029", "SUP-030", "5616", "IT-utrustningsleasing", 24_000, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-030", "SUP-031", "7699", "Rekrytering (löpande avtal, per uppdrag)", 0, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-031", "SUP-032", "7610", "Utbildning löpande", 12_000, D(2024, 10, 1), D(2026, 9, 30), noise_pct=0.4)
    add("STR-032", "SUP-033", "6991", "Juridik löpande", 15_000, D(2025, 9, 1), D(2026, 9, 30))
    add("STR-033", "SUP-034", "4520", "Underkonsulter Kraftkod", 136_000, D(2025, 1, 1), D(2026, 7, 31))
    add("STR-034", "SUP-035", "4520", "Underkonsult Dataverket", 58_800, D(2025, 3, 1), D(2026, 9, 30),
        changes={"2026-06": 117_600})
    add("STR-035", "SUP-036", "4520", "Underkonsult Testhuset", 40_500, D(2025, 6, 1), D(2026, 9, 30))
    add("STR-036", "SUP-037", "4520", "Underkonsult Pixel & Form", 44_500, D(2024, 10, 1), D(2026, 3, 31))
    add("STR-038", "SUP-038", "6310", "Företagsförsäkring", 21_000, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-039", "SUP-039", "6420", "Revision", 0, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-040", "SUP-040", "6540", "Löpande redovisning", 18_000, D(2024, 10, 1), D(2026, 9, 30))
    add("STR-041", "SUP-001", "5010", "Hyra extra våningsplan", 48_000, D(2026, 7, 1), D(2026, 9, 30))
    return out
