# Nya golden cases för A1–B

Type: grilling
Status: resolved
Blocked by: 03, 04

## Question

Vilka nya golden cases ska läggas till, med vilka labels och förväntade utfall
per arm — utan att de befintliga elva fallen ändras?

Befintliga fall ska återanvändas: `short_sufficient`, `tail_counterevidence`,
`late_evidence`, `large_567k`, `multi_obligation`, `missing_source_type`,
`unknown_requirements`, `duplicate_sources`, `later_wave_contradiction`,
`no_support`, `adversarial_empty`.

Nya riktade fall som specen kräver:

- Motsägelse med hög dubblettscore (A2 får inte lösa den).
- Motsägelse mellan två oberoende källor (A3 ska hitta den).
- Förenliga fakta med olika tidsperioder (A2/A3 får inte kalla det motsägelse).
- Förenliga fakta från olika avtal (får inte blandas ihop).
- Saknat eller ogiltigt Jev-routingbeslut (A1 fail-closed).
- Faktapar som inte ryms inom kontextbudgeten (A3 ska markera obehandlat).

Beslut: exakta payloads eller payload-generatorer, källordning, labels
(ground truth för varje arm), förväntad draft/status per arm, vilka fall som är
scripted-only respektive kräver live-repetition, och varför varje fall finns.
Återanvänd de tre märkta kontrollparen från labbkoden
(`tests/research_reuse/jev_window_controls.py`: `matching-dates`,
`historical-change`, `different-contracts`) som grund för de förenliga fallen.
Notera att den scriptade Jev:en aldrig kan producera duplicate > 0,05
(`scripted.py:66`), så duplicate-regeln kan inte prövas i CI utan ny scriptad
förmåga.
Statiska fall-dimensioner ska skiljas från modellmätningar.

Leverans: en case-tabell + fixture-krav som kan implementeras och användas av
mätprotokollet. Inga nya modeller används för att sätta labels.

## Answer

**Beslut 2026-10-22 (grilling med användaren).** Q1–Q5 låsta; fixtures och
test-seams implementerade i commit `ff52d1d7` på
`feat/sufficiency-conflict-cases`. Ticketen stängs först när fixtures, seams och
workflowtester är färdiga — de är det nu.

### Låst testmatris

| Golden case | A2 | A3 |
| --- | --- | --- |
| `duplicate_contradiction` | Unresolved | Unresolved |
| `independent_contradiction` | Unresolved | Identifierat konfliktpar |
| `compatible_periods` | Not applicable med bevis | Samma |
| `compatible_entities` | Not applicable med bevis | Samma |
| `unknown_counterpart` | Unresolved | Ingen påhittad motpart |
| `pair_over_budget` | Ej tillämpligt | Unevaluated, fail-closed när paret är obligatoriskt |

### Tre låsta detaljer

1. `compatible_*` får endast bli `not_applicable` när tid/entitet kan verifieras
   från faktisk provenance. Saknad eller motsägelsefull metadata → `unresolved`.
   Fixturen har positiva och negativa exempel (saknad metadata, överlappande
   perioder, samma entitet).
2. `unknown_counterpart` får aldrig hitta på en motpart. Testet verifierar att
   `sides` bara innehåller kända evidence-id:n, att `has_unknown_counterpart` är
   sann och att `unresolved → gate FAIL → draft insufficient`.
3. `pair_over_budget` har säkerhetsbeteendet dokumenterat:
   `unevaluated → never sufficient solely on that unverified pair`. Fallet ligger
   i `all_golden_cases()` men utanför A2/A3-mätseten tills A3 finns.

### Fixtures och seams

- Nya fall i `golden.py` med unika evidence-id:n: `dup-support`/`dup-contra`,
  `ind-support`/`ind-contra`, `period-old`/`period-new`,
  `entity-a`/`entity-b`, `unknown-contra`, `budget-left`/`budget-right`.
- `conflict_benchmark_cases()` = fem utvärderbara fall (utan
  `pair_over_budget`). `scripted_benchmark_cases()` är fortsatt de fyra A0-fallen.
  `all_golden_cases()` = 17 unika fall.
- Seam 1: `SCRIPTED_SCORE_OVERRIDES` i `scripted.py` per evidence-id (t.ex.
  `dup-contra` duplicate 0.89). Test-double, aldrig modellkvalitet.
- Seam 2: valfri `counterparts`-mappning `run_experiment → evaluation_jobs →
  PassageEvaluation.counterpart_passage_ids`. A3 ersätter den med riktig
  detektion.
- Båda seams är strikt experimentella; ingen produktionsmodul importerar dem.

### Verifiering

`tests/test_sufficiency_experiment_conflict_cases.py` kör hela SWE-workflowen:
matrisen, negativa metadatafall, okänd motpart, separata benchmark-set och att
scripted-overrides är fixture-data. 55 sufficiency-tester gröna, ruff och
maintainability gröna. A0:s fyra fall är oförändrade.

### Live

Inga live-anrop i denna ticket. Live-mätningen skjuts till A3 och följer ticket
08:s slutliga protokoll.
