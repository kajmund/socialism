# Document catalog and Tabular Review

Step A is in: production document ingest enqueues
`document_catalog_write` on the existing outbox. The backend graph
owner writes `CanonicalDocument`, `DocumentVersion`, TextUnits and
embeddings into the tenant OverGraph. Classification and tags are
Step B. Do not import `experiments/overgraph_ingest` into
`backend/app`.

Socialism already has the document spine the tag experiment asked
for: `CanonicalDocument` → `DocumentVersion` → `TextUnit`.
The experiment closed a catalog model and a lifecycle. This note
says how those two product abilities should meet that spine.

## Two abilities

| Ability | Job | Not |
|---|---|---|
| Document catalog | Find and organize documents by type, tags, and user labels | Legal proof |
| Tabular Review | Answer a user question from original text with citations | A second catalog |

The product loop is: choose *which* documents, then ask *what* to
know. Catalog filter must not call Jev. Tabular Review still reads
the current version's text.

## Reuse, do not copy

| Experiment idea | Socialism home |
|---|---|
| Stable document id | `CanonicalDocument.id` (`canonical_documents`) |
| Content snapshot | `DocumentVersion` (`document_versions.content_hash`) |
| Passage / source | `TextUnit` on that version |
| Tenant | existing `scope_key` / `customer_id` |
| Workspace | existing workspace ↔ `stored_objects` binding |
| OverGraph | the product catalog, not the experiment database |

Do not use ingest content-hash as the logical document id. A new
file version of the same agreement stays the same
`CanonicalDocument`. The hash identifies the `DocumentVersion`.

Do not ship the experiment CLI, gold sets, or `overgraph_ingest`
package.

## What lives where

```text
CanonicalDocument
  ├── effective_type, type lock, user labels, rejections
  └── DocumentVersion
        ├── TextUnits
        └── extracted proposals + validated excerpts
```

User decisions belong on the logical document. They survive a new
version.

Extracted properties and their sources belong on the version where
the text was found. A source-verified tag on version 1 is not
source-verified on version 2 until the new text is checked.

Origin is history, not identity. Keep who proposed and who reviewed:

- `proposed_origin` (`structure` / `jev` / `user`)
- `proposed_at`
- `review_status`
- `reviewed_by` / `reviewed_at` when a user acts

Tag identity stays tenant, workspace, logical document, class, and
value. Several values in one class remain allowed.

`user_label` and `extracted_property` share the Tag node. Only an
extracted property with a validated excerpt on the *current*
version may be shown as source-verified. User labels never need a
source.

## Ingest

On a new current version:

1. Store frozen-style document-type B on the document as
   `predicted_type`. Do not overwrite a locked `effective_type`.
2. Run cheap deterministic extraction (experiment A) as proposals
   on that version.
3. Apply the closed lifecycle: rejected values stay rejected, user
   labels stay, stale unreviewed proposals are withdrawn.
4. Store raw Jev `confidence` and `probabilities` when a Jev call
   already happened. Do not invent a threshold.

Keep Jev tag extraction (experiment B) off the default path. It is
an optional later tool for harder classes, not a reason to extract
every legal property at ingest.

Automatic tags stay proposals. Tabular Review remains the path for
a legal answer.

## Archive and purge

The experiment's delete only hides a document. That is archive.

| Action | Document | Versions / text | User decisions | Excerpts |
|---|---|---|---|---|
| Archive | Hidden from filters | Kept | Kept | Kept |
| Purge | Removed | Removed | Removed | Removed |

Purge must follow the product deletion rules. Do not leave tags or
source excerpts behind after a permanent delete.
`CanonicalDocument` already cascades versions and units. Catalog
nodes and excerpts must go with them.

## Integration order

0. Step A: persist document / version / TextUnits / embeddings on
   the tenant OverGraph through `graph_ingest_work`. Searchable
   without classification.
0b. Batch ingest UI: many files, durable per-file progress, open
    when searchable. See `document-batch-ingest.md`.
1. Persist classification and tags on the existing document spine.
2. Filter by `effective_type`, tag class, and value inside
   tenant / workspace scope. No Jev at query time.
3. Let a user correct type, approve, reject, or add a label.
   Corrections take effect immediately.
4. Open Tabular Review on the filtered current versions.

Do not change Tabular `answer_cell`, default hybrid retrieval, or
embeddings as part of this plan.

When a tenant OverGraph file is opened, use `TenantCatalogs` only.
The lifecycle lock is approved and frozen
(`document-qa-lock-close-v1`). Do not add a second open path.

## Measured inputs, not a joint score

These are separate benches. Do not merge them into one quality
gate.

| Ability | Result | Source |
|---|---|---|
| Document type | B 86 % | `phase2-doctype-run-v1` |
| Tag extract A | 94.1 % recall / 32 of 34 | `phase2-document-tags-v1` |
| Tag extract B | same recall, higher precision, weaker sources | `phase2-document-tags-v1` |
| Tag filter | about 2 ms | `phase2-document-tags-v1` |
| Tabular holdout | Dense k=5 89 % on an earlier holdout | tabular holdout run |

No more Jev on the 16 tag documents.
