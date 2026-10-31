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
