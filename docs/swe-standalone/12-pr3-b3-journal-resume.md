# 12 — PR 3 (B3): journal och resume som motorgaranti

**Blockerare:** B3 (`07-go-no-go.md` §4).
**Förutsättning:** [`09-contract-decision.md`](09-contract-decision.md) godkänt,
PR 1 och PR 2 mergade.
**Storlek:** ~1–2 dagar.
**Central distinktion:** exakt-engångs**debitering** är en garant. Exakt-
engångs**exekvering av externa verktyg** är det inte och får inte påstås.

## 1. Vad som finns idag

| Komponent | Plats | Vad den bevisar |
| --- | --- | --- |
| Python `RunStore` + `RunRecord`/`InvocationRecord` | `backend/app/swe/run_store.py:15-56` | Transitioner kan persisteras och replayas |
| Replay på resume | `backend/app/swe/runtime.py:294` (`resume_run`), `:401` (`_apply_replay`) | Persisterade invocation-resultat kompletteras utan att handlern körs igen |
| OverGraph-implementation | `backend/app/services/overgraph/workflows.py` | Atomisk persistens per transition — **inte produktionskopplad** (`02` E10) |
| Demon-journal | `crates/swe-reference/src/journal.rs` | Definition-hash-grind, replay + `Ledger::replay`; exakt-engångsdebitering bevisad |
| Ledger-idempotens | `crates/swe-gym/src/ledger.rs` | Reservera/settle med nyckel debiteras exakt en gång |

Saknas: ett **Rust-kontrakt** för journalen, och en modell som skiljer försök,
bekräftelse och debitering.

## 2. Mål

```rust
// swe-core::journal  (schema swe.journal.v1)
pub struct RunSnapshot {
    pub run_id: String,
    pub definition_sha256: String,
    pub schema_version: u32,
    pub input: Json,
    pub status: RunStatus,
    pub started_at_ms: u64,
    pub last_seq: u64,
    pub recovery: RecoveryStrategy,
}

pub struct InvocationAttempt {
    pub attempt_id: String,          // run:node:branch:epoch:serial:attempt
    pub invocation_id: String,
    pub action: String,
    pub idempotency_key: String,     // sha256(run_id, invocation_id, action, attempt)
    pub started_at_ms: u64,
    pub state: AttemptState,         // Started | Confirmed | Abandoned
}

pub struct ConfirmedResult {
    pub invocation_id: String,
    pub attempt_id: String,
    pub outcome: CompletionOutcome,  // Ok(Json) | Error{kind, message, path} | Cancelled
    pub confirmed_at_ms: u64,
}

pub struct ChargeRecord {
    pub charge_id: String,
    pub invocation_id: String,
    pub attempt_id: String,
    pub amount_milli: u64,
    pub tariff_milli: u64,
    pub idempotency_key: String,
    pub state: ChargeState,          // Reserved | Settled | Released
}

pub enum RecoveryStrategy { ReplayResult, IdempotentRetry, UnconfirmedAbort }

pub trait RunJournal {
    fn record_snapshot(&mut self, snapshot: &RunSnapshot) -> Result<()>;
    fn record_attempt(&mut self, attempt: &InvocationAttempt) -> Result<()>;
    fn record_confirmed(&mut self, result: &ConfirmedResult) -> Result<()>;
    fn record_charge(&mut self, charge: &ChargeRecord) -> Result<()>;
    fn load(&self, run_id: &str) -> Result<Option<JournalView>>;
}
```

## 3. Resume-algoritm (kontraktet)

```text
1.  Läs journalen. Saknas den        -> typat fel (`resume`), ingen nystart.
2.  schema_version måste vara exakt   -> annars `unsupported`.
3.  definition_sha256 måste matcha    -> annars `conflict` (inte "tolerant" resume).
4.  Ledger rekonstrueras med replay   och verifieras: sum(settled) == saldo.
5.  För varje InvocationAttempt utan ConfirmedResult:
      a. recovery = ReplayResult     -> om resultat finns i journal: replaya.
      b. recovery = IdempotentRetry  -> nytt försök med SAMMA idempotensnyckel;
                                         debitera bara om åtgärden bekräftat nytt svar.
      c. recovery = UnconfirmedAbort -> stoppa typat `unconfirmed_attempt`;
                                         markera charge som `released`, aldrig `settled`.
6.  Starta en fräsch maskin med samma run_id/input/klocka och replaya
    ConfirmedResult i effektordning (samma som idag i Python, `runtime.py:401`).
7.  Fortsätt från effektgränsen. Varje ny åtgärd bokförs som ett nytt försök.
```

Formell garanti som **får** påstås:

> **Exakt-engångsdebitering:** varje åtgärd debiteras högst en gång per run,
> oberoende av krascher och antal återupptaganden, förutsatt att
> idempotensnyckeln är intakt i journalen.

Formell garanti som **inte** får påstås:

> ~~Exakt-engångsexekvering av externa åtgärder.~~ Det gäller bara för
> deterministiska/mockade åtgärder (`ReplayResult`), eller när den externa
> åtgärden själv respekterar idempotensnyckeln (`IdempotentRetry`).

## 4. Förändringar per komponent

| Komponent | Ändring |
| --- | --- |
| `backend/app/swe/run_store.py` | `RunRecord` får `schema_version`; ny `AttemptRecord` och `ChargeRecord`; protokollet utökas med `attempts()`/`charges()` |
| `backend/app/swe/runtime.py` | Skriver `InvocationAttempt` före dispatch och `ConfirmedResult` när svaret tas emot; `_apply_replay` (`:401`) läser bara bekräftade resultat |
| `backend/app/services/overgraph/workflows.py` | Nya nodtyper `WorkflowAttempt`/`WorkflowCharge` i samma atomiska transition; ingen ändring i `WorkflowRun`/`WorkflowInvocation` |
| `crates/swe-core/src/journal.rs` | Ny modul med typerna ovan + `JournalView` + replayhjälp |
| `crates/swe-reference` | Journalen använder `swe-core`-kontraktet; tre nya tester (§5) |
| `docs/specs/swe-overgraph.md` | Uppdateras: nya nodtyper och `schema_version`; Owner-regeln gäller fortsatt för katalogen |

## 5. Tester som pinnar garantierna

| Test | Bevisar |
| --- | --- |
| `pause_resume_charge_and_execute_exactly_once` (finns) | Oförändrad semantik för deterministiska åtgärder |
| `unconfirmed_attempt_is_not_silently_completed` (ny) | Ett försök utan bekräftelse → `ReplayResult` reproducerar, `UnconfirmedAbort` ger typat fel; aldrig "gjort" utan bekräftelse |
| `crash_after_external_side_effect_does_not_double_charge` (ny) | Bekräftad åtgärd + krasch före settle → resume debiterar exakt en gång |
| `idempotent_retry_reuses_the_key` (ny) | Samma `idempotency_key` i nytt försök; åtgärden kan känna igen sig |
| `journal_version_and_hash_are_enforced` (ny) | Fel `schema_version`/`definition_sha256` → typat fel, ingen tyst resume |
| `released_charge_is_never_settled` (ny) | Obekräftat försök → `Released`, aldrig `Settled` |
| Python: `test_swe_persistence.py` (11) | Utökas med attempt/charge-transitioner och version-kontroll |

## 6. Acceptanskriterier

1. Rust-journal-kontraktet finns i `swe-core` och referensexperimentet använder
   det (ingen demospecifik journal kvar).
2. De sex nya testerna ovan är gröna; de elva befintliga dito.
3. Journalen skiljer `InvocationAttempt`, `ConfirmedResult` och `ChargeRecord`.
4. `RecoveryStrategy` står i journalen och dokumenteras i `docs/specs/`.
5. Ingen text i docs eller PR påstår exakt-engångs*exekvering* av externa verktyg.
6. Research-beteendet oförändrat: `runtime.py`-ändringarna är additiva
   (attempts/charges skrivs, resultatlogiken är densamma).

## 7. Risker

| Risk | Mildring |
| --- | --- |
| Ökad skrivvolym per transition | Attempts/charges skrivs i **samma** `begin_write_txn`; mät antal noder per run i PR:en |
| OverGraph-katalogen växer | `WorkflowAttempt`-noder är små; retention/kompaktering är ett separat beslut, inte en semantikändring |
| Owner-regeln | Inget ändras i ägarskapet: implementationen stannar som Socialism-adapter (`09` §2.1, `02` §8.3) |
| Äldre journaler saknar försök | Före produktion finns inga kunder; ingen migration byggs (`09` §3.5) |
