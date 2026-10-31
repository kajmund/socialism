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
running 11 tests
test all_required_gate_lists_every_missing_input ... ok
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
test result: ok. 11 passed; 0 failed; ...
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

## 8. Vad denna PR innehåller (scope)

```console
$ git status --short
 M .github/workflows/ci.yml
?? crates/swe-reference/
?? docs/swe-standalone/
```

- Nya dokument `docs/swe-standalone/README.md` + `01`–`12` (denna fil är 08; `09`–`12` är besluts- och PR-underlag).
- Ny crate `crates/swe-reference` (eget `Cargo.lock`, `.gitignore` med `/target`).
- En CI-rad i `swe-runtime`-jobbet.
- **Inga ändringar** i `backend/`, `crates/swe-native`, `crates/swe-gym`,
  produktions-Research eller blindtest v3.
