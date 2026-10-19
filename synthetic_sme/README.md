# SPEC – Synthetic SME Benchmark v1.0

**Nordviken Digital AB** – ett komplett syntetiskt svenskt IT- och konsultbolag för
objektiv testning av **Socialism**: dokumentingest, retrieval, flerstegsresonemang,
ekonomiska beräkningar, avtalsanalys, källhänvisning och svarstid/kostnad.

> **Fiktionsdeklaration:** Alla företag, organisationsnummer, personer, e-postadresser,
> telefonnummer, adresser och händelser i detta dataset är fiktiva och genererade för
> benchmarkändamål. Likheter med verkliga bolag eller personer är oavsiktliga. Inga
> verkliga personnummer förekommer. Bank, försäkringsbolag och banker är fiktiva.

## 1. Analysram

| Egenskap | Värde |
|---|---|
| Analysdatum | 2026-10-18 |
| Historik | 2024-10-01 – 2026-09-30 (24 månader) |
| Räkenskapsår | **Brutet räkenskapsår**: FY2025 = 2024-10-01–2025-09-30, FY2026 = 2025-10-01–2026-09-30 (används konsekvent i bokföring, SIE, rapporter och facit) |
| Primär analysperiod | FY2026 (senaste 12 månaderna) |
| Valuta | SEK |
| Bokföringsmodell | Dubbel bokföring, BAS-inspirerad kontoplan |
| Export | SIE4 (Utgåva 4C, #FORMAT PC8/CP437), 2 filer (ett per räkenskapsår) |
| Anställda | 25 vid analysperiodens slut (37 personer totalt i historiken, 12 avgångar, 8 nyanställningar) |
| Kunder | 50 (45 aktiva, 2 lämnade, 1 i konkurs) |
| Leverantörer | 40 |
| Projekt | 32 (inkl. 2 interna) |
| Avtal | ≥200 (ram-, projekt-, konsult-, leverantörs-, anställnings-, NDA-, DPA-, SaaS-, hyres-, leasing- och aktieägaravtal) |
| Kundfakturor | 889 (inkl. kreditnota) |
| Leverantörsfakturor | 867 |

## 2. Bolaget i korthet (översikt för tolkningsram)

Nordviken Digital AB (org.nr 559245-1673, Stockholm) grundades 2018 och levererar
IT-konsulttjänster, systemutveckling, molnmigrering och förvaltning. Ägare: Maja
Lindqvist (VD, 42 %), Jonas Sandberg (CTO, 28 %), Anders Bergström (CFO, 12 %),
Sara Holm (8 %), Erik Norén (5 %), övriga 5 %.

- **Största kund:** Skogsbygdens Energi AB (SEAB) ≈ 34 % av FY26-omsättningen
  (SE-Billing, SE-Integration, SE-Förvaltning).
- **Ekonomi:** FY2025: omsättning ≈ 42,6 MSEK, resultat −270 tkr (svagt år,
  likviditetsansträngning, checkkredit som mest utnyttjad med 1,18 MSEK i mars 2025).
  FY2026: omsättning ≈ 54,3 MSEK, resultat ≈ +6,3 MSEK. Banklånet slutamorterat
  under FY26. Bolagsskatt FY26 ≈ 2,1 MSEK (varav ≈ 1,5 MSEK obetald vid analysdatum).
- **Kända verksamhetsproblem (avsiktliga, ekonomiskt avstämda):**
  1. *Underdebitering:* KF-Biljettsystem (Kustbandets Färjor) – avtalad indexhöjning
     1 050→1 150 kr/h fr.o.m. 2025-11-01 debiterades först fr.o.m. 2026-02;
     eftersläpningsfaktura 53 730 kr ex moms utfärdad 2026-02-28.
  2. *Missad indexuppräkning:* Gråvikens kommun (per 2025-10-01, korrekt pris
     1 075 kr/h) och Blåklintens Vård (per 2026-04-01, korrekt pris 1 009 kr/h)
     har aldrig indexreglerats i faktureringen.
  3. *Försenat projekt:* TS-Produktionsportal (Timmervikens Såg) 8 veckor försenad;
     förlikning via kreditnota 90 000 kr inkl. moms (2026-06-30).
  4. *Kundförlust:* Sjöstadens Bryggeri i konkurs 2025-12-08; september- och
     novemberfakturorna (totalt 220 065,00 kr inkl. moms) avskrivna 2025-12-31
     (september hölls inne p.g.a. reklamation; oktober betalades sent).
  5. *Tvistig fordran:* Örby Handel & Logistik håller inne 96 800 kr (slutfaktura).
  6. *Personalomsättning:* 12 avgångar på 24 månader (inkl. en avskedad med
     förlikning om 141 000 kr, två rekryterade av kund/underkonsult).
  7. *Avtalsrisker:* ett avtal med obegränsat ansvar, ett med 24 månaders
     funktionsgaranti, viteklausuler, två exklusivitetsklausuler och
     change-of-control-klausuler.
  8. *Likviditet:* checkkredit 3,0 MSEK, som mest utnyttjad 1,18 MSEK (mars 2025);
     banken krävde covenants (soliditet ≥ 25 %, EBITDA > 0 rullande 12 mån) 2025-09.
  9. *Fakturering efter periodens slut:* FS-Intranäts slutfaktura (375 000 kr inkl.
     moms) fakturerades 2025-10-10 och periodiserades korrekt vid bokslutet.

## 3. Mappstruktur

```
synthetic_sme/
  README.md, manifest.json
  company/            registreringsbevis, bolagsordning, aktiebok, instruktioner
  accounting/         sie4/, general_ledger/, accounts_receivable/,
                      accounts_payable/, banking/, payroll/, tax/, financial_reports/
  contracts/          customers/, suppliers/, employees/, corporate/ (DOCX)
  invoices/           outgoing/ (per år), incoming/ (per år) (DOCX)
  projects/           projektstatus, tidrapporter, mötesprotokoll
  employees/          HR-dokument, undersökningar, rekrytering
  customers/          CRM-export, offerter, kundmöten, klagomål
  suppliers/          leverantörsbedömningar, inköpsregister, IT- och säkerhetsunderlag
  management/         styrelse- och ledningsprotokoll, budget, prognos, affärsplan
  correspondence/     e-post (.eml) och brev
  policies/           GDPR, IT-säkerhet, AI, rese-, arbetsmiljö- m.fl. policyer
  golden_questions/   golden_questions.json (200 frågor, ID + originalformulering)
  ground_truth/       truth_model.json, facit.json, coverage_matrix.json,
                      provenance.json (ENDAST i ground-truth-paketet)
  validation/         validation_report.json/.md (16 kontroller)
  generator/          all genereringskod, konfiguration, seed, data, validators
```

## 4. De tre paketen

| Paket | Innehåll | Exkluderar |
|---|---|---|
| `socialism_ingest.zip` | Dokument + data som Socialism får läsa: bokföring (SIE4, huvudbok, reskontra, bank, lön, moms, rapporter), avtal, fakturor, verksamhetsdokument, golden questions (utan klassificering) | Facit, sanningsmodell, proveniens, valideringsrapport, generatorkod |
| `socialism_ground_truth.zip` | `truth_model.json`, `facit.json` (200 poster med metod, källpositioner, toleranser), `coverage_matrix.json`, `provenance.json`, facts, manifests, valideringsrapport | – |
| `socialism_generator.zip` | Hela `generator/`: kod, `config.py` (seed 20261018), scheman, golden-questions-källa, validatorer | Genererade dokument/PDF:er |

## 5. Reproducerbarhet

- Fast seed **20261018**; alla slumptal via `generator.util.rng()` (hash-deriverade strömmar).
- Inga väggklockstämplar i innehåll. Alla ID:n och nummerserier är deterministiska.
- Kör: `python -m generator.generate && python -m generator.facts && python -m generator.validate && python -m generator.package`
  (bundled Python: `/Users/erikfremred/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3`, från `synthetic_sme/`).
- PDF:er renderas från DOCX via LibreOffice i efterhand och är inte hash-stabila
  (manifestet hash-verifierar DOCX-källorna; PDF:erna noteras som renderade artefakter).

## 6. Golden Questions och facit

- 200 frågor (GQ-001..GQ-200) från källfilen `socialism_200_golden_questions_v1.xlsx`
  (ID och originalformulering bevarade), fördelade på Ekonomi, Marknad, Personal,
  Juridik, Strategi, Verksamhet (30 var), Risk (10) och VD-beslut (10).
- Klassificering (i ground truth): **ANSWERABLE** 153 · **PARTIALLY_ANSWERABLE** 18 ·
  **INSUFFICIENT_EVIDENCE** 8 · **CONFLICTING_EVIDENCE** 6 · **EXTERNAL_DEPENDENCY** 15.
- Facit per fråga: förväntat svar, beräkningsmetod, krävd information, källdokument
  med positioner, giltighetstider, toleranser och bedömningskriterier.
- ≥60 av frågorna kräver två eller fler oberoende källor.

## 7. Dokumenterade antaganden och avvikelser

1. *Golden Questions-källfilen* bifogades av uppdragsgivaren och har lästs in
   maskinellt (`generator/data/golden_questions_raw.json`); ID och formuleringar
   är oförändrade.
2. *KPI-indexserien* är en fast, kalibrerad snapshot (SCB-nivå) med hämtningstid
   2026-10-18 – extern referensuppsättning sparad i `generator/config.py`
   (ersätt med SCB:s officiella serie före ett externt benchmarkkörning om så krävs).
3. *Personnummer* utelämnas helt i dokumenten (endast födelsedatum används) för att
   aldrig riskera kollision med verkliga individuppgifter.
4. Semesterlöner för perioden före 2024-10 är skattade från lönenivån 2024-10
   (dokumenterat antagande i sanningsmodellen).
5. *Räkenskapsåren är brutna* (okt–sep) – se §1; indelningen används konsekvent.
6. *SIE-validering mot SIE-gruppens testtjänst* (sietest.sie.se) kräver webbläsaruppladdning;
   den lokala valideringen är en strikt spec-baserad återläsningskontroll (kontroll 16).
   Extern uppladdning rapporteras som NOT_TESTED i valideringsrapporten.
7. Momsavdrag/återvinning vid kundförlusten (220 065,00 kr) har inte gjorts –
   bokförd som kostnad i sin helhet (dokumenterat, realistiskt för SME).
8. Avsiktliga affärsavvikelser (§2.4) är ekonomiskt avstämda i sanningsmodellen och
   ska inte förväxlas med genereringsfel; tekniska fel elimineras av valideringen.

## 8. Validering

`python -m generator.validate` kör 16 kontroller (verifikationsbalans, IB/UB,
balansräkning, kund-/leverantörsreskontra, bankavstämning, fakturareferenser,
avtalspriser, löner, projektkoppling, dokumentreferenser, 200 frågor, facittäckning,
klassificering, facitläckage, SIE-roundtrip). Rapport: `validation/validation_report.json`.
Inga tysta fel: kontroller som inte kan köras rapporteras som NOT_TESTED med orsak.
