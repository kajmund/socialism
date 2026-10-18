# Batch document ingest

Step A of tenant OverGraph ingest is in. This note is the product
path that feeds it: many files, one durable batch, real progress
per file. Classification and tags stay Step B. Do not import
`experiments/overgraph_ingest`. Do not add PDF conversion here.

The vertical in this delivery is:

```text
Select files → upload → table row per file → poll backend →
open a searchable document
```

A later slice adds classifying / enriching stages and finer
unit-level bars. Tabular Review UI waits until documents can
enter the engine this way.

## Download-manager modal

A large modal, not a multi-file `<input>` that disappears.

1. Drop or choose many DOCX / PDF files (txt / md stay allowed).
2. A table lists every file with **two** bars: upload and ingest.
3. Closing the modal does not stop work. Reopening reads the
   persisted batch.

| Column | Source |
|---|---|
| Document | filename |
| Upload | bytes stored / size. 100 only after the object exists |
| Ingest | TextUnits written to the tenant OverGraph / total. 0 during extract |
| Status | current stage, plus searchable vs finished |

Frontend may show XMLHttpRequest byte progress **while the POST
is in flight**. That is measured upload, not a guessed bar.
After the POST returns, only backend numbers are shown.

A bar must not render 100 until that side is actually done.

## Stages

| Stage | Upload | Ingest | Searchable |
|---|---|---|---|
| waiting | 0 | 0 | no |
| uploading | 0–99 | 0 | no |
| extracting | 100 | 0 | no |
| indexing | 100 | 0–99 | no |
| classifying | 100 | 100 | yes |
| enriching | 100 | 100 | yes |
| ready | 100 | 100 | yes |
| failed | last real value, never a fake 100 | last real value | no |

Vertical slice uses waiting → uploading → extracting →
indexing → ready | failed.

Extracting ends when TextUnits are persisted and the catalog
write is queued. Ingest does not generate knowledge cards and
must not hold that stage, the extract slot, or a database
connection for an LLM.

**Searchable** means TextUnits and embeddings are in the tenant
OverGraph (`document_catalog_write` completed). Experts may use
the document then.

**Finished** later means classification and tag proposals are
also stored. Searchable must not wait for those.

## Persistence

A batch is a bag of individual document jobs.

```text
document_ingest_batches
  └── document_ingest_batch_items  → StoredObject + Job + graph_ingest_work
```

Three failed files must not rewind the other ninety-seven.
Retry is per item. Replay of the same upload idempotency key
does not create a second document.

Identity stays `CanonicalDocument` / `DocumentVersion` /
`TextUnit`. A second file with new bytes is a new upload object
today; content-hash reuse on the same object id still follows
the existing spine.

## Parallelism

| Concern | Limit |
|---|---|
| Browser uploads | 3 at a time |
| `document_ingest` extract + vector persist | 3 in this process |
| Tenant OverGraph write | existing graph owner / outbox, one Catalog |

Extraction and embeddings may run before the graph write.
Producers never open the tenant file.

## Out of this vertical

- Document-type B and tag proposals A
- Tabular Review UI
- Mandatory PDF conversion
- Semantic Q&A cache
- A second graph worker or queue
