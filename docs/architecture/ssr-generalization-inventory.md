# Inventeringsrapport — generaliserad SSR, dokumentfingeravtryck och adaptiv routing

Status: Fas 0-leverans (inventering + fryst experimentprotokoll), **uppdaterad med Fas 1–3-genomförande**.
Datum: 2026-10-27. Grund: integrationsbranch `feat/ssr-generalization` (merge av origin/main
`482aaecd` in i `feat/swe-gym-poc`-toppen `3c2da5dc`).
Komplement: [ssr-generalization-experiment-protocol.md](ssr-generalization-experiment-protocol.md).

---

## 9b. Implementationsstatus (Fas 1–3) — bifogat efter inventeringsleveransen

Branchbeslut (användaren): integrationsbranch som mergear origin/main in i feat/swe-gym-poc.
Genomfört i en separat git worktree `/Users/erikfremred/socialism-ssr-generalization`;
originalarbetskopian med ocommittad live-speech-WIP är **orörd**. Merge-konflikt: endast
`crates/swe-gym/src/lib.rs` (modullista; löst som union — lokal branch är en supermängd).
Alembic-kedjan på den mergeade branchen är koherent (192→193_tabular_reviews→
194_live_voice_model→195_stt_correction, ett head).

### Fas 1 — generaliserad subject-modell (commit `92817813`)

- **Ändrat:** `clause_ssr/types.py` (SubjectKind/SubjectRef, subject-fält på
  Verification/Anchor/AnchorSet, MatchProfile, AnchorSetRef med pool_revision,
  subject_kinds på ClassificationDefinition), ny `subjects.py` (subject-identitet +
  vektorupplösning för text_unit och fact; fact-rendering `fact:v1` = source name +
  namespaced predicate + target name + fact_text; fail loud vid saknad/dimension-fel),
  ny `thresholds.py` (versionerad matchprofil; dagens konstanter 0,25/0,04/0,45 =
  profil v1, oförändrad semantik), `match.py`/`owner_match.py` (subject-ref + profil +
  anchor_sets/match_profile i resultatet), `verifications.py`/`anchors.py`/
  `classifications.py`/`owner_classifications.py`/`owner_select.py` + `repository.py`
  (beslut och promotion tar subject-ref; klassificering gate:ar tillåtna subject_kinds;
  ny `owner_payloads.py` håller den baselinede repository.py ≤ baseline),
  `api/clause_ssr.py` (`POST /match` och `/decisions` tar `{subject:{kind,id}}`; svar
  med subject/anchor_sets/match_profile/embedding), frontend `clauseSsr.ts` +
  `ClauseSsrQueuePage.tsx` migrerade (ingen permanent shim; interna callers migrerade
  i samma serie).
- **Återanvändning:** samma matchkärna för båda subject-typerna (en motor), samma
  owner-batch/idempotens/revocation-semantik, samma cosine-primitiv.
- **Tester:** 112 gröna i clause/tabular/owner-sviterna + 10 nya subject-/tröskeltester
  (fact via samma kärna, rendering-determinism, fail-loud, tenant-isolering,
  subject_kind-gate, profilversionering). Ruff grön; maintainability-baseline sänkt
  (repository.py 590→589; C901/PLR0912-exemptioner borttagna).
- **Grindar:** 1, 2, 4 verifierade i tester (tenant-isolering, provenance, fail loud).
  Grind 6 (Recall@5 ≥ 0,95) är **inte mätt** — kräver körning mot retrieval_gold med
  riktiga embeddings (ej del av denna serie).

### Fas 2 — dokumentfingeravtryck + offline-benchmark (commit `bc6bc840`)

- **Ändrat:** ny `clause_ssr/fingerprint.py` (build_fingerprint enligt spec §7.2-kontrakt;
  kategorinycklat, inte centroid; presence present/absent/abstained — absent aldrig från
  utebliven träff ensamt), ny `clause_ssr/docclassify.py` (linjär klassificerare +
  abstain + centroid-/prototyp-armar, frusen feature-ordning i artifact-kontraktet),
  ny `scripts/benchmark_doc_fingerprint.py` (4-armar offline-harness, familj+org-split,
  scripted-märkt output), `experiments/ssr_fingerprint/` (gold-manifest-**schema** —
  mänskligt verifierat gold saknas fortfarande och är uttryckligen inte fabricerat —
  + smoke-classifier-artifact).
- **Tester:** 7 nya (reproducerbarhet via content_hash, vocab/missing/abstain,
  definitionsversion i identitet, split-läckage per familj, klassificerar-abstain,
  stabil feature-ordning). Ruff grön; maintainability grön.
- **Grindar:** 8/9/10 **kan inte mätas ännu** — inget mänskligt verifierat dokumenttypgold
  existerar. Detta rapporteras, inte tystas.

### Fas 3 — adaptiva policyfamiljer i swe-gym (commit `bc6bc840`)

- **Ändrat (endast `crates/swe-gym/`; armar D/E/G och befintliga benchfiler orörda):**
  ny `policy.rs` (PolicyDecisionEvent med propensity, baseline/shadow, scripted/replay/live,
  authoritative/shadow, kostnad/latens/kvalitet — ingen rå text), ny `policy_a.rs`
  (två separata beslutspunkter `ssr_to_jev@a1` och `model_profile@a1` med egna id:n/
  actionrum/rewards; mean-table bandits; deterministiska kontrollarmar), ny `policy_b.rs`
  (`budget_alloc@b1` — ett budgetbeslut per episod genom riktiga ledgern), ny
  `policy_bench.rs` + frysta scriptade benchar `bench_policy_a_v1.json`/
  `bench_policy_b_v1.json` bredvid befintliga + `examples/policy_experiment.rs` +
  `POLICY.md`. En ny dependency: serde_json (exakt samma pin som redan finns i
  swe-native; endast för JSON-numrering av propensity).
- **Tester:** 7 nya (separata id:n, propensity valid, reproducerbarhet vid frusen seed,
  separata mätetal i rapport, ledger-konservering + idempotent retry, inga råa
  textfält i event). Hela gymmet grönt inkl. frysta bandit-/TD-tester.
- **Grindar:** 5 uppfylld (scripted-markering). 14–18 **inte mätbara** — 4 scriptade
  episoder är en PoC; minst 200 goldenevents + 1000 shadowbeslut krävs före promotion.

### Verifieringsstatus på integrationsbranchen

- Backend: full `pytest` **4226 passed, 36 skipped** (inkl. samtliga clause-/tabular-/
  owner-/fingerprint-tester); ruff grön; maintainability grön.
- Frontend: `pnpm lint` (oxlint) grön; `tsc --noEmit` grön; vitest **344 passed**.
- swe-gym: `cargo test` helt grönt (bandit/TD/ledger/frysta armar + 7 nya policytester).
- `maturin develop` (swe_native) byggd så research-vägen är testad.

**Produktionen är fortsatt opåverkad:** inga ändringar i research-/Jev-/SWE-/
expertchatt-/Tabular Review-/rapportbeteende; inga experimentarmar kopplade till
produktionsbeslut; ingen backend-shadow är inkopplad (Fas 3 är gym-intern).
Öppna beslut O1–O5 kvarstår (O1 löst enligt ovan).

---

## 1. Aktuell HEAD och lästa instruktioner

| Faktum | Värde |
| --- | --- |
| Lokal HEAD | `1e0507122a19f77224bf90315e11c8c7ea049e22` — "swe-gym: chain experiment" (2026-10-27 18:16) |
| Branch | `feat/swe-gym-poc` (ingen upstream konfigurerad) |
| Specens referenscommit `4d6aed55` | Merge PR #438 (research-ordering-measurement), finns på `origin/main` — **inte** en anfader till lokal HEAD |
| Merge-base mot origin/main | `b55eae13` (2026-10-22 22:01) |
| Lokal HEAD vs origin/main | **59 commits före** (swe-gym v2: 30 golden questions, chain-experiment, budget-MDP-gym) och **177 commits bakom** (clause-SSR PR #428, Tabular Review PR #429, Overgraph Owner PR #432, live voice, research-ordering PR #438) |
| origin/main-tip | `482aaecd` (2026-10-27 19:25, merge PR #430 ticket40-tabular-perf) |
| Ocommittad WIP i arbetskopian | ~44 modifierade filer + flera untracked (live speech/STT: `api/live_speech.py`, `services/live_speech_*`, `elevenlabs_live`, `gemini_live`, `openai_live_*`, `config.py`, `database/models.py`, `schemas/domain.py`, `main.py`, frontend live-voice, `194_stt_correction.py`, `experiments/overgraph_ingest/eval/research-ordering-v1.md` + `tests/test_research_ordering.py`, `docs/architecture/clause-ssr-embedding-migration.md`, `crates/swe-gym/benchmarks/variant_capture/`, `examples/v2_variants.rs`). **Inte rörda under denna inventering.** |

**Instruktioner lästa i sin helhet:** rot-`AGENTS.md`, `backend/AGENTS.md`, `frontend/AGENTS.md`, `crates/swe-gym/AGENTS.md` (child-AGENTS med egna friheter + 6 icke-förhandlingsbara kvalitetskrav), `docs/architecture/reuse-before-new.md`, `docs/architecture/workflow-first-execution.md`, `docs/specs/overgraph-knowledge-engine.md`, `docs/architecture/overgraph-catalog-routing.md`, `docs/architecture/ssr-anchor-library-extension.md`, `docs/architecture/ssr-clause-pr-review.md`, `docs/architecture/clause-ssr-embedding-migration.md` (untracked WIP), `docs/architecture/clause-ssr-library.md` (origin/main), `docs/architecture/clause-ssr-reuse-audit.md` (origin/main), `docs/architecture/catalog-owner-routing.md` (origin/main), `docs/specs/tabular-review-ssr-v1.md` (origin/main), `docs/specs/tabular-review-later-phases.md` (origin/main), `docs/guides/expert-reasoning-route.md`, `docs/guides/research-jev-controller.md`, `docs/guides/research-jev-shadow.md`, `docs/SWE_Sweycoins_resultat.md` (origin/main), `docs/SWE_Sweycoins_strategi.md` (origin/main), `experiments/overgraph_ingest/eval/research-ordering-v1.md` (untracked WIP). Djupinventeringar från tre parallella delrapporter: `.scratch/ssr-generalization/inventory-ssr.md` (303 rader), `inventory-gym.md` (526 rader), `inventory-overgraph.md` (429 rader).

**Verifieringsmetod:** origin/main-kod läst via en read-only git worktree (`/tmp/socialism-main`, detached `482aaecd`); lokal kod läst direkt (WIP-smutsiga filer via `git show HEAD:`/`git grep HEAD`). Backend `uv sync` OK; `tests/test_anchor_sets.py` 9/9 gröna; swe-gym `cargo test` grönt (se §2.7). `swe_native`-extensionen är inte byggd i denna miljö (kräver `make swe-native`), vilket begränsar vilka backend-tester som kan köras lokalt innan Fas 1 (researchvägen kräver extensionen).

---

## 2. Verifierad inventering av implementation, data, tester, API och callers

### 2.0 Det kritiska fyndet: branch-topologin

Specen beskriver en repositorytillstånd som motsvarar **origin/main** vid `4d6aed55`. Den aktuella arbetskopian är branch `feat/swe-gym-poc`, som divergerade från origin/main **2026-10-22 — innan clause-SSR-biblioteket, Tabular Review och Overgraph Owner-stacken mergeades**. Konsekvens:

- **`backend/app/services/clause_ssr/`, `backend/app/api/clause_ssr.py`, `backend/app/services/tabular_review/`, `backend/app/api/tabular_reviews.py`, `backend/app/database/tabular_review.py`, `backend/app/services/overgraph/owner*.py` existerar inte på lokal HEAD** (verifierat med `git grep` på HEAD — noll träffar på `clause_ssr`/`SsrClassification`).
- Lokal HEAD har istället: (a) **rapport-SSR** (`services/ssr/` — ton/stil-Likert-ankare för snabbrapporter, identiska filer på main), (b) **SQL-kalibreringsankarbiblioteket** (`api/anchor_sets.py`, `anchor_pool.py`, `anchor_store.py`, `anchor_calibration.py` — `SsrAnchorSet`/`SsrAnchorPoolItem` i `database/models.py`, samexisterar med OverGraph-setten även på main), (c) `document_qa` (med `QUESTION_KINDS` inkl. `tabular_review` som enum-värde utan producent), (d) hela swe-gym v2-arbetet.
- Lokal HEAD har **nyare** swe-gym: `golden_v2.json` (30 frågor, dual facit), `chain_synthesis/`, v2-gym (`env.rs`, `agent.rs`, `student.rs`, `explore.rs`), `bench_real_v2.json` — dessa saknas på origin/main.

Alla spec-påståenden om "befintlig clause-SSR" bekräftas därför **mot origin/main**, och §4 dokumenterar avvikelserna mot lokal HEAD. Fas 1–3-planen (§7) förutsätter ett explicit branch-beslut (§8).

### 2.1 Befintlig Clause SSR (verifierad på origin/main `482aaecd`)

**Spec-påståendena i uppdraget bekräftas i huvudsak, med fyra korrigeringar:**

1. **Objekten finns:** `SsrClassification`, `SsrVerification`, `SsrVerificationRevision`, `SsrClauseAnchor`, `SsrClauseAnchorSet`, `SsrReviewSession` — alla som OverGraph-noder med `scope_key`-prop + scope-label, medvetet **utanför** `KNOWLEDGE_TYPES` (`services/clause_ssr/labels.py` L9–22), kanter namespacede `ssr.ABOUT/ANSWERS/DERIVED_FROM/REPRESENTS/MEMBER_OF/FOR/SUPERSEDES`. TextUnits återanvänds; ingen parallell vektor- eller dokumentdatabas.
2. **YES/NO är frågespecifika; skip/unsure är inte labels** (`verifications.py`; test `test_clause_ssr_store.py::test_skip_unsure_are_not_labels`, `test_no_is_not_generic_irrelevant`). **Promotion och AnchorSet-bygge är explicita** (`promote_anchor` aldrig automatiskt, re-check-race-guard L82–85; `build_anchor_set` supersederar, `deterministic_diversity`, max 12 per polaritet, holdout).
3. **Matchning:** `POST /clause-ssr/match` finns (`api/clause_ssr.py` L430–459, admin-only). Återanvänder TextUnitens lagrade `dense_vector` när `EmbeddingSpec(model, revision, dimension)` stämmer (`spec.py` L9–14); failar högt vid saknad/inkompatibel vektor; returnerar top-k (default k=8), `category_scores` med `score = mean(pos-sims) − 0.5·mean(neg-sims)`, `margin`, `support_count`, `independent_support` (unika content_hash), `negative_signal`, `top_similarity`, abstention med `abstain_reason`, multi-label inom 0.04. `score_kind: "cosine_similarity"` + `not_a_probability: true` på matchresultat och varje CategoryScore (`serialize.py` L132–170).
4. **Trösklar — KORRIGERING mot spec:** de är **hårdkodade modulkonstanter, inte versionerade kalibreringsartefakter**: `MIN_SIMILARITY = 0.25`, `MIN_MARGIN = 0.04`, `SUPPORT_THRESHOLD = 0.45` (`match.py` L22–24). Tabular: `DEFAULT_SCORE_THRESHOLD = 0.35` per review i DB (`tabular_review/types.py` L17, DB-default), `abstain_margin` per kolumn. Detta är exakt det spec §3.3 vill ersätta med "en versionerad kalibreringsartefakt kopplad till AnchorSet eller matchprofil".
5. **Dubbel implementation:** clause_ssr har en synkron Catalog-variant (`match.py`, `queue.py`, `sessions.py`, `select.py`, `classifications.py`, `verifications.py`, `anchors.py`) och en async Owner-variant (`owner_match.py`, `owner_queue.py`, `owner_select.py`, `owner_classifications.py`, `repository.py` 590 rader). API:t väljer Owner-vägen när `get_owner_runtime().client` finns, annars Catalog via `asyncio.to_thread`. Matchlogiken delas (`owner_match` återanvänder `_rank_hits/_category_scores/_decide_labels`).

**Revocation/supersede:** `record_decision` med ändrat svar arkiverar gammal revision som `SsrVerificationRevision` med `SUPERSEDES`-kant och **revokerar härledda ankare** (L127–132); `revoke_verification` gör detsamma; `anchor_is_matchable` är en läs-guard (aktiv verifikation + samma polaritet, L239–247) så att en återkallad/superseded verifikation omedelbart gör ankare obrukbara för nya matchningar medan historiken bevaras. Tester: `test_clause_ssr_revocation.py` (195 rader) + owner-konkurrenstester (`test_clause_ssr_owner_repository.py`).

**API:** `/clause-ssr/classifications` (GET/POST/PATCH), `/queue`, `/decisions`, `/decisions/undo`, `/anchors/promote`, `/anchors`, `/anchor-sets`, `/anchors/mark-stale`, `/match`. Alla admin-only, tenant-isolerade (`customer_id` → `visible_scope_keys`), ägandekontroll före top-k.

### 2.2 Overgraph, TextUnits, fakta och provenance

- **TextUnit** (`knowledge/units.py`): `id = sha256(document_version_id \0 locator \0 content_hash)`, `content_hash = sha256(text)`, `document_version_id` = uuid4 per temporal förekomst, `ordinal`, `locator`, `page_start/page_end`, `char_start/char_end`, `valid_from/valid_to`, `ingested_at`, `embedding`. **Auktoritativ i OverGraph — ingen SQL-spegel** (migration 191). OverGraph-noden bär ingen embeddingmodel/revision-prop; embedding-identiteten hålls i tre lager: katalogdimension (knowledge=3072), `EmbeddingSpec`-validering, och SQL `graph_embedding_cache` (nyckel = sha256 av model/revision/dimension/purpose/text-hash, med lease/single-flight).
- **Fakta:** Graph v2 `FactInput(source_id, target_id, predicate, fact_text, sources: tuple[SourceRef], …)` med `SourceRef(kind ∈ text_unit|episode, ref)` (`graph_v2/types.py` L27–50); OverGraph-faktanod med `SUPPORTS`-kanter per källa, `SUBJECT/OBJECT/CONTEXT`, `CONTRADICTS`, `valid_at/invalid_at`; `owner_facts.py` har innehållsadresserad fact-key förankrad i `document_version_id`. OverGraph-kanter har ingen stabil nyckel eller embedding (spec: bekräftad — `edge_uniqueness = (from,to,label)`).
- **Owner-protokoll (origin/main):** exakt en writer per katalog via flock på `./.owner.lock` (`owner.py` L73–78), backend i owner-mode öppnar aldrig knowledge-katalogen (`owner_guards.DirectWriteForbidden`), Unix-socket newline-JSON (16 MB, 30 s), en skriv-tråd, `MutationReceipt` + `payload_hash` i samma transaktion (idempotens), fsync före ack (durabilitet), `expected_nodes/expected_absent`-preconditions med retry. Registry: `(kind, customer_id)` → socket (`catalog-owner-routing.md`). **På lokal HEAD finns ingen av detta** — lokala `document_qa/owner.py` är `TenantCatalogs` (flock per tenant-katalog), inte single-writer OvergraphOwner.
- **Skrivvägar lokal HEAD:** direkt synkron Catalog (document-ingest, research/answers/claims) + `graph_ingest_work`-outbox med pollande worker (skip_locked lease, backoff). Inga DB-transaktioner hålls över externa anrop (verifierat i `fill_review` med pool_size=1-probe-test).

### 2.3 Tabular Review och dokumentnavigation

- **Tabular Review (origin/main):** opt-in SSR-tabell, en avtalsrad per dokument (`TabularReviewRow`), **aktivt OverGraph AnchorSet per kolumn** (`TabularReviewColumn.anchor_set_id`, valideras mot `category == label` + `can_reference`), celler med `exact_text` (verbatim TextUnit), `similarity` (cosinus), `source_json` (befintlig locator — `locators.py` fabricerar aldrig geometri), `status ∈ hit|no_hit|unknown|negative_hit`; under tröskel = **"Ingen träff"** (≠ klausul saknas, ≠ negativ bevisning — testat). Låsta celler hoppas över vid omkörning; omkörning resetar olåst `approved→pending` vid resultatbyte. Reviewhistorik i `TabularReviewCellEvent`; approve/reject skriver `TabularReviewVerificationLabel` med `activated_as_ssr_anchor = false` (aldrig automatisk anchor-promotion). Cache-key inkluderar content_hash + AnchorSet id/version/pool revision + embedding-model + label + polarity. **ExtractedValue finns inte** — utvinning är explicit senare fas (`tabular-review-later-phases.md`). Callers: endast admin/opt-in-modulen (`tabular_review` i `available_modules`); **inte** importerad av research/Jev/rapport-SSR (testbevisat).
- **Dokumentnavigation:** spec `docs/specs/expert-chat-document-navigation.md` finns lokalt (Fas 0 klar): capabilities mappade på befintliga verktyg (`show_document`, `focus_anchor`, `read_source` outline/section/quote, `search_knowledge`), locators page/char-intervall, frontend `pdfAnchorPresentation.ts` (`page|document|unlocatable`), `PdfKnowledgeViewer` återanvänds; dokument utan locator visas som hela dokumentet utan påhittade positioner.

### 2.4 Jev-routing, shadow och Research Gym

- **Jev/LLM-routing (expertchatten):** `expert_reasoning.py` bedömer varje tur med Jev System One (8 NOUL-scores från promptfältet `chat.expert.reasoning_assessment`; state klippt till 4000 tecken) och väljer `fast|balanced|deep` med **deterministiska tröskelregler** (deep vid conflicting≥0.75/synthesis≥0.7/comparison≥0.8/analysis≥0.9 eller 0.75+multi_step≥0.75; fast kräver simple≥0.85 med hårda max-tak; fel/timeout → balanced). `llm/selection.py` matchar profilen mot `llm_configurations` (`selection_role`, `enabled_for_auto`, capability-flaggor). Profil kan bara höjas under en tur; `spawn_workers` vid deep+decomposable/parallelizable≥0.85. Event `expert_chat.reasoning_routed` (loggar ej användarmeddelande). Spec: bekräftad — dock **ingen propensity-loggning**.
- **Research shadow:** `fast_gate.py` ordning programmatisk → Jev → LLM; default off; med nyckel default **shadow** (Jev och auktoritativ LLM körs parallellt, LLM-resultatet publiceras, `research.jev.shadow_comparison` loggas); `active` kan kortsluta. Jev-fel → alltid LLM-vägen. Samma mönster för completeness-reviewer.
- **Research Gym (`crates/swe-gym`):** append-only Sweycoin-ledger (`Allocate/Reserve/Spend/Release/Transfer/Reward`; `available` aldrig negativ; idempotensnycklar; reward i ospenderbar pool; replay för resume) — **`allocate`, `reserve`, `spend`, `release`, `transfer` finns** (spec §8.2: bekräftad). Hårda budgettak → `RuntimeError::limit` (högljutt). Replay/live-seam via `run_arm_with_provider` (samma harness, annan provider; live env-gatad). Facit-isolering via typsystemet (`QuestionView` vs `Question`). Armar: A sekventiell, B parallell, C adaptiv, C* orakel (diagnostik), **D** linjär bandit (ett djupbudgetbeslut), **E** sekventiell bandit (per-scan), **G** TD(0)-Sarsa, H likhetsordnad scan; v2-gym = budget-MDP över 3 capabilities (Invest/Pause/Stop/Finish, DP-orakel, McQLearner, teacher/student/exploration). **Tidigare armar D/E/G är frysta jämförelseunderlag och får inte ändras** (spec: bekräftad som policy i AGENTS.md + frysta benchfiler).
- **Benchversioner:** `bench_v1.json` (syntetisk, 2 frågor), `bench_real_v2.json` (5 riktiga juridiska frågor: auto-renewal/notice-period/liability-cap/confidentiality/liability-secrecy-carveout, totalbudget 2 000 000, riktiga chunk-texter + uppmätt `scan_order`), `real_fixtures/` + `real_fixtures_deep/` (**2019 frysta JEV-svar**), `jev_fixture_v1.json`, `golden_v2.json` (**30 frågor**, dual facit evidence+conclusion), `golden_v2_fixtures/g2-XX-{jev,llm}.json`, `chain_synthesis/`. Chain-experimentet (HEAD) kördes men CHAIN_C/D/D_NEEDS felade med "invalid LLM answer" (formatfel) på 5 frågor — ej validerat mot facit.
- **Gym-resultat (frysta, från `docs/SWE_Sweycoins_resultat.md`):** JEV 100 % goldträffar på de 5 riktiga frågorna; arm H 9–15× bättre scanningsfront än A; D bäst kvalitet/Sweycoin i brusig värld; G konvergerar till C och slår C i strukturerad värld (337/500). Tre inlärningsfällor dokumenterade (frusen rng, linjär överanpassning, myopisk shaping).

### 2.5 Data och gold (manifest)

| Gold | Plats | Innehåll |
| --- | --- | --- |
| Klausullokalisering | `experiments/overgraph_ingest/retrieval_gold/` (lokal + main) | 9 klausul-golder: assignment, auto-renewal (`measured_c8`), confidentiality, force-majeure, governing-law, liability-cap, liability-secrecy-carveout, notice-period, personal-data + expansions, blind/, document_properties/, question_gold/, index.json (`legal-questions-v1`) |
| Research-ordering | `experiments/overgraph_ingest/eval/research-ordering-v1.md` + `baselines/research-ordering-v1.json` + `tests/test_research_ordering.py` | scans-until-covered per strategi (dense/sparse/hybrid/union_rrf/union_pool) på 2548 TextUnits; **untracked WIP lokalt, tracked på origin/main** (PR #438) — merge-konfliktrisk |
| Researchkvalitet | `backend/tests/fixtures/research_eval/` (3 fall: 36_avtl, nja_2005_142, sou_1974_83) + `fixtures/sufficiency_experiment/pr420_cerebras_baseline.json` + 18 kod-frysta `GoldenCase` i `sufficiency_experiment/golden.py` | 10-stage-harness + fryst PR #420-baseline |
| Bred routing | `synthetic_sme/` (repo-rot, SPEC-SME-1.0, version 1.0.0, seed 20261018) | **200 Golden Questions** GQ-001…200 (`golden_questions/golden_questions.json`), `ground_truth/facit.json` (200 poster), `truth_model.json`, `coverage_matrix.json`, `provenance.json`, ~200 DOCX/PDF-avtal i `contracts/`, 3070 filer |
| Dokumenttyp | **Finns inte.** Specen kräver ett nytt mänskligt verifierat goldenset (anställnings-/aktieägar-/övriga avtal). Kandidatkorpus: `synthetic_sme/contracts/` + `data/suite-corpus/` | att byggas i Fas 2 |
| Gym-bench | `crates/swe-gym/benchmarks/` | bench_v1, bench_real_v2, golden_v2 (+fixtures/ranks/measurement/chains), jev_fixture_v1, real_fixtures(+deep), real_trajectories_v1 |

**Korrigering mot spec:** specen nämner "research-sufficiency-goldens, stage-specifika research-fixtures och SPEC-SME:s 200 Golden Questions i `synthetic_sme/ground_truth/`" — verifierat: goldens och fixtures finns, och de 200 frågorna ligger i `synthetic_sme/golden_questions/golden_questions.json` med facit i `synthetic_sme/ground_truth/facit.json`.

### 2.6 Tester och verktygskedja

- **Backend:** `uv sync` OK. `pytest tests/test_anchor_sets.py` 9/9 gröna. **`swe_native` ej byggd** i denna miljö (ingen `maturin`-build gjord); research-/swe-bro-tester kräver `make swe-native`. Relevant befintlig täckning (origin/main): 7 clause_ssr-testfiler (~1300 rader), 4 tabular-testfiler (~790 rader), 19 overgraph-owner-testfiler; konkurrenstester för pool-release (`fill_review` med pool_size=1+probe). Täckningsluckor dokumenterade i `inventory-ssr.md` §G (owner_match/owner_select saknar isolerade tester; low_margin/negative_score-abstention inte explicit testade; mark-stale/list-sets saknar API-tester).
- **swe-gym:** `cargo test` grönt (cargo 1.83.0 via rustup; PATH behöver `~/.cargo/bin`). 15 testfiler.

### 2.7 Callers (produktionsvägar)

- `clause_ssr`/`tabular_review` (main): registreras i `main.py` respektive `modules/registry.py` (ModuleManifest `tabular_review`, opt-in per kund). **Inga** research/SWE/Jev/rapport-SSR-importörer (testbevisat: `test_clause_ssr_benchmark.py::test_research_imports_ignore_clause_ssr`).
- Research auktoritativ väg: `execution.py::_run_research_loop` → `swe_bridge.run_research_loop_via_swe` → `WorkflowRunner` (enda söm; gamla loopen raderad). Gates: `fast_gate.py`/`fast_controller.py`/`evidence_screen.py`.
- Expertchat: `expert_reasoning.py` → `llm/selection.py::resolve_llm_runtime` → `llm_configurations`.
- Frontend (main): `ClauseSsrQueuePage.tsx`, `TabularReviewPage.tsx` + `components/tabular-review/`, `api/clauseSsr.ts`, `api/tabularReviews.ts`. **Saknas helt på lokal HEAD.**

---

## 3. Reuse-vs-new-matris

| Ny enhet (spec) | Befintlig motsvarighet | Beslut | Motivering | Bevis/integrationstest |
| --- | --- | --- | --- | --- |
| Generaliserad subject-modell (`text_unit`/`fact`/`document_version`) | clause_ssr `Verification.source_unit_id` (implicit TextUnit); Graph v2 `FactInput`+`SourceRef`; `knowledge/units.py` TextUnit | **extend** | Spec §3: "utvärdera först om befintliga typer kan utökas med en subject-referens". Lägg `subject_kind`+`subject_id`+`subject_hash` på `SsrVerification`/`SsrAnchor`; behåll TextUnit-vägen orörd. Ingen ny matchmotor. | `test_clause_ssr_match.py` (återanvändning av `ssr.similarity.cosine_similarity`); nya subject-tester i Fas 1 |
| Matchkärna för TextUnit + Fact | `clause_ssr/match.py` + `owner_match.py` (gemensam `_rank_hits/_category_scores/_decide_labels`) | **reuse** | En matchkärna; Fact-subject löser bara ut en annan vektor+källa; rendering-version läggs till EmbeddingSpec-kontraktet. | befintliga match-tester + nya fact-match-tester |
| Versionerade trösklar/kalibreringsartefakt | `MIN_SIMILARITY/MIN_MARGIN/SUPPORT_THRESHOLD` (hårdkodade konstanter, `match.py` L22–24); `SsrAnchorPool` revisionsräknare (`repository.py` L52–70); SQL-kalibreringsbiblioteket (`anchor_calibration.py`, `SsrAnchorCalibrationItem`) | **new (liten)** | Spec §3.3 kräver versionerad artefakt kopplad till AnchorSet/matchprofil; dagens konstanter är just vad specen förbjuder att ändra "genom globala magiska konstanter". Namn: `SsrMatchProfile` (eller `SsrThresholdSet`) med version, fält per tröskel, supersede; AnchorSet/matchprofil refererar den. Läses via Owner-läsning. | nytt test: threshold-set versionering + abstain-ändring via ny version, gamla resultat behåller gammal version |
| Fingerprint (`SsrFingerprintDefinition`/`SsrDocumentFingerprint`) | Inget. Närmast: tabular score-cache-key, `golden_v2`-kedjemätning, `research-ordering-v1` (union_pool-mätning) | **new** | Spec §5 definierar en kategorinycklad sparsam struktur — ingen befintlig motsvarighet. Byggs i Fas 2 som offline-experiment över befintlig matchkärna. | offline-harness + reproducerbarhetstest (samma fingerprint två körningar) |
| Dokumentklassificerare | Inget; `document_properties`-golder och `doctype-*-v1`-evalrapporter i `experiments/overgraph_ingest` | **new (offline)** | Enkel linjär/regelbaserad klassificerare utan ny dependency (spec §5.2); körs bara i harness. | Fas 2 benchmark + frozen report |
| `ExtractedValue` + extraktionsschema | Inget (tabular "no value extraction"); `document_properties`-Jev-verifiering som mönster | **new (senare fas)** | Spec §3.5/§6: läggs i Fas 4, efter Fas 1–3-grindar. Typade schemas (duration/datum/pengar/procent/text) som pydantic-modeller. | Fas 4-tester |
| `PolicyDecisionEvent` + propensity | `expert_chat.reasoning_routed` (scores/profil, ingen propensity), `research.jev.*`-events, swe-gym `StepRecord`/`Trajectory` (dataset v4, ingen propensity) | **new** | Spec §9 kräver enhetligt event med propensity; dagens tre disjunkta loggar saknar val-sannolikhet. Byggs i Fas 3 i swe-gym (dataset v5 + event-schema), inte i backend-appen. | dataset_tests.rs (v5 roundtrip + propensity) |
| Policy A (ssr_to_jev + model_profile som två beslutspunkter) | swe-gym `Strategy`-trait (D/E/G/H), v2-env (Invest/Pause/Stop/Finish), `expert_reasoning.route_scores` (deterministisk) | **new policyfamilj bredvid, ej ändring av D/E/G** | Spec §8.1: nya, tydligt versionerade policyfamiljer; tidigare armar frysta. Återanvänd ledger/harness/provider-seam/facit-isolering. | nya benchversioner (`bench_policy_a_v1.json`), befintliga tester oförändrade |
| Policy B (budgetallokering) | swe-gym ledger + D (ett budgetbeslut) + v2 budget-MDP | **new policyfamilj bredvid** | Separat policy-id/actionrum/reward/artifact (spec §8.2); contextual bandit för ett budgetbeslut först. | nya tester + benchversion |
| Shadow-instrumentering i backend | `fast_gate.py` shadow (parallell Jev, LLM auktoritativ), `stop_shadow` | **reuse/extend** | Spec §9: shadow får logga men aldrig ändra auktoritativa svar. Samma mönster. | befintliga shadow-tester som mall |
| Dokumenttyps-navigation | `document_navigation.py`, `pdfAnchorPresentation.ts`, `PdfKnowledgeViewer` | **reuse** | Spec §3.6: återanvänd befintliga viewers/locators; inga påhittade positioner. | befintliga navigationstester |

**Inte tillåtet att bygga (per inventering):** ett andra vektorbibliotek, SQL-kopior av ankare/TextUnits/Facts/embeddings, ett parallellt `/semantic-ssr`-API, en andra matchmotor, ändringar av frysta armar D/E/G eller deras benchfiler, import från `crates/swe-gym` i `backend/app`.

---

## 4. Avvikelser mellan repositoryt och specen

1. **Branch-topologi (blockerande för genomförande):** specen förutsätter clause-SSR/Tabular Review/Owner-stacken i arbetskopian; de finns bara på origin/main. Lokal HEAD har i stället 59 nyare swe-gym-commits. Inget av träden har allt. **Beslut krävs innan Fas 1** (§8, öppet beslut O1).
2. **Trösklar inte versionerade:** spec §3.3 ("versionerad kalibreringsartefakt") vs hårdkodade konstanter i `match.py`.
3. **Subject-modell:** spec §3.1 kräver `fact` och `document_version`; befintligt har endast implicit TextUnit.
4. **Fingerprint/klassificerare/ExtractedValue/PolicyDecisionEvent:** existerar inte i något av träden (spec §4/§5/§6/§9 är nybygge).
5. **Propensity:** saknas även där strategidokumentet §10.2 kräver det (bandit/TD loggar ingen val-sannolikhet).
6. **Dokumenttypgold:** spec §5.2 kräver ett nytt mänskligt verifierat goldenset; finns inte. `synthetic_sme/contracts/` (~200 avtal) är en kandidatkälla men klassificerade per kontraktstyp måste verifieras manuellt.
7. **Dokumentnamn:** specen refererar `docs/architecture/catalog-owner-routing.md` — på origin/main heter den det (lokalt finns en äldre `overgraph-catalog-routing.md`). `docs/architecture/clause-ssr-library.md` och `clause-ssr-reuse-audit.md` finns endast på origin/main. `docs/SWE_Sweycoins_*` endast på origin/main.
8. **Spec-filen själv:** uppdragets spec-dokument (avsnitt 3.1–3.6, 8–11) finns inte i någon checkout — gap-analysen har gjorts mot de namngivna kraven i uppdraget.
9. **Chain-experimentet (HEAD):** CHAIN_C/D/D_NEEDS felade med formatfel ("invalid LLM answer") — gymmet har v2-bencharna men kedjevalideringen är oavslutad. Ingen påverkan på frysta v1-resultat.
10. **WIP-kollision:** `experiments/overgraph_ingest/eval/research-ordering-v1.md` + `tests/test_research_ordering.py` är untracked lokalt och tracked på origin/main (PR #438) — merge/rebasing måste hantera detta.
11. **Miljö:** `swe_native` inte byggd lokalt; backend-testkörning begränsad tills `make swe-native` körts.

---

## 5. Föreslagen data-/gold-split med leakage-kontroller

### 5.1 Dokumenttyp (Fas 2) — nytt goldenset

- **Källa:** `synthetic_sme/contracts/` (customers/suppliers/employees/corporate, ~200 DOCX+PDF). Mänsklig verifiering på dokumentversionsnivå av: `anstallningsavtal`, `aktieagaravtal`, `ovriga_avtal` (hårda negativa).
- **Splitenhet = dokumentfamilj/template + organisation, aldrig dokumentversion.** Ett gold-manifest `experiments/ssr_fingerprint/gold/document-type-manifest.json` med per dokument: familj-id (template-hash-grupp), org-id (motpart), klass, text-enhets-hash-lista, dokumentversionshash.
- **Regler (leakage-kontroll):**
  1. Samma template/familj får inte förekomma i både train och test.
  2. Samma organisation (motpart) får inte förekomma i både train och test (förhindrar nära dubbletter via klipp-och-klistra-mallar).
  3. Near-duplicates grupperas med content_hash på TextUnit-nivå; två dokument vars TextUnit-hash-mängd överlappar >50 % (Jaccard) tilldelas samma split-sida.
  4. Holdout (10–20 % av familjerna) rörs inte förrän slutlig evaluation.
  5. **Filnamn/metadata exkluderas från features** (spec §5.1) — träna aldrig på filnamn.
- **Rapportering:** om färre än ~10 oberoende familjer per klass finns ska resultatet uttryckligen rapporteras som otillräckligt och ingen promotion göras (spec §5.2).

### 5.2 Klausullokalisering (Fas 1-utvärdering)

- Återanvänd `retrieval_gold/` 9 klausul-golder (frysta, `index.json` legal-questions-v1). Guld-TextUnit-id:n hålls utanför AnchorSet-bygge (befintlig holdout-mekanism i `select.py` + `test_clause_ssr_benchmark.py`).
- Stabilitetsmätning efter 2/4/8/12 verifierade ankare per polaritet använder deterministisk `deterministic_diversity`-selektion (befintlig, reproducerbar).

### 5.3 Routing (Fas 3)

- Offline: `bench_real_v2` (5 frågor) + `golden_v2` (30 frågor, dual facit) — redan delade i frysta fixtures; nya policyfamiljer får **nya benchversioner** bredvid (spec: ändra inte historiska benchfiler).
- Bred routing: `synthetic_sme` 200 GQ delas per `area` (8 områden: Ekonomi/Juridik/Marknad/Personal/Risk/Strategi/VD-beslut/Verksamhet) — stratifierad split, facit från `ground_truth/facit.json` hålls utanför policykontexten.
- Gold/replay först, bounded live-shadow sist (spec §14: shadowkostnad).

---

## 6. Exakt experimentprotokoll och frysta acceptansgränser

Fullständigt, versionerat protokoll: [ssr-generalization-experiment-protocol.md](ssr-generalization-experiment-protocol.md). Sammanfattning av de frysta grindarna (spec §11 defaultgrindar, oförändrade):

| # | Grind | Gräns |
| --- | --- | --- |
| 1 | Tenantläckor (match/kö/AnchorSets/fingerprints/navigation/policyloggar/fact-provenance) | 0 |
| 2 | Resolvable provenance på alla träffar/extraherade värden | 100 % |
| 3 | Connection-release vid externa anrop (pool_size=1-probe) | grön |
| 4 | Saknad/stale embedding/AnchorSet/policyversion | fail loud / abstain, ingen tyst alternativ modell |
| 5 | Scriptade/replayade/live-resultat separerade | alltid märkta |
| 6 | Klausullokalisering Recall@5 på held-out gold; hard-negative rank ej sämre | ≥ 0,95 |
| 7 | Median scans-until-covered vs replay av produktionsordning | ≥ 2× bättre |
| 8 | Dokumentklassificering macro-F1; precision/recall per klass | ≥ 0,90 resp. ≥ 0,85 på familje-held-out |
| 9 | Selective accuracy vid abstention | ≥ 0,95 vid ≥ 0,70 coverage |
| 10 | Fingerprint vs centroidbaseline | måste **slå** på macro-F1 och selective accuracy |
| 11 | Grounding + schema validity (extraktion) | 100 % |
| 12 | Normaliserad value accuracy | ≥ 0,90 totalt, ≥ 0,85 per värdetyp |
| 13 | Unsupported/hallucinerad value rate | 0 |
| 14 | Kvalitetens nedre 95 % KI vs deterministisk kontroll | ≤ 1 p.e. sämre (totalt och per kritisk uppgiftstyp) |
| 15 | SSR→Jev: Jev-anrop −30 % utan kvalitetsförlust > 1 p.e. | ja |
| 16 | fast/balanced/deep: p95-latens eller kostnad −20 % vid samma kvalitet | ja |
| 17 | Budgetpolicy: verifierad kvalitet/Sweycoin +10 %; solve/pass-rate ≥ −2 p.e. | ja |
| 18 | Minst 200 oberoende goldenevents + ≥1000 shadowbeslut före produktionsbeslut | ja |

Frysta konstanter (protokollfilen): seeds (20261027 för nya experiment; befintliga benchar behåller sina pinnade seeds), tariffer (scan 1000 / deep 10000 milli, totalbudget 2 000 000 i bench_real_v2), belöningslambdas (`lambda_cost = 1.0 / 10_000_000` per milli, `lambda_latency = 1.0 / 900_000` per ms — fryses före valideringskörning), embedding-identitet (`text-embedding-3-large`, revision v1, dim 3072).

---

## 7. Konkret PR-plan (filer per fas)

Förutsättning: öppet beslut O1 (branch-bas) löst — rekommendation nedan antar en integrationsbranch.

### Fas 0 — Inventering (denna leverans)
- Ny: `docs/architecture/ssr-generalization-inventory.md`, `docs/architecture/ssr-generalization-experiment-protocol.md`, `.scratch/ssr-generalization/inventory-{ssr,gym,overgraph}.md`. Ingen produktionskod.

### Fas 1 — Generaliserad subject-modell i isolerad SSR-kärna
- **Bas:** origin/main (eller merge därav). Ändringar:
  - `backend/app/services/clause_ssr/types.py`: lägg `subject_kind ∈ text_unit|fact|document_version`, `subject_id`, `subject_hash`, `rendering_version` på `Verification`/`Anchor` (bakåtkompatibla default för TextUnit).
  - `backend/app/services/clause_ssr/match.py` + `owner_match.py`: matchkontraktet utökas med subject-ref; `document_version` löses till en deterministisk fingerprint-matchfunktion (v1: max-pooling över TextUnits), `fact` löser Fact-nodens vektor via `owner_facts.py`-läsning med `EmbeddingSpec`-kontroll.
  - Ny: `backend/app/services/clause_ssr/subjects.py` (subject-upplösning: id → vektor + hash + rendering-version; fail loud vid inkompatibel embedding).
  - Ny: `backend/app/services/clause_ssr/thresholds.py` (versionerat tröskelset `SsrMatchProfile` med supersede; nuvarande konstanter blir `match-profile-v1` default — ingen semantisk ändring utan benchmark).
  - API: `backend/app/api/clause_ssr.py` — `POST /match` tar `subject: {kind, id}` (+ bibehåller `text_unit_id` för interna callers under samma serie; ingen permanent shim).
  - Tester: nya `test_clause_ssr_subjects.py`, `test_clause_ssr_thresholds.py`; utökade match-tester. **Ingen** research-/tabular-/expertchatkoppling.
- **Grindar att verifiera:** 1, 2, 4, 6 (Recall@5 på retrieval_gold med befintligt flöde).

### Fas 2 — Fingerprint och dokumenttypbenchmark (offline)
- Ny katalog `experiments/ssr_fingerprint/`: `fingerprint.py` (build_fingerprint enligt spec §7.2-kontrakt), `classify.py` (linjär/regelbaserad + abstain), `benchmark.py`, `gold/` (manifest + labels), `reports/frozen-*.md`.
- Återanvänder: `clause_ssr`-matchkärna per kategori, `ssr.similarity.cosine_similarity`, `experiments/overgraph_ingest`-verktyg för TextUnit-läsning.
- Inga produktionsändringar; ingen HTTP-yta (spec §7.2: CLI/harness räcker i första PR).
- **Grindar:** 6, 8, 9, 10; rapport fryses före tolkning.

### Fas 3 — Adaptiva policyexperiment i swe-gym (shadow)
- **Endast `crates/swe-gym/`** (isolering + importförbud bibehålls). Nya filer bredvid befintliga:
  - `src/policy_a.rs`: två beslutspunkter med egna policy-id:n — `ssr_to_jev` (accept/abstain/escalate) och `model_profile` (fast/balanced/deep), egna actionrum/rewards/versionshistorik; capability-maskering.
  - `src/policy_b.rs`: separat budgetpolicy (ett budgetbeslut, contextual bandit; återanvänd `ledger.rs` allocate/reserve/spend/release/transfer).
  - `src/policy_event.rs`: `PolicyDecisionEvent` med propensity (dataset v5), shadow/authoritative-marker, kostnad/latens/outcome — ingen rå text.
  - Nya benchversioner: `benchmarks/bench_policy_a_v1.json`, `benchmarks/bench_policy_b_v1.json` (bredvid befintliga, orörda).
  - Kontrollarmar: nuvarande deterministiska router (som baseline i gymmet), always-balanced, Jev/LLM-väg utan SSR-gate, diagnostisk oracle (offline-gold only).
- **Grindar:** 5, 14, 15, 16, 17, 18; rapportera quality/kostnad/latens/abstention/deep-call-rate separat.

### Fas 4 — Tabular Review-extraktion och navigationsexperiment (endast om 1–3 klarar grindar)
- `backend/app/services/tabular_review/extraction.py` + `ExtractedValue`-schema; `POST /tabular-reviews/{id}/cells/{cid}/extract`; opt-in; locked cells förblir låsta; approve/reject skapar aldrig ankare. Navigation: rankade TextUnits via befintliga locators.
- **Grindar:** 11, 12, 13.

### Fas 5 — Produktionsbeslut
- Separat decision record (benchmark, CI, kostnad, risker, rollback). Ingen koppling i Fas 1–4.

---

## 8. Risker och öppna beslut

### Risker (spec §14 + inventeringsspecifika)

- **R1 Branch-topologi/wip-kollision:** merge origin/main → lokal branch riskerar konflikt med ocommittad live-speech-WIP i `config.py`, `database/models.py`, `schemas/domain.py`, `main.py`, frontend, samt untracked `research-ordering-v1`-filer (tracked på main). Åtgärd: integrationsbranch + noggrann merge; WIP committas av dess ägare, inte av Fas 0–3-arbetet.
- **R2 Gold-/templateläckage:** nära identiska avtal (samma mall) kan ge falskt hög dokumentklassificering → split på familj+org med Jaccard-grind (§5.1).
- **R3 Felaktiga negativa ankare:** `NO` måste förbli frågespecifikt hard negative (befintligt test täcker; nya subject-typer måste behålla samma isolering).
- **R4 Embeddingdrift:** model/revision/dimension ändring gör ankare/fingerprints stale; befintlig mark-stale-flöde + `EmbeddingSpec`-kontroll återanvänds; `clause-ssr-embedding-migration.md` (WIP) dokumenterar manuell migrationsprocedur.
- **R5 Centroidkollaps:** dokumentfingerprintet måste vara kategorinycklat (spec §5.1); centroid-armen är en diagnostisk baseline, aldrig klassificeraren.
- **R6 Cosinus som sannolikhet:** `score_kind`/`not_a_probability` måste följa med alla nya ytor (subject-match, fingerprint, klassificerare, UI).
- **R7 Relationers identitet:** råa kanter saknar stabil key; fact-subject ankras mot Fact-nodens identitet + rendering-version.
- **R8 Reward hacking:** policy kan abstaina för ofta eller välja för enkel modell → separat rapportering av quality/abstention/deep-call-rate; severe_penalty för unsupported output.
- **R9 Off-policy bias:** propensity-loggning krävs innan någon IPS/SNIPS-analys; presentera aldrig counterfactual kvalitet utan giltig metod.
- **R10 Icke-stationära modeller/priser:** versionera resolved model + tariffs i varje event.
- **R11 Sällsynta deep-fall:** rapportera per uppgiftstyp, inte bara totalmedel.
- **R12 Shadowkostnad:** gold/replay först, bounded live-shadow sist.
- **R13 Tenantläckage via loggar/cache:** scope i cache-identitet; rå text aldrig i policyevents.
- **R14 Stale provenance:** validera dokumentversion/content-hash/AnchorSet/extractor-version vid läsning.
- **R15 Owner-/concurrencyfel:** inga direkta katalogöppningar i backend när Owner konfigurerad; inga parallella writers.
- **R16 DB-anslutning under modellanrop:** befintlig regel + pool-probe-tester; nya match-/fingerprintvägar följer trefas-mönstret.
- **R17 Påhittad navigation:** saknad locator → begränsad navigation, aldrig konstruerade koordinater.
- **R18 Miljöbegränsning:** `swe_native` ej byggd; research-tester kräver `make swe-native` innan de kan köras lokalt.

### Öppna beslut

- **O1 (blockerande): Branch-bas för Fas 1–3.** Alternativ: (a) integrationsbranch som mergear origin/main in i `feat/swe-gym-poc` (behåller gym-v2 + tillför clause-SSR/Tabular/Owner; kräver konfliktlösning mot WIP — rekommenderas), (b) ny branch från origin/main + cherry-pick av gym-v2-commits, (c) arbeta direkt på origin/main-baserad branch och lämna gym-v2 på sin branch. Beslut från ägaren krävs innan Fas 1.
- **O2:** Ska den ocommittade live-speech-WIP:en committas/stashas av ägaren före integrationsmerge?
- **O3:** Dokumenttypgold — vilken mänsklig resurs verifierar klasserna? (krävs för Fas 2-grind 8/9).
- **O4:** Threshold-set-migration — ska `SsrMatchProfile` vara ett OverGraph-objekt eller SQL (applikationsmetadata, spec §4 tillåter SQL för "review-/experimentadministration")? Rekommendation: OverGraph bredvid AnchorSet, eftersom matchläget läser det via samma Owner-väg.
- **O5:** Policy A:s kontextfeatures kräver SSR-scores i gymmet — offline fixture (`ssr_score`-fält i benchversionen) räcker för Fas 3; live-koppling är Fas 5-beslut.

---

## 9. Uttrycklig bekräftelse: produktionen är inte påverkad

1. **Ingen produktionskod har ändrats.** Denna fas levererar endast dokument (denna rapport + protokollfilen) och tre inventeringsdokument under `.scratch/ssr-generalization/`.
2. Ingen fil i den ocommittade live-speech-WIP:en har rörts (verifierat: enbart nya filer skapades; `git status` visar samma modifierade filer som vid start).
3. Research-, Jev-, SWE-, expertchatt-, Tabular Review- och rapportbeteende på origin/main är oförändrat; lokal HEAD har inte rörts alls.
4. Inga trösklar, modellval, prompts eller data har ändrats. Inga experimentarmar är kopplade till produktionsbeslut.
5. Fas 1–3 kommer att implementeras som isolerade, versionerade experiment bredvid befintliga artefakter (swe-gym-benchversioner och backend-opt-in-ytor), med frysta grindar (§6) — en misslyckad grind innebär att förändringen stannar som experiment eller tas bort, aldrig att produktionen ändras.
