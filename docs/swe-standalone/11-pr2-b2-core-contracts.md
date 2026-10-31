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

### C2.2 — `swe-core::evidence` (bedömningsdata i domänen, reduktion i Rust)

**Rättelse mot första versionen:** API:t hade bara `min_confidence_bp`, vilket
inte gör konfliktpolicyn faktiskt injicerbar — Rust kan inte avgöra om två
gods­tyckliga JSON-värden "kan förenas". Dessutom motsade regeln "REJECTED
blockerar RESOLVED" dagens GLiNER-kontrakt, där NO/UNCERTAIN blir REJECTED och
sedan inte deltar i konfliktberäkningen
(`backend/app/services/research/gliner/contract.py:261-327`). Det hade ändrat
Research-resultat.

**Låst gräns:**

- **Domänen producerar typad, versionssatt bedömningsdata** — den avgör *vad*
  som är relevant, likvärdigt och konkurrerande.
- **Rust validerar och äger reduktionen** till `VERIFIED`/`AMBIGUOUS`/
  `REJECTED` och till slutlig `NeedStatus`.

```rust
// swe.evidence_assessment.v1  (produceras av domänen)
pub struct EvidenceAssessment {
    pub need: NeedRef,
    pub value: Option<Json>,
    pub admissibility: Admissibility,      // Admitted | NotAdmitted | Uncertain
    pub equivalence_key: Option<String>,   // normaliserat värde; lika nyckel = ej konflikt
    pub conflict_scope: String,            // t.ex. "notice_period@Avtal_17"
    pub operational_role: Option<String>,  // E3: roll inom scopet
    pub reason_code: String,               // domänens kod, sparas för revision
    pub policy_version: String,            // vilken domänregel som gällde
    pub provenance: Provenance,
}

pub enum Admissibility { Admitted, NotAdmitted, Uncertain }
```

```rust
// swe-core::evidence  (reduktionen, Rust-normativ)
pub fn reduce(assessments: &[EvidenceAssessment], policy: &EvidencePolicy)
    -> Vec<EvidenceState>;            // VERIFIED | AMBIGUOUS | REJECTED per behov

pub struct EvidencePolicy {
    /// Om Uncertain får blockera: den blockerar endast inom ett conflict_scope
    /// som domänen uttryckligen har deklarerat som operativt.
    pub uncertain_blocks_scope: bool,
    /// Om AMBIGUOUS-värden får redas ut av en majoritet (default: nej).
    pub majority_vote: bool,
}
```

**Reduktionsregler (kontraktet):**

1. `NotAdmitted` → `REJECTED`. Rejected evidens **sparas för revision** och
   **blockerar inte** ett accepterat värde (samma semantik som
   `derive_findings`: icke-YES blir REJECTED och deltar inte i konfliktberäkningen).
2. Två eller fler **distinkta** `equivalence_key` inom samma `conflict_scope`
   → `AMBIGUOUS` för den scopets accepterade kandidater.
3. Semantiskt likvärdiga normaliserade värden har **samma** `equivalence_key`
   och skapar alltså ingen konflikt.
4. Olika `operational_role` inom samma scope konkurrerar inte — men en kandidat
   vars roll inte kan avgöras räknas som konkurrerande (fail-safe, samma som
   `derive_findings`).
5. `Uncertain` blockerar **endast** när domänen har deklarerat scopet som
   operativt; annars påverkar den inte reduktionen.
6. `NeedStatus`: `RESOLVED` kräver minst en `VERIFIED` och ingen `AMBIGUOUS`
   inom behovets scope; annars `UNRESOLVED`.

**Vad som följer av gränsen:** ingen domänregel (normalisering, rollavgörande,
relevansbedömning) hamnar i `swe-core`. `swe-core` känner bara till
`equivalence_key`, `conflict_scope`, `operational_role` och `admissibility` som
**opaka strängar/enum** — det kan beskrivas utan avtal, JEV eller GLiNER2.

**Obligatoriska differentialtester** (varje par måste ge samma utfall via ren
Rust-väg och via Python-projektionen):

| Scenario | Förväntat |
| --- | --- |
| rejected + verified | `RESOLVED` (rejected blockerar inte) |
| normaliserat likvärdiga värden (samma `equivalence_key`) | `VERIFIED`, ingen konflikt |
| olika operativa roller i samma scope | ingen konflikt, båda kan accepteras |
| två verkligt konkurrerande värden | `AMBIGUOUS` → `UNRESOLVED` |
| `Uncertain` i ett icke-operativt scope | påverkar inte |
| `Uncertain` i ett operativt scope | `AMBIGUOUS` → `UNRESOLVED` |

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
   Domänen producerar `EvidenceAssessment` och får aldrig skriva en slutlig
   `NeedStatus`.
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
| Konfliktpolicyn blir en gissning i Rust | Rust reducerar bara över `equivalence_key`/`conflict_scope`; semantiken för likvärdighet ägs av domänens bedömningsdata |
| Ny reduktion ändrar Research-resultat | De sex differentialtesterna ovan pinnar dagens GLiNER-semantik; samtliga research-sviter måste vara gröna |
| Portningen tappar `ops.rs`-skydden | De fyra skyddsreglerna har exakta befintliga tester som flyttas, inte skrivs om |
| `swe-reference` bryts av typbytet | Demon uppdateras i samma PR (C2.3/C2.5), inte i efterhand |
