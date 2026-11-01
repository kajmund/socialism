# Fas B — Ägarskapsmatris: SWE respektive Socialism

**Status:** Utredningsleverans baserad på koden i `origin/main` (`666eccb0`) och
inventeringarna [`01-inventory-rust.md`](01-inventory-rust.md),
[`02-inventory-python.md`](02-inventory-python.md) samt
[`05-gym-split.md`](05-gym-split.md). Ingen kod ändras av detta dokument.
**Frågan:** vilken förmåga ska ägas av SWE respektive Socialism?
**Regel (spec §4):** en förmåga hör hemma i SWE när den kan beskrivas, testas
och användas **utan Socialisms domänbegrepp**. Att flera domäner använder en
förmåga är inte skäl nog att flytta den.

## 1. Metod och läsanvisning

- Raderna är kapaciteter/moduler, inte filer; filnivå finns i inventeringarna.
- **Ägare** = den som äger kontraktet och får ändra det. **Åtgärd** = vad som
  behöver göras vid en extraktion, inte vad som görs nu.
- Kodreferenser är `fil:rad` i `origin/main`. Där en bedömning inte kan avgöras
  från koden är den markerad **beslutspunkt** (§7).
- Gränsfall som kräver ett aktivt val redovisas separat i §7 i stället för att
  gömmas i tabellerna.

## 2. Sammanfattning

| Kategori | Antal enheter | Ägare |
| --- | --- | --- |
| Rust-kärna (SWD-maskin, effekter, events, uttryck, preflight, kanonisering) | 1 crate, 17 källfiler (3 804 rader) | SWE |
| Python-hostlager (compile/validate/driver/dispatch/kontrakt) | 16 `.py` + JSON-schemat flyttbara oförändrat; 4 med liten inversion; `features.py` + `providers.py` till Socialism | SWE |
| Domänläckage i Python-paketet | 3 filer, 5 importrader | ska bort ur SWE |
| Generiska experimentförmågor (ledger, metering, behov/operationer, gym-runner) | delar av `crates/swe-gym` | SWE (befrämjas) |
| Research-/juridik-/dokumentdomän | `backend/app/services/research/**`, `app/jev/**`, `app/services/research/gliner/**`, OverGraph, prompts, fixtures | Socialism |
| Domänexperimentet i `crates/swe-gym` (JEV/GLiNER2/blindtest) | 21 källfiler (20 moduler) + 24 exempel + 45 verktyg + 224 benchmarkfiler (~11 MB) | Socialism (eller arkiv) |

Slutsats i en mening: **motorn och dess host-kontrakt är generiska; det som
blandar dem med Socialism är fyra små beroenden, medan behovs-, evidens-,
operations- och budgetförmågorna finns i experimentcraten och måste befrämjas
till SWE.** Ingen av dessa punkter kräver en ny arkitektur — de kräver
beroendeinversion och flytt av befintlig kod.

## 3. SWE — exekveringsmotorn

| Kapacitet | Nuvarande placering | Domänkoppling | Ägare | Åtgärd | Not |
| --- | --- | --- | --- | --- | --- |
| SWD 1.0-definition, schema, graf, joins, uttryck | `crates/swe-native/src/{definition,preflight,expression,path,canonicalize,json,convert}.rs`; `backend/app/swe/{definition,graph,joins,expression,paths,schema,canonicalize,yaml_load,freeze}.py` + `swd_v1.schema.json` | Generisk | SWE | Behåll | `prompt_key`-valideringen skiljs från katalogmedlemskap (§5) |
| Maskin: schemaläggning, komplettering, idempotens, konflikter | `crates/swe-native/src/machine/**` (1 660 rader) | Generisk | SWE | Behåll | Publikt kontrakt: effekter + completions |
| Effekter/status | `crates/swe-native/src/effects.rs` | Generisk | SWE | Behåll | `RunStatus`, `InvokeHandler/Provider/Cancel` |
| Typade fel | `crates/swe-native/src/error.rs`; `backend/app/swe/{errors,runtime_errors}.py` | Generisk | SWE | Behåll | Publik felkategori |
| Events/linjage | `crates/swe-native/src/events.rs` | Generisk | SWE | Behåll | In-memory sink; durable sink är host |
| Kanonisk JSON + SHA-256 | `crates/swe-native/src/canonicalize.rs`; `backend/app/swe/canonicalize.py` | Generisk | SWE | Behåll | Rust ska bli normativ; Python är orakel tills paritet är etablerad |
| Host-driver (asyncio, deadlines, cancel, replay) | `backend/app/swe/runtime.py` (496 rader) | Generisk | SWE | Flytta | Enda `swe_native`-importen (`runtime.py:74-80`, lazy) |
| asyncio-dispatch, semafor, outputvalidering | `backend/app/swe/runtime_dispatch.py` | Blandad: `render_prompt` importeras | SWE | Refaktorera → Flytta | Injicera renderare (§5) |
| Preflight/validering/klocka/thaw | `backend/app/swe/{runtime_preflight,runtime_validate,runtime_clock,runtime_thaw}.py` | Generisk | SWE | Flytta | |
| Publik exportyta | `backend/app/swe/__init__.py` | Blandad (exporterar `FEATURE_IDS`) | SWE | Refaktorera | Host-exporter flyttas till Socialism |
| PyO3-bindning | `crates/swe-native/src/python.rs` + `pyproject.toml` | Generisk | SWE | Flytta | Modulnamnet `swe_native` behålls |
| Rust/Python-paritetstester | `backend/tests/test_swe_runtime_parity.py` | Generisk | SWE | Flytta | Kräver byggd extension |
| Runtime-benchmark | `backend/scripts/benchmark_swe_runtime.py` | Generisk | SWE | Flytta | Enda generiska benchmarket |

## 4. SWE — host-kontrakt och injektionspunkter

| Kapacitet | Nuvarande placering | Domänkoppling | Ägare | Åtgärd | Not |
| --- | --- | --- | --- | --- | --- |
| Provider-protokoll + registry + dispatch | `runtime_dispatch.py:22-41`, `runtime_preflight.py:29-55` | Generisk | SWE | Flytta | `Provider = Callable[[request], Awaitable]` |
| Provider-svarsvalidering | `runtime_dispatch.py:194-217` | Generisk | SWE | Behåll | `choice` måste ligga i nodens `choices`; ingen fallback |
| Prompt-**identitet** (`prompt_key`) + cache-nyckel | `swd_v1.schema.json`; `cache.py` | Generisk | SWE | Behåll | Identitet ja, prompttext nej |
| Prompt-**text** och katalog | `backend/app/services/prompt_catalog.py` (3 565 rader), DB-prompts | Socialism-specifik | Socialism | Behåll | Injiceras som `prompts`-map + key-whitelist |
| Prompt-rendering | `backend/app/services/prompt_render.py:3-16` (16 rader) | Generisk default; host kan injicera egen policy | SWE | Flytta + injicera | Den generiska default-renderaren flyttar till SWE-hostpaketet; dispatch tar en injicerad renderare. Ingen kopia stannar i Socialism (ingen dubbelimplementation) |
| Beslutscache | `backend/app/swe/cache.py` | Generisk | SWE | Flytta | `DecisionCache` + `decision_cache_key` |
| OverGraph JEV-cache (implementation) | `backend/app/services/overgraph/jev_cache.py` | Blandad (generiskt kontrakt, domänlagring) | Socialism | Behåll | Implementerar SWE-protokollet; öppnar katalog direkt → Owner-fråga (§7) |
| Run/Invocation-kontrakt | `backend/app/swe/run_store.py:15-56` | Generisk | SWE | Flytta | `RunRecord`, `InvocationRecord`, `RunStore` |
| OverGraph run-store (implementation) | `backend/app/services/overgraph/workflows.py` | Blandad | Socialism | Behåll | Atomiska transitions + `immediate` WAL; stannar i Socialism |
| Resume-semantik | `docs/specs/swe-overgraph.md`; `runtime.py:294` | Generisk | SWE | Flytta + dokumentera | Rust-journal saknas (§7/`04`) |
| Host-scope/katalog (customer/feature) | `backend/app/swe/features.py`; `schema.py:16-18` | Socialism-specifik | Socialism | Separera | SWE tar opak scope/nyckel eller store-fabrik |
| Event-konsumtion (progress, UI, DB) | `research_progress_events`, `models.py:2964`; `loop_control.py:129+` | Socialism-specifik | Socialism | Behåll | SWE äger bara event-**kontraktet** |
| JEV-provider (implementation) | `backend/app/swe/providers.py` | Socialism-specifik | Socialism | Flytta ut | Enda rena domänfilen i `app/swe`; används bara av test i dag |

## 5. Förmågor som måste befrämjas från experimentcraten

Dessa finns i dag bara i `crates/swe-gym` (och delvis som Python-verktyg i
samma crate). De är generiska men ligger i experimentlagret.

| Kapacitet | Nuvarande placering | Domänkoppling | Ägare | Åtgärd | Not |
| --- | --- | --- | --- | --- | --- |
| Sweycoin-ledger | `crates/swe-gym/src/ledger.rs` (append-only, milli, replay, idempotens) | Generisk | SWE | Flytta till `swe-budget` | Fullt testad (`tests/ledger_tests.rs`); ingen produktionsanvändning i dag |
| Meterad exekvering (provider-anrop mot budget) | `crates/swe-gym/src/driver.rs:48-188` | Blandad: generisk loop, research-chunk-specifik `fake_analyze`/dokumentbyggare | SWE | Separera | Generisk loop + typade budgetfel flyttar; chunk-harness stannar |
| Behov (`NeedRef`, prioritet, status) | `crates/swe-gym/src/ops.rs:12-24`; domänvariant `ResearchNeed` (`research/models.py:63`) | Blandad: generisk struktur, juridiska fixtures | SWE | Separera + Refaktorera | SWE äger generisk typ; `ResearchNeed` projiceras av bryggan. `01` klassar filen som Socialism-specifik — den generiska typen bryts ut (B2) |
| Operationskontrakt + grind | `crates/swe-gym/src/ops.rs:26-213` | Blandad: generisk grind, domänexekutorerna `MAX_NOTICE_PERIOD`/`APPLY_EXCEPTION` | SWE | Separera | `OperationSpec`/`ExecutionPolicy`/`OpOutcome`/grind + loopen befrämjas; exekutorerna stannar. `01` klassar filen som Socialism-specifik — grinden är den generiska delen (B2) |
| `NeedMore`-slingan | `ops.rs:143-213` | Generisk | SWE | Flytta | Skyddet mot identisk `NeedMore` två gånger ingår |
| Evidensstatus VERIFIED/AMBIGUOUS/REJECTED | `crates/swe-gym/tools/eval_uncertainty_states.py:60-81`, `tools/run_blindtest_v2.py` | Blandad: generisk tillståndslogik, juridisk spann/GLiNER2-koppling | SWE | Befrämja logiken; verktygen stannar | Ingen generisk evidenstyp finns i dag → byggs i SWE, domänhärledning i Socialism |
| Evidensproveniens | frånvarande som generisk typ; domänen har `ResearchEvidence` (source/locator) | — | SWE | Bygg | Proveniens obligatorisk i SWE-kontraktet |
| Policy-gränssnitt (tillåtna åtgärder) | `crates/swe-gym/src/{agent,bandit,td,student,explore,train,env}.rs` | Blandad: generisk policy-loop, research-MDP | SWE | Separera | SWE äger det smala `Policy`-kontraktet; inlärningsarmarna är gym |
| Benchmark-/experimentrunner | `crates/swe-gym/src/{bench,benchmark,dataset,calibrate,oracle}.rs` | Blandad | SWE | Separera | Se `05-gym-split.md` |
| Syntetisk frögenerator | `crates/swe-gym/src/gen.rs` | Generisk | SWE (gym) | Flytta | Ren deterministisk generator |

## 6. Socialism — applikationen

| Kapacitet | Nuvarande placering | Domänkoppling | Ägare | Åtgärd | Not |
| --- | --- | --- | --- | --- | --- |
| Research-planering, behovshantering, evidensinsamling, quality/assessment/completeness/follow-up/freeze | `backend/app/services/research/**` | Socialism-specifik | Socialism | Behåll | Den domän som SWE kör |
| Research-bryggan (SWD-loopen) | `backend/app/services/research/swe_bridge.py` | Socialism-specifik | Socialism | Behåll | Enda produktionsseamen (`execution.py:938-941`) |
| Research-leases, claims, worker | `research/claims.py`, `research_worker.py`, `question_attempt_worker.py` | Socialism-specifik | Socialism | Behåll | Postgres CAS |
| Research-persistens | `execution_research_claims`, `research_need_executions`, `evidence_sets`, `research_progress_events` | Socialism-specifik | Socialism | Behåll | Inte SWE-runstate |
| JEV System One + JEV-provider | `backend/app/jev/**`, `app/swe/providers.py` | Socialism-specifik | Socialism | Flytta `providers.py` hit | Provider-implementation, inte motor |
| Promptkatalog + prompttext/konfiguration | `app/services/prompt_catalog.py`, `app/config.py` | Socialism-specifik | Socialism | Behåll | Injiceras i SWE |
| OverGraph-integrationer | `app/services/overgraph/**` (kunskap, Owner, workflows, jev_cache) | Socialism-specifik | Socialism | Behåll | SWE får kontrakten, inte implementationerna |
| Dokumentingest, PDF/Word, TextUnits | `app/services/overgraph/**`, knowledge/document-moduler | Socialism-specifik | Socialism | Behåll | SWE får stabila id:n/hashar via evidensproveniens |
| GLiNER2 + spannkontrakt | `app/services/research/gliner/**` | Socialism-specifik | Socialism | Behåll | |
| Externa rättskällor (lagen.nu, Riksdagen) | research-sources | Socialism-specifik | Socialism | Behåll | |
| Juridiska golden-frågor, avtalsfixtures, blindtest | `backend/tests/research_reuse/**`, `crates/swe-gym/{benchmarks,tools,examples}/**` | Socialism-specifik | Socialism | Behåll | Får inte följa med SWE |
| Produkt-API, frontend, användarkonfiguration, auth | `backend/app/api/**`, `frontend/**` | Socialism-specifik | Socialism | Behåll | |

## 7. Gränsfall och beslutspunkter

| # | Fråga | Rekommendation | Varför |
| --- | --- | --- | --- |
| 1 | Ska Python-hostlagret (`app/swe`) flytta till SWE-repot? | **Ja**, som `python/swe` i samma repo/tag som Rust-craten | Det är generisk motorhost; att lämna det i Socialism vore att låta Socialism äga SWE:s publika host-kontrakt. Kräver att domänläckagen (§5 i `02`) är brutna först |
| 2 | Ska `OverGraph`-run-storen följa med? | **Nej.** SWE äger `RunStore`/journal-kontraktet; OverGraph-implementationen stannar | Lagringsbackend + Owner-regel är Socialism-arkitektur. Att flytta implementationen vore fel både för domän och Owner |
| 3 | Ska `WorkflowHostContext`/`FEATURE_IDS` vara kvar i SWE? | **Nej.** Flytta till Socialism; SWE tar opak `scope`/katalognyckel eller store-fabrik | Fem hårdkodade produktfeatures är Socialisms produktyta; motorn behöver bara en opak nyckel |
| 4 | Ska `prompt_key` finnas kvar i SWD-schemat? | **Ja** som identitet; medlemskapsvalideringen ska ske mot en injicerad registry | Cache/spårbarhet behöver en stabil nyckel; kataloginnehållet är domän |
| 5 | Ska JEV-providern vara en "SWE provider"? | **Nej.** Provider-**protokollet** är SWE; JEV-implementationen är Socialism | Modell/vendor-integration hör till applikationen. I dag är den bara testad, inte produktionskopplad |
| 6 | Ska `swe-gym` flyttas som helhet? | **Nej.** Generisk kärna separeras; domänexperimentet stannar | 224 juridiska benchmarkfiler (~11 MB), GLiNER2/JEV-verktyg och blindtest tillhör Socialism. Se `05-gym-split.md` |
| 7 | Ska SWE äga evidensstatusarna VERIFIED/AMBIGUOUS/REJECTED? | **Ja, den generiska tillståndsmodellen.** Domänhärledningen (spann, klausuler, JEV) stannar | Statusarna beskriver evidens generellt; hur de härleds ur juridiska spann är domän |
| 8 | Ska SWE äga `Sweycoins`/ledger? | **Ja**, i `swe-budget` | Budget är generisk enligt spec §9; ledger är redan domänfri och fullt testad |
| 9 | Ska `benchmark_research_swe*.py` flytta? | **Nej.** `benchmark_swe_runtime.py` flyttar; research-benchmarks stannar | Den förstnämnda mäter research-cutover, den senare motorns transitionskapacitet |
| 10 | Var ska referensexemplet bo? | SWE-repot (`crates/swe-reference`) | Det är beviset att motorn kan användas utan domän och ska följa motorns version |
| 11 | Vad händer med `wait`/`subworkflow`/`retry`? | Inte en del av v1-kontraktet; dokumenteras som avvisade | De är redan preflight-avvisade; att lova dem i ett publikt kontrakt vore fel |
| 12 | Licens/namn/publicering av nya repot? | **Beslutspunkt före PR 4** (i dag `UNLICENSED`, `publish = false`) | Krävs för crate/wheel-distribution; git-tagg-konsumtion fungerar utan |

## 8. Felriktade beroenden (sammanfattning)

Fullständig evidens i `02-inventory-python.md` §4. Riktningen är i dag:

```
app.swe.definition        → app.services.prompt_catalog        (SWE → domän)   [fel]
app.swe.runtime_dispatch  → app.services.prompt_render         (SWE → domän)   [fel]
app.swe.providers         → app.jev / app.services.research    (SWE → domän)   [fel]
app.services.research     → app.swe                            (domän → SWE)   [rätt]
app.services.overgraph    → app.swe                            (adapter → kontrakt) [rätt]
```

- **Ingen litterär Python-cykel** hittades, men en **paketnivåcykel**: `app.swe`
  importerar in i `app.services`/`app.jev` samtidigt som `app.services` importerar
  `app.swe`. Den måste vändas innan flytt.
- `app.swe` importerar **aldrig** OverGraph (0 importrader; endast docstrings) och
  importerar `swe_native` på exakt en plats (`runtime.py:74-80`, lazy). Det är
  den önskade riktningen och ska bevaras.
- Rust-kärnan har inga domänberoenden; det enda "domänlika" i `swe-native` är
  inert testdata med research/jev-strängar (`machine/mod.rs:222,249,272` och
  `tests/machine.rs:188-189`) samt crate-beskrivningen i `Cargo.toml:6` och
  `README.md:3`. Byt till neutrala värden vid extraktion.

## 9. Vad som inte får hända

1. Generisk kod får inte flyttas "för att den används av flera domäner" om den
   fortfarande kräver domänbegrepp (t.ex. `ResearchNeed`, `ResearchEvidence`,
   juridiska operationsnamn).
2. Inga parallella implementationer: grinden, ledgern och behovsmodellen får
   inte återimplementeras i demot eller i hostlagret. Demot ska konsumera
   befintliga kontrakt.
3. Socialism får inte behålla en tyst lokal kopia av motorn efter flytten (ingen
   fallback, inget vendordat `swe-native`).
4. SWE får inte ärva OverGraph-arkitekturen (Owner, kataloger) som ett internt
   antagande; lagring ska vara en injicerad adapter.
5. Socialisms produktfeatures, kundbegrepp, promptkatalog, JEV, GLiNER2,
   TextUnits eller juridiska fixtures får inte förekomma i SWE-repot.

## 10. Slutsats för Fas B

- **Gränsen är tydlig och ligger nära den föreslagna hypotesen i specen.**
  Motorn, hostkontrakten och de generiska experimentförmågorna hör till SWE;
  research, juridik, dokument, JEV, GLiNER2, OverGraph-implementationerna och
  produkten hör till Socialism.
- **Fem injektionspunkter** definierar gränsen: handlers, providers,
  prompts+renderare, beslutscache och run-store. Fyra är redan korrekt
  injicerade (handlers, providers, cache, run-store); prompts är delvis
  injicerade (kartan ja, renderaren importeras) och prompt-/feature-valideringen
  är hårdkodad.
- **Tre filer står för de fem domänimporterna** i Python-paketet:
  `providers.py`, `definition.py`, `runtime_dispatch.py`. Därutöver finns
  hostbegrepp att separera i `features.py`, `schema.py` och `__init__.py`
  (`02` §3/§5.1). Det är små, maskinella inversioner — inte arkitekturproblem.
- **Bonusfynd:** de generiska förmågorna behov/evidens/operationer/budget är
  mognare i experimentcraten än i motorn. Utan befrämjning dit är SWE inte den
  "generella motorn för budgetstyrd, verifierbar problemlösning" som specen
  beskriver, även om exekveringskärnan är generisk.
