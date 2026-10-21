# Fas 1 — Arkitekturgranskning: OverGraph som auktoritativ kunskapsgraf + Tantivy som sökindex

**Status:** För granskning (Fas 1). Ingen produktionskod och inget databasschema har ändrats.
**Omfattning:** inventering av faktisk implementation, funktionsinventering av
`overgraph==0.17.0` och `tantivy==0.26.2`, förslag på graf-/indexmodell, konsistensstrategi,
blockerare, benchmarkplan och PR-steg.

Detaljerade inventeringar med radnummerhänvisningar finns som bilagor:

- [01 — SQL-lagret](architecture-review/01-sql-layer.md)
- [02 — OverGraph 0.17.0](architecture-review/02-overgraph-capabilities.md)
- [03 — Tantivy 0.26.2](architecture-review/03-tantivy-capabilities.md)
- [04 — Jev-verifieringskedjan](architecture-review/04-jev-chain.md)
- [05 — Kvarvarande SQL-kunskapsgraf (steg 1-inventering)](architecture-review/05-legacy-graph-inventory.md)

---

## 0. Sammanfattning och beslutspunkter

**Slutsatsen är att målarkitekturen är genomförbar med den redan installerade
programvaran.** OverGraph 0.17.0 är en betydligt mer kapabel motor än vad den tidigare
godkända specen ([`docs/specs/overgraph-knowledge-engine.md`](specs/overgraph-knowledge-engine.md))
antog — den har exakta sekundärindex, atomiska skrivtransaktioner, WAL-hållbarhet och
paginering. Tantivy 0.26.2 täcker allt specen kräver av sökprojektionen utom två
bindningsbegränsningar (facet-frågor och BM25-inställning), som inte är blockerande.

**Beslut: D1–D3 är godkända** med de justeringar som beskrivs nedan.

| Id | Beslut | Godkänd riktning |
|---|---|---|
| **D1** | Var görs *exakta* egenskapsuppslag (property lookup)? | **OverGraph sekundärindex** (auktoritativt, inget synk-fönster). Tantivy = fulltext + lexikal sökning **enbart** — inget separat Tantivy-egenskapsindex. Se §4.4. |
| **D2** | Verifieringsstatus som nod? | **Separata `Claim`- och `VerificationObservation`-noder.** Observationerna omfattar **både** discovery-kandidat och Jev-verifikation (stabil identitet per dokumentversion + egenskap), så `UNSUPPORTED`/`UNDECIDED` och obehandlade kandidater förblir inventerbara. Aldrig supersession för misslyckad verifiering. Se §4.2. |
| **D3** | Var går gränsen SQL↔OverGraph? | **TextUnits, claims, juridiska observationer och relationer ägs av OverGraph** (ingen permanent SQL-spegel). SQL behåller enbart dokumentmetadata/ägarskap, lagrade originalfiler och orkesteringsköer. Se §9. |

### Fas 2 — status

Fas 2 är påbörjad. **PR-steg 1 och 2 är implementerade och testade** (ingen
SQL-avveckling ännu; återställning/konsistens testas enligt §6 innan dess):

- **Steg 1** — nodmodellen `Claim`/`VerificationObservation` + etiketter + sekundärindex
  + scope-isolerad, keyset-paginerad exakt lookup:
  [`backend/app/services/overgraph/claims.py`](../backend/app/services/overgraph/claims.py),
  tester [`backend/tests/test_overgraph_claims.py`](../backend/tests/test_overgraph_claims.py).
- **Steg 2** — auktoritativ persistens flyttad till OverGraph och pipelinen omslagen:
  [`backend/app/services/document_properties/graph_persistence.py`](../backend/app/services/document_properties/graph_persistence.py)
  + `pipeline.discover_and_verify` skriver nu `Claim`/`VerificationObservation`-noder
  (SQL-läsväg för TextUnits behålls till cutover). Tester:
  [`backend/tests/test_document_properties_graph_persistence.py`](../backend/tests/test_document_properties_graph_persistence.py)
  och uppdaterad [`test_document_properties_pipeline.py`](../backend/tests/test_document_properties_pipeline.py).
- **Steg 3** — Tantivy fulltextindex (härledd, återskapbar) med svensk analys, BM25,
  tenant-/dokumentfilter och deterministisk keyset-paginering:
  [`backend/app/services/tantivy_index.py`](../backend/app/services/tantivy_index.py)
  (beroende `tantivy==0.26.2` tillagt i `backend/pyproject.toml`). Tester:
  [`backend/tests/test_tantivy_index.py`](../backend/tests/test_tantivy_index.py).
- **Steg 4** — inventerings-API exponerat: `GET /document-properties/lookup` med
  scope-isolerad exakt lookup, `value`-filter, separation supported/candidates och
  keyset-paginering:
  [`backend/app/api/document_properties.py`](../backend/app/api/document_properties.py)
  + `graph_persistence.lookup_document_properties` (paginerad `PropertyLookup`). Tester:
  [`backend/tests/test_document_properties_api.py`](../backend/tests/test_document_properties_api.py).
- **Steg 5** — konsistens/staleness: inkrementell `reconcile` (läser TextUnits med
  `updated_at > watermark` direkt från OverGraph, idempotent delete-then-add),
  watermark-persistens (`watermark.json`) och `pending_updates`-stalenessdetektering:
  [`backend/app/services/tantivy_index.py`](../backend/app/services/tantivy_index.py).
  Tester i [`backend/tests/test_tantivy_index.py`](../backend/tests/test_tantivy_index.py).
- **Steg 6 (del 1)** — återställningstestet (§6.1-gaten) implementerat och grönt:
  `Catalog.snapshot` (quiesce → `flush()`/`sync()` → kopiera), `Catalog.scrub`
  (integritetskontroll) och testet som skriver noder/kanter/vektorer/index, återställer
  i en ny katalog och verifierar:
  [`backend/tests/test_overgraph_backup.py`](../backend/tests/test_overgraph_backup.py).
- **Steg 6 (del 2, skrivsidan)** — domän→OverGraph-mappning för TextUnits klar och
  **wire:ad in i canonical ingest**: `persist_extracted_source` skriver nu TextUnit-noder
  (text/struktur, utan vektor för att undvika dimensionsberoende) till OverGraph efter
  SQL-commit:
  [`backend/app/services/overgraph/text_units.py`](../backend/app/services/overgraph/text_units.py),
  [`backend/app/services/knowledge/canonical_ingest.py`](../backend/app/services/knowledge/canonical_ingest.py).
  Tester: [`backend/tests/test_overgraph_text_units.py`](../backend/tests/test_overgraph_text_units.py)
  + [`test_text_units.py::test_ingest_writes_text_units_to_overgraph`](../backend/tests/test_text_units.py).
- **Steg 6 (del 3, lässidan — klar)** — alla display-/navigerings-/grounding-läsare är nu
  migrerade till OverGraph (hydrering av TextUnit-text/locator/sektion; `stored_objects`-
  åtkomstkontrollen stannar i SQL): `document_properties.pipeline`,
  `knowledge/document_grounding.py`, `knowledge/shared_document_grounding.py`,
  `api/workspace_chats.py`, `services/document_navigation.py` (+ `TextUnitView.section_id`).
  Kvarvarande SQL-`TextUnitRecord`-användning är enbart **skrivare**
  (`canonical_ingest`/`graph_v2`-projektion/`index repair`) och **legacy claims/relationships**,
  som avvecklas i steg 8.
- **Steg 8 (del 1, klar — `text_units`/`shared_text_chunks`)** — SQL-spegeln är **borttagen**:
  ingen dual-write, `shared_chunks`/`chunk_guards`/SQL-modellerna borta, alla kvarvarande
  arbetsflöden (document-QA, kunddokument-räkning/purge, live-speech-STT, dokumentborttagning,
  claim_rekey, live-integrationsskript) migrerade, ~25 testfiler seedar/läser OverGraph och
  Alembic-migreringen [`191_drop_text_units`](../backend/alembic/versions/191_drop_text_units.py)
  är head. Detaljer i §11.1. Kvar: legacy claims + Graph v2-mirror (§11.2).

### Två beslut som verifierades empiriskt under PR-steg 1

1. **Exakt property-lookup i OverGraph** fungerar via `query_nodes` med
   `label_filter` (scope-isolering före filtrering) + filter-DSL
   `{"and":[{"property":"class_id","eq":…},{"property":"value","eq":…}]}` +
   keyset-paginering (`limit`/`after`). Sorteringen är `node_id_asc` (enda giltiga
   `order_by`; ingen offset-paginering). Sekundärindex byggs asynkront
   (`building→ready/failed`) men fråge-API:et är indextransparent — korrektheten
   beror inte på indexstatus.
2. **Claim-identitet måste vara versionsscopad** (innehåller `document_version_id`)
   för att uppfylla spec §5.3 ("en ändrad dokumentversion får inte ärva tidigare
   verifierade egenskaper"). Detta **avviker** från dagens SQL-`_claim_value`
   (dokumentscopad, `document_properties/persistence.py:50-57`); cutover rekey:ar.

---

## 1. Nuvarande kunskapsarkitektur och dataflöden

Dagens läge är exakt det tvålagers-läge specen beskriver: **SQL är auktoritativ källa** för
claims/relationer/observationer/TextUnits och för en hel Graph v2-egenskapsgraf som
*speglar* OverGraph; **OverGraph är en härledd sökprojektion**.

### 1.1 Var kunskapsmodellerna ligger (SQL)

Kunskapsmodellerna är spridda över sex moduler, inte bara `models.py`
([01 §0](architecture-review/01-sql-layer.md)):

| Modul | Tabeller |
|---|---|
| `database/models.py` | `knowledge_claims`, `knowledge_claim_text_units`, `knowledge_claim_answers`, `knowledge_entities`, `knowledge_relationships`, `knowledge_graph_events`, `canonical_documents`, `document_versions`, `document_sections` |
| `database/text_units.py` | `text_units`, `shared_text_chunks` |
| `database/knowledge_observation.py` | `knowledge_observations` |
| `database/answer_review.py` | `knowledge_answer_reviews` |
| `database/graph_v2.py` | `graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations`, `graph_fact_question_dependencies`, `graph_ingest_work`, `graph_embedding_cache` |

### 1.2 Identiteter, scope, temporalitet (kondenserat)

- **Claim-identitet** = `SHA-256(scope_key · predicate.strip() · canonical_json(normalize_assertion(value)))`
  (`services/knowledge/identity.py:67-76`). `knowledge_claims.predicate` saknar index —
  indexet `(document_id, predicate)` togs bort i migration `126_knowledge_claim_source_independence.py`.
- **TextUnit-identitet** = `SHA-256(document_version_id · locator · content_hash)` (`units.py:25-32`).
- **Scope/tenant** styrs centralt i `database/knowledge_scope.py`: `scope_type ∈ {shared, customer}`,
  `scope_key ∈ {shared, customer:{id}}`, fail-closed, DB-CHECK + ORM-lyssnare
  ([01 §7](architecture-review/01-sql-layer.md)).
- **Supersession/temporalitet**: claims har `superseded_at`/`successor_id`; dokumentversioner har
  partiellt unikt index `document_id WHERE superseded_at IS NULL` (högst en aktuell version).
  Revalideringsköer är **redan borttagna** (migration `142` och `190`); endast answer-review-TTL
  (`knowledge_answer_reviews`) återstår, som separat CLI-worker där Jev körs *utanför* DB-transaktionen.

### 1.3 Dataflöden (skrivväg och läsväg)

**Skrivväg** ([01 §9](architecture-review/01-sql-layer.md)):

1. Canonical-ingest → `persist_segmented_document` skriver dokument/version/sektion/TextUnits;
   `commit()` **före** embedding (anslutningsfrigöring).
2. Research write-back → `persist_extracted_knowledge` → klassificeringsgrind
   (`domain_knowledge` → `knowledge_claims`; `source_quality`/`research_observation` → `knowledge_observations`).
3. Graph-projektionen frikopplas via **outbox + worker**: `graph_ingest_work`-rad
   (`graph_v2/outbox.py`, `FOR UPDATE SKIP LOCKED` + lease + exponentiell retry) →
   `legal_writeback.py` löser fakta/embedding/Jev-dom → `graph_v2/write.py` (SQL-mirror) →
   `overgraph/publish.py` (OverGraph-projektion). `start_graph_owner` kör loopen.

**Läsväg**: den auktoritativa research-läsvägen är redan Graph v2 / OverGraph
(`research/graph_reuse.py` + `answer_graph.py` + `result_store.py`), **inte** legacy-claims
([01 §11](architecture-review/01-sql-layer.md)). Legacy `knowledge_claims`/`relationships`/
`entities`/`claim_answers` är redan frånkopplade från reuse — en stark grund för avveckling.

### 1.4 Ny kod (idag): `services/document_properties/`

Idag lades en ny produktionsmodul till (`discovery.py`, `verification.py`, `local_dense.py`,
`persistence.py`, `pipeline.py`, `taxonomy.py`) som implementerar specens §9-kedja. Den
**persisterar till SQL** (`knowledge_claims` + `knowledge_observations`), i linje med
[`docs/document-property-phase1-design.md`](document-property-phase1-design.md) (D1/D3). Det
är denna persistens som Fas 2 ska flytta till OverGraph, och vars lookup som ska byta från
"SQL-uppslag på `predicate`" (den äldre D3-rekommendationen) till Tantivy/OverGraph-index.

---

## 2. Funktionsinventering — OverGraph 0.17.0

Fullständig verifiering mot installerad `__init__.pyi` (1899 rader), `async_api.py`,
vendor-`METADATA`, kompilerad modul och produktionswrappern i
[`02-overgraph-capabilities.md`](architecture-review/02-overgraph-capabilities.md).

### 2.1 Snabbverdict

| # | Förmåga | Verdict |
|---|---|---|
| 1 | Persistent lagring (katalog, LSM + WAL + manifest + segment) | ✅ |
| 2 | Noder/kanter (labels, key, weight, props, dense/sparse-vektor) | ✅ |
| 3 | Nod-/kantattribut (typade skalärer + nästlade, schema valfritt) | ✅ |
| 4 | Exakta uppslag + sekundära egenskapsindex (equality + range) | ✅ (⚠️ async index-build) |
| 5 | Dense + sparse + hybrid vektorsökning | ✅ (❌ ingen encoder, BYO) |
| 6 | Traversering (neighbors/BFS/PPR/top-k/shortest path) | ✅ |
| 7 | Relationer mellan godtyckliga nodtyper | ✅ |
| 8 | Batchskrivning (`batch_upsert`, `graph_patch`, ingest-mode, group-commit) | ✅ |
| 9 | Uppdatering/borttagning (upsert/delete/invalidate/prune) | ✅ |
| 10 | Samtidiga läsningar/skrivningar | ⚠️ enkelprocess, enkel skrivare |
| 11 | Backup/återställning | ⚠️ endast `cp -r` (ingen snapshot-API) |
| 12 | Export/import | ⚠️ endast adjacency-export, ingen import |
| 13 | Transaktioner/ACID | ⚠️ atomisk commit + WAL; **ingen MVCC-snapshot** |
| 14 | Kantunicitet/nycklar/validitet/vikt | ✅ unik `(from,to,label)`; ingen stabil kantnyckel/embedding |
| 15 | Label/scope-filter i vektorsökning | ✅ label-filter; ⚠️ ingen property-filter i `vector_search` |
| 16 | Async-API | ✅ (`asyncio.to_thread`-spegel) |

### 2.2 De viktigaste verifierade fakta

- **Exakta uppslag finns nativt.** `get_node_by_key(label, key)` (`__init__.pyi:1261`),
  `get_edge_by_triple(from,to,label)`, `find_nodes(label, prop_key, prop_value)`, samt
  **deklarerade sekundärindex** `ensure_node_property_index`/`ensure_edge_property_index`
  (`kind: "equality"|"range"`, enkel + compound, `__init__.pyi:1356-1361`). Detta motsäger
  delvis specens "anta inte"-varning: 0.17.0 *har* exakta egenskapsindex.
- **Paginering utan top-k finns nativt**: `find_nodes_paged`, `query_node_ids` (`IdPageResult`),
  `traverse(..., cursor=...)`, `neighbors_paged` m.fl. (`__init__.pyi:1529-1547`).
- **Transaktioner finns, men inte full ACID.** `begin_write_txn()` → `WriteTxn` med
  `stage`/`rollback`/atomisk `commit`/optimistisk konfliktdetektering (`__init__.pyi:1607-1668`),
  plus WAL-hållbarhet (`sync()`, `wal_sync_mode: group_commit|immediate`). **Däremot ingen
  MVCC/read-snapshot och enkel skrivare** — `Isolation` i ACID saknas.
- **Vektorsökning** filtrerar enbart på `label_filter`, inte godtycklig property
  (`__init__.pyi:1588-1605`) — precis som den godkända specen kräver. Property-filtering görs
  i en separat index-/query-sökning (`find_nodes`/`find_nodes_range`) eller post-filter.
- **Gap som kräver arbete** (se §5): backup/snapshot-API, full export/import, MVCC/snapshot,
  multi-process-access, sparse-encoder. Produktionswrappern deklarerar **inga** sekundärindex
  idag (`catalogs.py` använder bara `get_node_by_key`).

### 2.3 mem0-integration

OverGraph agerar `VectorStoreBase`-adapter åt `mem0ai==2.0.20` (minneskatalogen 1536-d,
`mem0_patch.py` + `mem0_store.py`). Detta påverkas inte av att kunskapsgrafen flyttas till
OverGraph — minnet fortsätter i sin egen katalog (`OVERGRAPH_DIR/memory`).

---

## 3. Funktionsinventering — Tantivy 0.26.2

Fullständig verifiering i [`03-tantivy-capabilities.md`](architecture-review/03-tantivy-capabilities.md).

### 3.1 Verdict mot specens 10 krav (§4.3)

| Krav | Status |
|---|---|
| Exakta uppslag på typade fält | ✅ `Query.term_query` på text/i64/u64/f64/bool/date/bytes/json/ip; sträng-exakt via `tokenizer_name="raw"` |
| TermQuery + BooleanQuery | ✅ `term_query`, `term_set_query`, `boolean_query` (`Occur.Must/Should/MustNot` + `minimum_number_should_match`) |
| Fulltext + BM25 | ✅ default-BM25; ⚠️ ingen scoring/k1/b-inställning |
| Svenska analyzers/tokenisering | ✅ `Filter.stemmer("swedish")` (Snowball) + `Filter.stopword("swedish")` |
| Filtrering på dokument/tenant | ✅ `range_query` + boolean `Must`-filter (experimentet använde raw-text-fält + `term_query`) |
| Stabil paginering med bestämd sortering | ✅ `Searcher.search(offset, order_by_field, order, count)`; experimentet använder egen app-kursor (se 3.2) |
| Indexering + borttagning | ✅ `add_document`, `commit`, `rollback`, `delete_documents_by_term/by_query` |
| Commit + reader refresh | ✅ `commit()` (opstamp), `reload()`, `config_reader(reload_policy="commit")` |
| Flera samtidiga läsare | ✅ snapshot-modell (single-writer/multi-reader); bindningen dokumenterar inte trådsäkerhetskontrakt |
| Återskapande från OverGraph | ✅ redan implementerat atomiskt: bygg i temp-dir → `os.replace` ([03 §Q10](architecture-review/03-tantivy-capabilities.md)) |

### 3.2 Python-bindningens begränsningar vs. Rust (viktigaste)

1. Ingen `facet_query`/`facet_prefix_query` — hierarkisk facet-filtrering är inte förstklassig
   (tenant/dokument-filter måste använda typade fält eller raw-text-fält, vilket experimentet redan gör).
2. Ingen custom scoring / `Similarity` / k1-b-tuning — BM25-parametrar är låsta.
3. Ingen `IndexReader`/`TopDocs`-klass; `Searcher`/`SearchResult` ersätter dem
   (`SearchResult.count` används vid körning men saknas i stubben — ett typningsgap).
4. Inga custom Rust-tokenizers, ingen merge-policy/segment-kontroll, inga mmap-inställningar.
5. Full lista: [03 §5](architecture-review/03-tantivy-capabilities.md).

### 3.3 Fryst BM25-v1-resultat (redan mätt)

Från [`experiments/overgraph_ingest/eval/tantivy-bm25-v1.md`](../experiments/overgraph_ingest/eval/tantivy-bm25-v1.md):

- **Fristående BM25 är svagast** (DocR@20 28,3 %, DocR@50 38,6 %) — bekräftar att BM25 inte är en
  ersättning för dense.
- **Dense+BM25** (49,6 % R@20) slår dense (39,7 %) men förlorar mot `hybrid_current` (57,0 %)
  och förlorar dokument-lokalt (CE@5 71,4 % vs 98,7 %).
- **Latens (varm):** BM25 p50 ~1 ms vs dense ~11–12 ms; indexbygge ~0,67 s / 1,3 MB för 2 548 TextUnits.
- Slutsats `mixed`, `tuned_on_gold=false`, ingen produktionsändring. **Detta är exakt den
  separation specen vill ha: Tantivy som snabb, exakt/lexikal motor — inte som rankingmodell.**

---

## 4. Föreslagen graf- och indexmodell

### 4.1 Grafmodell (OverGraph — auktoritativ)

Återanvänder befintliga identiteter (§1.2) och den label+key-modell OverGraph redan kräver.
Inga nya nod-/kanttyper där en befintlig redan löser uppgiften.

```
DocumentVersion (key=document_version_id, labels=[DocumentVersion, scope.*])
   ├── CONTAINS ─────────► TextUnit (key=text_unit_id, labels=[TextUnit, scope.*])
   │                          props: text, content_hash, document_id, document_version_id,
   │                                 section_id, ordinal, locator, page/char-offsets
   │
   └── HAS_CLAIM ────────► Claim (key=claim_identity, labels=[Claim, scope.*])
                              props: class_id, value, polarity, taxonomy_version,
                                     document_id, document_version_id
                              ▲  SUPPORTS (TextUnit → Claim; flera TextUnits kan stödja samma claim)
                              └── CONTRADICTS ──► Claim
```

Kopplingar till specens krav:

- **Claim vs. verifieringsobservation hålls åtskilda** (spec §5.2). `SUPPORTED` → `Claim`-nod
  med evidenskanter till den versions TextUnits. `UNSUPPORTED`/`UNDECIDED` och discovery-kandidaten
  → **`VerificationObservation`-nod** (proveniens: vilken evidens Jev bedömde, `verification_version`,
  tidpunkt, `reason_code`) — **inte** ett negativt claim och **inte** supersession av ett claim.
- **Evidenskanten återanvänder `SUPPORTS`** (TextUnit → Claim), samma riktning och etikett som
  dagens `attach_sources` (TextUnit → Fact, `write.py:183`). Specens `SUPPORTED_BY` motsvarar
  SQL-relationen `knowledge_claim_text_units.relation=SUPPORTED_BY`; i grafen är det samma semantik
  med OverGraphs befintliga etikett.
- **Dokumentversioner särskiljs** som separata `DocumentVersion`-ankarnoder. En ändrad version får
  en ny ankarnod; dess claims måste stödjas av den nya versionens TextUnits. Ingen automatisk
  ärvning av verifierade egenskaper — **claim-identiteten (värdet) innehåller `document_version_id`**
  (`claims.py:claim_value`), så en ny version ger ett nytt claim. Detta avviker från dagens
  dokumentscopade SQL-`_claim_value` och rekey:as vid cutover.
- **Scope/tenant i labeln före top-k**: `scope.shared` / `scope.customer.{id}` (befintlig konvention
  i `overgraph/catalogs.py`, `scope_label`), i enlighet med den godkända specen.
- **Proveniens**: `SUPPORTS`-kanten bär `props` med käll-/verifieringsmetadata (motsvarande dagens
  `knowledge_claim_text_units.relation=SUPPORTED_BY` och Graph v2:s `graph_fact_sources`).

### 4.2 Verifieringsstatus som separat nod (beslut D2)

`VerificationObservation`-noden bär `observation_class`, `kind`, `class_id`, `value`,
`polarity`, `taxonomy_version`, `document_id`, `document_version_id`, `statement`,
`source_unit_keys` och (vid verifiering) `decision`, `verification_method`,
`verification_version`, `reason_code`. Den täcker **två** observerade tillstånd med
stabil identitet per dokumentversion + egenskap (`knowledge_observation_id`):

- **Discovery-kandidat** (`kind=document_property_candidate`) — så att *samtliga*
  deterministiskt identifierade kandidater förblir inventerbara **innan** Jev verifierat dem.
- **Jev-verifiering** (`kind=document_property_verification`) — `SUPPORTED|UNSUPPORTED|UNDECIDED`,
  aldrig ett negativt claim.

Detta motsvarar exakt dagens `knowledge_observations` och håller claim-identiteten ren
(verifieringsstatus får inte ingå i claim-identitet — [`04 §2`](architecture-review/04-jev-chain.md)).
`SUPPORTED` → `Claim`-nod (plus en verifierings-observation som spår); `UNSUPPORTED`/`UNDECIDED`
→ enbart observationer. En `UNSUPPORTED`-skrivning är en *ny observation*, aldrig supersession
av ett befintligt claim.

### 4.3 Tantivy-indexmodell (härledd, återskapbar)

Två logiska index (separata eller samma, tekniskt valfritt — rekommenderas separata för olika
analyzers/typer):

**TextUnit-index** (fulltext/BM25/lexikal kandidat):

| Fält | Typ | Anmärkning |
|---|---|---|
| `tenant_id` | raw-text (eller u64/facet) | filter |
| `document_id` | raw-text | filter |
| `document_version` | raw-text | filter |
| `text_unit_key` | raw-text | exakt identifiering |
| `structure_id` | raw-text | struktur |
| `text` | text (position, sv-analyser) | BM25-yta |
| `content_hash` | raw-text | integritet |

**Property-index** — **avstår** (D1 godkänd: exakt property-lookup görs i OverGraph
sekundärindex, inte i Tantivy). Redovisas här endast som dokumenterad alternativväg om
läslast/latens senare motiverar en frikopplad projektion:

| Fält | Typ | Anmärkning |
|---|---|---|
| `tenant_id` | raw-text | filter |
| `document_id` | raw-text | filter |
| `document_version` | raw-text | filter |
| `claim_id` / `candidate_id` | raw-text | identitet |
| `class_id` | raw-text | exakt `term_query` |
| `value` | typat (bool/sträng) | exakt match |
| `polarity` | raw-text | filter |
| `verification_state` | raw-text | **projicerad från grafen** |
| `taxonomy_version` | raw-text | filter |

Om den någonsin byggs projiceras `verification_state` alltid från grafens claims+observationer
och är **aldrig** en andra sanning (§6.2). Indexet är en ren projektion som byggs om helt från
OverGraph.

### 4.4 Exakt property lookup — beslut D1 (godkänd)

**Godkänt: OverGraph sekundärindex, ingen Tantivy-egenskapsprojektion.** Exakt lookup görs
i samma skrivning som äger data (inget synk-fönster), uppfyller §8 trivially, och undviker en
andra, fristående sanning för verifieringsstatus.

**Verifierad API-form (empiriskt testad i PR-steg 1):** `query_nodes` med
`label_filter={"labels":[CLAIM, "scope.shared"],"mode":"all"}` (scope-isolering före filtrering) +
filter-DSL `{"and":[{"property":"class_id","eq":…},{"property":"value","eq":…}]}` +
keyset-paginering (`limit`/`after`). `order_by` är `node_id_asc` (enda giltiga värdet; ingen
offset-paginering). Sekundärindex (`ensure_node_property_index`, equality, enkel + compound) byggs
asynkront men fråge-API:et är indextransparent — korrektheten beror inte på indexstatus.

| | OverGraph sekundärindex | Tantivy property-index |
|---|---|---|
| Auktoritativ | ✅ (source of truth) | ❌ (härledd) |
| Synk-fönster | Inget (samma skrivning) | Ja (måste detekteras) |
| "Strikt aktuell" (§8) | Trivialt uppfyllt | Kräver watermark-kontroll |
| Paginering utan top-k | ✅ `query_nodes` keyset | ✅ `offset`+`order_by_field` |
| Decoupling av läslast | Nej (samma process) | Ja |
| Fulltext i samma fråga | Nej | Ja |

Tantivy gör **fulltext/BM25 + svensk lexikal kandidatidentifiering** (§3.2, §3.5) — det som
OverGraph inte kan.

---

## 5. Blockeringar och risker

| # | Blockering/risk | Allvarlighetsgrad | Åtgärd |
|---|---|---|---|
| 1 | **Ingen MVCC/snapshot-isolation** i OverGraph; enkel skrivare, enkelprocess | ⚠️ begränsning, inte blockerare | Befintlig `threading.RLock` + en-runtime-modell räcker; dokumentera att "läs-egen-skrivning inom transaktion" är gränsen |
| 2 | **Backup = `cp -r`**; ingen snapshot-API; ingen full export/import | ⚠️ operativ risk | Bygg rutin: quiesce → `sync()`/`flush()` → kopiera → `scrub()`; bygg en export/import-tool på `batch_upsert_nodes`/`graph_patch` (eller GQL) för katastrofåterställning |
| 3 | **Sekundärindex byggs asynkront** (`building→ready→failed`); planner faller tillbaka på scan | ⚠️ | Vänta på `ready` före indexberoende lookup; använd `get_node_by_key` som alltid exakt |
| 4 | **Ingen sparse-encoder** i OverGraph | ⚠️ (ej kritisk) | Återanvänd experimentets lexikala sparse-encoder (`retrieval/encode.py`, `LexicalSparseEncoder`) eller SPLADE/BGE-M3 om hybrid krävs |
| 5 | **Tantivy bindning**: ingen facet-fråga, ingen BM25-tuning | ⚠️ (ej kritisk) | Filter via typade/raw-fält + `term_query`/`range_query` (bevisat i experimentet) |
| 6 | **Tantivy single-writer** | ⚠️ (ej kritisk) | Indexet är återskapbart; serialisera skrivningar via outbox/worker |
| 7 | **`knowledge_claims.predicate` saknar index** | ℹ️ (blir irrelevant) | Löses av D1: exakt lookup flyttas till OverGraph/Tantivy-index |
| 8 | **Katalog-kollision**: befintlig mem0-`knowledge`-katalog används idag av dokument-Q&A/catalog | ⚠️ | Klargör att den nya auktoritativa claim/TextUnit-grafen läggs i samma `knowledge`-katalog under nya labels (`Claim`, `VerificationObservation`), utan att bryta mem0-`memory`-katalogen |

Ingen av dessa blockerar målarkitekturen; de styr *hur* den byggs, inte *om*.

---

## 6. Konsistensstrategi OverGraph ↔ Tantivy

**Princip: OverGraph är alltid auktoritativ; Tantivy är alltid härledd och återskapbar.**

Återanvänd den befintliga outbox/worker-maskinen (`graph_ingest_work`, lease + retry) som redan
används för Graph v2 → OverGraph-projektionen:

1. **Indexering efter lyckad grafskrivning**: efter atomisk OverGraph-skrivning (inkl.
   `sync()` vid publicerad reuse) enqueues en Tantivy-indexuppgift i en beständig journal
   (`graph_ingest_work`-mönstret) med en monotont växande sekvens/högvattenmärke (OverGraph
   commit-opstamp eller appsekvens).
2. **Uppdatering/borttagning**: worker skriver `add_document` / `delete_documents_by_term`
   (per `text_unit_key`/`claim_id`) mot Tantivy och commitar. Vid borttagning av claim/TextUnit
   tas motsvarande indexpost bort (eller återspeglas via tombstones).
3. **Recovery efter krasch**: journalen återuppspelas (idempotenta nycklar); ett fullt
   indexbygge är alltid möjligt (atomisk `os.replace`, [03 §Q10](architecture-review/03-tantivy-capabilities.md)).
4. **Fel under indexuppdatering**: en misslyckad Tantivy-skrivning lämnar **Tantivy** inaktuellt,
   aldrig OverGraph. OverGraph-skrivningen är redan commitad; indexuppgiften retry:as
   (exponentiell backoff). **En claim/TextUnit kan aldrig existera enbart i Tantivy.**
5. **Indexversion/schemaändring**: Tantivy-schema + OverGraph-schema bär versionsnycklar; byte →
   bygg nytt index och byt atomiskt, aldrig in-place-migrering.
6. **Synkroniseringskontroll (strikt aktuell läsning)**: läsaren jämför Tantivys
   högvattenmärke med OverGraphs aktuella sekvens. Är indexet efter → läsaren (a) markerar
   resultatet som ofullständigt, och/eller (b) faller tillbaka på OverGraph-native exakt lookup
   (D1) — därmed kan ett ofullständigt uppslag aldrig presenteras som fullständigt.
7. **Avstämningsprocess (valfri)**: en periodisk `reconcile` jämför key-set (Tantivy vs
   OverGraph) och bygger om avvikande delar. Ingen permanent SQL-kopia av kunskapsgrafen skapas.

### 6.1 Verifierat återställningstest (gate före SQL-avveckling)

Eftersom OverGraph saknar snapshot-/backup-API måste återställning bevisas innan SQL-spegeln
försvinner. Obligatoriskt test (Fas 2-steg 6/7, innan någon `DROP` av SQL-kunskapsmodeller):

1. Skriv deterministiska grafdata: noder (`Claim`, `TextUnit`, `VerificationObservation`,
   `DocumentVersion`), kanter (`HAS_CLAIM`, `SUPPORTS`, `CONTAINS`, `CONTRADICTS`), props,
   dense-vektorer och sekundärindex.
2. Ta en **konsistent backup**: quiesce skrivningar → `sync()`/`flush()` → `cp -r` katalogen.
3. Återställ i en **ny katalog** (ny path) och `OverGraph.open` på kopian.
4. Verifiera `scrub()` (integritet) + att samtliga noder, kanter, TextUnits, props, vektorer och
   index är läsbara och identiska (key-set + innehåll mot källan).

Testet är en del av acceptanskriteriet "OverGraph kan återställas efter haveri" — inte en
efterhandskontroll.

### 6.2 Krashfönstret: OverGraph-commit ↔ journalregistrering

Ett vanligt retry-flöde räcker inte om processen kraschar **mellan** en commitad
OverGraph-skrivning och journalraden (`graph_ingest_work`) som ska driva Tantivy-uppdateringen —
då finns data i OverGraph men ingen uppgift att retry:a. Lösningen är att göra
**avstämningen till korrekthetens ryggrad, och journalen till en snabbväg**:

- **Källa för sanning = OverGraph själv, inte journalen.** OverGraph exponerar
  `updated_at`/`created_at` (epoch-ms) på varje nod och `find_nodes_by_time_range` /
  `find_nodes_by_time_range_paged`. En `reconcile` läser alla `Claim`/`TextUnit` vars
  `updated_at > sista_högvattenmärke` och (om)indexerar dem i Tantivy. Denna väg överlever
  krashfönstret eftersom den läser direkt från den auktoritativa grafen, inte från en
  eventuellt-aldrig-skriven journalrad.
- **Journalen (outbox) är en latensoptimering**, inte en sanning: efter commit enqueue:as en
  indexuppgift med samma sekvens. Tappas uppgiften i krashfönstret fångar `reconcile` upp den
  via `updated_at`-scannet — **idempotent** (key-baserad `add_document`/`delete_documents_by_term`).
- **Idempotens + at-least-once**: både outbox-replay och `reconcile` är idempotenta på
  TextUnit-/claim-nycklar, så dubbelkörning är ofarlig.
- **Strikt aktuell läsning** jämför Tantivys högvattenmärke med OverGraphs maximala `updated_at`;
  vid eftersläpning markeras resultatet ofullständigt eller faller tillbaka på OverGraph-native
  lookup (D1).

Detta uppfyller spec §8:s krav att "en indexuppdatering som misslyckas aldrig får göra Tantivy
till den enda plats där ett claim eller en TextUnit existerar", och att systemet kan **upptäcka**
att indexet inte är ikapp.

---

## 7. Benchmarkplan

Mät mot befintliga syntetiska avtalskorpusar och frysta facit (experimentets baselines,
`experiments/overgraph_ingest/baselines/`). Redovisa **varm sökning** och **total tid inkl.
synkronisering** separat.

| Mått (§10) | Hur mäts | Befintligt referensvärde |
|---|---|---|
| Ingesthastighet TextUnits/claims | `batch_upsert_nodes` / `graph_patch` genomströmning | experimentets `GraphWriter` |
| Grafskrivningar/sek | `begin_write_txn` vs batch; group_commit | vendor: 1,29 M+ noder/s batch |
| Exakt property lookup | OverGraph `find_nodes_paged` (D1) vs Tantivy `term_query` | — (ny) |
| Fulltextsökning | Tantivy BM25 varm | p50 ~1 ms (varm, 2 548 TextUnits) |
| Dense retrieval | OverGraph `vector_search` | p50 ~11–12 ms |
| Traversering av evidensrelationer | `neighbors_batch`/`traverse`/`extract_subgraph` | — (ny) |
| Hydrering av originaltext | `get_nodes_by_keys` + SQL `stored_objects` | — (ny) |
| Paginering stora mängder | OverGraph paged vs Tantivy offset/cursor | experimentet: 20-sidor utan dup |
| Claim→sökbart index (lag) | watermark-delta efter skrivning | — (ny) |
| Minne/disk | `DbStats`/`stats()` + katalogstorlek | — (ny) |
| Recovery + full rebuild | journalreplay + Tantivy `os.replace`-bygge | indexbygge ~0,67 s/1,3 MB |
| End-to-end inventering | discovery→Jev→lookup→hydrera | kedja p50 258 ms / p95 560 ms (Jev-dom) |

**Kvalitetskrav**: frys samma gold innan mätning; kvaliteten ska vara oförändrad eller bättre.
Jev-beslutssemantiken får inte ändras (verifierat oförändrad i [04 §8](architecture-review/04-jev-chain.md)).

### 7.1 Resultat (första körning, föreslagen arkitektur)

Benchmark-verktyget [`backend/scripts/benchmark_overgraph_tantivy.py`](../backend/scripts/benchmark_overgraph_tantivy.py)
mäter de nya primitiven på en syntetisk korpus (5 000 TextUnits + 5 000 claims, dim=16):

| Mått | Värde |
|---|---|
| Grafinmatning (10 000 noder, sekventiell) | 0,18 s |
| Fulltext-index rebuild (5 000 TextUnits) | 0,63 s |
| Reconcile (full scan, watermark=0) | 3,2 s |
| Exakt lookup `class_id AND value` | p50 2,4 ms / p95 3,1 ms |
| Exakt lookup `class_id` (enbart) | p50 1,0 ms / p95 1,5 ms |
| Fulltext BM25 (varm) | p50 0,008 ms / p95 0,011 ms |
| Disk: OverGraph-katalog | 2,5 MiB |
| Disk: Tantivy-index | 283 KiB |

**Tolkning och reservationer:**

- Fulltext BM25 (8 µs) och index-rebuild (0,63 s) matchar experimentets frysta siffror
  (BM25 ~1 ms, indexbygge ~0,67 s/1,3 MB) och bekräftar Tantivys värde som lexikal motor.
- Exakt lookup (~1–2,4 ms) är **utan** färdigbyggt sekundärindex (index byggs asynkront;
  fråge-API:et faller tillbaka på label-scopad scan tills indexet är `ready`). Den siffran
  är alltså scan-vägen, inte den indexerade vägen — med `ready` sekundärindex förväntas
  lägre latens. Reconcile (3,2 s full scan) är en bakgrundsoperation, inte en hot path.
- Detta är **varm sökning** (uppvärmd index/reader); total tid inkl. synkronisering och
  jämförelse mot befintlig SQL/experiment-miljö återstår när cutover är klar.

---

## 8. Implementationsplan (PR-steg, Fas 2)

Fas 2 påbörjas först efter att denna granskning godkänts. Stegen är ordnade så att varje PR
levererar ett testbart tillstånd och ingen produktionskod byts innan ersättningen är testad.

1. **OverGraph-schema + sekundärindex (utan produktionsändring):** wire `ensure_node_property_index`
   för `Claim` (`class_id`+`value`) och `TextUnit` (`content_hash`), scope-labels. Enhetstester mot
   en temporär katalog. *(Verifierar gap #3 och #7.)*
2. **Claim/observation-persistens → OverGraph (auktoritativ):** flytta `persist_supported_property`
   och kandidat-/verifieringsobservationer från `knowledge_claims`/`knowledge_observations` till
   `Claim`/`VerificationObservation`-noder + `SUPPORTED_BY`-kanter; behåll outbox för Tantivy.
   Reuse-läsväg via `get_node_by_key`. Tester inkl. 1-anslutningspool (DB-fri Jev-anrop).
3. **Tantivy TextUnit-index (härledd fulltext):** bygg `text_unit`-index från OverGraph
   (`retrieval/bm25.py`-mönstret) med svensk analyzer; outbox-drivet, atomisk rebuild.
4. **Inventerings-API (exakt lookup + paginering):** D1-lösningen (OverGraph `find_nodes_paged`
   som auktoritativ + Tantivy fulltext för lexikal kandidat) + `verification_state`-projektion
   från grafen; `include_candidates`-separation (SUPPORTED vs ej verifierad).
5. **Konsistens + staleness:** watermark/högvattenmärke, `reconcile`, fail-closed vid eftersläpning.
6. **Cutover av läsare:** peka research/dokumentegenskaps-läsare på OverGraph; ta bort Graph v2-mirror
   och legacy claims-läsare enligt §9.
7. **Benchmark + regression:** kör §7-planen mot frysta facit; lås siffror.
8. **Avveckling + städning:** drop SQL-kunskapsmodeller (D-listan), uppdatera tester/dokumentation.

---

## 9. Migrering och avveckling av SQL

Sammanfattning av [01 §12](architecture-review/01-sql-layer.md). Legend: **D** = avveckla
(flytta auktoritativ lagring till OverGraph), **K** = behåll i SQL (applikationsdata/orkestrering).

Gränsen är tydlig: **dokumenthantering vs kunskapsgraf.** Dokumentmetadata, ägarskap, lagrade
originalfiler och orkesteringsköer stannar i SQL; TextUnits, claims, juridiska observationer och
relationer ägs av OverGraph — **ingen permanent SQL-spegel**.

| Område | Verdict |
|---|---|
| `knowledge_claims`, `knowledge_claim_text_units`, `knowledge_claim_answers` | **D** — legacy assertionslager; ingen research-läsväg konsumerar dem |
| `knowledge_entities`, `knowledge_relationships` | **D** — ersatta av Graph v2/OverGraph-noder/-kanter |
| `graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations`, `graph_fact_question_dependencies` | **D** — SQL-spegeln av OverGraph (samma identitetsformler) |
| `text_units`, `shared_text_chunks` | **D** — text + citatidentitet + locator flyttar till OverGraph `TextUnit`-noder; SQL behåller struktur/åtkomst via `document_versions`/`document_sections`/`stored_objects`, inte som text-kopia |
| `knowledge_observations` | **D** — flyttar till OverGraph `VerificationObservation`-noder |
| `canonical_documents`, `document_versions`, `document_sections` | **K** — dokumentmetadata/ägarskap/versionering (inte kunskapsgraf) |
| `knowledge_graph_events` | **K** — append-only audit |
| `graph_ingest_work`, `graph_embedding_cache`, `knowledge_answer_reviews` | **K** — orkestrering/cache/TTL, inte kunskapslagring |

Inga bakåtkompatibilitetslager byggs. Avveckling sker inom samma förändringsarbete, efter att
ersättningen är testad **och** återställnings-/konsistenstesten i §6.1–6.2 är gröna
(Fas 2 steg 6/8).

---

## 10. Svar på acceptanskriterierna (§13)

1. **Kan OverGraph vara auktoritativ lagring för claims/observations/relationships/TextUnits?**
   Ja — noder/kanter med stabila nycklar, typade props, sekundärindex, atomiska skrivtransaktioner,
   WAL-hållbarhet och paginering är verifierade i 0.17.0 ([02](architecture-review/02-overgraph-capabilities.md)).
2. **Vilka persistens-/konsistensgarantier gäller?** Atomisk commit + rollback + WAL-hållbarhet
   (`group_commit`/`immediate`); **ingen MVCC/read-snapshot, enkel skrivare, enkelprocess** ([02 §13](architecture-review/02-overgraph-capabilities.md)).
3. **Hur kan Tantivy erbjuda exakta, paginerade property lookups?** Den ska **inte** göra det
   (D1 godkänd): exakt, paginerad property-lookup görs auktoritativt i OverGraph via
   `query_nodes` (scope-`label_filter` + filter-DSL + keyset-paginering). Tantivy gör
   fulltext/BM25 + svensk lexikal kandidatidentifiering; typade `term_query`/`range_query`
   finns om en frikopplad projektion senare motiveras ([03](architecture-review/03-tantivy-capabilities.md)).
4. **Hur hålls Tantivy synkroniserat med OverGraph?** Outbox (snabbväg) + `reconcile` mot
   OverGraphs `updated_at` (korrekthetsryggrad) + watermark/staleness-detektering; OverGraph
   alltid auktoritativ (§6.1–6.2).
5. **Vilka SQL-kunskapsmodeller kan avvecklas?** D-listan i §9: legacy claims/relationships/
   entities/claim_answers, hela Graph v2-mirror, **plus** `text_units`/`shared_text_chunks` och
   `knowledge_observations` (flyttar till OverGraph). SQL behåller enbart dokumentmetadata,
   ägarskap, originalfiler och orkesteringsköer.
6. **Vilka prestandaförändringar kan påvisas?** Se §7; befintliga referensvärden (BM25 ~1 ms vs
   dense ~11–12 ms, indexbygge ~0,67 s) finns redan frysta.
7. **Vilka tekniska hinder återstår?** §5 — inga blockerande; MVCC/backup/export kräver
   app-sidiga rutiner; sparse-encoder och Tantivy facet-frågor är "vore bra", ej nödvändiga.

---

## 11. Avvecklingsplan (steg 8)

Gater som är **gröna**: återställningstest (§6.1), konsistenstest (§6.2), alla
lässare migrerade (display/navigering/grounding + lagen.nu + Graph v2-proveniens/legal-writeback +
legacy claims/relationships + index-repair + document-item-grounding + document-QA).

### 11.1 KLART — `text_units`/`shared_text_chunks` avvecklade

`text_units` och `shared_text_chunks` är **borttagna ur SQL** (migrering
[`191_drop_text_units`](../backend/alembic/versions/191_drop_text_units.py), head). OverGraph är
enda auktoritativa TextUnit-lagring:

- **Ingen dual-write:** `knowledge/persistence.py::_insert_text_units` + `text_unit_from_record` +
  `text_units_for_version`/`current_text_units` är borttagna; `knowledge/shared_chunks.py` och
  `database/text_units.py`/`chunk_guards.py` är borttagna. `document_knowledge_item_text_units`och
  `knowledge_claim_text_units` behåller `text_unit_id` som **vanlig OverGraph-nyckel** (FK borta).
- **Alla läsare:** `load_domain_text_units`/`load_text_unit_views` (OverGraph).
- **Övriga aktiva arbetsflöden kontrollerade och migrerade:** document-QA
  (`document_qa/catalog_apply.py`), kunddokument-räkning/purge (`kund_dokument.py`),
  live speech STT-termer (`live_speech_stt_terms.py`), dokumentborttagning
  (`delete_canonical_document`), claim_rekey-migreringen samt live-integrationsskriptet
  `integration-tests/check_workspace_ingest_live.py`.
- **Tester:** ~25 testfiler seedar/läser nu OverGraph; `research_reuse`-kontrakten
  (`test_03_chunk_sha.py`, `test_04_shared_chunks.py` omskriven till OverGraph-förekomster),
  `test_shared_chunk_postgres.py` verifierar OverGraph-ingestion på Postgres.

### 11.2 KVAR — legacy claims + Graph v2-mirror

Legacy `claims`/`entities`/`relationships`/`observations` (`knowledge_claims` m.fl.) och
Graph v2-mirror (`graph_nodes`/`graph_facts` m.fl.) skrivs fortfarande via research-skrivvägen.
Fullständig läsar-/skrivarinventering, gap-analys och ordning: [05 — Kvarvarande SQL-kunskapsgraf](architecture-review/05-legacy-graph-inventory.md).
Avvecklas i nästa PR:

2. **Ersätt research-skrivvägen** — legacy `claims`/`entities`/`relationships`/`observations`
   (och Graph v2-mirror) skrivs direkt till OverGraph (`overgraph/claims.py` + `write.py`);
   `research/answer_graph.py`/`result_store.py`/`graph_reuse.py` läser answer-episoder och
   facts från OverGraph, inte `GraphFact`/`GraphNode` SQL.
3. **Alembic-drop** av `knowledge_claims`, `knowledge_claim_text_units`, `knowledge_claim_answers`,
   `knowledge_entities`, `knowledge_relationships`, `knowledge_observations`, `graph_nodes`,
   `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations`,
   `graph_fact_question_dependencies` — i FK-ordning, med reversibel `downgrade`. **Behålls**:
   `canonical_documents`, `document_versions`, `document_sections`, `stored_objects`,
   `graph_ingest_work`, `graph_embedding_cache`, `knowledge_answer_reviews`,
   `knowledge_graph_events`, `document_knowledge_items*`.

Full CI-körning krävs för steg 11.2 (den fullständiga sviten är för långsam att köra lokalt —
se nedan).

---

## Bilaga: primära källfiler

- OverGraph API: `backend/.venv/.../overgraph/__init__.pyi` (1899 rader), `async_api.py`, vendor `METADATA`.
- Tantivy API: `experiments/overgraph_ingest/.venv/.../tantivy/tantivy.pyi` (714 rader).
- Produktionswrappers: `backend/app/services/overgraph/`, `backend/app/services/knowledge/`,
  `backend/app/services/graph_v2/`, `backend/app/services/document_properties/`,
  `backend/app/database/{models,text_units,knowledge_observation,graph_v2,answer_review,knowledge_scope}.py`.
- Experiment: `experiments/overgraph_ingest/overgraph_ingest/{graph,retrieval,jev,doctags}/`.
- Godkänd arkitektur (äldre, delvis överträffad av 0.17.0): `docs/specs/overgraph-knowledge-engine.md`.
