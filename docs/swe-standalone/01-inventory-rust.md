# 01 — Rust-inventering: `swe-native` och `swe-gym`

**Status:** Inventering klar (Fas A). Underlag för beslut om vad som är SWE, vad som är Socialism och vad som är experiment.
**Worktree:** `/Users/erikfremred/swe-standalone`, branch `feat/swe-standalone-investigation`, baserad på `origin/main` `666eccb0`.
**Metod:** Läsning av all Rust-kod, manifest, tester, exempel, verktyg och fixtures; två offline-testkörningar som baseline; grep-baserade mått. Inga filer utanför denna leverabel har ändrats. Alla siffror i dokumentet är uppmätta i denna worktree om inget annat anges (se §18 Evidence).
**Läsare:** någon som inte känner till Socialism. Därför förklaras domänbegrepp första gången de används.

---

## 0. Begrepp och klassificeringsregel

| Begrepp | Betydelse i detta dokument |
| --- | --- |
| **SWE** | "Socialism Workflow Engine" — den generiska in-memory-exekveringskärnan för SWD 1.0 (JSON-workflows med `task`, `decision`, `fork`, `join`, `map`, `end`). I Rust: `crates/swe-native`. |
| **SWD 1.0** | Workflow-definitionsformatet (version `1.0`) som kärnan tolkar. Kontrakt: `docs/specs/swe-swd-1.0.md`. |
| **Socialism** | Produktrepot/produkten: politisk budskapssimulering och due diligence; dess research-domän granskar juridiska avtal och andra dokument. Allt som kräver produktens domänbegrepp hör hit. |
| **JEV** | Extern LLM-baserad klassificeringstjänst som research-domänen anropar ("finns evidens i denna chunk?"). Domänspecifik integration, inte en SWE-förmåga. |
| **GLiNER2** | Span-/entitetsextraktionsmodell som används i en legaldomän-utvärdering (finns bara i `swe-gym/tools` och `swe-gym/benchmarks`, inte i `swe-gym/src`). |
| **Chunk / evidence / coverage** | Research-domänens modell: ett dokument delas i chunks; en fråga har ett facit som är en mängd evidens-chunks; "coverage" = hur stor del av facit som hittats. Detta är **inte** en generisk SWE-förmåga. |
| **Sweycoin** | Intern kostnadsenhet i gym-experimentet (tusendelar, heltal). En generisk budget-/kostnadsmekanik, men namnet är experimentspecifikt. |
| **Arm** | En strategi i en A/B-jämförelse (t.ex. "sekventiell prioritet" vs "parallell med lika budget"). |

**Klassificeringsregeln (uppdragets regel, tillämpad rakt av):**

> En förmåga hör till SWE endast när den kan beskrivas, testas och användas **utan** Socialisms domänbegrepp.

Etiketterna som används genomgående:

| Etikett | Innebörd |
| --- | --- |
| **Generisk** | Kan beskrivas, testas och köras utan Socialism/JEV/legal/chunk-begrepp. |
| **Blandad** | Innehåller både en generisk kärna och domänspecifika typer/vokabulär; kräver uppdelning för att bli generisk. |
| **Socialism-specifik** | Kräver Socialisms domänbegrepp (legal avtalsgranskning, JEV, svenska avtalstyper, uppsägningstider, chunk-evidens). |

| Ägaretikett | Innebörd |
| --- | --- |
| **SWE** | Hör hemma i en fristående SWE-kärna (generisk förmåga). |
| **Socialism** | Ska stanna i produkten/legaldomänen. |
| **Experiment** | Experiment/scaffolding som varken är SWE-kärna eller produktionsdomän; kan arkiveras eller flyttas till experimentrepo. |

| Åtgärd | Innebörd |
| --- | --- |
| **Behåll** | Ingen ändring behövs för uppdelningen. |
| **Separera** | Generisk del måste brytas ut från blandad/domänspecifik fil. |
| **Flytta** | Filen hör hemma i en annan ägare (SWE eller Socialism). |
| **Refaktorera** | Beteendet är rätt men beroenden/typer måste neutraliseras innan flytt. |

---

## 1. Sammanfattning

1. **`crates/swe-native` är helt igenom generisk.** 17 källfiler, 3 804 rader källkod + 478 rader integrationstest, 30 gröna tester offline. Kärnan har inga beroenden till JEV, OverGraph, research, legal eller HTTP. Domänord förekommer bara som döda strängar i testfixtures (`prompt_key: "research.assessment.user"`, provider `"jev"`), inte som kodberoende (`crates/swe-native/src/machine/mod.rs:220-230`, `crates/swe-native/tests/machine.rs:188-208`).
2. **`crates/swe-gym` har en generisk kärna men är till största delen domänbunden.** Filnivå: **3 generiska, 16 blandade, 2 socialism-specifika** av 21 källfiler. Förmågenivå är bilden viktigare: *ledger*, *metered driver*, *benchmark-runner*, *replay/frozen providers*, *arm-interface* och *kostnadskalibrering* är generiska förmågor; själva frågemodellen (chunks/coverage/fynd/inget), den frysta legala bänken och operationsgrafen (uppsägningstider) är domän.
3. **Den generiska kärnan i gymmet är inte renodlad.** Generiska moduler importerar domänmoduler: `provider.rs` → `strategy::FakeCorpus`, `dataset.rs` → `real::RealEnv`, `bench.rs` → `strategy::Question`. Det är den viktigaste "wrong direction"-risk som måste lösas innan något kan lyftas ut (§8).
4. **Inga cykler finns** i någon av cratarna (verifierat med skript, §8). Beroenderiktningen är crate-nivå korrekt: `swe-gym → swe-native`, aldrig tvärtom; backend importerar `swe_native` som kompilerad PyO3-modul, aldrig `swe_gym`. Det finns ingen `Cargo.toml`-workspace på repo-roten — tre oberoende byggen med var sin lockfil.
5. **Legal-/JEV-materialet är stort och får inte följa med.** 224 committed benchmark-filer (10,5 MB git-blobs, 11 MB i working tree), 45 Python-verktyg och 15 nätverksgated examples är legal-/JEV-/GLiNER2-forskning. De ligger idag i produktrepot under `crates/swe-gym/` och har egen CI-jobb.
6. **Mätavvikelse mot uppdraget:** uppdraget anger "98MB of benchmarks/*.json". Uppmätt är **10,5 MB committed** (224 filer) / 11 MB i working tree; `du -sh crates/swe-gym` visar 615 MB men då ingår det gitignorerade `target/` (603 MB). Se §18.

---

## 2. Kodbasens omfattning (uppmätt)

| Crate | Trackade filer | `src`-filer | `src` LOC | Tester | Exempel | Verktyg | Fixtures | `target/` (gitignored) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `crates/swe-native` | 24 | 17 (+1 testfil) | 3 804 | 30 (18 unit + 12 integration) | 0 | 0 | — | 111 MB |
| `crates/swe-gym` | 333 | 21 | 8 745 | 106 (93 integration + 13 inline) | 24 | 45 | 224 filer / 10,5 MB | 603 MB |

*`src` LOC = `wc -l` över alla filer under `src/`; `swe-native`-siffran exkluderar `tests/machine.rs` (478 rader).*

Katalogträd (relevant utsnitt):

```text
crates/
├── swe-native/                     # generisk SWD 1.0-kärna
│   ├── Cargo.toml                  # egna pins, egna features (python, extension-module)
│   ├── Cargo.lock  rust-toolchain.toml  pyproject.toml  README.md
│   ├── src/ (17 filer, varav machine/ 5)
│   └── tests/machine.rs            # 12 integrationstester
└── swe-gym/                        # fristående experiment (egen AGENTS.md)
    ├── Cargo.toml  Cargo.lock  AGENTS.md  .gitignore
    ├── src/ (21 filer)
    ├── tests/ (15 filer)
    ├── examples/ (24 filer: 15 live-gated, 9 offline)
    ├── tools/ (45 Python-skript)
    └── benchmarks/ (224 committed filer, 10,5 MB; 11 kataloger med captures/fixtures)
```

---

## 3. Crate-nivå: arkitektur och beroenderiktning

```text
                        ┌─────────────────────────────────────────────┐
                        │ Python: backend/app/swe/runtime.py           │
                        │   import swe_native (PyO3, compiled .so)     │
                        └───────────────────┬─────────────────────────┘
                                            │  anropar start/complete/fail/tick
                                            ▼
                        ┌─────────────────────────────────────────────┐
                        │ crates/swe-native  (lib + cdylib)            │
                        │   SWD 1.0: definition, machines, effects,    │
                        │   events, expressions, canonical JSON        │
                        │   externa: indexmap, serde_json, sha2,       │
                        │   thiserror, unicode-normalization, pyo3(opt)│
                        └───────────────────▲─────────────────────────┘
                                            │  path-beroende (enda riktningen)
                        ┌───────────────────┴─────────────────────────┐
                        │ crates/swe-gym  (experiment + binär demo)    │
                        │   ledger, metered driver, arms, env/RL,      │
                        │   providers, legal bench, fixtures           │
                        │   externa: swe-native, minreq(https-rustls)  │
                        └─────────────────────────────────────────────┘
```

Belägg:

* `crates/swe-gym/Cargo.toml:11` — `swe-native = { path = "../swe-native" }`; `:14` — `minreq` (endast för live-providers).
* `crates/swe-native/Cargo.toml` — inga path-/repo-beroenden; endast externa crates + valfri `pyo3` (`features.python`, `extension-module`).
* `backend/app/swe/runtime.py:75` — `import swe_native`; modulen är byggd med maturin (`crates/swe-native/pyproject.toml:15-18`, `Makefile:161-162`).
* `backend/` refererar **inte** `swe_gym`; enda träffen är en historisk kommentar i `backend/app/services/research/gliner/contract.py:3` ("Ported from the swe-gym experiments"), inte ett kodberoende.
* Det finns **ingen** `Cargo.toml`, ingen workspace och ingen gemensam lockfil på repo-roten (`ls Cargo.toml` → "No such file"). Varje crate byggs och versionspinnas separat (Rust 1.83: `crates/swe-native/rust-toolchain.toml:1-3`, båda `Cargo.toml` `rust-version = "1.83"`).

**Slutsats crate-nivå:** riktningen är korrekt (experiment → kärna; Python → kärna). Det finns ingen kärna→experiment- eller backend→experiment-beroende. Cykler: inga.

---

## 4. `crates/swe-native` — modulinventering (17 filer)

Alla rader är **Generisk / SWE / Behåll** om inget annat anges. Domen "Generisk" är motiverad i kolumnen Ansvar + i §4.1.

| Nuvarande placering (fil + modul + crate) | Ansvar | Beroenden (interna + externa) | Domänkoppling | Rekommenderad ägare | Åtgärd |
| --- | --- | --- | --- | --- | --- |
| `crates/swe-native/src/lib.rs` — crate root | Deklarerar 12 moduler + `machine`; exporterar publik API (`canonicalize`, `CompiledDefinition`, `Effect`, `EventSink`, `evaluate_expression`, `Json`, `start_run`, `WorkflowMachine`); `python`-modulen bakom feature `python` | interna: alla moduler; externa: — | **Generisk** | **SWE** | **Behåll** |
| `src/json.rs` — `Json` | Typat JSON-värde med Python-paritet (`true != 1` även nästlat); `IndexMap`-objekt; helpers `object`, `from_i64/u64/usize`, `as_*`, `require_*` | externa: `indexmap`, `serde_json::Number` | **Generisk** | **SWE** | **Behåll** |
| `src/canonicalize.rs` — kanonisering | Kanoniska JSON-bytes + SHA-256 som matchar SWD-oraklet; NFC-normalisering, sorterade nycklar, kollisionskontroll; `CANONICAL_SCHEMA_VERSION = "swd-canonical-json-v1"` (`:13`, `:15`, `:26`) | interna: `error`, `json`; externa: `sha2`, `unicode-normalization`, `serde_json` | **Generisk** | **SWE** | **Behåll** |
| `src/convert.rs` — konvertering | `serde_json::Value` ⇄ `Json`; NaN/Infinity avvisas; `parse_json_str` (`:9`, `:39`, `:57`) | interna: `error`, `json`; externa: `serde_json` | **Generisk** | **SWE** | **Behåll** |
| `src/error.rs` — felmodell | `ErrorKind` (13 typer: preflight, expression, path, type, limit, timeout, idempotency, unknown_invocation, conflict, cancelled, handler, unsupported, internal) + `RuntimeError {kind,message,path}`; `thiserror` (`:6`, `:36`) | externa: `thiserror` | **Generisk** | **SWE** | **Behåll** |
| `src/events.rs` — händelser | `EventKind` (13 typer), `Lineage {branch_path, fork/map-instance, loop_epoch}`, `RuntimeEvent`, `EventSink`-trait, `MemoryEventSink`; in-memory, ingen durability-claim (`:7`, `:44`, `:52`, `:65`, `:70`) | interna: `error`, `json` | **Generisk** | **SWE** | **Behåll** |
| `src/effects.rs` — effekter | `RunStatus` (running/completed/incomplete/failed/cancelled), `Effect` (`InvokeHandler`, `InvokeProvider`), `StepOutcome {status,effects,ignored}`; Rust väntar aldrig på async-handlers (`:6`, `:31`, `:67`) | interna: `json` | **Generisk** | **SWE** | **Behåll** |
| `src/path.rs` — JSON-path | Begränsad `$.a.b`-path-parser och uppslagning (`Found`/`Missing`) utan eval (`:15`) | interna: `error`, `json` | **Generisk** | **SWE** | **Behåll** |
| `src/expression.rs` — uttryck | Typad JSON-AST-evaluator: `const,var,eq,ne,lt,lte,gt,gte,and,or,not,in,add,sub,mul,div,exists`; rekursiv JSON-likhet; inga host-operatorer, ingen `eval` (`:7`) | interna: `error`, `json`, `path` | **Generisk** | **SWE** | **Behåll** |
| `src/definition.rs` — definition | Läser redan kompilerad SWD 1.0-dokument (ingen andraparser): `Limits`, `EndStatus`, `Binding`, `CachePolicy`, `Node` (Task/Decision/ProviderDecision/Fork/Join/Map/End) och `CompiledDefinition::load` med SHA-256-kontroll (`:48`, `:89`, `:100`) | interna: `canonicalize`, `error`, `json`, `preflight`; externa: `indexmap` | **Generisk** | **SWE** | **Behåll** |
| `src/preflight.rs` — preflight | Avvisar reserverade features innan körning: `wait`, `subworkflow`, `retry`, samt `cache_policy: exact` på `task` (`:7`, `:18-38`); aldrig tyst ignorerade | interna: `definition`, `error`, `json` | **Generisk** | **SWE** | **Behåll** |
| `src/machine/mod.rs` — maskin-API | `Machine::start/complete/fail/cancel/tick`, `protect`/`drain`, `emit`, `start_run` (`:20`, `:90-121`, `:142`, `:156`, `:165`, `:191`); en maskin per run | interna: `canonicalize`, `definition`, `effects`, `error`, `events`, `json`, `state` | **Generisk** | **SWE** | **Behåll** |
| `src/machine/state.rs` — maskintillstånd | `ScopeKind` (Root/Fork/Branch/Map/MapChild), `WorkStatus`, `BranchState`, `ChildState`, `Scope`, `Machine`-fält (scopes, invocations, sink, effects, work-kö) (`:9`, `:42`, `:87`) | interna: `definition`, `effects`, `events`, `json` | **Generisk** | **SWE** | **Behåll** |
| `src/machine/context.rs` — kontext/bindning | Bygger utvärderingskontext (`input`, `run`, scope-locals, `branches`, `children`, `item`, `index`) och binder `Binding::Path/Const`; `evaluate_condition` (`:11`, `:44`) | interna: `definition`, `error`, `expression`, `json`, `state`, `path` | **Generisk** | **SWE** | **Behåll** |
| `src/machine/schedule.rs` — schemaläggning | Schemalägger `task`, `decision`, `fork`, `join`, `map`, `end`; skapar scopes, branch/map-instanser, provider-effekter; steg-/djupgränser (`:39`, hjälptyper `:14-36`) | interna: `definition`, `effects`, `error`, `events`, `json`, `context`, `state`, `path` | **Generisk** | **SWE** | **Behåll** |
| `src/machine/complete.rs` — completion | `complete_invocation`/`fail_invocation`: idempotens (samma payload = no-op, olika = conflict), routing, join/map-barriärer, branch-resultat, timeout (`:11`, `:138`) | interna: `definition`, `effects`, `error`, `events`, `json`, `state` | **Generisk** | **SWE** | **Behåll** |
| `src/python.rs` — PyO3-brygga | `swe_native`-modul: `sha256_hex`, `canonical_json_bytes`, `evaluate_expression`, `PyMachine` (start/complete/fail/cancel/tick/deadline/status/events/output/error/lock/with_machine); konverterar Py↔Json, släpper GIL runt state-mutationer (`:1`, `:18`, `:53`, `:175-195`) | interna: `canonicalize`, `effects`, `error`, `events`, `expression`, `json`, `machine`; externa: `pyo3` (opt), `serde_json`; feature `python`/`extension-module` | **Generisk** | **SWE** | **Behåll** |
| `crates/swe-native/tests/machine.rs` — integrationstest | 12 tester: expression-routing, fork/join, map 0/1/många, provider-decision, idempotens/konflikt, nästlade forks, isolerade runs, loopar/loop_epoch, max_depth, timeout/tick, max_steps | interna: crate-API; externa: — | **Generisk** | **SWE** | **Behåll** |

### 4.1 Noteringar om `swe-native`

* **Fullt generisk kärna.** `lib.rs:1` säger uttryckligen "No OverGraph, Jev, or research knowledge", och grep över `src/` + `tests/` ger inga kodberoenden till dessa begrepp. De enda domänorden är inert testdata: `prompt_key: "research.assessment.user"` och `provider: "jev"` (`src/machine/mod.rs:220-230`, `:249`, `tests/machine.rs:188-208`). Det påverkar inte klassificeringen men bör bytas till neutrala värden i en fristående repo (kosmetiskt, låg risk).
* **Kontraktsfakta som är generiska** (verifierade mot `docs/specs/swe-runtime.md:52-66`, `docs/specs/swe-swd-1.0.md:36-46`): nodtyperna, reserverade features (preflight), steg-/djup-/timeout-gränser, idempotenta completions, events och lineage, kanonisk JSON + SHA-256.
* **Kvarvarande produktnära text:** `Cargo.toml:6` och `README.md:3` beskriver craten som "for Socialism Workflow Engine". Det är metadata, inte kod; en fristående repo bör byta beskrivning (åtgärd: textuell ändring, ingen kodändring).
* **Beroenden:** `serde = "=1.0.219"` med `derive` är deklarerat men inte direkt använt i `src/` (grep: inga `serde::`- eller derive-makron; endast `serde_json` används, `src/json.rs:4`, `src/convert.rs:4`). Det är en redundant direktberoende-post, inte en risk — men kan städas vid extraktion.
* **Features:** `python` (valfri `pyo3`) och `extension-module` (för `cdylib`/maturin). Utan `python` är craten ren rlib med noll nätverks-/tjänstekoppling — detta är den del som enklast blir en fristående kärna.

---

## 5. `crates/swe-gym` — modulinventering (21 filer)

För varje rad anges även det som gör filen blandad/domänspecifik. Fullständig motivering per förmåga finns i §6.

| Nuvarande placering (fil + modul + crate) | Ansvar | Beroenden (interna + externa) | Domänkoppling | Rekommenderad ägare | Åtgärd |
| --- | --- | --- | --- | --- | --- |
| `src/lib.rs` — crate root | Deklarerar 20 moduler (`:6-24`); doc-kommentar säger "Sweycoin budget experiment. No external services" | interna: —; externa: — | **Generisk** (ren modulmanifest) | **Experiment** (blir kärnmanifest efter split) | **Behåll** |
| `src/ledger.rs` — `ledger` | Append-only Sweycoin-ledger: eventlog som sanning, materialiserade saldon = fold (`Ledger::replay` `:495`); `allocate/reserve/settle/release/transfer/reward` (`:156,193,250,325,376,422`); idempotensnycklar, reservationer som regleras exakt en gång, virtuell reward-pool som aldrig blir spenderbar; invariant 1–5 dokumenterade (`:4-18`) | interna: —; externa: std (`HashMap`, `HashSet`) | **Generisk** — generisk budget-/kostnadsledger; "Sweycoin" är bara ett enhetsnamn. Kan beskrivas/testas utan domän (bevis: 9 tester i `tests/ledger_tests.rs` använder bara konton/amounts) | **SWE** (generisk budgetförmåga; exakt placering beslutas i `05-gym-split.md`) | **Separera** |
| `src/calibrate.rs` — `calibrate` | Härleder tariffer (milli-Sweycoins) från uppmätta `CallSample {tokens, latency_ms}` under explicit ankare; `CalibrationReport` (`:14`, `:22`, `:40`); inga dolda defaults | interna: `ledger`; externa: — | **Generisk** — kostnadskalibrering från tokens+latens är domänneutral. 3 tester pinner formeln (`tests/calibrate_tests.rs`) | **SWE** | **Separera** |
| `src/provider.rs` — `provider` | Provider-seam: `ProviderAnswer {choice, score_bp, latency_ms, raw}` (`:21`), `trait ResearchProvider {analyze(provider, chunk_id, chunk_text)}` (`:33`); implementationer: `FakeCorpus` (`:47`), `ReplayProvider` från fryst fixture (`:74`), `RecordProvider` (`:164`), `HttpJevProvider` (`:230`), `HttpLlmProvider` (`:341`); hjälpare `usage_tokens` (`:316`), `map_llm_word` (`:424`), `map_jev_choice` (`:441`), `resolve_secret`/dotenv (`:467`), `json_escape` (`:492`) | interna: `strategy::FakeCorpus` (**domänberoende**); externa: `swe_native` (JSON), `minreq` (via HTTP-impl) | **Blandad** — trait + record/replay är generiska; `FakeCorpus`, `HttpJev`, JEV-/LLM-mappning och "fynd"/"inget" (`:22`, `:60`) är domän | **SWE** (trait + replay/record) / **Experiment** (FakeCorpus, HttpJev) | **Separera** |
| `src/strategy.rs` — `strategy` | `QuestionView {id, chunks, required_coverage, question, scan_order}` (`:14`), `Question` med facit (`:28`), `FakeCorpus` score-modell (`:70`), `ProviderKind`, `Tariffs`, `BranchPlan`, `Continuation`, `ScanDecision`, `ScanState`, `trait Strategy` (plan/continuation/observe_scan/revise, `:213`), `Observations` (`:257`), `rank_unresolved_by_score` (`:266`), armar A/B/C/H/orakel (`:287,328,370,429,477`) | interna: `ledger`; externa: `swe_native` (indirekt via benchmark) | **Blandad** — själva arm-interfacet (budgetförslag in/ut) är generiskt; `chunks/coverage/fynd`-modellen och de konkreta armarna är research-domän | **SWE** (arm-interface) / **Socialism** (frågemodell + armar) | **Separera** |
| `src/bench.rs` — `bench` | Läser fryst bench-fil (`version, name, score_model, tariffs, total_budget, questions`) (`:17`); facit isoleras från strategier via typ (`QuestionView` vs `Question`, `:1-7`); `load_bench`/`load_bench_file` (`:36`, `:141`) | interna: `ledger`, `strategy`; externa: `swe_native` | **Blandad** — fryst benchmark-format + budget/tariffer är generisk idé; `Question`-modellen (chunks/coverage/evidence) är domän | **SWE** (bench-format) / **Socialism** (frågemodell) | **Refaktorera** |
| `src/benchmark.rs` — `benchmark` | A/B-harness: kör en strategis `BranchPlan` mot swe-native-kärnan med **en delad ledger**, varvar brancher round-robin (en provider-call per steg), verkställer tak; `ArmReport` (`:26`), `run_arm` (`:68`), `run_arm_with_provider` (`:81`, realism-seam), `Harness` (`:52`) | interna: `driver`, `ledger`, `provider`, `strategy` (**blandad**); externa: `swe_native` | **Blandad** — körnings-/mätloopen är generisk; frågor/armar/coverage är domän | **SWE** (A/B-runner) | **Separera** |
| `src/driver.rs` — `driver` | Metrad driver ovanpå kärnan: dispatchar `InvokeProvider`-effekter, `reserve → provideranrop → settle`, hårt budgettak, "loud denial", stabilt replay (`:1-11`, `run_with_budget` `:48`); demo-/domänhjälpare `fake_analyze` ("fynd"/"inget", `:189`, `:196-197`), `build_chain_document` (kedja av provider-decisioner, `:204`, choices `:218`), `build_chunk_input*` (`:230-243`) | interna: `ledger`; externa: `swe_native` | **Blandad** — meter-/dispatch-loopen är generisk (den enda platsen en riktig LLM-klient pluggas in); demo-hjälparna är research-domän | **SWE** (metered driver) | **Separera** |
| `src/gen.rs` — `gen` | Deterministisk syntetisk frågegenerator (`:14`): 10 chunks, en del evidens "blind" för scan-providern så eskalering alltid behövs | interna: `strategy`; externa: — | **Blandad** — generatorlogiken är generisk; chunk/evidens-modellen är domän | **Experiment** | **Behåll** |
| `src/env.rs` — `env` | v2 budget-manager-MDP: `trait SweEnv {reset, step}` (`:802`), `SyntheticEnv` (`:813`), diskret `Observation` (`:52`) och `Action` (`:103`, 19 handlingar), `EnvConfig` + fyra världar (`default_config` `:195`, `capability_config` `:346`, `synergy_config` `:499`, `benchmark_config` `:651`); `STRATEGY_COUNT = 3; // A retrieval/graph, B JEV, C narrative LLM` (`:25`) | interna: `ledger`; externa: — | **Blandad** — MDP-/miljöformen är generisk; strategisemantiken (A=retrieval, B=JEV, C=LLM), frågetyper och kvalitetsmodell är domän | **Experiment** | **Refaktorera** |
| `src/oracle.rs` — `oracle` | Exakt DP-orakel för syntetisk miljö (baklängespass över budget×tiers), diagnostiskt tak; `oracle_value` (`:67`), `oracle_policy_cost` (`:87`) | interna: `env`, `ledger`; externa: std | **Blandad** — algoritmen är generisk; tillståndsrymden är env-definierad | **Experiment** | **Behåll** |
| `src/train.rs` — `train` | Tränings-/evalharnesk: frågeset (train vs held-out) (`:17`), episodloop (`:54`), `evaluate` (`:87`), `run_season` (`:97`), `calibration_gate` (`:160`), `GateReport` (`:149`) | interna: `agent`, `env`, `oracle`; externa: — | **Blandad** — tränings-/utvärderingsmetodik generisk; allt typat mot env:s domänfrågor | **Experiment** | **Behåll** |
| `src/agent.rs` — `agent` | `trait Policy` (deterministisk i eval, `:25`) + baslinjer `EqualSplitPolicy` (`:85`), `SequentialPolicy` (`:146`), `AdaptiveGreedyPolicy` (`:203`) + tabulär MC-Q-lärare `McQLearner` (`:321`, `replay_fit` `:478`) | interna: `env`; externa: — | **Blandad** — policy-/lärarmekaniken är generisk; observationer/handlingar är domän | **Experiment** | **Behåll** |
| `src/td.rs` — `td` | TD(0)-Sarsa över scan-checkpoint-kedjan, baklängespass per episod; `MIN_SAMPLES` (`:25`), `TdPolicy` (`:28`), `TdSequentialStrategy` (`:142`), `train_td` (`:247`) | interna: `bandit`, `benchmark`, `ledger`, `strategy`; externa: std | **Blandad** — RL-algoritmen generisk; scan-kedjan/eskaleringen domän | **Experiment** | **Behåll** |
| `src/bandit.rs` — `bandit` | Kontextuell linjär bandit (SGD) för ett budgetbeslut: hur många djupanrop som ska auktoriseras efter scan-passet; `BanditPolicy` (`:87`), `BanditStrategy` (`:199`), `train_bandit` (`:326`), scan-policy (`:406`), sekventiell variant (`:535`) | interna: `benchmark`, `ledger`, `strategy`; externa: — | **Blandad** — bandit-/SGD-mekanik generisk; kontext/aktioner domän | **Experiment** | **Behåll** |
| `src/student.rs` — `student` | Behavior-cloning-elev: multinomial logistisk regression över facit-fria observationsfeatures (`:18`, `:20`), `StudentPolicy` (`:66`), leave-one-question-out-grind (`:167`) | interna: `agent`, `dataset`, `env`; externa: — | **Blandad** — BC/LOO-metodik generisk; features ur domänobservationen | **Experiment** | **Behåll** |
| `src/dataset.rs` — `dataset` | Inspelade beslutstrajektorier (v4): frågefeatures, varje beslut med facit-fri observation, utfall, kostnad, terminal kvalitet; `record_episode` (`:45`), `load_dataset` (`:244`) | interna: `agent`, `env`, `ledger`, `provider`; `real::RealEnv` (**domänberoende**); externa: `swe_native` | **Blandad** — trajektorieformatet är generiskt; typat mot `RealEnv`/legal-frågor | **Experiment** (generisk form att återanvända) | **Refaktorera** |
| `src/explore.rs` — `explore` | Kontrollerad exploration: epsilon-greedy (`:37`) och riktad exploration (`:84`); `run_exploration` (`:177`), `eval_frozen` (`:265`) | interna: `agent`, `dataset`, `env`, `real`, `student`; externa: — | **Blandad** — explorationsmekaniken generisk; JEV-hit rate/stall-gränser domän | **Experiment** | **Behåll** |
| `src/real.rs` — `real` | `RealEnv`: v2-gym över **fryst legal bänk**; A=retrieval (`LOOKUP_MILLI=50`), B=JEV mot frysta 2019-svar (`SCAN_MILLI=1000`), C=LLM maskad; `RealQuestion` (`:63`), `RealEnv` (`:74`), `run_episode_real` (`:500`), `evaluate_real` (`:539`), `load_real_bench` (`:554`), `RealPipelinePolicy` (`:620`) | interna: `agent`, `bench`, `env`, `ledger`, `provider`, `train`; externa: `swe_native` | **Socialism-specifik** — legal avtalsbänk, 2019-frysta JEV-svar, svenska avtals-id (`Avtal_47_Programvarulicensavtal:25`, `:53-57`), uppsägningstid/auto-renewal-frågor | **Socialism** | **Flytta** |
| `src/ops.rs` — `ops` | Typad operationsgraf med exekveringskontrakt: `NeedRef {fact, document}` (`:12`), `OperationSpec` med required inputs/ALL_REQUIRED/missing-outcome (`:40`), `max_notice_period` (`:68`), `OpOutcome` inkl. `NeedMore` (`:146`), `apply_exception` (`:157`), `investigate_operate_loop` (`:178`); tester refererar `Avtal_17/18/20` | interna: — (fristående); externa: std | **Socialism-specifik** — uppsägningstider, villkor/undantag, svenska avtalsdokument; kontraktsregler är legaldomän | **Socialism** | **Flytta** |
| `src/main.rs` — binär demo | PoC-demo: budget-cut + armar A/B (`:1-11`) samt sektioner A–H, J, L (bandit, generalisering, TD, strukturerad korpus, inbäddningsanalys, retrieval-kapitalkostnad) (`:34`, `:160`, `:253`, `:312`, `:419`, `:525`, `:685`, `:781`) | interna: nästan alla moduler; externa: — | **Blandad** — demon blandar generisk körning med domänarmar och svensk output | **Experiment** | **Behåll** (eller flytta till examples vid split) |

**Filnivåräkning:** Generisk **3** (`lib`, `ledger`, `calibrate`), Blandad **16** (`main`, `agent`, `bandit`, `bench`, `benchmark`, `dataset`, `driver`, `env`, `explore`, `gen`, `oracle`, `provider`, `strategy`, `student`, `td`, `train`), Socialism-specifik **2** (`real`, `ops`). Summa 21.

> Viktigt: filnivåräkningen **underskattar** den generiska kärnan, eftersom flera "blandade" filer innehåller en generisk förmåga som är omgiven av domäntyper (t.ex. `benchmark.rs`, `driver.rs`, `strategy.rs`). Förmågenivån i §6 är det som styr vad som kan lyftas.

---

## 6. Generisk kärna vs research-/legaldomän i `swe-gym`

Uppdraget bad särskilt om att skilja den generiska kärnan (ledger, driver/metering, benchmark-runner, replay/frysta providers, strategy-arms, kostnadsmätning) från research-/legaldomän-experimenten (JEV/GLiNER2-fixtures, chunk-scanning, kontraktsuppsägningstider).

| Förmåga | Kod (file:line) | Klassning | Varför (regeln) |
| --- | --- | --- | --- |
| **Append-only budget-ledger** (reserve/settle/release/transfer/reward, idempotens, replay) | `src/ledger.rs:136` (struct), `:156-450` (API), `:495` replay | **Generisk** | Kan beskrivas som "budgeterade körningar med reservation och deduplicerad (at-most-once) debitering"; inga domänbegrepp i typerna (`Account = String`, `Amount = u64`). Testas utan domän i `tests/ledger_tests.rs` (9 tester). |
| **Metered driver** (effekt-dispatch + reservation per provider-call + hårt tak + loud denial) | `src/driver.rs:48-187`; dispatch-mönster i `src/benchmark.rs:81-...` (`Harness` `:52`) | **Generisk** (kärnan) | Detta är den generiska "host-driver"-förmågan: kärnan emitterar `InvokeProvider`/`InvokeHandler`, drivern mäter och anropar. Demo-hjälparna i samma fil (`fake_analyze` `:189`, `build_chain_document` `:204`) är domän och kan flyttas. |
| **A/B benchmark-runner** (flera armar, en delad ledger, interleaved branch-körning, armrapport) | `src/benchmark.rs:26` (`ArmReport`), `:68`/`:81` (`run_arm*`) | **Generisk** (ramen) | Ramen jämför budgetförslag mot en körande workflow; den behöver bara ett neutralt arm-/frågeinterface. Idag tar den `strategy::{Strategy,Question}` (§8). |
| **Frysta/replay-providers + record-wrapper** | `src/provider.rs:74` (`ReplayProvider`), `:164` (`RecordProvider`), `:183` (fixture-format) | **Generisk** | Inspelning och deterministisk uppspelning av provider-svar är domänneutralt (samma idé som HTTP-VCR). |
| **Strategy-arm-interface** (plan → budgetförslag; observe/revise-hooks) | `src/strategy.rs:213-278`, `:170` (`BranchPlan`), `:181` (`Continuation`) | **Generisk form, domän i innehåll** | Formen "strategi får ett facit-fritt view + budget, returnerar brancher/fortsättning" är generisk. `QuestionView.chunks/required_coverage/scan_order` (`:14-24`) och armarna (`:287-553`) är domän. |
| **Kostnadsmätning/kalibrering** (tokens + latens → tariff under ankare) | `src/calibrate.rs:14/22/40` | **Generisk** | Ren aritmetik på mätsamples; 3 tester pinner formeln. |
| **Deterministisk env + DP-orakel + tränings-/utvärderingsloop** | `src/env.rs:802` (`SweEnv`), `:813` (`SyntheticEnv`); `src/oracle.rs:67`; `src/train.rs:54/87/97/160` | **Blandad** | Metodiken (MDP, exakt orakel, calibration gate, held-out) är generisk och återanvändbar; tillstånd/aktioner/kvalitetsmodell är definierade av A=retrieval/B=JEV/C=LLM (`env.rs:25`) och därmed domän. |
| **Inlärda policies** (MC-Q, linjär bandit, TD(0)-Sarsa, BC-elev) | `src/agent.rs:321`; `src/bandit.rs:87/326`; `src/td.rs:28/247`; `src/student.rs:66/167` | **Blandad** | Algoritmerna är generiska (~100–300 rader var, medvetet utan externt RL-bibliotek); features/context/actions är domän. |
| **Trajektorie-dataset** | `src/dataset.rs:19/45/244` | **Blandad** | Formatet (obs, action, cost, reward, terminal quality) är generiskt men typat mot `RealEnv` (`:16`) och legal-frågor. |
| **Syntetisk frågegenerator** | `src/gen.rs:14` | **Blandad** | Generatorlogiken är generisk; den genererar chunk-evidensfrågor (`CHUNK_COUNT = 10`, `:12`). |
| **Chunk-scanning / evidens-coverage / "fynd"/"inget"** | `src/strategy.rs:14-40`, `:70-137`; `src/provider.rs:21-31`, `:55-61`, `:428-459`; `src/driver.rs:189-202`, `:218`; `src/bench.rs:28-40` | **Socialism-specifik (research-domän)** | Detta är produktens research-modell: dokumentchunks, evidensfacit, täckningskrav och svensk binär vokabulär ("fynd"/"inget"). Kan inte beskrivas utan domänbegreppen. |
| **Fryst legal bänk + JEV-svar (2019)** | `src/real.rs:1-20`, `:554-620`; `benchmarks/bench_real_v2.json`; `benchmarks/real_fixtures/*`; `benchmarks/real_fixtures_deep/*` | **Socialism-specifik** | Svenska avtal (`Avtal_01_Tillsvidareanstallningsavtal`), frågor som "Innehåller texten en stående uppsägningstid…", frysta JEV-klassificeringar. |
| **Operationsgraf med kontraktsregler** (uppsägningstid, undantag) | `src/ops.rs:12/40/68/146/157/178` | **Socialism-specifik** | Domänregler: `max_notice_period` över `Avtal_17/18/20`, `apply_exception` för villkor. |
| **GLiNER2/JEV-utvärdering** | Inget i `src/` (grep: `gliner` = 0 träffar i `swe-gym/src`); finns i `tools/eval_gliner*.py`, `tools/gen_gliner_*.py`, `benchmarks/gliner_*.json`, `documents docs/architecture/gliner2-*.md` | **Socialism-specifik** | Ren legaldomän-forskning; får inte följa med en SWE-extraktion. |

**Slutsats:** det finns en **naturlig generisk kärna** om sex delar — ledger, metered driver, A/B-runner, replay/record-provider, arm-interface och kostnadskalibrering — men den är idag sammanvävd med research-frågemodellen via `strategy`/`provider`/`bench`. En extraktion måste först invertera de beroendena (§8), inte kopiera filerna rakt av.

---

## 7. Modulnivå: beroendegraf

### 7.1 `swe-gym` interna beroenden (från `use crate::…`)

```text
ledger ──────────────┬── strategy ── gen
   │                 │      │
   │                 │      ├── bench ── real ── train ── oracle
   │                 │      │      │        │        │
   │                 │      ├── provider ◄─┘        └── agent ── env
   │                 │      │      │
   │                 ├── benchmark ─┤
   │                 │      │      └── driver
   │                 │      │
   │                 ├── bandit ── td ──┘
   │                 │      │
   │                 └── dataset ── student ── explore
   │                        │
   └────── calibrate        └── real
```

Kanterna (från skriptet i §18): `agent→env`; `bandit→{benchmark,ledger,strategy}`; `bench→{ledger,strategy}`; `benchmark→{driver,ledger,provider,strategy}`; `calibrate→ledger`; `dataset→{agent,env,ledger,provider,real}`; `driver→ledger`; `env→ledger`; `explore→{agent,dataset,env,real,student}`; `gen→strategy`; `oracle→{env,ledger}`; `provider→strategy`; `real→{agent,bench,env,ledger,provider,train}`; `strategy→ledger`; `student→{agent,dataset,env}`; `td→{bandit,benchmark,ledger,strategy}`; `train→{agent,env,oracle}`. Blad (ingen intern dependens): `ledger`, `calibrate`, `ops`. Moduler utan dependenter: `calibrate`, `explore`, `gen`, `lib`, `main`, `ops`.

**Cykler:** inga. Verifierat med DFS-skript över alla `use crate::*`-kanter (utskrift: `cycles: none`).

### 7.2 `swe-native` interna lager (från `use crate::…`)

```text
error  json  (blad)
  ▲      ▲
  │      ├── path ── expression
  │      ├── events ── effects
  │      ├── canonicalize ── definition ── preflight
  │      └── convert
  └───────── machine/{state,context,schedule,complete,mod}
                 ▲
              python (endast feature python)
```

Riktningen är strikt uppåt (högre lager beror på lägre); inga bakåtkanter och inga cykler. `python.rs` är det enda bladet som beror på machine-lagret.

### 7.3 Felriktade beroenden ("wrong direction")

| # | Kant | Problem | Bevis | Åtgärd |
| --- | --- | --- | --- | --- |
| W1 | `provider` (generisk seam) → `strategy::FakeCorpus` (domänkorpus) | Generisk provider-modul beror på en konkret domänimplementation; att flytta `provider.rs` kräver att `FakeCorpus` följer med eller att beroendet inverteras | `src/provider.rs:18` (`use crate::strategy::FakeCorpus`), `:47-72` | **Refaktorera:** låt `provider` bara äga `ResearchProvider`-trait + replay/record; flytta `FakeCorpus`-impl till domän-/experimentmodul. |
| W2 | `dataset` (generiskt trajektorieformat) → `real::RealEnv` (legaldomän) | Generisk dataformatmodul beror på domänmiljön; "generic dataset" kan inte flyttas utan legal-bänken | `src/dataset.rs:16` (`use crate::real::{RealEnv, RealQuestion}`), `:12` (`use crate::agent::Policy`) | **Refaktorera:** inför ett generiskt `Env`-/`Observation`-gränssnitt (finns delvis som `env::SweEnv`, `src/env.rs:802`) och låt `RealEnv` implementera det; `dataset` ska bara känna det gränssnittet. |
| W3 | `bench` / `benchmark` / `strategy` → domänfrågemodell | Benchmark-formatet och A/B-runnern är sammanvävda med `Question{chunks,evidence,coverage}`; kan inte beskrivas utan research-begrepp | `src/bench.rs:13`, `:17-40`; `src/benchmark.rs:16-21`; `src/strategy.rs:14-40` | **Separera:** generisk `Question`/`BenchFile` (id + budget + tariffer) + domänspecifik `EvidenceQuestion`. |
| W4 | `td` / `bandit` / `student` / `explore` → `strategy`/`benchmark`/`real` | Inlärningsmodulerna beror på körningsharnesk och legaldomän, inte bara på miljögränssnittet; försvårar återanvändning av RL-mekaniken | `src/td.rs:12-19`; `src/bandit.rs:10-15`; `src/student.rs:13-14`; `src/explore.rs:17-21` | **Refaktorera** vid behov; inte nödvändigt för SWE-extraktion (dessa stannar i experiment). |
| W5 | Exempel → `../../backend/.env` (host-koppling) | Exempel läser produktens `.env` via relativ sökväg; kopplar experimentet till produktrepots layout och hemligheter | `examples/live_smoke.rs:14-18`; `examples/live_cap.rs:21-22`; `examples/v2_milestone.rs:99-106`; `src/provider.rs:467-473` | **Flytta/Refaktorera:** env-gated live-exempel ska inte följa en fristående SWE-repo; om de behålls, läs bara processmiljö. |
| — | `real` → `train`/`env`/`ledger`/`provider` | Domän → generisk riktning. Detta är **korrekt** riktning (domän får bero på generisk kärna) och ska bevaras. | `src/real.rs:24-30` | **Behåll** |

**Slutsats:** det finns inga *cykler* och ingen omvänd crate-riktning, men tre strukturella felriktningar (W1–W3) som blockerar en ren extraktion av den generiska kärnan. De är små till omfattningen (några `use`-rader + typflyttar) men måste göras medvetet.

---

## 8. Externa beroenden

### 8.1 `swe-native` (direkta)

| Crate | Version (pinnad) | Syfte | Används i | Kommentar |
| --- | --- | --- | --- | --- |
| `indexmap` | `=2.9.0` (feature `std`) | Insättningsordnade maps/sets — deterministisk ordning i scopes, noder, kanonisk JSON | `json.rs`, `definition.rs`, `canonicalize.rs`, `machine/*` | Kärnberoende för determinism. |
| `serde_json` | `=1.0.140` (feature `preserve_order`) | JSON-parsning + `Number`-typ | `json.rs`, `convert.rs`, `canonicalize.rs`, `python.rs`, `definition.rs`, `expression.rs` | `preserve_order` krävs för turordning. |
| `sha2` | `=0.10.8` | SHA-256 för definitions-id/canonical bytes | `canonicalize.rs:26-30` | — |
| `thiserror` | `=2.0.12` | Härledda `Error`-impls för typade fel | `error.rs` | — |
| `unicode-normalization` | `=0.1.24` | NFC-normalisering av nycklar i kanonisk JSON | `canonicalize.rs:8`, `:40-...` | Krävs för Python-paritet. |
| `pyo3` | `=0.24.2` | Python-bindningar | `python.rs` | **Valfri** (feature `python`; `extension-module` för maturin). Utan feature är craten ren rlib. |
| `serde` | `=1.0.219` (derive) | Deklarerad men **inte direkt använd** i `src/` (endast transitivt via serde_json) | — | Redundant direktberoende; kan tas bort vid extraktion. |

Transitiva (från `crates/swe-native/Cargo.lock`, 41 poster): `proc-macro2`, `quote`, `syn`, `heck` (pyo3-makron), `digest`, `block-buffer`, `crypto-common`, `generic-array`, `typenum`, `cpufeatures`, `autocfg`, `memchr`, `itoa`, `ryu`, `hashbrown`, `equivalent`, `libc`, `once_cell`, `portable-atomic`, `indoc`/`unindent` (pyo3), `memoffset`, `target-lexicon`, `version_check`, `rustversion`, `unicode-ident`, `tinyvec`, `cfg-if`, `pyo3-*`. Inget nätverk, ingen async runtime, ingen databas.

### 8.2 `swe-gym` (direkta)

| Crate | Version | Syfte | Används i | Kommentar |
| --- | --- | --- | --- | --- |
| `swe-native` | path `../swe-native` | SWD 1.0-kärnan (workflow-exekvering, JSON, kanonisering) | `driver.rs:13`, `benchmark.rs:12-14`, `provider.rs:16`, `bench.rs:11`, `dataset.rs:17` | Enda interna beroendet. |
| `minreq` | `2.14.1` (feature `https-rustls`) | Liten synkron HTTP-klient för live JEV/LLM-providers | `provider.rs:287`, `:390` (`minreq::post`) | **Endast live-vägar**; tester och offline-benchmarks använder replay/fake. TLS-stacken drar in `rustls 0.21`, `ring`, `webpki-roots`, `sct`, `untrusted` m.fl. (se `Cargo.lock`). Kommentar i `Cargo.toml:12-13` förklarar att `ureq` valdes bort p.g.a. edition 2024 vs Rust 1.83. |

`swe-gym` har **inga dev-dependencies** — alla tester använder standardbiblioteket eller crate-API:t.

### 8.3 Beroendepolicy-observationer

* Båda cratarna är små och pinnade (`=version` i `swe-native`); inga frameworks.
* Enda nätverksberoendet (`minreq`/`rustls`) finns i experimentets live-providers, inte i kärnan — bra för en fristående SWE-kärna utan nätverk.
* `swe-native` saknar `Cargo.lock`-post för dev-dependencies utöver serde_json.

---

## 9. Testinventering

### 9.1 `swe-native` (30 tester, alla generiska)

| Fil | Antal | Vad som pinnas | Domänkoppling | Ägare |
| --- | ---: | --- | --- | --- |
| `src/canonicalize.rs` (`mod tests`, `:230`) | 7 | Kanoniska bytes, SHA-256, NFC, kollisionsfel, talnormalisering | Generisk | SWE |
| `src/expression.rs` (`mod tests`, `:198`) | 5 | Operatorer, typfel, `exists`, `in`-likhet, `const`/`var` | Generisk | SWE |
| `src/machine/mod.rs` (`mod tests`, `:203`) | 6 | Provider-decision: effekt, route, okänt choice, route/choice-validering, dubbletter | Generisk | SWE |
| `tests/machine.rs` | 12 | Expression/fork/join/map/provider/idempotens/nästlade forks/isolering/loopar/max_depth/timeout/max_steps | Generisk | SWE |

Uppmätt körtid: ~0,3 s. Kommando och utskrift i §18.

### 9.2 `swe-gym` (106 tester; 15 filer + 2 inline-moduler)

| Fil | Antal | Vad som pinnas | Domänkoppling | Ägare |
| --- | ---: | --- | --- | --- |
| `src/ops.rs` (`mod tests`, `:76`) | 10 | Operationskontrakt: ALL_REQUIRED, `max_notice_period`, `NeedMore`, undantagsregel | Socialism-specifik | Socialism |
| `src/oracle.rs` (`mod tests`, `:140`) | 3 | DP-orakel mot kända små fall | Blandad | Experiment |
| `tests/ledger_tests.rs` | 9 | Reservation/settle/release, dubbel debitering, idempotens, delegation konserverar budget, reward ej spenderbar, negativa saldon, replay/resume | Generisk | SWE |
| `tests/calibrate_tests.rs` | 3 | Kalibreringsformel, skalning, krav på samples/ankare | Generisk | SWE |
| `tests/driver_tests.rs` | 3 | Hårt budgettak (loud), generös budget, avbruten run replay:as identiskt | Generisk (använder "chunks" i input) | SWE (driver) |
| `tests/provider_tests.rs` | 8 | FakeCorpus bakom trait, JEV-mappning, record→replay, saknad fixture, JSON-escape, LLM-mappning, malformed fixtures, fryst live-fixture | Blandad (5 generiska replay-tester, 3 JEV-/legal) | SWE + Experiment |
| `tests/benchmark_tests.rs` | 10 | Fryst bench pinnad, A/B/C/orakel-armar, hårt tak, identisk eventlogg vid replay | Blandad | SWE (runner) / Experiment (armar) |
| `tests/env_tests.rs` | 12 | Per-steg-reward summerar, determinism, maskerade actions, budgettak via ledger, reward-pool, max_steps, orakelvärden, calibration gate, learner slår baslinje | Blandad | Experiment |
| `tests/bandit_tests.rs` | 10 | Generator-determinism, eskalering, SGD-uppdatering, fryst bench, reproducerbar träning, brusig score-modell, generalisering | Blandad | Experiment |
| `tests/td_tests.rs` | 5 | TD-uppdatering, reproducerbarhet, strukturerad korpus, TD vs arm C | Blandad | Experiment |
| `tests/student_tests.rs` | 3 | Facit-fria features, LOO-grind, rollout mot läraren | Blandad | Experiment |
| `tests/dataset_tests.rs` | 3 | Förlustfri round-trip, replay till samma kvalitet, fryst blandad dataset | Blandad | Experiment |
| `tests/explore_tests.rs` | 4 | Ceiling-probe, exploration-verdict, riktad exploration, held-out-skydd | Blandad | Experiment |
| `tests/capability_tests.rs` | 4 | Capability-orakel, gate, learner slår regel, nära orakelkostnad | Blandad | Experiment |
| `tests/synergy_tests.rs` | 5 | Synergi-orakel, gate, delayed return, retrieval-först, stoppkostnad | Blandad | Experiment |
| `tests/real_bench_tests.rs` | 7 | Fryst legal bench komplett, fixtures matchar gold, syntetiskt tränade policies transfererar, retrieval-kapitalkostnad, tvåfas-scanner vs blind, inbäddningsrapport, replay-armar | Socialism-specifik | Socialism |
| `tests/real_env_tests.rs` | 7 | Legal fixtures mot gold, determinism/replay, reward-summa, retrieval gatar JEV, facit-fria signaler, budgettak, benchmark-jämförelse | Socialism-specifik | Socialism |

**Körtid:** totalt ~4,5 min; tunga sviter är `explore_tests` (100 s), `real_bench_tests` (55 s), `student_tests` (45 s), `td_tests` (34 s), `bandit_tests` (32 s). Alla 106 passerar **offline** (`cargo test --offline`, se §18). Testsviten bevisar att gymmet är självförsörjande utan nätverk — de nätverksgated kodvägarna ligger i `examples/`, inte i `tests/`.

**Generisk andel av testerna:** 15 tester är strikt generiska (ledger 9, calibrate 3, driver 3), 5 replay-tester i `provider_tests` är generiska, resten (86) är blandade eller domän. Det visar att den generiska kärnan redan har en separat, domänfri testyta — ett gott tecken för extraktion.

---

## 10. Exempelinventering (24 filer)

Alla exempel är `cargo run --example <namn>`. Indelning efter om de kan köras helt offline.

| Grupp | Filer | Antal | Domänkoppling | Ägare |
| --- | --- | ---: | --- | --- |
| **Live-JEV/LLM-captures (env-gated, kräver nät + nycklar)** | `capture_fixture.rs`, `capture_real.rs`, `live_cap.rs`, `live_smoke.rs`, `v2_capture_deep.rs`, `v2_chains.rs`, `v2_dependencies.rs`, `v2_g4.rs`, `v2_market.rs`, `v2_measure.rs`, `v2_milestone.rs`, `v2_oracle_decomp.rs`, `v2_states.rs`, `v2_variants.rs`, `v2_verification.rs` | 15 | Socialism-specifik (JEV/legal/GliNER2-material) | **Socialism / Experiment** |
| **Offline på frysta fixtures (legal bänk)** | `calibrate.rs` (JEV-fixture → tariff), `replay_arms.rs` (auto-renewal), `v2_collect.rs`, `v2_explore.rs`, `v2_real.rs`, `v2_student.rs` | 6 | Blandad → Socialism-specifik (legal bänk; `calibrate` är generisk metod) | **Socialism** (utom kalibreringsmetoden) |
| **Offline syntetiska (generisk metodik)** | `v2_capabilities.rs`, `v2_synergy.rs`, `v2_synthetic.rs` | 3 | Blandad (syntetisk A/B/C-värld; metodiken generisk) | **Experiment** |

Noteringar:
* 15 exempel använder `HttpJevProvider`/`HttpLlmProvider` och `resolve_secret(..., "../../backend/.env")` — de är **host-kopplade** till produktrepot och får inte följa en SWE-extraktion (W5).
* `examples/calibrate.rs` läser `benchmarks/jev_fixture_v1.json` och är det enda exemplet vars *mekanik* (tariffkalibrering) är generisk även om datat är JEV-domän.
* Exempel-katalogen är den enda platsen i gymmet som kräver nätverk; tester är offline.

---

## 11. Verktygsinventering (`tools/`, 45 Python-skript)

Inga verktyg är Rust eller SWE-generiska; alla är research/legaldomänens analys- och utvärderingsskript. De får inte följa med en SWE-extraktion.

| Grupp | Filer (räkning) | Domän |
| --- | --- | --- |
| **GLiNER2/JEV-utvärdering** | `eval_gliner.py`, `eval_gliner_arms.py`, `eval_gliner_challenge.py`, `eval_postprocessing_arms.py`, `eval_verification_arms.py`, `eval_verification_h.py`, `eval_verification_stages.py`, `eval_uncertainty_states.py`, `eval_d2.py`, `gen_gliner_testset.py`, `gen_gliner_challenge.py`, `test_challenge.py`, `investigate_false_resolved.py`, `fill_gold_verdicts.py`, `analyze_contamination.py` (15) | Socialism-specifik (span/entitet, legal avtalsklausuler) |
| **Blindtest/replay** | `run_blindtest.py`, `run_blindtest_v2.py`, `blindtest_v2_arms*.py` (4), `d10_blindtest.py`, `replay_d10_v2.py`, `replay_d10_v3.py` (9) | Socialism-specifik (unseen contracts, redacted artifacts) |
| **Golden-/mätverktyg** | `gen_golden_v2/v3/v4.py`, `measure_chains/dependencies/g4/marginal/market/milestone/ops/selective/sequences/states/variants/verification.py` (3+12=15) | Blandad→Socialism (metodik + legaldomän) |
| **Isolerade experiment** | `exp_dates.py`, `exp_role_check.py`, `exp_span_equiv.py` (3) | Socialism-specifik (datum/roller/span) |
| **Korpus-/infrastruktur** | `export_real_bench.py`, `rank_candidates.py`, `embed_analysis.py` (3) | Socialism-specifik (projektets korpus; `embed_analysis` metodiskt generisk) |

**Antal:** 45 (uppdraget anger "~49" — uppmätt är 45; se §18). De refererar `benchmarks/*.json` och `docs/architecture/gliner2-*.md`.

---

## 12. Fixtures/benchmarks-inventering (`benchmarks/`, 224 committed filer, 10,5 MB)

Storlek uppmätt på två sätt: git-blobbar (committed innehåll) = **10,5 MB / 224 filer**; working tree = **11 MB**. Fördelning: **68 filer på toppnivå + 156 filer i 11 underkataloger = 224**. Största filerna: `real_trajectories_v1.json` 5,6 MB, `bench_real_v2.json` 732 KB, `jev_span_fixtures.json` 360 KB, `real_fixtures/liability-cap.json` 304 KB.

| Familj | Filer (urval) | Antal / ungefärlig storlek | Innehåll | Klassning |
| --- | --- | --- | --- | --- |
| **Syntetisk minimal bench** | `bench_v1.json` | 1 / 4 KB | `name: swe-gym-minimal-bench`, frågor "Q1 lätt", chunks `chunk-00…` | **Generisk form** (syntetisk data, ingen legaldomän) |
| **Fryst legal bänk** | `bench_real_v2.json` (`name: swe-gym-real-legal-v1`) | 1 / 732 KB | 5 svenska avtalsfrågor (auto-renewal, notice-period, liability-cap, confidentiality, carveout), `Avtal_*`-chunks, 2019-frysta JEV-svar | **Socialism-specifik** |
| **Golden questions v2–v4 (toppnivå)** | `golden_v2*` (7), `golden_v3*` (12), `golden_v4*` (3) | 22 / ~300 KB | Forskningsfrågor med facit (`kategori`/`documents`/`evidence`/`conclusion`), svenska avtal, samt mått-/verify-filer | **Socialism-specifik** |
| **Golden v2-fixtures** | `golden_v2_fixtures/` | 61 / 1,6 MB | Frysta JEV/LLM-svar per golden-fråga | **Socialism-specifik** |
| **Frysta JEV-fixtures** | `real_fixtures/` (5), `real_fixtures_deep/` (5), `jev_*` (6) | 16 / ~1,8 MB | Rå JEV-svar med tokens/latens/`raw`-payload; `source: "live JEV capture …"`; `jev_span_fixtures*` för GLiNER2-span | **Socialism-specifik** |
| **Blindtest (redacted)** | `blindtest_*` | 19 / ~220 KB | Generaliseringstest på nya avtal; `"redacted": true` med SHA-256-digest i stället för avtalstext | **Socialism-specifik** |
| **GLiNER2-testset** | `gliner_*` | 8 / ~90 KB | Span-/entitetscases med svensk avtalstext | **Socialism-specifik** |
| **Capture-kataloger (JEV/LLM-svar)** | `dependency_capture/` (37), `milestone_capture/` (25), `states_capture/` (13), `variant_capture/` (6), `action_market/` (1), `chain_synthesis/` (1), `g4_capture/` (1), `oracle_decomp/` (1) | 85 / ~1,1 MB | Frysta JEV/LLM-svar per fråga/behov/operation för offline-uppspelning | **Socialism-specifik** |
| **Trajektorier/inbäddningar/analyser (toppnivå)** | `real_trajectories_v1.json` (5,6 MB), `real_embedding_report.json`, `contamination_analysis.json`, `d2_comparison.json`, `false_resolved_investigation.json`, `postprocessing_arms.json`, `uncertainty_states.json`, `verification_*.{json,txt}` | ~10 / ~5,8 MB | Träningsdata (policy-trajektorier), mätresultat och verifieringsutskrifter | **Socialism-specifik** (data) |

*Familjerna är snitt av samma 224 filer (toppnivå + kataloger); de summerar därför inte till 224.* Exakta räkningar: `find . -maxdepth 1 -type f | wc -l` = 68; `find . -type f | wc -l` = 224; katalogsumma = 156.

**Sammanfattning:** endast `bench_v1.json` är domänfri data; övriga 223 filer är legal-/JEV-/GLiNER2-domän (blindtest-filerna redigerade). `.gitignore` undantar bara `benchmarks/real_embeddings.json` (regenererbar). Inget av detta bör följa med en SWE-extraktion.

---

## 13. Dokumentinventering (kontraktsfakta)

| Dokument | Innehåll | Klassning | Viktiga fakta (file:line) |
| --- | --- | --- | --- |
| `docs/specs/swe-swd-1.0.md` | SWD 1.0-schema, nodtyper, uttryck, kanonisk JSON, isolering, PR-plan | **Generisk kärna** | Nodtyper `:36-42`; uttrycksoperatorer `:44-46`; kanonisk JSON `:52-54`; isolering från kund/feature `:48-50` |
| `docs/specs/swe-runtime.md` | Körande kärna: API, noder, reserverade features, limits, state/paths, completions, events, isolering, research-cutover | **Generisk kärna** (research-avsnittet `:128-163` är produktdomän) | Publik API `:7-27`; stödda noder `:52-66`; preflight-reserverat `:68-74`; limits `:79-86`; events `:107-118`; isolering `:120-126` |
| `docs/specs/swe-provider.md` | `decision(provider)`-nod, choices/routes, exakt cache, Jev-provider | **Blandad** (nod-/cachekontrakt generiska; Jev-provider `:104-118` domän) | Nodformat `:30-51`; effekt `:53-75`; cache-kontrakt `:120-139` |
| `docs/specs/swe-overgraph.md` | Durable run store, katalogisolering, atomiska transitions, resume | **Blandad** (run-store-protokollet generiskt; OverGraph/kataloglayout `:20-39` produktinfra) | `RunRecord`/`InvocationRecord` `:46-74`; atomiska transitions `:76-93`; resume `:95-117` |
| `docs/specs/swe-cutover.md` | Research-cutover, borttagna/behållna funktioner | **Socialism-specifik** (produktens research-integration) | `:1-16`, `:48-110` |
| `docs/specs/swe-inventory.md` | Inventering av research/backend-kod före SWD 1.0 | **Socialism-specifik** | `:18-50` (reuse-lista), `:37-50` (moved to SWE) |
| `docs/SWE_Sweycoins_strategi.md` | Vision/strategi för Sweycoins och självlärande researchmotor | **Socialism-specifik** (SWE är namnet, men innehållet är researchprodukt) | Sweycoins `:38-44`; spekulativ exekvering `:22-36`; arms A–E `:81-87` |
| `docs/SWE_Sweycoins_v2.md` | Gym v2-arkitektur, MDP, ledger-koppling, reuse-matris, experiment 12–32 | **Socialism-specifik / experiment** | Reuse-matris `:136-164`; env-trait `:36-51`; ledger-koppling `:85-97` |
| `docs/SWE_Sweycoins_resultat.md` | Uppmätta PoC-resultat | **Socialism-specifik / experiment** | `:15-60` |

**Slutsats:** de tre förstnämnda specarna innehåller generiska kontraktsfakta som en fristående SWE-repo kan återanvända, men de är skrivna i en produktkontext (backend-paths, OverGraph, Jev, research). `swe-cutover.md`, `swe-inventory.md` och `SWE_Sweycoins_*.md` är produkt-/experimentdokument.

---

## 14. Bygge och CI (fakta som påverkar en extraktion)

| Mekanism | Var | Innebörd |
| --- | --- | --- |
| PyO3-build | `crates/swe-native/pyproject.toml:1-18` (maturin), `Makefile:161-162` (`maturin develop`) | Kärnan distribueras som Python-extension till backend; kräver maturin + CPython ≥3.12. En fristående SWE-repo kan behålla detta som ETT distributionssätt. |
| `make test-swe` | `Makefile:164-166` | Kör `cargo test` på `crates/swe-native` + `pytest tests/test_swe_*.py` i backend. |
| CI-jobb `swe-gym` | `.github/workflows/ci.yml:90-110` | Triggas av `crates/swe-gym/*`, kör `cargo fmt --check` + `cargo test` (offline på ubuntu). Eget jobb — påverkar inte backend. |
| CI-jobb `backend` | `.github/workflows/ci.yml:112+`, filter `crates/*` → backend | Ändringar i `crates/swe-native` triggar backend-sviten (eftersom kärnan är en del av produkten). |
| Workspace | — | Ingen. Varje crate har egen `Cargo.toml`/`Cargo.lock`; `swe-gym` använder path-beroende. En extraktion kräver beslut om gemensam workspace eller separata repos. |
| Rust-version | `crates/swe-native/rust-toolchain.toml:1-3`; båda `Cargo.toml` `rust-version = "1.83"` | 1.83 pinnad; `minreq` valdes för att undvika edition 2024-krav (`Cargo.toml:12-13`). |

---

## 15. Topp 5 risker för fel riktning (sammanfattning för Lead)

1. **Generisk kärna beror på domän (W1–W3).** `provider → strategy::FakeCorpus` (`src/provider.rs:18`), `dataset → real::RealEnv` (`src/dataset.rs:16`), `bench/benchmark/strategy` sammanvävda med `Question{chunks,evidence,coverage}` (`src/bench.rs:17-40`, `src/strategy.rs:14-40`). Att flytta filerna rakt av vore att exportera domän. **Åtgärd:** invertera beroendena först (§7.3).
2. **Research-/legaldomänens material är stort och ligger i produktrepot.** 224 benchmark-filer (10,5 MB committed), 45 verktyg, 15 live-exempel, `ops.rs` och `real.rs`. Risk att det följer med, eller att hemligheter/korpus läcker mellan repo:n. **Åtgärd:** explicit exkluderingslista (denna inventering §10–§12) innan någon extraktion påbörjas.
3. **Domänvokabulär i det som ska bli generiskt protokoll.** `ProviderAnswer.choice = "fynd"/"inget"` (`src/provider.rs:22`, `:60`, `:428-459`), demo-workflowens choices (`src/driver.rs:218`, `:204-236`), svenska kommentarer/utskrifter (`main.rs`). Ett generiskt provider-/kernel-kontrakt måste använda neutrala värden; annars är det inte "beskrivbart utan domänbegrepp".
4. **Host-koppling via `backend/.env`.** Live-exemplen läser produktens `.env` med relativa sökvägar (`examples/live_smoke.rs:14-18`, `examples/live_cap.rs:21-22`, `examples/v2_milestone.rs:99-106`). Får inte bli ett beroende i en fristående repo.
5. **CI/docs är produktkopplade.** `swe-gym` har eget CI-jobb i produktens workflow (`.github/workflows/ci.yml:90-110`), och specarna refererar backend/OverGraph/Jev (`docs/specs/swe-runtime.md:120-126`, `swe-overgraph.md:20-39`). En fristående SWE-repo behöver eget CI + omskrivna kontraktsdokument; annars importeras produktens struktur.

**Positivt:** `swe-native` är redan en ren, generisk kärna med egna tester och utan nätverk — den kan extraheras i stort sett oförändrad (endast metadata + teststrängar). Gymmets generiska kärna är identifierbar och har delvis domänfri testyta (15 strikt generiska tester), men kräver den invertering som beskrivs ovan.

---

## 16. Osäkerheter och avgränsningar

* **Benchmark-storlek:** uppdraget säger "98MB"; uppmätt committed innehåll är 10,5 MB (224 filer) och working tree 11 MB. Skillnaden förklaras av gitignorerade `target/`-kataloger (603 MB) — men jag har inte kunnat belägga varför just "98MB" angavs. **Osäkert.** Siffran i denna rapport är den uppmätta.
* **Antal verktyg:** uppdraget säger "~49"; uppmätt `ls tools/ | wc -l` = 45. Jag har klassificerat alla 45 via filrubriker; exakt innehåll i varje skript har inte lästs rad för rad.
* **`swe-gym/tools` och stora JSON-filer:** jag har läst rubriker/struktur och storlekar, inte öppnat varje fil (särskilt `real_trajectories_v1.json` 5,6 MB). Klassningen av dessa som legaldomän vilar på `source`-fält, nyckelnamn och stickprov.
* **"Offline" för gymmets tester:** verifierat att `cargo test --offline` passerar utan nätverk; jag har inte granskat varje tests källkod för dolda DNS-/socket-anrop, men inga tester använder `Http*`-providers (grep: live-providers endast i `examples/`).
* **Historiska dokumentpåståenden** (t.ex. prestandasiffror i `docs/specs/swe-runtime.md:165-180`) är återgivna som dokumentfakta, inte återmätta av mig.
* **Klassning är en bedömning:** gränsen "blandad" vs "socialism-specifik" för `real.rs`/`ops.rs` är tydlig, men `env.rs`/`strategy.rs` skulle kunna argumenteras vara mer generiska om man inför ett neutralt "budget allocation over workflow branches"-gränssnitt. Jag har valt den strängare tolkningen (kräver domänbegrepp idag).

---

## 17. Evidence — kommandon och resultat

Alla kommandon kördes i `/Users/erikfremred/swe-standalone` (om inte `cd` anges). `export PATH="$HOME/.cargo/bin:$PATH"` före varje cargo-kommando. Inget nätverk användes (`--offline`; live-exempel kördes aldrig).

### E1. Verktygskedja

```console
$ cargo --version && rustc --version
cargo 1.83.0 (5ffbef321 2024-10-29)
rustc 1.83.0 (90b35a623 2024-11-26)
```

### E2. `swe-native` baseline

```console
$ cd crates/swe-native && cargo test --offline
running 18 tests
test result: ok. 18 passed; 0 failed; ...
running 12 tests
test result: ok. 12 passed; 0 failed; ... finished in 0.28s
running 0 tests
test result: ok. 0 passed; ...
```

**Resultat:** 30 tester, 0 fel, offline. (18 unit-tester i `src/{canonicalize,expression,machine/mod}.rs`, 12 integrationstester i `tests/machine.rs`.)

### E3. `swe-gym` baseline

```console
$ cd crates/swe-gym && cargo test --offline
unittests src/lib.rs:      13 passed
tests/bandit_tests.rs:     10 passed   (32.31s)
tests/benchmark_tests.rs:  10 passed   (0.04s)
tests/calibrate_tests.rs:   3 passed
tests/capability_tests.rs:  4 passed   (0.50s)
tests/dataset_tests.rs:     3 passed   (1.68s)
tests/driver_tests.rs:      3 passed
tests/env_tests.rs:        12 passed   (0.44s)
tests/explore_tests.rs:     4 passed   (100.00s)
tests/ledger_tests.rs:      9 passed
tests/provider_tests.rs:    8 passed
tests/real_bench_tests.rs:  7 passed   (54.85s)
tests/real_env_tests.rs:    7 passed   (1.21s)
tests/student_tests.rs:     3 passed   (44.99s)
tests/synergy_tests.rs:     5 passed   (1.22s)
tests/td_tests.rs:          5 passed   (33.93s)
Doc-tests:                  0 passed
```

**Resultat:** 106 tester, 0 fel, offline. Summan verifierades mot `grep -rc '#\[test\]'` (106 förekomster).

### E4. Storlek och filantal

```console
$ wc -l crates/swe-native/src/*.rs crates/swe-native/src/machine/*.rs crates/swe-native/tests/*.rs
# summa 4 282 (varav tests/machine.rs 478) → src 3 804
$ wc -l crates/swe-gym/src/*.rs
# summa 8 745
$ git ls-files crates/swe-native | wc -l                     → 24
$ git ls-files crates/swe-gym | wc -l                        → 333
$ git ls-files crates/swe-gym/src | wc -l                    → 21
$ git ls-files crates/swe-gym/tests | wc -l                  → 15
$ git ls-files crates/swe-gym/examples | wc -l               → 24
$ git ls-files crates/swe-gym/tools | wc -l                  → 45
$ git ls-files crates/swe-gym/benchmarks | wc -l             → 224
$ du -sh crates/swe-gym/benchmarks                           → 11M
$ git ls-files crates/swe-gym/benchmarks | (sum av git cat-file -s)
                                                             → files=224 total_blob_bytes=10.5 MB
$ find crates/swe-gym/benchmarks -maxdepth 1 -type f | wc -l → 68
$ find crates/swe-gym/benchmarks -type f | wc -l             → 224
$ du -sh crates/swe-native crates/swe-gym                    → 111M, 615M
$ du -sh crates/swe-native/target crates/swe-gym/target      → 111M, 603M   (gitignored)
```

### E5. Domänterm-räkning i `swe-gym/src` (Skript: `grep -ric` över `src/*.rs`)

```console
$ for term in fynd inget jev chunk avtal uppsägning legal 2019 gliner; do ...; done
fynd 12, inget 9, jev/JEV 51+51, chunk 245, avtal 23, uppsägning 0,
legal 3, 2019 2, gliner 0, Socialism 0
```

Per modul (`grep -ciE 'fynd|inget|jev|chunk|avtal|uppsägning|legal|2019|gliner'`):

```text
strategy.rs 63/553   provider.rs 57/506  real.rs 43/734   driver.rs 41/263
main.rs 28/938       benchmark.rs 24/516  ops.rs 20/317    bandit.rs 16/686
env.rs 14/1073       gen.rs 12/145        td.rs 6/288      explore.rs 5/318
bench.rs 4/171       student.rs 1/201     (0 i: agent, calibrate, dataset,
ledger, lib, oracle, train)
```

Tolkning: domäntermerna koncentreras till `strategy/provider/real/driver` och saknas helt i de generiska modulerna (`ledger`, `calibrate`, `dataset`, `agent`, `train`, `oracle`, `lib`). Det stöder filklassningen i §5.

### E6. Modulcykler (DFS över `use crate::*`-kanter)

```text
cycles: none
modules with no internal deps (leaves): ['ledger', 'lib', 'main', 'ops']
```

### E7. Importriktning (crate-/backend-nivå)

```console
$ grep -rn 'swe_gym\|swe-gym' backend/
backend/app/services/research/gliner/contract.py:3:  # "Ported from the swe-gym experiments ..."
# (endast en historisk kommentar; inget kodberoende)
$ grep -rln 'swe_gym' backend/app/ | wc -l        → 0
$ grep -rn 'backend/\|Socialism' crates/swe-gym/src crates/swe-gym/Cargo.toml
# (inga träffar i src; endast examples/*.rs refererar ../../backend/.env)
$ grep -rn 'Socialism' crates/swe-native/
crates/swe-native/Cargo.toml:6: description = "... for Socialism Workflow Engine"
crates/swe-native/README.md:3: ... for Socialism Workflow Engine
$ grep -rn 'overgraph\|OverGraph\|JevDecisionCache' crates/swe-gym/src
# (inga träffar)
$ ls Cargo.toml    → No such file (ingen workspace)
```

### E8. Provider-/live-koppling i exempel

```console
$ grep -l 'HttpJevProvider\|HttpLlmProvider' crates/swe-gym/examples/*.rs | wc -l   → 15
$ grep -l 'resolve_secret' crates/swe-gym/examples/*.rs | wc -l                     → 15
$ grep -L 'HttpJevProvider\|HttpLlmProvider' crates/swe-gym/examples/*.rs           → 9 offline
$ grep -l 'RealEnv\|load_real_bench\|real_fixtures\|bench_real' crates/swe-gym/examples/*.rs | wc -l → 16
$ grep -rn 'minreq' crates/swe-gym/src
crates/swe-gym/src/provider.rs:287:        let response = minreq::post(&url)
crates/swe-gym/src/provider.rs:390:        let response = minreq::post(&url)
```

### E9. Externberoenden

```console
$ grep -c '^name = ' crates/swe-native/Cargo.lock   → 42 poster
$ grep -c '^name = ' crates/swe-gym/Cargo.lock      → 52 poster
$ grep -rn 'serde::\|Serialize\|Deserialize' crates/swe-native/src/  → (0 träffar)
```

### E10. `du` för docs/kontraktsdokument

```console
$ wc -l docs/specs/swe-runtime.md docs/specs/swe-provider.md docs/specs/swe-swd-1.0.md \
        docs/specs/swe-cutover.md docs/specs/swe-overgraph.md docs/SWE_Sweycoins_*.md
  180 swe-runtime.md
  165 swe-provider.md
   69 swe-swd-1.0.md
  384 swe-cutover.md
  193 swe-overgraph.md
   96 SWE_Sweycoins_resultat.md
  208 SWE_Sweycoins_strategi.md
  646 SWE_Sweycoins_v2.md
```

---

## Bilaga A — Fil-för-fil-täckning (kontrollista)

Kravet är att varje Rust-källfil (src, tests, examples) täcks av en tabellrad eller en explicit grupprad.

**`swe-native/src` (17/17):** `lib.rs` ✓ §4 · `json.rs` ✓ · `canonicalize.rs` ✓ · `convert.rs` ✓ · `error.rs` ✓ · `events.rs` ✓ · `effects.rs` ✓ · `path.rs` ✓ · `expression.rs` ✓ · `definition.rs` ✓ · `preflight.rs` ✓ · `machine/mod.rs` ✓ · `machine/state.rs` ✓ · `machine/context.rs` ✓ · `machine/schedule.rs` ✓ · `machine/complete.rs` ✓ · `python.rs` ✓.
**`swe-native/tests` (1/1):** `machine.rs` ✓ §4/§9.1.
**`swe-gym/src` (21/21):** `lib.rs` ✓ · `ledger.rs` ✓ · `calibrate.rs` ✓ · `provider.rs` ✓ · `strategy.rs` ✓ · `bench.rs` ✓ · `benchmark.rs` ✓ · `driver.rs` ✓ · `gen.rs` ✓ · `env.rs` ✓ · `oracle.rs` ✓ · `train.rs` ✓ · `agent.rs` ✓ · `td.rs` ✓ · `bandit.rs` ✓ · `student.rs` ✓ · `dataset.rs` ✓ · `explore.rs` ✓ · `real.rs` ✓ · `ops.rs` ✓ · `main.rs` ✓.
**`swe-gym/tests` (15/15):** `bandit_tests.rs`, `benchmark_tests.rs`, `calibrate_tests.rs`, `capability_tests.rs`, `dataset_tests.rs`, `driver_tests.rs`, `env_tests.rs`, `explore_tests.rs`, `ledger_tests.rs`, `provider_tests.rs`, `real_bench_tests.rs`, `real_env_tests.rs`, `student_tests.rs`, `synergy_tests.rs`, `td_tests.rs` ✓ alla i §9.2.
**`swe-gym/examples` (24/24):** fördelade på tre grupper i §10 (15+6+3 = 24) ✓.
**Manifest/övrigt:** `swe-native/{Cargo.toml, Cargo.lock, pyproject.toml, rust-toolchain.toml, README, .gitignore}` ✓ §3/§8/§14; `swe-gym/{Cargo.toml, Cargo.lock, AGENTS.md, .gitignore}` ✓ §3/§8/§14; `tools/` (45) ✓ §11; `benchmarks/` (224) ✓ §12.
