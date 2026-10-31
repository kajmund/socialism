# 11 — PR 2 (B2): generiska kontrakt till SWE Core (Rust normativ)

**Blockerare:** B2 (`07-go-no-go.md` §4).
**Förutsättning:** [`09-contract-decision.md`](09-contract-decision.md) godkänt
och PR 1 (B1) merget. Ordningen är medveten: **B2:s kontrakt definieras först,
implementeras efter B1.**
**Storlek:** ~2–4 dagar, uppdelad i fem små commits.
**Ramverksgränsen** i `09` §5 gäller: SWE äger mekanismen, inte domänens
innehåll.

## 1. Mål

Behov, evidens och operationer blir **riktiga motorförmågor i Rust** med
normativ semantik; Python blir adapter. Budgeten flyttas från experimentcraten
till `swe-budget` i samma serie (den är redan generisk och testad).

Efter PR 2:

- `swe-core` exporterar `needs`, `evidence`, `operations` som typade moduler.
- Python-adaptern projicerar domänobjekt och begär/mottar **Rust-beräknade**
  tillstånd — den härleder dem inte själv.
- Referensexperimentet använder de nya typerna i stället för sina lokala
  kopior (`crates/swe-reference/src/{evidence,operations}.rs`).

## 2. Leverans i fem commits

### C2.1 — `swe-core::needs`

```rust
pub struct NeedRef { pub fact: String, pub document: String }   // experimentets form, unified
pub enum NeedPriority { Required, Supporting, Exploratory }
pub enum NeedCardinality { Single, Multiple, Unknown }
pub enum NeedStatus { Unresolved, Resolved, Ambiguous }
pub struct Need { pub spec: NeedRef, pub priority: NeedPriority,
                  pub cardinality: NeedCardinality }
pub enum NeedMore { /* one discovered need; identical repeat is rejected */ }
pub fn apply_need_more(seen: &mut Vec<NeedRef>, need: &NeedRef)
    -> Result<(), NeedLoopError>;   // andra gången = INSUFFICIENT_EVIDENCE
```

Semantik som flyttas (och stannar i Rust):

- behov härleds ur `OperationSpec.required_inputs`, aldrig ur det som råkade
  bli löst (`crates/swe-gym/src/ops.rs:120`-testet portas);
- identisk `NeedMore` två gånger avslutar undersökningen
  (`ops.rs:198-200`);
- ett UNRESOLVED behov kan inte försvinna ur en grind.

**Tester:** `ops.rs`-testerna portas med neutraliserade värden (`doc-a/b/c`), plus
nya för prioritet/kardinalitet.

### C2.2 — `swe-core::evidence`

```rust
pub struct Provenance { pub source_id: String, pub locator: Option<String>,
                        pub content_hash: Option<String>,
                        pub retrieved_at_ms: Option<u64>, pub provider: Option<String> }
pub enum EvidenceStatus { Verified, Ambiguous, Rejected }
pub struct EvidenceCandidate { pub need: NeedRef, pub value: Option<Json>,
                               pub provenance: Option<Provenance>,
                               pub confidence_bp: Option<u16>,
                               pub conflict_group: Option<String> }
pub struct ConflictPolicy { pub min_confidence_bp: u16 }   // domänen injicerar tröskel
pub fn derive_status(candidate: &EvidenceCandidate, policy: &ConflictPolicy) -> EvidenceStatus;
pub fn resolve_need(need: &Need, evidence: &[EvidenceCandidate], policy: &ConflictPolicy)
    -> NeedStatus;
```

Generisk regel (från `tools/eval_uncertainty_states.py:60-81`, samma semantik):

- inget värde **eller** ingen proveniens → `REJECTED`;
- flera kandidater i samma `conflict_group` som inte kan förenas, eller
  konfidens under tröskeleln → `AMBIGUOUS`;
- annars `VERIFIED`;
- ett behov är `RESOLVED` **endast** om det finns minst en VERIFIED och ingen
  AMBIGUOUS eller REJECTED i konfliktgruppen.

Domänen äger: vilka källor som får tala, vad som är en konflikt, tröskeln.

### C2.3 — `swe-core::operations`

```rust
pub enum ExecutionPolicy { AllRequired }
pub enum MissingOutcome { InsufficientEvidence }
pub struct OperationSpec { pub name: String, pub required_inputs: Vec<NeedRef>,
                           pub execution_policy: ExecutionPolicy,
                           pub on_missing: MissingOutcome }
impl OperationSpec { pub fn gate(&self, states: &[NeedStatus]) -> Result<(), MissingOutcome>; }
pub enum OpOutcome { Answer(Json), NeedMore(NeedRef), InsufficientEvidence }
pub fn investigate_operate_loop<G, E, R>(gate: G, execute: E, resolve: R, max_rounds: usize)
    -> OpOutcome;
```

Portas från `crates/swe-gym/src/ops.rs:26-213` med dess fyra skyddsregler.
Domänexekutorerna (`max_notice_period:68`, `apply_exception:157`) stannar i
Socialism. Referensexperimentets `OpOutcome`/`all_required` ersätts av de nya
typerna.

### C2.4 — `swe-budget`

Flytta `crates/swe-gym/src/ledger.rs` + `tests/ledger_tests.rs` oförändrade till
`crates/swe-budget/` (som `05-gym-split.md` G1 föreskriver). `swe-gym` och
`swe-reference` konsumerar den nya crate:n; ingen kopia lämnas kvar.

### C2.5 — Python-adaptern projicerar

```python
# app/swe/needs.py  (tunnt lager, ingen egen semantik)
def project_needs(domain_needs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]: ...
def read_need_states(result: Mapping[str, Any]) -> dict[str, str]: ...   # Rust har räknat
def project_evidence(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]: ...
```

Kontrakt (`09` §3): `swe.need_spec.v1`, `swe.evidence_candidate.v1`,
`swe.need_state.v1`, `swe.operation_outcome.v1`.

## 3. Differentialtest — den avgörande kontrollen

För varje semantik som flyttas:

```
samma indata (behov + evidenskandidater + operationsspec)
  ├─ ren Rust-väg        → utfall A
  └─ Python-projektion   → Rust → utfall B
assert A == B  (varje fält, inte bara status)
```

Om A ≠ B är det en bugg i adaptern, inte en fallback. Testet läggs i
`backend/tests/test_swe_core_parity.py` och i `crates/swe-reference/tests/`.

## 4. Ett scenario som ska pinnas

`09` §2.3: Python får inte kunna säga `RESOLVED` när Rust säger AMBIGUOUS.
Testet konstruerar exakt det läget (två motstridiga källor i samma
konfliktgrupp) och assertar att: Rust → `AMBIGUOUS`, Python-adapterns projektion
→ `AMBIGUOUS`, och att operationens grind därefter avstår med
`INSUFFICIENT_EVIDENCE`.

## 5. Acceptanskriterier

1. `swe-core` exporterar `needs`/`evidence`/`operations`; alla semantikregler
   har Rust-tester (porterade + nya).
2. Python-adaptern innehåller **ingen** egen övergångslogik (grep-gate: inga
   `RESOLVED`/`AMBIGUOUS`-tilldelningar i `backend/app/swe/`; de bara läses).
3. Differentialtestet är grönt för varje flyttad semantik.
4. `crates/swe-reference` använder de nya typerna; dess 11 tester gröna
   (eventuellt fler).
5. Ramverksgränsen: grep-gaten från `05-gym-split.md` §7 ger 0 träffar i
   `swe-core` (inga avtal/JEV/chunk/uppsägningstid-terner).
6. Research-beteendet oförändrat (research-sviterna gröna).
7. Den nya `swe-budget`-craten har 9 gröna ledger-tester och ingen dubblett
   kvar i `swe-gym`.

## 6. Vad som inte hör hit

- Ingen `wait`/`subworkflow`/`retry` (fortfarande preflight-avvisade).
- Ingen `Environment`/MDP/RL-mekanik (`05` §2: befrämjas inte nu).
- Ingen ny gym-implementation: `swe-bench` kommer i gym-split, inte här.
- Ingen flytt av `crates/swe-gym` som helhet.

## 7. Risker

| Risk | Mildring |
| --- | --- |
| SWE blir ett för stort ramverk (ägarens huvudinvändning) | `09` §5 är en del av acceptanskriterierna; allt som bara kan beskrivas med domänord stannar utanför `swe-core` |
| Två sanningskällor under övergången | Diff-testet + grep-gaten i §5.2; Python får inte beräkna tillstånd |
| Portningen tappar `ops.rs`-skydden | De fyra skyddsreglerna har exakta befintliga tester som flyttas, inte skrivs om |
| `swe-reference` bryts av typbytet | Demon uppdateras i samma PR (C2.3/C2.5), inte i efterhand |
