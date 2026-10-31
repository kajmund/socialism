# 08 — Verifieringslogg (Lead)

**Syfte:** samla de kommandon och resultat som utredningens slutsatser vilar på,
så att de kan reproduceras. Inventeringarnas egna Evidence-avsnitt
(`01` §17, `02` §13) och referensexperimentets README innehåller mer detalj.
**Miljö:** worktree `/Users/erikfremred/swe-standalone`, branch
`feat/swe-standalone-investigation`, bas `origin/main` `666eccb0`,
Rust 1.83.0 (cargo 1.83.0), macOS aarch64. Datum: 2026-10-31.
**Ingen nätverksåtkomst:** alla Rust-körningar med `--offline`; inga
modell-, databas- eller HTTP-anrop.

## 1. Rust-kärnan (`crates/swe-native`)

```console
$ cd crates/swe-native && cargo test --offline
running 18 tests
test result: ok. 18 passed; 0 failed; 0 ignored; ...
running 12 tests
test result: ok. 12 passed; 0 failed; 0 ignored; ... finished in 0.26s
running 0 tests
test result: ok. 0 passed; ...
```

**Resultat: 30/30 gröna** (18 unit + 12 integration). Källor:
`crates/swe-native/src/{canonicalize,expression,machine/mod}.rs` (18) och
`crates/swe-native/tests/machine.rs` (12).

Domänord i `swe-native/src` (grep `research|jev|overgraph|gliner`): **4 träffar,
alla ofarliga** — en docstring som säger att kärnan är oberoende
(`src/lib.rs:1`) och tre teststrängar med `prompt_key: research.assessment.user`
(`src/machine/mod.rs:222,249,272`). Inget kodberoende.
(`tests/machine.rs:188-189` har även `provider: "jev"` i testdata.)

## 2. Gym-experimentet (`crates/swe-gym`, oförändrat)

```console
$ cd crates/swe-gym && cargo test --offline   # ~5 min
# 106/106 gröna, exit code 0
```

Per-svit-siffrorna finns i `01-inventory-rust.md` §17 E3 (13 inline + 93
integration; bl.a. ledger 9, benchmark 10, provider 8, env 12, real_bench 7,
real_env 7). Kärnan och experimentet är alltså gröna före utredningen och
påverkas inte av den (inga ändringar i `crates/swe-gym` i denna PR).

## 3. Referensexperimentet (`crates/swe-reference`)

```console
$ cd crates/swe-reference
$ cargo fmt --check                 # inga fel
$ cargo clippy --offline --all-targets -- -D warnings
    Finished `dev` profile ...      # inga varningar
$ cargo test --offline
running 12 tests
test all_required_gate_lists_every_missing_input ... ok
test no_compliant_supplier_is_a_terminal_report_not_a_crash ... ok
test deterministic_comparison_prefers_cheapest_compliant ... ok
test need_more_is_a_typed_operation_outcome ... ok
test needs_are_derived_from_operation_contracts_not_data ... ok
test missing_and_ambiguous_evidence_abstains ... ok
test metering_is_per_action_and_sums_to_the_ledger ... ok
test a_tampered_journal_is_rejected ... ok
test conclusion_is_beta ... ok
test need_more_is_resolved_and_operation_reruns ... ok
test repeated_runs_are_deterministic ... ok
test pause_and_resume_charge_and_execute_exactly_once ... ok
test result: ok. 12 passed; 0 failed; ...
```

`cargo run --offline` (exit 0) visar de tio demonstrationerna. Utdrag ur
utskriften:

```text
[6] Deterministic comparison: lowest price among compliant suppliers
    Beta — 950 SEK
[7] Abstention is a terminal incomplete run with an explicit reason
    terminal status: Incomplete
    conclusion: INSUFFICIENT_EVIDENCE
    reason: ... ALL_REQUIRED gate is missing 1 required input(s): beta.req_c
[8] total: 46000 milli Sweycoin spent of 50000 allocated (4000 remaining);
    67 ledger events; sum(per action) == ledger spent
[9] segment 1 paused at 20000 milli ... 13 completed invocation results journaled
    segment 2 replayed 13 completed invocations without re-running handlers or
    re-charging, then executed 20 new actions
    resumed conclusion: Beta; total spent 46000 milli (uninterrupted: 46000);
    unique invocations executed: 33 (uninterrupted: 33) — nothing ran twice
[10] screen_compliance pass 1: NeedMore
      NeedRef alpha.c_exception — ...
     screen_compliance pass 2: ok (compliant: beta)
Conclusion: Beta (950 SEK) ...
```

**Förbjudna beroenden:** grep `research|overgraph|gliner|socialism|backend|app.jev`
över `crates/swe-reference/{src,tests,Cargo.toml}` → **0 träffar**.

Den enda återanvändningen utanför motorn är `swe_gym::ledger` (budget), vilket är
avsiktligt: ledgern är generisk men bor ännu i experimentcraten. Efter
`05-gym-split.md` G1 ska demon pekas om till `swe-budget`.

## 4. Importriktning (Socialism)

```console
$ grep -rnE "from app\.(config|jev|services)" backend/app/swe/ | wc -l
5        # de kända läckagen: providers.py:15,16,17, definition.py:13,
         # runtime_dispatch.py:17  (blockerare B1, åtgärdas i PR 1)
$ grep -rn "swe_gym" backend/app/ | wc -l
0        # backend importerar aldrig experimentcraten
$ grep -rn "overgraph" backend/app/swe/ | grep -v '"""' | wc -l
0        # endast docstrings, inga importrader
```

## 5. CI

```console
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
CI YAML OK
```

CI ändras bara med ett steg i det befintliga `swe-runtime`-jobbet:
`cargo fmt/clippy/test` + `cargo run` för `crates/swe-reference` (triggas av
`crates/*`-filtret). Inget nytt jobb, ingen ändrad jobbgraf.

## 6. Korsgranskning av Lead-dokumenten

Python-inventeringen korsgranskade `03`/`04`/`06` mot koden och
`02` (sparad som meddelande; ingen separat fil). Resultat: **4 blockerare,
12 viktiga, 13 mindre**. Alla är åtgärdade i dokumenten:

| Fynd | Åtgärd |
| --- | --- |
| B1 `06`: "13 files, 129 test functions" | Rättat till 13 filer / 111 testfunktioner; 129 räknade även de 4+14 research-testerna som stannar |
| B2 `06`: otydlig testflyttsmatris | Explicit matris i `06` §2 #9: 2 filer direkt, 8 efter PR 1, persistence/provider delas, features blir hosttest |
| B3 prompt-renderarens ägare | En linje: SWE-hostpaketet äger den generiska 16-rads-defaulten; dispatch tar injicerad renderare; ingen kopia i Socialism |
| B4 `06` §5: "ingen Rust-toolchain" vid git-tagg | Ersatt med två alternativ (source build vs prebuilt wheel); påståendet får inte göras förrän wheel publicerats |
| I1 `06`: 17+5 flyttbara filer | Rättat till 16 `.py` + JSON oförändrade, 4 inversioner, `features.py` + `providers.py` till Socialism |
| I2 `06`: demot "bevisar flyttade kontrakt" | Rättat: demot bevisar ett domänneutralt applikationslager; befrämjade kontrakt är PR 2 |
| I3 `04`: "PROMOTE" av need-typer som inte finns | Uppdelat i PROMOTE (`NeedRef`, `NeedMore`, reglerna) och BUILD (priority/cardinality/status/unifierad form) |
| I4 `04`: "mandatory provenance" som demot inte uppfyller | Markerar BUILD; demots `source_ref` beskrivs som förenklad källreferens |
| I5 `06`: `filter-repo --path` med glob | Ändrat till `--path-glob 'backend/tests/test_swe_*.py'` |
| I6 `06`: osanerade research-specs | Ändrat till "flytta men sanera/splitta"; research-avsnitten stannar |
| I7–I10 `03`: räkningar, injektionspunkter, domänsträngar | Rättade (§2, §8, §10) |
| I11–I12 + minor: `params` i provider-request, `tests/benchmarks`, radreferenser | Rättade i `04`/`06` |

## 7. Medvetet inte kört

- **Backendens pytest-svit:** kräver byggd `swe_native`-extension och en
  backend-venv som inte finns i worktreen; uppdraget förbjöd bygge i
  inventeringsfasen. Rust-kärnan är i stället byggd och testad direkt (30/30),
  och referensexperimentet (11/11) täcker host-protokollet offline.
- **Live-JEV/LLM-anrop:** inga. Alla "live"-exempel i `swe-gym` är env-gated och
  kördes inte (nätverksförbud i uppdraget).
- **Full `swe-gym`-svit** kördes av inventeringsworkstreamen (106/106, `01` §17
  E3); Lead körde den igen som oberoende kontroll (exit 0, ~5 min).

## 7.1 Ägarbeslut och PR-underlag (2026-10-31, efter granskning)

Projektägaren godkände riktningen med ändrad ordning. Detta lade till fyra
dokument utan att ändra någon produktionskod:

| Dokument | Innehåll |
| --- | --- |
| [`09-contract-decision.md`](09-contract-decision.md) | D1–D5: Rust normativ semantik, versionssatta serialiseringskontrakt, journalens tre tillstånd (försök/bekräftelse/debitering), ramverksgräns, B1 utan för tidig Python-friställning |
| [`10-pr1-b1-python-boundary.md`](10-pr1-b1-python-boundary.md) | PR 1-plan: de fem domänimporterna och exakt vart de flyttar |
| [`11-pr2-b2-core-contracts.md`](11-pr2-b2-core-contracts.md) | PR 2-plan: `swe-core`-typerna, `swe-budget`, Python-projektion, differentialtest |
| [`12-pr3-b3-journal-resume.md`](12-pr3-b3-journal-resume.md) | PR 3-plan: journalkontrakt och vilka garantier som får respektive inte får påstås |

Referensexperimentets README fick ett nytt avsnitt ("What the pause/resume
guarantee is — and is not") som skiljer exakt-engångs**debitering** från
exakt-engångs**exekvering av externa verktyg**. Inga kodändringar; testerna är
oförändrade (11/11).

## 7.2 Ägarens granskning: P1/P2 åtgärdade (2026-10-31)

Ägaren svarade **NO-GO för B1** med tre P1-blockerare plus ett kvarstående P2
i demon. Alla fyra är åtgärdade. Ingen produktionskod är ändrad; P1.1–P1.3 är
kontraktstext, P2 är kod i referensexperimentet.

| Fynd | Vad som kontrollerades | Åtgärd |
| --- | --- | --- |
| P1.1 Journalens identitet/återhämtning | `09` §4.2–4.3 och `12` §2–3: nyckeln innehöll `attempt` men skulle återanvändas vid retry; muterbara statusfält; global recovery; okänd kostnad sattes till noll | `delivery_key` = `sha256(run_id, invocation_id, action)`, stabil över försök; `attempt_id` = leverans + `attempt_no`; journalen är en append-only händelselogg (`AttemptStarted`, `ResultConfirmed`, `AttemptAbandoned`, `ChargeReserved`, `ChargeSettled`, `ChargeReleased`, `ChargePendingReconciliation`); `Delivery` per åtgärd sparas före dispatch; `recompute_pure` för obekräftade rena anrop; `unconfirmed` = okänt utfall; okänd kostnad = `pending_reconciliation`; "exakt-engångsdebitering" ersatt av deduplicerad/at-most-once settlement |
| P1.2 Konfliktpolicyn | `11` §C2.2: bara `min_confidence_bp` var injicerbar; "REJECTED blockerar RESOLVED" motsade `backend/app/services/research/gliner/contract.py:261-327`, där NO/UNCERTAIN blir REJECTED och inte deltar i konfliktberäkningen | Domänen producerar `EvidenceAssessment` (`admissibility`, `equivalence_key`, `conflict_scope`, `operational_role`, `reason_code`, `policy_version`, `provenance`); Rust validerar och äger reduktionen; rejected sparas men blockerar inte; lika `equivalence_key` = ingen konflikt; `uncertain` blockerar bara i deklarerat operativt scope; sex differentialtester |
| P1.3 Prompt-whitelisten | `10` §2 punkt 1 föreskrev fail-open (`None` = allt tillåtet) medan `backend/app/swe/definition.py:152-163` alltid validerar mot `PROMPT_KEY_SET` | Fail-closed: provider-nod kräver injicerad allowlist, saknad allowlist = typat fel, definition utan provider-noder får utelämna den; fyra nya tester; ren strukturvalidering får bara vara ett separat API |
| P2 Demon: `answer: null` | `select_cheapest` kan returnera `answer: null` medan rapportbyggaren läste `name`/`id`/`price_sek` ovillkorligt (`src/operations.rs:542-579`) | Nytt scenario `NoCompliantSupplier` + terminal rapport `NO_COMPLIANT_SUPPLIER` (null supplier/pris med per-leverantör-skäl) och nytt integrationstest |

Verifiering efter ändringarna:

```console
$ cd crates/swe-reference
$ cargo fmt --check                          # rent
$ cargo clippy --offline --all-targets -- -D warnings
    Finished `dev` profile ...                # inga varningar
$ cargo test --offline
    running 12 tests
    test no_compliant_supplier_is_a_terminal_report_not_a_crash ... ok
    ... (11 tidigare, oförändrade)
    test result: ok. 12 passed; 0 failed
$ cargo run --offline ; echo $?               # 0
```

Snabbtest av det nya utfallet (utdrag ur terminal rapport):

```text
STATUS=Completed
conclusion = NO_COMPLIANT_SUPPLIER
conclusion_id = null          price_sek = null
reason = "no supplier meets all three requirements"
supplier_states = Alpha/Beta/Gamma: compliant=false, "requirement B is not met"
evidence_status_counts = { VERIFIED: 12, AMBIGUOUS: 0, REJECTED: 0 }
```

## 7.3 B1 genomfört (2026-10-31) — kontraktsgodkänt, fyra commits

Projektägaren godkände `09` och gav klartecken för B1, med två uttryckliga
krav: prompt-whitelisten ska prövas **både vid kompilering och vid faktisk
exekvering**, och referensexemplet ska förbli regressionstest.

| B1-steg | Vad som gjordes | Commit |
| --- | --- | --- |
| 1. Allowlist-injektion | `compile_definition(..., prompt_keys=...)` fail-closed; `WorkflowResources.prompt_keys`; `assert_providers_registered` validerar vid körning | `2053ea2c` |
| 2. Prompt-renderaren | `app/services/prompt_render.py` → `app/swe/prompt_render.py`; alla anropare uppdaterade; ingen kvarvarande kopia | `3fe6d0a0` |
| 3. JEV-providern | `app/swe/providers.py` → `app/services/research/swe_providers.py` | `3fe6d0a0` |
| 4. Host-kontexten | `WorkflowHostContext`, `workflow_catalog_dir`, `FEATURE_IDS` → `app/services/swe_host/`; `schema.py`/`__init__.py` bara motor-API | `ff944524` |
| 5. Import-gate | `tests/test_swe_import_boundary.py` | `ff944524` |
| — | `prompt_keys` keyword-only (ruff) | `b3a34463` |

### B1-kriteriet: både kompilering och exekvering

Ägarens invändning var att en whitelist som bara gäller i
`compile_definition` inte räcker om en alternativ exekveringsväg kan rendera en
odeklarerad prompt. Därför prövas samma regel två gånger, med samma fail-closed-
semantik:

```console
$ pytest tests/test_swe_definition.py -k prompt -v
test_provider_node_without_prompt_keys_is_rejected           PASSED
test_provider_node_with_injected_prompt_keys_compiles        PASSED
test_unknown_prompt_key_is_rejected_against_injected_set     PASSED
test_definition_without_provider_nodes_needs_no_prompt_keys  PASSED
test_example_uses_catalog_prompt_key                         PASSED
test_unknown_prompt_key_is_rejected                          PASSED

$ pytest tests/test_swe_runtime_preflight.py -k "catalog or permitted" -v
test_execution_rejects_provider_node_without_prompt_catalog        PASSED
test_execution_rejects_prompt_outside_active_catalog               PASSED
test_execution_renders_when_prompt_is_declared_and_permitted       PASSED
```

Den tredje är happy-path-kontrollen: när katalogen är deklarerad **och**
tillåten körs workflowet normalt, så testet bevisar avvisning utan att bevisa
att funktionen är bortkopplad.

### Resultat (faktiska testkörningar, offline)

```console
$ cd backend
$ uv sync --frozen                      # venv skapad, Python 3.13.6
$ uv run maturin develop --manifest-path ../crates/swe-native/Cargo.toml
    Installed swe-native-0.1.0

$ pytest tests/test_swe_*.py tests/test_swe_host_context.py \
         tests/test_swe_import_boundary.py -m "not smoke" -q
125 passed in 13.79s

$ pytest tests/test_swe_*.py tests/test_research_swe -m "not smoke" -q
129 passed in 15.20s      (fyra på varandra följande rena körningar)

$ pytest tests/test_research_swe tests/test_sufficiency_experiment_reuse.py
18 passed

$ cd crates/swe-reference && cargo test --offline
12 passed                 # referensexemplet är kvar som regressionstest
$ cd crates/swe-native && cargo test --offline
30 passed

$ grep -rnE "^\s*(from|import)\s+app\.(config|jev|services)" backend/app/swe/
                          # inga träffar
```

Testantalet i SWE-sviten gick från 118 till 125: fyra fail-closed-tester för
kompilering, tre för exekvering, minus två som flyttades eller slogs samman.

### Befintlig flake — inte orsakad av B1

`tests/test_research_swe/test_wiring.py::test_cancelled_swe_run_is_persisted_as_cancelled`
fallerar **intermittent** när filen körs tillsammans med `test_swe_*`. Den är
tidsberoende (en lease-signal och en store-close kapplöper). Verifierat att
felet finns före B1:

```console
# med B1-ändringarna, 4 rena körningar:      129 passed (×4)
# med oförändrad origin/main-kod, 6 körningar: 1 failed, 114 passed
#                                              115 passed (×5)
```

Flaken ligger alltså i testet, inte i B1, och den enda ändringen jag gjorde i
filen är importvägen för `WorkflowHostContext`. Den bör åtgärdas separat (göra
testet deterministiskt) och **inte** blandas in i B1.

## 7.4 Oberoende kodgranskning av B1 — fynd och rättelser

Projektägarens arkitekturgodkännande ersätter inte kodgranskningen. En oberoende
granskning av `2053ea2c..ddbbe5c3` gav **changes required**. Det mest allvarliga
fyndet var mitt eget fel: jag verifierade aldrig den **fulla** sviten.

| Allvarlighet | Fynd | Rättelse |
| --- | --- | --- |
| **Blockerande** | `app/swe/features.py` togs bort men två `scripts/`-filer importerade den. `tests/test_benchmark_research_swe_v2.py` importerar v2-skriptet → **pytest kunde inte ens samla in** under det filter `CI`-checken använder. Granskaren bevisade att det var en B1-regression (14 passed på basen). | Två importrader → `app.services.swe_host`. Verifierat: 14 passed, och `--collect-only` med CI-filtret ger 0 fel. |
| **Hög** | Import-gaten hade en tyst full bypass: `from app import services` laddade hela appen men matchade inte regexet. Detsamma gällde `importlib`/`__import__`/`exec`/`eval`. | Gaten parsar nu med `ast` (`Import`/`ImportFrom` inkl. `from app import X`), flaggar dynamiska importer och skannar subpaket (`rglob`). Bevisat: vardera kringgåendet får gaten att faila. |
| **Medel** | Ett test kunde aldrig faila: `assert hasattr(...) or forbidden == "FEATURE_IDS"`. Det dolde att `FEATURE_IDS` inte exporterades från `app.services.swe_host`. | `FEATURE_IDS` exporteras nu; escape-hatchen borttagen; två parametriserade tester (host äger namnet / motorn definierar det inte). |
| **Låg** | Planen föreskrev en injicerbar `Renderer` som inte implementerades. | Avsiktligt utelämnad: ingen förhandsskapad abstraktion. `10` §2 är rättad så att planen matchar koden. |
| **Låg** | Kvarvarande gamla sökvägar i `docs/specs/swe-overgraph.md`, `swe-provider.md`, `swe-runtime.md`. | Rättade. |

Granskaren verifierade också positivt (mutationstestade) det som höll: noll
domänimporter, fail-closed vid kompilering **och** exekvering (borttagen grind →
exakt de tester som skulle fånga det failar), att happy-path-testet faktiskt
renderar en prompt (`{'prompt': 'decide', 'prompt_key': 'research.assessment.user'}`
innan `completed`), att filflyttarna är identiska (`git mv`, ingen kopia) och att
`swe_bridge.py`-diffen är en enda kommentarsrad.

### Verifiering efter rättelserna

```console
$ .venv/bin/python -m pytest -m "not smoke and not research_reuse and not swe_runtime" --collect-only -q
4017/4331 tests collected (314 deselected)          # 0 insamlingsfel
$ .venv/bin/python -m pytest -m "not smoke and not research_reuse and not swe_runtime" -q
3981 passed, 36 skipped, 314 deselected in 1045.82s (0:17:25)
$ .venv/bin/python -m ruff check app tests
All checks passed!
$ .venv/bin/python scripts/check_maintainability.py
Maintainability check passed (1405 modules, 52 baselined)
$ .venv/bin/python -m pytest tests/test_benchmark_research_swe_v2.py -q
14 passed
$ .venv/bin/python -m pytest tests/test_swe_*.py tests/test_swe_host_context.py \
    tests/test_swe_import_boundary.py tests/test_research_swe \
    tests/test_sufficiency_experiment_reuse.py tests/test_benchmark_research_swe_v2.py \
    tests/test_check_maintainability.py -q
168 passed
```

`runtime.py` gick över 500-radersgränsen när allowlisten lades till.
`WorkflowResources` flyttades därför till `run_store.py`, där
durable-run-kontraktet och de injicerade resurserna hör ihop; `runtime.py` är
493 rader och maintainability-checken är grön.

**Lärdom som gäller resten av B1–B3:** varje PR ska verifieras med den exakta
kommando-rad CI använder (inklusive `--collect-only`), inte bara de riktade
sviterna. En borttagen modul bryter collection globalt, vilket ruff inte fångar.

## 7.5 Beslut: `make_jev_provider` borttagen (2026-10-31)

Projektägarens princip: en funktion utan produktionsanropare ska inte leva kvar
som generellt gränssnitt "för att den kan bli användbar". Därför undersöktes om
`make_jev_provider` var en faktisk integration eller en övergiven
implementation.

**Undersökningen:**

| Fråga | Svar | Bevis |
| --- | --- | --- |
| Har den produktionsanropare? | **Nej** | `grep -rn make_jev_provider app/` → endast definitionen |
| Vem anropar den? | Endast `tests/test_swe_provider.py` | två tester |
| Hur fattar production-Research sina JEV-beslut då? | Via `fast_controller._decision_from_result` → `classify_research_decision` | `app/services/research/fast_controller.py:255-290` |
| Är det samma frågor/trösklar? | Ja, samma NOUL-frågor och `research_jev_*`-trösklar — men kopplade direkt till det kompakta research-tillståndet, inte till en SWE-provider-nod | `fast_controller.py:263-290` |
| Finns planerad användning? | **Nej** — `docs/specs/swe-provider.md` beskrev den som en framtida adapter, inte som en använd väg | inventering `02` E10 |

**Beslut:** `app/services/research/swe_providers.py` och dess två tester togs
bort. Provider-**kontraktet** (nodformat, `WorkflowResources.providers`,
validering av `choice`, ingen fallback) är oförändrat och fortsatt publik; det
testas fortfarande av de generiska provider-testerna. Att lägga till en
JEV-decision-provider igen är ett Host-ansvar i `app/services/research/`, inte i
motorn.

Rättade dokument: `docs/specs/swe-provider.md` (avsnittet "Jev provider" ersatt
med en beslutsnot), `docs/specs/swe-overgraph.md`, `docs/specs/swe-runtime.md`.

Verifiering efter borttagningen:

```console
$ .venv/bin/python -m ruff check app tests
All checks passed!
$ .venv/bin/python -m pytest tests/test_swe_provider.py -q
11 passed            # de generiska provider-/cache-testerna kvar
$ grep -rn "make_jev_provider\|swe_providers" app/ tests/ scripts/
                     # inga träffar
```

Detta räknas inte som en "ny förmåga" under separationen — det är borttagning av
död kod enligt `AGENTS.md` ("No backwards-compat shims", "remove legacy paths").

## 7.6 B2 genomförd (2026-10-31)

Projektägaren godkände B1 och gav klartecken för B2 med fem acceptanskriterier.
Ordningen behölls: **behov → evidens → operationer → budget → Python-projektion**,
en commit per steg.

| Steg | Leverans | Commit |
| --- | --- | --- |
| C2.1 | `swe-core::needs`: `NeedRef`, prioritet, kardinalitet, status, `derive_needs`, `NeedDiscovery` (loopskydd) | `7ec8f3fe` |
| C2.2 | `swe-core::evidence`: `EvidenceAssessment`, `classify`, `resolve_need` | `231e8af7` |
| C2.3 | `swe-core::operations`: `OperationSpec`, grind, `execute`, `OpOutcome`/`StopReason` | `7de66581` |
| — | Ramverksgrinden som permanent test | `d75446d6` |
| C2.5 | Python-projektion (`app/swe/needs.py`) + adaptörsgrind | `839121b6` |
| C2.4 | `swe-budget`: ledgern ut ur experimentcraten | `af15a396` |
| — | Differentialtester via `swe_native.resolve_evidence` | `6347d2a4` |

### De fem acceptanskriterierna

| # | Krav | Hur det uppfylls | Bevis |
| --- | --- | --- | --- |
| 1 | Rust ensam normativ för övergångar och exekveringsvillkor | `classify`/`resolve_need`/`OperationSpec::gate`/`execute` äger all logik; `NeedStatus` har ingen setter | `crates/swe-native/src/{needs,evidence,operations}.rs` |
| 2 | Python får inte fatta konkurrerande beslut | Adaptern konverterar och läser; `test_swe_core_adapter` failar om den tilldelar/returnerar en motorägd status eller grenar på en | `839121b6` |
| 3 | Differentialtester: samma indata, identiskt utfall | `test_swe_core_differential`, 10 fall genom `swe_native.resolve_evidence` | `6347d2a4` |
| 4 | Research-kontrakt och regressionstester fungerar | `swe_bridge`/research orörda; hela sviten grön | se nedan |
| 5 | Inga juridiska/Socialism-specifika begrepp i generiska typer | `crates/swe-native/tests/boundary.rs` skannar all källkod | `d75446d6` |

### Kriterium 2 och 3 är prövade, inte bara påstådda

Båda grindarna mutationstestades. Det är den del av verifieringen som
faktiskt skiljer "det står i dokumentet" från "det kan inte gå fel":

**Kriterium 2:** att lägga in `if status == "AMBIGUOUS": status = "RESOLVED"`
i adaptern gör `test_swe_core_adapter` rött.

**Kriterium 3:** samma mutation gör differentialtestet rött med
`AssertionError: assert 'RESOLVED' == 'AMBIGUOUS'` — exakt det scenario
projektägaren beskrev. Noterbart: **första mutationsförsöket slog inte igenom**
eftersom strängankaret pekade fel. Det upptäcktes först när utfallet
kontrollerades; ett differentialtest som inte kan faila bevisar ingenting.
Andra försöket verifierade att mutationen applicerats innan testet kördes.

**Kriterium 5:** grinden hittade en riktig kvarleva — kärnans egen
provider-testdata använde `prompt_key: "research.assessment.user"`. Neutraliserad
till `demo.decision.user`.

### Faktiska testresultat

```console
$ cd crates/swe-native && cargo test --offline
  43 passed (lib) + 2 passed (boundary) + 12 passed (machine)     # var 30
$ cd crates/swe-budget && cargo test --offline
  9 passed                        # oförändrade, bara crate-sökvägen bytt
$ cd crates/swe-reference && cargo test --offline
  12 passed                       # referensdemon är kvar som regression
$ cd backend
  pytest tests/test_swe_* ... tests/test_research_swe
  154 passed
  pytest -m "not smoke and not research_reuse and not swe_runtime" --collect-only
  4025/4337 collected, 0 errors
  ruff check app tests          All checks passed
  check_maintainability.py      passed
```

Kärnan gick från 30 till 57 tester, varav 43 är enhets- och gränstester för de
nya kontrakten. `crates/swe-reference` beror inte längre på experimentcraten:
den är nu `swe-native` + `swe-budget`, vilket är rätt form för en domänneutral
host.

### Ramverksgränsen hölls

Ingen ny förmåga tillkom utöver mekanismen. Explicit **inte** byggt, enligt
projektägarens beslut: cache och `ActionOffer`. Kontrakten är förberedda för
dem — behov har stabila id (`subject.fact`), evidens har
`equivalence_key`/`conflict_scope`, operationer har namn och krav, och
budgetposter har idempotensnycklar — men ingressen kommer efter B3.

## 7.7 Oberoende granskning av B2 — fynd och rättelser

En fristående granskning av `5fb83b8d..6347d2a4` gav **changes required**. Den
mutationstestade kärnan och fann den sund — tio mutationer, var och en fångad av
exakt rätt Rust-test — men påpekade att **verifieringen var svagare än den
påstod**. Det stämde.

| Fynd | Bedömning | Åtgärd |
| --- | --- | --- |
| Differentialtestets assertion var en tautologi: den jämförde adapterns läsning av motorns payload med payloadens eget fält | **Riktigt.** Testet kunde inte faila | Ersatt med ett test som pinnar konkurrerande värden hela vägen, plus att adaptern ekar motorns status och avvisar okänd status. **Mutation i Rust** (`if false && ambiguous_scope`) ger nu `'RESOLVED' == 'AMBIGUOUS'` |
| Tre av sex C2.2-scenarier var feldata: rejected-kandidaten hade `key=None` och tog därför "samma nyckel"-vägen i stället för att bevisa att rejected inte blockerar; ekvivalensfallen jämförde redan lika strängar | **Riktigt** | Rejected får egen nyckel, ekvivalens använder två olika råvärden som domänen normaliserar till en nyckel, `uncertain_blocks_scope` prövas i båda riktningarna genom motorn |
| Adapterns "beslutar aldrig"-gate såg bara `Assign`/`Return`; en if-expression, walrus eller assert kunde smuggla in ett beslut | **Riktigt** | Gaten flaggar nu **varje** användning av en motorägd statusliteral utanför vokabulärdefinitionen. Bevisat: en `IfExp` fångas |
| Ramverksgrinden skannade bara `src/`, så testfixtures läckte | **Riktigt** | Skannar nu `tests/` också — och hittade direkt `provider: "jev"` / `prompt_key: "research.assessment.user"` i `tests/machine.rs` samt en "OverGraph sink" i `src/events.rs`. Alla neutraliserade |
| **Påståendet att adapterns payload avvisas av motorn (`need.fact must be a string`)** | **Felaktigt.** Verifierat mot den byggda extensionen: adapterns payload accepteras och ger `RESOLVED` | Ingen åtgärd; granskaren testade mot en annan payload-form än adaptern faktiskt emitterar |

Det är värt att notera **båda** riktningarna: granskaren hittade att mitt test var
en tautologi (allvarligt), och att dess egen blockerare inte reproducerade. Därför
verifieras varje granskningspåstående innan det åtgärdas — inte bara B1 lärde ut
det.

### Verifiering efter rättelserna

```console
$ cd crates/swe-native && cargo test --offline
  43 passed (lib) + 2 (boundary) + 12 (machine)
  mutation (if false && ambiguous_scope)  -> 3 differential tests fail with
                                             'RESOLVED' == 'AMBIGUOUS'; restored
$ cd crates/{swe-budget,swe-gym,swe-reference} && cargo fmt --check
  alla tre gröna
$ cd backend && pytest tests/test_swe_* ... tests/test_swe_core_differential.py
  155 passed
$ .venv/bin/python -m ruff check app tests          All checks passed
$ .venv/bin/python scripts/check_maintainability.py passed (1407 modules)
$ pytest -m "not smoke and not research_reuse and not swe_runtime" -q
  4004 passed, 36 skipped   (19m42s)
```

### Kvarstående, medvetet inte åtgärdat i B2

| Punkt | Skäl |
| --- | --- |
| `crates/swe-reference` använder fortfarande sina lokala `Need`/`OpOutcome`-kopior i stället för `swe-core`-typerna | Demots byteste är 12/12 grönt; omkopplingen är en mekanisk följd som hör till ett eget steg, inte till semantiken. **Måste göras före PR 4** annars finns två sanningskällor för behovstyper |
| Operation-grinden och `derive_needs` saknar Python-bindningar | Kriterium 1 gäller inom Rust; att exponera dem över gränsen hör till när en Research-väg faktiskt använder dem. Får inte påstås vara testat över gränsen |
| `read_operation_outcome` har ingen producent ännu | Samma som ovan — död tills grinden exponeras |
| `EvidencePolicy` saknar `majority_vote` från skissen i `11` | Avsiktligt: ingen ny förmåga under separationen (ägarens princip) |

## 7.8 B3 genomförd (2026-10-31)

Projektägaren godkände B2 och krävde sex saker verifierade i B3: append-only
journal med separata händelser, stabil `delivery_key`, inga dubbla settlements,
korrekt återhämtning av obekräftade externa anrop, versionskontroll vid resume
och crash-/replay-tester vid varje kritisk övergång.

| Krav | Implementerat | Mutation | Fångas av |
| --- | --- | --- | --- |
| 1. Append-only, separata händelser | `AttemptStarted`/`ResultConfirmed`/`AttemptAbandoned`/`ChargeReserved`/`ChargeSettled`/`ChargeReleased`/`ChargePendingReconciliation`; all tillstånd härleds | — | `every_event_is_kept_in_order`, `a_confirmed_attempt_leaves_the_open_set` |
| 2. `delivery_key` stabil över retries | `sha256(run_id, invocation_id, action)`; `attempt_id` lägger på försöksnumret | lägg till ett `attempt`-fält i nyckeln | `the_delivery_key_is_a_pure_function_of_run_invocation_and_action` (pinnar exakt digest) |
| 3. Inga dubbla settlements | `ChargeSettled` på redan settled → `DuplicateSettlement` | tillåt andra settle | `a_charge_cannot_settle_twice` |
| 4. Obekräftat externt anrop | `plan_recovery`: `Pure`→recompute, `Replayable`→kräver resultat, `ExternalIdempotent`→retry med samma nyckel, `ExternalNonIdempotent`→fail stop; okänd kostnad → `PendingReconciliation` | (a) behandla obekräftat som bekräftat, (b) låt irreversibel extern retrya, (c) settla före bekräftelse | (a) `an_unconfirmed_attempt_is_open_not_confirmed`, (b) `recovery_never_reruns_an_external_irreversible_attempt`, (c) `a_charge_cannot_settle_before_its_attempt_is_confirmed` |
| 5. Versionskontroll vid resume | `JournalHeader::verify` prövar schema-version, definition-hash, kontraktsversion och beroendeversioner | (a) skippa definition-hash, (b) skippa beroendeversioner | (a) `resume_rejects_a_changed_definition`, (b) `resume_rejects_a_changed_or_missing_dependency`. **Obs:** i demon jämförs beroendekartan mot en konstant — kontrollen är verkningslös där (granskarens H1, ej åtgärdad) |
| 6. Crash/replay vid varje kritisk övergång | `every_critical_transition_survives_a_pause_and_resume` pausar vid varje mätad åtgärd i tur och ordning | — | kräver samma slutsats, samma spend och samma unika exekveringsantal |

**Den första mutationstabellen täckte bara de sex garantierna och sade
"7 av 7". Det var överdrivet:** en oberoende granskning körde 47 mutationer och
fann **7 som inte fångades**. Det korrekta påståendet är att de sex
garantierna var pinnade, inte att journalen var mutationssäker. De sju missade
låg i kanter som ingen av mina sex tester rörde: en release av en
avstämningspost, en andra reservation för samma leverans, dold
`PendingReconciliation` i `unresolved_charges`, `schema_version` utan
testtäckning, och tre demo-mutationer där versionstesterna jämförde konstanter
med sig själva.

Fem av de sju är åtgärdade (nya regler + tester, mutationsverifierade). Kvar som
känd svaghet: `schema_version`-checken testas bara indirekt, och
`JournalHeader` jämför beroendekartan i en riktning.

Två av mina egna tester fångade inte först:

- **`delivery_key`-mutationen.** Det ursprungliga testet jämförde nyckeln med sig
  själv, så ett försöksnummer i nyckeln gick igenom. Testet pinnar nu den exakta
  digesten av de tre indatafälten. Det här är samma felklass som B2:s tautologi.
- **`contract_version` skrevs aldrig till JSON.** Versionstestet "gick igenom"
  eftersom fältet saknades och läste en default — kontrollen var en
  självuppfyllande profetia. Testet kräver nu att felet *nämner versionen*, och
  serialiseringen rättades.

Båda hittades genom att kontrollera att mutationen faktiskt applicerats och att
fel *orsak* uppstod — inte bara att testet var rött.

### Resultat

```console
$ cd crates/swe-native && cargo test --offline
  62 passed (lib) + 2 (boundary) + 12 (machine)      # var 57 före B3, 76 efter
  clippy -D warnings: 0 issues; fmt --check: clean
$ cd crates/swe-reference && cargo test --offline
  15 passed                                          # var 12
$ cargo run --offline ; echo $?
  0
$ cd backend && pytest -m "not smoke and not research_reuse and not swe_runtime" -q
  (CI grönt: alla 13 checks passerade)
```

### Vad journalen INTE garanterar

Precis som `09` §4.5 säger: **exakt-engångs*utförande* av externa verktyg
garanteras inte**. Det är bara sant när verktyget respekterar `delivery_key`
(`ExternalIdempotent`) eller när åtgärden är ren (`Pure`). För
`ExternalNonIdempotent` är utfallet okänt och run:et stannar. Det står i
journalens egna typer, inte bara i dokumentationen.

## 7.9 B3-granskningen: fyra fynd och deras läge

Den oberoende granskningen av B3 körde **47 mutationer** och gav
`changes required`. Den fann kärnan sund — varje mutation som ändrar
beteende fångades av rätt test — men fyra verkliga problem:

| Fynd | Bedömning | Läge |
| --- | --- | --- |
| **H4: demon använde inte journalen alls.** `Attempt*`/`plan_recovery`/`JournalHeader` hade noll referenser i `swe-reference`; journalen fanns men ingenting konsumerade den. Kriterierna 1, 4 och 6 var bevisade bara av enhetstester på oanvänd API. | **Riktigt och allvarligast** | **Åtgärdat.** Demon bokför varje mätad åtgärd genom kärnans journal: `AttemptStarted` → `ChargeReserved` → exekvering → `ResultConfirmed` → `ChargeSettled`. Händelserna persisteras med demonjournalen och replayas in i en fräsch motorjournal vid resume. Walkthrough skriver ut **132 händelser: 33 försök, 33 bekräftelser, 33 reservationer, 33 settlements** över en pausad och återupptagen körning. Ett nytt test fångade att den återupptagna journalen annars startade tom. |
| **H2: en leverans kunde reservera två kostnader.** `ChargeReserved` kontrollerade `attempt_id` men aldrig `delivery_key`, så två försök av samma logiska leverans kunde var och en reservera och settlementa — mot `09` §4.6.2. | **Riktigt** | **Åtgärdat.** En leverans får högst en reservation; test + mutation. |
| **H3: en okänd kostnad kunde skrivas av som noll.** `ChargeReleased` accepterade en `PendingReconciliation`-post, som då försvann ur operatörens kö med `settled_total() == 0`. | **Riktigt** — motsäger `12` §3.2 och acceptanskriterium 5 | **Åtgärdat.** Typat `Conflict`; test + mutation. |
| **H1: demon jämförde beroendekartan mot en konstant** (`{"mock.supplier_facts": CONTRACT_VERSION}` skickades till `verify` som både inspelade och aktuella versioner). | **Riktigt** | **Ej åtgärdat.** Den inspelade beroendeversionen måste skrivas till fil och läsas tillbaka. Mindre allvarligt: demon har en enda beroendeversion som är låst till bygget, så en kraschande missmatchning kan inte uppstå i praktiken — men kontrollen *påstås* finnas och gör inget. |
| **M1: demon prissätter om vid resume.** Tarifferna ingår inte i `definition_sha256`. | Riktigt | **Ej åtgärdat.** Bör pinnas som `tariff_sha256` i demonjournalen. |

### Vad detta säger om verifieringen

Min första tabell sade "7 av 7 mutationer fångas". Granskarens 47-mutationstest
visade att **7 missades**. Skillnaden är inte kosmetisk: den visar att mina sex
tester täckte *de sex garantierna* men inte journalens kanter, och att jag skrev
ett starkare påstående än underlaget. Tabellen i `7.8` är rättad, och de fem
åtgärdade fynden är mutationsverifierade en och en.

Det är samma mönster som i B2 (tautologin) och B1 (den kringgåbara gaten):
**verifieringen var svagare än självförtroende**. Den enda pålitliga motvikten
har varit den oberoende granskningen, tre gånger i rad.

## 8. Vad denna PR innehåller (scope)

```console
$ git status --short
 M .github/workflows/ci.yml
?? crates/swe-reference/
?? docs/swe-standalone/
```

(tre commits: dokumentation, referensexperiment, CI-rad; därefter
beslutsdokumenten `09`–`12` och denna P1/P2-rättelse)

- Nya dokument `docs/swe-standalone/README.md` + `01`–`12` (denna fil är 08; `09`–`12` är besluts- och PR-underlag).
- Ny crate `crates/swe-reference` (eget `Cargo.lock`, `.gitignore` med `/target`).
- En CI-rad i `swe-runtime`-jobbet.
- **Inga ändringar** i `backend/`, `crates/swe-native`, `crates/swe-gym`,
  produktions-Research eller blindtest v3.
