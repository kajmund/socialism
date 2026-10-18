# Document knowledge ingest

Uploaded underlag become usable when the original text is extracted, split
into TextUnits, and embedded. Ingest does not generate fact/Q&A cards.

Manual marks — facts, questions, bookmarks, and notes — remain a separate
product capability. Persistent OverGraph Q&A is created when a user asks a
question, not at upload.

## Flow

```text
StoredObject upload
  -> document_ingest Job
    -> extract DOCX/PDF text
    -> persist CanonicalDocument + DocumentVersion + Sections + TextUnits
    -> TextUnit embeddings
    -> enqueue tenant OverGraph catalog write
```

See [text-unit-knowledge.md](text-unit-knowledge.md) for the shared Document → Section → TextUnit model.

The upload returns immediately. `StoredObject.knowledge_status`,
`knowledge_error`, and `knowledge_job_id` record the ingest job. Research,
document navigation, `search_knowledge`, and `read_source` use the document
when `extraction_status` is `ok` and extracted text is present — after
TextUnits are indexed. PDF files without a usable text layer end in
`needs_ocr`; this phase has no OCR fallback.

Classification and tag proposals are later enrichment. They must not block
searchability. Batch UI "searchable" still means the tenant OverGraph write
completed; experts can use the original text as soon as it is indexed.

## Data model

- `DocumentKnowledgeItem` is a mutable presentation record with `kind`
  (`fact`, `qa`, `bookmark`, `note`), `origin` (`generated` leftover or
  `manual`), status, and revision number. Semantic provenance is
  `supporting_text_unit_ids`; exact quotes and PDF anchors remain for UI
  highlight. Generated leftovers are hidden from the knowledge API.
- `DocumentKnowledgeAnchor` links an item to exact source text and a generic
  anchor type (`text`, `image`, `chart`, `table`). Text anchors may include
  normalized page rectangles for visual highlighting.
- `DocumentKnowledgeRevision` is an append-only snapshot written on create,
  edit, and archive.
- `KnowledgeDocumentRecord.source_object_id` ties the raw document vector
  back to the uploaded object for scoped cleanup.

Manual content is preserved on re-ingest. Leftover generated cards are not
re-indexed and are not shown.

## Retrieval behavior

Search uses original TextUnit embeddings (`knowledge_kind=document_chunk`).
Manual marks are not written to the vector index and must not compete with
source passages. Bookmarks and notes stay in SQL for human reading.

All records use `case_id=StoredObject.id` and the underlag's module. The index
remains tenant- and case-scoped. SQL remains authoritative for tenancy and
scope.

The same Supabase vector bucket is reused. `knowledge_kind=document_chunk`
distinguishes uploaded source passages from canonical research questions.

## API and UI seam

`GET/POST /underlag/{object_id}/knowledge` and
`PUT/DELETE /underlag/{object_id}/knowledge/{item_id}` expose owner-scoped
CRUD for manual marks. The picker renders PDF.js or Word preview so a
browser selection can be saved as exact text plus anchors.

This layer is mutable document annotation, not a frozen `EvidenceSet`.

## Vector metadata and section-title limits

Vector content fields `text`, `title`, `locator`, `section_title`, and
`external_id` must be configured as **non-filterable** index metadata. All
other scalar metadata remains filterable, including customer, case, module,
scope, namespace, and document/TextUnit identity. Full text is returned with
hits; it must not be truncated to meet the filter budget. Before any batch is
written, the transport checks compact UTF-8 JSON against a conservative 2,048
byte filterable budget and 40 KiB total budget. Oversized records fail explicitly
without removing scope fields or logging source content.

Startup validates the exact non-filterable key set. An incompatible existing
index requires a new index: these settings cannot be changed in place. Do not
remove scope fields from the filters or delete the old index to bypass this.

Deployment order:

1. Apply Alembic migrations. `668bd23eb2df` changes `document_sections.title` to
   `TEXT` while preserving the full title. Downgrade refuses titles over 512
   characters rather than silently truncating them.
2. Start with a new, empty index using the same dimensions/distance metric and
   the five non-filterable keys above. No transfer of old vectors is required
   for this rollout. Pause research/vector writes while switching indexes.
3. Set `SUPABASE_VECTOR_INDEX` to the new index and start the updated application.
   A reused SQL document version still writes its TextUnits when the current
   index does not already contain them. A saved content hash does not leave the
   new index empty.
4. Ingest sources again, verify content roundtrips and customer-scoped searches,
   then rerun affected research through the normal application flow. Previously
   failed needs do not become successful merely because storage is repaired.
   Sources that are never fetched again stay absent until something ingests them.

The Alembic schema change is still required even when old vectors are discarded.

Regression coverage includes long Unicode passages and headings, preserving
scope filters, rejecting other-customer hits, and preventing partial writes
when metadata exceeds the budget. SQLite tests alone do not demonstrate live
PostgreSQL enforcement or a successful production index migration.
