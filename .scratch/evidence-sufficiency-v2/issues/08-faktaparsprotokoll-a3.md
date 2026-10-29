# Jev-protokoll och SWE-form för faktapar (A3)

Type: grilling
Status: resolved
Blocked by: 06, 07

## Question

Exakt hur ska ett faktapar bedömas av Jev, och hur ska subworkflowet se ut i
SWE?

Beslut som ticketen ska låsa:

- Frågeschema per faktapar. Minst fyra utfall: faktisk motsägelse, förenliga,
  skillnad i tid/omfattning/kontext, otillräcklig information. Använd befintlig
  NOUL/choice-infrastruktur; ange frågetext, kriterier och deterministiska
  trösklar.
- Båda påståendena ska ingå med relevant kontext i varje anrop. Vad är minsta
  kontextfönster, och vad händer när paret inte ryms? Markera obehandlat, kapa
  aldrig tyst.
- En konflikt får inte avgöras enbart av låg modellsäkerhet. Vilken
  konfidensregel gäller, och vad blir utfallet vid låg konfidens?
- Aggregering: hur blir parutfall till konfliktposter, och hur påverkar de
  gate/route givet A2-kontraktet?
- SWE-form: noder, map/parallelism, concurrency, timeout, anropsbudget,
  felhantering. Ingen ny Python-loop får ersätta SWE:s orkestrering.
- Placering: ska subworkflowet ligga i `sufficiency_experiment`, eller lyftas
  som en återanvändbar research-modul? Inventeringen visar att parformen bara
  finns i labbkoden (`tests/research_reuse`), så detta är ett nytt beslut — men
  det får inte bli en ny motor eller ett parallellt researchflöde.
- Konfliktpost: A2 har låst `ConflictRecord` (status, sides, resolution,
  flagged_by) och kopplingspunkten `PassageEvaluation.counterpart_passage_ids`.
  A3 ska fylla i motparten och kan sätta `flagged_by="jev_fact_pair"`. Besluta
  bara det som återstår (aggregering av parutfall, metadata för reglerna) —
  ingen ny konkurrerande posttyp.
- Indata: valda par från `pairs.py` (ticket 07), dvs. `PairSelection.selected`
  per strategi. Valda par = Jev-anropsbudgeten; antalet ska redovisas före
  körning. Facit för precision/recall är `pair-gold-v1.json`
  (`contradiction_pairs`); `candidate_pairs` styr recall.
- Provenance: vilka anrop, passager, par och utfall ska kunna spåras i
  artefakten.
- Modellberoende: den enda live-mätta parformen (16/16) kördes med
  `openjev-0.1`, medan sufficiency-spåret använder `jev-1.13.0`. A3 måste mäta
  om på den konfiguration huvudjämförelsen använder; ärva inte 16/16 som bevis.

Leverans: Jev-protokoll + SWE-kontrakt + acceptansfall, redo att implementeras.

## Answer

**Beslut 2026-10-22 (grilling med användaren), med tre preciseringar.**
Implementerat i commit `b6d4a196` på `feat/sufficiency-a3-claims`. Live-mätt
med `jev-1.14.0` (resolved model), två repetitioner.

### Låst beslut

| Fråga | Beslut |
| --- | --- |
| Q1 Choice-schema | Fyra utfall; `INSUFFICIENT` skiljs från tekniska fel (`uncertain` vs `unevaluated`) |
| Q2 A2-konflikter | Endast `CONTRADICTS`/`SCOPE_DIFFERENCE` blir konfliktkandidater; `COMPATIBLE` aldrig; A2 avgör materialitet |
| Q3 SWE-integration | `prepare_pairs → pair_jobs (map) → aggregate_pairs` i huvudworkflowen |
| Q4 Kontext/budget | Båda claims + fulla passager + metadata; 6 000 tecken; ingen tyst trunkering |
| Q5 Parstrategier | `pair_strategy` default `deterministic`; A/B/C mäts separat |
| Q6 Live-mätning | Alla tre strategier jämförs; falska motsägelser och Jev-tid mäts |

### Preciseringar

1. Fyra utfall, men `INSUFFICIENT` = Jev bedömde båda påståendena men kan inte
   avgöra relationen (`uncertain`). Timeout, ogiltigt svar och över-budget =
   bedömningen genomfördes inte (`unevaluated`). Båda blockerar `sufficient` när
   paret är obligatoriskt och redovisas separat.
2. `SCOPE_DIFFERENCE` kräver verifierbar metadata för att bli `not_applicable`;
   annars blir den `unresolved` och går vidare till A2. `COMPATIBLE` skapar
   ingen konfliktpost. Jev får inte själv "verifiera" en omfångsskillnad.
3. Rapporten skiljer bedömt, osäkert, ej skickat (budget) och misslyckat anrop.
   Passager kapas aldrig för att rymmas; över-budget syns.

### Implementation

`pair_eval.py`: `PAIR_CONFLICT_QUESTIONS` (choice), `evaluate_pair`,
`evaluate_pairs`, `pair_coverage`, `merge_pair_conflicts`.
`PairEvaluation(pair_id, need_id, left/right_claim_id, verdict, status,
sources, state_chars, latency_ms, error, model)`.
`PairCoverage(total, judged, uncertain, unevaluated, complete, reasons)`.
Workflowen har nu `sufficiency.prepare_pairs`, `sufficiency.evaluate_pair`,
`sufficiency.aggregate_pairs`; ingen subworkflow-nod används (stöds inte).

Konfliktmappning: `CONTRADICTS` och `SCOPE_DIFFERENCE` prövas mot A2:s
metadata_resolution; verifierad temporal/entitet/definition → `not_applicable`,
`superseding` → `resolved`, annars `unresolved`. `INSUFFICIENT` → `unresolved`
med `flagged_by="jev_fact_pair"`. `COMPATIBLE` → ingen post. `unevaluated` →
`pair_coverage_incomplete` i gaten.

### Live-resultat (`pair-judgement-v1.json`, 2 repetitioner)

| Strategi | Recall | Precision | Falska motsägelser | Anrop | Unevaluated |
| --- | ---: | ---: | ---: | ---: | ---: |
| deterministic | 1.00 | 1.00 | 0 | 88 | 1 (timeout) |
| embeddings | 0.67 | 0.50 | 4 | 96 | 0 |
| hybrid | 1.00 | 0.67 | 4 | 96 | 0 |

- `compatible_periods`/`compatible_entities`: Jev svarade `SCOPE_DIFFERENCE` i
  alla körningar; A2:s metadata gjorde dem `not_applicable`. Inga falska
  motsägelser där.
- Tail-fallet: deterministic och hybrid hittade motsägelsen; embeddings-only
  missade den vid bedömningen.
- Embeddings/hybrid parade även `Avgörandet gäller ett annat avtal.` med
  stödclaimen; Jev kallade det `CONTRADICTS` → 4 falska motsägelser.
- En deterministic pair fick timeout i rep 0 och rapporterades `unevaluated`
  med ofullständig täckning — fail-closed, inte tyst bortfall.
- Wall time är Jev-bunden: ~650–750 ms för 4-anropsfall, 2 345 ms för
  tail-fallets 49 anrop (concurrency 8). Summad Jev-latens överstiger wall time
  eftersom anropen körs parallellt; `workflow_timing` i artefakten.

### Verifiering

`tests/test_sufficiency_experiment_pair_eval.py` (10 tester): över-budget utan
anrop, ogiltigt svar, timeout, `INSUFFICIENT` vs tekniskt fel, `COMPATIBLE` utan
konflikt, `SCOPE_DIFFERENCE` med/utan metadata, `CONTRADICTS` + verifierad
metadata, ofullständig täckning, samt workflowtest att `unevaluated` pair
blockerar `sufficient`. 83 sufficiency-tester gröna, ruff och maintainability
gröna.

### Kvar till nästa ticket

Live-mätningen är parnivå, inte hela A3-armens end-to-end-mätning. Arm-jämförelse
och kostnad per upptäckt motsägelse hör till mätprotokollet (ticket 10) och
Variant B (ticket 11).
