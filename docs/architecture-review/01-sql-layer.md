# 01 — SQL-Backed Knowledge Layer Inventory

Read-only code inventory for the architecture review. Goal: precisely map every SQL
table that today stores the knowledge graph (claims / relationships / observations /
TextUnits / document structure / graph-v2 projection), who writes and reads each one,
and classify each as **decommissionable when OverGraph becomes authoritative** vs
**must remain in SQL**.

Scope: `backend/app/` + Alembic migrations under `backend/alembic/versions/`.
Every claim below is backed by code read in this review.

---

## 0. How the layer is split across files

The knowledge tables are **not** all in `models.py`. They are spread over several
modules, all registered on the same SQLAlchemy `Base`:

| Module | Tables |
| --- | --- |
| `app/database/models.py` | `knowledge_claims`, `knowledge_claim_text_units`, `knowledge_claim_answers`, `knowledge_entities`, `knowledge_relationships`, `knowledge_graph_events`, `canonical_documents`, `document_versions`, `document_sections`, `document_knowledge_item_text_units` (+ application tables) |
| `app/database/text_units.py` | `text_units`, `shared_text_chunks` |
| `app/database/knowledge_observation.py` | `knowledge_observations` |
| `app/database/answer_review.py` | `knowledge_answer_reviews` |
| `app/database/graph_v2.py` | `graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations`, `graph_fact_question_dependencies`, `graph_ingest_work`, `graph_embedding_cache` |

`models.py` re-imports `TextUnitRecord` and `KnowledgeObservationRecord` at
`models.py:23-24` so ORM relationships resolve across modules.

The authoritative tenant-scope rules live in `app/database/knowledge_scope.py`
(re-exported for services via `app/services/knowledge/scope.py`).

---

## 1. `knowledge_claims` — `KnowledgeClaimRecord`

Defined at `models.py:1760-1808`. Migration history: created `116_knowledge_claims.py`,
reworked by `125_knowledge_persistence_gate.py` (adds `identity_key`), then
`126_knowledge_claim_source_independence.py` (drops `document_id` /
`document_version_id`, rekeys identity).

### Columns

| Column | Type | Notes |
| --- | --- | --- |
| `id` | String(64) PK | equals `identity_key` |
| `identity_key` | String(64) NOT NULL, indexed | source-independent identity |
| `scope_type` | String(16) NOT NULL, indexed | `shared` \| `customer` |
| `scope_key` | String(64) NOT NULL, indexed | `shared` \| `customer:{id}` |
| `customer_id` | FK `kunder.id`, nullable, indexed | null only when shared |
| `predicate` | String(128) NOT NULL | **no index** (see below) |
| `value` | JSON NOT NULL | assertion payload |
| `valid_from` | timestamptz | system/valid time start |
| `valid_to` | timestamptz | valid time end |
| `created_at` | timestamptz | |
| `superseded_at` | timestamptz nullable | lifecycle tombstone |
| `successor_id` | FK self `knowledge_claims.id` ON DELETE SET NULL, indexed | points to replacement claim |

### Indexes / constraints

- `uq_knowledge_claims_scope_identity` (`scope_key`, `identity_key`) — `models.py:1766-1770`
- `ix_knowledge_claims_superseded_at` — `models.py:1765`
- `ix_knowledge_claims_identity_key` — added `125_knowledge_persistence_gate.py:24`
- `ck_knowledge_claims_knowledge_scope` check constraint — `models.py:1771-1776`
- **`predicate` has no index.** The historical `(document_id, predicate)` index from
  migration `116` was dropped in `126_knowledge_claim_source_independence.py:21-27`
  (the migration drops any index/constraint touching the removed `document_*`
  columns). Reuse lookups today are by `identity_key` + `scope_key`, not by predicate.
  This matters for the review: predicate-as-attribute is not a query dimension.

### Identity derivation

`app/services/knowledge/identity.py:67-76` — `knowledge_claim_identity`:

```text
SHA-256( scope_key \0 predicate.strip() \0 canonical_json(normalize_assertion(value)) )
```

- `canonical_json` = `json.dumps(..., sort_keys=True, separators=(",", ":"))` (`identity.py:43-44`)
- `normalize_assertion` casefolds/strips punctuation on strings and drops a volatile
  key allowlist (`attempt_id`, `citation`, `question`, `run_id`, `wording`, …) so
  identity is stable against LLM wording and source/attempt provenance (`identity.py:10-64`).
- Persist rejects any `KnowledgeClaim` whose `id` does not equal this identity
  (`claim_store.py:57-63`).

### Temporal lifecycle

- Write: `persist_domain_claim` (`claim_store.py:42-76`) sets `valid_from=now`,
  `created_at=now`; reuse returns existing row.
- Supersede: `supersede_knowledge_claim` (`claims.py:170-205`) sets `superseded_at`,
  `valid_to`, optional `successor_id`, and records a `CLAIM_SUPERSEDED` graph event.
- Current claims are selected with `superseded_at IS NULL`
  (`claims.py:289`), and `_reject_superseded_claim` (`claim_store.py:123-125`) refuses
  to reuse a superseded row.

### Why SQL today / OverGraph status

Claims are the *legacy* durable-assertion store. The `backend/AGENTS.md` knowledge
persistence gate still routes `domain_knowledge` here, but the research reuse read
path (`research/graph_reuse.py`) explicitly does **not** read claims — it reads
Graph v2 / OverGraph. Claims remain SQL only to (a) feed the Graph v2 outbox and
(b) preserve history. **Decommissionable** as the authoritative assertion store once
OverGraph is authoritative.

---

## 2. `knowledge_relationships` — `KnowledgeRelationshipRecord`

Defined at `models.py:1922-1972`. Reworked by `125_knowledge_persistence_gate.py`
(adds `temporal_key` to the unique edge tuple).

### Columns

| Column | Type |
| --- | --- |
| `id` | String(64) PK |
| `scope_type` / `scope_key` / `customer_id` | tenant scope |
| `relation` | String(64) NOT NULL |
| `from_kind` | String(32) NOT NULL (`entity`\|`claim`\|`text_unit`\|`document`) |
| `from_id` | String(64) NOT NULL |
| `to_kind` | String(32) NOT NULL |
| `to_id` | String(64) NOT NULL |
| `temporal_key` | String(64) NOT NULL default `""` |
| `extra` | JSON |
| `valid_from` / `valid_to` | timestamptz |
| `created_at` | timestamptz |
| `superseded_at` | timestamptz nullable |

### Indexes / constraints

- `uq_knowledge_relationships_scope_edge` on (`scope_key`, `relation`, `from_kind`,
  `from_id`, `to_kind`, `to_id`, `temporal_key`) — `models.py:1927-1936`
- `ix_knowledge_relationships_from` / `_to` / `_relation` / `_superseded_at` — `models.py:1937-1940`
- `ck_knowledge_relationships_knowledge_scope` — `models.py:1941-1946`

### CORE_RELATIONS and node kinds

`relationships.py:33-40`:

```python
ABOUT = "ABOUT"; CONTRADICTS = "CONTRADICTS"; PART_OF = "PART_OF"; SAME_AS = "SAME_AS"
CORE_RELATIONS = frozenset({ABOUT, SUPPORTED_BY, CONTRADICTS, PART_OF, SAME_AS})
NODE_KINDS = frozenset({"entity", "claim", "text_unit", "document"})
```

`SUPPORTED_BY` is imported from `claims.py`. Any non-core relation must be a
namespaced adapter relation (`require_relation`, `relationships.py:65-73`).

### Identity derivation

`relationships.py:76-95`:

```text
SHA-256( (customer_id|"shared") \0 relation \0 from_kind \0 from_id \0 to_kind \0 to_id \0 temporal_key )
```

### Endpoint scope enforcement

`persist_knowledge_relationship_result` (`relationships.py:158-208`) resolves the
endpoint rows' scopes and calls `assert_relationship_scopes`
(`knowledge_scope.py:196-227`): customer↔customer cross-tenant edges are rejected,
`SAME_AS` cannot merge scopes, and shared edges may only connect shared nodes.

### Why SQL today / OverGraph status

Typed edges between claim/entity/TextUnit/document nodes. In Graph v2 the equivalent
semantics moved to `GraphFactRelation` (`core.contradicts`) and OverGraph edges
(`SUBJECT`/`OBJECT`/`CONTEXT`/`SUPPORTS`/`CONTAINS`/`NEXT`/`CONTRADICTS`/`DEPENDS_ON`).
No research read path consumes `knowledge_relationships` for evidence; it is written
via `persist_extracted_knowledge` and read only for scope-touching walks
(`relationships_touching`). **Decommissionable** as primary storage; keep only if the
event/audit history must be preserved in SQL.

---

## 3. `knowledge_observations` — `KnowledgeObservationRecord`

Defined at `app/database/knowledge_observation.py:21-71`. Created by
`125_knowledge_persistence_gate.py:48-100`.

### Columns

| Column | Type |
| --- | --- |
| `id` | String(64) PK |
| `scope_type` / `scope_key` / `customer_id` | tenant scope |
| `observation_class` | String(32) NOT NULL |
| `kind` | String(64) NOT NULL |
| `document_id` | FK `canonical_documents.id` |
| `document_version_id` | FK `document_versions.id` |
| `question_key` | String(64) NOT NULL default `""` |
| `statement_normalized` | Text NOT NULL |
| `extra` | JSON |
| `created_at` | timestamptz |

### Indexes / constraints

- `uq_knowledge_observations_identity` on (`scope_key`, `observation_class`, `kind`,
  `document_version_id`, `question_key`, `statement_normalized`) — `knowledge_observation.py:26-34`
- `ix_knowledge_observations_document_version`, `ix_knowledge_observations_class` — lines 35-36
- `ck_knowledge_observations_knowledge_scope` — lines 37-42

### observation_class / kind

`persistence_class.py:11-44`:

- `domain_knowledge` — **rejected** as an observation (observations are explicitly
  "not knowledge claims"; `observations.py:72-73`).
- `source_quality` — kinds `corrupted, incomplete_source, incorrect_source, ocr,
  partial_source, retrieval_limit, source_gap, truncation`.
- `research_observation` — kinds `does_not_answer, gap, insufficiency,
  question_relative_gap, unanswered`.

### Identity derivation

`identity.py:79-92`:

```text
SHA-256( scope_key \0 observation_class \0 kind \0 document_version_id \0 question_key \0 statement_normalized )
```

### How verification / quality observations are stored

The classify-then-persist gate (`persist.py`): an extracted claim classified as
`source_quality` or `research_observation` is **not** written to `knowledge_claims`;
it is converted into a `KnowledgeObservation` (`_observation_from_claim`,
`persist.py:237-261`) and persisted here. The `persist_extracted_claim` result then
reports `action="rejected_by_class"` with `observation_id` set. This is the durable
record of "the source did not / could not answer" and of source-quality defects.

### Why SQL today / OverGraph status

Observations are provenance-adjacent quality notes, not facts. They are not part of
the OverGraph projection and are not read for research reuse (they feed audits and
observability). **Candidate to move to OverGraph or keep as audit data** — they do not
need to be authoritative; they are secondary metadata.

---

## 4. `text_units` + `shared_text_chunks` — `TextUnitRecord` / `SharedTextChunkRecord`

Defined at `app/database/text_units.py`.

### `shared_text_chunks` (`SharedTextChunkRecord`, lines 19-28)

| Column | Type |
| --- | --- |
| `content_hash` | String(64) PK |
| `text` | Text NOT NULL |

Content-addressed, provenance-independent, **immutable** storage. Guards in
`chunk_guards.py`:
- `protect_shared_chunks` (lines 20-30): BEFORE UPDATE trigger rejects mutation
  (SQLite RAISE ABORT; Postgres `reject_shared_chunk_update()`); Postgres also
  `ENABLE ROW LEVEL SECURITY` and `REVOKE ALL` from `anon`/`authenticated`.
- `protect_text_unit_reference` (lines 33-40): `content_hash` on `text_units` may not change.

### `text_units` (`TextUnitRecord`, lines 31-99)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | String(64) PK | `make_text_unit_id` |
| `scope_type` / `scope_key` / `customer_id` | tenant scope | |
| `document_version_id` | FK `document_versions.id` ON DELETE CASCADE | |
| `document_id` | FK `canonical_documents.id` ON DELETE CASCADE | |
| `section_id` | FK `document_sections.id` ON DELETE SET NULL | |
| `ordinal` | Integer NOT NULL | order within section/version |
| `content_hash` | FK `shared_text_chunks.content_hash` ON DELETE RESTRICT | |
| `locator` | String(128) | `line:N-M`, `page:N`, `paragraph:N` |
| `page_start` / `page_end` | Integer | |
| `char_start` / `char_end` | Integer | |
| `valid_from` / `valid_to` | timestamptz | |
| `ingested_at` | timestamptz | |
| `embedding_id` | String(64) | default = `id` |
| `extra` | JSON | |

Indexes: `ix_text_units_document_ordinal`, `ix_text_units_version_ordinal`,
`ix_text_units_content_hash`, plus `ck_text_units_knowledge_scope` (`text_units.py:35-45`).

### Identity derivation

`units.py`:

- `hash_text(text)` = `SHA-256(text.encode("utf-8"))` (line 11-12) — content hash.
- `make_text_unit_id(document_version_id, locator, content_hash)` =
  `SHA-256(document_version_id \0 locator \0 content_hash)` (lines 25-32).
- `make_section_id(document_version_id, path)` = `SHA-256(document_version_id \0 path)` (lines 20-22).
- `make_document_version_id()` = `uuid4().hex` (lines 15-17) — random, temporal.

### Relationship to `shared_text_chunks`

`TextUnitRecord.chunk` relationship is `lazy="joined", innerjoin=True`
(`text_units.py:92`); `text` is a property that reads `chunk.text` (lines 94-96).
Persist resolves chunks via `resolve_shared_chunks` (`shared_chunks.py:14-38`), which
batches `on_conflict_do_nothing` upserts in groups of 200 and re-validates SHA on read.

### Why SQL today / OverGraph status

TextUnits are the canonical citable passage and are the **provenance** for claims,
observations, and Graph facts. They are already **mirrored** into OverGraph as
`TextUnit`/`DocumentVersion` nodes (`overgraph/write.py:93-137`, `overgraph/publish.py`,
`legal_writeback.py:222-237`). The SQL copy is the authority for document structure,
versioning, locators, and workspace/access-check grounding. TextUnit *content* and
*citation identity* are candidates to move to OverGraph, but the **document/version/
section metadata + stored-object access control must remain in SQL** (see §11).

---

## 5. Document & structure models

### `canonical_documents` (`CanonicalDocumentRecord`, `models.py:1568-1616`)

Stable source identity. Unique on (`scope_key`, `source_type`, `canonical_uri`)
(`models.py:1572-1578`). Columns: `id`, scope fields, `source_object_id`
(FK `stored_objects.id`), `source_type`, `canonical_uri` (String 1024), `title`,
`domain`, `jurisdiction`, `created_at`, `extra` JSON. Scope check constraint at lines
1579-1584.

### `document_versions` (`DocumentVersionRecord`, `models.py:1619-1677`)

Immutable content snapshot. Columns: `id`, scope fields, `document_id`, `version`,
`content_hash` (String 64), `mime_type`, `valid_from`/`valid_to`, `ingested_at`,
`superseded_at`, `extra`.

Key constraints:
- Partial unique index `uq_document_versions_current` on `document_id` **where
  `superseded_at IS NULL`** (both SQLite and Postgres) — `models.py:1624-1630`. This
  enforces at most one *current* version per document.
- `ix_document_versions_content_hash`, `ix_document_versions_superseded_at`.

### `document_sections` (`DocumentSectionRecord`, `models.py:1680-1730`)

Hierarchical regions. Columns: `id`, scope fields, `document_version_id`,
`document_id`, `parent_section_id` (self FK, SET NULL), `ordinal`, `type`, `title`,
`page_start`/`page_end`, `extra`. Indexes on `(document_id, ordinal)` and
`(document_version_id, ordinal)`.

### How versions are distinguished

`persist_segmented_document` (`persistence.py:107-184`): a new version row is created
only when `content_hash` differs from the current version; if the hash matches, the
current version is reused (`reused_current=True`, lines 152-158). On a real change the
old version gets `superseded_at = now` (line 160), then a new `DocumentVersionRecord`
is inserted (lines 167-181) followed by sections and text units.

### How changed versions relate to old evidence

Old evidence (TextUnits + claims grounded on them) remains pointed at the superseded
version. Read paths explicitly filter `superseded_at IS NULL`:
- `get_current_document_version` (`persistence.py:84-92`)
- `graph_grounding.py:129` (`_usable_source` → `version.superseded_at is None`)
- `document_grounding.py:89` (`readable_document_passage`)

Superseded versions stay queryable by frozen id (the vector index and Graph facts keep
their frozen source ids — see `canonical_ingest.py:357-359` comment).

### Why SQL today / OverGraph status

Document/version/section metadata + `stored_objects` ownership/access control are
application/document state, not knowledge-graph content. **Must remain in SQL.** Only
the citation identity and text may be projected to OverGraph.

---

## 6. Identity keys (SHA-256 formulas) — summary

| Object | Formula (all `\0`-joined, UTF-8, SHA-256 hex) | Source |
| --- | --- | --- |
| Claim | `scope_key · predicate.strip() · canonical_json(normalize_assertion(value))` | `identity.py:67-76` |
| Relationship | `(customer_id\|"shared") · relation · from_kind · from_id · to_kind · to_id · temporal_key` | `relationships.py:76-95` |
| Entity | `(customer_id\|"shared") · entity_type · normalize_key(key)` | `entities.py:45-57` |
| Observation | `scope_key · observation_class · kind · document_version_id · question_key · statement_normalized` | `identity.py:79-92` |
| TextUnit | `document_version_id · (locator\|"") · content_hash` | `units.py:25-32` |
| Section | `document_version_id · path` | `units.py:20-22` |
| Graph event | `scope_key · event_type · node_kind · node_id · (related_id\|"")` | `events.py:52-65` |
| Graph node | `stable_id(scope_key, node_type, key)` where `key` = strong identifier `ns:id` or `weak:{ctx}:{name}` | `graph_v2/identity.py:9-31`, `graph_v2/write.py:41-69` |
| Graph fact | `stable_id(scope_key, source_id, target_id, namespaced(predicate), context_id\|"", occurrence_key, normalized(fact_text))` | `graph_v2/identity.py:33-40` |

`stable_id(*parts)` = `SHA-256("\0".join(parts))` (`graph_v2/identity.py:9-10`).
`namespaced()` requires a dotted label; `normalized()`/`normalize_assertion_text()`
casefold + strip edge punctuation.

---

## 7. Provenance, scope, tenant

Single source of truth: `app/database/knowledge_scope.py` (re-exported by
`app/services/knowledge/scope.py`).

- Scope pair invariants: `scope_type='shared'` ⇒ `customer_id IS NULL` and
  `scope_key='shared'`; `scope_type='customer'` ⇒ `customer_id` set and
  `scope_key='customer:{id}'` (`knowledge_scope.py:40-47`, `264-273`).
- Persist fails closed: `require_persist_scope` never infers shared from a missing
  customer_id (`knowledge_scope.py:81-110`).
- DB-level enforcement: every knowledge table carries the `ck_*_knowledge_scope`
  CHECK constraint generated by `knowledge_scope_check_sql` (`knowledge_scope.py:246-251`),
  plus ORM `before_insert`/`before_update` listeners via `bind_scoped_mapper`
  (`knowledge_bind.py:19-33` → `_enforce_row_scope` → `fill_row_scope`,
  `knowledge_scope.py:135-163`).
- Read isolation: `visible_to_customer_clause` (`knowledge_scope.py:230-243`) returns
  shared OR owned-customer rows only.
- Promotion guard: `assert_not_promoted` blocks customer→shared
  (`knowledge_scope.py:175-183`); `assert_relationship_scopes` blocks cross-tenant and
  `SAME_AS` scope-merge edges (`knowledge_scope.py:196-227`).

Graph v2 tables use a **narrower** scope pair (`scope_key` + nullable `customer_id`,
no `scope_type`) with their own `ck_graph_*_scope` constraints
(`graph_v2.py:17-19, 54-56`), enforced the same way (`scope_key='shared'` ⇒ null
customer; else `customer:{id}`).

---

## 8. Supersession and temporality

- **Claims**: `superseded_at` + `successor_id` + `valid_to`; `supersede_knowledge_claim`
  (`claims.py:170-205`). Only "current" claims read (filter `superseded_at IS NULL`).
- **Relationships**: `superseded_at`; reuse is refused if superseded
  (`relationships.py:239-240`).
- **Document versions**: `superseded_at` + partial unique current index (see §5).
- **Graph facts**: `valid_at`/`invalid_at` + `status` (`active`/…) instead of
  supersession; `fact_is_current` = active AND `valid_at ≤ now < invalid_at`
  (`graph_grounding.py:36-37`).
- **Answer-review TTL** (`knowledge_answer_reviews`, `app/database/answer_review.py:12-54`):
  independent of evidence validity. `ttl ∈ {soon(3mo), later(6mo), never}`; status
  machine `awaiting_ttl → scheduled → candidate → completed`. Check constraints at
  `answer_review.py:16-32`. The TTL is a *review reminder*, not an expiry — see
  `REVIEW_TTL_QUESTION` prompt text (`services/knowledge/answer_review.py:22-38`) and
  `record_answer_review`'s "must not reset the clock on reuse" identity
  (`answer_review.py:84-100`).

---

## 9. Ingest and update flows (full write path)

### 9.1 Canonical document/TextUnit ingest

Entry: `KnowledgeIngestService.ingest_document` (`ingest.py:53-103`) →
`ingest_extracted_source` (`canonical_ingest.py:63-95`) →
`persist_extracted_source` (`canonical_ingest.py:98-177`):

1. `get_canonical_document_by_identity` (dedupe on scope+source_type+canonical_uri).
2. `DocumentSegmenter.segment` (`segmentation.py:63-107`) builds `CanonicalDocument` →
   `DocumentVersion` → `DocumentSection` → `TextUnit` (headings or block grouping).
3. `persist_segmented_document` (`persistence.py:107-184`) writes document/version/
   section/text_units; `_insert_text_units` (`persistence.py:265-297`) first resolves
   `shared_text_chunks`, then inserts `TextUnitRecord` rows with `embedding_id=unit.id`.
4. `await session.commit()` **releases the connection before embedding**
   (`canonical_ingest.py:160-161`) — this is the mandated connection-release pattern.
5. `index_persisted_source` (`canonical_ingest.py:180-206`) embeds and upserts into the
   **vector store** (not SQL; Supabase vector bucket or in-memory). TextUnit ids remain
   frozen per temporal occurrence.

Batch upsert: `resolve_shared_chunks` batches 200 (`shared_chunks.py:26`).
Chunk guards: immutability triggers in `chunk_guards.py`.

### 9.2 Claim / entity / relationship / observation persist (research write-back)

Entry: providers produce `KnowledgeClaim`/`KnowledgeEntity`/`KnowledgeRelationship` →
`persist_extracted_knowledge` (`persist.py:107-171`):

1. Observations first, then claims via `persist_extracted_claim` (`persist.py:69-104`).
2. `classify_persistence` (`persistence_class.py:117-172`) decides the persistence class.
3. `domain_knowledge` → `persist_domain_claim` (`claim_store.py:42-76`): validates
   stable id, asserts grounding scope, idempotent insert, then
   `attach_supporting_text_units` (`claim_store.py:79-103`) with
   `on_conflict_do_nothing` on (`claim_id`, `text_unit_id`).
4. `source_quality`/`research_observation` → `persist_knowledge_observation`
   (`observations.py:111-141`).
5. Entities → `persist_knowledge_entity_result` (`entities.py:109-136`).
6. Relationships → `persist_knowledge_relationship_result` (`relationships.py:158-208`),
   with endpoint-scope assertion.

### 9.3 Graph v2 outbox + worker pattern

The legal/graph projection is decoupled from the research transaction:

1. **Enqueue**: `enqueue_legal_graph` (`graph_v2/outbox.py:29-57`) writes a
   `GraphIngestWork` row (status `pending`) with the claim/entity payload, keyed by
   `stable_id(scope_key, research_need_id, json(payload))` (idempotent).
2. **Poll/claim**: `claim_graph_work` (`outbox.py:78-94`) uses
   `FOR UPDATE SKIP LOCKED` + a 5-minute lease to claim a `pending` row (or a stale
   `processing` row past its lease), increments `attempts`.
3. **Process**: `process_graph_work` (`outbox.py:97-154`) dispatches by payload kind
   (`DOCUMENT_QA_WRITE`, `DOCUMENT_CATALOG_WRITE`, or legal) and for legal calls
   `write_legal_facts` (`legal_writeback.py:28-125`).
4. **Legal write-back** (`legal_writeback.py`): resolves the `legal.source` entity and
   per-claim value nodes via `resolve_node`; computes `resolve_exact_fact` first
   (before any embedding), batches embeddings for the misses, then `resolve_fact`
   (judge for SAME/CONTRADICTS/DISTINCT) — writing `GraphNode`/`GraphFact`/
   `GraphFactSource` via `graph_v2/write.py`. Then `attach_question_dependency`
   (`graph_v2/dependencies.py:17-51`) and finally `_publish_overgraph`
   (`legal_writeback.py:204-272`) → `publish_legal_fact` (`overgraph/publish.py:34-53`).
5. **Worker loop**: `run_graph_ingest_loop` (`graph_v2/worker.py:15-25`) polls every 5s
   with `limit=10`; started via `start_graph_owner` only when
   `settings.graph_ingest_loop_enabled` (`config.py:223`). It attaches a document-owner
   marker (`document_qa/owner.py`).
6. Retry/terminal: permanent errors → `failed`; transient → `pending` with exponential
   backoff (5s·2^n capped 600s) (`outbox.py:175-203`). One bad row never stalls the
   queue (break after failure).

### 9.4 Answer episodes (freeze → publish)

`publish_answer` (`research/answer_graph.py:42-131`): on frozen `EvidenceSet`, resolves
question node + answer node, writes a `research.answered_by` fact via `resolve_fact`
(SQL `GraphNode`/`GraphFact`), attaches question→fact dependencies, then
`publish_answer_fact` (`overgraph/publish.py:73-117`) writes the same fact + question/
answer entities + `DEPENDS_ON` edges into OverGraph.

### 9.5 Who writes what — quick matrix

| Table(s) | Writer |
| --- | --- |
| `canonical_documents`, `document_versions`, `document_sections`, `text_units`, `shared_text_chunks` | `persistence.py` / `canonical_ingest.py` / `shared_chunks.py` |
| `knowledge_claims`, `knowledge_claim_text_units` | `claim_store.py` (+ `claim_rekey.py` migration) |
| `knowledge_claim_answers` | `claims.py:208-261` (`answer_research_need`) |
| `knowledge_entities` | `entities.py` |
| `knowledge_relationships` | `relationships.py` |
| `knowledge_observations` | `observations.py` |
| `knowledge_graph_events` | `events.py` (`record_graph_event`) |
| `graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`, `graph_fact_relations`, `graph_fact_question_dependencies` | `graph_v2/write.py`, `graph_v2/dependencies.py`, `graph_v2/legal_writeback.py`, `research/answer_graph.py` |
| `graph_ingest_work` | `graph_v2/outbox.py`, `document_qa/outbox.py`, `document_qa/catalog_outbox.py` |
| `graph_embedding_cache` | `graph_v2/embeddings.py` (`GraphEmbeddingCacheProvider`) |
| `knowledge_answer_reviews` | `services/knowledge/answer_review.py` (`record_answer_review`) |

---

## 10. Revalidation / TTL / outbox

- **Answer-review worker** is a separate CLI process
  (`services/knowledge/answer_review_worker.py`), never invoked by research:
  - `enqueue` — promotes due `scheduled` rows to `candidate` (`answer_review.py:136-158`).
  - `classify` — `classify_pending_reviews` (`answer_review_classification.py:130-163`)
    claims one `awaiting_ttl` row at a time with a CAS token, calls Jev **outside** the
    DB transaction (`client.ask` after the claim transaction committed — the mandated
    connection-release pattern, lines 141-152), then writes `soon|later|never`.
  - `complete` — moves `candidate` → `completed`.
- **GraphIngestWork outbox rows** (`graph_ingest_work`): the durable projection queue
  (§9.3). Status: `pending → processing → completed | failed | pending(retry)`.
- **Revalidation triggers were removed.** `142_drop_graph_revalidation_queues.py` drops
  `graph_fact_revalidations` and `graph_question_revalidation_work`;
  `190_drop_evidence_set_revalidations.py` drops `evidence_set_revalidations`
  (refusing if rows remain). The `backend/AGENTS.md` states: freeze only writes
  `awaiting_ttl`; the Graph worker only processes ingest; no graph-impact revalidation
  in provider write-back. Freshness is now checked at *read* time via
  `research_knowledge_freshness_max_age_seconds` and `_current_basis`
  (`research/answer_graph.py:203-240`).

---

## 11. Consumers that read directly from SQL

This is the "who still SELECTs these tables" map, driving the decommissioning call.

### Graph v2 (authoritative read path for research)

| Consumer | Reads | Purpose |
| --- | --- | --- |
| `research/graph_reuse.py` | OverGraph catalog (via `lookup_candidates`) + `answer_graph.lookup_answers` (SQL `GraphNode`/`GraphFact`) | the single research read path for persisted knowledge |
| `research/answer_graph.py:134-194` (`lookup_answers`) | `GraphNode`, `GraphFact`, `GraphFactSource` | whole-answer episode retrieval |
| `research/result_store.py:69-145` | `GraphFact`, `GraphIdentifier`, `GraphNode` + `KnowledgeQuestionRow` | read completed answers (`research.answered_by`) |
| `research/graph_grounding.py:57-111` | `DocumentVersionRecord`, `CanonicalDocumentRecord` + OverGraph `TextUnit` | hydrate facts from canonical passages |
| `services/document_knowledge.py` | `GraphFact`, `GraphIdentifier`, `GraphNode` | answer listing |
| `services/kund_dokument.py:137-356` | every knowledge + graph table | tenant stats + cascade delete |

### TextUnit / document structure (must remain in SQL)

| Consumer | Reads | Purpose |
| --- | --- | --- |
| `services/document_navigation.py:152-194` | `TextUnitRecord`, `DocumentSectionRecord`, `DocumentVersionRecord`, `CanonicalDocumentRecord` | workspace document navigation/citations |
| `api/workspace_chats.py:239-241` | `TextUnitRecord`, `DocumentVersionRecord`, `CanonicalDocumentRecord` | passage/delivered-document views |
| `services/research/workspace_grounding.py` | `CanonicalDocumentRecord`, `DocumentVersionRecord` + OverGraph `load_text_units` | workspace access + grounding |
| `services/workspace_research_start.py:34-42` | `CanonicalDocumentRecord`, `DocumentVersionRecord` | research-start source resolution |
| `knowledge/document_grounding.py`, `knowledge/shared_document_grounding.py` | `TextUnitRecord`, `DocumentVersionRecord`, `CanonicalDocumentRecord`, `StoredObject` | private/shared passage access control |
| `services/lagen_nu/research_source.py` | `TextUnitRecord` | legal source reuse of canonical units |
| `document_qa/catalog_apply.py:73` | `TextUnitRecord` (via `text_units_for_version`) | catalog projection |

### Legacy claim/relationship/observation (not the research read path)

| Consumer | Reads | Purpose |
| --- | --- | --- |
| `research/question_graph_sql.py` (`SqlQuestionEvidenceGraph`) | `KnowledgeQuestionRow`, `KnowledgeQuestionEvidenceLink`, `EvidencePassage` | legacy question→evidence SQL store (replaced by Graph v2 for reuse, but code still present) |
| `knowledge/claims.py:264-341` (`claim_answers_for_question_key`) | `KnowledgeClaimRecord` + `KnowledgeClaimAnswer` | legacy reuse by question key (not used by `graph_reuse`) |
| `knowledge/audit.py:71` | `KnowledgeObservationRecord` | audit |
| `knowledge/answer_review.py` / `answer_review_classification.py` | `KnowledgeAnswerReview` | TTL lifecycle |

---

## 12. Per-model verdict: SQL vs OverGraph

Legend: **D** = decommission when OverGraph authoritative; **K** = keep in SQL;
**M** = mirror (OverGraph copy + SQL authority retained for access/structure).

| Model / table | Why in SQL today | Functions that actually require SQL | Verdict |
| --- | --- | --- | --- |
| `knowledge_claims` | legacy durable assertion store; feeds Graph v2 outbox; preserves supersession history | `claim_store` persist + `claim_answers_for_question_key` (legacy reuse) | **D** — no research read path consumes it; OverGraph `Fact` is the authoritative assertion |
| `knowledge_claim_text_units` | claim→TextUnit support links | claim persist + legacy reuse | **D** (follows claims) |
| `knowledge_claim_answers` | ResearchNeed→claim answer mapping | `answer_research_need`, `claim_answers_for_question_key` | **D** — superseded by `GraphFactQuestionDependency` + `research.answered_by` episodes |
| `knowledge_entities` | legacy named nodes | `entities.py` persist/lookup | **D** — Graph v2/OverGraph `Entity` nodes + `Identifier` aliases replace it |
| `knowledge_relationships` | legacy typed edges | `relationships.py` persist, `relationships_touching` | **D** — `GraphFactRelation` + OverGraph edges replace it |
| `knowledge_observations` | source-quality / research-gap notes | `observations.py`, audit | **M/K** — secondary provenance/audit; could live in OverGraph or stay as audit data |
| `knowledge_graph_events` | append-only mutation audit | `events.py` | **K** (audit history) or move to OverGraph event log |
| `canonical_documents` | document identity + ownership | `document_grounding`, `graph_grounding`, `document_navigation`, `kund_dokument` | **K** — document/ownership metadata, not graph content |
| `document_versions` | immutable versioning + `superseded_at` | grounding freshness, navigation | **K** — version lifecycle is document state |
| `document_sections` | structure + ordinal ordering | navigation, segmentation | **K** — document structure |
| `text_units` | canonical passage + locator/char offsets + `stored_objects` access | `document_grounding`, `document_navigation`, `workspace_chats`, `graph_grounding` hydration | **M** — cite/identity/text may move to OverGraph; SQL stays for access control + structure |
| `shared_text_chunks` | content-addressed immutable text | `resolve_shared_chunks`, `TextUnit.text` property | **M** — content could live in OverGraph `TextUnit` props; SQL immutability/RLS is a storage detail |
| `graph_nodes` / `graph_identifiers` | Graph v2 property graph (SQL mirror) | `graph_v2/write.py`, `answer_graph`, `result_store`, `kund_dokument` | **D** — the SQL mirror of OverGraph; OverGraph becomes authoritative |
| `graph_facts` | fact + embedding + FTS index | `graph_v2/retrieval.py` (hybrid+FTS), `result_store`, `answer_graph` | **D** — OverGraph dense vector + PPR replaces SQL FTS/embedding search |
| `graph_fact_sources` | fact provenance (episode/TextUnit) | `graph_v2/write.py`, `answer_graph` | **D** — OverGraph `SUPPORTS` edges + `source_refs_json` |
| `graph_fact_relations` | contradiction edges | `graph_v2/write.py` | **D** — OverGraph `CONTRADICTS` edge |
| `graph_fact_question_dependencies` | question→fact dependency | `graph_v2/dependencies.py` (reuse reads these) | **D** — OverGraph `DEPENDS_ON` edge (already written in parallel) |
| `graph_ingest_work` | durable projection outbox | `graph_v2/outbox.py`, `worker.py`, `document_qa/*` | **K** (orchestration) — queue/lease/retry is app orchestration, not knowledge storage |
| `graph_embedding_cache` | content-addressed vector cache | `graph_v2/embeddings.py` | **K** — cache/lease orchestration |
| `knowledge_answer_reviews` | TTL review schedule | `answer_review.py`, `answer_review_classification.py` | **K** — review scheduling/orchestration, independent of the graph |

### Bottom line

- **Decommission as authoritative knowledge storage** (`D`): `knowledge_claims`,
  `knowledge_claim_text_units`, `knowledge_claim_answers`, `knowledge_entities`,
  `knowledge_relationships`, and the entire `graph_v2` property-graph mirror
  (`graph_nodes`, `graph_identifiers`, `graph_facts`, `graph_fact_sources`,
  `graph_fact_relations`, `graph_fact_question_dependencies`). OverGraph already
  stores every one of these shapes as nodes/edges with stable keys derived from the
  same identity formulas.
- **Mirror** (`M`): `text_units` + `shared_text_chunks` — OverGraph holds text/citation
  identity, but SQL remains the authority for document structure, `stored_objects`
  access control, and workspace scoping.
- **Must remain in SQL** (`K`): `canonical_documents`, `document_versions`,
  `document_sections` (document/version metadata + ownership), `knowledge_graph_events`
  (audit), `graph_ingest_work`, `graph_embedding_cache` (orchestration/caching), and
  `knowledge_answer_reviews` (TTL scheduling). `knowledge_observations` is secondary
  provenance that can stay in SQL or move with the graph.
