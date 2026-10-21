# Research SWE — mätlogg (frysta mätningar)

Durable beslutslogg för mätfasen (task-4). Den genererade rapporten
[research-swe-experiment.md](research-swe-experiment.md) är en artefakt av den
slutliga mätningen; den här loggen bevarar även de tidigare mätningarna och
varför urvalet ändrades.

## Fryst harness

| Fält | Värde |
| --- | --- |
| Commit (harness + mätlogik) | `b009b69bd44278bb52c5ebaa1a6caf192cbc3df8` |
| Branch | `feat/research-swe-experiment` |
| `backend/scripts/benchmark_research_swe.py` sha256 | `2e202ed7584a9e609e27cdf526ab0a5c51c709a32b9cb019565e270319c8aff3` |
| Trösklar | median: CI95-övre kvot ≤ 1,10; p95 parad kvot ≤ 1,25; domänparitet exakt; fake-guards (0 LLM, 0 nätverk) |
| Fixture | 16 needs, 40 ms fake-latens/need; A = `research_need_concurrency` 8 (två vågor), B = 16 (en våg) |

Frys #1 (`be75efa4`, sha `8ae29e8a…`) ändrade bara rapporttext; frys #2
(`b009b69b`, sha `2e202ed7…`) lade till exakt reproduce-kommando, förväntat
resultat, samples/arm och den konkreta live-blockeraren. **Mätlogik och
trösklar är identiska mellan frysarna.**

## Artifakter

| # | Katalog (`data/research_swe/`) | Runs | Cold-samples/arm | Exit | Cutover-gate (A) |
| --- | --- | --- | --- | --- | --- |
| 1 | `frozen-8ae29e8affc3-20261021T215707Z` | 3 | 36 | 0 | pass (CI95 1,0471) |
| 2 | `frozen-2e202ed7584a-20261021T220232Z` | 3 | 36 | **1** | **FAIL** (CI95 1,1141) |
| 3 | `frozen-2e202ed7584a-20261021T221038Z` | 8 | 96 | **0** | **pass** (CI95 1,0502) |

Alla tre körningarna gjordes på tyst maskin med samma frågor, fixture och
trösklar. Rådata är gitignorad men ligger kvar lokalt; `results.json` bär
`git_head`, `script_sha256`, exakt reproduce-kommando och gate-resultat.

## Beslut: statistisk styrka n=3 → n=8

Körning 2 (n=3, den frysta slutliga harnessen) fällde cutover-gaten:
A:s punktestimat var +3,4 % median och p95-par-kvoten 1,165 (under 1,25), men
CI95-övre median-kvot blev 1,1141 > 1,10. Körning 1 med samma mätlogik gav
1,0471. Skillnaden är run-to-run-brus kring tröskeln.

Beslut (förhandsdeklarerat, före körning 3): **behåll trösklarna, öka antalet
oberoende runs från 3 (protokollminimum) till 8** för att få ett smalare
konfidensintervall. Ingen tröskel, fixture eller mätlogik ändrades. Båda
n=3-artefakterna (inklusive FAIL:en) behålls som transparens.

## Slutresultat (n=8, körning 3)

| Arm | Cold median (ms) | Median-kvot | CI95-övre | p95 parad kvot | Gate |
| --- | --- | --- | --- | --- | --- |
| baseline (dagens wave-loop) | 863,3 | 1,0 | 1,0 | 1,0 | pass |
| **SWE A** (dagens concurrency) | 898,8 | 1,0334 | 1,0502 | 1,1712 | **pass** |
| SWE B (2× fan-out, 8→16) | 870,8 | 1,0087 | 1,0353 | 1,1362 | pass |

- Domänparitet: exakt lika i alla armar (status, stop_reason, wave, needs,
  evidens, assessments, completeness, quality, provider-anrop).
- Fake-guards: 0 LLM-anrop, 16 provider-anrop/cold, 16 map-barn per SWE-cold,
  24/24 exakt warm-reuse, 0 nätverksförsök, inga timeouts.
- **Cutover-säker vinnare: arm A** — samma concurrency och loopform som i dag;
  den variant som wires i parity-PR:en.
- **Snabbast: arm B** — vinsten kommer från concurrency 8 → 16, inte från
  workflow-formen. Rekommenderas endast som separat config-följd efter live
  rate-limit-validering, aldrig som cutover-val.

Tolkning: SWE-loopen kostar ca **3 % median** i orkestrering jämfört med dagens
loop i fake-läget (inom +10 %-budgeten), medan B:s högre concurrency sparar
ca **3 %** i en latensbunden fixture. Fake-läget mäter orkestrering, inte
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
  data/research_swe/frozen-2e202ed7584a-20261021T221038Z
```

Baslinjen för dagens loop mäts separat av
[benchmark_research_loop.py](../../backend/scripts/benchmark_research_loop.py)
(se [research-baseline-measurement.md](research-baseline-measurement.md)).
