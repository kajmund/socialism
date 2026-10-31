# Go/No-Go — är SWE redo att flyttas?

**Status:** Utredningens beslutspunkt. Bas: `origin/main` `666eccb0`,
inventeringarna [`01-inventory-rust.md`](01-inventory-rust.md) /
[`02-inventory-python.md`](02-inventory-python.md), kontrakten
[`04-public-contracts.md`](04-public-contracts.md), referensexperimentet
[`../../crates/swe-reference/`](../../crates/swe-reference/README.md) och
planen [`06-extraction-plan.md`](06-extraction-plan.md).
**Ingen fysisk flytt har gjorts eller godkänts av detta dokument.**

## 0. Beslut och ändrad ordning (2026-10-31)

Projektägaren har **godkänt riktningen** och fattat följande beslut, som
uppdaterar ordningen i §7:

- **Godkänd:** separationen av SWE som självständigt projekt, förutsatt att
  kodgranskningen bekräftar inventeringen och att referensexemplet verkligen är
  domänneutralt (det är verifierat i `08-verification-log.md` §3).
- **B1–B3 genomförs som tre separata PR:er**, men **kontraktsdesignen för B2
  ligger före B1:s implementation**. Så undviker vi att abstrahera
  Python-importerna mot ett gränssnitt som sedan ändras när behovs- och
  operationsmodellen flyttas till Rust. Det betyder att kontrakten ska vara
  *definierade* först — inte att B2 måste vara *färdigimplementerat* först.
- **Varje PR ska kunna mergas utan att Research eller SWE:s befintliga
  workflows ändrar beteende.**
- **Gym-splitten (`05`) och licensfrågan får inte fördröja B1–B3.**
- **Fysisk repo-flytt sker först efter att B1–B3 är stängda och verifierade mot
  GO-grinden i §6.**

Det gemensamma kontraktsbeslutet för B1–B3 finns i
[`09-contract-decision.md`](09-contract-decision.md); de tre PR-planerna i
[`10-pr1-b1-python-boundary.md`](10-pr1-b1-python-boundary.md),
[`11-pr2-b2-core-contracts.md`](11-pr2-b2-core-contracts.md) och
[`12-pr3-b3-journal-resume.md`](12-pr3-b3-journal-resume.md).

Två principiella ställningstaganden från ägaren ingår i kontraktsbeslutet:

1. **En sanningskälla:** Rust är normativ implementation; Python är adapter med
   versionssatta serialiseringskontrakt. Samma behov får inte bli `RESOLVED` i
   Python och `INSUFFICIENT_EVIDENCE` i Rust.
2. **Journalen är en motorgaranti** — men deduplicerad (at-most-once)
   *settlement* är inte samma sak som exakt-engångs*exekvering* av externa
   verktyg. Journalen är en append-only logg över **försök**, **bekräftade
   resultat** och **ekonomisk debitering**; ett obekräftat försök betyder okänt
   utfall (inte "ej utfört"), och okänd kostnad får aldrig skrivas av som noll.
   Se `09` §4.

**Rättelse efter ägarens granskning (2026-10-31):** tre blockerare (P1) är
åtgärdade i dokumenten innan någon implementation:

| # | Fynd | Rättelse |
| --- | --- | --- |
| P1.1 | Journalens identitet och återhämtning motsade sig själv (nyckel innehöll `attempt`, muterbara statusfält, global recovery) | `delivery_key` är stabil över försök; journalen är en append-only händelselogg; `Delivery` per åtgärd sparas före dispatch; `recompute_pure` för obekräftade rena anrop; okänd kostnad = `pending_reconciliation`. Se `09` §4.2–4.6, `12` §2–3 |
| P1.2 | Konfliktpolicyn var inte injicerbar och ändrade GLiNER-semantiken (REJECTED blockerade RESOLVED) | Domänen producerar typad bedömningsdata (`admissibility`, `equivalence_key`, `conflict_scope`, `operational_role`, `policy_version`); Rust validerar och äger reduktionen; rejected sparas men blockerar inte; sex differentialtester. Se `11` §C2.2 |
| P1.3 | Prompt-whitelisten blev fail-open i B1 | Fail-closed: provider-nod kräver injicerad allowlist; saknad allowlist ger typat kompileringfel; definition utan provider-noder får utelämna den. Se `10` §3 |
| P2 | Demon kraschade på `answer: null` när ingen leverantör uppfyllde kraven | Terminal `NO_COMPLIANT_SUPPLIER`-rapport + nytt integrationstest; demon är nu 12/12 grön |

Se `08` §7.2 för verifieringen.

**Ramverksbegränsning för B2:** SWE äger *mekanismen* för behov, evidens och
operationer — inte domänens faktatyper, verifieringsregler eller
undersökningsstrategier. Den gränsen definieras i `09` §5 och är en del av
B2:s acceptanskriterier.

## 1. Beslut

> **NO-GO för omedelbar fysisk flytt.**
>
> **GO för extraktionsprogrammet** enligt `06-extraction-plan.md`, under
> förutsättning att blockerarna B1–B3 nedan är åtgärdade och verifierade.
> De är små, avgränsade och kräver ingen ny arkitektur.

Detta är inte ett "SWE är felbyggt"-utlåtande. Kärnan är generisk och
referensexperimentet bevisar att motorn kan köra en domänneutral, budgetstyrd,
behovsdriven och avbrytbar undersökning helt offline. Hindret är att **fem
specifika kodrader i Python-hostlagret pekar in i Socialism**, och att de
generiska behovs-/evidens-/operations-/budgetförmågorna ännu inte bor i SWE.

## 2. Vad som är bevisat redo

| Område | Bevis | Bedömning |
| --- | --- | --- |
| Rust-kärnan är domänfri | Inga importer av research/JEV/OverGraph/GLiNER2 i `crates/swe-native/src`; endast neutrala teststrängar kvar | **Redo** |
| Kärnan bygger och testas offline | `cargo test --offline` i `crates/swe-native`: 30 tester gröna (18 unit + 12 integration) | **Redo** |
| Domänneutralt referensexperiment | `crates/swe-reference`: 10/10 krav i specens Fas D, offline, egna integrationstester; svar Beta utan att workflowet får facit | **Redo** (se `07` §3 och demo-README) |
| Kontraktsbilden är kartlagd | `04-public-contracts.md`: KEEP/DECOUPLE/PROMOTE/BUILD per område med `fil:rad` | **Redo** |
| Ägarskapsgränsen är tydlig | `03-ownership-matrix.md`: motor + hostkontrakt + generiska experimentförmågor vs research/juridik/dokument/OverGraph/produkt | **Redo** |
| Gym-uppdelningen är genomförbar | `05-gym-split.md`: generisk kärna (ledger, metering, runner, replay, kostnadsmätning) kan separeras från domänexperimentet | **Redo som plan**, inte som flytt |
| Socialisms produktionsflöde påverkas inte | Endast nya filer + en CI-rad i denna utredning; research-seamen orörd | **Redo** |

## 3. Vad referensexperimentet bevisar (och inte bevisar)

Bevisar:

1. Motorn kan exekvera ett workflow som **inte** får svaret och själv bygger upp
   behov, evidens och slutsats (Beta).
2. Behov härleds från **operationskontrakt**, inte från data som råkade finnas.
3. ALL_REQUIRED-grinden blockerar partiella data; operationen körs aldrig på dem.
4. Evidensstatus VERIFIED / AMBIGUOUS / REJECTED med källreferens per faktum
   fungerar som avstängningsmekanism (`INSUFFICIENT_EVIDENCE`).
5. `NeedMore`-slingan fungerar: operationen upptäcker ett nytt behov, workflowet
   undersöker det och operationen körs om.
6. Sweycoin-budgeten redovisas per åtgärd och totalt via den återanvända
   ledgern; paus + återupptagning laddar en journal och debiterar/kör exakt en
   gång.
7. Inga Socialism-beroenden: inga Python-, research-, OverGraph-, GLiNER2-,
   juridik- eller produktionsimporter.

Bevisar **inte**:

- Att paus/återupptagning är produktionshärdad. Python-kontraktet är testat men
  `run_store=None` i produktion (`02-inventory-python.md` E10); demon bevisar
  semantiken på host-nivå, inte drift i Socialism.
- Att de generiska behovs-/evidens-/operationstyperna är mogna nog att vara
  publika som de är. Demons typer är applikationslager; befrämjandet till
  `swe-core` (B2) återstår. Inte heller det fulla provenienskontraktet
  (locator, content hash, retrieved_at, provider) demonstreras — demots
  `source_ref` är en förenklad källreferens.
- Att OverGraph-run-storen följer Owner-regeln i produktion — den är inte
  produktionskopplad i dag (`02-inventory-python.md` §8.3).

## 4. Blockerare

### B1 — Domänimporter i Python-hostlagret (**åtgärdad**; plan `10`, resultat `08` §7.3)

Fem importrader i tre filer gör att det "generiska" paketet inte kan flyttas:

| Fil:rad | Import | Åtgärd |
| --- | --- | --- |
| `backend/app/swe/definition.py:13` | `PROMPT_KEY_SET` från promptkatalogen | `compile_definition(..., prompt_keys=...)`; host skickar setet |
| `backend/app/swe/runtime_dispatch.py:17` | `render_prompt` från `app.services` | injicera renderare (eller flytta den 10-radiga generiska hjälpen till SWE-hostpaketet) |
| `backend/app/swe/providers.py:15-17` | `app.config`, `app.jev`, `app.services.research.fast_controller` | flytta hela JEV-providern till Socialism; SWE behåller providerprotokollet |
| `backend/app/swe/schema.py:16` + `features.py:28,35` | Socialisms fem feature-id + OverGraph-katalogväg | flytta host-/feature-modellen till Socialism; SWE tar opak scope/nyckel eller store-fabrik |

**Varför blockerande:** utan detta importerar SWE-repot Socialism. Det bryter
mot utredningens huvudregel och gör "byggas och testas utan Socialisms backend"
omöjligt.

**Minsta åtgärd:** en PR (PR 1 i `06` §8) med beroendeinversionerna +
ett import-riktningsgate i CI. Ingen beteendeändring i research.

### B2 — Generiska förmågor bor i experimentcraten (blockerande för målbilden; plan i `11`)

Behov, evidens, operationer och budget är generiska enligt specen men finns i
`crates/swe-gym` (delvis med juridiska fixtures) eller saknas som generisk typ:

| Förmåga | I dag | Minsta åtgärd |
| --- | --- | --- |
| Sweycoin-ledger | `crates/swe-gym/src/ledger.rs` (generisk, testad) | flytta till `swe-budget` |
| `NeedRef`/prioritet/status | `ops.rs` + domänvariant `ResearchNeed` | generisk typ i `swe-core`; domän projicerar |
| Operationskontrakt + ALL_REQUIRED-grind | `ops.rs` (generisk struktur, juridiska exekutorer) | flytta grind + `OpOutcome`; exekutorer stannar |
| `NeedMore`-slingan | `ops.rs` | flytta med skyddet mot identisk upprepning |
| Evidensstatus + proveniens | `tools/eval_uncertainty_states.py` (experiment) + `ResearchEvidence` (domän) | bygg generisk evidensmodell i `swe-core` |
| `CostRecord`/budgetredovisning | påbörjat i gym-drivern | typa i `swe-budget` + hostkontrakt |

**Varför blockerande:** utan detta är SWE efter flytten bara en
workflow-exekutor, inte den "generella motorn för budgetstyrd, verifierbar,
behovsdriven problemlösning" som är det överordnade målet. Referensdemon visar
att förmågorna fungerar — men som applikationskod, inte som SWE-kontrakt.

**Minsta åtgärd:** PR 2 i `06` §8 (befrämja + peka om demon mot de nya
kontrakten; inga parallella implementationer).

### B3 — Paus/återupptagning saknar Rust-kontrakt (blockerande för
självständigt bibliotek; plan i `12`)

Python har `RunStore`/`InvocationRecord` + replay-semantik
(`backend/app/swe/run_store.py`, `docs/specs/swe-overgraph.md`), men det finns
ingen Rust-motsvarighet och ingen produktionskoppling. Demon implementerar
journalen i applikationslagret.

**Minsta åtgärd:** PR 3 — `RunStore`/journal-trait i `swe-core` med samma
semantik (definition-hash-grind, replay av invocationer, idempotent debitering)
och låt demon använda den. Kvarvarande OverGraph-implementation blir en adapter.

### B4 — Test-/CI-infrastruktur (blockerande för "byggas och testas självständigt")

Dagens SWE-tester lever i backendens harness: `tests/conftest.py` importerar
hela appen, fixtures är research-färgade (`research_parallel.*`), och
`test_swe_persistence.py` importerar OverGraph-adaptern. Dessutom finns en
befintlig CI-lucka: `test_research_swe/test_wiring.py` och
`test_sufficiency_experiment_reuse.py` är `swe_runtime`-märkta men körs av
inget CI-jobb (`02-inventory-python.md` §10.4, E11).

**Minsta åtgärd:** egen minimal harness + neutrala fixtures i det nya repot;
flytta persistens-testet efter att adaptern injicerats; lägg de två
konsumenttesterna i ett dedikerat Socialism-jobb (PR 4–5).

## 5. Icke-blockerande fynd att åtgärda i samband med flytten

| Fynd | Åtgärd |
| --- | --- |
| Ingen av run-store/JEV-cache/JEV-provider är produktionskopplad | Dokumentera som "testat, ej produktionsbevisat"; produktionssätt först när durable runs aktiveras |
| OverGraph Owner-regeln gäller alla kataloger, även SWE:s | När durable runs aktiveras: kör store/cache i Owner eller som Owner-klient (`02` §8.3) |
| `UNLICENSED` + `publish = false` | Licensbeslut före crate/wheel-publicering; git-tagg-konsumtion fungerar utan |
| Två benchmarks (`benchmark_research_swe*.py`) är research-specifika | stannar i Socialism; bara `benchmark_swe_runtime.py` följer med |
| Gym-experimentet är stort och blandat | separat spår enligt `05-gym-split.md`; ingen ny gymimplementation |
| Rust-kärnans preflight är svagare än Python-compile (JSON Schema + graf/join-validering) | en extern Rust-konsument kan skicka ett dokument som Python skulle avvisa. Åtgärd: portera grafvalideringen till `swe-core` eller dokumentera `compile_definition` som normativt innan PR 4 (`04` §1.7 G1) |
| `Json` saknar dokumenterad serialize/parse-pair | hosts får handskriva journal-läsaren (demon gör det); dokumentera paret i `swe-core` (`04` §1.7 G5) |

## 6. Vad som skulle göra detta till ett GO

GO-grinden (alla måste vara uppfyllda och verifierade i CI):

1. **Importriktning:** noll `app.*`-importer i det blivande SWE-paketet; ett
   automatiskt gate som failar vid återfall. (B1)
2. **Domänneutral demo mot de nya kontrakten:** `crates/swe-reference` använder
   `swe-core`-typerna för behov/evidens/operationer/journal och
   `swe-budget`-ledgern — ingen applikationskopia av grind eller ledger. (B2/B3)
3. **Rust-journal:** paus/återuppta-testet i demon går genom
   `swe-core`-kontraktet, inte en demospecifik implementation. (B3)
4. **Fristående harness:** `cargo test --workspace` + `pytest` i det nya repot
   utan Socialism-checkout; neutrala fixtures; ingen `backend/conftest.py`. (B4)
5. **Research oförändrat:** Socialisms research-sviter och backend-CI gröna mot
   den pinnade versionen, inklusive de två konsumenttester som i dag saknar
   CI-täckning.
6. **Kontrakten i `04` är frysta** (SWD 1.0, event-schema v1, journal v1,
   provider request/response v1) och dokumenterade i det nya repot.
7. **Licens och repo-beslut** fattade (offentligt/privat, licens för crate och
   wheel).

Uppskattad omfattning (grov, för planering): B1 ~0,5–1 dag; B2 ~2–4 dagar;
B3 ~1–2 dagar; B4 ~1–2 dagar; PR 4–5 (repo + konsumtion) ~1–2 dagar. Gym-split
är ett separat spår (~2–4 dagar) och blockerar inte SWE-extraktionen.

### B2-status: godkänd inom sin omfattning, med två öppna skulder

B2 är genomförd och godkänd inom sin definierade omfattning. Två punkter är
uttryckligen **inte** färdiga och hör till GO-grinden:

| Skuld | Varför den inte är stängd | Blockerar |
| --- | --- | --- |
| Referensdemon har kvar en lokal `OpOutcome` | Kärnans `NeedMore(NeedRef)` bär ett behov per utfall; demon bär en lista. Byten är en beteendeförändring och ska vara eget granskat steg (C2.4b) | **PR 4** |
| Operationsgrinden saknar Python-bindningar | Kriterium 1 gäller inom Rust; över gränsen är det otestat. Krävs bara om Python ska vara stödd konsument av grinden | **GO-grinden**, inte B3 |

Det som är stängt och mutationstestat: Rust normativ semantik, Python utan egen
statuslogik, differentialtest som faktiskt kan faila, domänneutral kärna,
`swe-budget` utan beteendeförändring.

## 7. Rekommendation (uppdaterad ordning, beslutad)

1. **Kontraktsbeslut** (`09-contract-decision.md`) — definierar Rust som
   normativ semantik, serialiseringsversioner, journalens tre tillstånd och
   ramverksgränsen. Ingen produktionskod ändras. **Detta sker före PR 1.**
2. **PR 1 — B1:** ✅ **genomförd.** `app/swe` har noll domänimporter,
   prompt-allowlisten är fail-closed både vid kompilering och exekvering,
   import-gaten ligger i testsviten (`10-pr1-b1-python-boundary.md`, resultat i
   `08` §7.3).
3. **PR 2 — B2:** flytta de generiska kontrakten till `swe-core` som
   normativ Rust-implementation, med Python som adapter
   (`11-pr2-b2-core-contracts.md`).
4. **PR 3 — B3:** journal- och resume-kontraktet i `swe-core`, inklusive
   försök/bekräftelse/debitering och idempotensnycklar
   (`12-pr3-b3-journal-resume.md`).
5. **B4** (egen CI och konsumenttester) följer därefter; gym-split och licens
   löper parallellt utan att blockera 1–4.
6. **Utvärdera GO igen** mot §6 när B1–B3 är mergade; först därefter flyttas
   SWE till ett eget repo.

Varje PR ska kunna mergas utan att Research eller SWE:s befintliga workflows
ändrar beteende. Flytta inte `crates/swe-gym` som helhet och skapa ingen
parallell implementation — följ `05-gym-split.md` och `06` §8.

Kort uttryckt: **motorn är redo, hostlagret är nästan redo, målbilden är inte
redo — men vägen dit är kort och mekanisk.**
