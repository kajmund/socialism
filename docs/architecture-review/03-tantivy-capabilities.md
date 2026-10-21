# Tantivy Capability Inventory (Python binding `tantivy==0.26.2`)

> Read-only inventory. No code was modified.
>
> **Scope.** The `tantivy` Python binding surface (type stubs are ground truth), the
> `overgraph_ingest` experiment's actual Tantivy usage, the frozen BM25 v1 results,
> and the OverGraph graph model that the BM25 index is built from.
>
> **Authoritative API source:** `experiments/overgraph_ingest/.venv/lib/python3.13/site-packages/tantivy/tantivy.pyi` (714 lines, complete binding surface).
> Confirmed installed version: `tantivy 0.26.2` (dist-info `METADATA`, `Requires-Python >=3.10`), `overgraph 0.17.0`.

---

## 1. Binding surface inventory (`tantivy.pyi`)

### 1.1 `SchemaBuilder` — field types

The binding exposes **ten** field types plus a `FieldType` enum. Field types are
declared by method name; there is **no** generic `add_field(type=...)`.

| Method | Underlying type | `FieldType` enum member | Options |
|---|---|---|---|
| `add_text_field(name, stored=False, fast=False, tokenizer_name="default", index_option="position")` | text | `FieldType.Text` | `index_option`: `"basic"`, `"freqs"`, `"position"` |
| `add_integer_field(name, stored=False, indexed=False, fast=False)` | **i64** | `FieldType.Integer` | stored/indexed/fast |
| `add_unsigned_field(name, stored=False, indexed=False, fast=False)` | **u64** | `FieldType.Unsigned` | stored/indexed/fast |
| `add_float_field(name, stored=False, indexed=False, fast=False)` | **f64** | `FieldType.Float` | stored/indexed/fast |
| `add_boolean_field(name, stored=False, indexed=False, fast=False)` | bool | `FieldType.Boolean` | stored/indexed/fast |
| `add_date_field(name, stored=False, indexed=False, fast=False)` | `datetime.datetime` | `FieldType.Date` | stored/indexed/fast |
| `add_json_field(name, stored=False, fast=False, tokenizer_name="default", index_option="position", expand_dots_enabled=False)` | JSON | `FieldType.Json` | stored/fast/tokenizer/index_option/expand_dots |
| `add_facet_field(name)` | hierarchical facet | `FieldType.Facet` | (no stored/indexed flags — always indexed) |
| `add_bytes_field(name, stored=False, indexed=False, fast=False, index_option="position")` | bytes | `FieldType.Bytes` | stored/indexed/fast/index_option |
| `add_ip_addr_field(name, stored=False, indexed=False, fast=False)` | IP address | `FieldType.IpAddr` | stored/indexed/fast |

- `SchemaBuilder.is_valid_field_name(name) -> bool` (line 14) validates field names.
- `SchemaBuilder.build() -> Schema` (line 108). `Schema` is an **opaque class** (`class Schema: pass`, line 8) — no introspection methods.

**Notable naming:** there are no `add_i64_field`/`add_u64_field`/`add_f64_field`
aliases — signed int is `add_integer_field`, unsigned is `add_unsigned_field`.
`FieldType` enum (`tantivy.pyi` lines 207–217): `Text, Unsigned, Integer, Float,
Boolean, Date, Facet, Bytes, Json, IpAddr`.

### 1.2 `Document` (field container — the closest thing to `Field`)

There is **no `Field` class** in the binding; field handles are addressed by
string name. `Document` (`tantivy.pyi` lines 139–198) is the container:

- Mutators: `add_text`, `add_unsigned`, `add_integer`, `add_float`, `add_boolean`,
  `add_date`, `add_facet`, `add_bytes`, `add_json`, `add_ip_addr`.
- Bulk: `Document(**kwargs)`, `Document.from_dict(py_dict, schema=None)`,
  `extend(py_dict, schema=None)`, `to_dict()`, `__getitem__`.
- Reads: `get_first(field_name)`, `get_all(field_name)`, `num_fields`, `is_empty`.

### 1.3 `Query` — query types (`tantivy.pyi` lines 227–372)

| Query builder | Signature highlights |
|---|---|
| `Query.term_query(schema, field_name, field_value, index_option="position")` | **exact match** on one field value |
| `Query.term_set_query(schema, field_name, field_values)` | OR of terms in one field |
| `Query.boolean_query(subqueries: [(Occur, Query)], minimum_number_should_match=None)` | MUST/SHOULD/MUST_NOT |
| `Query.all_query()` / `Query.empty_query()` | match all / match none |
| `Query.exists_query(fast_field_name, json_subpaths=False)` | field-presence |
| `Query.fuzzy_term_query(schema, field_name, text, distance=1, transposition_cost_one=True, prefix=False)` | Levenshtein fuzzy |
| `Query.phrase_query(schema, field_name, words, slop=0)` | ordered phrase |
| `Query.phrase_prefix_query(schema, field_name, words)` | phrase with prefix tail |
| `Query.regex_query(schema, field_name, regex_pattern)` | full regex |
| `Query.regex_phrase_query(schema, field_name, words, slop=0)` | regex on phrase terms |
| `Query.range_query(schema, field_name, field_type, lower_bound, upper_bound, include_lower, include_upper, use_inverted_index=False)` | typed range filter |
| `Query.disjunction_max_query(subqueries, tie_breaker=None)` | DisMax |
| `Query.boost_query(query, boost)` | score boost |
| `Query.const_score_query(query, score)` | constant score |
| `Query.more_like_this_query(doc_address, ...)` / `more_like_this_document_fields_query(schema, document_fields, ...)` | MLT |
| `Query.and_must_match(*queries)` / `and_must_not_match(*queries)` / `or_should_match(*queries)` | fluent boolean wrappers |
| `Query.explain(searcher, doc_address) -> Explanation` | score explanation |

- `Occur` enum (`tantivy.pyi` lines 201–204): `Must`, `Should`, `MustNot` — i.e.
  the boolean operators are exposed.
- `Explanation.to_json()` (line 375) returns the per-doc score breakdown.

### 1.4 `Searcher` / `SearchResult` (`tantivy.pyi` lines 397–454)

- `Searcher.search(query, limit=10, count=True, order_by_field=None, offset=0, order=Order.Desc, weight_by_field=None) -> SearchResult`
  — **`offset`, `order_by_field`, `Order.Asc/Desc`, and `weight_by_field` are all exposed.**
- `SearchResult.hits -> list[tuple[Any, DocAddress]]` — `(score, doc_address)` pairs.
  ⚠️ `SearchResult.count` is **used by the experiment** (`bm25.py` lines 323, 419)
  but is **not declared** in the stubs (runtime-only attribute).
- `Searcher.aggregate(query, agg_dict) -> dict` — aggregations (thin dict-based wrapper).
- `Searcher.num_docs`, `Searcher.num_segments`, `Searcher.doc(doc_address)`,
  `Searcher.fast_field_values(field_name, doc_addresses)`, `Searcher.doc_freq(field_name, field_value)`,
  `Searcher.terms_with_prefix(field_name, prefix, filter_query=None, limit=None)`,
  `Searcher.cardinality(query, field_name)`.
- `DocAddress(segment_ord, doc)` (lines 384–395) is exposed — segment ordinal + local doc id.
- There is **no `TopDocs` and no `IndexReader`** class; `Searcher` is obtained
  directly from `Index.searcher()`.

### 1.5 `Index` / `IndexWriter` (`tantivy.pyi` lines 456–570)

- `Index(schema, path=None, reuse=True)` — `path=None` = in-RAM index.
- `Index.open(path)` — open existing; `Index.exists(path)`, `Index.is_compatible(path)`.
- `Index.writer(heap_size=128_000_000, num_threads=0) -> IndexWriter`.
- `Index.config_reader(reload_policy="commit", num_warmers=0)` — reader reload policy (default `"commit"`).
- `Index.searcher() -> Searcher`, `Index.reload()`, `Index.schema`.
- `Index.parse_query(query, default_field_names=None, field_boosts=None, fuzzy_fields=None, conjunction_by_default=False, allow_regexes=False)` and
  `parse_query_lenient(...)` — the QueryParser is surfaced on `Index`.
- `Index.register_tokenizer(name, TextAnalyzer)` and `register_fast_field_tokenizer(name, TextAnalyzer)`.
- Module-level `parse_query(query) -> dict` / `parse_query_lenient(query) -> tuple[dict, list[dict]]` (lines 685–712) return a query **AST dict** (not a `Query`).

`IndexWriter` methods: `add_document(doc)`, `add_json(json)`, `commit() -> opstamp`,
`rollback()`, `garbage_collect_files()`, `delete_all_documents()`,
`delete_documents(field_name, field_value)` (deprecated alias),
`delete_documents_by_term(field_name, field_value)`,
`delete_documents_by_query(query)`, `wait_merging_threads()`,
`commit_opstamp` property, context-manager `__enter__`/`__exit__`.

### 1.6 Tokenizers / analyzers (`tantivy.pyi` lines 608–683)

- `Tokenizer`: `raw()`, `simple()`, `whitespace()`, `regex(pattern)`,
  `ngram(min_gram=2, max_gram=3, prefix_only=False)`, `facet()`.
- `Filter`: `alphanum_only()`, `ascii_fold()`, `lowercase()`,
  `remove_long(length_limit)`, **`stemmer(language)`**, **`stopword(language)`**,
  `custom_stopword(stopwords)`, `split_compound(constituent_words)`.
- `TextAnalyzerBuilder(tokenizer).filter(filter).build() -> TextAnalyzer`; `TextAnalyzer.analyze(text) -> list[str]`.

`stemmer(language)` delegates to Rust `rust-stemmers` (Snowball), which includes
**`"swedish"`**. `stopword(language)` uses the tantivy stopword lists (includes a
Swedish list). There is no Python-level stemmer/stopword *list* exposed — only the
language-tagged filters.

### 1.7 Highlighting

`SnippetGenerator.create(searcher, query, schema, field_name)`,
`SnippetGenerator.snippet_from_doc(doc)`, `set_max_num_chars(...)`;
`Snippet.to_html()`, `highlighted() -> list[Range]`, `fragment()` (`tantivy.pyi` lines 583–605).

---

## 2. Verification of the 11 capability questions

### Q1 — Exact lookups on typed fields

**Supported.** `Query.term_query(schema, field_name, field_value)` is the exact
`field == value` primitive, and works for every indexed field type (text, i64, u64,
f64, bool, date, bytes, json, ip). For **string** exact match the text field must use
`tokenizer_name="raw"` (no tokenization/lowercasing) — which is exactly what the
experiment does for its identifier fields. There is no separate `Field` object;
fields are referenced by name.

### Q2 — TermQuery and BooleanQuery

**Fully exposed.** `Query.term_query`, `Query.term_set_query`, and
`Query.boolean_query([(Occur, Query), ...], minimum_number_should_match=...)` with
`Occur.Must / Occur.Should / Occur.MustNot`. Fluent helpers
`and_must_match` / `and_must_not_match` / `or_should_match` also exist.

### Q3 — Fulltext search and BM25

**Supported, with fixed scoring.** `Index` → `Searcher` → `search()`. The scorer is
Tantivy's **default BM25**; there is **no scoring customization** in the binding —
no custom `Similarity`, no k1/b tuning knobs (the experiment only *documents*
k1=1.2 / b=0.75 as "Tantivy default", `bm25.py` lines 29–30, 282–287). The only
scoring levers exposed are `Query.boost_query`, `Query.const_score_query`,
`Query.disjunction_max_query` tie-breaker, and `Searcher.search(weight_by_field=...)`.

### Q4 — Swedish analyzers / tokenization

**Supported via language-tagged filters.** `Filter.stemmer("swedish")` and
`Filter.stopword("swedish")` are available; no explicit "Swedish stemmer class" or
stopword *list* is exported. The experiment configured Swedish as
`simple` tokenizer → `lowercase` → `stemmer("swedish")`, **with no stopword filter**
(`bm25.py` lines 44–52, 65–70; README lines 263–268). A second `sv_plain_v1` profile
drops the stemmer.

### Q5 — Filtering on document and tenant

**Combined via boolean + typed/range filters.** The experiment filters
`document_id` and `collection_id` using text fields with `tokenizer_name="raw"` +
`term_query` wrapped as `Occur.Must` clauses (`bm25.py` lines 75–92, 363–376).
Typed range filtering is available via `Query.range_query(..., field_type, lower, upper, ...)`
over `FieldType.Integer/Unsigned/Float/Date/...`. **Facets** are exposed for
indexing (`add_facet_field`, `Facet.from_string/path/root`, `Document.add_facet`)
but there is **no `facet_query`/`facet_prefix_query`** builder in `Query` — hierarchical
facet filtering is not first-class in this stub surface.

### Q6 — Stable pagination with deterministic sort

**Partially supported natively; the experiment does not rely on it.** `Searcher.search`
exposes `offset`, `order_by_field`, and `order=Order.Asc/Desc`, plus `count=True` for
the total-hit count — so typed-field sorting and offset paging *are* available.
However, the experiment **does not use offset/sort**; it implements deterministic
pagination itself:
- **Tie-safe top-k:** `_search_with_ties` (`bm25.py` lines 411–466) re-searches with a
  growing `limit` until the score at the boundary is distinct (overfetch), then sorts
  in Python by `(-score, key)` with the stable `key` as final tie-breaker.
- **Paging:** `bm25_paging.py` is an application-level cursor over a **frozen**
  candidate list (`FrozenCandidateList` + `Cursor`, page size 20), replaying an
  already-computed ranking — explicitly *not* a streaming DB latency test.

### Q7 — Indexing and deletion

**Supported.** `IndexWriter.add_document`, `add_json`, `commit`, `rollback`,
`delete_all_documents`, `delete_documents_by_term`, `delete_documents_by_query`,
`garbage_collect_files`, `wait_merging_threads`, `commit_opstamp`. (The experiment is
a read-only artifact and never deletes.)

### Q8 — Commit and reader refresh

**Supported.** `writer.commit()` returns an opstamp; `commit_opstamp` is readable.
`Index.reload()` reopens the snapshot, and `Index.config_reader(reload_policy=...)`
(default `"commit"`) controls when new commits become visible. Consistency is
Tantivy's single-writer / multiple-reader snapshot model: a `Searcher` holds an
immutable snapshot until reloaded.

### Q9 — Multiple concurrent readers

Not documented in the stubs. Tantivy's Rust core makes `Index`/`Searcher` cheap,
thread-safe snapshots; the Python binding does not surface explicit thread-safety
contracts. The experiment uses sequential, single-process access (one `Index` →
one `Searcher`).

### Q10 — Rebuilding the index from OverGraph

**Straightforward, and already implemented atomically.** `build_index` (`bm25.py`
lines 168–237) writes into a temp dir (`Index(schema, path=tmp)`), bulk
`add_document` over all TextUnits, `commit()`, `wait_merging_threads()`, then
`os.replace(tmp, root)` to atomically swap the directory in. `Index.open(path)` +
`reload()` + `searcher()` reopens it.

### Q11 — Python binding limitations vs Rust Tantivy

See section 5 for the full enumeration.

---

## 3. What the experiment actually does with Tantivy (`retrieval/bm25.py`)

The **only** file that imports `tantivy` for indexing/searching is
`retrieval/bm25.py` (the `bm25_run.py` driver and `bm25_answer.py` import it only
for the version string). `document_properties.py`, `jev_property_verify.py`, and
`jev_end_to_end.py` are OverGraph/LLM tracks that do **not** use Tantivy.

### 3.1 Schema — everything is a text field

`build_schema` (`bm25.py` lines 73–96) declares **seven text fields**, none typed:

| Field | `tokenizer_name` | `index_option` | Purpose |
|---|---|---|---|
| `key` | `raw` | `basic` | stable TextUnit key (exact match) |
| `document_id` | `raw` | `basic` | document filter |
| `collection_id` | `raw` | `basic` | tenant/collection filter |
| `relative_path` | `raw` | `basic` | provenance |
| `document_version_id` | `raw` | `basic` | provenance |
| `content_hash` | `raw` | `basic` | integrity check |
| `text` | `profile.name` | `position` | the actual BM25 search surface |

Identifier fields use the **raw tokenizer** so `term_query` performs a byte-exact
string match. The experiment **never uses** typed integer/facet/date fields for
filtering — an important contrast to how a production tenant filter *could* be built.

### 3.2 Analyzer profiles

`SV_STEM = "sv_stem_v1"`, `SV_PLAIN = "sv_plain_v1"` (`bm25.py` lines 26–28).
Both are `Tokenizer.simple()` + `Filter.lowercase()`; `sv_stem_v1` adds
`Filter.stemmer("swedish")`; neither adds a stopword filter (the `custom_stopword`
filter is only applied when `stopwords` is non-empty). The analyzer is registered
per index via `index.register_tokenizer(profile.name, analyzer)` (`bm25.py` lines 207, 260).

### 3.3 Query construction

`build_query` (`bm25.py` lines 346–377): for each analyzed query term, an
`Occur.Should` `term_query(schema, "text", term)`; wrapped as one boolean with
`minimum_number_should_match=1` (OR semantics). Document/collection filters are
added as `Occur.Must` `term_query` clauses. The query is built programmatically —
`Index.parse_query` is **not** used.

### 3.4 Ranking and ties

`_search_with_ties` (`bm25.py` lines 411–466): default BM25 scores; overfetch past
`limit` until the boundary score is distinct; Python sort by `(-score, key)`.
Rank is then assigned in Python; the `SearchHit.rank` is the experiment's rank, not
the engine's.

### 3.5 Index lifecycle

Build → `tantivy.Index(schema, path=tmp)` → `index.writer(heap_size=..., num_threads=0)` →
`add_document` per unit → `commit()` → `wait_merging_threads()` → `os.replace(tmp, root)`.
Open → `Index.open(path)` → `register_tokenizer` → `reload()` → `searcher()`.
Verification (`verify_index`, lines 313–343) uses `searcher.num_docs`, `Query.all_query()`,
`searcher.doc(address)`, `document.get_first(...)`, and `result.count`.

---

## 4. Frozen BM25 v1 result (`eval/tantivy-bm25-v1.md`, README lines 237–339)

**Verdict: `mixed`; production unchanged; claim scope `improved_retrieval_only`;**
`holdout_status: not_blind`; `generalisation_status: insufficient`.

Global macro (9 golds, dev + locked holdout, k=20/50):

| Arm | DocR@20 | EvidR@20 | NDCG@20 | DocR@50 | CE@5 (doc-local) |
|---|---:|---:|---:|---:|---:|
| dense | 39.7 % | 38.3 % | 0.461 | 69.3 % | **98.7 %** |
| sparse | 28.8 % | 26.7 % | 0.281 | 51.9 % | 55.8 % |
| hybrid_current | **57.0 %** | **54.7 %** | 0.553 | **76.0 %** | 67.5 % |
| hybrid_rrf_control | **57.1 %** | 54.8 % | 0.583 | 76.2 % | 67.5 % |
| hybrid_rrf_positive | **57.1 %** | 54.8 % | **0.583** | 76.2 % | 80.5 % |
| bm25 (standalone) | 28.3 % | 26.0 % | 0.306 | 38.6 % | 52.0 % |
| **dense_bm25** | 49.6 % | 47.4 % | 0.456 | 71.3 % | 71.4 % |

**Key conclusions (frozen):**
1. **Standalone BM25 is weak** (DocR@20 28.3 %, DocR@50 38.6 %) — the weakest of all arms.
2. **Dense+BM25 beats dense on global DocR@20** (49.6 % vs 39.7 %, delta +0.099) and
   slightly on the aggregate DocR@50 guard (71.3 % vs 69.3 %) — but the 95 % CI for the
   R@20 delta crosses zero (`[-0.095, +0.301]`, n=9 clusters).
3. **Dense+BM25 loses to `hybrid_current` at 20** (49.6 % vs 57.0 %) and **loses badly to
   dense document-locally** (CE@5 71.4 % vs 98.7 %).
4. Several golds lose coverage at 50 (auto-renewal, confidentiality, governing-law).
5. **The `sv_plain_v1` control lowers both BM25 and dense+BM25** — the Swedish stemmer's
   behavior (maps `förlängs`→`förläng` but leaves `förlängning` unchanged) means the
   result is pipeline-level, not a pure BM25 formula proof.
6. **Latency:** index build ~0.67 s / 1.3 MB for 2,548 TextUnits; warm BM25 retrieval
   p50 ~1 ms vs dense ~11–12 ms and sparse ~0.3 ms; query encoding dominates (~0.19 s).
7. **No production change, no router, no BM25 parameter tuning** (`tuned_on_gold: false`).
8. Paging replay completed (20-unit pages, no duplicates); the **answer test was not run**,
   so the claim is retrieval-only.

**Tantivy features used:** text fields (raw + position), custom registered analyzer
(`simple`+lowercase+Swedish stemmer), `term_query`, `boolean_query` (Must/Should,
`minimum_number_should_match`), `all_query`, `add_document`, `commit`,
`wait_merging_threads`, `Index.open`/`searcher`/`reload`/`num_docs`/`doc`/`get_first`,
`SearchResult.hits` + runtime `count`.

**Tantivy features NOT used:** typed fields, facets, `range_query`, `offset`/`order_by_field`
search, `parse_query`, deletion, aggregations, highlighting, `config_reader`.

---

## 5. Python binding limitations vs Rust Tantivy

The stubs are the ground truth for what is callable. Rust Tantivy's public API has
features with no counterpart in `tantivy.pyi` (inferred from the Rust Tantivy surface):

1. **`Field` handle type** — absent; fields are name-string addressed. Rust's typed
   `Field`/`FieldValue`/`TantivyDocument` model is flattened into `Document`.
2. **`IndexReader` / `TopDocs`** — absent as classes; `Searcher` wraps the reader and
   `SearchResult` replaces `TopDocs` (`hits` only; `.count` is an undeclared runtime attr).
3. **Custom scoring / `Similarity`** — no way to supply a custom scorer or tune BM25
   k1/b/boosts beyond `boost_query`/`const_score_query`/`weight_by_field`.
4. **Custom analyzers/tokenizers in Rust** — only composition of the 6 built-in
   `Tokenizer`s + 8 `Filter`s via `TextAnalyzerBuilder`; no arbitrary Rust tokenizer,
   no `Box<dyn Tokenizer>` plug-in, no `Lindy` analyzer.
5. **Merge policy / segment management** — no `MergePolicy`, no segment-count/merge
   tuning, no `segment_updater`; only `wait_merging_threads()` + `garbage_collect_files()`.
6. **Memory-mapping / directory control** — no `MmapDirectory`/`RamDirectory`/mmap
   settings; the only RAM toggle is `Index(schema, path=None)`.
7. **Writer settings** — only `heap_size` and `num_threads`; no `WriterSettings` for
   buffer size, segment merge thresholds, or `IndexSettings` (writer/mmap/etc.).
8. **Standalone `PrefixQuery`** — no `Query.prefix_query`; prefix matching only via
   `phrase_prefix_query` or `Searcher.terms_with_prefix`.
9. **Facet queries** — `Facet`/`add_facet_field` exist, but no `facet_query`/`facet_prefix_query`.
10. **Term dictionary / posting streamers** — no `TermDictionary`/`TermStreamer`/`DocSet`
    iteration; `terms_with_prefix` and `doc_freq` are limited substitutes.
11. **Schema/indexing fine-control** — no `set_indexing_options`, no `CARDINALITY`/`STORE`
    bitflags beyond the boolean flags; no per-field `COERCION`/`sortable` enum.
12. **`Searcher.count`** — used at runtime but missing from the stubs (typing gap).

---

## 6. OverGraph graph model (the index's source of truth)

### 6.1 Node types (`graph/schema.py` lines 3–6; `graph/builder.py`)

| Label | Key | Key attributes (`graph/builder.py`) |
|---|---|---|
| `Collection` | `collection_id` | `collection_id` |
| `Document` | `document_id` | `document_id`, `document_version_id`, `collection_id`, `relative_path`, `source_hash`, `mime_type`, `status`, `page_count`, `char_count`, `expected_text_units`, `extraction_version`, `segmentation_version`, `exclusions_json`, optional `error` |
| `Structure` | `structure_id` | `structure_id`, `document_id`, `document_version_id`, `path`, `title`, `level`, `ordinal`, `clause_number`, `page_start/end`, `char_start/end` |
| `TextUnit` | `text_unit_id` | `document_id`, `document_version_id`, `structure_id`, `text`, `normalized_text`, `content_hash`, `page_start/end`, `char_start/end`, `sequence`, `segmentation_version` |

Additional labels added elsewhere: doctags add tag nodes + `HAS_TAG` edges
(`doctags/store.py` line 317).

### 6.2 Edge labels (`graph/schema.py` lines 8–12; `graph/builder.py` lines 92–163)

| Edge | From → To |
|---|---|
| `CONTAINS` | `Collection` → `Document`; `Structure` → `TextUnit` |
| `HAS_SECTION` | `Document` → `Structure` |
| `PARENT_OF` | `Structure` → child `Structure` |
| `NEXT` / `PREVIOUS` | `TextUnit` → next/previous `TextUnit` |

> Note: `SUPPORTED` / `CONTRADICTED` / `UNDECIDED` are **proof-status values** in the
> `coverage`/`jev` tracks (e.g. `coverage/evidence.py` line 17, `jev/proof_eval.py`
> line 9), not graph edge labels in the phase-1 ingest schema.

### 6.3 Writer / persistence (`graph/writer.py`)

- `GraphWriter` (lines 16–104) batches `batch_upsert_nodes` / `batch_upsert_edges`,
  maintains a `key_to_id` cache, and publishes a `Document` via a short
  `begin_write_txn()` / `txn.upsert_node(...)` / `txn.commit()` (lines 28–35).
- `open_database(path, dimension)` (lines 107–116) opens OverGraph with:
  `create_if_missing=True`, **`dense_vector_dimension=dimension`**,
  **`dense_vector_metric="cosine"`**, `wal_sync_mode="group_commit"`,
  `edge_uniqueness=True`.
- `read_manifest_dimension` / `resolve_dimension` (lines 119–142) lock the database to
  one dense dimension; the dimension is read back from `manifest.current`.

### 6.4 Dense / sparse / vector search

- Dense: `text-embedding-3-large`, **dimension 3072** (`encode.py` lines 14–15,
  `OpenAIDenseEncoder` lines 151–192). Sparse: hashed lexical TF-IDF,
  `SPARSE_DIMENSIONS = 262144`, `SPARSE_ENCODER_ID = "lexical-tfidf-hash-v1"`
  (`encode.py` lines 16–17, `LexicalSparseEncoder` lines 109–135), with a hand-rolled
  Swedish stemmer (`_STEM_SUFFIXES`) and stopword set.
- Vectors are written onto `TextUnit` nodes via `writer.write_vectors(payloads)`
  (`index.py` lines 87–88, `writer.py` lines 55–57), payload keys: `labels`, `key`,
  `props`, `dense_vector`, `sparse_vector` (`index.py` lines 123–131).
- Retrieval uses OverGraph `vector_search(mode, k, *, dense_query, sparse_query,
  label_filter, ef_search, scope_*, dense_weight, sparse_weight, fusion_mode)`
  (`overgraph/__init__.pyi` lines 1588–1605). The experiment calls it with
  `label_filter={"labels": ["TextUnit"], "mode": "all"}` and `fusion_mode="reciprocal_rank"`
  (`search.py` lines 39–48). `search_units` maps results back to `StoredUnit`; RRF fuse
  uses `RRF_K = 60` (`search.py` line 97). Document-local arms use **exhaustive Python
  ranking** (`exhaustive_rank`, `search.py` lines 69–94) — reported separately from
  engine latency.

---

## 7. Source references

- Binding: `experiments/overgraph_ingest/.venv/lib/python3.13/site-packages/tantivy/tantivy.pyi` (714 lines).
- Tantivy usage: `experiments/overgraph_ingest/overgraph_ingest/retrieval/bm25.py` (595 lines).
- Paging replay: `experiments/overgraph_ingest/overgraph_ingest/retrieval/bm25_paging.py`.
- Frozen result: `experiments/overgraph_ingest/eval/tantivy-bm25-v1.md` (249 lines).
- Narrative/commands: `experiments/overgraph_ingest/README.md` lines 237–339.
- Graph model: `overgraph_ingest/graph/schema.py`, `graph/builder.py`, `graph/writer.py`.
- Retrieval (dense/sparse/BM25): `overgraph_ingest/retrieval/index.py`, `search.py`, `encode.py`.
- OverGraph binding: `.venv/lib/python3.13/site-packages/overgraph/__init__.pyi` (lines 1194–1313, 1588–1617).
