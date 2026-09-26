# Document knowledge ingest

Uploaded underlag now have a mutable, document-scoped knowledge layer. Its purpose is neutral document understanding: parties, dates, amounts, definitions, obligations as written, and other facts needed to navigate the document. It does not perform issue spotting, risk analysis, legal assessment, external lookup, or expert assignment.

## Flow

```text
StoredObject upload
  -> document_ingest Job
    -> KnowledgeIngestService
         extraction -> Section/TextUnit segmentation -> TextUnit embeddings
  -> persist CanonicalDocument + DocumentVersion + Sections + TextUnits
  -> Q&A generation from neighbouring TextUnits in the same section
  -> exact-quote validation, TextUnit grounding, and PDF rectangle anchoring
  -> DocumentKnowledgeItem + anchors + supporting_text_unit_ids + revision snapshot
  -> fact/Q&A item vectors in the same case-scoped index
```

See [text-unit-knowledge.md](text-unit-knowledge.md) for the shared Document → Section → TextUnit model.

The upload returns immediately. `StoredObject.knowledge_status`, `knowledge_error`, and `knowledge_job_id` provide durable state for leaving and reopening the picker. PDF files without a usable text layer end in `needs_ocr`; this phase deliberately has no OCR fallback and no tool calls. Generated Q&A is an isolated enrichment stage: raw text/chunks remain usable when one or more model batches fail, successful batches are saved, and the durable status becomes `partial` so the failure stays visible.

## Data model

- `DocumentKnowledgeItem` is a mutable presentation record with `kind` (`fact`, `qa`, `bookmark`, `note`), `origin` (`generated`, `manual`), status, and revision number. Semantic provenance is `supporting_text_unit_ids`; exact quotes and PDF anchors remain for UI highlight.
- `DocumentKnowledgeAnchor` links an item to exact source text and a generic anchor type (`text`, `image`, `chart`, `table`). Text anchors may include normalized page rectangles for visual highlighting. Image/chart/table anchors are future seams, not active extraction paths.
- `DocumentKnowledgeRevision` is an append-only snapshot written on create, edit, archive, and re-ingest review transitions.
- `KnowledgeDocumentRecord.source_object_id` ties both the raw document vector and item vectors back to the uploaded object for scoped cleanup.

Generated content is replaced on re-ingest. Manual content is preserved and marked `needs_review`, because its anchor may no longer be valid for the new document version.

## Retrieval behavior

Facts and Q&A are indexed as individual vector documents using a richer embedding text (title, question, answer, generated retrieval queries) while returning the concise human-readable content as the excerpt. Bookmarks and notes are intentionally not indexed as research evidence.

All records use `case_id=StoredObject.id` and the underlag's module. The index remains tenant- and case-scoped, but `case_knowledge` is not registered as a production research capability. User uploads can contain arbitrary material and must not be treated as research evidence until source classification, provenance, and trust rules exist.

The same Supabase vector bucket is reused. `knowledge_kind=document_chunk` and `knowledge_kind=document_item` metadata distinguish these records from canonical research questions and other knowledge types; SQL remains authoritative for tenancy and scope.

## API and UI seam

`GET/POST /underlag/{object_id}/knowledge` and `PUT/DELETE /underlag/{object_id}/knowledge/{item_id}` expose owner-scoped CRUD. The PDF picker renders PDF.js text layers so a browser selection can be converted into exact text plus normalized page rectangles. Selecting an item restores its source highlight and scroll position.

This layer is mutable document understanding, not a frozen `EvidenceSet`. It supports navigation and claims about what the uploaded document contains; it does not currently supply external research evidence.

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
   Before reusing previously ingested sources, explicitly arrange fresh ingestion:
   persisted indexed document versions can otherwise skip ingestion even though
   the new index is empty. This PR does not reset that SQL state automatically.
4. Ingest sources again, verify content roundtrips and customer-scoped searches,
   then rerun affected research through the normal application flow. Previously
   failed needs do not become successful merely because storage is repaired.

The Alembic schema change is still required even when old vectors are discarded.
Do not point an active workload at an empty index and assume all previously
indexed sources will automatically be rebuilt.

Regression coverage includes long Unicode passages and headings, preserving
scope filters, rejecting other-customer hits, and preventing partial writes
when metadata exceeds the budget. SQLite tests alone do not demonstrate live
PostgreSQL enforcement or a successful production index migration.
