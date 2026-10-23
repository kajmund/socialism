# Clause SSR library — reuse audit

Mandatory matrix before the isolated clause-anchor library. Production
tone/style SSR, research, Jev, and SWE execution stay unchanged.

Policy: [reuse-before-new.md](reuse-before-new.md).

## Inventory (existing)

| Primitive | Path | Role |
| --------- | ---- | ---- |
| TextUnit nodes | `overgraph/text_units.py`, `overgraph/write.py` | Authoritative clause/passage store |
| Tenant scope | `database/knowledge_scope.py`, `overgraph/isolation.py` | `scope_key` + `scope.*` labels |
| Catalog I/O | `overgraph/catalogs.py` | `upsert_node`, edges, `query_nodes`, dense vectors |
| Cosine | `ssr/similarity.py` | `cosine_similarity` (not a probability) |
| Knowledge embeddings | TextUnit `dense_vector` + `settings.embedding_model` | Reuse stored vectors; no second vector store |
| Tone/style SSR | `ssr/anchors.py`, `anchor_store.py`, SQL `SsrAnchorSet` | Report rating of simulation reactions |
| Jev verification | `overgraph/claims.py`, `document_properties` | Claim / `VerificationObservation` (SUPPORTED/UNSUPPORTED) |
| Admin tools | `ToolsShell`, `RequireAdmin`, `/tools/*` | Admin chrome + i18n |

## Reuse-vs-new matrix

| New unit | Existing counterpart | Decision | Justification if new | Integration test |
| -------- | -------------------- | -------- | -------------------- | ---------------- |
| Source passages | OverGraph `TextUnit` | **Reuse** | No clause table or parallel document model | `test_queue_reads_existing_text_units` |
| Tenant boundary | `KnowledgeTenantScope` + `assert_visible` | **Reuse** | Same scope labels and visibility | `test_match_does_not_leak_foreign_tenant` |
| Similarity | `ssr.similarity.cosine_similarity` | **Reuse** | Matching is cosine, never a new metric | `test_match_uses_ssr_cosine_similarity` |
| Query vectors | TextUnit `dense_vector` | **Reuse** | Match fails loud if the stored vector is missing; no silent embed | `test_match_reuses_text_unit_vector` |
| Tone/style `SsrAnchorSet` | SQL report anchors | **Do not extend** | Different domain (reaction tone vs grounded clauses). Mixing would change production reports. | `test_clause_ssr_does_not_import_anchor_store` |
| Jev `VerificationObservation` | Document-property verdicts | **Do not reuse as labels** | A human "Nej" means "not this question", not "claim unsupported". Skip/unsure must not become negatives. | `test_no_is_not_generic_irrelevant` |
| Node/edge kinds | Core `labels.py` | **New, isolated** | `SsrClassification` / `SsrVerification` / `SsrClauseAnchor` / `SsrClauseAnchorSet` plus `ssr.*` edges (same namespacing as `legal.*`). Not added to `KNOWLEDGE_TYPES`. | `test_classification_round_trip` |
| Storage adapter | Catalog wrapper | **New, thin** | Isolates clause-SSR I/O so research write paths stay untouched | store tests use `open_catalog` / `require_knowledge` |
| Queue / match / select | Report playground SSR | **New, opt-in** | Separate `/clause-ssr` API; not wired into research, Jev, or SWE | `test_research_imports_ignore_clause_ssr` |
| Golden benchmark | Live embedding API | **Scripted only** | Fixture vectors; not presented as model quality | `test_clause_ssr_benchmark_scripted_holdout` |

## Not added

- A second vector database or embedding cache
- SQL tables for clause anchors
- Automatic promotion of YES → active anchor
- LLM/Jev calls on the match path
- Changes to `swe_bridge`, evidence sufficiency, or report SSR
- `DERIVED_FROM` / `MEMBER_OF` as global edge labels (namespaced `ssr.*` instead)
