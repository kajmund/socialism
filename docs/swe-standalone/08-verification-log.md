# 08 — Verifieringslogg (Lead)

**Syfte:** samla de kommandon och resultat som utredningens slutsatser vilar på,
så att de kan reproduceras. Inventeringarnas egna Evidence-avsnitt
(`01` §17, `02` §13) och referensexperimentets README innehåller mer detalj.
**Miljö:** worktree `/Users/erikfremred/swe-standalone`, branch
`feat/swe-standalone-investigation`, bas `origin/main` `666eccb0`,
Rust 1.83.0 (cargo 1.83.0), macOS aarch64. Datum: 2026-10-31.
**Historik:** loggen är kronologisk. Poster före B4 avser `backend/app/swe`
och `backend/tests`; poster efter B4 avser `python/swe` och `python/tests`.
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

### Tidigare flake — nu deterministiskt stängd

`tests/test_research_swe/test_wiring.py::test_cancelled_swe_run_is_persisted_as_cancelled`
fallerar **intermittent** när filen körs tillsammans med `test_swe_*`. Den är
tidsberoende (en lease-signal och en store-close kapplöper). Verifierat att
felet finns före B1:

```console
# med B1-ändringarna, 4 rena körningar:      129 passed (×4)
# med oförändrad origin/main-kod, 6 körningar: 1 failed, 114 passed
#                                              115 passed (×5)
```

Flaken låg alltså i test-/exekveringsgränsen, inte i B1. Den är nu stängd genom
att `execute_attempt_research` kontrollerar write-fencen omedelbart efter den
returnerade SWE-loopen. Testet kräver därför deterministiskt `CancelledError`
och verifierar därefter att run-store-statusen är `cancelled`; samma fyra
wiring-tester körs nu i CI tillsammans med sufficiency-reuse-sviten.

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
| C2.3 | `swe-core::operations`: `OperationSpec`, grind, `execute`, `OpOutcome`/`StopReason` (`execute`, `Investigation` och `StopReason` borttagna i B4 — ingen konsument) | `7de66581` |
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

## 7.10 Befintlig flake i `test_ready_execute_returns_persisted_panel_result`

Backend-shard 1 fallerade i CI två gånger i rad på:

```
tests/test_execution_api.py::test_ready_execute_returns_persisted_panel_result
  > assert result["evidence_refs"]["E1"]["ordinal"] == 0
  E assert 1 == 0
```

Det finns ingen ändring i min PR som rör den vägen: `git diff 666eccb0..HEAD`
rör endast en importrad i `app/services/sme_panel_chat.py` (flytten av
`prompt_render`), ingenting i `app/api/execution.py`, `app/services/panel/` eller
`answer_review`.

**Verifierat att felet är befintligt**, på samma sätt som `test_wiring`-flaken i
B1 — genom att checka ut orörd `origin/main` (`666eccb0`) i en tillfällig
worktree och köra samma fil upprepat:

```
baseline (666eccb0), tests/test_execution_api.py:
  run 1: 36 passed
  run 2: 36 passed
  run 3: 1 failed, 35 passed      <-- samma test
```

Mot min branch: 5/5 gröna isolerat och 36/36 i filen. Felet är alltså
ordnings-/tidsberoende och finns före B1–B3. Den tillfälliga worktreen togs bort
efter mätningen (`git worktree list` verifierad).

**Åtgärd:** ingen i denna PR. Flaken bör fixas separat (testet verkar anta att
en evidensreferens får ordinal 0, vilket inte är garanterat när
panelsessionen bygger referenserna). Att röra den vore att blanda in en
oberoende bugg i en arkitektur-PR.

## 7.11 Runda 8: journal-roundtrip, H1/M1, operationstyper i demon, Python-bindningar

Projektägarens lägesbild var skarpare än min: **B1 stängd, B2/B3 kärnimplementation
stängd, B2/B3 integrationsbevis fortfarande öppet, PR #458 inte mergeklar, GO
väntar.** Den här rundan stängde integrationsbeviset och de öppna
journalfrågorna, i den ordning ägaren angav.

### 1. Journal v1: förlustfri och fail-closed roundtrip

Ägarens fynd bekräftades alla fyra:

| Fynd | Före | Nu |
| --- | --- | --- |
| Saknad `contract_version` | blev automatiskt aktuell version | **obligatoriskt fält**, frånvaro ger typat fel |
| Saknad/felskriven `journal_events` | blev en tom logg | **obligatoriskt**, måste vara en array |
| Tids-/tariffält | kunde bli `0` | **obligatoriska** |
| `ResultConfirmed` | bara en bool → Ok/Error/Cancelled kollapsade | **förlustfri kodning**, payload bevaras |

### 2. H1 och M1

- **H1:** journalen spelar nu in den beroendekarta den körde under, och
  `validate()` jämför den mot **den aktuella** kartan. Kärnans jämförelse är
  symmetrisk: ett beroende som världen kräver men journalen aldrig spelade in
  avvisas också.
- **M1:** tarifferna pinnas av `tariff_sha256` — självkonsistens prövas vid
  inläsning, och vid resume jämförs de mot den återuppspelande värden.

### 3. Demon konsumerar kärnans operationsmodell

- `NeedRef` re-exporteras från `swe_native`; demon mappar leverantör → `subject`
  och faktum → `fact`.
- `OperationResult` omsluter kärnans `OpOutcome` (`Answer`, **singulär**
  `NeedMore(NeedRef)`, `InsufficientEvidence(GateFailure)`) och bär bara den JSON
  handlern returnerar. **Kärnan breddades inte till en lista** — demon väljer
  första upptäckta behov deterministiskt per runda.
- Nytt `TwoExceptions`-scenario: en runda upptäcker två saknade fakta, och
  `several_discovered_needs_are_resolved_over_several_rounds` visar att de löses
  över flera rundor, att varje extra runda kostar pengar och att budgeten går
  jämnt ut.

### 4. Python-bindningar

`swe_native.derive_needs` och `swe_native.operation_gate` exponerar kärnans
behovshärledning och grind. Adaptern (`read_operation_gate`,
`read_derived_needs`) rapporterar motorns utfall och omtolkar det aldrig.
Differentialtesterna täcker härledda behov och fyra grindsituationer.

### Mutationstabell — rättad efter granskning

Min första tabell sade "5 av 5". **Det var fel:** den oberoende granskningen
körde **40 mutationer och fann 12 missade**. Tabellen täckte de fall jag valt
att pröva, inte den yta som fanns — samma övertro som i B3.

| Garanti | Mutation | Fångas av |
| --- | --- | --- |
| Obligatorisk `contract_version` | återinför default | `a_journal_without_a_contract_version_is_refused` |
| Obligatorisk `journal_events` | återinför tom logg | samma (helpern panikar nu om fältet saknas) |
| Förlustfri utfallskodning | koda `Err` som `Cancelled` | `an_error_outcome_does_not_become_a_cancellation` |
| Ok-payload bevaras | nolla payloaden | `ok_payload_survives_the_round_trip` |
| Okänd utfallstyp | acceptera den | `an_unknown_outcome_kind_is_refused` |
| Alla händelsetyper | tappa en typ | `every_event_kind_round_trips` |
| Tariff-hash prövas vid inläsning | hoppa över | `a_tampered_tariff_hash_is_refused` |
| Resume prövar **hostens** tariffer | ignorera config | `a_journal_replayed_under_other_tariffs_is_refused` |
| Skrivvägen pinnar faktiska tariffer | skriv default | `a_run_priced_with_custom_tariffs_round_trips_and_resumes` |
| Beroenden jämförs inspelat mot aktuellt (H1) | jämför mot sig själv | `a_journal_recording_another_dependency_version_is_refused` |
| Grinden avvisar ofullständig indata | `if true` | `test_the_gate_can_never_report_ready_with_a_missing_input` |
| Grinden rapporterar **varför** | status → `UNRESOLVED` | `test_the_gate_reports_the_status_that_blocked` |

**Fem mutationer som granskningen fann och som nu är stängda:**

1. `drop_top_level_field` var en tyst no-op när fältet saknades → tre av fyra
   fältkontroller bevisade ingenting.
2. `CompletionOutcome`-kodningen hade inget direkt test, och demo-resumen
   använder `completed[].output`, inte `journal_events` → `Err → Cancelled` och
   Ok-payloaden var opinnade.
3. Tariff-fästet jämförde filen mot sig själv; `ResumeConfig` saknade hostens
   tariffer och `RunConfig::with_tariffs` hade noll anropare.
4. De två nya differentialtesterna för Python-bindningarna var tautologier
   (`read == f(engine)`).
5. `derive_needs`-testet pinnade bara id:n och defaultvärdena.

**Kvar som dokumenterad svaghet:** `OperationSpec::gate` använder
`states.iter().find(..)`, så om samma behov förekommer två gånger i statuslistan
avgör ordningen. Bindningen matchar Rust exakt (ingen divergens), men det bör
antingen avvisas eller dokumenteras innan grinden blir ett offentligt kontrakt.

### Resultat

```console
crates/swe-native     80 tester   (66 lib + 2 boundary + 12 machine)
crates/swe-budget      9 tester
crates/swe-reference  32 tester   (5 codec + 27 integration); walkthrough exit 0
backend SWE+research 163 tester; ruff och maintainability rena
CI                    alla 13 checks gröna
```

## 7.12 Tredje kända flaken: `test_lagen_nu_connection_release`

Backend-shard 1 föll på:

```
tests/test_lagen_nu_connection_release.py::test_four_cached_needs_leave_connection_available_during_routing[True]
  sqlalchemy.exc.TimeoutError: QueuePool limit of size 1 overflow 0 reached,
  connection timed out, timeout 0.20
```

**Bedömning: tidskänslig, inte orsakad av denna branch.** Testet använder
avsiktligt en pool med **storlek 1 och timeout 0,2 s** för att bevisa att
anslutningen släpps före externa anrop; fyra samtidiga `gather`-anrop ska rymmas
i tur och ordning. Under CI:s fyra parallella shards räcker 200 ms inte alltid.

Bevis:

- ingen fil i den vägen (`lagen_nu`, `connection_release`, `LegalResearchResult`)
  ändras av PR:en: `git diff --name-only 666eccb0..HEAD` ger noll träffar;
- testet passerar 4/4 på orörd `origin/main` i en tillfällig worktree, och 3/3
  isolerat på denna branch, samt 3/3 omgångar tillsammans med grannsviterna.

Till skillnad från de två andra flakerna kunde jag alltså **inte** reproducera
den på baslinjen. Det svagare men ärliga påståendet är: den rörs inte av
ändringen, den är konstruerad med en 200 ms-timeout, och den föll en gång i CI.
Den bör åtgärdas separat (t.ex. genom att höja timeouten eller göra testet
deterministiskt), inte blandas in i en arkitektur-PR.

## 7.13 Runda 9: sista B3-kompletteringen inför GO

Projektägarens beslut: stäng den sista skulden, verifiera gränserna, flytta
sedan SWE — och lägg inte till cache, `ActionOffer` eller andra nya förmågor.

### 1. En grind, inte två

`all_required`, `GateResult` och `MissingInput` är **borttagna** ur
referensdemon. `gate_inputs` projicerar nu demots evidens på kärnans
`NeedStatus` och anropar `swe_native::OperationSpec::gate`; demon formaterar bara
kärnans svar. Den enda regel som finns kvar i demon är mappningen
Verified/Ambiguous/Rejected → Resolved/Ambiguous/Unresolved, vilket är demots
eget vokabulär — inte en regel.

Mutationsbevis:

| Mutation | Fångas av |
| --- | --- |
| Demon ignorerar kärnans utfall (`_ => Ok(None)`) | **5 tester**, bl.a. `the_demo_cannot_accept_an_input_the_engine_refuses` |
| Demon mappar `AMBIGUOUS` som användbar | **4 tester** |

### 2. Dubblerade statusposter avvisas

`OperationSpec::gate` returnerar nu `Result<(), GateError>`:

```rust
pub enum GateError {
    DuplicateState { need: NeedRef },
    Unsatisfied(GateFailure),
}
```

- Dubbletter prövas **först**, så en dubblerad post kan aldrig bli en tyst
  "första träff".
- Även två **identiska** statusar avvisas: en behovspost som beskrivs två gånger
  är en felaktig anropssignal, oavsett om värdena råkar stämma.
- Felet namnger den `NeedRef` som är dubblerad och är deterministiskt: första
  behovet som återkommer, i indataordning.
- Det är **inte** en abstention: `unsatisfied()` är `None` och strängen börjar
  inte med `INSUFFICIENT_EVIDENCE`. En bugg i värden får inte förklä sig som en
  slutsats om världen.
- Python-bindningen kastar `ValueError` med behovet namngivet.
- Regeln har **en** implementation: `ensure_unique_state`, som både
  `OperationSpec::gate` och `execute` anropar. Resolver-skyddet i `execute` är
  ingen andra validering utan **prevention**: det hindrar loopen från att skapa
  den dubblett valideringen skulle avvisa. `execute` validerar före loopen,
  så `max_rounds = 0` inte kan förvandla en felaktig statuslista till ett
  `RoundLimit`-avslut.

Ordningsoberoendet prövas från båda sidor — kärnan kräver samma fel för båda
ordningarna, och Python-testet ställer samma krav **oberoende av
engine-payloaden** (`pytest.raises`, fyra ordningskombinationer, plus ett test
att en dubblett inte rapporteras som `INSUFFICIENT_EVIDENCE`).

Mutationsbevis:

| Mutation | Fångas av |
| --- | --- |
| Ta bort dubblettkontrollen i `gate` | **5 kärntester + 6 Python-tester** (de två `execute`-testerna fångas av `execute`s egen förkontroll, se nedan) |

### 3. Ny verifieringsstandard

`13-verification-standard.md` införs som **granskningskrav**. Det finns därför
att samma felform återkommit i B1, B2, B3 och runda 8. Kärnan i kravet:

1. varje differentialtest ska visa oberoende exekveringsvägar eller en separat
   förväntad specifikation — aldrig `assert read == f(engine)`;
2. varje kritiskt test ska paras med minst en mutation som bevisar att testet
   kan upptäcka felet, och mutationen ska **bevisas ha applicerats**;
3. en sanning får bara ha en implementation — testet ska visa att konsumenten
   anropar källan, inte att en kopia stämmer;
4. en grind får inte tyst välja vid tvetydig indata;
5. ett fel får inte kunna förklä sig som ett svar.

### 4. Granskningsfynd som stängdes i samma runda

Den sista oberoende granskningen fällde den första versionen av denna runda på
fem punkter. Alla är åtgärdade:

| Fynd | Vad som var fel | Nu |
| --- | --- | --- |
| **B1** `test_swe_core_differential.py:85` | `assert projected["status"] == read_need_state(engine)["status"]` — exakt den förbjudna formen `read == f(engine)`. Kunde aldrig upptäcka en divergens. | Varje fall bär en **separat förväntad status** (`CASES`), och både motor och adapter prövas mot den literalen. Mutationsbevis: låter adaptern rapportera `AMBIGUOUS` som `RESOLVED` blir **7 tester röda**. Före rättelsen gav samma mutation **2** röda — båda i tester som jämförde mot explicita literaler; det tautologiska kärntestet gav 0. |
| **B2** `execute()` | Kastade `GateError::DuplicateState` som `StopReason::InsufficientEvidence` — Req 5 bruten, och nåbar både via anroparens statuslista och via en resolver som svarar för ett redan känt behov. | `execute` returnerar `Result<Investigation, GateError>`; endast `Unsatisfied` blir en slutsats. Statuslistan valideras **före** loopen, så även `max_rounds = 0` avvisar en dubblett i stället för att rapportera `RoundLimit`. Tre nya tester. **B4 tog bort `execute`, `Investigation` och `StopReason`:** ingen produktionskonsument fanns, och loop-skyddet duplicerade `NeedDiscovery`. |
| **B3** denna sektion | Saknade standardens egna redovisningskrav. | Denna tabell. |
| **M4** `Screening::Insufficient` | Demon avgjorde lokalt (`if !entry.is_verified()`) och motorn anropades bara för att bekräfta; grenen var otestad och en mutation förbi anropet förblev grön. | `screen_candidate` frågar `gate_inputs` **först** och grenar på motorns utfall. Nytt `AmbiguousException`-scenario gör grenen nåbar; testet kräver statusen `AMBIGUOUS` i payloaden. En lokal kopia som återanvänder demots egen mappning kan producera samma sträng — det är bevisat grönt — men **källmutation** fäller testet (5 röda), liksom det gamla lokala beteendet (1 röd). Delegationen är alltså bevisad, inte strängen. |
| **M5/M6/M7** | "enda implementationen" gällde inte repo-vid täckning (`swe-gym` har en egen grind, G4); gym sades ha 13 tester (faktiskt 97); `swe-reference` README/lib/evidence sade att grinden var applikationslager. | Påståendet skopat till `swe-native` + `swe-reference` med gym-dubbletten namngiven som G4; siffran rättad; dokumenten uppdaterade. |

Mindre fynd som också stängdes:

- dubblettnamnet var inte pinnat till indataordning (lexikografisk implementation
  förblev grön) → nytt test där första dubbletten **inte** är minst, plus
  mutation;
- `gate_failure_json` hade inget test → ny payload-assertion (`missing[].need`,
  `missing[].status`, `detail`), plus mutation;
- `Screening::Insufficient` tappade `missing` ur payloaden → rättat, och
  upptäcktes av det nya testet.

**Kvar som dokumenterad svaghet:** `execute()` är publik men bara anropad från
tester idag. Dess `Result`-form är rätt, men gränssnittet bör ses över när en
riktig värd börjar använda det.

### 5. Redovisning enligt 13-verification-standard.md

Standardens avsnitt *Tillämpning* kräver fyra rader. Här är de:

| Krav | Redovisning |
| --- | --- |
| Nya kritiska tester **med vilken mutation som bevisar var och en** | Se tabellen nedan. |
| Missade mutationer | **12 av 40** i runda 8 (rapporterade i `7.11`). I den första versionen av runda 9 hittade granskningen **9 missade**: B1-self-jämförelsen, `execute`-armen, `gate_failure_json`, `Screening::Insufficient`, gym-siffran, tre dokumentfynd (`swe-reference/README.md`, `src/lib.rs`, `src/evidence.rs`) och indataordningen — alltså 9 punkter, inte 8. Alla nio är stängda. Kvar som dokumenterad svaghet: `execute`-gränssnittet är publik API men bara anropad från tester. |
| Differentialtest-audit | Alla 31 tester i `test_swe_core_differential.py` genomgångna: nio fall jämför nu mot `CASES`-literaler och båda sidor prövas; den tidigare självjämförelsen är borttagen. `test_need_projection_emits_the_wire_shape` döptes om eftersom den aldrig anropar motorn; `test_unknown_role_counts_as_competing_in_both_layers` prövar nu båda sidor. Kvarvarande jämförelser är mot explicita literaler eller mot motorns payload i rent formatkontrollsyfte. |
| Grön baslinje efter varje återställning | Bekräftad efter varje mutation: `swe-native` 74 lib-tester, `swe-reference` 30 integrationstester (+ 5 codec), Python 31 differentialtester. |

**Vilken mutation bevisar vilket test** (alla uppmätta på denna tree, inte
härledda):

| Test | Bevisande mutation | Röda |
| --- | --- | --- |
| `the_gate_is_the_engines_and_lists_every_missing_input` | `gate_inputs` ignorerar motorns utfall | 5 |
| `the_demo_cannot_accept_an_input_the_engine_refuses` | mappar `AMBIGUOUS` som användbar | 4 |
| `a_discovered_fact_the_engine_refuses_stops_the_investigation` | lokal `GateFailure` i stället för motorns anrop | 1 |
| `the_refusal_payload_reports_every_missing_input_and_its_status` | `gate_failure_json` tappar `missing` | 2 |
| de fem grindtesterna för dubbletter | tar bort den enda regeln (`ensure_unique_state` → `Ok`) | 7 kärntester (de fem + `a_zero_round_budget_cannot_hide_a_duplicate` + `execute_refuses_a_caller_supplied_duplicate_instead_of_abstaining`) |
| (samma) | samma mutation **plus** borttaget resolver-skydd | 8 kärntester |
| `execute_refuses_a_caller_supplied_duplicate_instead_of_abstaining` | tar bort förkontrollen **och** återställer armens `DuplicateState` → `InsufficientEvidence` | 2 (denna + `a_zero_round_budget_cannot_hide_a_duplicate`); enbart den första åtgärden fäller inte denna test, men ger 1 rött totalt (`a_zero_round_budget_cannot_hide_a_duplicate`) |
| `execute_refuses_a_duplicate_that_the_resolver_creates` | tar bort resolver-kontrollen **och** återställer armens `DuplicateState` → `InsufficientEvidence` | 1; **enbart den första åtgärden ger 0** |
| `a_zero_round_budget_cannot_hide_a_duplicate` | tar bort förkontrollen före loopen | 1 |
| `the_named_duplicate_follows_input_order_not_identity_order` | namnger lexikografiskt minsta dubblett | 1 |
| fyra Python-fall för ordningar + namn + inte-abstention | tar bort dubblettkontrollen i `gate` | 6 (Python) |
| `test_engine_and_projection_both_match_the_specification` m.fl. | adaptern rapporterar `AMBIGUOUS` som `RESOLVED` | 7 |

### Resultat

```console
crates/swe-native     88 tester   (74 lib + 2 boundary + 12 machine)
crates/swe-budget      9 tester
crates/swe-reference  35 tester   (30 integration + 5 journal codec); walkthrough exit 0
crates/swe-gym       97 tester   (17 targets)
backend SWE+research 170 tester; ruff och maintainability rena
```

## 7.14 B4: fristående paketering

B4 skulle göra B1–B3 flyttbara utan att lägga till förmågor. Fem steg, i den
ordning ägaren angav:

| Steg | Resultat |
| --- | --- |
| 1. Root Cargo-workspace | `swe-native`, `swe-budget`, `swe-reference` är medlemmar; `swe-gym` är explicit exkluderad (eget governance, egna fixtures, egen CI-jobb). En root-lock ersätter tre. Release-profilen flyttade till root — annars hade den tyst ignorerats. CI kör nu exakt `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace`. `swe-gym` byggs dessutom i CI när kärn-craterna ändras, eftersom den path-beroende gym-craten annars kunde brytas utan att någon grind märker det. |
| 2. Python-paket | `backend/app/swe/**` → `python/swe/**` med `python/pyproject.toml`. **129 `app.swe`-bärande rader (130 förekomster) i 44 filer** (mätt med `git diff --no-renames 9d17b096..HEAD -- '*.py'`: 129 rader på `-`-sidan, fördelade på 44 filer); inga `app.swe`-importer kvar i exekverbar kod — en historisk kommentar i `scripts/check_contract_freeze.py` nämner den gamla sökvägen. Backend konsumerar paketet som riktig path-dependency via uv. **Fristående bevis:** venv utanför repot, maturin-wheel + `pip install python/`, `pytest python/tests` → **136 passed**, backend inte på `sys.path`. CI kör samtliga **40** `swe_runtime`-märkta backend-konsumenttester: provider, persistence, research-wiring och sufficiency-reuse. Lease-cancel-fallet kontrollerar write-fencen direkt efter SWE-loopen och verifierar både `CancelledError` och persisterad `cancelled`-status. CI bygger också wheel + sdist och installerar wheel i en ren venv utanför repot (`swe.load_schema()`), så att paketdata inte kan försvinna tyst. |
| 3. `execute()` borttagen | Ingen produktionskonsument. `Investigation`/`StopReason` försvann med den. Den återstående skyddslogiken mot upprepade behov ligger i `NeedDiscovery`, som i dag bara exerceras av kontraktstestet (`crates/swe-reference/tests/contracts.rs`); referenshosten anropar den inte, så skyddet är inte inkopplat i någon körloop. Kärnan 74 → 67 tester. |
| 4. Frysta kontrakt | `contracts/` med kanoniska fixtures, `MANIFEST.sha256` och **två** grindar: strukturell (hashar, inga olistade `*.json`) och semantisk (fixtures *exekveras*: SWD-dokumentet kompilerar till headerns definition-hash, varje journalhändelse kodas förlustfritt, `NeedMore`-repeat, dubbletter, `AMBIGUOUS`, recovery per delivery-klass, okänd kostnad aldrig noll, fel versioner namnges). **13 kontraktstester** (`cargo test -p swe-reference --test contracts --offline`), inklusive ett nytt fixture==emitter-test: de frysta filerna måste vara exakt vad `swe-reference`-emittern producerar, och headerns versionsfält pinnas mot emitterns värden (som byggs av `CONTRACT_VERSION` och `current_dependency_versions()`) i stället för att läsas från fixturen och matas tillbaka (den tidigare formen var en tautologi). **Matrisbevisat** av `scripts/test_check_contract_freeze.py`: 38 negativa/positiva fall med exakt förväntad fallista — byte-tampering fäller det strukturella, ändring + regenererad manifest fäller det semantiska, och kommentarer, strängar eller funktionslokala deklarationer kan inte låtsas vara en version bump (Python läses via AST på modulnivå; Rust kräver crate-scope `pub const`). |
| 5. Mutationsgrind | `scripts/check_mutations.py` + `mutations/baseline.json`, blockerande CI-jobb. Varje mutation klassificeras `detected`/`equivalent`/`excepted` med motivering; en mutation som inte kan appliceras fäller grinden. `equivalent`/`excepted` kräver **exit 0** — en kraschande testprocess eller ett build-fel är ett gate-fel för varje klass, inte "grönt utan namngivet rött test". Grinden har en egen negativmatris (`scripts/test_check_mutations.py`, 32 fall) som körs i CI och avvisar absoluta/parent-traverserande manifestvägar; den upplösta filen måste ligga i den isolerade worktree:n. **10 mutationer, alla som klassificerade**, verifierat med `python3 scripts/check_mutations.py --offline` efter `cargo fetch --locked` (isolerad worktree, ingen ändring av checkouten). |

### Vad grinden hittade om sig själv

Samma mönster som i `13-verification-standard.md`: mekanismen fällde sin egen
första version.

- Kärnan rapporterade `UNRESOLVED` för varje saknat behov i stället för den
  faktiska statusen — inget **kärntest** pinnade `MissingInput::status`; bara
  referensdemon gjorde det. Nytt test:
  `the_gate_reports_why_each_input_is_missing`.
- En mutation som skulle förbjuda release av en avstämningspost träffade
  `ChargeSettled`-armen, blev oåtkomlig och därmed ekvivalent. Det syntes bara
  för att en `detected`-mutation måste fälla något.

### Kontraktsändring: journal v1 är additiv, ingen version bump

`contracts/` och journal-kodningen ändrades i B4, så kontraktsgrinden kräver en
uttrycklig post. Bedömningen:

- **Ingen wire-ändring.** Inga fält byter namn, typ eller betydelse. Fixturen
  utökas med `AttemptAbandoned` och `ChargeReleased` — två varianter formatet
  redan definierade men som fixturen saknade. Manifestet uppdateras i samma
  commit.
- **Dekodern skärps, inte luckras.** Obligatoriska belopp och tidsstämplar måste
  finnas och vara heltal; saknade värden avvisas i stället för att bli noll.
- **Kärnan får en ny invariant:** en settlement får aldrig **överstiga**
  reservationen (en högre kostnad än taket avvisas med ett typat fel som namnger
  båda beloppen). En lägre settlement är tillåten och redovisar den faktiska
  kostnaden — det matchar `swe-budget`-ledgerns dokumenterade semantik att
  reglera verklig kostnad och frigöra outnyttjad reservation. Den första
  versionen krävde exakt likhet, vilket hade gjort dokumenterad
  delavräkning oavstämbar i journalen; rättat efter den oberoende granskningen.

Därför stannar `JOURNAL_SCHEMA_VERSION` på 1. Detta är den dokumenterade
post som `scripts/check_contract_freeze.py` kräver när en kontraktsväg ändras.

### Oberoende granskning och rättelser (2026-11-01)

B4 granskades av fem oberoende spår (mutationsgrinden, kontraktsgrindarna,
Python-paketet + backend-konsumtion, Rust-workspace/`execute`-borttagningen +
licensiering, och CI-workflowens grindintegritet) innan ägarens sign-off. Varje
spår försökte reproducera fel med doctored commits eller syntetiska
`cargo`-körningar i stället för att bara läsa koden. Fynden och rättelserna:

- **Kontraktsgrinden:** versionsdeklarationen lästes ur rå text, så en kommentar
  `// CONTRACT_VERSION = 2` kunde ersätta en riktig bump. Nu läses den ur
  Python-AST på modulnivå respektive crate-scope Rust-tokenström;
  kommentars-, sträng- och funktionslokala spoof fäller grinden. Header-fixturens
  `contract_version`/`dependency_versions` var inte pinnade (tautologiskt test);
  nu jämförs alla tre fixtures mot emitterns output, som byggs av konstanterna.
  Matrisen har exakt förväntad fallista och egna självkontroller
  (tabell-paritet, CI-glob-paritet, pointer-uppslagning), så att en tyst
  borttagen negativ falla eller en uppluckrad undantagstabell fäller den.
- **Mutationsgrinden:** en kraschande testprocess (SIGABRT med en grön
  syskonbinär) räknades som "grön" för `equivalent`/`excepted`. Nu krävs exit 0
  och en ej tolkningsbar körning är ett gate-fel för varje klass; grinden har
  dessutom en egen 32-fallsmatris som körs i CI. `--package`-flaggan (död) togs
  bort och städningen flyttades till `try/finally`; grinden dokumenterar nu att
  den bara mäter committed HEAD och inte skyddar sig själv mot en PR som skriver
  om den. Manifestets filsökvägar måste vara relativa utan parent-traversering,
  och den upplösta mutationsfilen måste ligga kvar i den isolerade worktree:n.
- **Python/backend:** 22 `swe_runtime`-märkta provider-/persistence-tester hade
  slutat köras i CI när `swe-runtime`-jobbet bytte till `python/tests`; de körs nu
  igen. `python-swe`-jobbet byggde aldrig distributionen; nu byggs wheel+sdist
  och wheel installeras i en ren venv utanför repot med `swe.load_schema()` som
  rökprov. Dev-verktygsversionerna i `python/pyproject.toml`-kommentaren var
  felaktiga och är rättade. Wiring- och sufficiency-reuse-filerna (18 tester)
  körs också i samma jobb; den tidigare lease-cancel-kapplöpningen är stängd
  med en explicit write-fence-kontroll efter SWE-loopen.
- **Rust/licens:** den nya journalinvarianten krävde exakt likhet mellan
  reservation och settlement, vilket motsade `swe-budget`-ledgerns dokumenterade
  delavräkning; nu avvisas bara settlement > reservation (se ovan). Stale
  `execute`-referenser i doc-kommentarer och `13` rättade. Licensieringens
  siffror gjordes reproducerbara (bas `9d17b096`: 1 415 commits; 9
  `Cursor Agent`/5 Erik Fremred på de namngivna målvägarna; 41 Rust- och 14
  externa Python-beroenden) och `kajmund/swe` är nu formulerat som ett beslut,
  inte som en verifierad registrering.
- **CI-workflowen:** förändringsdetektorn kunde faila öppet (ett misslyckat
  `git diff` gav alla flaggor `false` och aggregate-jobbet grönt); nu körs den
  med `set -euo pipefail` och ett explicit fel på tom eller felaktig diff,
  använder merge-base, och kräver att gate-skript, matriser och
  workflow-invocations inte kan försvinna tyst. Workflow-ändringar triggar
  mutationsgrinden, kärnändringar bygger `swe-gym`, och aggregate-jobbet avvisar
  ett selector-värde som varken är `true` eller `false`.
- **Kvar som senare PR:** projektägaren signerade kontraktsfrysning v1
  2026-11-01 (kriterium 6); den fysiska repo-flytten återstår. Även skydd mot
  att en PR skriver om grindarna själva (CODEOWNERS/ruleset);
  `repository`/`homepage`-metadata och
  `THIRD-PARTY-NOTICES` i flytten; att `swe-native` namnger
  `contract_version`-fel som `schema_version` i feltexten; att
  `CONTRACT_VERSION`/`current_dependency_versions()` exporteras publikt så att
  kontraktstesterna kan pinna dem literalt; och Krav 4:s båda ordningar i
  kontraktstestet (kärnans enhetstester täcker ordningen i dag).

### Kvar efter B4

- **Kontraktsfrysning v1** (kriterium 6): **signerad av projektägaren
  2026-11-01.** Dokumenten och grindarna ska nu föras över oförändrade och
  verifieras i målrepot under PR 4.
- **Licens och repo** (kriterium 7): **fattat** — MIT OR Apache-2.0 för
  extraktionsmålet, `Copyright (c) 2026 Erik Fremred`, repo `kajmund/swe`
  (planerat, publikt i flytten), PyPI-distribution `swe-engine`;
  `publish = false` kvarstår till flytten/PR 4 (`15-licensing.md`), nu som ett
  publiceringssteg — namn, licens och äganderätt är verifierade/beslutade.
- `swe-gym` behåller sin egen grind (G4); kärnan är enda implementationen i
  extraktionsmålet.
- En ~35-rads helper-duplikat i `backend/tests/swe/runtime_helpers.py` är
  medveten: alternativet vore ett backend-beroende i den fristående sviten.

### Licensutredning (underlag för det beslut som nu är fattat)

Fakta för repo-beslutet (mätt vid basen `9d17b096`; branch-HEAD efter B4 har
1 422 commits): ingen LICENSE-fil har någonsin funnits i historiken; alla tre
crates anger `license = "UNLICENSED"` och `publish = false`; inga
SPDX-identifierare eller copyright-huvuden finns. **Ingen kopierad
tredjepartskod** hittades — enda härledningen är intern (`swe-budget` är en
0-rads flytt av `swe-gym`-ledgern, `af15a396`). Alla 41 Rust-beroenden och 14
externa Python-paket är permissiva (MIT/Apache-2.0-varianter; `unicode-ident` är
`(MIT OR Apache-2.0) AND Unicode-3.0`; inga GPL/AGPL/LGPL/MPL/NOTICE). 5 commits
av Erik Fremred och 9 av `Cursor Agent` på de namngivna målvägarna; inga
CLA/DCO/sign-off och personlig GitHub-remote. **Rättighetsinnehavaren
bekräftades av ägaren 2026-11-01** och AI-agentförfattarskapet dokumenterades i
`06` — licensen är alltså given av rättighetsinnehavaren, inte antagen.

## 8. Vad utrednings-PR:en innehöll (historik, före B4)

Detta avsnitt beskriver den ursprungliga utrednings-PR:en. B4:s omfattning
beskrivs i §7.14 ovan.

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
