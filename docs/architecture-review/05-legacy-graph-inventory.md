# Inventering — kvarvarande SQL-kunskapsgraf (steg 1)

**Status:** underlag för avvecklings-PR:n. Ingen produktionskod ändras av detta dokument.
**Omfattning:** alla aktiva läsare och skrivare för `knowledge_claims`,
`knowledge_claim_text_units`, `knowledge_claim_answers`, `knowledge_entities`,
`knowledge_relationships`, `knowledge_observations` samt Graph v2-tabellerna
(`graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`,
`graph_fact_relations`, `graph_fact_question_dependencies`).

`text_units`/`shared_text_chunks` är redan avvecklade (se
[`191_drop_text_units`](../../backend/alembic/versions/191_drop_text_units.py) och
huvudrapportens §11.1) och ingår inte längre.

---

## 1. Sammanfattning

Den kvarvarande SQL-kunskapsgrafen är **inte** föräldralös: den har både aktiva skrivare
och aktiva läsare i research-, document-QA- och experttools-flödena. Avvecklingen är därför
en riktig migrering av research-skrivvägen — inte en städning av död kod.

Två separata system ska bort:

| System | Tabeller | Aktiv skrivare | Aktiva läsare |
|---|---|---|---|
| **Legacy claims** | `knowledge_claims`, `knowledge_claim_text_units`, `knowledge_claim_answers`, `knowledge_entities`, `knowledge_relationships`, `knowledge_observations` | `lagen_nu/graph_writeback.py` → `knowledge/persist.py::persist_extracted_knowledge` | `knowledge/audit.py`, `knowledge/claims.py`, `knowledge/claim_store.py`, `knowledge/entities.py`, `knowledge/observations.py`, `knowledge/relationships.py`, `knowledge/claim_rekey.py`, `knowledge/persistence.py`, `kund_dokument.py` (purge) |
| **Graph v2-mirror** | `graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations`, `graph_fact_question_dependencies` | `graph_v2/outbox.py` → `graph_v2/legal_writeback.py`; `research/answer_graph.py`; `graph_v2/questions.py`; `kund_dokument.py` (purge) | `graph_v2/retrieval.py`, `graph_v2/dependencies.py`, `research/answer_graph.py`, `research/result_search.py`, `research/result_store.py`, `execution/reuse_views.py` |

OverGraph-sidan finns redan till stor del: `overgraph/research.py`
(`persist_research_fact`, `update_fact`, `load_fact`, `search_research_facts`,
`neighbourhood_facts`, `question_facts`, `find_question`, `attach_question_dependency`,
`question_frontier`, `collect_research_hits`, `add_text_unit_ref`, `set_text_unit_refs`,
`load_text_units`, `supporting_units`) och `overgraph/claims.py` (Claim-noder med
`SUPPORTS`-kanter, `VerificationObservation`, `find_claims`). Avvecklingen handlar alltså
om att **peka om läsare/skrivare** till det API:et och sedan droppa spegeln.

---

## 2. Skrivvägar (måste bort i steg 3)

| # | Entry point | Skriver | Anropas från |
|---|---|---|---|
| W1 | `knowledge/persist.py::persist_extracted_knowledge` → `claim_store.persist_domain_claim` + `observations.py` | `knowledge_claims`, `knowledge_claim_text_units`, `knowledge_claim_answers`, `knowledge_observations` | `lagen_nu/graph_writeback.py:112` (enda produktionsanropet) |
| W2 | `knowledge/entities.py::persist_entity` | `knowledge_entities` | `persist_extracted_knowledge` |
| W3 | `knowledge/relationships.py::persist_relationship` | `knowledge_relationships` | `persist_extracted_knowledge` |
| W4 | `graph_v2/write.py::resolve_node` / `resolve_fact` / `resolve_exact_fact` | `graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations` | `graph_v2/legal_writeback.py` (outbox-worker), `research/answer_graph.py:69,84`, `graph_v2/questions.py:17,34` |
| W5 | `graph_v2/dependencies.py::attach_question_dependency` | `graph_fact_question_dependencies` | `graph_v2/legal_writeback.py` |
| W6 | `kund_dokument.py::_delete_graph_v2` / `_delete_claims` | raderar samtliga ovan | `purge_kund_documents` |

OverGraph-motsvarighet: W1–W3 → `overgraph/claims.py` (`upsert_claim`,
`upsert_verification_observation`) + `overgraph/write.py` (`upsert_entity`) +
`overgraph/write.py` (`upsert_edge` med `SUPPORTS`/`CONTRADICTS`); W4–W5 →
`overgraph/research.py` (`persist_research_fact`, `update_fact`,
`attach_question_dependency` + `overgraph/publish.py::publish_legal_fact`).

> **Kontrollpunkt:** `research/answer_graph.py` skriver *både* Graph v2 (SQL) och, via
> `overgraph/publish.py::publish_answer_fact`, OverGraph. Efter ompekningen får endast
> OverGraph-skrivningen vara kvar — annars fortsätter research att skapa SQL-fakta.
>
> **Verifierat (steg 2-förutsättning):** `publish_answer_fact` täcker hela skrivningen —
> frågenod, svarsnod, `research.answered_by`-fakt och `DEPENDS_ON`-beroenden — så läsarna kan
> flyttas innan SQL-skrivningen kapas. Regression:
> `tests/research_reuse/test_06_overgraph_parity.py` pinnar att varje publicerad svarsfakt
> finns i OverGraph med rätt predikat/scope/status och att frågenoden finns med
> `canonical_question_id`.

---

## 3. Läsare (flyttas i steg 2)

### 3.1 Legacy claims

| Fil | Läser | OverGraph-ersättning |
|---|---|---|
| `knowledge/audit.py` | claims, entities, relationships, observations (räkningar) | `overgraph/claims.py::find_claims*`, `count_nodes_by_labels`, edge-räkning |
| `knowledge/claims.py::claim_answers_for_question_key` | `knowledge_claim_answers` | `research.answer`-episoder (`question_facts`) |
| `knowledge/claim_store.py::claim_support_ids` | claims + `knowledge_claim_text_units` | `overgraph/claims.py::supporting_text_unit_ids` |
| `knowledge/entities.py::find_entity` | `knowledge_entities` | `overgraph/research.py::find_entity`-motsvarighet |
| `knowledge/observations.py::observations_for_question` | `knowledge_observations` | `overgraph/claims.py::find_observations` |
| `knowledge/relationships.py::load_relationships` | `knowledge_relationships` | `overgraph/research.py` (kanter) |
| `knowledge/persistence.py::delete_canonical_document` (claim-länkar) | `knowledge_claim_text_units` | OverGraph `SUPPORTS`-kanter (raderas med TextUnit-noden) |
| `kund_dokument.py` (räkning + purge) | alla sex | OverGraph-rakning/purge per scope-label |

### 3.2 Graph v2-mirror

| Fil | Läser | OverGraph-ersättning |
|---|---|---|
| `graph_v2/retrieval.py` | facts (hybrid/lookup) | `overgraph/research.py::search_research_facts` + `overgraph/retrieval.py::hybrid_search` |
| `graph_v2/dependencies.py` | facts, nodes, dependencies | `question_facts`, `neighbourhood_facts`, `question_frontier` |
| `research/answer_graph.py` | facts, sources, nodes | `load_fact`, `supporting_units`, `find_question` |
| `research/result_search.py` | facts, nodes, dependencies | `collect_research_hits` |
| `research/result_store.py` | facts, nodes, identifiers | `load_fact`, `find_question`, `question_frontier` |
| `execution/reuse_views.py` | facts, nodes | `search_research_facts`/`lookup_candidates` |

---

## 4. Testfiler som berörs (steg 4)

18 filer: `test_graph_v2.py`, `test_graph_v2_shared_retrieval.py`,
`test_graph_v2_embedding_cache.py`, `test_knowledge_claims.py`,
`test_knowledge_persistence_gate.py`, `test_knowledge_persistence_codex_regressions.py`,
`test_knowledge_tenant_boundary.py`, `test_kund_dokument.py`,
`test_lagen_nu_claim_grounding.py`, `test_lagen_nu_graph_writeback.py`,
`test_research_graph_v2_reuse.py`, `test_research_question_evidence.py`,
`test_workspace_general_knowledge.py` samt `research_reuse/`-kontrakten
(`probes.py`, `test_01_main_lookup.py`, `test_04_main_answer.py`,
`test_completed_result.py`, `test_result_navigation.py`).

---

## 5. Gap-analys (måste lösas i steg 2/3)

| Gap | Detalj | Åtgärd |
|---|---|---|
| **Supersession/temporalitet** | Legacy claims använder `superseded_at`; Graph v2-fakta använder `status` + `valid_at`/`invalid_at`. OverGraph `Claim` saknar `superseded_at`; kanter har `valid_from`/`valid_to`. | Modellera supersession som stängd giltighet (`valid_to`) i stället för kolumn; verifiera i tenant-/temporalitetstester. |
| **`CONTRADICTS`** | Finns som etikett i `overgraph/labels.py` och hanteras i `overgraph/ingest.py`, men legacy-`relationships.py` skriver `CONTRADICTS` som SQL-rad. | Säkerställ att ompekningen bevarar `CONTRADICTS`-kanter och att `test_knowledge_claims`/`test_research_question_evidence` verifierar dem. |
| **`ANSWERED_BY`** | `knowledge_claim_answers` (fråga → svar) motsvaras av Graph v2 `research.answer` + `research.answered_by`. | Migrera `claim_answers_for_question_key` till `overgraph/research.py::question_facts` innan tabellen droppas. |
| **Identifier-noder** | `graph_identifiers` (namespaced identiteter) motsvaras av OverGraph `Identifier`-noder via `overgraph/write.py`. | Verifiera att `result_store.py`-behovet (identitetsuppslag) täcks av `research.py`-API:t. |
| **Proveniens** | `graph_fact_sources` motsvaras av `source_refs_json` på Fact-noden (`fact_view.text_unit_refs`). | Verifiera att alla `source_kind`-varianter (`text_unit`, `episode`) bevaras. |
| **Bakgrundsjobb** | `graph_v2/outbox.py`-workern är enda bakgrundsvägen som skriver Graph v2. | Efter ompekning ska workern endast anropa `overgraph/publish.py`; lägg en regression som failar om `resolve_fact` anropas från worker-kedjan. |

---

## 6. Ordning för avvecklings-PR:n

1. **Läsare först** (steg 2): peka om `graph_v2/retrieval.py`, `graph_v2/dependencies.py`,
   `research/answer_graph.py` (läsdelen), `research/result_search.py`,
   `research/result_store.py`, `execution/reuse_views.py` samt legacy-claim-läsarna till
   `overgraph/research.py`/`overgraph/claims.py`. Kör research-reuse + juridiska
   evidensfrågor + tenantisolering efter varje grupp.
2. **Skrivare sedan** (steg 3): ta bort `resolve_node`/`resolve_fact`-anropen i
   `legal_writeback.py` och `answer_graph.py` (behåll endast `overgraph/publish.py`),
   flytta `persist_extracted_knowledge` till OverGraph-claims. Kontrollera
   `SUPPORTED_BY`, `CONTRADICTS`, observationer och claim-identiteter.
3. **Purge/räkning**: `kund_dokument.py` mot OverGraph (scope-label per kund).
4. **Modeller + Alembic** (steg 4): droppa de tolv tabellerna i FK-ordning med reversibel
   `downgrade`. Behåll dokumentmetadata (`canonical_documents`, `document_versions`,
   `document_sections`, `stored_objects`), orkestrering (`graph_ingest_work`,
   `graph_embedding_cache`), `knowledge_answer_reviews`, `knowledge_graph_events`,
   `document_knowledge_items*`.
5. **Regression** (steg 5): research-reuse, juridiska evidensfrågor, document-QA,
   tenantisolering, Tantivy-synkronisering (`reconcile`) + återställningstestet (§6.1).

---

## 6b. Genomförande — status per slicearbetspaket

| # | Paket | Status |
|---|---|---|
| 1 | Svarsläsning (`research/answer_graph.py::lookup_answers`) | **KLART** — läser OverGraph |
| 2 | Resultatnavigering (`result_store.py`, `result_search.py`) | **KLART** — läser OverGraph |
| 3 | Retrieval/beroenden | **KLART** — hela kedjan OverGraph/Tantivy utan SQL-läsning |
| 4 | Legacy claims (läsarna) | **KLART så när som på returtypkopplade läsare** (se 6d) |
| 5 | Skrivvägarna | återstår |
| 6 | Modellgap + tabelldropp | återstår |

### Paket 1 — svarsläsning (klart)

`lookup_answers` läser nu enbart OverGraph; SQL-skrivningen är kvar under övergången.

- **Stabil ingång:** `canonical_question_id` → `research.question_id`-alias (IDENTIFIER) →
  frågenod. Ingen vektorsökning krävs för ett känt svar.
- **Grafrelation:** svarsfakta hittas via frågenodens inkommande `SUBJECT`-kanter
  (`overgraph/research.py::answer_facts`), filtrerade på `predicate = research.answered_by`
  och `status = active`, sorterade nyast först.
- **Basis:** läses från svarsnodens `attributes_json` via indexerat uppslag på `target_key`
  (`entity_attributes`); ingen ny frågemotor.
- **Temporalitet:** `overgraph/research.py::current_fact` (status + giltighetsfönster) för
  fakta som basis refererar; `DocumentVersionRecord` ligger kvar i SQL enligt D3.
- **Ordning:** fakta skriver nu `created_at_ms` (`overgraph/write.py::write_fact`) så att
  "nyast först" matchar SQL:s `created_at DESC`; `engine_id` är tiebreaker.
- **Taket (200) är säkert:** `answer_facts` filtrerar status **och** giltighetsfönster
  (`now=`) innan `limit` tillämpas, så historiska/utgångna svar kan aldrig tränga undan ett
  aktuellt. Regression: `test_limit_applies_after_filtering_so_history_cannot_hide_a_current_answer`
  (205 utgångna svar + 1 aktuellt, tak 5 → endast det aktuella returneras).

**Semantik som bevarats:** scope/tenantisolering (svarsnodens scope måste matcha faktans,
annars `GraphResearchError`), freshness (befintlig `_current_basis`-logik oförändrad),
`manifest_matches`/modul/case-filter, dedupe på `evidence_ref` och `need.source_types`-filter.

**Tester:** `tests/test_overgraph_answer_selection.py` (7 st) — flera svar per fråga
(nyast först), supersedade svar, svar utanför giltighetsfönster, annan tenant osynlig,
delat svar synligt för alla, okänt fråge-id utan vektorsökning. Plus hela
`research_reuse`-sviten + `test_research_question_evidence.py` +
`test_research_graph_v2_reuse.py` + `test_knowledge_tenant_boundary.py`: **283 passed**.

**Prestanda** (`scripts/benchmark_answer_lookup.py`, p50 per uppslag):

| Svar per fråga | OverGraph | SQL-join (legacy) |
|---|---|---|
| 1 | **0,024 ms** | 0,142 ms |
| 5 | **0,070 ms** | 0,150 ms |
| 10 | **0,125 ms** | 0,161 ms |
| 50 (stress) | 0,630 ms | **0,247 ms** |

OverGraph är snabbare i det realistiska fallet (1–10 svar per kanonisk fråga, ingen
SQL-rundtur) och långsammare först vid ~50 svar på samma fråga. `answer_facts` har ett
hårt `limit` (200) så en patologisk fråga inte kan ge obegränsad traversering.

### Paket 2 — resultatnavigering (klart)

`result_store.py` läser nu OverGraph; `result_search.py` använder samma primitiv.
`_nearby`-vägen (hybrid retrieval + beroenden) ligger kvar i SQL till paket 3.

- **Identitet:** `exact_answers` slår upp `KnowledgeQuestionRow` på `identity_key`
  (SQL, dokumentmetadata) och går sedan via `answer_facts` med `exact_scope=customer:N`
  — samma resultat nås via frågeidentitet och via faktans id (`load_saved_answer`).
- **Temporalitet:** `answer_facts(now=...)` filtrerar status **och** giltighetsfönster
  innan `limit` tillämpas, så historiska svar kan inte tränga undan ett aktuellt.
- **Scope:** `exact_scope` begränsar till kundens egna svar; svarsnodens scope måste
  matcha faktans, annars `GraphResearchError`. Delade svar nås via `answer_facts`
  utan `exact_scope`.
- **Evidens/proveniens:** `EntityView` (scope, node_type, **name**, attributes) bär
  `basis`, `assessment` och `evidence_set_id`; `EvidenceSet`/`ExecutionAttempt`/
  `ExecutionRun` ligger kvar i SQL (orkestrering) och knyts via `evidence_set_id`.
- **Ordning:** `(created_at_ms, engine_id)` fallande; `exact_answers` har taket 8
  (samma som tidigare) och returnerar unika id. `exact_scope` filtreras före taket.
- **Modul:** de nya läs-primitiven bor i `app/services/overgraph/answers.py`
  (`answer_facts`, `entity_attributes`/`EntityView`, `current_fact`, `find_question`),
  så `research.py` håller sig under maintainability-gränsen.

**Tester:** `tests/research_reuse/test_07_saved_result_selection.py` (7 st) — nås via
frågeidentitet och fakt-id, basis bevarad, invaliderat svar osynligt i båda vägarna,
ännu inte giltigt svar osynligt, annan kund når inte resultatet, unika id i fallande
ordning, taket 8. Plus `research_reuse`-sviten: **284 passed**.

**Prestanda** (`scripts/benchmark_answer_lookup.py`, p50, `exact_answers`-uppslaget):

| Svar per fråga | OverGraph | SQL 3-tabellsjoin (legacy) |
|---|---|---|
| 1 | **0,017 ms** | 0,201 ms |
| 5 | **0,046 ms** | 0,203 ms |
| 10 | **0,078 ms** | 0,259 ms |

### Paket 3 — retrieval och beroenden (delvis klart)

**Klart: `execution/reuse_views.py::reuse_payloads`.** Projektionen av återanvända resultat
läser nu svarsfaktan och svarsnoden från OverGraph (`fact_view` + `entity_attributes`) i
stället för SQL-joinen `GraphFact ⨝ GraphNode`. Ordinarie `ExecutionRun`-slagning ligger
kvar i SQL (orkestrering, enligt D3). Semantik som pinnas:

- **Identitet:** `reuse_payloads` hittar svaret via `answer_fact_id` i
  `attempt.input_snapshot[REUSE_KEY]`.
- **Scope:** svarsnodens scope måste matcha såväl faktans som `customer:{id}` från run:en,
  annars `RuntimeError`; en faktor från annan tenant avvisas.
- **Evidens:** payloaden är svarsnodens `basis`/`assessment`/`evidence_set_id`.
- **Fryst set:** `evidence_set_id` måste matcha attemptens — annars `RuntimeError`.
- **Saknat svar:** `RuntimeError` (tidigare `KeyError`).

Tester: `tests/research_reuse/test_08_reuse_payloads.py` (4 st).

**Beroendesemantik vid flera evidenskällor (pinnad, inte ändrad).** Ett svar vars basis
refererar flera graffakta förblir läsbart så länge alla refererade fakta är aktuella;
blir **en** refererad fakt ogiltig avvisas hela svaret (`_current_basis`). Det är den
befintliga regeln — den har inte ersatts av en förenklad "tappa ett stöd = fortfarande
ok"-regel. Regression:
`test_multiple_evidence_sources_lose_the_answer_only_when_a_referenced_fact_breaks`.

**Beslut: alternativ 1 — Tantivy indexerar även `Fact`.** Lexikal sökning ägs av Tantivy
(BM25 + svensk analys), OverGraph äger fakta/dense/traversering. Dense-only avvisades
eftersom det tar bort en fungerande sökförmåga.

**Klart: Tantivy-indexet omfattar nu `Fact`.**

- Schemat har utökats med `kind`, `status`, `valid_from_ms`, `valid_to_ms`
  (`INDEX_VERSION = graph-index-v2`). TextUnit-dokument fyller `kind=text_unit`.
- `FactDoc` indexeras med **stabilt fakt-ID**, **scope** (`tenant_id`),
  **`normalized_text`** (BM25 med svensk analys), **innehållshash**
  (`sha256(normalized_text)`) och **giltighetsfönster**.
- Samma mekanism som för TextUnits återanvänds: `build_from_overgraph` (atomisk
  `_atomic_swap`, indexerar båda nodtyperna), `upsert_facts` (delete-then-add =
  idempotent), `reconcile` + `pending_updates` (watermark-fönstret täcker nu både
  `TEXT_UNIT` och `FACT`, så ett misslyckat reconcile lämnar kvar gamla watermarken och
  nästa körning skannar om samma fönster).
- `TextUnitIndex.search_fact_keys(query, tenant_ids, limit)` ger BM25-rankade
  faktakandidater med scope-filter i indexet; hydrering och giltighetskontroll sker
  därefter i OverGraph. Indexet kan alltid byggas om från grafen.

Tester: `tests/test_tantivy_facts.py` (5 st — lexikal träff, tenantisolering,
hydrering till auktoritativ faktas giltighetsfönster, reconcile av nya fakta,
ombuild från grafen) + befintliga `tests/test_tantivy_index.py` (11 st) gröna.

**Klart: fusion + hydrering + eftersläpningsvakt** (`overgraph/hybrid_retrieval.py`).

- `hybrid_fact_hits` fuserar Tantivy-BM25-kandidater med OverGraph-dense via RRF
  (`RRF_K = 50`, budget `max(100, limit*5)`, dedupe på fakt-id, sortering på
  `(-score, fact_id)` för determinism).
- **All giltighet kontrolleras i OverGraph** efter hydrering: aktuell `status`,
  giltighetsfönster, tenant (`visible_scope_keys`). Tantivys `status`/`valid_*` är bara
  indexerade ögonblicksbilder.
- **Ogiltiga träffar konsumerar ingen budget:** indexet pagineras (`FACT_INDEX_PAGE`) tills
  budgeten är fylld eller kandidatströmmen tar slut — ingen dold recallförlust.
- **Eftersläpningsvakt:** `ensure_fact_index_current` jämför grafens ändringar mot
  indexets watermark och kastar `FactIndexStaleError` i stället för att tyst köra en
  ofullständig lexikal sökning (ingen tyst fallback till dense-only).

Tester: `tests/test_hybrid_fact_retrieval.py` (8 st) — lexikalt-only-faktum hittas utan
dense, giltighet/status avgörs i OverGraph (indexet är kvar med inaktuell träff),
ogiltiga träffar tar inte budget (paging), annan tenant osynlig, eftersläpning vägras tills
reconcile + watermark är persisterad, fusion utan dubbletter, samt **frysta frågor** mot
SQL-`hybrid_facts`.

**Sammansatta ord — löst med kompletterande delordsfält** (`tantivy_subwords.py`).

BM25 med svensk analys tokeniserar `avtalsvillkor` som **ett** token, så frågan
"oskäliga villkor" tappade substrängträffen som SQL:s `ILIKE`/`tsvector` gav. Det är
åtgärdat utan avsammansningslexikon och utan hårdkodade undantag:

- Varje token med minst `MIN_COMPOUND = 8` tecken delas på **varje** position där båda
  halvorna är minst `MIN_PART = 3` tecken; delarna indexeras i ett **separat fält**
  (`subwords`) med en egen analyskedja (simple + lowercase, **ingen stemming**).
  Ex: `avtalsvillkor` → `avtal|s`/`villkor`, `uppsägningstid` → `uppsägning`/`tid`,
  `sekretessförpliktelse` → `sekretess`/`förpliktelse`.
- **Delord väger lättare:** huvudsignalerna är BM25-träffarna; delordsträffar läggs
  *efter* dem i kandidatlistan, så RRF ger dem automatiskt lägre vikt. Ingen boost behövs.
- **Korta strängar matchar inte fritt:** frågetermer under `MIN_QUERY_PART = 4` söks aldrig
  i delordsfältet (`tid` indexeras men kan inte ensamt trigga en sökning).
- Dubbletter dedupas på fakt-id, så en träff som både BM25 och delord hittar räknas en gång
  med huvudrankningen.

**Frysta frågor: ingen lexikal recallförlust.** Sviterna i
`tests/test_hybrid_fact_retrieval.py` jämför mot SQL-`hybrid_facts` och kräver nu att varje
legacy-träff finns kvar (`lost == set()`), att det frysta fallet
`oskäliga villkor` → `avtalsvillkor får jämkas` återfinns, att delordningen är generisk
(`sekretessförpliktelse`/`förpliktelse`) och att en direkt BM25-träff rankas före en
delords-träff.

**Klart: `neighbourhood` → OverGraph** (`overgraph/neighbourhood.py`).

- **Traversering:** fakta är kanter (`fact --SUBJECT--> source`, `fact --OBJECT--> target`);
  ett hopp = frontens inkommande `SUBJECT`/`OBJECT`-fakta via `catalog.neighbors`. Antal hopp
  och `1/hop`-poäng är oförändrade.
- **Giltighet i varje steg:** status, giltighetsfönster och tenant kontrolleras per faktum i
  katalogen. Ett ogiltigt mellanled bidrar **aldrig** med sina endpoints till nästa front,
  så det kan inte öppna vägen vidare.
- **Cykler/flera vägar:** `visited` på faktum-id → varje faktum en gång, och eftersom BFS
  går hoppvis vinner alltid den kortaste giltiga vägen. Fronten och grannarna itereras i
  sorterad ordning → deterministiskt resultat.
- **Budget:** ogiltiga träffar filtreras före `limit`, så historiska fakta tränger inte undan
  aktuella.

Tester: `tests/test_overgraph_neighbourhood.py` (8 st) — hopp/`1/hop`, ogiltigt (utgånget och
supersedat) mellanled bryter vägen, cykel + flera vägar ger ett kortaste-hopp-faktum,
determinism, budget efter filtrering, annan tenant osynlig, samt **fryst struktur jämförd
mot SQL-`neighbourhood`** (samma faktum-id och samma hopp).

**Precision för delordsfältet (mätt).** Frysta sviten mäter nu hur många träffar som
tillkommer utöver SQL-vägen (`current - legacy`) och kräver att summan är bunden
(≤ en per fråga), plus att en direkt sammansättningsträff alltid rankas före en
delords-träff. Lösningen behålls tills vidare enligt beslut, med kostnaden synlig.

**Latens, hela retrievalkedjan** (`scripts/benchmark_retrieval_chain.py`, 200 fakta, p50):

| Steg | p50 | p95 |
|---|---|---|
| Tantivy lexikal (50 kandidater) | 0,21 ms | 0,33 ms |
| OverGraph dense (k=20) | 0,03 ms | 0,04 ms |
| Hybrid fusion + hydrering (limit 20) | 2,86 ms | 3,69 ms |
| `neighbourhood` 2 hopp (40 seeds) | 1,16 ms | 1,48 ms |

Fusionen domineras av hydreringen: upp till `max(100, limit*5)` lexikala kandidater
verifieras mot grafen (det är priset för att ogiltiga träffar inte ska konsumera budget).
Dense-sidan återanvänder träffarnas egna vyer och gör därför ingen extra uppslagning.

**Klart: inkopplad i researchvägen.** `result_search._seeds` använder nu
`hybrid_fact_hits` + OverGraph för endpoints, `DEPENDS_ON`-beroenden och frågefilter.
Ingen produktionsläsare anropar längre SQL-`hybrid_facts` eller SQL-`neighbourhood`
(verifierat med grep: noll träffar).

**Indexets livscykel i produktion** (`app/services/retrieval_index.py`):
`require_current_index()` kastar `RetrievalIndexUnavailableError` när indexet saknas och
`FactIndexStaleError` när det ligger efter grafen — research faller aldrig tyst tillbaka på
dense-only. Återhämtning är ombyggnad/reconcile mot grafen.

**Mätt, integrerad väg** (`scripts/benchmark_retrieval_chain.py`, 200 fakta, p50):

| Steg | p50 | p95 |
|---|---|---|
| Tantivy lexikal | 0,21 ms | 0,28 ms |
| OverGraph dense | 0,03 ms | 0,05 ms |
| Hybrid fusion + hydrering | 2,83 ms | 3,36 ms |
| **`research._seeds` (integrerad)** | **2,93 ms** | **3,55 ms** |
| `neighbourhood` 2 hopp | 1,10 ms | 1,48 ms |

**Regression:** research-reuse-kontrakten 235 gröna + 81 i den berörda sviten.

**Delordsfältet:** "högst en extra träff per fråga" är en *testobservationsregel* för den
frysta sviten, inte en produktionsgräns — på större korpusar kan fler relevanta
extraträffar vara önskvärda. Produktionsregeln är att delordsträffar alltid rankas under
direkta BM25-träffar.

**Tidigare blockerare (nu löst genom beslut 1):**
`graph_v2/retrieval.py::hybrid_facts` genererar kandidater lexikalt (Postgres `tsvector` /
SQLite `ILIKE` på `normalized_text`) och densen via vektor. OverGraph erbjuder
`scoped_type_search` (dense/hybrid sparse) och **exakta** property-uppslag — men ingen
substräng-/BM25-sökning på nodtext. Enligt beslutad arkitektur ägs lexikal sökning av
**Tantivy**, som idag indexerar TextUnits men inte `Fact`-noder. Två vägar:

1. **Tantivy indexerar även `Fact`** (lexikal kandidatgenerering + OverGraph för hydrering),
   vilket följer målarkitekturen och gör `hybrid_facts` helt SQL-fri.
## 6c. Paket 4 — klassificering av kvarvarande läsare

Först en klassificering: allt som ligger i PostgreSQL är inte en SQL-spegel av
kunskapsgrafen. Bara kunskapsgrafen ska till OverGraph.

| Läsare/skrivare | Klass | Mål |
|---|---|---|
| `knowledge/claim_store.py` | **Kunskapsgraf** | `overgraph/claims.py`: `Claim`-noder, `claim_key`-identitet, `SUPPORTS`-kanter |
| `knowledge/claims.py` | **Kunskapsgraf** | `upsert_claim`, `find_claims`, `find_claims_by_class`, `supporting_text_unit_ids` |
| `knowledge/entities.py` | **Kunskapsgraf** | `overgraph/write.upsert_entity` |
| `knowledge/relationships.py` | **Kunskapsgraf** | grafkanter `SUPPORTS`/`CONTRADICTS` via `upsert_edge` |
| `knowledge/observations.py` | **Kunskapsgraf** (D2) | `VerificationObservation` via `upsert_verification_observation` / `find_observations` |
| `knowledge/persistence.py::delete_canonical_document` (claim-länkar) | **Kunskapsgraf** | radera `SUPPORTS`-kanter/noder via OverGraph |
| `kund_dokument.py` (claims/entities/relationships/observations + graph_v2) | **Kunskapsgraf** (räkning/purge) | OverGraph nod- **och** kantradering per scope |
| `knowledge/audit.py` | **Blandad** | grafdelen (claims/entities/relationships/observations) → OverGraph; `knowledge_graph_events` **stannar i SQL** som append-only applikationsaudit |
| `knowledge/claim_rekey.py` | **Migreringshjälp** (Alembic-engångs) | stannar tills tabellerna droppas, ingen runtime-läsare |
| `database/knowledge_bind.py`, `database/knowledge_observation.py`, claim-/entity-/relationship-modellerna | **Schemabärare** | droppas i paket 6 |

**Stannar permanent i PostgreSQL (applikationsdata, inte kunskapsgraf):**
`canonical_documents`, `document_versions`, `document_sections`, `stored_objects`
(dokumentmetadata/ägarskap), `graph_ingest_work`, `graph_embedding_cache`, `execution_*`,
`evidence_sets` (orkestrering), `knowledge_answer_reviews` (TTL-bokföring) samt
`knowledge_graph_events` (append-only revisionslogg).

### Claim-identiteten: två begrepp som inte får blandas

Kontrollerat i koden: den `Claim`-nod som dokumentegenskaperna använder har
**versionsscopad** identitet (`claim_value` innehåller `document_id` + `document_version_id`,
medvetet enligt spec §5.3: en ny dokumentversion får inte ärva tidigare verifierade
egenskaper). Den får därför **inte** användas för logiska juridiska claims — då skulle hela
claimets livscykel bindas till en enskild dokumentversion, precis den risk som flaggades.

Paket 4 använder därför två nodtyper:

| Nod | Etikett | Identitet | Innehåll |
|---|---|---|---|
| **Logiskt claim** | `Claim` | `scope + predicate + canonical_json(value)` — **ingen** dokument-/versionsuppgift | `scope_key`, `predicate`, `value_json`, `status` |
| **Evidens per dokumentversion** | `ClaimEvidence` | `(claim_key, document_version_id)` | `document_version_id`, TextUnit-referenser, `status`, aggregatets giltighet |
| **Dokumentegenskap** | `DocumentProperty` | `scope + class_id + doc/version + polarity + taxonomi` (§5.3) | oförändrad sedan tidigare |

**Etikettseparation (krav):** dokumentegenskaperna använder nu `DocumentProperty`, inte
`Claim`. Två olika identitetsregler under samma nodtyp är inte acceptabelt; regressionen
`test_logical_claims_and_document_properties_do_not_share_a_label` pinnar att ett logiskt
claim bär `Claim` och aldrig `DocumentProperty`.

**Speglingen verifierar ingenting.** Att ett claim accepterats av kunskapspipelinen är
**inte** en Jev-verifiering. `graph_claim_mirror` skriver därför stödjekanter **utan**
verdict (`decision` tom, ingen `verification_version`): claimet finns i grafen som
inventerbar kandidat och `claim_is_verified` är **false** tills en faktisk verifiering
registrerar `SUPPORTED` med källa och verifieringsversion. Regressioner:
`test_an_accepted_claim_without_verified_evidence_exists_but_is_not_verified` (negativt
paritetsfall) och `test_an_explicit_verification_verifies_the_mirrored_claim`.

**Paritet via den verkliga skrivvägen.** Eftersom SQL-skrivningen är kvar speglas varje
accepterad claim från `knowledge/persist.py::persist_extracted_claim` även till OverGraph
(`knowledge/graph_claim_mirror.py`). Paritetstesterna i
`tests/test_legal_claim_parity.py` driver den riktiga vägen
(`persist_extracted_knowledge`) och kräver att:

- SQL-raden finns kvar **och** att OverGraph-claimets nyckel är **samma** som
  `KnowledgeClaimRecord.identity_key` (båda använder `knowledge_claim_identity`),
- ett dokumentversion-stöd ger en evidenslänk **utan** att claimet därmed blir verifierat,
- två dokument som stöder samma påstående ger **en** SQL-rad och **en** OverGraph-nod med
  två evidenslänkar — aldrig dubblering.

**Claim-läsaren har paritet med SQL.** `legal_claims.claim_in_graph(scope_key, identity)`
slår upp claimet på den logiska nyckeln och avvisar fel scope. Regression:
`test_graph_reader_matches_the_sql_claim_lookup` (samma `identity_key`, samma predikat,
samma scope; annan kund får `None`).

**Entities: speglade, med enkel skrivning.** `overgraph/write.upsert_entity_at_key` skriver
numret direkt på den externa nyckeln (ingen upsert-sedan-omväg), så ingen dubblettnod
uppstår. `knowledge/graph_entity_mirror.py` speglar varje entity från den verkliga
skrivvägen (`persist_knowledge_entity_result`) under **samma id som SQL-raden**.

Eftersom OverGraph kräver namespaceda nodtyper medan äldre adaptrar kan använda bara namn
(`person`), mappas sådana deterministiskt till `knowledge.entity.<typ>`; redan namespaceda
typer (`legal.source`, `legal.court`) behålls oförändrade. Regressioner:
`test_entity_mirror_keeps_the_sql_identity_and_namespaced_type`,
`test_bare_entity_types_get_a_deterministic_namespaced_label`.

Två tidigare försök backades innan de nådde main: upsert-then-rekey lämnade en dubblettnod
(bröt fem tenantisoleringstester) och ett direkt skrivförsök avvisade icke-namespaceda
typer. Båda orsakerna är nu åtgärdade i grunden.

**Observationer speglas som inventarium, aldrig som verdict.** Research-observationer
(`source_quality`, `research_observation`, t.ex. "ingen passage stöder påståendet") speglas
till `VerificationObservation`-noder med `polarity="observed"` och **tomt `decision`**. De
kan därför aldrig verifiera ett claim och aldrig skapa en `CONTRADICTS`-kant — de är
inventarium. Regression:
`test_research_observations_are_inventory_never_verification` (inga nya claim-noder, ingen
ny motsägelsekant, observationen finns i grafen utan verdict).

**Tenantisolerad dokumentradering.** `legal_claims.unlink_document_versions` tar bort
evidenslänkarna för ett dokuments versioner via indexerat uppslag på `document_version_id`
och raderar noden (incidenta kanter kaskaderas). Claimet och andra dokumentversioners stöd
ligger kvar. Inkopplad i `knowledge/persistence.delete_canonical_document`, som nu även
härleder dokumentets versioner och städar grafen.

Regressioner:
- `test_deleting_one_document_removes_only_its_evidence_and_keeps_the_claim` (3 dokument →
  radera 1 → claimet + 2 stöd kvar, fortfarande verifierat),
- `test_deleting_evidence_from_another_tenant_leaves_local_evidence_alone` (purge rör
  aldrig annan tenants stöd),
- `test_document_deletion_keeps_support_from_other_documents` (via den **verkliga**
  raderingsvägen: två dokument → radera `doc-a` → bara `ver-b` kvar).

**Audit — läshalvan migrerad.** `knowledge/graph_audit.py::graph_audit_counts` räknar claims,
entities, observationer, evidenslänkar samt `SUPPORTS`/`CONTRADICTS`-kanter från grafen.
Regression `test_graph_audit_counts_match_the_sql_audit` kräver paritet med SQL-spegeln.
Dubblettstädningen i `audit.py` lämnas till paket 5, eftersom den skriver grafen.

**Relationer speglas som kanter.** `knowledge/graph_relationship_mirror.py` skriver varje
validerad relation från `persist_extracted_knowledge` som en OverGraph-kant:
`SUPPORTED_BY` → `SUPPORTS`, `CONTRADICTS` → `CONTRADICTS`, övriga → `LINKED` med
relationsnamnet som prop. Endpoints löses mot de speglade claim-/entity-noderna; kanter mot
TextUnits eller dokument behåller sin SQL-rad tills paket 5.

Två regressioner pinnar betydelsen: `test_relationships_become_graph_edges_without_inventing_contradictions`
(exakt **en** `CONTRADICTS`-kant när det finns en faktisk motsägelse) och
`test_unsupported_evidence_creates_no_contradiction_edge` (accepterad men overifierad
evidens skapar **noll** motsägelsekanter). Därmed är `CONTRADICTS` fortfarande reserverat
för faktisk motsägelse mellan påståenden — aldrig för uteblivet stöd.

**Verifieringsmetadata på varje stöd.** `SUPPORTED` är Jev:s bedömning, inte en
sanningsgaranti. Varje `SUPPORTED_BY`-kant bär därför även `verification_version`,
`source_ref` och proveniens. Regression:
`test_support_edge_keeps_verification_version_and_source_ref`.

**Verifierad evidens, inte bara giltig i tid:** varje `SUPPORTED_BY`-kant bär Jev:s
`decision`. `claim_is_verified` kräver **både** att kantens giltighetsfönster är öppet
**och** att `decision == SUPPORTED`. En kandidat som bara hittats lexikalt (ingen verdict),
`UNSUPPORTED` eller `UNDECIDED` räknas aldrig som juridiskt verifierad.
Regressioner: `test_a_lexical_candidate_never_verifies_a_claim`,
`test_undecided_verification_does_not_verify_either`.

**Evidensgranularitet:** `ClaimEvidence` är en sammanhållande nod per dokumentversion, men
varje stöd är en egen `SUPPORTED_BY`-kant till en TextUnit med **egen** giltighet och
proveniens (`add_support` / `support_is_valid`). Två klausuler i samma version kan alltså
giltighetstider oberoende av varandra — att en upphör ogiltigförklarar inte den andra.
Regression: `test_two_independent_supports_in_one_document_version_expire_separately`.

Kanten `Claim --HAS_EVIDENCE--> ClaimEvidence` kopplar dem. Implementerat i
[`overgraph/legal_claims.py`](../../backend/app/services/overgraph/legal_claims.py):
`upsert_legal_claim`, `link_evidence`, `evidence_links`, `claim_is_verified`,
`unlink_document_version`, `add_support`, `support_is_valid` (med `Support`-spec:
TextUnit, proveniens, giltighet, Jev-verdict).

**Regression (`tests/test_overgraph_legal_claims.py`, 5 st):**

- flera dokument som stöder samma påstående ger **en** claim-nod och en evidenslänk per
  dokumentversion (nyast först, deterministiskt),
- radering av **ett** dokument tar bara bort dess evidenslänk; claimet och de andra
  dokumentens stöd finns kvar,
- försvinner **sista** giltiga evidenslänken blir claimet *inte verifierat* men stannar som
  aktiv nod — och **inget negativt claim** skapas,
- utgånget giltighetsfönster upphör att verifiera,
- `UNSUPPORTED` från Jev skapar **ingen** `CONTRADICTS`-kant (motsägelse kräver en faktisk
  motsägelse mellan påståenden, inte uteblivet stöd).

### Semantiska vakter som ska pinnas i paket 4

1. **Claim-identitet:** `claim_key(scope, predicate, canonical_json(value))` är stabil.
   Innan skrivning slås befintlig nod upp med `find_claims`; flera källor som stöder samma
   påstående får **en** claim med flera `SUPPORTS`-kanter — aldrig dubblering.
2. **Relationer och observationer:** `SUPPORTED_BY`/`SUPPORTS` och `CONTRADICTS` är kanter;
   supersession modelleras som stängd giltighet (`valid_to`), inte som en kolumn.
   En observation om att evidens saknas är en `VerificationObservation` — den får aldrig
   bli ett negativt juridiskt `Claim`.
3. **Dokument- och tenantgränser:** `kund_dokument`-purge och dokumentradering måste ta
   både noder och kanter. Empiriskt verifierat: `Catalog.delete_node` **kaskaderar**
   incidenta kanter (kant 1 → 0 i test), så borttagning av en nod städar sina kanter —
   men kanter som pekar *till* en kvarvarande nod från en borttagen nod måste verifieras
   med ett regressionstest, liksom scope-isolering (ingen kund ska kunna radera delade noder).

## 6d. Paket 4 — status och överlämning till paket 5

**Klart i paket 4 (läsare + spegling, SQL-skrivning orörd):**

- Klassificering av alla kvarvarande läsare (kunskapsgraf / applikationsaudit / migreringshjälp).
- `Claim` (logisk) / `ClaimEvidence` (per dokumentversion, per klausul) / `DocumentProperty`
  (versionsbunden) med separata identitetsregler.
- Verifierad evidens: `claim_is_verified` kräver Jev `SUPPORTED` **och** öppet
  giltighetsfönster; kandidat/`UNSUPPORTED`/`UNDECIDED` verifierar aldrig.
- Spegling via den verkliga skrivvägen för claims, entities, relationer och observationer —
  med paritetstester som jämför SQL och graf på identitet, scope och antal.
- Speglingen skapar **inga** verdicts: accepterat ≠ verifierat (negativt paritetstest).
- Tenantisolerad dokumentradering (endast dokumentets evidenslänkar; claim + andra dokument
  kvar) samt graf-audit med SQL-paritet.

**Överlämnat till paket 5 — returtypkopplade läsare.**
`claim_store.claim_by_identity` och `entities.lookup_knowledge_entity` /
`lookup_readable_entity` returnerar **SQL-modellobjekt** som skrivvägen använder för
återanvändning (`row.id`, `row.superseded_at`, `scope_from_row(row)`). De kan inte flyttas
isolerat utan att byta returtyp, och returtypen hör till paket 5 där SQL-modellerna och
skrivningen tas bort samtidigt. Grafen har redan motsvarigheterna
(`claim_in_graph`, entities speglade under SQL-id) med paritetstester, så bytet är
mekaniskt när skrivningen kapas.

**Nästa steg (paket 5):** kapa SQL-skrivvägarna (`persist_domain_claim`, `_insert_claim`,
`persist_knowledge_entity_result`, `persist_knowledge_relationship_result`,
`persist_knowledge_observation`), flytta de returtypkopplade läsarna, kör full regression,
och först därefter droppa modeller/tabeller i paket 6.

## 6e. Paket 5 — kopplingskarta för att kapa SQL-skrivvägarna

Varje skrivväg måste kapas **tillsammans med sina läsare och tester**, annars tappas
semantik. Nedan är den exakta kopplingen, i den ordning som ger minst blast radius.

### 5.1 Relationer (minst risk)

- Skrivväg: `relationships.persist_knowledge_relationship_result` (reuse via tuple,
  `_update_relationship` **slår ihop `extra`** med `merge_relationship_extra`, avvisar
  superseded och scope-byte).
- Läsare som måste flyttas först: `audit.py` (dubblettgrupper + cleanup), `kund_dokument`
  (räkning/purge; kan ligga kvar som tabellstädning till paket 6).
- Tester: `test_knowledge_persistence_codex_regressions` (kräver att sammanslagen `extra`
  bevaras), `test_knowledge_persistence_gate` (dubblettstädning).
- Graf-motsvarighet: `graph_relationship_mirror` (klart) + `graph_audit_counts`.
- **Bevaras:** `extra`-sammanslagning (får inte bli skriva-över), superseded-avvisning,
  scope-likhet. Vid kapning måste grafen slå ihop `attributes_json` i stället för att
  ersätta.

### 5.1 Relationer — försökt och backat (kunskapsläge)

Ett försök att kapa relationsskrivningen gjordes och **backades** innan det nådde en grön
svit. Lärdomarna är konkreta och styr nästa försök:

1. **Reuse-semantiken är flerfaldig.** Grafen måste slå ihop `extra` **både** från en
   befintlig grafkant **och** från en legacy-SQL-rad (testet kräver
   `{"legacy": True, "new": True}`). Enbart grafkantens props räcker inte.
2. **Legacy-endpoints finns bara i SQL.** Relationer som pekar på entiteter skrivna före
   speglingen måste speglas först, annars tappas kanten (eller kastar).
3. **Sju tester pinnar SQL-raden** (audit-dubbletter, tenant-scope, lagen.nu-writeback,
   graph events). De måste flyttas i samma ändring, inte efter.

konsekvens: relationer kapas **efter** entiteter och claims, när endpoint-speglingen är
fullständig och testerna redan läser grafen.

**5.1 GENOMFÖRT (efter entiteterna).** `persist_knowledge_relationship_result` skriver
numera grafen som auktoritativ för alla kanter vars båda endpoints har grafrepresentation
(claim↔entity, entity↔entity). `extra` slås ihop från **både** en legacy-SQL-rad och en
befintlig grafkant, så `{"legacy": True, "new": True}` bevaras. Reuse avgörs från grafen.

Kanter mot TextUnits/dokument har ännu ingen grafrepresentation. De behåller därför sin
SQL-rad via `_persist_unmappable_relationship` (med `EDGE_ADDED`-event) i stället för att
tyst tappas — flaggan `MirroredRelationship.mappable` skiljer fallen. Sidoeffekt: claims
speglas nu i `claim_store.persist_domain_claim` (den delade vägen), inte bara i gate-vägen,
så alla claim-skrivningar får graf-identitet.

`relationships_touching` läser nu grafen och kräver att **båda** endpoints är synliga för
läsaren — annars kunde en kunds kant läcka via en delad entitet (fångat av
tenant-regressionen).

### 5.1b Sista modelluckan: kanter mot TextUnits och dokument (klart)

`graph_relationship_mirror` mappar nu **alla** relationsslag till grafendpoints:

| `kind` | Grafnod |
|---|---|
| `entity` | `Entity` |
| `claim` | `Claim` |
| `text_unit` | `TextUnit` |
| `document` | `Document` (tunn ankarnod) |

`Document`-noden bär bara `scope_key` + `document_id` — metadata och ägarskap ligger kvar i
PostgreSQL. Noden finns för att kanter ska ha en endpoint, inte för att grafen ska äga
dokument. Den skapas på begäran när en kant refererar dokumentet.

Följden: `mappable=False` inträffar inte längre för kända slag, så relationer behöver ingen
SQL-rad av det skälet. Regression:
`test_edges_to_text_units_and_documents_are_mirrored` (claim→TextUnit blir en `SUPPORTS`-kant,
entity→dokument blir `LINKED` med ankarnod). Läsaren `relationships_touching` använder samma
nodtyper.

### 5.2 Observationer

- Skrivväg: `observations.persist_knowledge_observation` — reuse via
  `_lookup_observation` på `(scope, observation_class, kind, document_version_id,
  question_key, statement_normalized)`.
- Läsare: `audit` (antal), `kund_dokument` (delete), `claim_rekey` (migreringshjälp).
- Tester: `test_knowledge_persistence_gate` (observationsantal, 3 referenser).

**Identitetsgapet är stängt.** Grafens `observation_key(...)` gav en **annan** nyckel än
domänens `observation.id`, eftersom grafen använder `OBSERVATION_CLASS`/normaliserat
statement medan domänen använder `observation_class`/`question_key`. En kapning hade gett
dubbla observationer. `upsert_verification_observation` tar nu emot en explicit `key`, och
`graph_observation_mirror` skriver under `observation.id`. Regression:
`test_observations_are_mirrored_under_the_domain_identity`.

- Graf-motsvarighet: `graph_observation_mirror` (klart; `decision` tomt, nyckel =
  domän-id) + `graph_audit_counts`. Reuse kan nu avgöras med ett uppslag på domän-id:t.

**5.2 GENOMFÖRT: SQL-skrivningen för observationer är kapad.**
`persist_knowledge_observation` skriver nu **endast** OverGraph (under domän-id:t) och
returnerar `PersistedObservation(id)`. Reuse avgörs med ett uppslag i grafen.
Proveniensvalideringen mot dokumentmetadata ligger kvar (det är applikationsdata).
`audit_knowledge_graph` räknar observationer från grafen. `test_knowledge_persistence_gate`
verifierar nu att SQL-tabellen är **tom** och att klasserna finns i grafen.

`kund_dokument`-purge tar nu även bort grafens observationsnoder per tenant
(`_delete_scope_nodes` delas med TextUnit-purgen), så radering lämnar inget inventarium
kvar. Regression: `test_customer_purge_removes_graph_observations`. SQL-tabellen städas som
förut tills den droppas i paket 6.

**5.2 är därmed klart.**

### 5.3 Entiteter

**Speglingen är nu semantiskt likvärdig med SQL-vägen.** `graph_entity_mirror` slår ihop
`attributes_json` (inte skriva-över), uppdaterar `name`, och på reuse-speglingen speglas
**den mergade raden** (`_domain_from_row`) — inte det inkommande förslaget. Regression:
`test_entity_mirror_merges_extra_like_the_sql_update` (SQL-row och grafnod får identiska
attribut och namn efter två skrivningar med olika `extra`).

Det gör kapningen mekanisk: när `persist_knowledge_entity_result` slutar skriva SQL-raden
finns redan rätt merge-semantik i grafen, och `lookup_knowledge_entity`/`lookup_*` är bara
anropade av tester (inte av produktionsflödet).

**Returtypen är redan avkopplad.** `persist_knowledge_entity_result` returnerar nu
`PersistedEntity(id)` i stället för SQL-modellen, så kapningen inte längre kräver att
signaturen ändras samtidigt. Läsaren `entity_in_graph(scope_key, entity_id)` finns med
paritetstest mot `lookup_knowledge_entity` (samma id, namn, nodtyp; annan kund får `None`).

**5.3 GENOMFÖRT: entity-skrivningen är kapad.** `persist_knowledge_entity_result` skriver
inte längre någon SQL-rad; den returnerar `PersistedEntity(id)` och avgör reuse med ett
uppslag i grafen. Läsarna `lookup_knowledge_entity` / `lookup_readable_entity` läser nu
**grafen** (owned först, sedan shared, aldrig annan tenant), och relationsvalideringen
(`_endpoint_scope`) hämtar entitetens scope från grafnoden i stället för SQL-raden.

Legacy-rader läses fortfarande (stable-key-reuse och dubblettstädning) men skrivs aldrig.
Testerna flyttades i samma ändring: persist-paths assertioner läser grafen, medan
cleanup-testerna — som seedar legacy-rader direkt i SQL — behåller SQL-assertionerna med en
explicit kommentar om varför.

Verifierat: **108 tester** gröna i sviten.


- Skrivväg: `entities.persist_knowledge_entity_result` (reuse via `_entity_by_stable_key`,
  `_update_entity` **slår ihop `extra`** och uppdaterar `name`, scope-avvisning).
- Läsare: `lookup_knowledge_entity`, `lookup_readable_entity` (kund först, sedan shared;
  aldrig annan tenant), `audit`.
- Graf-motsvarighet: entities speglade under SQL-id (klart).
- **Bevaras:** `extra`-merge, `name`-uppdatering, owned→shared-fallbackens
  `visible_to`-kontroll.

### 5.4 Claims (störst risk)

**Förberett (grönt):**

- `legal_claims.supporting_text_units(catalog, claim_key)` läser stödjande TextUnits från
  grafen (evidenslänk → `SUPPORTED_BY`-kant → TextUnit) med paritetstest mot SQL:s
  `supporting_text_unit_ids_for_claim` — samma lista för samma claim.
- **Supersession speglas nu i grafen.** `supersede_knowledge_claim` sätter `status`,
  `superseded_at_ms`, `valid_to_ms` och `successor_key` på den logiska claim-noden, så
  historiken är frågbar även utan SQL-mirror. Regression:
  `test_supersession_is_visible_in_the_graph`. Det var ett verkligt modellgap: utan detta
  hade supersession tyst försvunnit i paket 6.
- Claims speglas nu från `claim_store.persist_domain_claim` (delade vägen), så även direkta
  `persist_knowledge_claim`-anrop får grafidentitet.

**Gjort denna omgång (grönt):**

- **Claim-nyckeln är nu alltid SQL-radens id.** Legacy-rader kan ha ett annat id än den
  beräknade identiteten; speglingen skriver därför under `row.id`
  (`mirror_claim(claim, key=row.id)`, `upsert_legal_claim(..., key=...)`). Utan detta pekade
  evidenslänkarna på en nyckel som inte fanns (fångat av backfill-regressionen).
- **Sena stöd kopplas i grafen.** `attach_supporting_text_units` speglar nu även nya
  TextUnits (`attach_claim_supports`, med merge av `text_unit_ids_json` + `SUPPORTED_BY`),
  så grafen inte hamnar efter SQL när stöd läggs till efter första skrivningen.
- **Speglingen sker före stödkopplingen**, så claim-noden finns när stöden refererar den.

**Backat:** att läsa `supporting_text_unit_ids_for_claim` från grafen. Legacy-rader som bara
finns i SQL (backfill, cleanup-tester) gjorde att grafen och SQL divergerade; en
graf-först-läsning med SQL-brygga gav inkonsekventa svar. Läsaren ligger kvar i SQL tills
skrivningen kapas i samma ändring — då försvinner divergensen.

**Backfill av legacy-claims (ny, grön).** `knowledge/backfill_claims.py` materialiserar
varje SQL-claim i grafen under sitt SQL-id och **verifierar** att grafen rapporterar exakt
samma stödjande TextUnits (`ClaimBackfillReport`: rows / mirrored / verified / mismatches,
`verified_completely`). Legacy-rader som aldrig åter-persistas hade annars tystnadsförsvunnit
i paket 6. Tester: idempotens, full verifiering, och att divergens rapporteras i stället för
att döljas.

**Två buggar fångade av backfillen:**

1. Speglingen skrev en evidensnod **per TextUnit**, så `text_unit_ids_json` överskrevs och
   bara sista klausulen blev kvar. Nu grupperas stöd per dokumentversion och noden får hela
   unionen.
2. `link_evidence` **ersatte** stödlistan. Nu ackumuleras den ( `previous | new` ), så en
   omspegling kan aldrig tyst tappa evidens — borttagning sker explicit via
   `unlink_document_version(s)`.

**Kvar:** `claim_by_identity`/`_insert_claim`/`attach_supporting_text_units` samt
`audit`/`kund_dokument`-läsarna — den största testsviten (`test_knowledge_claims`).

**Försök att kapa claim-skrivningen — backat, med exakt orsak.** Kapningen gjordes
(grafen auktoritativ, `PersistedClaim`, graf-supersession) och gav **13 röda tester**. De
fördelade sig på tre beroenden som måste flyttas först:

1. `KnowledgeClaimRecord`-rader läses av `claim_by_identity`, `claims_for_document`,
   question-evidence och tenant-tester — 20+ referenser.
2. `supporting_text_unit_ids_for_claim` måste vara SQL tills skrivningen kapas: grafen
   ackumulerar stöd, så en graf-först-läsning ändrade svaret för
   "radera ett stödjande dokument"-fallet.
3. `supersede_knowledge_claim` returnerar en SQL-rad; en graf-variant kräver att alla
   anropare byter returtyp samtidigt.

Graf-supersession (`claim_supersession.supersede_graph_claim`) ligger kvar som väg för
claims som bara finns i grafen, och backfillen verifierar att grafen har samma stöd som SQL.

**Läsaromkoppling, steg 1 (klart):**

- `_claim_scope` läser claimens tenant-scope från grafnoden när SQL-raden saknas — så en
  claim som bara finns i grafen fortfarande har rätt scope.
- **Modellucka stängd: claim → fråga.** `overgraph/claim_answers.py` inför
  `KnowledgeQuestion`-noder (logisk fråga per scope+question_key) och `ANSWERED_BY`-kanter
  från claim, med `research_need_id`, `source_type`, `knowledge_question_id` och relation på
  kanten. `answer_research_need` speglar varje svar. Läsaren
  `claim_answers_for_question` ger samma claim-id:n som SQL-varianten (paritetstest).
  Därmed kan reuse-frågan "vilka claims besvarar den här frågan?" köras helt i grafen.
- `claim_supersession.py` bröts ut (claims.py höll på att passera 500-radersgränsen).

**Läsaromkoppling, steg 2 (klart): claim→fråga läses nu från grafen.**

`claim_answers_for_question_key` returnerar `KnowledgeClaimAnswerHit` byggda från
`KnowledgeQuestion`-noden, `ANSWERED_BY`-kanten (source_type, knowledge_question_id,
created_at_ms) och claimens grafstöd. Paritet med SQL-varianten verifierad i
`test_claim_answer_links_are_mirrored_for_question_reuse`; tenant-testerna
(customer/shared/annan kunds fråga) är gröna på den grafbaserade läsaren.

Det betyder att **två av tre** blockerande beroenden för claim-kapningen nu är grafbaserade
(scope + frågesvar). Kvar: `KnowledgeClaimRecord`-raderna läses fortfarande av
`claim_by_identity`, `claims_answering_question_key` (via hit-läsaren, nu graf) och
`claim_rekey` (migreringshjälp).

**Tredje kapningsförsöket (claim-rader + svarsrader samtidigt) — backat.** 17 röda tester
visade att även med graf-läsare för scope och frågesvar återstår ett beroende:
`KnowledgeClaimRecord` konsumeras av cleanup/`claim_rekey`/question-evidence-flödena och av
gate-testerna som seedar legacy-rader. Två kapningar (claims + svarsrader) i samma ändring
kräver att **alla** dessa flyttas samtidigt — annars blir det en halvmigrerad väg.

Behållet från försöket (allt grönt): graf-läsaren för claim→fråga, `answered_claim_ids`
(idempotens i grafen), `PersistedClaim`-typen, `CLAIM_ADDED`-event från den delade vägen,
och att `persist_domain_claim` avvisar supersedade claims via grafstatus.

**Testflytten påbörjad (grönt, SQL-skrivningen kvar):** de tester som tidigare blockerade
kapningen läser nu **också** grafen, så de kan stå kvar oförändrade när skrivningen kapas:

- gate-testerna kräver en grafclaim utöver SQL-raden (`_graph_claim_count`), och
  dokumentraderingstestet kräver att claimet finns i grafen efter radborttagning.
- tenant-testet för `ANSWERED_BY` kräver att svarslänken syns i grafen för rätt kund och
  **inte** för en annan kund.
- stale-claims-testet stämplar grafclaimens `created_at_ms`, och färskhetsläsaren väljer
  claimnodens tidsstämpel före svarskantens — så TTL/färskhet fungerar utan SQL-raden.

**Modellgap stängt: claimens skapelsetid finns nu i grafen** (`created_at_ms` på `Claim`),
bevarad vid omskrivning. Det krävdes för att färskhetsregeln ska överleva utan SQL.

**Testflytten fortsatt (grönt):** gate-testerna för persist-vägen räknar nu grafclaims
(`_graph_claim_count`), tenant-testet för en privat claim läser grafnoden i stället för
SQL-raden, och `test_knowledge_claims` verifierar predikatet via `claim_in_graph`.
Legacy-testerna (cleanup, backfill) ligger kvar på SQL-rader — de testar
migreringsverktyget, inte skrivvägen.

**Graf-deduplicering: verktyg klart, behovet preciserat.** `legal_claims.merge_claims`
flyttar evidens, `ANSWERED_BY`/`SUPPORTS`/`CONTRADICTS`/`LINKED`-kanter till vinnaren och
raderar förlorarnoden (regression: evidens från båda noderna finns kvar, svarslänkar följer
med, förloraren är borta).

Behovet är dock mindre än antaget: `uq_knowledge_claims_scope_identity` gör att **samma
identity inte kan ha två rader** efter Alembic 126. Dubbletter kan bara uppstå för
pre-126-data som `backfill_source_independent_claims` slår ihop; där känner merge-verktyget
förlorar-id:na och kan anropa `merge_claims` i paket 6. Att gissa dubbletter från
identity i backfillen vore fel — det försöket backades efter att unikhetsvillkoret visade
att grupperingen inte kunde inträffa.

**Wiring klar:** `claim_rekey.rekey_claim_identities` anropar `merge_claims` för varje
förlorare (där id:na är kända), och hoppar över rader som ännu inte speglats. Regression:
`test_rekey_merges_legacy_duplicates_in_the_graph_too` — två pre-126-rader blir **en**
SQL-rad **och en** grafnod med unionen av båda dokumentens stöd; förlorarnoden är borta.

**5.4 GENOMFÖRT: claim-rader och svarsrader är kapade tillsammans.**

`persist_domain_claim` skriver nu **endast** OverGraph (logisk claim + evidens per
dokumentversion + `SUPPORTED_BY`-kanter) och returnerar `PersistedClaim`. Svarslänkar
(`ANSWERED_BY`) skrivs också enbart i grafen, med `answered_claim_ids` för idempotens.
`_insert_claim`, de SQL-baserade stöd-länkarna och `KnowledgeClaimAnswer`-insättningen är
borttagna ur produktionsvägen.

Läsarna flyttades i samma svep:

| Läsare | Nu |
|---|---|
| `supporting_text_unit_ids_for_claim` | graf först (ackumulerade stöd), SQL-brygga för pre-mirror-rader |
| `claim_answers_for_question_key` | `KnowledgeQuestion`-nod + `ANSWERED_BY`-kant |
| `audit_knowledge_graph` domänclaims | `Claim`-noder klassificerade via `value_json` |
| `_claim_scope` | SQL-rad, annars grafnod |
| kund-radering | rensar även `Claim`-noder per tenant |

**FK-kravet hanterat:** eftersom `knowledge_claim_answers.claim_id` refererar
`knowledge_claims.id` kapades båda skrivningarna i samma ändring — annars hade Postgres
avvisat svarsrader utan claim-rad.

Verifierat: **154 tester** gröna i sviten (inkl. `test_alembic_graph_reconcile`).

**Hinder upptäckt: FK mellan svarsrader och claims.** `knowledge_claim_answers.claim_id` har
`ForeignKey("knowledge_claims.id")`. Att sluta skriva claim-rader medan svarsraderna skrivs
skulle bryta FK på Postgres. Därför måste claim-rader **och** svarsrader kapas i samma
ändring (eller tabellerna droppas tillsammans i paket 6) — det är därför kapningen inte kan
göras halvvägs.

- Skrivväg: `claim_store.persist_domain_claim` + `_insert_claim` +
  `attach_supporting_text_units` (reuse via `claim_by_identity`, `_reject_superseded_claim`,
  scope-likhet, `assert_claim_grounding_scope`).
- Läsare: `claim_by_identity`, `audit`, `kund_dokument`, `persistence.delete_canonical_document`
  (claim-länkar).
- Graf-motsvarighet: `legal_claims` (klart) + `claim_in_graph` (paritet verifierad).
- **Bevaras:** att en återanvänd claim inte tappar befintliga stödjekanter, att superseded
  avvisas, och att `ClaimEvidence`/`SUPPORTED_BY` får rätt dokumentversion och verdict.

### 5.5 Slutordning

1. Relationer → läsare + tester.
2. Observationer → läsare + tester.
3. Entiteter → `lookup_*` + `audit`.
4. Claims → `claim_by_identity` + `audit` + `kund_dokument`.
5. Först därefter paket 6: modellgap, Alembic-dropp, full regression + återställningstest.

**Varför inte kapa nu:** varje skrivväg har reuse/merge-semantik som testerna pinnar
(t.ex. `row.extra == {"legacy": True, "new": True}`). Att kapa en skrivväg utan att flytta
dess läsare och uppdatera dessa tester skulle tyst tappa semantik — exakt det som ska
undvikas.

## 6f. Paket 6 — inventering och paritetskontroll

### Inventering av de tolv tabellerna

| Tabell | Innehåll | Skrivs nu av | Graf-motsvarighet |
|---|---|---|---|
| `knowledge_claims` | logiska claims | **ingen** | `Claim` |
| `knowledge_claim_text_units` | `SUPPORTED_BY` | **ingen** | `ClaimEvidence` + `SUPPORTED_BY`-kanter |
| `knowledge_claim_answers` | `ANSWERED_BY` | **ingen** | `KnowledgeQuestion` + `ANSWERED_BY`-kant |
| `knowledge_entities` | noder | **ingen** | `Entity` |
| `knowledge_relationships` | kanter | **ingen** | `SUPPORTS`/`CONTRADICTS`/`LINKED` |
| `knowledge_observations` | inventarium | **ingen** | `VerificationObservation` |
| `graph_nodes` / `graph_identifiers` | Graph v2-noder | `graph_v2/write.py` | `Entity`/`Identifier` |
| `graph_facts` / `graph_fact_sources` / `graph_fact_relations` / `graph_fact_question_dependencies` | Graph v2-fakta | `graph_v2/write.py`, `dependencies.py` | `Fact` + kanter |

**Slutsats:** de sex `knowledge_*`-tabellerna är helt utan producenter. De sex `graph_*`-tabellerna
har **fortfarande skrivare** — deras skrivvägar måste kapas (eller verifieras mot grafen) innan
tabellerna kan droppas. Det är nästa steg i paket 6 och får inte förbigås.

### Identitetsägarskap — din huvudrisk, utredd

**Fakta:** OverGraph äger identiteten med **samma funktion** som Graph v2:
`overgraph/write.fact_key` anropar `graph_v2/identity.fact_identity`
(`scope, source, target, predicate, context, occurrence_key, normalized text`). Samma faktum
ger alltså samma nodnyckel — ingen duplicering vid identiska fakta.

**Flera källor:** `attach_sources` lägger `SUPPORTS`-kanter och ackumulerar
`source_refs_json`.

**Två riktiga buggar hittade och fixade** (båda hade tyst tappat proveniens vid flera källor):

1. `attach_sources` litade på den **inskickade** noden i stället för att läsa lagrat tillstånd
   → tidigare källor kunde skrivas över. Nu läses `catalog.get_by_key` som bas.
2. `write_fact` skrev `source_refs_json` från enbart den nya källan vid omskrivning. Nu
   bevaras `source_refs_json`, `created_at_ms`, `status`, `valid_at_ms` och `invalid_at_ms`
   från befintlig nod, och returvärdet läses om efter `attach_sources`.

Regression: `test_two_sources_for_one_fact_share_a_single_graph_node` — två källor till samma
faktum ger **en** `Fact`-nod med **båda** källorna.

**Kvarvarande semantikskillnad (måste beslutas innan graph_v2-skrivningen kapas):**
SQL-vägen har en LLM-**domare** (`judge.compare` → SAME/CONTRADICTS/DISTINCT) som slår ihop
fakta med *olika* identitet men samma innebörd. OverGraph gör bara deterministisk
identitetsmatchning. Kapas SQL-skrivningen utan att domarbeslutet flyttas tappas den
fuzzy dedupliceringen — och då kan semantiskt identiska fakta bli två noder trots att
identiteten är korrekt. Det måste lösas (t.ex. att domarbeslutet beräknas först och den
resulterande nyckeln skrivs till grafen) innan `graph_v2/write.py` kopplas bort.

### Additivt faktakontrakt (arkitekturbeslut, implementerat)

Beslutet: **faktanoder skapas deterministiskt och källförankrat; semantisk likhet får
aldrig avgöra om en nod skapas, återanvänds eller slås ihop.**

**Identitet (`graph_v2/identity.py`):**

```
source_fact_identity(scope, source_identity, document_version_id,
                     source_unit_key, fact_occurrence_key)
  = sha256(canonical_encode({"identity_version": "source-fact-v1", ...}))
```

Kanonisk JSON med sorterade nycklar — ingen strängkonkatenering. `fact_occurrence_key` är en
explicit förekomstnyckel när extractorn ger en; annars en deterministisk **lokal** selektor
(`fact_occurrence_selector` över predikat + kontext + kanoniserad text) som bara används
tillsammans med käll­enheten och dokumentversionen.

**Konsekvenser som nu gäller:**

| Situation | Resultat |
|---|---|
| samma källförekomst skrivs igen | samma nod (idempotent) |
| två TextUnits med samma formulering | **två** noder |
| två dokument/versioner med samma formulering | **två** noder |
| två påståenden i samma TextUnit | **två** noder |
| semantiskt likvärdiga formuleringar | **två** noder (relation får läggas till) |
| motstridiga påståenden | **två** noder + `CONTRADICTS`-kant |

**Jev är bortkopplad från skrivvägen.** `overgraph/ingest.py::resolve_fact` anropar inte
längre `judge.compare`; parametrarna finns kvar för anropsplatser men påverkar aldrig om en
nod får skapas. `write_fact` konsulterar varken domare eller embeddings för identiteten.

**Buggar som fixades i samma svep** (de hade tyst tappat proveniens):
`attach_sources` läser lagrat tillstånd i stället för den inskickade noden, och `write_fact`
bevarar `source_refs_json`/temporalitet vid omskrivning samt returnerar en färsk nod.

**Tester** (`tests/test_source_fact_identity.py`, 10 st): identitetsmatrisen ovan,
embeddings påverkar inte identitet, tenant-isolering, `CONTRADICTS` behåller båda noderna,
lokal selektor deterministisk, samt upprepad skrivning idempotent.

**Gamla semantiska sammanslagningen borttagen från produktionsskrivvägen.**

- `graph_v2/write.write_deterministic_fact` — ny skrivväg: beräknar `fact_identity`, gör
  idempotent upsert, kopplar källor. **Ingen** domare, inga kandidater, inga embeddings.
- `graph_v2/legal_writeback.write_legal_facts` (outbox-workerns skrivväg) använder den i
  stället för `resolve_fact(..., judge=...)`. Jev avgör inte längre om en faktanod skapas.
- `overgraph/ingest.resolve_fact` (OverGraph-vägen) hade också en domargrind — den är
  borttagen; parametrarna finns kvar för anropsplatser men påverkar inte nodskapande.

`resolve_fact` (SQL) finns kvar för tester och historiska anrop, men produktionen använder
inte dess domarväg längre.

**Jev borttagen från hela skrivkedjan (inte bara fakta):**

- `graph_v2/legal_writeback`: node-domaren (`resolve_node(..., judge=...)`) är borttagen —
  nodidentitet är deterministisk. `_LazyJudges`/`_LazyJudgeProxy` och parametermarkisen i
  `outbox.process_graph_work`/`write_legal_facts` är borttagna (inga oanvända
  kompatibilitetsparametrar kvar).
- `graph_v2/jev_judge` finns kvar som fristående modul för separat relationsberikning
  (tillåtet enligt beslutet), men **ingen produktionsskrivväg importerar den längre**.

**Tantivy:** `INDEX_VERSION` höjd till `graph-index-v4` eftersom faktanycklarna är
källförankrade; ett gammalt index kan därmed inte återanvändas med nya nycklar.

**Robusthetstester** (`tests/test_source_fact_identity.py`, nu 13): skrivning med en domare
som alltid kastar → noden skapas ändå (Jev kan inte blockera), retry av samma förekomst är
idempotent utan dubbel provenienskant, och fel i relationsworkflow lämnar lagrade fakta orörda.

**Migrering av befintliga fakta (`knowledge/migrate_fact_identity.py`).**

Legacy-fakta hade en identitet per *semantisk* faktum och alla matchande källor hängda på
den. Den additiva kontraktet kräver en faktanod per källförekomst, så migreringen:

1. läser varje `graph_facts`-rad och dess `graph_fact_sources`,
2. härleder `document_version_id` från TextUnit-noden,
3. beräknar `source_fact_identity(scope, source_identity, version, unit, occurrence)`,
4. materialiserar **en faktanod per TextUnit** när den gamla noden hade flera källor,
5. kopierar relationer (`SUBJECT`/`OBJECT`/`CONTEXT`/`SUPPORTS`/`CONTRADICTS`/`DEPENDS_ON`)
   till varje materialiserad nod (de låg på den sammanslagna noden),
6. rapporterar fakta utan källankare som `kept_explicit_contract` och saknade TextUnits som
   **`unresolved` — aldrig fabricerade**.

Rapporten ger `total`, `compliant`, `rewritten`, `kept_explicit_contract`, `materialised`,
`unresolved`. Regressioner: en sammanslagen legacy-faktum med två källor → **två** nya noder;
faktum med episode-källa behåller sitt explicita kontrakt; saknad TextUnit rapporteras och
ingen nod skapas (ingen fabricering).

**Paritet på källförekomstnivå (utökad till `graph_*`).**

`verify_parity` kontrollerar nu även de sex Graph v2-tabellerna:

| Tabell | Kontroll |
|---|---|
| `graph_nodes` | noden finns som `Entity` med samma id |
| `graph_facts` | **för varje TextUnit-källa** finns en faktanod med den källförankrade nyckeln (`source_fact_identity`); fakta utan TextUnit-källa kräver nod på sitt explicita kontrakt |
| `graph_fact_sources` | källistan används för att verifiera förekomsttäckningen |
| `graph_fact_relations` | båda fakta finns och det finns en `LINKED`-kant i grafen |
| `graph_fact_question_dependencies` | det finns en `DEPENDS_ON`-kant från faktanoden |
| `graph_identifiers` | räknas in i underlaget |

Regression `test_parity_covers_graph_v2_tables_before_the_drop`: före migreringen **felar**
pariteten för ett legacy-faktum med TextUnit-källa (ingen källförankrad nod), efter
`migrate_fact_identities` är den **grön** — det är exakt den grind som Alembic-droppen ska
kräva.

**Alembic-droppen kräver färsk paritet (`192_drop_graph_tables`).**

- `knowledge/parity_gate.py::require_parity(database_url)` bygger en egen async-anslutning
  till **samma databas** och öppnar vid behov katalogen på `settings.overgraph_dir`, kör
  `verify_parity` och kastar `GraphParityError` med de första avvikelserna. Ett tidigare
  godkänt fingerprint accepteras alltså **inte**.
- Migrationen: kontrollerar att tabellerna finns, kör grinden, kopierar varje tabell till
  `<tabell>_dropped` (`CREATE TABLE AS SELECT`) och droppar i FK-ordning.
  `downgrade()` återskapar tabellerna från metadata och återställer rader från
  `_dropped`-tabellerna.
- `graph_ingest_work`, `graph_embedding_cache`, `knowledge_answer_reviews` och
  `knowledge_graph_events` lämnas kvar — orkestrering och applikationsaudit enligt beslutet.

Regressioner: `test_gate_passes_when_the_graph_is_current` (grönt när grafen är aktuell) och
`test_gate_refuses_when_a_legacy_claim_is_missing_in_the_graph` (`refusing to drop …`) samt
Alembic-head-testerna som nu kräver att de tolv tabellerna är **borta** vid head.

**Skrivvägarna mot Graph v2 är delvis avvecklade (denna omgång):**

- `graph_v2/legal_writeback` (outbox-workern) beräknar faktanyckeln med OverGraphs
  `fact_key` och skriver endast via `publish_legal_fact`; SQL-uppslagningen
  (`resolve_exact_fact`, `write_deterministic_fact`) och den SQL-baserade
  frågeberoende-skrivningen är borta ur vägen.
- **Svarsfaktapubliceringen är BACKAD** till SQL+OverGraph: när SQL-delen togs bort
  slutade `lookup_answers` hitta svaren och 21 research-reuse-kontrakt föll. Orsaken är att
  återanvändningsläsningen fortfarande matchar svarsfakta via den SQL-härledda identiteten
  (`fact.id`), inte den nya källankrade nyckeln. Det måste migreras i samma ändring som
  publiceringen — annars tappas återanvändningen.
- **Paritetsgrinden fångar ordningen:** eftersom svarsfakta fortfarande får sin nyckel från
  SQL kommer `verify_parity` att rapportera dem som saknade i grafen, och
  `192_drop_graph_tables` **vägrar** droppa. Droppen kan alltså inte köras förrän
  svarsfaktapubliceringen är OverGraph-only. Det är avsiktligt.

**Tantivy-versionen kontrolleras nu på riktigt.** `INDEX_VERSION` var tidigare bara en
konstant. Nu skriver `build_from_overgraph` `version.json` bredvid indexet och
`retrieval_index.open_index` **vägrar** öppna ett index byggt med en annan version (t.ex.
`graph-index-v3` efter identitetsbytet) och kräver ombyggnad. Regression:
`test_index_rebuilds_from_source_anchored_fact_keys`.

**Prestandamätning (`scripts/benchmark_additive_fact_write.py`, 200 fakta):**

| Mått | Värde |
|---|---|
| tid per faktaskrivning (p50) | 0,154 ms |
| p95 | 0,171 ms |
| skrivningar/sekund | ~6 600 |
| **Jev-anrop på kritiska skrivvägen** | **0** |

Proveniens skrivs alltid (källa + dokumentversion på faktanoden) — hastigheten vinns inte
genom att hoppa över den.

**Svarsfaktornas identitet är nu pinnad mellan lagren.** Regression
`test_answer_fact_identity_agrees_with_the_sql_contract` visar att OverGraphs `fact_key`
och Graph v2:s `fact_identity` ger **samma nyckel** för en svarsfakta (episode-källa, ingen
TextUnit-ankare). Det betyder att byteset till OverGraph-only publicering är mekaniskt när
det görs — och att ett framtida fel där nycklarna glider isär fångas direkt.

**SQL-bryggorna i claims är borttagna.** `supporting_text_unit_ids_for_claim` och
`_claim_scope` läser nu **endast** OverGraph — ingen SQL-fallback kvar. Det krävdes eftersom
tabellerna droppas vid head; en kvarvarande brygga hade kraschat på en migrerad databas.
Legacy-testerna (backfill/rekey) som seedar rader direkt i SQL läser nu SQL-länkarna explicit
i stället för via produktionsläsaren — de testar migreringsverktyget, inte skrivvägen.

**Sista SQL-läsaren i researchvägen identifierad — och backad.**

`result_search._frontier` och `_nearby` läser fortfarande SQL `graph_facts`/`graph_nodes`.
Ett försök att migrera dem till OverGraph gav 9 röda research-reuse-tester: fixturesna
(`persisted_basis` m.fl.) **seedar SQL-graftabellerna direkt**, så en grafbaserad läsare ser
inget i testmiljön. Slutsats: läsarbytet måste flytta fixturesna i samma ändring — precis som
för claims och relationer tidigare.

Detta är den **sista kvarvarande produktionsläsaren** av SQL-graftabellerna. När den är
migrerad är paritetsgrinden det enda som återstår innan `192_drop_graph_tables` kan köras.

**Nästa försök på frontier/nearby: två felorsaker identifierade.**

Migreringen gjordes två gånger och backades båda gångerna. Det som är känt:

1. `_nearby` **närvaro-kontroll** är den känsliga delen. Den nuvarande SQL-versionen kräver
   en svarsfakta vars *mål* är en nod som hör till ett **färdigt attempt** (ready/completed)
   för samma kund och modul — en join över `graph_nodes.attributes.evidence_set_id` →
   `evidence_sets` → `execution_attempts` → `execution_runs`. Min OverGraph-version ersatte
   den med "finns färdig evidence set + scanna alla Fact-noder efter evidence_set_id", vilket
   **inte gav samma urval** i testmiljön och gjorde att `_nearby` returnerade tidigt → inga
   partiella träffar.
2. Rätt väg är att återanvända den befintliga frågan `answer_facts(catalog,
   need.knowledge_question_id, customer_id, …)` (samma väg som `exact_answers`) för
   närvaro/frontier, och att flytta fixtures-proben (`tests/research_reuse/probes.py::capture`)
   som i dag läser SQL `graph_nodes`/`graph_facts` till OverGraph i samma ändring.

**Denna omgång: två bestående förbättringar, en backad.**

- `tests/research_reuse/probes.py::capture` läser nu OverGraph (`find_question` +
  `answer_facts`) i stället för SQL `graph_nodes`/`graph_facts` — fixturen är därmed
  oberoende av SQL-graftabellerna.
- `kund_dokument` räknar och rensar grafen via OverGraph (`count_nodes_by_labels`,
  `_delete_scope_nodes`), inklusive `Fact`/`Entity`/`KnowledgeQuestion` per tenant.
- **`_frontier`/`_nearby` backades igen.** Med en förenklad närvaro-kontroll gick
  `test_result_navigation` grönt (12/12), men `test_01_saved_answer` föll (4) eftersom den
  SQL-joinen i närvaro-kontrollen också fungerar som **skydd mot att ladda prompts** i
  onödan. Slutsats: närvaro-kontrollen måste återanvända `answer_facts` **och** bevara
  "färdigt attempt"-filtret exakt; en förenkling ändrar när `_nearby` körs.

**GENOMBROTT: svarsfakta publiceras nu enbart i OverGraph, och researchvägen läser enbart
grafen.**

- `answer_graph.publish_answer`: ingen SQL `resolve_fact`/`resolve_node`/frågeberoende kvar.
  Faktanyckeln beräknas med OverGraphs `fact_key`; endpointsen (fråga/svar) upsertas i grafen;
  beroenden kopplas via `publish_answer_fact`. `GraphFactSource`-läsningen är borta.
- `result_search._frontier`/`_nearby` läser OverGraph. `_nearby`s närvaro-kontroll bevarar
  **exakt** SQL-semantiken: färdiga attempts (ready/completed) för samma kund/modul + svarsfakta
  vars **målnod** har `evidence_set_id` i en sådan mängd. Den detaljen var avgörande — en
  förenklad kontroll ändrade när `_nearby` körs och därmed när promptkatalogen krävs.
- Fixtures/prober (`probes.py::capture`, `test_04`, `test_07`) läser grafen i stället för
  SQL-tabellerna; `test_06` verifierar att svarsfakta finns i grafen med rätt målnod.

**Verifierat: 254 kontrakt gröna** (235 research-reuse + 19 question-evidence).

**Sista SQL-grafskrivaren är borta ur produktionen.**

- `SqlQuestionEvidenceGraph` ankrar frågor i OverGraph via
  `overgraph/questions.ensure_question_node` i stället för `graph_v2.questions.question_node`.
- `question_prepare` gör samma sak för nya frågor.
- `graph_v2.questions.link_decomposition` skriver en `research.decomposed_to`-fakta i
  OverGraph (med `attach_question_dependency`) i stället för SQL `resolve_fact`.

**Verifierat: 267 kontrakt gröna** (235 research-reuse + 19 question-evidence + 13 iterativ
question research).

`graph_v2/questions.py::question_node` har **inga produktionsanropare** kvar. Kvar att städa
(ingen funktionspåverkan): `graph_v2/write.py`, `graph_v2/dependencies.py`,
`graph_v2/retrieval.py` samt SQL-`question_node`, som bara används av legacy-tester
(`test_graph_v2.py` och retrieval-jämförelsetester). De tas bort tillsammans med sina tester
när arkitekturen är slutligt verifierad.

**Avvecklingen är genomförd i koden.**

- `graph_v2/write.py`, `graph_v2/dependencies.py`, `graph_v2/retrieval.py` och
  `graph_v2.questions.question_node` är **borttagna**; `scripts/evaluate_graph_v2.py` och
  `tests/test_graph_v2.py`/`test_graph_v2_shared_retrieval.py` likaså.
- `legal_writeback` kopplar frågeberoenden direkt i OverGraph.
- `parity_gate` öppnar katalogen med **konfigurerad** dimensionalitet
  (`settings.embedding_dimension` + mem0-modellens), inte en hårdkodad 32 — annars kunde
  grinden aldrig köras på en riktig katalog.
- Legacy-testet för semantisk `SAME` är uppdaterat till det additiva kontraktet:
  likvärdig formulering ger en **ny** nod, `CONTRADICTS` behåller båda.
- Nytt: `tests/test_graph_restore.py` — backa upp katalogen, öppna i ren miljö, verifiera
  noder/kanter/proveniens/claims och bygg om Tantivy från den återställda grafen (inkl.
  tenant-isolering). Det täcker acceptanskriterium 10 (återställning utan SQL-spegel).

**Sista SQL-spegelläsningarna borta (entiteter och relationer).**

- `persist_knowledge_entity(_result)` läser/skriver **endast** OverGraph: identiteten är
  deterministisk per scope/typ/nyckel, sammanslagning av `extra` sker på noden och
  returvärdet är den auktoritativa domänmodellen (namn + attribut).
- `persist_knowledge_relationship(_result)` skriver endast grafen; `extra` slås samman på
  kanten, och ett saknat endpoint ger ett **tydligt fel** i stället för en SQL-rad i en
  droppad tabell. `edge_in_graph` läser kanten för idempotens.
- Cirkulär import som slog ut processproben: `graph_v2.identity` importerar nu
  `knowledge.identity` lazy, och `overgraph.model` importerar `KnowledgeTenantScope` från
  `app.database.knowledge_scope` (källan) i stället för via `knowledge`-paketets tunga
  `__init__`. Probing av flerprocess-låset fungerar igen.

**Sista SQL-läsningarna borta även i kund-purge, audit-vägen och writeback.**

- `kund_dokument` räknar claims/entities/relationships från OverGraph och rensar tenantens
  claims/entiteter i grafen (SQL-raderna för observationer togs bort — grafen rensas redan).
- `legal_writeback` hämtar frågekopplingar via `questions_answered_by_claim` (ANSWERED_BY i
  grafen) i stället för `knowledge_claim_answers`.
- `persist_knowledge_entity`/`persist_knowledge_relationship` läser och skriver endast grafen;
  tenant-skyddet (`_assert_endpoint_scopes`) validerar mot grafens endpoints.
- Cirkulär import som slog ut multiprocess-proben bröts vid källan
  (`graph_v2.identity` → lazy `knowledge.identity`, `overgraph.model` → `database.knowledge_scope`).

Kvar för att kunna köra droppen på data: kör `backfill_claims`, faktamigreringen och
`backfill_text_units` på utvecklingsdatabasen, bygg om Tantivy, och låt sedan
`192_drop_graph_tables` köra — grinden vägrar om pariteten inte håller. Audit-/rekey-verktygen
(`audit.py`, `claim_rekey.py`) är migreringsverktyg som körs **före** droppen och rör de
tabeller som då fortfarande finns.

**Tidigare kvar innan SQL-graftabellerna får droppas:** migration av befintliga fakta (gamla
semantiska nycklar → källförankrade), ombyggnad av Tantivy-indexet efter de nya nycklarna,
och paritet på källförekomstnivå. `graph_v2/write.py` har fortfarande kvar sin gamla
domarväg, men produktionen går via OverGraph.

### Paritetskontroll (byggd)

`knowledge/verify_graph_parity.py` kontrollerar före droppen:

- **identitet/scope/värde** per claim mot `Claim`-noden,
- **temporalitet**: `superseded_at` ⇒ `status="superseded"` i grafen, annars `active`,
- **`SUPPORTED_BY`**: varje SQL-länk måste finnas som grafstöd (flera stöd per claim testas),
- **`ANSWERED_BY`**: claim + fråga måste ha en grafkant med samma `research_need_id`,
- **entiteter och observationer** måste finnas som noder,
- **relationer**: rätt kantetikett per relation, endpoints i grafen,
- **proveniens**: evidensens dokumentversion finns på `ClaimEvidence`.

Rapporten ger `verified`, `mismatches` och ett **fingerprint** över tabellräkningarna.
Regressioner: paritet passerar för en claim med **två** stöd; en legacy-rad utan grafnod
rapporteras som avvikelse i stället för att tyst godkännas.

## 7. Verifiering av uppgraderingsflödet (åtgärdat)

`191_drop_text_units` **blockerar inte längre** en uppgradering. Tidigare avbröt den när
`text_units` innehöll rader, vilket hade stoppat befintliga utvecklingsdatabaser som
fortfarande bar den retired dual-write-spegeln.

Ny ordning: rader kopieras till `text_units_dropped` / `shared_text_chunks_dropped` innan
tabellerna droppas, och `python -m app.services.knowledge.backfill_text_units` spelar upp dem
i OverGraph. Att uppgraderingen lyckas bevisar **inte** att data finns i grafen, så replayen
verifierar tre steg innan backupen får tas bort:

1. **innehållshash** — varje rads `content_hash` måste vara `sha256` av den lagrade texten,
2. **upsert** — raden skrivs till kunskapskatalogen,
3. **återläsning** — raden läses tillbaka från OverGraph och jämförs fält för fält
   (`text`, `content_hash`, `document_id`, `document_version_id`, `ordinal`, `section_id`,
   `locator`).

`--drop-backup` **vägrar** köra om inte varje rad passerat alla tre stegen; annars kastas ett
fel och backuptabellerna ligger kvar. Ingen tyst dataförlust.

```sh
uv run python -m app.services.knowledge.backfill_text_units              # replay + verifiering
uv run python -m app.services.knowledge.backfill_text_units \
  --drop-backup --expect-fingerprint <fingerprint från verifieringen>
```

Rapporten skriver ut `rows`/`replayed`/`verified`/`verified_completely`/`mismatches` samt
`database`, `catalog` och `fingerprint`.

**Fingeravtrycket är ett komplement — inte beviset.** En ny katalog på samma sökväg kan ge
samma avtryck, eftersom avtrycket bygger på sökväg och radinnehåll, inte på katalogens identitet.
Det som faktiskt bevisar att datan finns är därför den **färska återläsningen i samma kommando
som borttagningen**: `--drop-backup` verifierar alltid mot den graf som är öppen just då och
vägrar om någon rad inte kan läsas tillbaka korrekt. Avtrycket används bara för att kunna binda
en tidigare verifiering till samma databas/katalog och upptäcka att grafen eller backupen bytts.

**Bindning till just den databasen och katalogen.** Verifieringen är alltid knuten till den
aktuella körningen: raderna läses från den databas som uppgraderas, och återläsningen sker mot
den katalog som öppnas i samma kommando. `fingerprint` = `sha256` över databasens URL
(lösenordsmaskerad), katalogens katalogsökväg och de verifierade `(unit_id, content_hash)`-paren.
En tidigare lyckad körning räcker alltså aldrig som bevis: har grafen bytts ut eller
backupraderna ändrats blir fingeravtrycket ett annat. Med `--expect-fingerprint` vägras
`--drop-backup` om avtrycket inte matchar den aktuella databasen och katalogen — även om
raderna skulle verifiera sig mot en annan graf.

Regressionstester:
`tests/test_alembic_graph_reconcile.py::test_existing_text_units_are_preserved_when_the_sql_mirror_is_dropped`
(uppgraderingen bevarar rader) samt `tests/test_backfill_text_units.py` (verifierad replay,
hash-avvikelse, saknad chunk-text, att `--drop-backup` vägras före verifiering, att ett inaktuellt
fingeravtryck behåller backupen, att ett färskt fingeravtryck tillåter droppen, och att
fingeravtrycket ändras med katalogsökväg, databas och radinnehåll).
