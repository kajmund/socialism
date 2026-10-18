"""Story: business events timeline (canonical truth).

Every anomaly, decision and document-worthy happening is registered here as an
Event. Finance posts and generated documents link back to these IDs.
"""
from __future__ import annotations

from datetime import date

from .model import Event

D = date


def events() -> list[Event]:
    e: list[Event] = []

    def add(eid, d, etype, title, desc, entities=None, docs=None, vouchers=None, invoices=None, note=""):
        e.append(Event(eid, d, etype, title, desc, entities or [], docs or [], vouchers or [], invoices or [], note))

    # ---- 2024 ----
    add("EVT-001", D(2024, 10, 7), "MGMT", "Ledningsgrupp: budgetförutsättningar FY25",
        "Ledningsgruppen går igenom budgetförutsättningar för FY25 (okt 2024–sep 2025). Omsättningsmål 41 MSEK, EBIT-mål 6 %.",
        ["P-001", "P-002", "P-003", "P-005", "P-007"], ["DOC-MGMT-001"])
    add("EVT-002", D(2024, 10, 15), "INCIDENT", "Säkerhetsincident: phishing",
        "Phishingmejl till ekonomiavdelningen; två medarbetare klickade. Inget konstaterat dataintrång. Incidentrapport upprättad.",
        ["P-003", "P-006"], ["DOC-SEC-001"], note="GQ-178 (säkerhetsincidenter).")
    add("EVT-003", D(2024, 11, 1), "HIRE", "Nyanställning DevOps",
        "Patrik Öberg (EMP-027) börjar som DevOps-ingenjör.",
        ["P-027"], [], [], [], "Lön 54 000 kr/mån.")
    add("EVT-004", D(2024, 11, 15), "LEAVE", "Gustav Pettersson slutar",
        "Gustav Pettersson (EMP-032) sade upp sig och gick till konkurrenten Blå Ocean IT AB. Konkurrensklausul (12 mån) i anställningsavtalet diskuteras med advokat.",
        ["P-032", "P-041"], ["DOC-HR-001", "DOC-MAIL-001"], note="GQ-108.")
    add("EVT-005", D(2024, 11, 21), "BOARD", "Styrelsemöte (nov)",
        "Styrelsen fastställer FY25-budget. Beslut: bibehållen investeringsnivå, rekryteringsplan 6 nyanställningar, mål beläggning >= 82 %.",
        ["P-038", "P-039", "P-001", "P-002", "P-003"], ["DOC-BOARD-001"])
    add("EVT-006", D(2024, 11, 29), "DECISION", "Datorinköp aktiveras",
        "Beslut om inköp av 20 laptops + skärmar (350 000 kr ex moms) från Datorlagret; aktiveras som datorer (3 års avskrivning).",
        ["P-002", "P-003"], [], ["C-2024-014"], ["SIN-2024-014"], "Verk: C-2024-014.")
    add("EVT-007", D(2024, 12, 18), "COMPLAINT", "Kundklagomål: NH-Logistikportal",
        "Norrhamns Hamn klagar på prestanda i NH-Logistikportal (tredje gången på samma tema). Åtgärdsplan beslutad.",
        ["CUS-011"], ["DOC-MAIL-002", "DOC-COM-001"], note="GQ-046, GQ-158.")
    add("EVT-008", D(2024, 12, 20), "MGMT", "Ledningsgrupp: riskgenomgång",
        "Halvårsvis riskgenomgång. Riskregistret uppdateras; kundkoncentration (SEAB) och nyckelpersonsberoende lyfts till styrelsen.",
        ["P-001", "P-003", "P-007"], ["DOC-MGMT-002", "DOC-RISK-001"])

    # ---- 2025 ----
    add("EVT-009", D(2025, 1, 7), "MGMT", "Ledningsgrupp: SE-Integration start",
        "Uppstart SE-Integration (löpande konsultstöd till SEAB, 1 150 kr/h initialt).",
        ["CUS-001", "P-007"], ["DOC-MGMT-003"])
    add("EVT-010", D(2025, 1, 12), "HIRE", "Nyanställning utvecklare",
        "Viktor Lind (EMP-019) börjar som utvecklare.", ["P-019"], [], [], [], "Lön 48 000 kr/mån.")
    add("EVT-011", D(2025, 1, 31), "LEAVE", "Martina Bergqvist slutar",
        "Martina Bergqvist (EMP-033) slutar; flyttar till Göteborg.", ["P-033"], ["DOC-HR-002"])
    add("EVT-012", D(2025, 2, 3), "HIRE", "Nyanställning senior utvecklare",
        "Camilla Westin (EMP-018) börjar som senior utvecklare.", ["P-018"], [], [], [], "Lön 59 000 kr/mån.")
    add("EVT-013", D(2025, 2, 10), "BOARD", "Styrelsemöte (feb)",
        "Kvartalsrapport Q1 (okt–dec). Styrelsen noterar att checkräkningskrediten var utnyttjad till 190 000 kr i december och att likviditeten försämras; beslut om månatlig likviditetsprognos.",
        ["P-038", "P-001", "P-003"], ["DOC-BOARD-002"])
    add("EVT-014", D(2025, 2, 28), "CREDIT_NOTE", "ÖH-Webbplattform: tvistig slutfaktura",
        "Örby Handel bestrider slutfakturan (500 000 kr ex moms). Kunden betalar 528 200 kr (625 000 − 96 800) och håller inne 96 800 kr p.g.a. acceptansanmärkningar. Tvist pågår.",
        ["CUS-009", "P-041"], ["DOC-MAIL-003"], [], ["INV-2025-0030"], note="GQ-004, GQ-046.")
    add("EVT-015", D(2025, 3, 10), "DECISION", "Datorinköp aktiveras",
        "Inköp av servrar och nätverksutrustning 480 000 kr ex moms (aktiveras).",
        ["P-002"], [], ["C-2025-018"], ["SIN-2025-018"])
    add("EVT-016", D(2025, 3, 14), "LEAVE", "Tobias Lindqvist avskedas",
        "Tobias Lindqvist (EMP-034) avskedas p.g.a. bristande prestation. Medarbetaren bestrider uppsägningen via facket. Tvist.",
        ["P-034"], ["DOC-HR-003", "DOC-MAIL-004"], note="GQ-075, GQ-103.")
    add("EVT-017", D(2025, 3, 31), "CONTRACT_END", "Örby Handel lämnar oss",
        "Örby Handel & Logistik AB avslutar samarbetet 2025-03-31 (tvisten olöst).", ["CUS-009"], ["DOC-MAIL-005"])
    add("EVT-018", D(2025, 4, 1), "HIRE", "Nyanställning junior utvecklare",
        "Alice Forsberg (EMP-022) börjar som junior utvecklare (exjobb).", ["P-022"], [], [], [], "Lön 34 000 kr/mån.")
    add("EVT-019", D(2025, 4, 3), "RAISE", "Lönerevision 2025",
        "Årlig lönerevision: 8 medarbetare får höjningar fr.o.m. 2025-04-01 (se löneunderlag).",
        ["P-001", "P-004", "P-005", "P-008", "P-017", "P-020", "P-024", "P-025", "P-036"], ["DOC-HR-004"])
    add("EVT-020", D(2025, 4, 15), "DECISION", "Förlikningsförhandling Tobias Lindqvist",
        "Advokat Krav & Klar förhandlar med Tobias Lindqvists ombud. Motbud 6 månadslöner.",
        ["P-034", "P-041"], ["DOC-MAIL-006"], note="GQ-075.")
    add("EVT-021", D(2025, 4, 28), "MGMT", "Ledningsgrupp: kapacitetsbrist",
        "Leveranschefen flaggar kapacitetsbrist i leveransteamet (beläggning > 95 % i maj–juni). Beslut: öka underkonsultanvändning och prioritera rekrytering.",
        ["P-007", "P-001", "P-005"], ["DOC-MGMT-004"], note="GQ-072, GQ-137.")
    add("EVT-022", D(2025, 5, 19), "BOARD", "Styrelsemöte (maj)",
        "Kvartalsrapport Q2. Godkänd. Diskussion om SEAB-beroendet (30 % av omsättningen).",
        ["P-038", "P-039", "P-001", "P-003"], ["DOC-BOARD-003"], note="GQ-042, GQ-127.")
    add("EVT-023", D(2025, 6, 30), "LEAVE", "Jenny Lindholm slutar",
        "Jenny Lindholm (EMP-035) slutar för ny roll i annan bransch.", ["P-035"], ["DOC-HR-005"])
    add("EVT-024", D(2025, 6, 12), "DECISION", "Optionsprogram beslutas",
        "Styrelsen beslutar om teckningsoptionsprogram för nyckelpersoner (3 %).", ["P-038", "P-001"], ["DOC-BOARD-003"], note="GQ-147.")
    add("EVT-025", D(2025, 8, 18), "HIRE", "Nyanställning DevOps",
        "Simon Dahl (EMP-028) börjar som DevOps-ingenjör.", ["P-028"], [], [], [], "Lön 52 000 kr/mån.")
    add("EVT-026", D(2025, 8, 15), "DECISION", "Möbelinköp aktiveras",
        "Inköp av möbler till nya kontorsplatser 250 000 kr ex moms (inventarier, 5 år).",
        ["P-004"], [], ["C-2025-041"], ["SIN-2025-041"])
    add("EVT-027", D(2025, 8, 27), "SETTLEMENT", "Förlikning Tobias Lindqvist",
        "Förlikning: avgångsvederlag 3 månadslöner (141 000 kr) + advokatkostnader. Utbetalas 2025-09-05.",
        ["P-034", "P-041"], ["DOC-HR-006"], ["D-2025-008"], [], "Lönekörning september: 141 000 kr (7210/7510).")
    add("EVT-028", D(2025, 8, 31), "PAYMENT_DELAY", "Likviditetsansträngning",
        "Likviditeten var som mest ansträngd i mars (checkkrediten utnyttjad till 1,18 MSEK). Läget har förbättrats, men ledningen inför veckovisa likviditetsavstämningar inför bankmötet.",
        ["P-003", "P-001"], ["DOC-MGMT-005"], note="GQ-005, GQ-186.")
    add("EVT-029", D(2025, 9, 1), "HIRE", "Nyanställning utvecklare",
        "Robin Åkerlund (EMP-021) börjar som utvecklare.", ["P-021"], [], [], [], "Lön 46 000 kr/mån.")
    add("EVT-030", D(2025, 9, 15), "MGMT", "Bankmöte: covenant",
        "Norrvidden Bank kräver kvartalsvisa covenant-rapporter (soliditet >= 25 %, EBITDA > 0) och månatlig likviditetsprognos som villkor för förnyad checkkredit.",
        ["P-042", "P-003", "P-001"], ["DOC-BANK-001"], note="GQ-029.")
    add("EVT-031", D(2025, 9, 25), "BOARD", "Styrelsemöte (sep): budget FY26",
        "Styrelsen fastställer FY26-budget: omsättning 47 MSEK, EBIT-mål 7 %, investeringsram produktutveckling 2,4 MSEK.",
        ["P-038", "P-039", "P-001", "P-002", "P-003"], ["DOC-BOARD-004", "DOC-BUDG-001"], note="GQ-021, GQ-129.")
    add("EVT-032", D(2025, 9, 30), "PERIOD", "Bokslut FY2025",
        "Räkenskapsåret 2024-10-01–2025-09-30 avslutas. Revision november.",
        ["P-003", "P-040"], ["DOC-FIN-001"], ["E-2025-090"], note="Årsbokslut.")
    add("EVT-033", D(2025, 10, 1), "INDEX_MISSED", "Gråvikens kommun: indexuppräkning missad",
        "Enligt ramavtalet (CTR-2022-007) skulle timpriset räknas upp med KPI per 2025-10-01 (bas 2023-10). Uppräkningen har inte tillämpats i faktureringen. Ingen har agerat.",
        ["CUS-002"], ["DOC-MAIL-007"], note="GQ-053, GQ-092.")
    add("EVT-034", D(2025, 10, 31), "LEAVE", "Rasmus Holm slutar – rekryterad av kund",
        "Rasmus Holm (EMP-036) slutar och börjar hos kunden Skogsbygdens Energi AB. Intressekonflikt och konkurrensklausul diskuteras i ledningsgruppen.",
        ["P-036", "CUS-001"], ["DOC-HR-007", "DOC-MGMT-006"], note="GQ-108.")
    add("EVT-035", D(2025, 11, 1), "UNDERBILLING", "KF-Biljettsystem: indexhöjning ej debiterad",
        "Enligt avtalet gäller 1 150 kr/h fr.o.m. 2025-11-01, men faktureringen fortsätter på 1 050 kr/h (internt fel i debiteringsunderlaget).",
        ["CUS-005"], ["DOC-MAIL-008"], note="GQ-052, GQ-053. Upptäckt 2026-02.")
    add("EVT-036", D(2025, 11, 8), "DECISION", "Kickoff produktutveckling",
        "Start av ND-Intern plattform (produktutveckling). Budget 2,4 MSEK.",
        ["P-002", "P-026"], ["DOC-MGMT-007"], note="GQ-026, GQ-144.")
    add("EVT-037", D(2025, 11, 20), "DECISION", "Revisionsarvode FY25",
        "Revision & Tal fakturerar 95 000 kr för revision av FY2025.", ["P-040", "P-003"], [], ["C-2025-052"], ["SIN-2025-052"])
    add("EVT-038", D(2025, 11, 24), "BOARD", "Styrelsemöte (nov)",
        "Godkännande av bokslutskommuniké FY25. Resultat efter skatt presenteras. Styrelsen skjuter upp utdelningsbeslut till årsstämman.",
        ["P-038", "P-039", "P-001", "P-003"], ["DOC-BOARD-005"], note="GQ-150.")
    add("EVT-039", D(2025, 12, 8), "BANKRUPTCY", "Sjöstadens Bryggeri i konkurs",
        "Kunden Sjöstadens Bryggeri AB försätts i konkurs. Konkursförvaltare Carl Broman. Septemberfakturan (110 032,50 kr) hölls inne p.g.a. reklamation, oktoberfakturan betalades sent (2025-11-20) och novemberfakturan (110 032,50 kr) förblev obetald.",
        ["CUS-010", "P-054"], ["DOC-MAIL-009"], note="GQ-182, GQ-004.")
    add("EVT-040", D(2025, 12, 31), "DECISION", "Kundförlust avskriven",
        "Kundfordringar på Sjöstadens Bryggeri (september- och novemberfakturorna, totalt 220 065,00 kr) konstateras som kundförlust (6351). Ingen momsåtervinning.",
        ["CUS-010"], [], ["A-2025-096"], [], "Bokförd 2025-12-31.")

    # ---- 2026 ----
    add("EVT-041", D(2026, 1, 12), "HIRE", "Nyanställning junior utvecklare",
        "Hugo Larsson (EMP-023) börjar som junior utvecklare.", ["P-023"], [], [], [], "Lön 35 000 kr/mån.")
    add("EVT-042", D(2026, 1, 15), "CONTRACT_SIGN", "SEAB-ramavtal förlängt",
        "Förlängning av ramavtalet med SEAB (CTR-2026-002): 1 180 kr/h, t.o.m. 2028-01-31.",
        ["CUS-001"], ["DOC-CTR-026"], note="GQ-045, GQ-052.")
    add("EVT-043", D(2026, 1, 20), "DECISION", "Datorinköp aktiveras",
        "Inköp av arbetsstationer 520 000 kr ex moms (aktiveras).", ["P-002"], [], ["C-2026-006"], ["SIN-2026-006"])
    add("EVT-044", D(2026, 1, 30), "MGMT", "Ledningsgrupp: AI-strategi",
        "Beslut om internt AI-initiativ (ND-Intern AI). Budget 1,2 MSEK 2026. AI-policyn fastställs.",
        ["P-001", "P-002", "P-026"], ["DOC-MGMT-008", "DOC-POL-004"], note="GQ-176, GQ-180.")
    add("EVT-045", D(2026, 2, 6), "CONTRACT_SIGN", "Tilläggsavtal SE-Billing",
        "Tilläggsavtal CTR-2026-004: slutdatum 2026-07-15, +800 000 kr.",
        ["CUS-001"], ["DOC-CTR-030"], note="GQ-086.")
    add("EVT-046", D(2026, 2, 10), "UNDERBILLING", "KF-underfakturering upptäckt",
        "Ekonomichefen upptäcker att KF-Biljettsystem fakturerats med 1 050 kr/h i stället för 1 150 kr/h sedan 2025-11-01. Eftersläpningsfaktura beslutas.",
        ["CUS-005", "P-003"], ["DOC-MAIL-010"], note="GQ-052, GQ-053.")
    add("EVT-047", D(2026, 2, 24), "CONTRACT_SIGN", "SU-Produktionssystem signerat",
        "Nytt avtal med Sundbygdens Varv (CTR-2026-001): fast pris 1,95 MSEK, vite 1 %/vecka (tak 10 %), källkodsdepåkrav.",
        ["CUS-025"], ["DOC-CTR-031"], note="GQ-100.")
    add("EVT-048", D(2026, 2, 28), "LEAVE", "Anna Westberg slutar",
        "Anna Westberg (EMP-037) slutar; uppger arbetsbelastning i avslutssamtal.", ["P-037"], ["DOC-HR-008"], note="GQ-075, GQ-078.")
    add("EVT-071", D(2026, 1, 31), "LEAVE", "Robin Åkerlunds provanställning avslutas",
        "Robin Åkerlunds (EMP-021) provanställning avslutas 2026-01-31.", ["P-021"], ["DOC-HR-010"], note="GQ-071.")
    add("EVT-072", D(2026, 2, 27), "LEAVE", "Magnus Ryd säger upp sig",
        "Magnus Ryd (EMP-010) säger upp sig (3 mån uppsägning); uppger utmattningsrelaterade skäl i avslutssamtal. Sista dag 2026-03-31.",
        ["P-010"], ["DOC-HR-011"], note="GQ-072, GQ-075, GQ-078.")
    add("EVT-073", D(2026, 4, 29), "LEAVE", "Sofia Lindgren säger upp sig",
        "Sofia Lindgren (EMP-016) säger upp sig; börjar hos kunden Polstjärnan Försäkring AB 2026-07-01. Sista dag hos oss 2026-06-30.",
        ["P-016", "CUS-015"], ["DOC-HR-012"], note="GQ-075.")
    add("EVT-074", D(2026, 5, 31), "LEAVE", "Lukas Ek lämnar",
        "Lukas Ek (EMP-031) lämnar 2026-05-31; rekryterad av underkonsulten Dataverket Nord AB. Daniel Nyström blir ensam dataspecialist (nyckelpersonsrisk).",
        ["P-031"], ["DOC-HR-013"], note="GQ-070, GQ-184.")
    add("EVT-075", D(2026, 7, 1), "LEAVE", "Björn Falk säger upp sig",
        "Björn Falk (EMP-029) säger upp sig 2026-07-01 (2 mån uppsägning); flyttar utomlands. Sista dag 2026-08-31.",
        ["P-029"], ["DOC-HR-014"], note="GQ-071.")
    add("EVT-076", D(2026, 8, 27), "LEAVE", "Klara Månsson säger upp sig",
        "Klara Månsson (EMP-030) säger upp sig (1 mån uppsägning). Sista dag 2026-09-30. Supporten står därefter utan ansvarig.",
        ["P-030"], ["DOC-HR-015"], note="GQ-066, GQ-153.")
    add("EVT-049", D(2026, 2, 28), "DECISION", "Eftersläpningsfaktura KF",
        "Eftersläpningsfaktura till Kustbandets Färjor: 3 månader × (1 150 − 1 050) kr/h × fakturerade timmar.",
        ["CUS-005"], [], ["B-2026-018"], ["INV-2026-0036"], note="Beräknas av motorn.")
    add("EVT-050", D(2026, 3, 2), "DECISION", "Extra kontorsplan",
        "Tilläggshyra extra våningsplan fr.o.m. 2026-07-01 (48 000 kr/mån) för planerad tillväxt.",
        ["P-004", "P-001"], ["DOC-CTR-032"], note="GQ-024, GQ-194.")
    add("EVT-051", D(2026, 3, 12), "BOARD", "Styrelsemöte (mars)",
        "Q2-rapport (okt–dec FY26). Styrelsen uttrycker oro för SEAB-beroendet (35 %) och beslutar om fördjupad scenarioanalys.",
        ["P-038", "P-039", "P-001", "P-003"], ["DOC-BOARD-006"], note="GQ-127, GQ-182.")
    add("EVT-052", D(2026, 3, 20), "MGMT", "Bankmöte: förnyad checkkredit",
        "Banken bekräftar förnyad checkkredit t.o.m. 2026-12-31 under förutsättning av covenants.",
        ["P-042", "P-003"], ["DOC-BANK-002"], note="GQ-029.")
    add("EVT-053", D(2026, 3, 26), "CONTRACT_END", "Mossbackens Mekaniska säger upp",
        "Mossbackens Mekaniska säger upp MM-Underhållssystem (3 mån uppsägning) – kunden går till konkurrent med lägre pris.",
        ["CUS-008"], ["DOC-MAIL-011"], note="GQ-044, GQ-055.")
    add("EVT-054", D(2026, 4, 1), "INDEX_MISSED", "Blåklintens Vård: indexuppräkning missad",
        "Enligt avtalet (CTR-2023-018) skulle timpriset räknas upp med KPI per 2026-04-01 (bas 2024-04). Har inte tillämpats.",
        ["CUS-007"], ["DOC-MAIL-012"], note="GQ-053.")
    add("EVT-055", D(2026, 4, 1), "RAISE", "Lönerevision 2026",
        "Årlig lönerevision: 12 medarbetare får höjningar fr.o.m. 2026-04-01.",
        ["P-003", "P-006", "P-009", "P-012", "P-014", "P-015", "P-018", "P-019", "P-022", "P-026", "P-027", "P-029", "P-030", "P-031"], ["DOC-HR-009"])
    add("EVT-056", D(2026, 4, 20), "INCIDENT", "Integrationshaveri lönesystem",
        "Integrationen lönesystem -> ekonomisystem fallerade (tredje gången på 6 månader). Manuell överföring tog 2 dagar.",
        ["P-003"], ["DOC-IT-001"], note="GQ-172, GQ-175.")
    add("EVT-057", D(2026, 5, 4), "HIRE", "Nyanställning arkitekt",
        "Nadia Haddad (EMP-012) börjar som lösningsarkitekt (senior specialist, rekrytering via Talangjakten).",
        ["P-012"], [], [], [], "Lön 72 000 kr/mån.")
    add("EVT-058", D(2026, 5, 25), "BOARD", "Styrelsemöte (maj)",
        "Q3-rapport. Styrelsen efterfrågar åtgärder mot försenade projekt och underfakturering. Prognos revideras.",
        ["P-038", "P-039", "P-001", "P-003"], ["DOC-BOARD-007"], note="GQ-143.")
    add("EVT-059", D(2026, 6, 1), "DECISION", "Helårsprognos reviderad",
        "CFO presenterar reviderad helårsprognos FY26 (bas/scenario) – lägre än budget p.g.a. kundförlust och förseningar.",
        ["P-003"], ["DOC-BUDG-002"], note="GQ-022, GQ-028.")
    add("EVT-060", D(2026, 6, 12), "DECISION", "Slutlig skatt FY25 betald",
        "Slutlig skatt FY2025 regleras via skattekontot.", ["P-003"], [], ["A-2026-045"])
    add("EVT-061", D(2026, 6, 30), "CREDIT_NOTE", "TS-Produktionsportal: förlikning",
        "Förlikning med Timmervikens Såg: kreditnota 90 000 kr (motsvarande 50 % av avtalsenligt vite) mot slutacceptans.",
        ["CUS-006"], ["DOC-MAIL-013"], ["B-2026-032"], ["KIN-2026-001"], note="GQ-046, GQ-182.")
    add("EVT-062", D(2026, 6, 30), "CONTRACT_END", "Mossbackens Mekaniska lämnar",
        "Samarbetet med Mossbackens Mekaniska upphör 2026-06-30 (kunden gick till konkurrent).", ["CUS-008"], [], note="GQ-043.")
    add("EVT-063", D(2026, 7, 15), "DECISION", "SE-Billing slutlevererad",
        "SE-Billing slutlevererad och godkänd 2026-07-15. Slutmilestone 800 000 kr faktureras.",
        ["CUS-001"], ["DOC-PRJ-030"], note="GQ-151.")
    add("EVT-064", D(2026, 8, 4), "INCIDENT", "Driftstörning Nordhost",
        "Nordhost-driften låg nere 6 timmar; kundpåverkan på förvaltningskunder. SLA-ersättning diskuteras.",
        ["SUP-004"], ["DOC-IT-002"], note="GQ-171, GQ-187.")
    add("EVT-065", D(2026, 8, 20), "MGMT", "Ledningsgrupp: kostnadsprogram",
        "Beslut om kostnadsöversyn inför FY27: licensinventering, utvärdering av underutnyttjade verktyg, pausad rekrytering.",
        ["P-001", "P-003", "P-005", "P-007"], ["DOC-MGMT-009"], note="GQ-018, GQ-163, GQ-196.")
    add("EVT-066", D(2026, 9, 2), "INCIDENT", "AI-verktyg med osäkra svar",
        "Internt AI-verktyg levererade svar utan källstöd i två kundrapporter; korrigerades efter granskning. Logg saknas.",
        ["P-026"], ["DOC-IT-003"], note="GQ-180.")
    add("EVT-067", D(2026, 9, 10), "COMPLAINT", "Kundklagomål: BV-Journalsystem",
        "Blåklintens Vård klagar på supportens svarstider (tredje klagomålet på samma tema 2026).",
        ["CUS-007"], ["DOC-MAIL-014"], note="GQ-046.")
    add("EVT-068", D(2026, 9, 15), "DECISION", "Uppsägning av BV-avtalet övervägs",
        "Ledningen överväger att säga upp BV-Journalsystem-avtalet senast 2026-09-30 (3 mån uppsägning) för omförhandling av pris och supportnivå. Beslut skjuts till nästa ledningsmöte.",
        ["CUS-007"], ["DOC-MGMT-010"], note="GQ-091, GQ-047.")
    add("EVT-069", D(2026, 9, 28), "BOARD", "Styrelsemöte (sep)",
        "Styrelsemöte inför bokslut FY26. Utdelningsfrågan bordläggs till årsstämman. Styrelsen kräver riskrapport med källhänvisningar till nästa möte.",
        ["P-038", "P-039", "P-001", "P-002", "P-003"], ["DOC-BOARD-008"], note="GQ-145, GQ-150, GQ-199.")
    add("EVT-070", D(2026, 9, 30), "PERIOD", "Bokslut FY2026",
        "Räkenskapsåret 2025-10-01–2026-09-30 avslutas. Analysdatum 2026-10-18.",
        ["P-003", "P-040"], ["DOC-FIN-002"], ["E-2026-090"])
    return e
