# 05 — SWE Gym-uppdelning: generisk kärna vs juridiskt domänexperiment

**Status:** Förslag (Fas E), grundat på faktisk kod i `origin/main` `666eccb0` — inte spekulation.
**Worktree:** `/Users/erikfremred/swe-standalone`, branch `feat/swe-standalone-investigation`.
**Beroende:** [`01-inventory-rust.md`](01-inventory-rust.md) (all kod-/fil-/storleksdata), [`03-ownership-matrix.md`](03-ownership-matrix.md) (ägarskap), [`04-public-contracts.md`](04-public-contracts.md) (publika kontrakt, särskilt §5 Budget, §7 Policy, §9 Benchmark), [`06-extraction-plan.md`](06-extraction-plan.md) (målstruktur och PR-ordning).
**Ingen kod ändras av detta dokument.** Alla rader är förslag; inget är flyttat eller raderat.
**Avgränsning:** dokumentet beskriver uppdelningen av `crates/swe-gym` (21 moduler, 15 testfiler, 24 exempel, 45 verktyg, 224 benchmarkfiler) efter att SWE extraherats.

---

## 0. Regel och destinationer

**Regel (samma som 01/03):** en förmåga hör till SWE endast när den kan beskrivas, testas och användas utan Socialisms domänbegrepp. Att gymmet använder en förmåga är inte skäl att flytta den.

| Destination | Betydelse | Motsvarar uppdragets kategori |
| --- | --- | --- |
| `swe-core` | SWE:s generiska kärna (idag `crates/swe-native` + generiska behovs-/evidens-/operationskontrakt) | (b) generisk motorkapacitet |
| `swe-budget` | SWE:s budget-/kostnadsledger (idag `swe-gym/src/ledger.rs`) | (b) generisk motorkapacitet |
| `swe-bench` | SWE:s generiska experiment-/benchmarkpaket: runner, arm-protokoll, replay, kostnadsrapport, golden-evalueringsram, jämförelserapport | (a) generisk gym-infrastruktur |
| `Socialism` | Stannar i produkten/experimentet: legal-/researchdomän, JEV/GLiNER2, svenska avtal, LAS, uppsägningstider, blindtest/golden-fixtures, RL-miljön | (c) Socialism/legaldomän |
| `archive` | Experiment-scaffolding som inte behövs efter uppdelningen (kan tas bort/arkiveras) | (d) experiment-only scaffolding |

`swe-budget` och `swe-bench` är samma målstruktur som `06-extraction-plan.md` §0 redan anger (`crates/swe-budget`, `crates/swe-bench`). Detta dokument konkretiserar innehållet och ordningen.

---

## 1. Svar i korthet

**Finns det en naturlig generisk kärna i dagens `swe-gym`?** **Ja** — men den är smalare än crate-namnet antyder. Sex förmågor är generiska och kan flyttas utan domäntolkning:

1. append-only budgetledger (`src/ledger.rs`),
2. metrad körloop över SWD-effekter (`src/driver.rs:48-187`),
3. A/B-runner med delad ledger och armrapport (`src/benchmark.rs:26-...`, `:68`, `:81`),
4. replay/record av provider-svar (`src/provider.rs:74-228`),
5. arm-protokollet "facit-fri vy + budget in → plan/fortsättning ut" (`src/strategy.rs:170-278`),
6. kostnadsmätning/tariffkalibrering (`src/calibrate.rs`).

**Rekommendation: separat paket `swe-bench` (+ `swe-budget`), inte en generisk "swe-gym" 2.0 och inte en ny parallell implementation.** Skäl:

* Kärnan är sex smala förmågor; resten (MDP-miljö, RL-armar, policyinlärning, legal bench, fixtures) är domänformat. Att generalisera hela crate:n vore att uppfinna ett behov som inte finns och bryta mot reuse-before-new.
* `06-extraction-plan.md` har redan `crates/swe-bench` som mål för "generic experiment runner, strategy arms, frozen replay, golden evaluation".
* En separat crate ger en **testbar gräns**: `swe-bench` kan byggas och testas utan legal domän, och domänexperimentet kan fortsätta i Socialism genom att implementera dess traits.
* **Ingen andraimplementation:** allt som flyttas är befintlig kod som flyttas/refaktoreras; domänarmarna (`strategy.rs:287-553`, `env.rs`, `bandit.rs`, …) stannar och implementerar `swe-bench`s protokoll.

**Gränslinjen (en rad):** `swe-bench` äger *experimentkontraktet* (frysta indata med opaka id:n, arm-protokoll, metrad körning, replay, kostnad, jämförelserapport, held-out-evaluering). `Socialism` äger *betydelsen av indata* (chunk/evidens/coverage, JEV/LLM-klienter, juridiska frågor och facit, LAS/uppsägningstider, RL-miljö och policyer).

**Vad flyttas först (låg risk, hög nytta):**

1. **`ledger.rs` + `tests/ledger_tests.rs` → `swe-budget`** (helt domänfri, redan 9 gröna tester, enda konsumenten i dag är experimentet + `crates/swe-reference`, se §9 G1).
2. **Metrad körmotor + replay/record + minimal runner/arm-protokoll → `swe-bench`** (§9 G2–G3).
3. **Generiska operationskontrakt (`ops.rs`: `NeedRef`, `OperationSpec`, grind, `OpOutcome`, loopen) → `swe-core`** (§9 G4), i linje med `04-public-contracts.md` §4 och `06-extraction-plan.md` §1.1.
4. **Inget annat i denna omgång.** `env.rs`/`agent.rs`/`td.rs`/`bandit.rs`/`student.rs`/`train.rs`/`oracle.rs`/`explore.rs`/`dataset.rs`/`gen.rs`/`real.rs` befrämjas **inte** nu — de är domän- eller experimentkod vars generiska form ännu inte är bevisad (§8).

---

## 2. Modul-för-modul: `crates/swe-gym/src/*.rs` (21 moduler)

| Modul | Ansvar | Domänkoppling | Föreslagen destination | Motivering | Beroenden att bryta |
| --- | --- | --- | --- | --- | --- |
| `src/lib.rs` | Crate-manifest, deklarerar 20 moduler (`:6-24`) | Generisk (manifest) | **Socialism** (kvarvarande domänexperiment) | Efter split äger Socialism experimentcraten; generiska moduler konsumeras från `swe-budget`/`swe-bench` | Ersätt flyttade moduler med `pub use swe_budget as ledger;` (tillfällig, en implementation) tills domänexperimentet arkiveras |
| `src/ledger.rs` | Append-only budgetledger: allocate/reserve/settle/release/transfer/reward, idempotens, replay (`:136`, `:156-450`, `:495`), invariants 1–5 (`:4-18`) | **Generisk** | **`swe-budget`** | Kan beskrivas/testas utan domän (9 tester i `tests/ledger_tests.rs`); identisk med `04-public-contracts.md` §5 "PROMOTE" | Inga interna beroenden (endast `std`). Konsumenter: `driver.rs`, `benchmark.rs`, `strategy.rs`, `bench.rs`, `calibrate.rs`, `env.rs`, `oracle.rs`, `real.rs`, `bandit.rs`, `td.rs`, `dataset.rs` → byt `crate::ledger` mot `swe_budget` |
| `src/calibrate.rs` | Tariffkalibrering från `CallSample{tokens, latency_ms}` under explicit ankare (`:14`, `:22`, `:40`) | **Generisk** | **`swe-bench`** | Ren aritmetik; 3 tester; mäter resurser utan domänbegrepp | `use crate::ledger::Amount` → `swe_budget::Amount` |
| `src/provider.rs` | Provider-seam + implementationer: `ResearchProvider` (`:33`), `FakeCorpus` (`:47`), `ReplayProvider` (`:74`), `RecordProvider` (`:164`), `HttpJevProvider` (`:230`), `HttpLlmProvider` (`:341`), `usage_tokens` (`:316`), `map_llm_word` (`:424`), `map_jev_choice` (`:441`), `resolve_secret` (`:467`) | **Blandad** | **`swe-bench`**: trait, `ReplayProvider`, `RecordProvider`, `usage_tokens`, `json_escape`. **`Socialism`**: `FakeCorpus`, `HttpJevProvider`, `HttpLlmProvider`, `map_jev_choice`, `map_llm_word`, `resolve_secret` | Trait + replay/record är generiska (VCR-mönster); JEV/LLM-klienter, "fynd"/"inget" (`:22`, `:60`) och legal korpus är domän | `use crate::strategy::FakeCorpus` (`:18`) måste bort: `FakeCorpus` flyttar till Socialism eller injiceras. `ProviderAnswer.choice` neutraliseras till opak sträng; replay-nyckel `(provider, chunk_id)` → `(provider, input_key)` (`:79-131`) |
| `src/strategy.rs` | Arm-protokoll: `QuestionView` (`:14`), `Question` (`:28`), `FakeCorpus` (`:70`), `Tariffs` (`:154`), `BranchPlan` (`:170`), `Continuation` (`:181`), `ScanDecision` (`:195`), `trait Strategy` (`:213`), `Observations` (`:257`), armar A/B/C/H/orakel (`:287-553`) | **Blandad** | **`swe-bench`**: den minimala arm-formen (`ArmPlan`, `Continuation`, `Arm`-trait, `Observations` utan chunk-fält). **`Socialism`**: `QuestionView`/`Question`/`FakeCorpus`/`Tariffs`/`ScanDecision`/alla armar | Formen "få en facit-fri vy + budget, returnera brancher/fortsättning" är generisk; `chunks/required_coverage/scan_order` (`:14-24`) och `scan/deep`-tariffer (`:154-168`) är domän | Extrahera neutrala typer; `Tariffs{scan_milli, deep_milli}` (`:154-161`) → generisk `TariffTable(HashMap<provider, Amount>)`; `Question`/`QuestionView` blir domänprojektion av `swe-bench`s `ExperimentQuestion` |
| `src/bench.rs` | Fryst experimentfil: `BenchFile{version,name,score_model,tariffs,total_budget,questions}` (`:17`), facit-isolering via typ, `load_bench` (`:36`), `load_bench_file` (`:141`) | **Blandad** | **`swe-bench`**: laddare + generisk filstruktur (`id`, `budget`, `tariffs`, `score_model`-etikett, opaka fråge-id:n). **`Socialism`**: `Question` med `evidence`/`chunks` | Fryst indatafil med budget/tariffer och facit utanför armen är en generisk experimentidé; evidensmodellen är domän | `use crate::strategy::{Question, QuestionView, Tariffs}` (`:13`) → generisk `ExperimentQuestion`; facitfältet (`evidence: HashSet<String>`) blir domänpålägg |
| `src/benchmark.rs` | A/B-runner: `ArmReport` (`:26-43`), `Harness` (`:52`), `run_arm` (`:68`), `run_arm_with_provider` (`:81`), interleaved brancher, delad ledger, hårt tak | **Blandad** | **`swe-bench`** (generisk runner). `ArmReport`-fälten `found/required` (`:31-32`) blir domänpålägg eller opaka resultat | Körloopen (en provider-call per steg, round-robin, ett gemensamt tak, replay-bar eventlogg) är generisk; "solved/coverage" är research-domän | Import av `strategy::{BranchPlan,Strategy,…}` (`:19-21`) och `provider::ResearchProvider` (`:18`) → `swe-bench`-traits. Hårdkodad klocka `1_000` (`:358`, `:377`, `:448-504`) → injicerad `Clock`. `ArmReport` saknar `data/model/seed` (krav enligt `crates/swe-gym/AGENTS.md` non-negotiable 1) → fält måste byggas |
| `src/driver.rs` | Metrad host-driver: dispatch av `InvokeProvider` (`:48-187`), `reserve→anrop→settle`, hårt tak, loud denial; demo-hjälpare `fake_analyze` (`:189-202`), `build_chain_document*` (`:204-236`), `build_chunk_input*` (`:230-243`) | **Blandad** | **`swe-bench`**: den generiska dispatch-/meterloopen. **`Socialism`**: demo-/chunk-hjälparna | Loopen är den generiska "host driver"-förmågan (samma plats en riktig provider pluggas in); `fake_analyze`/chunk-workflow är domän | Hårdkodad klocka `1_000` (`:60`, `:91`, `:136-168`) → injicerad. `"fynd"/"inget"` (`:196-197`) och `choices` (`:218`) flyttar med demo-hjälparna till Socialism |
| `src/gen.rs` | Deterministisk syntetisk frågegenerator (`:14`), chunk-evidens med "blinda" chunks | **Blandad** | **Socialism** (experiment) | Genererar chunk-/evidensfrågor; generatorlogiken är generisk men används bara av domänexperimentets tester (`tests/bandit_tests.rs`) | Inga för SWE; om en neutral generator behövs senare, skriv en separat i `swe-bench` (inte kopiera denna) |
| `src/env.rs` | v2 budget-manager-MDP: `SweEnv` (`:802`), `SyntheticEnv` (`:813`), `Observation` (`:52`), `Action` (`:103`, 19 handlingar), fyra världar (`:195/346/499/651`), `STRATEGY_COUNT=3 // A retrieval/graph, B JEV, C narrative LLM` (`:25`) | **Blandad** | **Socialism** (experiment) | MDP-formen är generisk men tillstånd/aktioner/kvalitetsmodell är definierade av researchstrategierna A/B/C; att befrämja den vore spekulativt | Inga för SWE nu. Framtida `swe-bench::Environment`-trait får inte införas förrän en andra, icke-legal miljö finns |
| `src/oracle.rs` | Exakt DP-orakel för syntetisk miljö (`:67`, `:87`) | **Blandad** | **Socialism** (experiment/diagnostik) | Diagnostiskt tak för domänmiljön; ingen generisk konsument | Inga |
| `src/train.rs` | Tränings-/evalharnesk: frågeset (`:17`), episodloop (`:54`), `evaluate` (`:87`), `run_season` (`:97`), `calibration_gate` (`:160`) | **Blandad** | **Socialism** (experiment) | Metodiken (calibration gate, held-out) är generisk men typad mot domänmiljön; `swe-bench` får sin egen smala eval-loop, inte denna | Inga för SWE; håll isär syntetiska och verkliga siffror (AGENTS.md non-negotiable 1) |
| `src/agent.rs` | `Policy`-trait (`:25`) + baslinjer (`:85`, `:146`, `:203`) + tabulär MC-Q (`:321`, `:478`) | **Blandad** | **Socialism** (experiment); det smala `Policy`-**kontraktet** hör till `swe-core` enligt `04-public-contracts.md` §7, men implementationerna stannar | Policy-loop generisk; observationer/handlingar domän. Att flytta implementationerna nu vore att exportera MDP:n | `Policy`-kontraktet i `swe-core` ska byggas enligt 04 §7 (allowed actions), inte kopieras från `agent.rs` |
| `src/td.rs` | TD(0)-Sarsa över scan-kedjan (`:28`, `:142`, `:247`) | **Blandad** | **Socialism** (experiment) | RL-algoritm generisk men scan-/eskaleringskedjan domän; inte bevisat generisk | Inga |
| `src/bandit.rs` | Kontextuell linjär bandit (SGD) för djupanropsbudget (`:87`, `:199`, `:326`, `:406`, `:535`) | **Blandad** | **Socialism** (experiment) | Som `td.rs`; kontext/aktioner är researchdomän | Inga |
| `src/student.rs` | Behavior-cloning-elev + LOO-grind (`:18`, `:20`, `:66`, `:167`) | **Blandad** | **Socialism** (experiment) | Metodik generisk; features ur domänobservationen | Inga |
| `src/dataset.rs` | Trajektorieformat v4 (`:19`): observation, action, cost, reward, terminal kvalitet; `record_episode` (`:45`), `load_dataset` (`:244`) | **Blandad** | **Socialism** (experiment) | Formatet är en generisk idé men typat mot `RealEnv` (`:16`) och legal-frågor; att flytta kräver ett env-gränssnitt som inte finns | `use crate::real::{RealEnv, RealQuestion}` (`:16`) — skulle kräva env-trait; skjut upp |
| `src/explore.rs` | Epsilon-/riktad exploration (`:37`, `:84`), `run_exploration` (`:177`), `eval_frozen` (`:265`) | **Blandad** | **Socialism** (experiment) | Refererar JEV-hit rate/stall-gränser; domän | Inga |
| `src/real.rs` | `RealEnv` över fryst legal bänk; A=retrieval (`:36`), B=JEV mot frysta 2019-svar (`:38`, `:554-620`), C maskad; `RealQuestion` (`:63`), `RealPipelinePolicy` (`:620`) | **Socialism-specifik** | **Socialism** | Legal avtalsbänk, 2019-frysta JEV-svar, svenska `Avtal_*`-id:n; kan inte beskrivas utan domänbegrepp | Inga för SWE — får inte flyttas |
| `src/ops.rs` | Typade operationskontrakt: `NeedRef` (`:12`), `OperationSpec`+`gate` (`:40`, `:47-64`), `ExecutionPolicy` (`:27`), `MissingOutcome` (`:32`), `OpOutcome` (`:146`), `investigate_operate_loop` (`:178`); domänexekutorer `max_notice_period` (`:68`), `apply_exception` (`:157`) | **Blandad** | **`swe-core`**: `NeedRef`, `OperationSpec`, `ExecutionPolicy`, `MissingOutcome`, `OpOutcome`, `investigate_operate_loop` + 7 generiska tester. **`Socialism`**: executors + 3 domäntester | Kontraktsstrukturen (gate före exekvering, behov härleds ur spec, `NeedMore`, loopskydd) är generisk och efterfrågas av `04-public-contracts.md` §4/`06` §1.1; uppsägningstid/undantag är legaldomän | Endast `std`-beroenden för de generiska typerna; domänexekutorerna flyttar med sina tester (Avtal_17/18/20). Testvärden i de 7 generiska testerna neutraliseras |
| `src/main.rs` | PoC-demo-binär: budget-cut + armar A/B samt sektioner A–H/J/L (`:34`, `:160`, `:253`, `:312`, `:419`, `:525`, `:685`, `:781`) | **Blandad** | **archive** (eller Socialism-experiment) | Ingen test eller produktionskod anropar den; den demonstrerar domänarmar på svenska och ersätts av `swe-bench`s exempel + `crates/swe-reference` | Inga; om den behålls som experiment-demo ligger den kvar i Socialism |

**Räkning:** 21 moduler → **`swe-budget` 1** (`ledger`), **`swe-bench` 2 hela** (`calibrate`, `benchmark`) **+ 4 delade** (`provider`, `strategy`, `bench`, `driver`), **`swe-core` 1 delad** (`ops`), **`Socialism` 12 hela** (`lib`, `gen`, `env`, `oracle`, `train`, `agent`, `td`, `bandit`, `student`, `dataset`, `explore`, `real`) **+ domändelar av de 5 delade filerna**, **`archive` 1** (`main`). Summan blir 16 hela filer + 5 delade = 21.

---

## 3. Testinventering och destination (106 tester)

| Testfil / inline-modul | Antal | Vad den pinnar | Föreslagen destination | Beroenden att bryta |
| --- | ---: | --- | --- | --- |
| `tests/ledger_tests.rs` | 9 | Reservation/settle/release, idempotens, delegation konserverar budget, reward ospenderbar, replay/resume | **`swe-budget`** (flytta oförändrade, enda ändring är crate-sökväg) | `use swe_gym::ledger` → `swe_budget` |
| `tests/calibrate_tests.rs` | 3 | Kalibreringsformel, skalning, krav på ankare | **`swe-bench`** | `Amount`-import |
| `tests/driver_tests.rs` | 3 | Hårt tak (loud), generös budget, avbruten run replay:as identiskt | **`swe-bench`** (efter att demo-hjälparna flyttats) | Testet använder `build_chain_document`/chunk-input; skriv om mot en neutral provider/workflow i `swe-bench` — samma semantik, inga chunk-namn |
| `tests/provider_tests.rs` | 8 | FakeCorpus bakom trait, JEV-mappning, record→replay, saknad fixture, JSON-escape, LLM-mappning, malformed fixtures, fryst live-fixture | **Delad:** `record_then_replay_round_trips`, `replay_missing_entry_fails_loudly`, `json_escape_handles_quotes_and_controls`, `replay_provider_rejects_malformed_fixtures` → **`swe-bench`**. `corpus_provider_keeps_score_model_v1…`, `jev_answer_mapping…`, `llm_word_mapping…`, `live_jev_fixture_is_frozen_and_loads` → **`Socialism`** | Replay-fixturens nyckelformat `(provider, chunk_id)` → `(provider, input_key)` |
| `tests/benchmark_tests.rs` | 10 | Fryst bench pinnad, armresultat A/B/C/orakel, hårt tak över alla konton, eventlogg-replay | **Delad:** `frozen_bench_is_pinned` (format), `arm_event_logs_replay_identically`, `hard_cap_holds_across_all_branch_accounts` → **`swe-bench`**. De sex armresultat-testerna (`sequential_arm_solves_easy…`, `parallel_arm_pays…`, `hard_question…`, `adaptive_arm_solves…`, `adaptive_arm_ties…`, `oracle_arm…`, `oracle_floor…`) → **`Socialism`** | Armresultat-/coverage-pinning är domän; `swe-bench` testar runner-mekanik med neutrala armar |
| `tests/env_tests.rs` | 12 | MDP-reward, determinism, maskerade actions, budgettak via ledger, reward-pool, orakel, calibration gate, learner | **`Socialism`** (experiment) | Inga för SWE |
| `tests/bandit_tests.rs` | 10 | Generator-determinism, eskalering, SGD, fryst bench, reproducerbar träning, brusig score-modell, generalisering | **`Socialism`** | Inga |
| `tests/td_tests.rs` | 5 | TD-uppdatering, reproducerbarhet, strukturerad korpus, TD vs arm C | **`Socialism`** | Inga |
| `tests/student_tests.rs` | 3 | Facit-fria features, LOO-grind, rollout | **`Socialism`** | Inga |
| `tests/dataset_tests.rs` | 3 | Round-trip, replay till samma kvalitet, fryst dataset | **`Socialism`** | Inga |
| `tests/explore_tests.rs` | 4 | Ceiling-probe, exploration-verdict, riktad exploration, held-out-skydd | **`Socialism`** | Inga |
| `tests/capability_tests.rs` | 4 | Capability-orakel, gate, learner vs regel, kostnad | **`Socialism`** | Inga |
| `tests/synergy_tests.rs` | 5 | Synergi-orakel, gate, delayed return, retrieval-först, stoppkostnad | **`Socialism`** | Inga |
| `tests/real_bench_tests.rs` | 7 | Fryst legal bench, fixtures mot gold, transfer, retrieval-kapitalkostnad, tvåfas-scanner, inbäddningar, replay-armar | **`Socialism`** | Inga — får inte flyttas |
| `tests/real_env_tests.rs` | 7 | Legal fixtures, determinism, reward-summa, retrieval gatar JEV, facit-fria signaler, budgettak, benchmark-jämförelse | **`Socialism`** | Inga — får inte flyttas |
| `src/ops.rs` inline | 10 | 7 generiska: gate blockerar partiella inputs, gate passerar, behov härleds ur spec, missing outcome, oavgjort `NeedMore` två gånger, gate varje runda, unresolved→insufficient. 3 domän: `MAX_NOTICE_PERIOD`-exekutor, två `apply_exception`-fall | **`swe-core`** för de 7 (neutralisera `Avtal_17/18/20` → `doc-a/b/c`); **`Socialism`** för de 3 | Testvärden; domänexekutorerna flyttar med |
| `src/oracle.rs` inline | 3 | DP-orakel mot kända fall | **`Socialism`** | Inga |

**Summering:** 9 + 3 + 3 + 4 + 3 + 7 = 29 tester flyttar till `swe-budget`/`swe-bench`/`swe-core` (varav 7 ops-tester); 77 tester stannar i Socialism. **Krav:** ingen testtäckning får försvinna — varje flyttad test finns exakt en gång i sin nya hemvist; totalen 106 ska kunna räknas ihop i de två hemvisterna.

---

## 4. Exempel (24 filer)

| Grupp | Filer | Antal | Domänkoppling | Destination |
| --- | --- | ---: | --- | --- |
| Live-JEV/LLM-captures (nätverk, env-gated) | `examples/capture_fixture.rs`, `capture_real.rs`, `live_cap.rs`, `live_smoke.rs`, `v2_capture_deep.rs`, `v2_chains.rs`, `v2_dependencies.rs`, `v2_g4.rs`, `v2_market.rs`, `v2_measure.rs`, `v2_milestone.rs`, `v2_oracle_decomp.rs`, `v2_states.rs`, `v2_variants.rs`, `v2_verification.rs` | 15 | Socialism-specifik (JEV/legal/GLiNER2) | **Socialism** — får inte följa med. 15/15 läser `../../backend/.env` (`live_smoke.rs:14-18`, `live_cap.rs:21-22`, `v2_milestone.rs:99-106`) |
| Offline på frysta legal-fixtures | `examples/calibrate.rs`, `replay_arms.rs`, `v2_collect.rs`, `v2_explore.rs`, `v2_real.rs`, `v2_student.rs` | 6 | legaldomän (utom `calibrate`s metodik) | **Socialism** — `calibrate.rs` får en neutral motsvarighet i `swe-bench` (skriven mot generisk `CallSample`/tariff, inte flyttad med JEV-datat) |
| Offline syntetiska (A/B/C-värld) | `examples/v2_capabilities.rs`, `v2_synergy.rs`, `v2_synthetic.rs` | 3 | Blandad/experiment | **Socialism** (experiment) — inte SWE: de är bundna till `env.rs`s domänkonfiguration |

**Inget exempel flyttas till SWE.** `swe-bench` får egna, små exempel (neutrala provider-svar + en arm) i samband med G3.

---

## 5. Verktyg (`tools/`, 45 Python-filer, 452 KB)

Alla 45 stannar i Socialism. Ingen flyttas till SWE.

| Grupp | Filer (antal) | Destination |
| --- | --- | --- |
| GLiNER2/JEV-utvärdering: `analyze_contamination.py`, `eval_gliner.py`, `eval_gliner_arms.py`, `eval_gliner_challenge.py`, `eval_postprocessing_arms.py`, `eval_uncertainty_states.py`, `eval_verification_arms.py`, `eval_verification_h.py`, `eval_verification_stages.py`, `eval_d2.py`, `gen_gliner_testset.py`, `gen_gliner_challenge.py`, `test_challenge.py`, `investigate_false_resolved.py`, `fill_gold_verdicts.py` | 15 | **Socialism** |
| Blindtest/replay: `run_blindtest.py`, `run_blindtest_v2.py`, `blindtest_v2_arms.py`, `blindtest_v2_arms_m3_m4.py`, `blindtest_v2_arms_m5.py`, `blindtest_v2_arms_m6.py`, `d10_blindtest.py`, `replay_d10_v2.py`, `replay_d10_v3.py` | 9 | **Socialism** |
| Golden/mätverktyg: `gen_golden_v2.py`, `gen_golden_v3.py`, `gen_golden_v4.py`, `measure_chains.py`, `measure_dependencies.py`, `measure_g4.py`, `measure_marginal.py`, `measure_market.py`, `measure_milestone.py`, `measure_ops.py`, `measure_selective.py`, `measure_sequences.py`, `measure_states.py`, `measure_variants.py`, `measure_verification.py` | 15 | **Socialism** |
| Isolerade experiment: `exp_dates.py`, `exp_role_check.py`, `exp_span_equiv.py` | 3 | **Socialism** |
| Korpus/infrastruktur: `export_real_bench.py`, `rank_candidates.py`, `embed_analysis.py` | 3 | **Socialism** |

**Motiv:** alla läser/analyserar den juridiska korpusen, JEV-svar, span eller golden-facit; ingen är beskrivbar utan domänbegrepp. Enda generiska värdet är metodiken, som `swe-bench` i stället får i Rust (kalibrering, replay, jämförelserapport). Om ett verktyg senare visar sig domänneutralt kan det flyttas då — inte nu.

---

## 6. Benchmarks/fixtures (224 filer, 10,5 MB committed / 11 MB working tree)

| Familj | Sökväg | Antal / storlek | Destination |
| --- | --- | ---: | --- |
| Syntetisk minimal bench | `benchmarks/bench_v1.json` | 1 / 4 KB | **Socialism** (kan arkiveras; endast domänfri data i mappen, men används av experimentets armar) |
| Fryst legal bänk | `benchmarks/bench_real_v2.json` (`name: swe-gym-real-legal-v1`) | 1 / 732 KB | **Socialism** — innehåller svenska avtal och LAS-/uppsägningstidstexter (`bench_real_v2.json:2390-2424`) |
| Golden v2–v4 (toppnivå) | `benchmarks/golden_v2*` (7), `golden_v3*` (12), `golden_v4*` (3) | 22 / ~300 KB | **Socialism** |
| Golden v2-fixtures | `benchmarks/golden_v2_fixtures/` | 61 / 1,6 MB | **Socialism** |
| Frysta JEV-fixtures | `benchmarks/real_fixtures/` (5), `real_fixtures_deep/` (5), `jev_*` (6) | 16 / ~1,8 MB | **Socialism** |
| Blindtest (redacted) | `benchmarks/blindtest_*` | 19 / ~220 KB | **Socialism** |
| GLiNER2-testset | `benchmarks/gliner_*` | 8 / ~90 KB | **Socialism** |
| Capture-kataloger | `dependency_capture/` (37), `milestone_capture/` (25), `states_capture/` (13), `variant_capture/` (6), `action_market/` (1), `chain_synthesis/` (1), `g4_capture/` (1), `oracle_decomp/` (1) | 85 / ~1,1 MB | **Socialism** |
| Trajektorier/analyser (toppnivå) | `real_trajectories_v1.json` (5,6 MB), `real_embedding_report.json`, `contamination_analysis.json`, `d2_comparison.json`, `false_resolved_investigation.json`, `postprocessing_arms.json`, `uncertainty_states.json`, `verification_*.{json,txt}` | ~10 / ~5,8 MB | **Socialism** |

*Familjerna är snitt av samma 224 filer (68 toppnivåfiler + 156 i kataloger); de summerar därför inte exakt till 224.*

**Ingen benchmarkfil flyttas till SWE.** Största enskilda filen `real_trajectories_v1.json` (5,6 MB) är träningsdata för domänpolicyn. `.gitignore` undantar bara `benchmarks/real_embeddings.json` (regenererbar).

---

## 7. Vad som INTE får följa med `swe-gym` (konkret lista)

Detta är den exkluderingslista som en extraktion måste respektera. Siffror från `01-inventory-rust.md` §2/§10–§12.

| Kategori | Konkreta sökvägar | Storlek/antal | Skäl |
| --- | --- | --- | --- |
| **Juridisk bänk + frysta svar** | `crates/swe-gym/src/real.rs`, `benchmarks/bench_real_v2.json`, `benchmarks/real_fixtures/`, `benchmarks/real_fixtures_deep/` | 734 rader + 732 KB + 916 KB + 188 KB | Svenska avtal, 2019-frysta JEV-svar, LAS-referenser |
| **LAS/uppsägningstider/undantag** | `crates/swe-gym/src/ops.rs` (exekutorerna `max_notice_period:68`, `apply_exception:157`), `benchmarks/bench_real_v2.json:2390-2424`, `benchmarks/real_fixtures/notice-period.json` | se ovan | Legaldomän; `bench_real_v2.json` innehåller uttrycklig LAS-text och uppsägningstidstabell; 151 filer i `benchmarks`/`tools`/`src` innehåller anställnings-/uppsägningstermer |
| **Blindtest/golden-facit** | `benchmarks/blindtest_*` (19), `benchmarks/golden_v2*`/`golden_v3*`/`golden_v4*` (22), `benchmarks/golden_v2_fixtures/` (61) | ~3,3 MB | Facit till legal-frågor; blindtest är dessutom redigerat (`"redacted": true`) |
| **GLiNER2/JEV-utvärdering** | `benchmarks/gliner_*` (8), `benchmarks/jev_*` (6), `benchmarks/*_capture/` (85), `tools/` (45 filer) | ~1,2 MB + 452 KB | Span-/entitets- och JEV-forskning; ingen kod i `swe-gym/src` refererar GLiNER2 |
| **Live-providers och hemligheter** | `crates/swe-gym/src/provider.rs:230-506` (`HttpJevProvider`, `HttpLlmProvider`, `resolve_secret`), `examples/` (15 live-exempel) | 276 rader + 15 filer | Kräver nätverk/API-nycklar och läser `../../backend/.env` |
| **All benchmarkdata** | `crates/swe-gym/benchmarks/**` (224 filer) | 10,5 MB committed | Domändata; endast `bench_v1.json` är domänfri men används bara av domänarmar |
| **Alla Python-verktyg** | `crates/swe-gym/tools/**` (45 filer) | 452 KB | Domänanalys ovanpå legal-/JEV-data |
| **Domänarmar/RL-miljö** | `src/{env,agent,td,bandit,student,train,oracle,explore,dataset,gen,main}.rs` | 5 259 rader | Research-MDP, svenska utskrifter, syntetiska chunk-frågor; generisk form inte bevisad |
| **`crates/swe-gym` som helhet i SWE-repot** | `crates/swe-gym/**` | 333 filer | 06 §0: domänexperimentet är uttryckligen icke-mål för SWE-repot |

**Praktisk gate (föreslagen CI-kontroll i SWE-repot):**

```sh
# Ska ge 0 träffar i swe-core/swe-budget/swe-bench/swe-bindings (ej tester/fixtures):
grep -rniE 'fynd|inget|jev|gliner|avtal|uppsäg(ning)?stid|\bLAS\b|blindtest|golden_v|real_fixtures|backend/\.env' \
  crates/swe-core crates/swe-budget crates/swe-bench crates/swe-bindings
```

---

## 8. API-gräns för det generiska gymmet (`swe-bench`)

`04-public-contracts.md` §9 delegerar detaljerna hit. Kontraktet ska bestå av: **en runner över kompilerade definitioner med deterministisk klocka, frysta/replayade provider-svar, Sweycoin-mätning, golden-evaluering, arm-gränssnitt och en rapport som anger data, modell, seed och kostnad. Domänbenchmarks och fixtures ingår inte.**

| Förmåga | Befintlig kod | Redan generisk nog? | Vad som måste byggas/refaktoreras |
| --- | --- | --- | --- |
| **Experiment runner** (kör en arm mot en kompilerad SWD-definition, en provider-call per steg, terminal status) | `src/benchmark.rs:52-...` (`Harness`), `:68` (`run_arm`), `:81`; `src/driver.rs:48-187` | **Nej, nästan** | Injicera `Clock` (i dag hårdkodat `1_000` i `driver.rs:60,91,136-168` och `benchmark.rs:358,377,448-504`). Byt `strategy::{Strategy,Question}`/`provider::ResearchProvider` mot `swe-bench`-traits. Rapporten (`ArmReport:26-43`) saknar `data/model/seed` → bygg fält enligt AGENTS.md non-negotiable 1 |
| **Strategy arms** (facit-fri vy + budget in; brancher/fortsättning ut; observe/revise-hooks) | `src/strategy.rs:170-278` (`BranchPlan`, `Continuation`, `Strategy`) | **Nej** | Behåll formen men gör `QuestionView` opak: `ExperimentQuestion { id, budget, tariffs, opaque: Json }`; `Tariffs{scan,deep}` (`:154-168`) → `TariffTable`. Domänarmarna implementerar traitet i Socialism |
| **Frysta/replayade model-/provider-svar** | `src/provider.rs:33-44` (`ResearchProvider`), `:74-228` (`ReplayProvider`, `RecordProvider`, fixture-format) | **Ja, till största delen** | `ProviderAnswer.choice: "fynd"/"inget"` (`:22`) → opak sträng; replay-nyckel `(provider, chunk_id)` (`:79-131`) → `(provider, input_key)`; `FakeCorpus`-beroendet (`:18`) bort |
| **Replay/reproducerbarhet** (samma indata + frysta svar + samma klocka ⇒ identisk rapport) | `ReplayProvider`, `Ledger::replay` (`ledger.rs:495`), deterministisk maskin (swe-native) | **Ja, med klockfixen** | Dokumentera replay-kontraktet (clock + fixtures + tariffs + seed) i `swe-bench`; `docs/SWE_Sweycoins_*.md` har domänversionen, inte SWE-kontraktet |
| **Kostnadsmätning** (reservation per anrop, deduplicerad debitering, per-run total, loud denial) | `src/ledger.rs` (`:156-450`, `:495`); `src/driver.rs:69-92` (reserve→call→settle) | **Ja** | Flytta ledger till `swe-budget`; exponera `CostReport { run_id, invocation_id, action, tariff_milli, amount_milli, idempotency_key }` + per-run total (04 §5 "BUILD") |
| **Golden evaluation** (hållen-ute-frågor, facit utanför armen, score) | `src/bench.rs:17-40` (`QuestionView` vs `Question`), `src/train.rs:87` (`evaluate`) | **Nej** | Generisk form: `GoldenQuestion { id, required_items: Vec<OpaqueId>, budget, tariffs }` där domänen äger vad ett item betyder. Håll isär `swe-bench`s eval-loop från domänens `train.rs` (som har calibration gate/orakel) |
| **Policy-jämförelse** (flera armar på samma frågeset, samma budget; diagnostiska tak markerade) | `src/benchmark.rs:26-43` (`ArmReport`, `diagnostic`-fältet), `src/ledger.rs`-baserade jämförelser; `tools/measure_*.py` är domänens efterhandsanalys | **Nej** | `ComparisonReport { dataset, arms: Vec<ArmReport>, seed, cost }`; `ArmReport.diagnostic` (`:28`) är redan rätt princip (orakel är tak, inte contender). Seed/data/modell måste in i rapporten; domänens Python-analys flyttar inte |

**Föreslagen minimal publik yta** (skiss, ingen kod ändras nu; namn avstämda med `04-public-contracts.md` §5/§7/§9):

```rust
// swe-budget
pub type Amount = u64;                       // milli-enheter, heltal
pub struct Ledger { /* som idag */ }
pub struct CostRecord { pub run_id: String, pub invocation_id: String, pub action: String,
                        pub tariff_milli: Amount, pub amount_milli: Amount,
                        pub idempotency_key: String }

// swe-bench
pub struct ExperimentQuestion { pub id: String, pub budget_milli: Amount,
                                pub tariffs: TariffTable, pub payload: Json }
pub struct ArmPlan { pub account: String, pub start_budget_milli: Amount }
pub enum Continuation { /* neutral: Continue, Stop, Replan */ }
pub trait Arm { fn name(&self) -> &'static str;
                fn plan(&self, q: &ExperimentQuestion) -> Vec<ArmPlan>;
                fn observe(&mut self, view: &ObservationView) -> Continuation; }
pub struct ProviderRequest<'a> { pub provider: &'a str, pub input_key: &'a str, pub input: &'a str }
pub struct ProviderAnswer { pub choice: String, pub score_bp: u32, pub latency_ms: u64, pub raw: String }
pub trait Provider { fn analyze(&self, req: &ProviderRequest<'_>) -> Result<ProviderAnswer, String>; }
pub struct ReplayTable { /* (provider, input_key) -> ProviderAnswer */ }
pub fn run_arm(arm: &mut dyn Arm, q: &ExperimentQuestion, provider: &dyn Provider,
               clock: &dyn Clock) -> ArmReport;      // ArmReport har data/model/seed/cost
pub struct ComparisonReport { pub dataset: String, pub model: String, pub seed: u64,
                              pub arms: Vec<ArmReport> }
```

Gränsdragning i en rad: **inget i `swe-bench` får veta vad en "chunk", "fynd" eller ett avtalsdokument är; det får bara veta att en provider svarar på en nyckel med ett val och att en arm fördelar en budget.**

---

## 9. Migrationssekvens

Följer `06-extraction-plan.md` §8: PR 2 (befrämja ledger/kontrakt i monorepot), PR 6 (gym split). Inget steg kräver en andra implementation — allt flyttas/refaktoreras. Varje steg håller monorepot grönt.

### G0 — Denna utredning (PR 0)

* Leverans: detta dokument + `01`/`03`/`04`/`06`.
* Grind: dokumenten granskade; ingen kodändring; `cargo test --offline` oförändrat (se §11).

### G1 — `swe-budget`: flytta ledger (låg risk, först)

* Flytta `crates/swe-gym/src/ledger.rs` → `crates/swe-budget/src/lib.rs` (eller modul) + `tests/ledger_tests.rs` oförändrade.
* `swe-gym` konsumerar `swe-budget`; `src/ledger.rs` blir en ett-rads `pub use swe_budget::*;` tills domänexperimentet arkiveras (samma implementation, ingen kopia).
* Uppdatera `crates/swe-reference` (`crates/swe-reference/Cargo.toml`; `src/host.rs:18`, `src/journal.rs:14`, `src/lib.rs:83`) från `swe_gym::ledger` → `swe_budget` (ingår i 06 PR 2 "reference demo re-pointed").
* **Acceptans:** 9 ledger-tester gröna i `swe-budget`; `cargo test --offline` grönt i `swe-gym` och `swe-reference`; `grep -rn 'swe_gym::ledger' crates` = 0 utom Socialism-experimentet.

### G2 — `swe-bench`: metrad körmotor med injicerad klocka

* Extrahera den generiska dispatch-/meterloopen ur `src/driver.rs:48-187` till `swe-bench`; behåll `fake_analyze`/`build_chain_*`/`build_chunk_*` i Socialism.
* Inför `Clock`; befintliga anrop får en `FixedClock(1_000)` som default så att pinnade tester är oförändrade.
* **Acceptans:** `tests/driver_tests.rs` semantik (hårt tak, generös budget, identisk replay) finns som neutralt test i `swe-bench`; inga chunk-/fynd-strängar i den nya koden; `swe-bench` har inga beroenden till `swe-gym`.

### G3 — `swe-bench`: replay/record + arm-protokoll + runner

* Flytta generisk `ResearchProvider`-trait (neutraliserad), `ReplayProvider`, `RecordProvider`, `json_escape`, `usage_tokens`; flytta/refaktorera `benchmark.rs`-runnern och `strategy.rs`:s minimala arm-typer; flytta `bench.rs`-laddarens generiska fält.
* Domänimplementationerna (`FakeCorpus`, `HttpJev`, `HttpLlm`, `map_*`, `resolve_secret`, armar, `Question`, `Tariffs{scan,deep}`) stannar i Socialism och implementerar `swe-bench`-traits.
* Rapporten: lägg till `data`, `model`, `seed`, `cost` i `ArmReport`/`ComparisonReport` (AGENTS.md non-negotiable 1).
* **Acceptans:** en neutral, påhittad arm + fryst provider-fixture körs offline i `swe-bench` med identisk replay; domänexperimentets 106-testsvit fortsätter grönt (med `swe-gym` som konsument); exkluderings-gaten (§7) ger 0 träffar i `swe-bench`.

### G4 — `swe-core`: generiska operationskontrakt

* Flytta `NeedRef` (`ops.rs:12`), `OperationSpec`/`gate` (`:40-64`), `ExecutionPolicy`, `MissingOutcome`, `OpOutcome` (`:146`), `investigate_operate_loop` (`:178`) + de 7 generiska testerna till `swe-core` (neutralisera `Avtal_*`-värden).
* Lämna `max_notice_period` (`:68`), `apply_exception` (`:157`) + 3 domäntester i Socialism.
* **Acceptans:** generiska gate-/loop-tester gröna i `swe-core`; `ops.rs` i Socialism innehåller bara executors; `crates/swe-reference` kan använda `swe_core`-typerna (om/när den utökas — i dag har den egna demo-typer, vilket är OK).

### G5 — Socialism-städning och CI

* Ta bort flyttade moduler ur `crates/swe-gym`; crate:n konsumerar `swe-budget`/`swe-bench` från SWE-taggen och behåller endast domän-/experimentmaterial (legal bench, armar, RL, fixtures, tools, exempel).
* CI: monorepots `swe-gym`-jobb (`.github/workflows/ci.yml:90-110`) behålls för domänexperimentet; SWE-repot får `swe-core`/`swe-budget`/`swe-bench`/`swe-reference`-jobb. Ta inte bort monorepo-jobbet innan domänexperimentet är arkiverat.
* **Acceptans:** ingen kodduplicering (`grep` för ledger-/runner-implementationer = 1 träff per förmåga); domänexperimentet kör fortfarande offline; SWE-repot innehåller 0 juridiska filer (§7-gaten).

### Vad som raderas/arkiveras

* `src/main.rs` (PoC-demo) → **archive** när `swe-bench`s exempel + `crates/swe-reference` täcker demonstrationen. Ingen test/pkod anropar den (verifierat: inga `use swe_gym::main`, binär är enda konsumenten).
* Inget annat raderas i denna plan. Domänexperimentet behålls tills ett explicit beslut fattas (cratens exit criteria i `crates/swe-gym/AGENTS.md`).

---

## 10. Risker och acceptanskriterier

| Risk | Sannolikhet | Påverkan | Mildring |
| --- | --- | --- | --- |
| Över-generalisering: `env.rs`/RL-armarna befrämjas innan en andra domän bevisar formen | Medel | Hög (spekulativ API, bryter reuse-before-new) | **Befrämja inte** env/RL nu; endast ledger, meter, replay, runner-interface, kostnad, generisk gate |
| Domän läcker in i `swe-bench` via "fynd"/"inget"/chunk-namn | Hög om ingen gate | Hög (samma problem igen) | CI-gate i §7; tester i `swe-bench` använder neutrala värden (`yes`/`no`, `item-a`) |
| Klockinjektion ändrar pinnade resultat | Medel | Medel | `FixedClock(1_000)` som default; befintliga pinnar oförändrade; nya tester använder explicit klocka |
| Rapport-schema utan data/modell/seed uppfyller inte ärlighetskravet | Hög (saknas i dag) | Hög (resultat ej trovärdiga) | Bygg fälten i G3 innan någon "generisk bench"-siffra publiceras |
| Dubbla implementationer uppstår | Låg om planen följs | Hög | Flytta, refaktorera, `pub use`-re-export (en implementation); ingen ny arm/ledger/runner skrivs i Socialism |
| Tester tappas vid flytt | Medel | Medel | Räkna 106 → nya hemvister; varje flyttad test finns exakt en gång; CI räknar collected tests |
| `swe-reference` bryts av ledgerflytten | Hög (den importerar `swe_gym::ledger`) | Låg/medel | Ingår i G1: peka om till `swe_budget` innan gamla sökvägen tas bort |

**Acceptanskriterier för hela uppdelningen:**

1. `swe-budget`, `swe-bench`, `swe-core` bygger och testar offline utan Socialism-beroenden; §7-gaten ger 0 träffar.
2. 9 ledger-tester flyttade oförändrade och gröna i `swe-budget`.
3. 29 flyttade/förädlade tester (9 ledger + 3 calibrate + 3 driver + 4 provider + 3 benchmark + 7 ops) finns exakt en gång i SWE-hemvist; resterande 77 stannar i Socialism; totalen 106 kan räknas ihop.
4. `crates/swe-reference` använder `swe_budget` (och förblir domänneutral; se dess README).
5. Inga filer från `benchmarks/`, `tools/` eller live-exemplen finns i SWE-repot (grep + `git ls-files`-kontroll).
6. Domänexperimentet i Socialism kör fortfarande offline (`cargo test --offline`) med oförändrade domänresultat.
7. `swe-bench`-rapporten anger data, modell, seed och kostnad; syntetiska och verkliga siffror blandas inte.
8. Ingen parallell implementation: ledger, runner och replay finns på exakt ett ställe.

---

## 11. Evidence — kommandon och resultat

Körda i `/Users/erikfremred/swe-standalone` med `export PATH="$HOME/.cargo/bin:$PATH"`. Inget nätverk; inga live-exempel kördes. Fullständig inventerings-evidens finns i `01-inventory-rust.md` §17.

### E1. Baslinjer (oförändrade av denna utredning)

```console
$ cd crates/swe-native && cargo test --offline
running 18 tests  → 18 passed
running 12 tests  → 12 passed        (tests/machine.rs, 0.28s)

$ cd crates/swe-gym && cargo test --offline
unittests src/lib.rs 13 passed
bandit_tests 10, benchmark_tests 10, calibrate_tests 3, capability_tests 4,
dataset_tests 3, driver_tests 3, env_tests 12, explore_tests 4, ledger_tests 9,
provider_tests 8, real_bench_tests 7, real_env_tests 7, student_tests 3,
synergy_tests 5, td_tests 5
→ 106 passed, 0 failed (≈4,5 min; tunga sviter: explore 100s, real_bench 55s,
  student 45s, td 34s, bandit 32s)
```

### E2. Fil-/testräkning

```console
$ git ls-files crates/swe-gym/src | wc -l       → 21
$ git ls-files crates/swe-gym/tests | wc -l      → 15
$ git ls-files crates/swe-gym/examples | wc -l   → 24
$ git ls-files crates/swe-gym/tools | wc -l      → 45
$ git ls-files crates/swe-gym/benchmarks | wc -l → 224
$ grep -rc '#\[test\]' crates/swe-gym/src crates/swe-gym/tests | (summa) → 106
$ du -sh crates/swe-gym/{tools,examples,benchmarks} → 452K, 180K, 11M
```

### E3. Generisk kärna vs domän (grep-mått)

```console
$ grep -ric -E 'fynd|inget|jev|chunk|avtal|uppsägning|legal|2019|gliner' crates/swe-gym/src/*.rs
strategy.rs 63/553   provider.rs 57/506  real.rs 43/734   driver.rs 41/263
main.rs 28/938       benchmark.rs 24/516  ops.rs 20/317    bandit.rs 16/686
env.rs 14/1073       gen.rs 12/145        td.rs 6/288      explore.rs 5/318
bench.rs 4/171       student.rs 1/201     0 i agent/calibrate/dataset/ledger/
                                            lib/oracle/train
```

Slutsats: de generiska modulerna (`ledger`, `calibrate`, `dataset`, `agent`, `train`, `oracle`, `lib`) är helt fria från domäntermer; domäntermerna klustrar i `strategy`/`provider`/`real`/`driver` — exakt de filer som delas i §2.

### E4. Felriktade beroenden som måste brytas för `swe-bench`

```console
$ grep -n 'use crate::' crates/swe-gym/src/provider.rs  → :18 use crate::strategy::FakeCorpus
$ grep -n 'use crate::' crates/swe-gym/src/dataset.rs   → :16 use crate::real::{RealEnv, RealQuestion}
$ grep -n 'use crate::strategy' crates/swe-gym/src/bench.rs crates/swe-gym/src/benchmark.rs
bench.rs:13, benchmark.rs:19-21
$ grep -rn 'use crate::real' crates/swe-gym/src             → dataset.rs:16 (endast)
```

### E5. LAS/uppsägningstid är verklig domändata (inte antagande)

```console
$ grep -rn '\bLAS\b' crates/swe-gym/benchmarks/bench_real_v2.json | head -3
bench_real_v2.json:2390: "...huvudregeln för anställningar enligt LAS."
bench_real_v2.json:2393: "...enligt 4 § lagen (1982:80) om anställningsskydd (LAS)."
bench_real_v2.json:2421: "12.1 Uppsägningstiden följer 11 § LAS. ..." (tabell)
$ grep -rl 'anstallning\|anställning\|uppsägning\|uppsagning' \
    crates/swe-gym/{benchmarks,tools,src} | wc -l
151
```

### E6. Host-koppling i live-exempel

```console
$ grep -l 'HttpJevProvider\|HttpLlmProvider' crates/swe-gym/examples/*.rs | wc -l → 15
$ grep -l 'resolve_secret' crates/swe-gym/examples/*.rs | wc -l                   → 15
$ grep -rn 'backend/\.env' crates/swe-gym/examples | wc -l                         → 16
```

### E7. Referensexperimentet konsumerar ledgern (måste pekas om i G1)

```console
$ grep -rn 'swe_gym' crates/swe-reference/{Cargo.toml,src,tests}
Cargo.toml: swe-gym = { path = "../swe-gym" }
src/host.rs:18: use swe_gym::ledger::{Amount, Ledger};
src/journal.rs:14: use swe_gym::ledger::{Amount, Event, EventKind};
src/lib.rs:83-84: impl From<swe_gym::ledger::LedgerError>
```

### E8. Målstrukturen finns redan beslutad i 06

```console
$ grep -n 'swe-budget\|swe-bench' docs/swe-standalone/06-extraction-plan.md | head
28: ├── swe-budget/   # Sweycoin ledger + cost report (promoted from swe-gym/src/ledger.rs)
31: ├── swe-bench/    # generic experiment runner, strategy arms, frozen replay, golden evaluation
72: | crates/swe-gym/src/ledger.rs + tests/ledger_tests.rs | crates/swe-budget/ | ...
73: | Generic types in crates/swe-gym/src/ops.rs | crates/swe-core/src/operations.rs | ...
```

---

## 12. Osäkerheter och beslutspunkter

1. **`ops.rs`-delningen** är en bedömning: kontraktsstrukturen (gate, `NeedMore`, loopskydd) är generisk, men den är i dag bara använd av den juridiska domänen. `03-ownership-matrix.md` §5 och `04-public-contracts.md` §4 säger samma sak; om inget annat behov finns kan den ändå skjutas upp utan att blockera ledger/meter-extraktionen. **Beslutspunkt.**
2. **Golden evaluation i `swe-bench` eller `swe-core`?** Facit-isolering och held-out-utvärdering är generisk experimentinfrastruktur (→ `swe-bench`), men behovs-/evidenssemantiken hör till `swe-core`. Jag föreslår `swe-bench` med opaka item-id:n; `swe-core` äger behovs-/evidenstyperna. Alternativet (allt i `swe-core`) skulle göra kärnan större än nödvändigt. **Beslutspunkt före G3.**
3. **`env.rs`/RL-mekanikens framtid:** inte befrämjad nu. Om en andra, icke-legal miljö uppstår kan ett `Environment`-trait bli aktuellt — men det ska bevisas med en riktig andra konsument, inte antas.
4. **`src/main.rs` som archive:** den är en demo utan testberoende; om teamet vill behålla den som pedagogisk demo i Socialism är det ofarligt. Ingen kodändring krävs.
5. **`swe-reference`-beroendet** är en känd följd: efter G1 måste den använda `swe_budget`. Det är en mekanisk ändring men rör en annan agents leverans (`crates/swe-reference`) och ska samordnas.
6. **Storlekar:** 10,5 MB committed / 11 MB working tree / 224 filer är uppmätta i denna worktree; uppdragets "98MB" kunde inte beläggas (se `01` §16).
