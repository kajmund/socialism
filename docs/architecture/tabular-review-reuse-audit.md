# Tabular Review SSR v1 — reuse audit

Mandatory matrix before the SSR-only Tabular Review implementation.

Policy: [reuse-before-new.md](reuse-before-new.md).

## Inventory (existing)

| Primitive | Path | Role |
| --------- | ---- | ---- |
| Cosine similarity | `app/services/ssr/similarity.py` | Raw score, not a PMF |
| SSR embedding cache | `app/services/ssr/embeddings.py` | `(model, text)` disk/memory cache |
| Clause anchor library | `clause_ssr` Overgraph sets (`/clause-ssr`) | Verified anchors, vectors, versions, active sets |
| Report tone/style anchors | `ssr_anchor_sets` + `/anchor-sets` | Report SSR only; not clause storage |
| TextUnits | `app/services/overgraph/text_units.py` | Authoritative passages |
| Document grouping | `app/services/document_find/group.py` | `dedupe_document_ids` |
| Current version | `get_current_document_version` | One agreement snapshot per row |
| PDF viewer | `PdfKnowledgeViewer` | Existing page/anchor navigation |
| Module opt-in | `available_modules` + `MODULE_REGISTRY` | Kund-gated feature |
| Admin page chrome | `admin-page` / `AdminShell` | Existing shell |

## Reuse-vs-new matrix

| New unit | Existing counterpart | Decision | Justification if new | Integration test |
| -------- | -------------------- | -------- | -------------------- | ---------------- |
| Cell ranking | `cosine_similarity` | **Reuse** | No softmax, no probability | `test_ranking_is_deterministic_and_uses_cosine` |
| Clause columns | `clause_ssr` active anchor sets | **Reuse** | Published Overgraph sets; no SQL clause kind | `test_create_run_lock_approve_and_missed_hit` |
| TextUnits | `load_domain_text_units` | **Reuse** | OverGraph remains the store | `test_fill_reuses_overgraph_units_and_releases_connection` |
| Document set | `dedupe_document_ids` + `CanonicalDocument` | **Reuse** | One row per logical agreement | API create/run |
| Score cache | SSR text cache + new key table | **New table** | Key is TextUnit + AnchorSet version + model, not just text | ranking + fill tests |
| Review object | none | **New** | Persistent named review is not a run, report, or Q&A node | `test_create_run_lock_approve_and_missed_hit` |
| Verification label | `clause_ssr` verifications | **Separate** | Tabular approve/reject is a review label; it must not activate clause anchors | `test_revoked_anchor_preserves_locked_history_and_blocks_new_match` |
| Table UI | `WorkspaceComparison` / `DocumentBatchTable` | **New page, same chrome** | No shared comparison extract yet; PDF viewer reused | frontend unit + API |
| Virtual rows | none | **New 20-line helper** | No virtualizer dependency | `virtualRows.test.ts` |
| Jev / SWE / retrieval | research stack | **Do not touch** | Spec forbids production changes | no imports from those packages |

## Not reused on purpose

- Experiment `overgraph_ingest.tabular` — frozen CLI, must not enter `backend/app`.
- `rate_texts` softmax/PMF — would present similarity as probability.
- Document Q&A `user_verified` — different object; labels stay on the review.
