# Täckningsmätning på fem nivåer

Type: grilling
Status: resolved
Blocked by: 06, 07

## Question

Hur mäts och redovisas de fem täckningsnivåerna utan att 100 % passage-coverage
förväxlas med semantisk täckning?

Nivåer som ska definieras med formel, datakälla och artefaktfält:

1. **Ingestion coverage** — vad som finns tillgängligt.
2. **Passage coverage** — vad Jev faktiskt bedömt.
3. **Claim coverage** — vilka faktapåståenden som identifierats.
4. **Conflict candidate coverage** — vilka potentiella motsägelser som prövats.
5. **Narrative coverage** — vilket material den narrativa modellen sett (i B).

Beslut: nämnare och täljare för varje nivå, hur budgetavbrott och
"obehandlade par" räknas, hur missade kandidatpar kan upptäckas i
kontrollunderlaget, och vilka påståenden som aldrig får göras ("hela
EvidenceSet är konfliktfritt"). Ingen tyst trunkering eller tyst
bortfiltrering får döljas i siffrorna.

Leverans: metric-definitioner + artefaktfält + regler för hur osäkerhet
propageras till status, redo för mätprotokollet.

## Answer

**Beslut 2026-10-23 (grilling med användaren).** Implementerat i commit
`6b739e28` på `feat/sufficiency-a3-claims`. Fem nivåer, ingen sammanslagen
procentsiffra.

### Låsta beslut

| Fråga | Beslut |
| --- | --- |
| Gating | Processnivåer gatar; conflict-facit gatar endast när facit är bundet; narrative `not_applicable` före B |
| Conflict control | Process + facit; utan facit `not_measured`, aldrig `complete` |
| Ingestion | Provided EvidenceSet; upstream `not_measured`; found utan excerpt → incomplete |
| Claim | Endast `unprocessed` → incomplete; `uncertain` redovisas separat |
| Facit-binding | `bind_pair_facit()` på `SufficiencyLoop`, experiment-only; påverkar gaten i benchmark |
| Narrative | `not_applicable` före Variant B |

### Nivåer och kontroller

| Nivå | Kontroll | `complete` kräver |
| --- | --- | --- |
| `ingestion` | provided EvidenceSet | inga `found` utan excerpt |
| `passage` | character cover | judged chars == source chars |
| `claim` | candidate status | inga `unprocessed` |
| `conflict_candidate` | process (+ facit) | inga omissions/unevaluated; med facit även inga missade facitpar |
| `narrative` | none | `not_applicable` före B |

`CoverageLevel(level, status, control, counts, reasons, note, gate_complete)`;
`CoverageReport(levels)` har `gate_complete` och `level(name)` — ingen
`score`/procent. `GateInputs.coverage_incomplete` ger reason
`coverage_incomplete`.

### Fynd från artefakten

`pair-judgement-v1.json` (workflow timing, facit bundet): på
`tail_claim_contradiction` bedömdes facitparet (`facit_missing=0`) men **15 717
kandidatpar** föll på 40-parsbudgeten → `conflict_candidate=incomplete`
(`pair_budget_omitted`) och `coverage_incomplete` blockerar `sufficient`. På de
små fallen är nivån `complete` med facit. Det är avsiktligt fail-closed: ett
stort underlag får inte påstås vara täckt bara för att alla genererade jobb
avslutades.

### Verifiering

`tests/test_sufficiency_experiment_coverage.py` (7 tester): fem nivåer utan
samlad siffra, ingestion vid tom excerpt, claim-trunkering, conflict
`not_measured` utan facit men gate-ok, pair-budget utan facit → incomplete,
missat facitpar → blockerar `sufficient`, hittat facitpar → complete. 90
sufficiency-tester gröna, ruff och maintainability gröna.

### Konsekvens för nästa steg

- Deterministisk parstrategi är fortsatt experimentets default men **inte låst
  som generell vinnare**; det svårare semantiska tail-fallet saknas och en
  timeout observerades.
- Med 40-parsbudget blir conflict-coverage incomplete på stora underlag. Om
  det ska vara acceptabelt, eller om budgethanteringen ska ändras, hör till
  mätprotokollet (ticket 10) — inte till denna ticket.
- Narrative-nivån mäts först i Variant B (ticket 11).
