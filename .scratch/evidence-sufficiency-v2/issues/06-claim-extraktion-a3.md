# Claim-extraktion för A3

Type: grilling
Status: resolved
Blocked by: 01

## Question

Hur identifieras de faktapåståenden som A3 ska jämföra — och vad är en claims
identitet?

Beslut som ticketen ska låsa, med reuse-matrisen från inventeringen som grund:

- Metod: deterministisk sats-/klausuldelning, Jev-baserad extraktion,
  befintliga GraphFacts, eller en kombination där GraphFacts används när de
  finns och deterministisk split annars? Motivera mot kostnad, reproducerbarhet
  och "skapa inte en ny generell faktadatabas".
- Claim-schema: identitet, påståendets text, källa, dokumentversion,
  `ResearchNeed`/fråga, giltighetstid om känd, kontext som krävs för tolkning,
  samt koppling till passage/TextUnit.
- Vad händer när ett påstående inte kan extraheras säkert? Det ska registreras
  som osäkert, inte antas korrekt. Vilken status/provenance krävs?
- Hur undviks tyst bortfiltrering, och vilken budget gäller för extraktionen?
- Vilka claims är jämförbara: samma entitet/attribut/fråga? Definiera
  förväntade fält utan att bygga en generell ontologi.
- Claim-identitet vs fact-identitet: `knowledge_claim_identity`
  (påståendebaserad) och `source_fact_identity` (källankrad) är två olika
  begrepp; samma påstående från två källor blir en claim-nod men två
  faktanoder. Välj vilket som styr "jämförbara claims", och hur
  `valid_at`/`invalid_at`/kontext representeras (`KnowledgeClaim` saknar
  fälten, `GraphFactView` har dem).

Leverans: claim-modell + extraktionsmetod + osäkerhetshantering, redo att
användas av kandidatgenereringen.

## Answer

**Beslut 2026-10-22 (grilling med användaren), med tre preciseringar.**
Implementerat i commit `e8bfb860` på `feat/sufficiency-a3-claims`. Ingen DB,
inga modellbaserade fallbacks, ingen produktionskoppling.

### Låst beslut

| Fråga | Beslut |
| --- | --- |
| Q1 Identitet | Källankrad förekomst + separat kanonisk nyckel |
| Q2 Extraktion | Deterministisk kandidatdelning, inte semantisk faktatolkning |
| Q3 Osäkerhet | `extracted` / `uncertain` / `unprocessed`, med explicit täckningsredovisning |
| Q4 Schema | Godkänt med exakt offset-invariant |
| Q5 Budget | Explicita tak + redovisade obehandlade kandidater |

### Preciseringar

1. Delningen ger `claim_candidates`, inte atomära fakta. En mening med flera
   sammanhängande uppgifter förblir en kandidat; A3:s Jev-jämförelse avgör vad
   den påstår. `extraction_method="deterministic_segment"`.
2. Osäkerhet får inte bli osynlig: `uncertain` registreras med orsak
   (`too_short`, `question`, `too_long`, `citation_only`) och räknas i
   täckningen. Rena citat får inte slängas — bara kandidater som matchar en
   snäv citations-only-form blir `uncertain`. `unprocessed` betyder att budgeten
   hindrade behandling.
3. Invariant: `passage.text[start:end] == claim.text` för varje kandidat.
   `normalized_text`/`canonical_key` används bara för sökning/gruppering, aldrig
   för att ersätta text, slå ihop källförekomster eller påverka oberoende.
   `entity_id`, `valid_from`/`valid_to`, `definition_id` kopieras endast från
   verifierbar provenance — aldrig gissade från texten.

### Schema (`types.py`)

`ClaimCandidate(claim_id, evidence_id, source_id, passage_id, start, end, text,
normalized_text, canonical_key, research_need_ids, extraction_method,
extraction_status, uncertain_reason, entity_id, valid_from, valid_to,
definition_id, content_hash)`.
`ClaimCoverage(candidates, extracted, uncertain, unprocessed, per_evidence,
per_need, complete, reasons)`.

### Extraktion (`claims.py`)

Satsdelning med skyddsregel för juridiska förkortningar (`s.`, `nr.`, `kap.`,
`p.`, `mom.`, `st.`, `jfr.`, `dvs.`) så att `NJA 2005 s. 142.` inte klyvs.
Budget: `min_claim_chars=20`, `max_claim_chars=500`, `min_claim_words=4`,
`max_claims_per_need=200`. Taket är ett säkerhetstak: när det nås blir
återstående kandidater `unprocessed`, `complete=False`, gate får
`claim_coverage_incomplete` och `sufficient` blockeras.

### Täckning och TextUnit

`per_evidence` räknar kandidater per evidenspost (TextUnit-analogen i
experimentet), `per_need` räknar extraherade per behov. Okända/extraherade/
obehandlade kandidater redovisas separat — ingen tyst trunkering.

### Tester

`tests/test_sufficiency_experiment_claims.py` (11 tester): offset-invariant,
flerledad mening blir en kandidat, osäkerhetsorsaker, citerat avgörande blir
`extracted`, metadata endast från provenance, kanonisk nyckel grupperar utan att
slå ihop förekomster, budgettak → `unprocessed` + ofullständig täckning,
determinism, samt workflowtest att `claim_coverage_incomplete` blockerar
`sufficient`. 66 sufficiency-tester gröna, ruff och maintainability gröna.

### Vad som inte ingår

Ingen kandidatgenerering (ticket 07), ingen Jev-jämförelse (ticket 08), inga
live-anrop. `pair_over_budget`-fallets A3-beteende ligger kvar som definierad
förväntan.
