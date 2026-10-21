# OverGraph 0.17.0 — Capability Inventory

**Scope:** read-only inventory of the installed `overgraph==0.17.0` (pure-Rust embedded graph DB) and of the project's production wrapper in `backend/app/services/overgraph/`.

**Method.** Every claim below is verified against the *installed* artifacts, in priority order:

1. `backend/.venv/lib/python3.13/site-packages/overgraph/__init__.pyi` (1899 lines — full type stubs, ground truth for the public Python surface).
2. `backend/.venv/lib/python3.13/site-packages/overgraph/async_api.py` (1147 lines).
3. `backend/.venv/lib/python3.13/site-packages/overgraph/__init__.py` (139 lines — connector-side request helpers).
4. `backend/.venv/lib/python3.13/site-packages/overgraph-0.17.0.dist-info/METADATA` (vendor README — confirms version, durability modes, on-disk format, semantics).
5. Compiled module introspection (`overgraph.abi3.so`) — confirm which runtime methods actually exist.
6. Production wrapper `backend/app/services/overgraph/*.py` and `docs/specs/overgraph-knowledge-engine.md`.

Version is confirmed by both `METADATA` (`Version: 0.17.0`) and `backend/pyproject.toml:23` (`overgraph==0.17.0`), locked in `backend/uv.lock:2050`.

**Verdict legend** used throughout:

- ✅ **Present** — implemented in 0.17.0 and callable today.
- ⚠️ **Present but limited** — implemented, but with constraints that matter for our use.
- ❌ **Absent** — not in 0.17.0; requires development or an application-side workaround.

---

## 0. Quick verdict table

| # | Capability | Verdict |
|---|---|---|
| 1 | Persistent storage (open a directory) | ✅ |
| 2 | Nodes and edges (explicit model, labels, key, vectors) | ✅ |
| 3 | Node/edge properties (typed scalars + nested, schema-optional) | ✅ |
| 4 | Exact lookups + secondary/exact property index | ✅ (⚠️ index state is async "building/ready/failed") |
| 5 | Dense + sparse vector search | ✅ dense + sparse + hybrid; ❌ no encoder (BYO) |
| 6 | Traversal (neighbors / BFS / PPR / top-k / shortest path) | ✅ |
| 7 | Cross-type relations (edges between arbitrary node labels) | ✅ |
| 8 | Batch writes (`batch_upsert`, `graph_patch`, ingest mode, group commit) | ✅ |
| 9 | Updates / deletions (upsert, delete, invalidate_edge, prune) | ✅ |
| 10 | Concurrent reads/writes (locking, MVCC, multi-writer) | ⚠️ single-process, single-writer |
| 11 | Backup / restore | ⚠️ copy-the-directory only (no snapshot API) |
| 12 | Export / import | ⚠️ adjacency export only; no import / full serialization |
| 13 | Transactions / ACID | ⚠️ atomic commit + WAL durability; **no MVCC snapshot isolation, single-writer** |
| 14 | Edge uniqueness / keys / validity / weight | ✅ (unique `(from,to,label)`); no stable edge key/embedding |
| 15 | Label/scope filtering in vector search | ✅ label-only filter; ⚠️ no property filter inside `vector_search` |
| 16 | Async API | ✅ (full `asyncio.to_thread` mirror) |

---

## 1. Persistent storage

**Verdict:** ✅ Present.

The DB is opened from a **directory path**. On disk it is a self-contained folder (LSM-tree: WAL + manifest + immutable `segments/`), not a single file.

```python
class OverGraph:
    @staticmethod
    def open(path: str, **kwargs: Any) -> OverGraph: ...   # __init__.pyi:1195-1196
    def close(self, force: bool = False) -> None: ...       # __init__.pyi:1197
    def stats(self) -> DbStats: ...                          # __init__.pyi:1205
    def scrub(self) -> ScrubReport: ...                      # __init__.pyi:1206
```

On-disk layout (vendor `METADATA` "On-disk layout"):

```text
my-graph/
  manifest.current         # atomic checkpoint (JSON)
  wal_0.wal                # append-only write-ahead log generation
  segments/
    seg_0001/
      segment_manifest.dat     # component table of contents
      segment.core             # packed immutable core records + maintained indexes
      secondary_indexes/       # optional declared property-index sidecars
      planner_stats.dat        # optional advisory planner statistics
      degree_delta.dat         # optional signed degree deltas
      dense_hnsw_meta.dat / dense_hnsw_graph.dat   # dense-vector HNSW (only if segment has vectors)
      sparse_posting_index.dat / sparse_postings.dat  # sparse-vector posting lists
```

Open options are passed as `**kwargs` and are **not enumerated in the `.pyi`** (a documentation gap). The production wrapper opens with:

```python
# backend/app/services/overgraph/catalogs.py:282-292
db = OverGraph.open(
    str(path),
    create_if_missing=True,
    dense_vector_dimension=dimension,
    dense_vector_metric="cosine",
    wal_sync_mode="group_commit",
    edge_uniqueness=True,
)
```

Confirmed open options (from the wrapper above + vendor `METADATA`): `dense_vector_dimension` (int, fixed at open), `dense_vector_metric` (`cosine` | `euclidean` | `dot`), `wal_sync_mode` (`group_commit` default | `immediate`), `edge_uniqueness` (bool), `create_if_missing`. Two runtimes each own a directory: `OVERGRAPH_DIR/knowledge` (3072-d) and `OVERGRAPH_DIR/memory` (1536-d) — `docs/specs/overgraph-knowledge-engine.md:47-52`. Dense dimension is fixed at open and cannot change, hence the two catalogs.

**Storage engine facts** (vendor `METADATA` "Storage engine"): every mutation hits the WAL before the memtable; crash recovery replays the WAL; `group_commit` batches fsync on a ~50 ms timer ("at most one timer interval of data at risk"); `immediate` fsyncs every write. Background compaction never blocks reads/writes. `mmap`'d immutable segments — reads never block writes.

---

## 2. Nodes and edges

**Verdict:** ✅ Present (explicit node/edge model).

There **is** an explicit node/edge model, but it is *label + key* based, not a typed OOP class hierarchy. A node is a row of:

```python
class NodeView:                                  # __init__.pyi:411-421
    id: int                                      # u64, local to the DB process
    labels: list[str]                            # one or more labels
    key: str                                     # string key; identity is (label, key)
    props: dict[str, Any]                        # arbitrary properties
    weight: float
    dense_vector: list[float] | None
    sparse_vector: list[tuple[int, float]] | None
    created_at: int                              # epoch ms
    updated_at: int

class EdgeView:                                  # __init__.pyi:423-434
    id: int
    from_id: int
    to_id: int
    label: str                                   # single edge label
    props: dict[str, Any]
    weight: float
    valid_from: int                              # epoch ms
    valid_to: int                                # epoch ms (open-ended = 2**63-1)
    created_at: int
    updated_at: int
```

- A node **carries**: a `key`, one-or-more `labels`, a `weight`, arbitrary `props`, and optionally a `dense_vector` and/or `sparse_vector` (`upsert_node` — `__init__.pyi:1236-1245`). There is no dedicated `text` field; text is stored in `props` (the wrapper stores body text under `props["text"]` / `props["fact_text"]`, e.g. `write.py:113`, `write.py:246`).
- An **edge** carries `(from_id, to_id, label)`, `weight`, optional `valid_from`/`valid_to`, and `props`. Edges have **no vector** and **no stable key** (see §14).
- `id` is a **local u64**; the stable identity is the node `key` (confirmed by `model.py:1` "OverGraph u64 ids are local; `key` is the identity.").

---

## 3. Node and edge attributes / properties

**Verdict:** ✅ Present (typed scalars + nested; NOT string-only).

`props` is `dict[str, Any]` on both `upsert_node` (`__init__.pyi:1236-1245`) and `upsert_edge` (`__init__.pyi:1248-1258`). Values are JSON-like scalars plus nested lists/maps:

```python
GqlScalar = None | bool | int | float | str | bytes        # __init__.pyi:12
SchemaValueTypeName = Literal["bool","int","uint","float",  # __init__.pyi:15-25
    "number","string","bytes","array","map"]
```

- By default the DB is **open** (no schema): arbitrary keys/values are accepted.
- Optional per-label schemas can constrain properties — `PropertySchema` (`__init__.pyi:130-145`) supports `required`, `nullable`, a `types` list, numeric/string/bytes/array/map bounds, and `enum_values`. `NodeSchema`/`EdgeSchema` (`__init__.pyi:190-233`) additionally carry `additional_properties` (`allow` | `reject`), `key`, `weight`, `dense_vector`/`sparse_vector` (nodes), and edge endpoint/validity constraints. Schema setters: `set_node_schema`/`set_edge_schema`/`set_graph_schema` (`__init__.pyi:1219-1233`).
- **Project convention:** the wrapper JSON-encodes structured sub-objects into string props (`attributes_json`, `source_refs_json`, `payload_json`) — e.g. `write.py:72`, `write.py:255-261`, `mem0_store.py:103`. This is a deliberate choice (stable string comparison / dedup portability), **not** a library limitation; native `array`/`map` property types exist.

---

## 4. Exact lookups and secondary/exact indexes

**Verdict:** ✅ Present (contrary to the "assume nothing" caution — 0.17.0 *does* ship exact and indexed lookups).

Four independent exact-lookup paths exist:

1. **Node key lookup (indexed):** `get_node_by_key(label, key)` — `__init__.pyi:1261`. Each live `(label, key)` membership is unique; the query planner has a dedicated `key_lookup` node (`__init__.pyi:881`).
2. **Edge triple lookup:** `get_edge_by_triple(from_id, to_id, label)` — `__init__.pyi:1262` (backed by an `edge_triple_index`, `__init__.pyi:889`).
3. **Direct property equality:** `find_nodes(label, prop_key, prop_value) -> IdArray` — `__init__.pyi:1277`; plus paged `find_nodes_paged` (`__init__.pyi:1534`). Vendor docs: "focused equality lookups with semantic numeric equality for finite scalars."
4. **Declared secondary property indexes (exact + range):**

```python
SecondaryIndexKind = Literal["equality", "range"]           # __init__.pyi:28
SecondaryIndexState = Literal["building", "ready", "failed"] # __init__.pyi:29

class SecondaryIndexPropertyField(TypedDict):               # __init__.pyi:58-60
    source: Literal["property"]; key: str
class SecondaryIndexMetadataField(TypedDict):               # __init__.pyi:62-64
    source: Literal["metadata"]; field: NodeMetadataIndexField | EdgeMetadataIndexField
class SecondaryIndexSpecLike(TypedDict):                    # __init__.pyi:68-70
    fields: list[SecondaryIndexField]; kind: SecondaryIndexKind

def ensure_node_property_index(self, label: str, spec: SecondaryIndexSpecLike) -> NodePropertyIndexInfo: ...  # __init__.pyi:1356
def ensure_edge_property_index(self, label: str, spec: SecondaryIndexSpecLike) -> EdgePropertyIndexInfo: ...  # __init__.pyi:1359
def list_node_property_indexes(self) -> list[NodePropertyIndexInfo]: ...   # __init__.pyi:1358
def drop_node_property_index(self, label: str, spec: SecondaryIndexSpecLike) -> bool: ...  # __init__.pyi:1357
```

Indexes may be **single-field or compound** (`NodePropertyIndexInfo.compound`, `__init__.pyi:469-487`), and may target properties *or* metadata (`id`/`key`/`weight`/`created_at`/`updated_at`, plus edge `from`/`to`/`valid_from`/`valid_to` — `__init__.pyi:46-56`). `find_nodes_range(label, prop_key, lower, upper)` (`__init__.pyi:1369`) is the range counterpart.

**Limit (⚠️):** index build is **asynchronous** and stateful (`building` → `ready`/`failed`). The planner is index-transparent: when a matching declaration is `ready` it uses it; otherwise it falls back to a label-scoped scan via the same public API (planner warnings `missing_ready_index`, `using_fallback_scan`, `compound_index_prefix_not_satisfied` — `__init__.pyi:836-848`). Also the higher-level `query_node_ids`/`query_nodes` carry `allow_full_scan: bool = False` (`__init__.pyi:738`), i.e. full scans require explicit opt-in.

**Production usage:** the wrapper does **not** declare any secondary indexes today; it relies on `get_node_by_key` for identity lookups (`catalogs.py:150-155`), and on the app-level `IDENTIFIER` alias node for namespaced lookups (`research.py:244-261`). Full-property scan is done ad hoc in the admin viewer (`browse.py:64-84`).

---

## 5. Dense and sparse vector search

**Verdict:** ✅ dense + sparse + hybrid present. ❌ no encoder — vectors are supplied by the caller (BYO).

One dense vector space per DB, dimension fixed at open. Sparse vectors are `(dimension_id, weight)` pairs (`list[tuple[int, float]]`).

```python
def vector_search(
    self,
    mode: str,                     # "dense" | "sparse" | "hybrid"
    k: int,
    *,
    dense_query: list[float] | None = None,
    sparse_query: list[tuple[int, float]] | None = None,
    label_filter: NodeLabelFilter | None = None,
    ef_search: int | None = None,
    scope_start_node_id: int | None = None,      # graph-scoped search
    scope_max_depth: int | None = None,
    scope_direction: str | None = None,
    scope_edge_label_filter: list[str] | None = None,
    scope_at_epoch: int | None = None,
    dense_weight: float | None = None,           # hybrid weighting
    sparse_weight: float | None = None,
    fusion_mode: str | None = None,              # RRF / weighted score / weighted rank
) -> list[VectorHit]: ...                        # __init__.pyi:1588-1605
```

```python
class VectorHit:                                  # __init__.pyi:464-467
    node_id: int
    score: float
```

Verified from vendor `METADATA` ("Vector search"):
- **Dense:** HNSW indexes built per segment at flush time; `cosine` / `euclidean` / `dot` metrics.
- **Sparse:** inverted posting-list indexes for **exact dot-product** scoring; works with pre-computed SPLADE/BGE-M3 sparse embeddings.
- **Hybrid:** weighted-rank fusion, reciprocal-rank fusion, or weighted-score fusion; tunable `dense_weight`/`sparse_weight`.
- **Graph-scoped:** scope search to a neighborhood (`scope_start_node_id` + `scope_max_depth`).
- **Zero overhead when unused:** vector index files are only created for segments that contain vectors.

Vectors are attached to **nodes only** via `upsert_node(..., dense_vector=..., sparse_vector=...)` (`__init__.pyi:1236-1245`) and `batch_upsert_nodes`. There is **no** sparse encoder in the library — the caller must supply `sparse_query`/`sparse_vector`. This matches the spec: "Sparse-vektorer kräver en encoder som Socialism inte har." (`docs/specs/overgraph-knowledge-engine.md:103`). The wrapper currently emits dense-only search (`catalogs.py:168-189`, `retrieval.py:58` sets `mode = "hybrid" if sparse_query is not None else "dense"`).

---

## 6. Traversal

**Verdict:** ✅ Present and broad.

| Operation | Signature | Location |
|---|---|---|
| 1-hop neighbors | `neighbors(node_id, *, direction, edge_label_filter, limit, at_epoch, decay_lambda)` | `__init__.pyi:1376-1385` |
| Bounded BFS traversal | `traverse(start, max_depth, *, min_depth, direction, edge_label_filter, emit_node_label_filter, at_epoch, decay_lambda, limit, cursor)` | `__init__.pyi:1386-1399` |
| Top-K neighbors | `top_k_neighbors(node_id, k, *, direction, edge_label_filter, scoring, at_epoch, decay_lambda)` | `__init__.pyi:1400-1410` |
| Subgraph extract | `extract_subgraph(start_node_id, max_depth, *, direction, edge_label_filter, node_label_filter, at_epoch)` | `__init__.pyi:1411-1420` |
| Batch neighbors | `neighbors_batch(node_ids, *, ...)` | `__init__.pyi:1421-1429` |
| Shortest path | `shortest_path(from_id, to_id, *, direction, edge_label_filter, weight_field, at_epoch, max_depth, max_cost)` | `__init__.pyi:1466-1477` |
| Reachability | `is_connected(...)` / `all_shortest_paths(...)` | `__init__.pyi:1478-1500` |
| Degree/weight stats | `degree`, `sum_edge_weights`, `avg_edge_weight`, `degrees` | `__init__.pyi:1432-1463` |
| Personalized PageRank | `personalized_pagerank(seed_node_ids, *, algorithm, damping_factor, max_iterations, epsilon, approx_residual_tolerance, edge_label_filter, max_results)` | `__init__.pyi:1550-1561` |
| Connected components | `connected_components(...)` / `component_of(node_id, ...)` | `__init__.pyi:1571-1585` |

Notes:
- Traversal is **breadth-first** (`traverse`); no DFS primitive is exposed. Exact depth slices are expressed as `min_depth`/`max_depth` (e.g. `traverse(start, 2, min_depth=2)`).
- PPR exposes both exact power-iteration and `algorithm="approx"` (forward-push) — the wrapper uses `approx` (`retrieval.py:119-122`).
- `shortest_path` supports BFS (unweighted) or bidirectional Dijkstra (via `weight_field`).
- `direction` is `"outgoing" | "incoming"` (wrapper uses both, e.g. `write.py:287`, `research.py:233`).
- `decay_lambda` scales edge weights by `exp(-lambda * age_hours)`.
- `at_epoch` enables point-in-time traversal over edge `valid_from`/`valid_to`.

---

## 7. Relations between different node types

**Verdict:** ✅ Present.

Edges connect arbitrary node ids; there is **no** type restriction by default. `upsert_edge(from_id, to_id, label, ...)` (`__init__.pyi:1248-1258`) takes plain integer ids and a single string label. Cross-label edges are the norm in the wrapper (e.g. `Fact → SUBJECT → Entity`, `TextUnit → SUPPORTS → Fact`, `DocumentVersion → CONTAINS → TextUnit` — `write.py:129-136`, `write.py:269-273`).

Optional per-edge-label constraints on endpoint labels exist via `EdgeSchema.from`/`EdgeSchema.to` (`EndpointLabelSchema`, `__init__.pyi:177-180, 208-220`), including `allow_self_loops` — but they are opt-in and unused by the wrapper.

---

## 8. Batch writes

**Verdict:** ✅ Present.

```python
def batch_upsert_nodes(self, nodes: list[dict[str, Any]]) -> list[int]: ...   # __init__.pyi:1268
def batch_upsert_edges(self, edges: list[dict[str, Any]]) -> list[int]: ...   # __init__.pyi:1269
def get_nodes(self, node_ids: list[int]) -> list[NodeView | None]: ...        # __init__.pyi:1270
def get_nodes_by_keys(self, keys: list[dict[str, Any]]) -> list[NodeView | None]: ...  # __init__.pyi:1271
def graph_patch(self, patch: dict[str, Any]) -> PatchResult: ...              # __init__.pyi:1273
def batch_upsert_nodes_binary(self, buffer: bytes) -> list[int]: ...          # __init__.pyi:1372
def batch_upsert_edges_binary(self, buffer: bytes) -> list[int]: ...          # __init__.pyi:1373
def ingest_mode(self) -> None: ...                                            # __init__.pyi:1524
def end_ingest(self) -> CompactionStats | None: ...                           # __init__.pyi:1525
```

- `graph_patch` is **atomic**: it upserts nodes, upserts edges, deletes nodes/edges, and invalidates edges in a single operation. The wrapper exposes it as `Catalog.graph_patch(upsert_nodes=..., upsert_edges=..., invalidate_edges=..., delete_node_ids=..., delete_edge_ids=...)` (`catalogs.py:132-148`).
- `batch_upsert_nodes` amortizes WAL + memtable overhead (vendor claims 1.29M+ nodes/s); a packed binary variant is also available.
- Bulk ingest: `ingest_mode()` disables auto-compaction during large bursts, `end_ingest()` compacts and restores normal behavior (`ingest.py:56-66`).
- **GroupCommit** is the durability mode (`wal_sync_mode="group_commit"`, set at `catalogs.py:289`), not a separate API — see §13.

---

## 9. Updates and deletions

**Verdict:** ✅ Present.

```python
def upsert_node(self, labels, key, *, props, weight, dense_vector, sparse_vector) -> int: ...  # __init__.pyi:1236-1245
def upsert_edge(self, from_id, to_id, label, *, props, weight, valid_from, valid_to) -> int: ...  # __init__.pyi:1248-1258
def delete_node(self, node_id: int) -> None: ...        # __init__.pyi:1263
def delete_edge(self, edge_id: int) -> None: ...        # __init__.pyi:1264
def invalidate_edge(self, edge_id: int, valid_to: int) -> EdgeView | None: ...  # __init__.pyi:1265
def prune(self, *, max_age_ms, max_weight, label) -> PruneResult: ...          # __init__.pyi:1503-1509
def set_prune_policy(self, name, *, max_age_ms, max_weight, label) -> None: ...  # __init__.pyi:1510-1517
```

- **Upsert semantics** (vendor `METADATA`): a node key that resolves to the same node through supplied labels is updated; if supplied label memberships resolve to *different* nodes, the write is rejected as a conflict. Multi-label nodes own the same key in every label they carry.
- **Deletion:** `delete_node` (incident edges cascade — vendor docs: "Incident edges cascade automatically"), `delete_edge` by id.
- **Temporal invalidation:** `invalidate_edge` marks an edge invalid at `valid_to` **without deleting it**, preserving history. The wrapper uses `valid_from`/`valid_to` on structural edges (`write.py:129-136`) and stores validity as ms props on nodes (`write.py:121-122`).
- **Prune:** manual `prune` and named `set_prune_policy` policies applied during compaction; nodes matching a policy are invisible to reads immediately (lazy expiration) and removed at the next compaction. ⚠️ The spec forbids using `prune` against memories mem0 still owns (`docs/specs/overgraph-knowledge-engine.md:132`).

---

## 10. Concurrent reads / writes

**Verdict:** ⚠️ Present but limited — single-process, single-writer, no multi-reader MVCC.

- **Embedded, in-process.** "No separate process. No socket. Your database is a folder on disk." (`METADATA`). There is **no lock file** in the on-disk layout and **no multi-process coordination API**. The on-disk `manifest.current`, `wal_*.wal`, `segments/` contain no `.lock`.
- **Reads never block writes** (mmap'd immutable segments + memtable), and background compaction runs on a thread without blocking reads/writes (`METADATA` "Storage engine").
- **Writes are single-writer.** The concurrency primitive is `begin_write_txn()` → `WriteTxn` with **optimistic conflict detection** (`METADATA` "Explicit write transactions"), i.e. a write transaction that commits atomically or fails with a conflict for retry.
- **No MVCC read snapshots.** The `.pyi` is explicit that traversal pagination does not promise snapshot isolation: the vendor docstring-like note ("strict snapshot isolation across intervening writes is not promised") is reflected in the fact that there is no read-transaction/snapshot API anywhere in the stubs. Reads merge memtable + segments and verify against "latest visible records".
- **Application-level lock:** the wrapper wraps each catalog in a `threading.RLock` (`catalogs.py:68`) and runs reads/writes under it, with the explicit assumption "One writer process; callers use the runtime" (`catalogs.py:1`). The planned `tenant.lock` in the spec (`docs/specs/overgraph-knowledge-engine.md:54`) is an app-level lifecycle lock, not an OverGraph feature.

**Implication:** OverGraph is safe for a single process with one writer thread at a time (our runtime's RLock + `RELOAD=0` model). It is **not** a multi-process ACID database; a second `open()` on the same directory from another process is unsupported/undefined by this API surface.

---

## 11. Backup and restore

**Verdict:** ⚠️ Present but limited — copy-the-directory only; no snapshot API.

- No `snapshot`, `backup`, `checkpoint`, or `restore` method exists in the `.pyi` or runtime method list.
- The supported backup path is filesystem copy: "Each database is a self-contained directory. `cp -r ./my-db /backup/my-db` and you're done." (`METADATA`).
- Integrity checking exists to validate a copy: `scrub_path(path, *, validate_wal, include_orphan_segments, check_manifest_stability) -> DatabaseScrubReport` (`__init__.pyi:1178-1184`) and `db.scrub()` (`__init__.pyi:1206`). The `DatabaseScrubFindingTypeName` enum (`__init__.pyi:30-42`) covers `WalCorrupt`, `OrphanSegment`, `ManifestFileInvalid`, etc. — evidence that a copied directory can be verified.
- `db.stats() -> DbStats` (`__init__.pyi:396-409`) exposes WAL/segment/tombstone state (`pending_wal_bytes`, `segment_count`, `node_tombstone_count`, `active_wal_generation_id`, …), useful to reason about durability but not a backup primitive.
- ⚠️ No online/consistent snapshot guarantee while a writer is active — a `cp -r` of a live directory is only safe if writes are quiesced (`sync()`/`flush()` first).

---

## 12. Export and import

**Verdict:** ⚠️ Present but limited — adjacency-only export; no import; no full serialization.

```python
def export_adjacency(self, *, node_label_filter=None, edge_label_filter=None, include_weights=True) -> AdjacencyExport: ...  # __init__.pyi:1562-1568

class AdjacencyExport:                             # __init__.pyi:712-718
    node_ids: list[int]
    node_labels: list[str]
    node_label_indexes: list[list[int]]
    edge_labels: list[str]
    edges: list[ExportEdge]                        # from_id, to_id, edge_label_index, weight
```

- `export_adjacency` exports **structure only** — node ids, node label strings, edge label strings, and edges with optional weights. It does **not** export node/edge `props`, vectors, keys, or validity windows.
- There is **no import** API and no full graph serialization (no JSON/binary dump/load). GQL `CREATE`/`MERGE` statements can be used to *script* an import, but there is no `import`/`restore` primitive.
- **Gap:** a faithful export/import of the knowledge graph (keys + props + vectors + temporal edges) would need to be built on top of `batch_upsert_nodes`/`graph_patch` (or GQL), not a single library call.

---

## 13. Transactions / ACID

**Verdict:** ⚠️ Present but limited — atomic commit + WAL durability + rollback exist; **full ACID (I in particular) does not**.

What **is** present:

```python
def begin_write_txn(self) -> WriteTxn: ...          # __init__.pyi:1274

class WriteTxn:                                     # __init__.pyi:1607-1668
    def upsert_node(...) -> dict[str, Any]: ...      # aliases/read-own-writes
    def upsert_node_as(alias, ...) -> dict[str, Any]: ...
    def upsert_edge(...) / upsert_edge_as(...): ...
    def delete_node(target) / delete_edge(target) / invalidate_edge(target, valid_to): ...
    def stage(self, operations: list[dict[str, Any]]) -> None: ...
    def get_node(target) / get_edge(target) / get_node_by_key(...) / get_edge_by_triple(...): ...
    def commit(self) -> TxnCommitResult: ...          # atomic commit
    def rollback(self) -> None: ...
```

`TxnCommitResult` (`__init__.pyi:441-446`) returns `node_ids`, `edge_ids`, `node_aliases`, `edge_aliases` — aliases support referential writes inside one txn. Vendor docs: "ordered staging, rollback, read-own-writes point lookups, local aliases, atomic commit, and clean conflict errors for retry loops" — i.e. **optimistic concurrency** on commit.

- **Atomicity** ✅ — single ops, `graph_patch`, and `WriteTxn.commit()` are atomic (GQL mutation explain exposes `atomic_commit`/`uses_write_txn`, `__init__.pyi:1058-1061`).
- **Durability** ✅/⚠️ — WAL-first write path with crash replay; `sync()` (`__init__.pyi:1522`) forces durability, and `wal_sync_mode` is configurable (`group_commit` default = up to ~one 50 ms interval at risk; `immediate` = fsync per write). `flush()` (`__init__.pyi:1523`) freezes/flushes the memtable to a segment. The wrapper calls `catalog.sync()` after publishing a node that must be durable before reuse (`publish.py:116`; spec §7 "Publicerad reuse → sync()").
- **Isolation** ❌/⚠️ — **no MVCC and no snapshot reads**. Reads see the latest visible state merged across memtable + segments; traversal cursors explicitly do **not** promise snapshot isolation across intervening writes. There is no `begin_read_txn` / read snapshot.
- **Consistency** ⚠️ — optional schemas can enforce constraints (`set_node_schema`/`set_edge_schema`, `__init__.pyi:1219-1228`), but they are opt-in and the DB is open by default.

**Bottom line:** OverGraph 0.17.0 gives you *atomic write transactions with rollback and WAL durability*, but it is **not ACID in the SQL sense** — there is no multi-statement read isolation, and it is single-writer. It is best characterized as "eventually-consistent on read (no snapshots) with atomic, durable writes."

---

## 14. Edge uniqueness / keys / validity / weight

**Verdict:** ✅ uniqueness + validity + weight present; ❌ no stable edge key, ❌ no edge embeddings.

- **Uniqueness:** optional `edge_uniqueness=True` (set at `catalogs.py:290`) enforces uniqueness on `(from, to, label)`. Without it, duplicate triples are allowed. `get_edge_by_triple(from_id, to_id, label)` (`__init__.pyi:1262`) is the exact lookup; the planner has an `edge_triple_index` (`__init__.pyi:889`).
- **Validity:** `valid_from` / `valid_to` on edges (`upsert_edge`, `__init__.pyi:1248-1258`; `EdgeView.valid_from/valid_to`), queried via `at_epoch` on traversal/shortest-path calls. `invalidate_edge` sets `valid_to` without deleting. The wrapper's browse layer treats `2**63-1` as open-ended (`browse.py:10, 233-236`).
- **Weight:** every node and edge has a `weight: float` (default `1.0`), used as the ranking signal (spec: "`weight` är OverGraphs rankningssignal, inte identitet." — `docs/specs/overgraph-knowledge-engine.md:64`).
- **No stable edge key / no edge embedding:** edges are addressed by auto-assigned u64 `id` only; they carry no `key` field and no vector (`EdgeView` — `__init__.pyi:423-434`). This matches the spec: "Kanter har `valid_from`/`valid_to` och `weight`, men ingen stabil `key` och ingen embedding." (`docs/specs/overgraph-knowledge-engine.md:58`).

---

## 15. Label/scope filtering in vector search

**Verdict:** ✅ label-only filter present (as the spec requires); ⚠️ no arbitrary-property filter inside `vector_search`.

`vector_search(..., label_filter: NodeLabelFilter | None)` (`__init__.pyi:1595`) accepts a label filter only. There is **no** `prop_filter`/`filter` argument on `vector_search`. The wrapper drives tenant isolation *through labels* before top-k, exactly as the spec mandates:

```python
# backend/app/services/overgraph/catalogs.py:259
"label_filter": {"labels": [kind, scope], "mode": "all"},   # kind=Fact|TextUnit, scope=scope.shared|scope.customer.{id}
```

and `scoped_type_search` iterates each visible scope label separately and merges (`catalogs.py:247-263`). The spec's rationale is explicit: "`vector_search` filtrerar på nodlabel, inte på godtycklig property. … Isolering ska därför sitta i labeln före top-k." (`docs/specs/overgraph-knowledge-engine.md:84-85`).

- **Post-filter for other predicates:** arbitrary property equality/range filtering is available on the *query* APIs (`find_nodes`, `find_nodes_range`, `query_node_ids`/`query_nodes` with `filter`) but **not** combined with vector similarity in one call. If a future need is "vector search filtered on a property that is not a label," it must be done as a two-step (vector search → property verify) or by promoting the property to a label.
- **PPR does not filter on tenant** either (`personalized_pagerank` has only `edge_label_filter`, no node/property filter — `__init__.pyi:1550-1561`), which is why the wrapper filters visibility after ranking (`retrieval.py:104-129` + `is_visible` in `isolation.py:13-18`).

---

## 16. Async API

**Verdict:** ✅ Present.

`async_api.py` provides a full async mirror. It is a thin `asyncio.to_thread()` wrapper over the sync API (releasing the GIL), **not** a native async engine:

```python
"""Async wrapper for OverGraph using asyncio.to_thread()."""   # async_api.py:1

class AsyncOverGraph:                                          # async_api.py:224
    @staticmethod
    async def open(path: str, **kwargs: Any) -> AsyncOverGraph: ...  # async_api.py:235-238 (to_thread)
    async def close(self, force: bool = False) -> None: ...
    # ... one async method per sync method, e.g. upsert_node, vector_search, execute_gql

class AsyncWriteTxn:                                           # async_api.py:60-222
    # wraps WriteTxn with an asyncio.Lock so staged writes/reads/commit/rollback
    # preserve caller await order on this transaction (async_api.py:63-71)
```

- `AsyncOverGraph` mirrors the full sync surface (`__init__.pyi:1674-1881`), including `vector_search`, `execute_gql`, schemas, indexes, traversal, analytics, maintenance.
- `AsyncWriteTxn` wraps the sync `WriteTxn`, serializing operations with an `asyncio.Lock` (`async_api.py:71`).
- `async_scrub_path(path, **options)` wraps `scrub_path` (`async_api.py:56-57`).
- **Runtime note (docs gap):** `async_api.py` also exposes two methods **not** in the `.pyi` — `query_pattern` (`async_api.py:559-560`) and `explain_pattern_query` (`async_api.py:580-581`) — which call `self._db.query_pattern` / `self._db.explain_pattern_query`. Those sync methods *do* exist on the compiled module at runtime (introspection confirmed `hasattr(OverGraph, "query_pattern") == True`) but are **undocumented in the 0.17.0 stubs** (legacy names, superseded by `query_graph_rows`/`explain_graph_rows`). Dead/undocumented surface; not used by the wrapper.
- **Concurrency caveat:** because it runs the (single-writer) sync engine on a thread pool, an `AsyncOverGraph` shared across coroutines still serializes writes through the underlying engine and the `Catalog` RLock; it does not add multi-writer capability.

---

## Mem0 integration

**What it is:** OverGraph serves as a `VectorStoreBase` adapter so self-hosted `mem0ai==2.0.20` (pinned in `pyproject.toml:20`) persists and retrieves expert memory in the process-owned `memory` catalog instead of Mem0 Platform Graph Memory (`docs/specs/overgraph-knowledge-engine.md:126-132`).

**Registration hack** (`mem0_patch.py:16-34`): Mem0's `VectorStoreFactory`/`VectorStoreConfig` have no clean `register` path for a new provider, so the adapter patches three things at import time:
1. `VectorStoreConfig.__private_attributes__["_provider_configs"].default[PROVIDER] = CONFIG_CLASS` (`mem0_patch.py:25-26`) — because the pydantic-compiled validator reads that private default map.
2. Injects a synthetic module `mem0.configs.vector_stores.overgraph` with `OverGraphMem0Config` into `sys.modules` (`mem0_patch.py:27-30`) — because the config validator imports `mem0.configs.vector_stores.<provider>` (`mem0/vector_stores/configs.py:46-53`).
3. `VectorStoreFactory.provider_to_class["overgraph"] = "app.services.overgraph.mem0_store.OverGraphVectorStore"` (`mem0_patch.py:31-33`).

(`VectorStoreFactory.register_provider` *does* exist at `mem0/utils/factory.py:128`, but it does not satisfy the config-import path, so the manual patch above is still required.)

**Adapter** (`mem0_store.py:52-192`, `class OverGraphVectorStore(VectorStoreBase)`):
- `insert(vectors, payloads, ids)` → per-vector `_upsert`: `catalog.upsert_node(labels=[MEMORY|MEMORY_ENTITY, user.{id}?, agent.{key}?], key=memory_id, props={payload_json, user_id, agent_id, collection}, dense_vector=vector)` (`mem0_store.py:91-109`); `linked_memory_ids` become `LINKED` edges (`mem0_store.py:110-113`).
- `search(query, vectors, top_k, filters)` → `catalog.vector_search("dense", {dense_query, label_filter={labels, mode:"all"}})` filtered by `user_id`/`agent_id` labels **before** top-k, then payload-verified, then neighbor count attached (`mem0_store.py:115-143`).
- `update` merges payload and re-upserts, preserving the existing dense vector if none supplied (`mem0_store.py:80-89`).
- `delete(vector_id)` → `catalog.delete_node(engine_id)` (removes node; incident `LINKED` edges cascade — spec acceptance #11) (`mem0_store.py:145-148`).
- `list(filters, top_k)` → dense search with a dummy zero-vector and `k=top_k or 10_000` (`mem0_store.py:157-177`).
- `get`, `list_cols`, `col_info` return mem0's expected shapes; `create_col`/`delete_col`/`reset` are no-ops (`mem0_store.py:71-72, 182-192`).

**Key facts:**
- The adapter uses **dense-only** search (`mode="dense"`) and does **not** invent a sparse encoder (`docs/specs/overgraph-knowledge-engine.md:130`).
- The memory catalog is 1536-d (`text-embedding-3-small`); knowledge is 3072-d (`text-embedding-3-large`) — separate directories (`docs/specs/overgraph-knowledge-engine.md:49-50`).
- Expert chat calls mem0 (which calls OverGraph); the store is never called directly by chat code (`mem0_store.py:1`).

---

## (a) Features PRESENT in 0.17.0

- Directory-based persistent storage (LSM + WAL + manifest + immutable segments) with `open(path, **kwargs)`, `close`, `stats`, `scrub`.
- Explicit node/edge model: multi-label nodes with a `key` + `weight` + `props` + optional dense/sparse vector; edges `(from,to,label)` with `weight`, `valid_from/valid_to`, `props`.
- Typed (not string-only) arbitrary properties; optional per-label schemas/constraints.
- Exact lookups: `get_node_by_key`, `get_edge_by_triple`, `find_nodes`/`find_nodes_range`, and **declared secondary property indexes** (equality + range, single + compound) via `ensure_node/edge_property_index`.
- Dense (HNSW) + sparse (posting-list, exact dot product) + hybrid vector search with fusion, plus graph-scoped search.
- Broad traversal: `neighbors`, `traverse` (BFS), `top_k_neighbors`, `extract_subgraph`, `neighbors_batch`, `shortest_path`, `is_connected`, `all_shortest_paths`, `degree`/`degrees`, `personalized_pagerank` (exact + approx), `connected_components`, `component_of`.
- Cross-type edges (no type restriction).
- Batch writes: `batch_upsert_nodes/edges` (+ binary), atomic `graph_patch`, `ingest_mode`/`end_ingest`, `get_nodes_by_keys`.
- Upsert/delete/invalidate/prune (manual + named policies).
- Write transactions: `begin_write_txn` → `WriteTxn` (stage/rollback/read-own-writes/atomic commit, optimistic conflict detection).
- Durability controls: `sync()`, `flush()`, `wal_sync_mode` (`group_commit`/`immediate`).
- Full async mirror (`AsyncOverGraph` / `AsyncWriteTxn`) via `asyncio.to_thread`.
- GQL query language (`execute_gql`, mutations, schema DDL, property-index DDL, explain/profile).

## (b) Features PRESENT BUT LIMITED

- **Exact property index:** async build lifecycle (`building/ready/failed`); planner falls back to label-scoped scan until `ready`; full scans require `allow_full_scan` opt-in.
- **Concurrency:** single-process, single-writer; no multi-process support; no lock file. In-process safety is enforced by the wrapper's `threading.RLock` + one-runtime model.
- **Transactions/ACID:** atomic + durable writes with rollback, but **no read snapshots / MVCC** and single-writer — not full ACID (I is absent).
- **Backup/restore:** `cp -r` the directory only; no snapshot API; `scrub` for integrity verification; live-copy safety depends on quiescing writes.
- **Export/import:** `export_adjacency` (structure + labels + weights) only; no props/vectors/keys in export; no import.
- **Sparse vectors:** supported at the engine level, but no encoder is bundled — caller must supply sparse embeddings.
- **Vector-search filtering:** label-only filter; no arbitrary property predicate combined with vector similarity.
- **Async:** correctness of `AsyncWriteTxn` ordering is preserved by an `asyncio.Lock`, but the engine underneath is still single-writer.

## (c) Features ABSENT — would require development

1. **Full multi-reader / snapshot isolation (MVCC):** no `begin_read_txn`, no point-in-time read snapshot. Applications needing consistent multi-read views must implement read-side versioning themselves.
2. **Multi-process / multi-writer access:** no lock file or distributed coordination; a second `open()` on the same directory is out of scope for this API.
3. **Backup/snapshot API:** nothing beyond `cp -r`; a consistent online snapshot mechanism must be built (e.g. quiesce + `sync()`/`flush()` + copy, then `scrub`).
4. **Full graph export/import:** no serialization of keys/props/vectors/validity; a faithful dump/load must be composed from `batch_upsert_nodes`/`graph_patch` or GQL.
5. **Sparse encoder:** the library indexes sparse vectors but does not produce them; a SPLADE/BGE-M3 encoder (or equivalent) is a project dependency, not an OverGraph feature.
6. **Arbitrary-property filtering inside vector search:** property predicates would need a post-filter pass or a property promoted to a label.
7. **Exact secondary index on a *specific* typed property used by our wrapper:** the capability exists in the engine, but the current wrapper declares **no** indexes (`ensure_node_property_index` is never called). Wiring one for hot lookups (e.g. `status`, `ordinal`, `scope_key`) is development work, not available today in the running system.

---

### Source files inspected

- `backend/.venv/lib/python3.13/site-packages/overgraph/__init__.pyi` (1899 lines)
- `backend/.venv/lib/python3.13/site-packages/overgraph/__init__.py` (139 lines)
- `backend/.venv/lib/python3.13/site-packages/overgraph/async_api.py` (1147 lines)
- `backend/.venv/lib/python3.13/site-packages/overgraph-0.17.0.dist-info/METADATA` (vendor README, 25924 bytes)
- `backend/app/services/overgraph/{__init__,model,write,retrieval,browse,catalogs,ingest,isolation,labels,mem0_patch,mem0_store,publish,research}.py`
- `docs/specs/overgraph-knowledge-engine.md`
- `backend/pyproject.toml`, `backend/uv.lock`
