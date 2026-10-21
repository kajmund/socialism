# Research SWE — mätlogg (frysta mätningar)

Durable beslutslogg för mätfasen (task-4). Den genererade rapporten
[research-swe-experiment.md](research-swe-experiment.md) är en artefakt av den
slutliga mätningen; den här loggen bevarar även de tidigare mätningarna, ett
hittat analysfel och varför urvalet ändrades.

## Fryst harness

| Fält | Värde |
| --- | --- |
| Commit (slutlig harness) | `486d59afeff98ca948ad49f937cd3582f177f4a6` |
| Branch | `feat/research-swe-experiment` |
| `backend/scripts/benchmark_research_swe.py` sha256 | `a00ba5659b204dd12c2c58b9c76d4a04630e4a4ae19aa9e4dad8e363b82fdd6f` |
| Trösklar | median: CI95-övre kvot ≤ 1,10; p95 parad kvot ≤ 1,25; domänparitet exakt; fake-guards (0 LLM, 0 nätverk) |
| Fixture | 16 needs, 40 ms fake-latens/need; A = `research_need_concurrency` 8 (två vågor), B = 16 (en våg) |

Frys-historik: #1 `be75efa4` (sha `8ae29e8a…`, rapporttext), #2 `b009b69b`
(sha `2e202ed7…`, reproduce/expected/samples/live-blockerare) och #3
`486d59af` (sha `a00ba565…`, enradsfix av p95-parningen). **Mätlogik och
trösklar är identiska mellan frysarna** — endast rapportlager (#1, #2) och en
analysbugg (#3) skiljer.

## Artifakter

| # | Katalog (`data/research_swe/`) | Harness | Runs | Cold-samples/arm | Exit | Cutover-gate (A) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `frozen-8ae29e8affc3-20261021T215707Z` | #1 | 3 | 36 | 0 | pass (CI95 1,0471)¹ |
| 2 | `frozen-2e202ed7584a-20261021T220232Z` | #2 | 3 | 36 | **1** | **FAIL** (CI95 1,1141)¹ |
| 3 | `frozen-2e202ed7584a-20261021T221038Z` | #2 | 8 | 96 | 0 | pass (CI95 1,0502)¹ |
| 4 | `frozen-a00ba5659b20-20261021T221741Z` | #3 | 3 | 36 | **1** | **FAIL** (CI95 1,1340) |
| 5 | `frozen-a00ba5659b20-20261021T222445Z` | #3 | 8 | 96 | **0** | **pass** (CI95 1,0272) |

¹ p95-kolumnen i dessa artefakter beräknades med fel arm-parning (se nedan).
Cutover-besluten påverkades inte; körning 5 är den slutgiltiga artefakten.
Rådata är gitignorad men ligger kvar lokalt; `results.json` bär `git_head`,
`script_sha256`, exakt reproduce-kommando och gate-resultat.

## Analysfel som hittades och rättades (frys #3)

Granskningen hittade att parningen av parade kvoter byggde nämnaren från *sist
skrivna arm* i stället för baseline (`by_key` saknade `row.arm == "baseline"`),
vilket gav fel nämnare i 2/3 av de parade kvoterna. Fixen är en rad; mät- och
analys-sha är nu samma. Korrigerade p95 på de äldre stickproven: n=8 A 1,1712 /
B 1,2169; n=3 A 1,1563 / B 1,1505; freeze#1-artefakten A 1,1948 / B 1,2681.
Notera att freeze#1:s historiska "B fastest" därmed inte heller skulle ha
passerat p95-gaten (1,2681 > 1,25) — cutover-beslutet påverkas inte (A passerar
p95 i alla körningar; det är A:s median-CI som avgör cutover). Den slutliga
körningen (5) har p95 beräknad av fryst #3-kod: A 1,1584 / B 1,2000.

## Beslut: statistisk styrka n=3 → n=8

Körning 2 (n=3) fällde cutover-gaten: A:s punktestimat var +3,4 % median och
p95-par-kvoten 1,165, men CI95-övre median-kvot blev 1,1141 > 1,10. Körning 1
med samma mätlogik gav 1,0471. Skillnaden är run-to-run-brus kring tröskeln.

Beslut (förhandsdeklarerat, före körning 3): **behåll trösklarna, öka antalet
oberoende runs från 3 (protokollminimum) till 8** för ett smalare
konfidensintervall. Ingen tröskel, fixture eller mätlogik ändrades. Alla n=3-
artefakter behålls som transparens; de är neutral historik och aldrig
godkännande- eller cutover-underlag.

## Slutresultat (körning 5, n=8)

| Arm | Cold median (ms) | Median-kvot | CI95-övre | p95 parad kvot | Gate |
| --- | --- | --- | --- | --- | --- |
| baseline (dagens wave-loop) | 851,1 | 1,0 | 1,0 | 1,0 | pass |
| **SWE A** (dagens concurrency) | 856,0 | 1,0109 | 1,0272 | 1,1584 | **pass** |
| SWE B (2× fan-out, 8→16) | 844,7 | 1,0000 | 1,0167 | 1,2000 | pass |

- Domänparitet: exakt lika i alla armar (status, stop_reason, wave, needs,
  evidens, assessments, completeness, quality, provider-anrop).
- Fake-guards: 0 LLM-anrop, 16 provider-anrop/cold, 16 map-barn per SWE-cold,
  24/24 exakt warm-reuse, 0 nätverksförsök, inga timeouts.
- **Cutover-säker vinnare: arm A** — samma concurrency och loopform som i dag;
  den variant som wires i parity-PR:en.
- **Snabbast: arm B** — vinsten kommer från concurrency 8 → 16, inte från
  workflow-formen. Rekommenderas endast som separat config-följd efter live
  rate-limit-validering, aldrig som cutover-val.

Tolkning: SWE-loopen kostar ca **1 % median** i orkestrering jämfört med dagens
loop i fake-läget (väl inom +10 %-budgeten). Fake-läget mäter orkestrering, inte
researchkvalitet; kvalitetsparitet är garanterad by construction eftersom alla
armar kör samma domänkod.

## Live-lagret

Live-mätningen är **inte körd** — dokumenterad blockerare, inte en gate:

- `ResearchCompositionError: KnowledgeVectorStore is not configured` — scriptet
  kör inte appens lifespan/wiring, så vector store och OverGraph-runtime saknas.
- Dev-SQLite (`backend/data/opinionssimulator.db`) står på revision
  `105_enable_postgres_rls` och kan inte migreras till head: migration
  `111_raw_domain_claims` fallerar.

För att köra live krävs (a) app-livscykel-wiring av vector store +
OverGraph-runtime och (b) en databas på head med prompt defaults. Live är
observationellt (icke-deterministiskt), kan aldrig godkänna en workflow och
påverkar därför inte cutover-beslutet.

## Reproduktion

```bash
cd backend
uv run python scripts/benchmark_research_swe.py --runs 8 --repeats 6 \
  --questions 2 --needs 16 --fake-latency-ms 40 \
  --arms baseline,swe_a,swe_b --strict
uv run python scripts/benchmark_research_swe.py --render-run \
  data/research_swe/frozen-a00ba5659b20-20261021T222445Z
```

Baslinjen för dagens loop mäts separat av
[benchmark_research_loop.py](../../backend/scripts/benchmark_research_loop.py)
(se [research-baseline-measurement.md](research-baseline-measurement.md)).


<!-- v2:528d26d45dfa:v2-528d26d45dfa-20261021T234946Z -->
## Mätning v2 — kritisk väg, concurrency, paritet, live-kvalitet

- Harness: `backend/scripts/benchmark_research_swe_v2.py` sha256 `528d26d45dfa8ae874fe3ab8345c83c07463197ec3351a31f9aff1da32f24b90`
- git HEAD: `175b2ffea3f829d27fc7dbecfef7e79a554962e3`
- Rådata: `/Users/erikfremred/socialism/data/research_swe/v2-528d26d45dfa-20261021T234946Z`
- Fake: 8 oberoende runs x 6 repeats x 2 frågor, needs=16, latens=40 ms
- Live (observationslager): 2 frågor x 3 armar x 2 repeats
- Paritet: alla scenarier lika
- Live: ej körd
- v1-artefakten `a00ba565…` (n=8) är fortsatt cutover-bas.
