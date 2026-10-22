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
- Live: ej körd — environment-blocked (lagen.nu/mcp onåbar från mäthosten; live-wiring verifierad men ingen retrieval)
- v1-artefakten `a00ba565…` (n=8) är fortsatt cutover-bas.


<!-- v2:caafc8706a75:v2-caafc8706a75-20261022T062521Z -->
## Mätning v2 — kritisk väg, concurrency, paritet, live-kvalitet

- Harness: `backend/scripts/benchmark_research_swe_v2.py` sha256 `caafc8706a753898d88391d18f6a966b4ca279709f28d4870a0c2432056b9373`
- git HEAD: `e6a40a923efb2e9dfcaf3b78503cc70365321f1a`
- Rådata: `/Users/erikfremred/socialism/data/research_swe/v2-caafc8706a75-20261022T062521Z`
- Fake: 8 oberoende runs x 6 repeats x 2 frågor, needs=16, latens=40 ms
- Live (observationslager): 2 frågor x 3 armar x 2 repeats
- Paritet: se rapporten
- Live: körd (observationslager, ej gate)
- v1-artefakten `a00ba565…` (n=8) är fortsatt cutover-bas.


<!-- v2-live-observation:caafc8706a75 -->
### Live-observation (freeze #5, `caafc8706a75…`, commit `e6a40a92…`)

- Körning: 2 frågor × 3 armar × 2 repeats = 12/12, exit 0, ~14 m 44 s; alla 12 attempts `ready`, evidence sets `frozen` (12 st `research_frozen_ready`).
- **Evidens: 0 found totalt.** baseline 43 not_found/14 error; A 65/13; B 58/20. `lagen_nu`-excerpts: `resolve_no_document`, `search_no_hit`, `OperationalError: research source failed`; Supabase (`domain_knowledge`/`customer_knowledge`) gav inga träffar i temp-DB:n. Detta trots att endpoints är nåbara (healthy-verifiering) — retrieval gav alltså inga dokument för dessa 36 §-frågor.
- Assessments: 33 insufficiencies, 0 sufficient; completeness: 0 pass; syntesrubrik/LLM-dom: 0/12 (domarna säger uttryckligen att evidens saknas). `needs_success_rate` i harnesset är en proxy (needs med id), inte lyckade needs — verkliga lyckade needs = 0.
- Per-steg-tider (mätta): planning, source_fetch, assessment, follow_up, quality_persist, persist. **Inte exercerade/observerbara:** knowledge_reuse (0 anrop; tom Graph), jev_relevance (0; inga graph-kandidater), completeness (0 pass pga budget-stop), freeze (0 timer men `research_frozen_ready`=12 → ingår i persist/`finish_research_wave`), synthesis = not a separate stage.
- Ranking: alla kvalitetsdimensioner 0 för alla armar → "comparable"; ingen arm får klassas bättre. A snabbast i medel (57,8 s vs baseline 66,6 s, B 83,8 s) men med samma noll-evidenS; B högst spridning (22,8–118,1 s) och flest tokens (226,7k).
- Slutsats: mätningen är genomförd och instrumenteringen fungerar, men retrieval-kvaliteten kan inte utvärderas med denna körning; nästa steg är att felsöka varför lagen.nu/Supabase ger `resolve_no_document`/`search_no_hit` för 36 §-frågorna (query/tool-semantik eller provider-konfiguration), inte att köra fler jämförelser på noll-evidenS.


<!-- v2:caafc8706a75:v2-caafc8706a75-20261022T064321Z -->
## Mätning v2 — kritisk väg, concurrency, paritet, live-kvalitet

- Harness: `backend/scripts/benchmark_research_swe_v2.py` sha256 `caafc8706a753898d88391d18f6a966b4ca279709f28d4870a0c2432056b9373`
- git HEAD: `e6a40a923efb2e9dfcaf3b78503cc70365321f1a`
- Rådata: `/Users/erikfremred/socialism/data/research_swe/v2-caafc8706a75-20261022T064321Z`
- Fake: 8 oberoende runs x 6 repeats x 2 frågor, needs=16, latens=40 ms
- Live (observationslager): 1 frågor x 3 armar x 1 repeats
- Paritet: se rapporten
- Live: körd (observationslager, ej gate)
- v1-artefakten `a00ba565…` (n=8) är fortsatt cutover-bas.


<!-- v2:ba48eb2a3a7b:v2-ba48eb2a3a7b-20261022T070513Z -->
## Mätning v2 — kritisk väg, concurrency, paritet, live-kvalitet

- Harness: `backend/scripts/benchmark_research_swe_v2.py` sha256 `ba48eb2a3a7bdc1755184f43412a8af9570d04a9ddbb5b9fe908e700c40efc63`
- git HEAD: `c07fc348407c50e9fdf3aad3fcd50c5db08c6403`
- Rådata: `/Users/erikfremred/socialism/data/research_swe/v2-ba48eb2a3a7b-20261022T070513Z`
- Fake: 8 oberoende runs x 6 repeats x 2 frågor, needs=16, latens=40 ms
- Live (observationslager): 1 frågor x 3 armar x 1 repeats
- Paritet: se rapporten
- Live: körd (observationslager, ej gate)
- v1-artefakten `a00ba565…` (n=8) är fortsatt cutover-bas.


<!-- v2-live-artifacts:12runs+diag:task13 -->
## Mätning v2 — live-artefakt (12 runs), diagnostik och varför 0 found

### Huvudartefakt: full live-körning (12 runs)

- Katalog: `data/research_swe/v2-caafc8706a75-20261022T062521Z`; harness sha `caafc8706a753898d88391d18f6a966b4ca279709f28d4870a0c2432056b9373`; commit `e6a40a923efb2e9dfcaf3b78503cc70365321f1a`.
- 2 frågor (`source_1`/`source_2`, 36 §) × 3 armar × 2 repeats = **12 produktionskörningar**, temp-SQLite på alembic head, **produktions-embeddings** (`graph_embedding_cache` 5 001 rader, `text-embedding-3-large`, 3072 dims).
- 8 samtidiga needs; **44/213 evidence-items `OperationalError: database is locked`**; source_fetch ≈7–10 s/anrop; **0 found** i alla armar; alla 12 `ready` med frozen evidence sets.
- Tabell (wall mean/median ms, tokens, LLM, evidence): baseline 66 629,6/71 862,9, 156 518, 26–46, 43 nf/14 err; A 57 753,5/63 332,3, 167 513, 28–54, 65 nf/13 err; B 83 775,1/97 130,4, 226 683, 26–67, 58 nf/20 err. Assessments: 0 sufficient; completeness 0 pass; syntesrubrik 0.
- Per-steg (summa/calls): source_fetch dominerar (355 531/45; 413 262/57; 628 074/59); planning 13–15 s; follow-up 17–20 s; persist 18–21 s; assessment/quality_persist nära 0. Knowledge reuse/Jev/completeness/freeze gav 0 calls (tom Graph, inga graph-kandidater, budget-stop; freeze bekräftad av 12 `research_frozen_ready` inuti persist). Syntes = **not a separate stage**.
- Ranking: alla armar lika (noll) kvalitet → **"comparable"; ingen kvalitetsranking görs**; A:s snabbare medelvärde är inte bättre kvalitet.

### Diagnostikkörningar

- **Diag #1** (3 samples, samma frysta harness): katalog `data/research_swe/v2-caafc8706a75-20261022T064321Z`, sha `caafc870…`, commit `e6a40a92…`. `--live-questions 1 --live-repeats 1 --arms baseline` gav 3 samples (fryst harness itererade då alla armar). 0 found; baseline 13 nf/10 err (wall 137,6 s, 347k tokens, 65 LLM), A 17/7 (91,3 s, 242k, 49), B 17/9 (116,3 s, 395k, 80); source_fetch 15 anrop/arm med 25,1/11,4/16,8 s per anrop; 26 `OperationalError: research source failed`-events. MCP-verktygsräknare fanns inte ännu i harnessen.
- **Diag #2** (1 sample, concurrency=1): katalog `data/research_swe/v2-ba48eb2a3a7b-20261022T070513Z`, sha `ba48eb2a…`, commit `c07fc348…`; DB `backend/data/live_diag.sqlite` på head `192_drop_graph_tables`, kund 1, 195 prompt-fält; `RESEARCH_NEED_CONCURRENCY=1` + `RESEARCH_DOCUMENT_CONCURRENCY=1`. **OperationalError 0**; **29 MCP-anrop** (resolve 14, search 15, get_incoming 0, **get_document 0**); resolve-args = hela engelska frågor; search-queryer trunkerade engelska fragment; 16 needs/19 items: **found 0**, not_found 19, error 0 (resolve_no_document 8, irrelevant_relation 6, tom Supabase 4, search_no_hit 1); route/Jev nåddes aldrig (seed_ids/noul tomma); wall 38,9 s, 70 334 tokens, 29 LLM; source_fetch 22 594 ms/15 anrop (≈1,5 s/anrop), planning 3 862 ms, follow_up 11 888 ms, persist 12 177 ms. Child-stderr bara storage3-varning; inga exceptions.

### Varför live mätte 0 found

- `samples[].needs[].question` är **engelska redan i planner-outputen** i diag #2: N1–N5 och alla derived needs engelska, medan `research-main` (originalfrågan) är svensk. 5/6 initiala needs engelska.
- `samples[].mcp_diagnostics.resolve_args[]`: **14/14 är exakt lika med `needs[].question`** — källsteget får färdiga engelska hel-frågor, inte `36 § avtalslagen`; `_resolution_query`/`_search_query` kan inte rädda formatet (sökning blir trunkerade fragment).
- `research.planner.system` hämtas med `language="sv"`, men prompten saknar explicit språk-/citat-instruktion och det finns ingen deterministisk guard → **icke-deterministisk planner-output** (12-runs: svenska i 11/14 samples, engelska i 3; diag #1: svenska i alla; diag #2: engelska i 5/6 initiala + alla derived). `research-main` är svensk i samtliga.
- SQLite-lock (44/213 OperationalError, 7–25 s/anrop) var mätmiljöns problem: med concurrency=1 blev OperationalError 0 och source_fetch ≈1,5 s/anrop — men 0 found kvarstår.

### Slutsats

- Live-kvalitetsmätningen är **blockerad av retrieval-frågeformatet (task-13)**, inte av SWE, Jev eller embeddings.
- Fake/parity-lagren använder **fake embeddings (constant vector)** — deras kvalitet är **inte meningsfull**; endast gates/paritet är auktoritativa där.
- Ingen kvalitetsranking görs; v1-artefakten `a00ba565…` är fortsatt cutover-bas. Full rapport: [research-swe-experiment-v2.md](research-swe-experiment-v2.md).
