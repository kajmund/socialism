# Fas A — Python- och integrationsinventering (SWE host-adapter)

**Status:** Inventeringsleverans. Ingen produktionskod ändras av detta dokument.
**Bas:** `origin/main` `666eccb0cc61f4a5e15e95bc1e1edfbdf75b32e1`, branch
`feat/swe-standalone-investigation`, worktree `/Users/erikfremred/swe-standalone`.
**Omfattning:** `backend/app/swe/**`, research-integrationen (`swe_bridge`, seam i
`execution.py`, `loop_control.py`, `claims.py`, `research_worker.py`),
persistensadaptrarna (`overgraph/workflows.py`, `overgraph/jev_cache.py`),
providers, tester/fixtures/benchmarks samt build/CI.
**Kompanjoner:** [`01-inventory-rust.md`](01-inventory-rust.md),
[`04-public-contracts.md`](04-public-contracts.md),
[`05-gym-split.md`](05-gym-split.md), [`06-extraction-plan.md`](06-extraction-plan.md),
[`07-go-no-go.md`](07-go-no-go.md).

Dokumentet är skrivet för en läsare som inte känner Socialism: varje påstående om
kod har `fil:rad`. Där något inte kunnat verifieras är det uttryckligen markerat
**osäkert**.

---

## 1. Sammanfattning (verdict)

1. **`backend/app/swe/` är ett generiskt engine-paket med tre läckage, inte ett
   rent sådant.** Paketet består av **22 Python-moduler + 1 JSON-schema**
   (23 filer, 2 322 Python-rader), inte 24 moduler som uppdragsbeskrivningen
   antog — se §13 E1. Av dessa importerar **19 moduler** bara stdlib, `yaml`,
   `jsonschema` och övriga `app.swe`-moduler. **Tre moduler bryter mot
   domänneutraliteten:**
   - `providers.py:15-22` importerar `app.config`, `app.jev.system` och
     `app.services.research.fast_controller` (JEV/research),
   - `definition.py:13` importerar `app.services.prompt_catalog` (3 565-radig
     domänpromptkatalog) och validerar `prompt_key` ovillkorligt
     (`definition.py:152-163`),
   - `runtime_dispatch.py:17` importerar `app.services.prompt_render` och
     renderar prompttext inne i engine-dispatch (`runtime_dispatch.py:153`).
2. **Importriktningen är i praktiken enkelriktad ut ur engine-paketet, men
   paketnivån är tvåriktad.** `app.swe` importerar aldrig OverGraph
   (endast omnämnt i docstrings, `cache.py:4`, `run_store.py:4,43`; 0
   import-rader — E3), och `app.swe` importerar `swe_native` (PyO3) på exakt en
   plats, lat/lazy (`runtime.py:74-80`, `require_native` `runtime.py:115-121`).
   Men `app.swe` importerar in i `app.services`/`app.jev`, samtidigt som
   `app.services.{research,overgraph}` importerar `app.swe` (6 filer, 10
   import-rader — E4). Det är ingen litterär Python-cykel (leaf-modulerna är
   olika), men det är en **paketcykel** som gör en standalone-extraktion omöjlig
   utan att först vända beroendet.
3. **SWD 1.0:s generiska kärna är verkligt generisk.** Compile/validate
   (`definition.py`, `schema.py`, `graph.py`, `joins.py`, `expression.py`,
   `paths.py`, `canonicalize.py`, `yaml_load.py`), runtime-drivern
   (`runtime.py`), asyncio-dispatch (`runtime_dispatch.py`), preflight/errors/
   clock/thaw/freeze och de värdinjicerade kontrakten (`cache.py`,
   `run_store.py`, provider-registry i `runtime_dispatch.py:22-41`,
   `WorkflowResources` i `runtime.py:105-112`) är engine-kod. Endast
   `providers.py` är ren domänkod som råkat hamna i paketet.
4. **`FEATURE_IDS` är Socialism-produktens enum, inte engine-semantik.**
   `schema.py:16-18` hårdkodar `{research, expert_routing, model_routing,
   group_chat, webcrawler}`. Den används bara av host-kontexten
   (`features.py:28`) och styr en **valfri** OverGraph-katalogmappning
   (`features.py:35-37`) som i dag **inte är produktionskopplad** — run-store
   är `None` i produktion (`swe_bridge.py:24-25,118`; inga produktionsanrop av
   `WorkflowRunStore`/`JevDecisionCache`/`make_jev_provider` — E10). En fristående
   engine ska ta en **opak scope-/katalognyckel** från värden, inte känna till
   Socialisme features eller kunder.
5. **Research-integrationen är korrekt placerad och använder SWE som loop-motor.**
   Enda produktionsseamen är `execution._run_research_loop`
   (`execution.py:938-941`) → `swe_bridge.run_research_loop_via_swe`
   (`swe_bridge.py:298-303`). Loopen är fem SWD-noder + `end`
   (`swe_bridge.py:70-106`); alla research-primitiv ligger kvar i
   domain-handlers (`swe_bridge.py:159-239`). Det som ska stanna i Socialism är
   alltså stort och tydligt; det som ska flyttas är engine-katalogen.
6. **Vad ett standalone-repo fortfarande saknar:** inverterad prompt- och
   feature-validering, injicerad prompt-renderare, flyttad JEV-provider,
   generisk testfixture (dagens SWE-fixtures är research-färgade),
   standalone-`conftest`/CI, paketering av `swe_native` som distribuerbar wheel
   samt en persistensstrategi som respekterar OverGraph Owner-regeln. Detaljer i
   §11.3.

---

## 2. Terminologi och åtgärdsvokabulär

Kolumntaxonomin är låst av uppdraget. För att undvika missförstånd används
följande betydelser (kartan mot `04-public-contracts.md`:s KEEP/DECOUPLE/... i
parentes):

| Åtgärd | Betydelse (denna inventering) | Motsvarighet i 04 |
| --- | --- | --- |
| **Behåll** | Ligger kvar oförändrat där det är; ägs av Socialism. | KEEP |
| **Flytta** | Filen/modulen flyttas oförändrad till rekommenderad ägare (SWE-repo eller Socialism-app). | — |
| **Separera** | En fil delas: generisk del flyttas, domändel stannar; kräver minst en ny injektionspunkt. | DECOUPLE |
| **Refaktorera** | Beteendet behålls men gränssnittet ändras (beroendeinversion/injektion) före eller i samband med flytt. | DECOUPLE |

"Domänkoppling" avser **om modulen känner till Socialism-begrepp** (research,
JEV, kund, feature, promptkatalog), inte om den används av research.

---

## 3. Modulinventering — `backend/app/swe/` (samtliga filer)

Sortering i filordning. Varje rad är en fil; "Nuvarande placering" anger
modulens första meningsbärande symbol. `runtime.py` och `runtime_dispatch.py`
får djupanalys i §3.1–§3.2; `providers.py` i §4.2 punkt 3 och §5.3;
`definition.py` i §4.2 punkt 1 och §5.2.

| Nuvarande placering (file:line + module) | Ansvar | Beroenden (internal + external) | Domänkoppling (Generisk \| Blandad \| Socialism-specifik) | Rekommenderad ägare (SWE \| Socialism) | Åtgärd (Behåll \| Separera \| Flytta \| Refaktorera) |
| --- | --- | --- | --- | --- | --- |
| `backend/app/swe/__init__.py:3` (`app.swe`) | Publik exportyta för compile/validate/expression/errors/host-context. | Interna: `canonicalize`, `definition`, `errors`, `expression`, `features`, `schema`, `yaml_load`. Externa: inga. | Blandad — exporterar `FEATURE_IDS` (`__init__.py:8,12`) och `WorkflowHostContext` (`:7,20`) som är host-begrepp. | SWE | Refaktorera (dela yta i `engine`-exporter och host-exporter; flytta sedan) |
| `backend/app/swe/cache.py:18` (`app.swe.cache`) | `DecisionCache`-protokoll + `decision_cache_key` (stabil identitet över provider, prompt_key, prompttext, input, choices, params). | Interna: `canonicalize`. Externa: `hashlib`. | Generisk | SWE | Flytta |
| `backend/app/swe/canonicalize.py:21` (`app.swe.canonicalize`) | Kanonisk JSON (NFC, LF, int-normalisering, kollisionskontroll) + SHA-256; Python-orakel tills Rust är normativ (`:3-5`). | Interna: `errors`. Externa: `json`, `hashlib`, `unicodedata`, `math`. | Generisk | SWE | Flytta |
| `backend/app/swe/definition.py:42` (`app.swe.definition`) | `compile_definition`/`compile_swd_text`: version, storlek, schema, graf, joins, handler-/provider-registry, **prompt_key mot domänkatalog**. | Interna: `canonicalize`, `errors`, `freeze`, `graph`, `schema`, `yaml_load`, `joins` (via graph); **`app.services.prompt_catalog`** (`:13`). Externa: `jsonschema`. | Blandad | SWE | Refaktorera (injicera prompt-key-registry; ta bort `app.services`-import) |
| `backend/app/swe/errors.py:6` (`app.swe.errors`) | `SwdError`/`SwdParseError`/`SwdValidationError`/`SwdExpressionError` med `path`. | Interna: inga. Externa: inga. | Generisk | SWE | Flytta |
| `backend/app/swe/expression.py:14` (`app.swe.expression`) | Typad JSON-AST-uttrycksmotor (`eq/ne/lt/lte/gt/gte/and/or/not/in/add/sub/mul/div/exists`), ingen `eval` (`:1`, OPS `:204-220`). | Interna: `errors`, `paths`. Externa: `collections.abc`, `typing`. | Generisk | SWE | Flytta |
| `backend/app/swe/features.py:15` (`app.swe.features`) | Trusted `WorkflowHostContext` (customer_id, feature_id) + katalogkatalog `workflows/customer_<id>/<feature>/`. | Interna: `errors`, `schema` (`CUSTOMER_ID_PATTERN`, `FEATURE_IDS`). Externa: `re`, `pathlib`. | Blandad (host-/tenancy-konvention; OverGraph-specifik sökväg) | Socialism | Separera (opak scope-nyckel till SWE; customer/feature + `FEATURE_IDS` stannar) |
| `backend/app/swe/freeze.py:10` (`app.swe.freeze`) | Djupfrysning av kompilerad SWD till immutable `MappingProxyType`/tupler. | Interna: inga. Externa: `types`, `collections.abc`. | Generisk | SWE | Flytta |
| `backend/app/swe/graph.py:20` (`app.swe.graph`) | Semantisk grafvalidering: nodtyper, edge-targets, decision-routes, forks/maps, reachability, end-reachability, join-integration (`:20-29`). | Interna: `errors`, `joins`, `schema`. Externa: `collections`, `typing`. | Generisk | SWE | Flytta |
| `backend/app/swe/joins.py:14` (`app.swe.joins`) | Fork/map-branchkomplettering: varje branch slutar i sitt ägande join; ägarskap, escape, entry, delade noder. | Interna: `errors`. Externa: `collections`, `typing`. | Generisk | SWE | Flytta |
| `backend/app/swe/paths.py:15` (`app.swe.paths`) | Begränsad JSON-path (`$.a.b.0`), `resolve_path`, `MISSING`. | Interna: `errors`, `schema`. Externa: `re`, `collections.abc`. | Generisk | SWE | Flytta |
| `backend/app/swe/providers.py:27` (`app.swe.providers`) | Enda inbyggda providern `jev`: renderad prompt → JEV NOUL-frågor → `classify_research_decision` → deklarerat choice; inga fallbacks (`:31-68`). | Interna: `app.config.settings` (`:15`), `app.jev.system` (`:16`), `app.services.research.fast_controller` (`:17-22`). Externa: inga. | Socialism-specifik | Socialism | Flytta (till research-host-adapter; engine behåller bara provider-protokollet) |
| `backend/app/swe/run_store.py:15` (`app.swe.run_store`) | `RunRecord` (`:15-28`), `InvocationRecord` (`:31-39`), `RunStore`-protokoll (`:42-56`) för durable runs/replay. | Interna: inga. Externa: `dataclasses`, `typing`. | Generisk | SWE | Flytta |
| `backend/app/swe/runtime.py:74` (`app.swe.runtime`) | Tunn asyncio-driver runt Rust-maskinen: start/resume, effekt-applicering, persistens per transition, deadline/tick, cancel, replay. | Interna: `cache`, `definition`, `runtime_clock`, `runtime_dispatch`, `runtime_errors`, `runtime_preflight`, `run_store`, `runtime_thaw`; **`swe_native`** (`:74-80`). Externa: `asyncio`, `uuid`, `dataclasses`. | Generisk | SWE | Flytta |
| `backend/app/swe/runtime_clock.py:9` (`app.swe.runtime_clock`) | `WorkflowClock` (monotonic ms) + `FrozenClock` för tester. | Interna: inga. Externa: `time`, `dataclasses`. | Generisk | SWE | Flytta |
| `backend/app/swe/runtime_dispatch.py:22` (`app.swe.runtime_dispatch`) | Handler-/provider-dispatch utanför Rust-låset: `spawn_invocations`, semafor, output-validering, prompt-rendering, exact-cache single-flight. | Interna: `cache`, `runtime_errors`, `runtime_validate`; **`app.services.prompt_render`** (`:17`). Externa: `asyncio`, `dataclasses`. | Blandad | SWE | Refaktorera (injicera prompt-renderare; ta bort `app.services`-import) |
| `backend/app/swe/runtime_errors.py:6` (`app.swe.runtime_errors`) | Typade runtime-fel: `SweRuntimeError`, `SwePreflightError`, `SweHandlerError`, `SweUnsupportedError`. | Interna: inga. Externa: inga. | Generisk | SWE | Flytta |
| `backend/app/swe/runtime_preflight.py:13` (`app.swe.runtime_preflight`) | Fail-closed preflight: registrerade handlers/providers, aktiv promptkarta, cache vid `cache_policy: exact`, samt avvisning av `wait`/`subworkflow`/`retry` (`:10,58-78`). | Interna: `runtime_errors`. Externa: `collections.abc`, `typing`. | Generisk | SWE | Flytta |
| `backend/app/swe/runtime_thaw.py:9` (`app.swe.runtime_thaw`) | Tinar fryst SWD till JSON-värden före Rust-anrop. | Interna: inga. Externa: `collections.abc`, `typing`. | Generisk | SWE | Flytta |
| `backend/app/swe/runtime_validate.py:15` (`app.swe.runtime_validate`) | JSON-serialiserbarhet + `output_schema`-validering vid Python/Rust-gränsen. | Interna: `runtime_errors`, `runtime_thaw`. Externa: `jsonschema`, `math`. | Generisk | SWE | Flytta |
| `backend/app/swe/schema.py:10` (`app.swe.schema`) | Laddar `swd_v1.schema.json`, SWD-version, nodtyper, cache-policyer, **`FEATURE_IDS`** och regexkontrakt. | Interna: inga. Externa: `json`, `functools`, `pathlib`. | Blandad — allt utom `FEATURE_IDS:16-18` är generiskt. | SWE | Refaktorera (flytta feature-enum till host; schema kvar i engine) |
| `backend/app/swe/swd_v1.schema.json:1` | SWD 1.0 JSON Schema (Draft 2020-12): nodmodell, limits, expressions, bindings; provider-nod kräver `prompt_key` (`:213-239`). | Interna: inga. Externa: JSON Schema-spec. | Generisk (med host-semantik i `prompt_key`, se §4.2) | SWE | Flytta (prompt-nyckelvalidering separeras till host, se §4.2) |
| `backend/app/swe/yaml_load.py:14` (`app.swe.yaml_load`) | Valfri YAML/JSON-authoring-loader → JSON-objekt; runtime validerar bara JSON. | Interna: `errors`. Externa: `yaml`, `json`, `math`. | Generisk | SWE | Flytta |

**Summering:** **17 generiska filer** (16 `.py` + `swd_v1.schema.json`),
**5 blandade** (`__init__.py`, `definition.py`, `features.py`,
`runtime_dispatch.py`, `schema.py`) och **1 Socialism-specifik**
(`providers.py`). Alla 23 filer har en rad ovan.

### 3.1 Djupanalys `runtime.py` — den generiska drivern

- Importerar Rust-kärnan på ett ställe och feltolererar att extensionen inte är
  byggd (`runtime.py:74-80`); `require_native()` ger fail-fast med byggtips
  (`:115-121`). Detta är det enda `swe_native`-beroendet i `app/` (E5).
- Publik yta: `WorkflowRunner` (`:124`), `run_workflow` (`:273`),
  `resume_run` (`:294`), `WorkflowResources` (`:105-112`), `RunResult`
  (`:83-89`).
- Transition-persistens: `_persist` skriver `RunRecord` + nya events +
  invocation i **ett** store-anrop (`:337-363`); store-kontraktet är
  backend-agnostiskt.
- Effektloop: `_apply_effects`/`_apply_effect` (`:366-398`) hanterar
  `cancel_invocation`, spawn och **replay** av redan persisterade resultat
  (`_apply_replay` `:401-405`).
- Deadline: `_timeout_run` (`:420-424`) kallar `Machine.tick`; `_apply_one`
  (`:427-461`) väntar med återstående monotona tid och cancel-event.
- Inget i filen känner till research, JEV, OverGraph eller SQL. Den är flyttbar
  oförändrad.

### 3.2 Djupanalys `runtime_dispatch.py` — generisk dispatch med ett host-läckage

- `Handler`/`Provider` (`:22-23`) och `ProviderDispatch` (`:35-41`) är generiska
  kontrakt; `WorkflowResources` bär providers/prompts/cache/cancel
  (`runtime.py:105-112`).
- Hostläckaget är `render_prompt` (`:17`, anrop `:153`): engine äger
  prompt-**identiteten** (`prompt_key`) men inte prompt**textens** formatering.
  `render_prompt` är trivial `str.format` med `KeyError`-fel
  (`prompt_render.py:3-16`), men den hör till värden: en standalone-engine ska
  injicera `Callable[[Mapping[str,str], str, Mapping[str,Any]], str]` (eller en
  `PromptRenderer`-protokoll) i `ProviderDispatch`.
- Exact-cache: `_call_provider` (`:166-191`) beräknar `decision_cache_key` med
  providerns `cache_params` (`:177-184`), anropar `DecisionCache.resolve` och
  rapporterar `cache: hit` eller `cache: miss` i output (`:220-229`). Detta är generisk
  engine-semantik och flyttar.
- `identity_handler`/`sync_handler` (`:232-239`) är generiska test-/host-verktyg.

---

## 4. Importriktning, felriktningar och cykler

### 4.1 Verifierade riktningar

| Riktning | Bevis | Bedömning |
| --- | --- | --- |
| `app.swe` → `swe_native` (PyO3) | Endast `runtime.py:74-80` (import), `:115-121` (require). `grep -rn "swe_native" backend/app` ger 5 träffar, alla i `runtime.py` (E5). | Korrekt: engine-adaptern är enda bindningen. Lazy import gör att compile/validate-tester kan köras utan extension. |
| `app.swe` → OverGraph | 0 import-rader. `grep -rn "overgraph" backend/app/swe` ger 3 träffar, alla i docstrings (`cache.py:4`, `run_store.py:4,43`) (E3). | Korrekt: protokoll/implementation är separerade; `jev_cache.py`/`workflows.py` är Socialism-adaptrar. |
| `app.swe` → research/JEV/config/promptkatalog | 5 träffar i 3 filer: `providers.py:15,16,17`, `definition.py:13`, `runtime_dispatch.py:17` (E2). | **Felriktning** (se §4.2). |
| `app.services` → `app.swe` | 10 import-rader i 6 filer: `swe_bridge.py:38-41`, `sufficiency_experiment/loop.py:81-82`, `sufficiency_experiment/workflow.py:12`, `overgraph/workflows.py:32-33`, `overgraph/jev_cache.py:24` (E4). | Korrekt riktning: hosts använder engine. |
| `app.swe` → `app.jev` (JEV-systemet) | Endast `providers.py:16`. | **Felriktning** — JEV är research-domän. |

### 4.2 Felriktningar (måste vändas före extraktion)

1. **Promptkatalogen i compile (`definition.py:13,152-163`).** För varje
   provider-decision valideras `prompt_key` mot `PROMPT_KEY_SET` **ovillkorligt**
   — även när anroparen inte skickat någon prompt-registry. `PROMPT_KEY_SET`
   definieras i `prompt_catalog.py:3537` efter 3 565 rader Socialism-prompts.
   Konsekvens: en standalone-engine kan inte kompilera en provider-decision utan
   att importera hela Socialism-domänen. `compile_definition` har redan
   `handlers`/`providers` som valfria whitelists (`definition.py:45-46`); samma
   mönster ska användas för `prompt_keys`, och katalogen skickas in av värden.
   Tills dess är `definition.py` klassad **Blandad**.
2. **Prompt-rendering i dispatch (`runtime_dispatch.py:17,153`).** Engine
   ansvarar för att skicka en renderad prompt till providern, men
   renderingspolicyn (Python `str.format`, `KeyError`-semantik) är hostkod.
   Vänd med injicerad renderare i `ProviderDispatch`; flytta
   `prompt_render.py`-användningen till app-lagret.
3. **JEV-providern i engine-paketet (`providers.py:15-22,27-81`).**
   `providers.py` är den enda filen i `app/swe` som är ren Socialism-domän; den
   importerar `settings`, JEV-klienten och `classify_research_decision`. Den ska
   flytta till en host-adapter (t.ex. `services/research/swe_providers.py`);
   engine behåller `Provider`-protokollet + `cache_params`-konventionen.
   Notera att `04-public-contracts.md` § provider markerar provider-kontraktet
   som KEEP och JEV-implementationen som DOMAIN — samma slutsats.
4. **Host-context + feature-enum i engine (`schema.py:16-18`,
   `features.py:28,35-37`).** Se §5.1.
5. **Publika exportytan (`__init__.py:7-8,12,20,30`).** Engine-paketet
   exporterar `FEATURE_IDS`/`WorkflowHostContext`/`workflow_catalog_dir`. Det
   gör att även en framtida `python/swe`-distribution drar in
   OverGraph-katalogkonventionen i sin publik yta.

### 4.3 Cykler

Ingen **litterär Python-cykel** hittades: `definition.py:13` importerar
`prompt_catalog`, som i sin tur importerar `prompt_render`, `research_assessment_prompt`
m.fl. men **inte** `app.swe` (verifierat: `grep -n "app.swe"`
`prompt_catalog.py`/`prompt_render.py` → 0 träffar — E6). Däremot finns en
**paketnivåcykel**:

```
app.swe.definition  ──►  app.services.prompt_catalog
app.swe.runtime_dispatch ──► app.services.prompt_render
app.swe.providers   ──►  app.jev.system, app.services.research.fast_controller
app.services.research.swe_bridge ──► app.swe.{definition,run_store,runtime,runtime_dispatch}
app.services.overgraph.{workflows,jev_cache} ──► app.swe.{features,run_store,cache}
```

Det betyder att `backend/app/swe` inte kan flyttas som ett självständigt paket
förrän de fem `app.*`-raderna i E2 är borta. `swe_bridge.py` hanterar redan
en del av sin egen cykelrisk med **lazy imports** inuti metoder
(`swe_bridge.py:63-67,120-122,160-161,181-185,225-226,249,274,300`); det är
host-sidans problem och stannar i Socialism.

---

## 5. SWD 1.0: generiskt vs research-kopplat

### 5.1 `FEATURE_IDS` — ägarskap och analys

Fakta:

- Definieras i `schema.py:16-18` som en `frozenset` med fem Socialism-features.
- Konsumeras av `features.py:28` i `WorkflowHostContext.__post_init__` och av
  `tests/test_swe_features.py:51-58` som **låser listan som spec** (testet
  misslyckas om listan ändras).
- Styr katalogvägen `root/workflows/customer_<id>/<feature>/`
  (`features.py:35-37`) och scope-labeln
  `workflow.customer.<id>.<feature>` (`workflows.py:74-75`).
- Produktionsanrop: inga. `WorkflowHostContext` konstrueras **inte någonstans i
  produktionskoden**; endast av benchmark-skripten
  (`benchmark_research_swe.py:552`, `benchmark_research_swe_v2.py:707`) och i
  tester (`test_swe_persistence.py:29,300-301`,
  `test_research_swe/test_wiring.py:113`). Den enda produktionsseamen skapar
  ingen run-store (`swe_bridge.py:118` default `None`;
  `build_loop` vidarebefordrar bara ett eventuellt store — `swe_bridge.py:242-266`).

Bedömning:

- **Engine-semantik:** ingen. SWD-kompilering, routing, joins, expressions,
  provider-choices och events är oberoende av vilka feature-id:n som existerar.
- **Host-semantik:** ja. `customer_id` (tenancy), `feature_id` (produktyta) och
  `workflows/customer_.../...` (OverGraph-katalog) är Socialism-begrepp, inte
  workflow-begrepp.
- **Rekommendation:** flytta `FEATURE_IDS`, `CUSTOMER_ID_PATTERN` och
  `WorkflowHostContext` till Socialism-appen (t.ex.
  `backend/app/services/swe_host/`). Engine ska ta emot en **opak
  `scope`/`catalog_key: str`** (eller en `RunStore`-fabrik) och aldrig validera
  vilka scope-värden som finns. Om ett framtida SWE behöver tenant-begreppet
  generiskt ska det vara en host-definierad `frozenset[str]` som skickas in vid
  konstruktion, inte en konstant i engine.
- **Osäkerhet:** om `04`/`06` väljer att behålla en generisk "namespace"-typ i
  SWE (t.ex. `swe_host::Scope`) är det förenligt; poängen är att **värdet** på
  features inte får vara engine-konstant. Detta är en designfråga för Fas C/F,
  inte en inventeringsslutsats.

### 5.2 Promptnycklar

- `swd_v1.schema.json:39-44,213-239` kräver `prompt_key` för provider-noder.
  Det är rimligt generiskt: en provider-decision behöver en stabil
  prompt-identitet för cache och spårbarhet.
- Men `definition.py:152-163` gör **katalogmedlemskap** till ett
  kompileringskrav, och `runtime_preflight.py:45-50` gör en **icke-tom aktiv
  promptkarta** till ett preflightkrav. Båda är rätt som *host-resurskontrakt*
  men fel som *hårdkodad import*. Engine ska:
  1. alltid kräva ett `prompt_key`-format (schema),
  2. validera medlemskap endast mot en **injicerad** registry (om värden
     skickar en),
  3. kräva prompttext endast när en provider faktiskt ska köras (preflight,
     redan så i dag).
- Slutsats: `prompt_key`-fältet kan stanna i SWD-schemat; **valideringen** ska
  separeras (§4.2 punkt 1). `04-public-contracts.md` § 1.1 säger samma sak
  ("KEEP (DECOUPLE prompt/feature validation)").

### 5.3 Provider-avtalet

- Generiskt: `Provider = Callable[[Mapping], Awaitable[Any]]`
  (`runtime_dispatch.py:23`), svarsvalidering (`choice` måste vara sträng i
  deklarerade `choices`, `runtime_dispatch.py:194-217`), `cache_params`-attribut
  (`:183`), registry/preflight (`runtime_preflight.py:29-55`).
- Socialism: `make_jev_provider` (`providers.py:27-81`) med NOUL-frågor,
  thresholds och `classify_research_decision`.
- Rekommendation: behåll provider-**protokollet** i SWE (Behåll/Flytta);
  flytta JEV-implementationen till Socialism. Ingen generisk
  provider-implementation behövs i SWE-repot (04 markerar den som DOMAIN).

### 5.4 Cache- och store-kontrakt

- `DecisionCache` (`cache.py:18-30`) + `decision_cache_key` (`:33-51`) är
  generiska och ägs av engine; `jev_cache.py` implementerar dem mot OverGraph
  (`jev_cache.py:24,83-152`). Namnet "jev" är historiskt — kontraktet är inte
  JEV-specifikt (nyckeln innehåller `provider`/`prompt`/`params`).
- `RunStore`/`RunRecord`/`InvocationRecord` (`run_store.py:15-56`) är generiska;
  `workflows.py` är en OverGraph-implementation (§7).
- Båda implementationerna är i dag **endast testade/benchmarkade**, inte
  produktionskopplade (E10). Det är en lat risk: kontrakten är mindre prövade i
  produktion än de ser ut.

---

## 6. Generiskt host-/adapterlager som måste till SWE

Detta är den exakta gränsen. Allt i tabellen är engine-kod som en fristående
SWE-distribution behöver; kolumnen "Hostinjicerat" anger vad Socialism måste
tillhandahålla.

| Lager | Kod i dag | Generiskt ansvar | Hostinjicerat i dag | Åtgärd |
| --- | --- | --- | --- | --- |
| Definition/kompilering | `definition.py:42-163`, `schema.py`, `swd_v1.schema.json` | SWD-version, storlek, schema, graf, joins, registry, canonical hash | handler-/provider-whitelist via parametrar (`definition.py:45-46`); **promptkatalog** via import (`:13`) | Refaktorera → Flytta |
| Uttryck/paths | `expression.py:14-220`, `paths.py:15-44` | Deterministisk JSON-AST | — | Flytta |
| Graf/joins | `graph.py:20-221`, `joins.py:14-273` | Semantisk validering | — | Flytta |
| Kanonisering/serialisering | `canonicalize.py:21-86`, `yaml_load.py:14-64`, `freeze.py:10-15`, `runtime_thaw.py:9-14` | Kanoniska bytes + SHA-256, YAML/JSON-authoring, frysning | — (Rust blir normativ; Python kvar som orakel) | Flytta |
| Runtime-driver | `runtime.py:52-496` | Start/resume, effekter, persistens per transition, deadline, cancel, replay | `swe_native.Machine`, handler- och provider-map, run-store, klocka | Flytta |
| asyncio-dispatch | `runtime_dispatch.py:22-239` | Semantik för handlers/providers, semafor, outputvalidering, single-flight-cache | prompttexter + **renderare** (`:17,153`) | Refaktorera → Flytta |
| Preflight | `runtime_preflight.py:13-78` | Fail-closed resurskontroll | faktiska providers/prompts/cache | Flytta |
| Validering/errors/klocka | `runtime_validate.py:15-49`, `runtime_errors.py:6-28`, `runtime_clock.py:9-22` | JSON-gräns, typade fel, injicerbar tid | — | Flytta |
| Provider-registry | `runtime_dispatch.py:23,35-41`, `runtime_preflight.py:29-55` | Registrering + validering + `cache_params`-konvention | JEV-provider (`providers.py`) | Flytta (protokoll); JEV-implementation stannar |
| Decision-cache | `cache.py:18-51` | Protokoll + nyckel | OverGraph-cache (`jev_cache.py`) | Flytta (kontrakt); implementation stannar |
| Run-store | `run_store.py:15-56` | Durable run/invocation/replay-kontrakt | OverGraph-store (`workflows.py`) | Flytta (kontrakt); implementation stannar |
| Events/observability | Rust `EventKind` (`crates/swe-native/src/events.rs:7-21`) → `machine.events()` (`runtime.py:341,489-495`) → `RunStore.record(events=...)` | Append-only eventlogg per run | event-**konsumtion** (progress/UI/DB) sker i domänen (`research_progress_events`, `models.py:2964`; `ProgressTracker` i `loop_control.py:129+`) | Flytta (eventkontrakt); domänkonsumtion stannar. Notera: ingen generisk Python-event-**sink** finns i dag — endast `RunStore`-parametern; osäkert om det räcker som publikt kontrakt, se `04` |
| Host-scope/katalog | `features.py:15-37` | — | customer/feature-modell + `FEATURE_IDS` | Separera: opak scope till SWE, modell kvar |
| Prompt-rendering | `app/services/prompt_render.py:3-16` (importeras av engine) | — (hostpolicy) | `str.format`-semantik | Injicera; stannar i Socialism |

**Slutsats om gränsen:** engine behöver **fem injektionspunkter** — handlers,
providers, prompts+renderare, beslutscache och run-store — plus `swe_native` som
kärna. I dag är handlers/providers/cache/store redan injicerade; prompts är
delvis injicerade (karta) men renderaren importeras; prompt-*nycklar* och
host-scope är fortfarande hårdkodade.

---

## 7. Vad som stannar i Socialism

Inget av följande ska följa med till SWE-repot. Tabellen är också svar på
"var går gränsen" för `04`/`06`.

| Nuvarande placering (file:line + module) | Ansvar | Beroenden (internal + external) | Domänkoppling (Generisk \| Blandad \| Socialism-specifik) | Rekommenderad ägare (SWE \| Socialism) | Åtgärd (Behåll \| Separera \| Flytta \| Refaktorera) |
| --- | --- | --- | --- | --- | --- |
| `backend/app/services/research/swe_bridge.py:1` | Host-brygga: SWD-loop över research-primitiv; enda produktionsseamen. | Interna: `app.swe.{definition,run_store,runtime,runtime_dispatch}`, `app.services.research.{models,execution,loop_control,evidence_screen,quality_persist}`, `app.config`, `app.observability`. Externa: `asyncio`. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/execution.py:938` (`_run_research_loop`) | Tunn seam som delegerar till bryggan; patchas av wiring-tester. | Interna: lazy import av `swe_bridge`. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/execution.py:1057` (`execute_attempt_research`) | Preludium: lease/claim, plan, evidence set, snapshots; anropar loopen (`:1163`). | Interna: research-domän + DB. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/loop_control.py:54,74,122` (`ResearchWaveConfig`, `wave_config_from_kwargs`, `finish_research_wave`) | En vågs kropp: barrier → quality → assessment → beslut → follow-up/freeze. | Interna: research-domän. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/claims.py:35-145` | Postgres CAS-lease, enqueue, renew, release. | Interna: DB/models. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research_worker.py:166,313` | Worker som claimar och kör `execute_attempt_research`; skickar `lease_lost` (`:179,185,347`). | Interna: DB, research. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/question_attempt_worker.py:73`; `backend/app/services/workspace_research_job.py:93` | Övriga produktionsanropare av `execute_attempt_research`. | Interna: research/DB. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/sufficiency_experiment/loop.py:81-82`; `.../workflow.py:12` | Opt-in complete-EvidenceSet-experiment som också kör på `WorkflowRunner`; bevis att engine är återanvändbar. | Interna: `app.swe.runtime`, research-domän. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/prompt_catalog.py:3537` (`PROMPT_KEY_SET`) | Promptkatalog + promptnycklar (3 565 rader). | Interna: många domänpromptmoduler. | Socialism-specifik | Socialism | Behåll (men engine får inte importera den) |
| `backend/app/services/prompt_render.py:3-16` | Prompttextrendering (hostpolicy). | Interna: inga. | Socialism-specifik | Socialism | Behåll (injiceras i engine) |
| `backend/app/config.py:212-222` (`research_jev_*`) | JEV/research-konfiguration. | Externa: pydantic-settings. | Socialism-specifik | Socialism | Behåll |
| `backend/app/jev/system.py` | JEV System One-klient. | Externa: HTTP. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/research/models.py`, `plan.py`, `planner.py`, `quality*.py`, `assessment.py`, `completeness.py`, `followup.py`, `evidence_screen.py`, `router.py`, `registry.py` | Research-domänmodeller och primitiv. | Interna: DB/OverGraph. | Socialism-specifik | Socialism | Behåll |
| `backend/app/services/overgraph/workflows.py:246`; `backend/app/services/overgraph/jev_cache.py:83` | Konkreta persistens-/cache-adaptrar (se §8). | Externa: `overgraph`, `app.config`. | Blandad (implementerar generiskt kontrakt mot domänlagring) | Socialism | Behåll (separera vid behov via Owner-klient, se §8.3) |
| `backend/app/database/models.py:2032,2150,2180,2369,2399,2964`; `backend/alembic/versions/091_*.py:22`, `092_*.py:21` | SQL-persistens: evidence set, claims, need executions, progress events, migrationer. | Externa: SQLAlchemy/Postgres. | Socialism-specifik | Socialism | Behåll |
| `backend/scripts/benchmark_research_swe.py`, `benchmark_research_swe_v2.py` | Domänbenchmark för cutover (fake/offline). | Interna: research + `app.swe`. | Socialism-specifik | Socialism | Behåll |

---

## 8. Persistens: OverGraph RunStore, JEV-cache och SQL-claims

### 8.1 Generiskt vs Socialism-lagring

| Fråga | Svar | Bevis |
| --- | --- | --- |
| Vad är det generiska run-kontraktet? | `RunRecord` (run_id, definition_sha256, status, input, output, error, tider, last_seq) + `InvocationRecord` (invocation_id, node_id, ok, value, error) + `RunStore.record/load_run/replay_results/events`. | `run_store.py:15-56` |
| Vad lagrar OverGraph-implementationen? | En nod per run (`WorkflowRun`, props `:128-144`), en nod per event (`WorkflowRunEvent`, `:147-163`), en nod per invocation (`WorkflowInvocation`, `:166-181`); labels + host-scope (`:36-38`, `:74-75`). | `workflows.py:36-38,128-181` |
| Är varje transition atomisk? | Ja: run + nya events + invocation skrivs i **en** `begin_write_txn` (`workflows.py:94-110`, `record` `:264-275`), `wal_sync_mode="immediate"` (`:232-242`). | `workflows.py:94-110,232-242,264-275` |
| Vad är Socialism-lagring? | SQL-tabellerna `execution_research_claims` (lease), `research_need_executions`, `evidence_sets`/items, `research_claims`, `research_progress_events`. Dessa är **inte** engine-runstate. | `models.py:2032,2150,2180,2369,2399,2964`; `alembic/versions/091_execution_research_claims.py:22`; `092_research_progress_events.py:21` |
| Vem äger durable runs i dag? | Ingen i produktion: `swe_bridge` tar emot valfritt `run_store` men produktionsseamen skapar inget (`swe_bridge.py:24-25,118`). Endast benchmarkar (`benchmark_research_swe.py:550`, `..._v2.py:705`) och tester (`test_swe_persistence.py:117-118`, `test_research_swe/test_wiring.py:111-114`) öppnar en store. | E10 |
| Vem äger JEV-cachen i dag? | Ingen i produktion: `JevDecisionCache` instansieras bara i `test_swe_provider.py:215,259,305,319`; `make_jev_provider` bara i `test_swe_provider.py:337,358`. | E10 |
| Var kommer katalogroten ifrån? | `OVERGRAPH_DIR` via `settings.overgraph_dir` (`config.py:140`; `jev_cache.py:106-113`); workflow-store-roten skickas av anroparen. | `jev_cache.py:106-113` |

Slutsats: **`RunStore`/`DecisionCache` är generiska kontrakt**; **OverGraph är en
Socialism-adapter** precis som SQL-claims är Socialism-lagring. Run-historik i
OverGraph är alltså inte samma sak som research-attemptets durability (Postgres
claims/evidence) — de två får inte blandas ihop vid extraktion.

### 8.2 JEV-cache — exakt identitet

- L1: process-lokal FIFO, kapacitet 256 (`jev_cache.py:29,98,160-163`).
- L2: OverGraph-katalog `<OVERGRAPH_DIR>/jev` med `wal_sync_mode="immediate"`
  (`jev_cache.py:199-208`).
- Single-flight: samtidiga identiska nycklar delar en provider-call
  (`jev_cache.py:132-152`).
- Nyckeln ägs av engine: `decision_cache_key` importeras/re-exporteras
  (`jev_cache.py:24,26`), består av provider, prompt_key, prompt, input,
  choices, params (`cache.py:33-51`).
- Bedömning: kontraktet är generiskt; själva ordet "jev" och
  `settings.overgraph_dir` är Socialism. Adaptern stannar.

### 8.3 Risk: OverGraph Owner-regeln

Repo-regeln säger att varje aktiv OverGraph-katalog har **exakt en auktoritativ
Owner**, och att backend/workers inte får öppna en Owner-ägd katalog direkt
(`AGENTS.md`, avsnitt "Overgraph ownership"). Båda SWE-adaptrarna öppnar katalog
direkt i processen:

- `workflows.py:232-242` → `OverGraph.open(..., wal_sync_mode="immediate")`.
- `jev_cache.py:199-208` → `OverGraph.open(...)`.

I dag är detta inte produktionskopplat (E10), men **om/när durable SWE-runs
aktiveras i produktion** måste antingen (a) run-store/cache köras inuti Ownern,
eller (b) bli Owner-klienter över Owner-protokollet. Att flytta `RunStore`
kontraktet till SWE-repot är ofarligt; att flytta **OverGraph-implementationen**
dit vore fel både för domänkoppling och Owner-regel. Markera som **osäkert** om
Owner-arkitekturen är tänkt att gälla även SWE-kataloger — repo-regeln säger
"varje aktiv OverGraph-katalog", vilket inkluderar dem, men ingen
produktionskoppling finns att verifiera mot.

---

## 9. Research-integrationen i detalj

### 9.1 Produktionskedjan (endast vägar som finns i `app/`)

```
POST /execution/attempts/{id}/research
  → research_worker.run_research_claim              research_worker.py:166
  → _execute_claimed_research                       research_worker.py:313
  → execute_attempt_research                        execution.py:1057
  → _run_research_loop (patchbar seam)              execution.py:938-941
  → swe_bridge.run_research_loop_via_swe            swe_bridge.py:298-303
  → SweResearchLoop.run                             swe_bridge.py:149-157
  → SWD: run_wave → map(execute_need) → finish_wave → decision → run_wave/end
                                                    swe_bridge.py:70-106
```

- Loopen är fem noder + `end`: `run_wave` (task), `needs` (map, concurrency
  64 — `:88`), `execute_need` (task), `finish_wave` (task), `route`
  (expression decision) och `done` (end) (`swe_bridge.py:82-104`).
  `_WORKFLOW_LIMITS` = max_steps 500 / max_depth 4 / timeout 1800 s (`:60`).
- Handlers: `research.run_wave` (`:144`), `research.execute_need` (`:145`),
  `research.finish_wave` (`:146`) i dict `:143-147`; alla kroppar anropar oförändrade
  research-primitiv (`:159-239`). Detta är själva beviset för att SWE äger
  loopformen och research äger beteendet.
- Cancel/lease: `lease_lost` → `WorkflowResources(cancel_event=...)`
  (`swe_bridge.py:149-157`, `:255-257`); ett `cancelled`-resultat re-raisas som
  `asyncio.CancelledError` (`:290-291`) för att matcha write-fence-semantiken.
- Durable runs: valfritt store (`build_loop(..., run_store=...)`
  `swe_bridge.py:242-266`) — **inte** produktionskopplat (`:24-25`).
- Resultat: `completed` krävs, annars `ResearchExecutionError` (`:292-295`).

### 9.2 Vad bryggan importerar (gränssnittet mot SWE)

`swe_bridge.py:38-42` importerar `CompiledDefinition`/`compile_definition`,
`RunStore`, `RunResult`/`WorkflowResources`/`WorkflowRunner`, `Handler` samt
`ResearchNeed`/`ResearchPlan`. Det är exakt den publika SWE-yta en host
behöver — bra utgångspunkt för `04-public-contracts.md`.

### 9.3 Researcher-relaterad observability

- SWE-run events skapas i Rust (`EventKind`,
  `crates/swe-native/src/events.rs:7-21`) och exponeras via `Machine.events()`
  (`runtime.py:341,494`). De persisteras bara om ett `RunStore` finns
  (`run_store.py:45-51`; `workflows.py:147-163`).
- Research-progress (`research_progress_events`) är **domän** och skrivs av
  wave-kroppen (`loop_control.py:129+`, modell `models.py:2964-3002`); bryggan
  använder bara `log_context` (`swe_bridge.py:168,194,233`). Ingen generisk
  Python-event-sink finns — det är en lucka i det publika SWE-kontraktet, inte
  i research-integrationen.

---

## 10. Tester, fixtures och benchmarks

### 10.1 Testfilerna (exakta)

"Antal" är statiska `def test_`-räkningar (E7); inga `parametrize` hittades i
`test_swe_*.py`/`wiring.py` (E8), så antalet testfunktioner är också antalet
testfall där. Alla filer ligger under `backend/tests/`.

| Testfil | Antal | Vad den låser | Typ | Kräver `swe_native` | Körs offline | CI-jobb (i dag) |
| --- | --- | --- | --- | --- | --- | --- |
| `test_swe_canonicalize.py` | 9 | Kanoniska bytes/SHA-256: sortering, NFC, CRLF→LF, int-float, NaN, bool≠int, idempotens. | Generiskt kontrakt | Nej (ren Python) | Ja | `swe-runtime` (via `test_swe_*`) |
| `test_swe_definition.py` | 18 | Schema, version, handler/provider-registry, prompt_key, graf, joins, fryst dokument, hash, YAML=JSON. | Blandat: mest generiskt; `test_example_uses_catalog_prompt_key`/`test_unknown_prompt_key_is_rejected` låser promptkatalogkopplingen (`:188-210`). | Nej (ren Python) | Ja | `swe-runtime` |
| `test_swe_expression.py` | 13 | Typad expression-semantik: null/bool≠number, default, `in`, nested bool, fryst kontext. | Generiskt kontrakt | Nej | Ja | `swe-runtime` |
| `test_swe_features.py` | 5 | Host-context: katalogisolering per kund/feature, path traversal, **`FEATURE_IDS`-listan som spec** (`:51-58`). | Socialism-specifikt (host) | Nej | Ja | `swe-runtime` |
| `test_swe_joins.py` | 10 | Join-äggarskap, branch-escape, delade noder, nested fork, joinless map. | Generiskt kontrakt | Nej | Ja | `swe-runtime` |
| `test_swe_persistence.py` | 11 | OverGraph run-store: atomiska transitions, failed invocation, idempotent replay, rollback, crash/resume, terminal run, annan definition, katalogisolering, timeout, starttid. | Generiskt kontrakt + Socialism-adapter | Ja (`importorskip` `:12`) | Ja (tmp_path, ingen nätverks-IO) | `swe-runtime` |
| `test_swe_provider.py` | 13 | Provider-decision end-to-end, preflight, choices, fel, deadline, exact-cache hit/miss/key/single-flight/L2, JEV-mappning. | Blandat: mest generiskt; JEV-testerna (`:331-369`) är Socialism | Ja (`:11`) | Ja (`_FakeJev`, tmp_path) | `swe-runtime` |
| `test_swe_runtime_decision.py` | 2 | task → expression decision → end (true/false). | Generiskt kontrakt | Ja (`:7`) | Ja | `swe-runtime` |
| `test_swe_runtime_errors.py` | 12 | Preflight, icke-JSON-output, sibling-cancel, cancel utan reroute, timeout, hängande handler, läckta tasks, ignore-cancel, max_depth/max_steps, output_schema, duplicate completion. | Generiskt kontrakt | Ja (`:9`) | Ja | `swe-runtime` |
| `test_swe_runtime_fork.py` | 4 | Parallell fork/join barrier, run-isolering, deterministiskt fixtur, nested fork/loop. | Generiskt kontrakt | Ja (`:9`) | Ja | `swe-runtime` |
| `test_swe_runtime_map.py` | 3 | map 0/1/100 items + stabil ordning. | Generiskt kontrakt | Ja (`:7`) | Ja | `swe-runtime` |
| `test_swe_runtime_parity.py` | 6 | Rust/Python-paritet: canonical bytes, YAML/JSON-SHA, expressions, NaN/kollisioner, fel, att event-loopen inte blockeras. | Generiskt kontrakt (parity) | Ja (`:7`, `require_native` `:12`) | Ja | `swe-runtime` |
| `test_swe_runtime_preflight.py` | 5 | `wait`/`subworkflow`/`retry`/`cache_policy`-avvisning, provider/prompt-krav. | Generiskt kontrakt | Ja (`:7`) | Ja | `swe-runtime` |
| `test_research_swe/test_wiring.py` | 4 | Cutover-seamen: `lease_lost` når loopen, förlorad lease → `CancelledError` utan failed Attempt, cancelled SWE-run persisteras, in-flight handler skrivs inte. | Research-regression | Ja (`:18`) | Ja (in-memory SQLite/StaticPool, `:36-48`) | **Ingen** — se §10.4 |
| `test_sufficiency_experiment_reuse.py` | 14 | Att sufficiency-experimentet körs via `WorkflowRunner` (SWE-events i rapporten) och reuse-beteende. | Research-regression (SWE-konsument nr 2) | Ja (modulmarkering `swe_runtime`; `importorskip` i 3 tester) | Ja (scriptad JEV) | **Ingen** — se §10.4 |
| **Summa** | **129** | | | | | |

### 10.2 Fixtures

- `backend/tests/swe/research_parallel.yaml` + `.json` — **research-färgade**
  men semantiskt generiska: fork/join → expression decision → provider-decision
  (`prompt_key: research.assessment.user`, provider `jev`,
  choices sufficient/insufficient/uncertain). Se `research_parallel.yaml:8-69`,
  `swe/helpers.py:8-19`.
- `backend/tests/swe/runtime_parallel.yaml`, `helpers.py`, `runtime_helpers.py`
  — generiska runtime-fixtures (`runtime_helpers.py:11,22-37`).
- Används av: `test_swe_definition.py`, `test_swe_joins.py`,
  `test_swe_runtime_fork.py`, `test_swe_runtime_preflight.py`,
  `test_swe_runtime_parity.py` (E9). Ett av dem använder redan neutrala
  `demo.*`-namn (`test_swe_runtime_fork.py:140-156`).
  Rekommendation: gör `research_parallel.*` till ett generiskt
  `provider_parallel.*` med påhittade prompt-nycklar när prompt-valideringen
  inverterats; då blir de fem "rena" testfilerna helt domänfria.
- `test_swe_definition.py:188-210` binder fixturerna till promptkatalogen; byts
  samtidigt som §4.2 punkt 1.

### 10.3 Benchmarks

| Fil | Vad den mäter | Domän | Körs offline |
| --- | --- | --- | --- |
| `backend/scripts/benchmark_swe_runtime.py` | Deterministiska transitions (10 000 steg) + async fan-out (1 000 items), events, max RSS; "No LLM or network" (`:1`). | Generisk | Ja |
| `backend/scripts/benchmark_research_swe.py` | Cutover-benchmark, arm baseline vs swe_a/swe_b, fake mode med hårda gates (0 LLM, inga nätverksförsök) — `:1-17,213`. | Socialism | Ja i fake mode |
| `backend/scripts/benchmark_research_swe_v2.py` | Observability-instrumentering/live-mätning (v2). | Socialism | Fake-läge offline; live kräver nätverk (ej verifierat här) |

`benchmark_swe_runtime.py` är det enda generiska benchmarket och bör följa med
SWE-repot. `test_benchmark_research_swe_v2.py` (ej SWE-relaterad i övrigt) finns
också i testsviten men rör harnessen, inte engine.

### 10.4 CI-täckning — observerad lucka

- `backend`-jobbet kör `pytest -m "not smoke and not research_reuse and not
  swe_runtime"` (`.github/workflows/ci.yml:141-147`).
- `swe-runtime`-jobbet kör **endast** `pytest tests/test_swe_*.py -m "not
  smoke"` (`.github/workflows/ci.yml:213-214`).
- Därför körs varken `tests/test_research_swe/test_wiring.py` eller
  `tests/test_sufficiency_experiment_reuse.py` av något CI-jobb: båda är
  modulmärkta `swe_runtime` (`test_wiring.py:30-33`,
  `test_sufficiency_experiment_reuse.py:47`) men matchar inte
  `tests/test_swe_*.py`-sökvägen. Endast en enda CI-workflow finns
  (`.github/workflows/ci.yml`; E11).
- `research-reuse`-jobbet bygger `swe_native` (`.github/workflows/ci.yml:168-169`)
  men `tests/research_reuse` har **noll** referenser till `app.swe`/`swe_native`
  (E12) — bygget är sannolikt en historisk rest (låg risk, men bör städas vid
  extraktion).
- Slutsats: en fristående SWE-repo måste äga en egen CI-matris som (a) kör
  `test_swe_*` med extension, (b) kör de research-märkta konsumenttesterna i
  Socialism-repot, (c) inte är beroende av backend-jobbets markerexpression.

---

## 11. Build och CI

### 11.1 Hur `swe_native` byggs

| Steg | Detalj | Referens |
| --- | --- | --- |
| Rust-kärna | crate `swe-native`, lib `swe_native`, `crate-type = ["cdylib","rlib"]`, rust 1.83, edition 2021; endast `indexmap`, `serde`, `serde_json`, `sha2`, `thiserror`, `unicode-normalization` + valfri `pyo3 = 0.24.2`. | `crates/swe-native/Cargo.toml:1-32`; `rust-toolchain.toml` |
| Python-bindning | maturin-build-backend, `module-name = "swe_native"`, feature `extension-module`; kräver Python ≥3.12. | `crates/swe-native/pyproject.toml:1-3,9,15-18` |
| Lokal build | `make swe-native` → `cd backend && uv run maturin develop --manifest-path ../crates/swe-native/Cargo.toml`. | `Makefile:161-162` |
| SWE-testkörning | `make test-swe` → `cargo test` + `pytest tests/test_swe_*.py`. | `Makefile:164-166` |
| Test-backend | `make test-backend` **förutsätter** `swe-native` (målberoende `Makefile:156`). | `Makefile:156-159` |
| Beroende i Python-miljön | `maturin>=1.8,<2` i dev-gruppen; `swe_native` finns **inte** i `uv.lock` (installeras via `maturin develop`, inte som PyPI-beroende). | `backend/pyproject.toml:78-84`; E13 |
| Opt-in-markering | `swe_runtime` = "requires the compiled swe_native PyO3 extension". | `backend/pyproject.toml:96` |
| Lokal status i denna worktree | Extensionen är **inte byggd** (ingen `backend/.venv`, inga `swe_native*`-filer under `backend/`), så pytest-collection kördes medvetet inte. | E13 |

### 11.2 CI-jobb som rör SWE

| Jobb | Vad det gör | SWE-beroende | Rad |
| --- | --- | --- | --- |
| `changes` | Path-filter: `backend/*` eller `integrations/*` eller `data/*` eller `crates/*` ⇒ backend=true; `crates/swe-gym/*` ⇒ swe_gym=true. | Ja (crates) | `.github/workflows/ci.yml:19-88` |
| `swe-gym` | `cargo fmt --check` + `cargo test` i `crates/swe-gym`. | Ja (SWE-gym) | `:90-110` |
| `backend` | Ruff + maintainability + `pytest` (4 shards, exkluderar `swe_runtime`); bygger `swe_native` innan. | Delvis (bygge, men SWE-tester exkluderas) | `:112-147` |
| `research-reuse` | Bygger `swe_native`, kör `tests/research_reuse -m research_reuse`, laddar upp junit-xml. | Bygge ja; tester nej (E12) | `:149-182` |
| `swe-runtime` | `cargo fmt`/`clippy -D warnings`/`cargo test` + `maturin develop` + `pytest tests/test_swe_*.py -m "not smoke"`. | **Ja, huvudjobbet** | `:185-214` |
| `ci` | Aggregerar alla jobb; kräver success/skipped. | Ja | `:347-375` |

### 11.3 Vad ett standalone-repo behöver (härlett ur ovanstående)

1. **Rust workspace + `rust-toolchain.toml` (1.83)** och `pyo3 0.24.2`-pinnen;
   `cargo fmt/clippy -D warnings/test` som eget jobb (dagens `swe-runtime`
   `:205-210`).
2. **Egen Python-paketering** (`python/swe/...` enligt `06`), inte
   `opinionssimulator-backend`-projektet (`backend/pyproject.toml:1-2`).
   Endast `jsonschema` + `pyyaml` som runtime-beroenden för engine-delen.
3. **Wheel-build av `swe_native`** (maturin) och en versionspinnad
   konsumtionsväg; i dag installeras extensionen bara med `maturin develop`
   (E13), vilket är en dev-only-väg.
4. **Egen `conftest`**: backendens `tests/conftest.py:1-50+` sätter
   LLM/DB/Supabase-env och importerar `app.main`; engine-testerna ska inte
   behöva den. Fem av tretton `test_swe_*`-filer är redan rena Python-tester
   (E7) och kan köras i en minimal harness.
5. **Generiska fixtures**: ersätt `research_parallel.*`/`research.assessment.user`
   med neutrala prompts/nycklar (§10.2).
6. **Inverterade beroenden** innan flytt: `prompt_keys`-injektion,
   prompt-renderare, JEV-provider ut, `FEATURE_IDS`/host-context ut (§4.2, §5).
7. **CI-matris** som kör `test_swe_*` (extension), parity-testerna och de
   research-märkta konsumenttesterna på rätt ställe; ta bort det onödiga
   extensionbygget i `research-reuse` (§10.4).
8. **Python 3.12 + pytest 9.1/pytest-asyncio 1.4 + pytest-split**-pinnar om
   shardning ska behållas (`backend/pyproject.toml:78-84,87-96`).
9. **Inga `overgraph`/`openai`/`httpx`/`sqlalchemy`-beroenden i engine-paketet**
   — de tillhör adaptrarna i Socialism (§8).
10. **Dokumentation**: SWD 1.0-spec och runtime/provider/store-kontrakt
    (`docs/specs/swe-swd-1.0.md`, `swe-runtime.md`, `swe-provider.md`,
    `swe-overgraph.md`) följer med eller refereras; `docs/specs/swe-cutover.md`
    är Socialism-historia och stannar.

---

## 12. Topp 5 kopplingsrisker (för extraktion)

1. **Promptkatalogen blockerar kompilering (högst risk).**
   `definition.py:13,152-163` gör `PROMPT_KEY_SET` (3 565 rader) till ett
   kompileringstidskrav för alla provider-decisions. Utan inversion kan
   `python/swe` inte importeras utan Socialism. Åtgärd: `prompt_keys`-parameter
   + host-injektion (samma mönster som `handlers`/`providers`,
   `definition.py:45-46`).
2. **Prompt-rendering ligger i dispatch.** `runtime_dispatch.py:17,153`
   importerar `app.services.prompt_render`. Engine måste injicera renderaren;
   annars följer en hostpolicy med ut i SWE-repot.
3. **JEV-providern ligger i engine-paketet.** `providers.py:15-22` drar in
   `app.config`, `app.jev.system` och `app.services.research.fast_controller`.
   Flytta modulen till Socialism; behåll bara `Provider`-protokollet.
4. **Host-/feature-modellen ligger i engine.** `schema.py:16-18` +
   `features.py:28,35-37` kodar Socialism-produktens fem features och
   OverGraph-katalogvägen. Ersätt med opak scope-nyckel; flytta `FEATURE_IDS`
   och `WorkflowHostContext` till host. Testet `test_swe_features.py:51-58`
   måste följa med och bli ett host-test.
5. **Test-/CI-infrastrukturen är sammanvävd med backend.** `conftest.py`
   importerar hela appen; `backend`-jobbet exkluderar `swe_runtime`;
   `swe-runtime`-jobbet missar de två research-märkta SWE-konsumenttesterna
   (`ci.yml:141-147,213-214`). En standalone-repo måste äga sin egen harness
   och sina egna markerexpressioner, annars tappas regressionstäckningen vid
   flytten.

**Ytterligare (medelrisk):** OverGraph Owner-regeln mot `workflows.py:232-242`
och `jev_cache.py:199-208` (§8.3); Python/Rust-canonicalize-paritet där Rust
blir normativ (`canonicalize.py:3-5`, `test_swe_runtime_parity.py`); att
`make_jev_provider`/`JevDecisionCache`/`WorkflowRunStore` inte är
produktionskopplade (kontrakten är testade men inte produktionsbevisade, E10).

---

## 13. Evidence — kommandon och resultat

Alla kommandon kördes i `/Users/erikfremred/swe-standalone` (HEAD
`666eccb0cc61f4a5e15e95bc1e1edfbdf75b32e1`, branch
`feat/swe-standalone-investigation`). Inga skrivningar gjordes utanför detta
dokument. Ingen build och ingen testsvit kördes (reglerna för uppdraget).

**E1 — filinventering.** `ls -1 backend/app/swe/ | wc -l` → `23`;
`ls backend/app/swe/*.py | wc -l` → `22`; `ls backend/app/swe/*.json` → `1`;
`cat backend/app/swe/*.py | wc -l` → `2322`; `find backend/app/swe -maxdepth 2
-type d` → endast `backend/app/swe`. Slutsats: 22 Python-moduler + 1 JSON-schema
= 23 filer (uppdragsbeskrivningens "24 moduler" stämmer inte med trädet).

**E2 — `app.swe` → domänimporter.**
`grep -rnE "from app\.(config|jev|services)" backend/app/swe/` →
5 träffar: `providers.py:15`, `providers.py:16`, `providers.py:17`,
`definition.py:13`, `runtime_dispatch.py:17`.

**E3 — `app.swe` → OverGraph.** `grep -rn "overgraph" backend/app/swe/` →
3 träffar, alla docstrings (`cache.py:4`, `run_store.py:4`, `run_store.py:43`);
0 import-rader.

**E4 — `app.services` → `app.swe`.**
`grep -rn "from app\.swe" backend/app --include=*.py | grep -v "^backend/app/swe/"`
→ 10 rader i 6 filer (`swe_bridge.py:38-41`, `sufficiency_experiment/loop.py:81-82`,
`sufficiency_experiment/workflow.py:12`, `overgraph/workflows.py:32-33`,
`overgraph/jev_cache.py:24`).

**E5 — `swe_native`-beroende.** `grep -rn "swe_native" backend/app` → 5 träffar,
alla i `runtime.py` (`:75,76,77,116,118`; importblocket `:74-80`); `grep -rln "swe_native" backend/tests | wc -l`
→ `10` testfiler.

**E6 — ingen returcykel i promptlagret.** `grep -n "app.swe"
backend/app/services/prompt_catalog.py backend/app/services/prompt_render.py` →
0 träffar.

**E7 — testinventering.** `for f in backend/tests/test_swe_*.py
backend/tests/test_research_swe/test_wiring.py
backend/tests/test_sufficiency_experiment_reuse.py; do grep -c "^def test_\|^async
def test_" "$f"; done` → 9, 18, 13, 5, 10, 11, 13, 2, 12, 4, 3, 6, 5, 4, 14
(summa **129**). `grep -L "importorskip" backend/tests/test_swe_*.py` → de fem
rena: canonicalize, definition, expression, features, joins. `grep -rn
"parametrize" backend/tests/test_swe_*.py backend/tests/test_research_swe/test_wiring.py`
→ 0 träffar.

**E8 — markeringar.** `grep -rn "swe_runtime" backend/tests --include=*.py |
wc -l` → `10` träffar; `grep -rln "mark.swe_runtime" backend/tests | wc -l` →
`10` filer. Konfiguration: `backend/pyproject.toml:96`.

**E9 — fixturkoppling.** `grep -n "research\.\|jev\|source_type"
backend/tests/swe/research_parallel.json backend/tests/test_swe_runtime_*.py` →
`research.search_contracts`/`research.search_legal_sources`/`research.assessment.user`
i fixturen; `test_swe_runtime_fork.py:140-156` använder redan neutrala
`demo.*`-namn.

**E10 — produktionskoppling av adaptrar.**
`grep -rn "make_jev_provider\|JevDecisionCache\|WorkflowRunStore" backend/app` →
endast definitioner (`providers.py:27`, `jev_cache.py:26,28,83`,
`workflows.py:246,254`); inga anrop i `backend/app`. `grep -rn
"make_jev_provider" backend` → anrop endast i `tests/test_swe_provider.py:337,358`.
`grep -rn "WorkflowRunStore" backend` → anrop i
`tests/test_swe_persistence.py:117-118`, `tests/test_research_swe/test_wiring.py:111`,
`scripts/benchmark_research_swe.py:550`, `..._v2.py:705`.
`grep -rn "JevDecisionCache" backend` → anrop endast i
`tests/test_swe_provider.py:215,259,305,319`.

**E11 — CI-jobb.** `grep -n "swe-runtime\|test_swe_\|swe_native\|swe_runtime"
.github/workflows/ci.yml` → `:135-136`, `:141-147`, `:168-169`, `:185-186`,
`:205-210`, `:211-212`, `:213-214`; enda workflowfilen: `ls .github/workflows/`
→ `ci.yml`.

**E12 — research_reuse är inte SWE.** `grep -rn "app\.swe\|swe_native"
backend/tests/research_reuse/` → 0 träffar; `grep -rn "swe_runtime"
backend/tests/research_reuse/` → 0 träffar.

**E13 — build/CI-grund.** `nl -ba Makefile | sed -n '154,166p'` → `test-backend`
`:156`, `swe-native`:161-162, `test-swe`:164-166. `nl -ba
crates/swe-native/pyproject.toml` → maturin `:1-3`, module-name `:17`.
`grep -n "maturin" backend/pyproject.toml backend/uv.lock` → dev-dep
`pyproject.toml:84`; `maturin` finns i `uv.lock:1473+` men **`swe-native` finns
inte som paket i `uv.lock`**. `ls -d backend/.venv` → saknas;
`find backend -name "swe_native*"` → 0 filer. Därför **skippades** pytest-collection
(`pytest tests/test_swe_*.py --collect-only` kräver byggd extension; uppdraget
förbjöd bygge).

**E14 — gränssnittsrader i bryggan.** `grep -n "run_store"
backend/app/services/research/swe_bridge.py` → `:39,118,132,155,246,263`;
`grep -n "HANDLER_NAMES\|_workflow(" ...` → `:47-49`, `:70-106`; filläsning
bekräftade handlers-dicten `:143-147`, `build_loop` `:242-266` och
runner-funktionerna `:286-314`.

### 13.1 Osäkerhetsmarkeringar

- **Testantalsräkningen** är statisk (`def test_`), inte pytest-collected;
  parametrize-sökningen var begränsad till `test_swe_*.py` och `wiring.py`
  (sufficiency-filen kontrollerades inte för parametrize). Faktiskt antal
  testnoder kan vara högre.
- **"24 moduler"** i uppdraget stämmer inte med trädet: 23 filer (22 `.py` + 1
  `.json`). Möjligen avsågs 23 eller så räknades `swd_v1.schema.json` +
  `__init__.py` annorlunda.
- **CI-luckan (§10.4)** är härledd ur path-/marker-uttryck i enda
  workflowfilen; det kan vara avsiktligt att de två research-märkta
  konsumenttesterna bara körs lokalt. Ingen anteckning om det hittades.
- **OverGraph Owner-regelns tillämplighet på SWE-kataloger** (§8.3) är inte
  verifierad mot en produktionskoppling; repo-regeln säger "varje aktiv
  OverGraph-katalog", men ingen sådan koppling finns i dag.
- **`benchmark_research_swe_v2.py` live-läge** kan kräva nätverk; det
  verifierades inte (uppdraget förbjuder nätverk). Fake-läget är offline enligt
  skriptets docstring.
- **Klassningen av `features.py`** som Socialism-ägd är en bedömning: modulen är
  generisk som mönster (trusted host context) men innehåller Socialism-begrepp
  (customer/feature). `04`/`06` kan välja att behålla en generisk `Scope`-typ i
  SWE; slutsatsen "feature-värdena får inte vara engine-konstanter" gäller
  oavsett.
- **Rust/Python-paritetens slutliga ägarskap** (`canonicalize.py:3-5`: Rust ska
  bli normativ) är en framtida fråga som `01`/`04` äger; här noteras bara att
  Python-modulen i dag är orakel och därför måste följa med tills pariteten är
  etablerad.

---

## 14. Slutsats för Fas A

- **Gränsen går vid fem injektionspunkter:** handlers, providers,
  prompts+renderare, beslutscache, run-store. Engine-koden för dem finns redan i
  `app/swe` (utom renderaren); två av fem är delvis domänkopplade.
- **17 filer är flyttbara oförändrat till SWE** (16 `.py` + JSON-schemat);
  `providers.py` flyttar oförändrad till Socialism. **5 filer kräver en liten
  beroendeinversion** (`definition`, `runtime_dispatch`, `schema`, `__init__`,
  `features`/host-context).
- **Research bryggan är redan rätt konstruerad** och är den bästa specifikationen
  av den publika SWE-ytan (`swe_bridge.py:38-41`).
- **Persistens är det minst mogna området:** kontrakten är generiska men
  implementationerna är OverGraph-specifika, Owner-regeln är oprövad för SWE och
  ingen av dem är produktionskopplad. En standalone-repo ska äga kontrakten,
  inte adaptrarna.
- **Nästa steg (Fas C/F):** läs `04-public-contracts.md` för kontraktsstatus och
  `06-extraction-plan.md` för målstrukturen; denna inventering ger fil:rad-bevis
  för varje flytt/refaktorering som planen behöver.
