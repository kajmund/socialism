# Spec: Operations document generation (docs-operations)

## Goal
Generate ~110 realistic Swedish business documents across company/, management/,
correspondence/, policies/, projects/, employees/, customers/, suppliers/, plus
register `generator/data/operations_manifest.json`.

## Environment
Run from `/Users/erikfremred/socialism/synthetic_sme` with
`/Users/erikfremred/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3`.
Use `generator/docgen/common.py` for DOCX. Read `generator/data/facts.json`
(all entities/events) and `ground_truth/truth_model.json` (Model().load()).
Write your code in `generator/docgen/operations.py` (deterministic; util.rng()).

## Mandatory documents (referenced by story events – ids must match)
These doc_ids are referenced in the events list (facts.json). Create them with
matching content/date:
- DOC-BOARD-001..008: styrelseprotokoll 2024-11-21, 2025-02-10, 2025-05-19,
  2025-09-25, 2025-11-24, 2026-03-12, 2026-05-25, 2026-09-28 (per event dates).
  Include: beslutslistor (some NOT yet genomförda – fodder for GQ-148/GQ-081),
  the covenant discussion (EVT-030), utdelningsfrågan bordlagd (2026-09-28),
  riskkrav med källhänvisningar (EVT-069).
- DOC-MGMT-001..010: ledningsgruppsprotokoll (dates per events, monthly-ish).
  DOC-MGMT-008 must decide the AI-initiativ + AI-policy. DOC-MGMT-010 must contain
  the BV-uppsägning discussion (deadline 2026-09-30, decision postponed).
- DOC-MAIL-001..014: e-posttrådar per events (use .eml format: From/To/Date/
  Subject headers + body). Plus ≥12 additional threads: bank correspondence
  (covenants), inkassokrav (Blåklintens Vård), KF-fakturafel intern tråd,
  SEAB tilläggsförhandling, klagomålssvar, offertuppföljning.
- DOC-HR-001..015: HR-dokument per leave/raise events (avslutssamtal, uppsägningar).
- DOC-BUDG-001: FY26-budget (beslutad 2025-09-25) – monthly revenue/cost targets.
  IMPORTANT: budgeted FY26 revenue must total ≈ 50.2 MSEK net (2.0 MSEK above the
  actual 54.3? NO – set budget 50.2 MSEK: they planned less than actual because
  they did not expect the SEAB scale-up) – wait: make budget revenue ≈ 49.0 MSEK
  net and budgeted costs so EBIT target ≈ 7 % per EVT-031. Keep monthly rows
  plausible vs actuals (facts.json key_figures).
- DOC-BUDG-002: reviderad helårsprognos FY26 (2026-06-01): bas-scenario ≈
  52.5 MSEK net revenue, worst ≈ 48.5, best ≈ 55.0; EBIT-marginal 9–12 %.
- DOC-BANK-001/002: bankmötesprotokoll (2025-09-15 covenants; 2026-03-20 renewal).
- DOC-RISK-001: riskregister (top risks: kundkoncentration SEAB, nyckelpersoner
  [Daniel Nyström, Tomas Berg], avtalsrisker [obegränsat ansvar ÖH, vite SU],
  likviditet, IT-beroende Cloudserve, personalomsättning). ≥3 risks WITHOUT owner
  or action (GQ-183). Some claims stale vs newer data (GQ-188) – e.g. a risk
  marked "åtgärdad" that is NOT per newer docs, and one claim contradicted by the
  actuals (e.g. "ingen förfallen kundfordran").
- DOC-SEC-001: incidentrapport phishing 2024-10-15.
- DOC-IT-001: integrationshaveri lönesystem (2026-04-20, tredje gången).
- DOC-IT-002: driftstörning Nordhost (2026-08-04).
- DOC-IT-003: AI-svar utan källstöd (2026-09-02).
- DOC-POL-004: AI-policy (beslutad 2026-01-30).
- DOC-FIN-001/002: bokslutskommunikéer FY25/FY26 (use key_figures from facts.json).

## Additional required documents (question coverage)
- company/: bolagsordning, registreringsbevis, aktiebok (ägare per facts), 
  ägardirektiv, VD-instruktion (beslutsgränser SEK), attestordning (attestanter,
  beloppsgränser – fodder GQ-167), organisationsschema.
- management/: affärsplan 2026–2028 (strategiska mål ×3 with KPIs, ägare),
  KPI-rapport (månad), likviditetsprognos Q4, investeringskalkyl kontor Göteborg
  (DOC: kalkyl with 1.6 MSEK capex/år, break-even månad 9), bilkalkyl lease vs
  köp (två offerter), produktutvecklings-case (2.4 MSEK budget), värderingsmemo
  (DCF + multipel, antaganden explicit).
- correspondence/: kunddialoger (klagomål CUS-007 svarstider ×3 – GQ-046),
  förlorad affär Mossbackens (pris), konkurrentbevakning note.
- policies/: GDPR/personuppgiftspolicy (laglig grund, gallringsfrister),
  IT-säkerhetspolicy, sekretesspolicy (med 2023-02-15-mallen), resepolicy,
  arbetsmiljöpolicy, molntjänstpolicy (tredjelandsöverföring SUP-013!),
  behörighetspolicy.
- projects/: projektstatusrapporter (SE-Billing ×4 inkl. försening + tilläggsavtal;
  TS-Produktionsportal ×2 med viteförhandling; SU-Produktionssystem ×2;
  GV-Digitalisering ×1), projektmötesprotokoll ×5 (återkommande hinder: 
  "väntar på kundgodkännande", "kompetensbrist", "integrationer går sönder"),
  SE-Billing slutrapport 2026-07-15.
- employees/: medarbetarundersökning 2025 (resultat + öppna åtgärder – some still
  open 2026 – GQ-074) och 2026, utvecklingssamtalsregister (some employees last
  talk >12 months ago – GQ-073), sjukfrånvarorapport 2025 vs 2026 – TWO versions
  with a small inconsistency (GQ-078 CONFLICTING: Q1-2026 siffran skiljer),
  kompetensmatris (ensamkompetenser: Daniel data/AI, Tomas arkitektur, Maria
  testledning – GQ-070), rekryteringsärenden ×3 (kravprofiler + kandidatpoäng –
  GQ-068), utbildningsplan 2026, SAM-riskbedömning arbetsmiljö.
- customers/: CRM-export.csv (≥55 opportunities 2024-2026: stages, amounts,
  probability, owner, dates, win/loss; won → map to real contracts in model;
  total open pipeline ≈ 12–14 MSEK at 2026-10-18; ≥3 opportunities "stuck" 30+
  days; win-rate: small deals ~45 %, large ~25 %), offerter ×12 DOCX (3 expiring
  soon – GQ-036), förlorade-affärer register (orsaker), kundmötesanteckningar ×6
  (varför kunder väljer oss: fåtal citat only – GQ-050 must stay INSUFFICIENT),
  klagomålsregister, kundsegmentering (OFFENTLIG/ENTERPRISE/SMB).
- suppliers/: leverantörsbedömningar ×8 (säkerhetsgranskning; SUP-013 US-transfer,
  SUP-003 reverse charge; en leverantör saknar bedömning – GQ-168), inköpsregister
  CSV (leverantör, kategori, månadsbelopp – top-5 suppliers must match streams),
  systemförteckning (kritikalitet, ägare, reservrutin – vissa saknar reservrutin
  GQ-171), licensutnyttjande-rapport (Designsuiten 9/18, Datainsikt 2/10 –
  GQ-018), molnkostnadsrapport (månadsvis per tjänst – GQ-177), integrationslogg
  (frekventa fel lönesystem – GQ-172), behörighetsmatris (≥2 användare med för
  mycket behörighet – GQ-173), säkerhetsincidentlogg, DR/BCP-plan (RTO 48h, RPO
  24h – GQ-179), försäkringsbrev (ansvar 10 MSEK tak, egendom 5 MSEK; ingen
  cyber-/avbrottsförsäkring – GQ-185), reservrutinsförteckning.

## Manifest
`generator/data/operations_manifest.json`: entries
{"doc_id": "DOC-xxx", "path": "management/....docx", "dtype": "PROTOKOLL|MAIL|RAPPORT|
POLICY|BUDGET|CRM|OFFERT|REGISTER|...", "title", "created", "author_id" (person id
from facts), "entities": [...], "version", "valid_from", "valid_to",
"event_ids": [...], "supersedes": null, "note"}.
For CSV exports dtype=REGISTER. All doc_ids unique; reuse the story-referenced
ids listed above where given.

## Rules
- Truth model is READ-ONLY. Write only into the folders listed + your manifest +
  generator/docgen/operations.py.
- Numbers must match facts.json key_figures and the model registers; invent
  plausible-but-consistent details only where the model is silent.
- Realistic imperfection: keep dates/typos natural; do not add answer markings.
- Report back: file count by folder, any story-referenced doc you skipped and why.
