# Document knowledge ingest

Uploaded underlag now have a mutable, document-scoped knowledge layer. Its purpose is neutral document understanding: parties, dates, amounts, definitions, obligations as written, and other facts needed to navigate the document. It does not perform issue spotting, risk analysis, legal assessment, external lookup, or expert assignment.

## Flow

```text
StoredObject upload
  -> document_ingest Job
  -> existing KnowledgeIngestService
       extraction -> raw case-scoped chunks -> Supabase vector index
  -> neutral structured generation from extracted source blocks
  -> exact-quote validation and PDF rectangle anchoring
  -> DocumentKnowledgeItem + anchors + immutable revision snapshot
  -> fact/Q&A item vectors in the same case-scoped index
```

The upload returns immediately. `StoredObject.knowledge_status`, `knowledge_error`, and `knowledge_job_id` provide durable state for leaving and reopening the picker. PDF files without a usable text layer end in `needs_ocr`; this phase deliberately has no OCR fallback and no tool calls. Generated Q&A is an isolated enrichment stage: raw text/chunks remain usable when one or more model batches fail, successful batches are saved, and the durable status becomes `partial` so the failure stays visible.

## Data model

- `DocumentKnowledgeItem` is a mutable presentation record with `kind` (`fact`, `qa`, `bookmark`, `note`), `origin` (`generated`, `manual`), status, and revision number.
- `DocumentKnowledgeAnchor` links an item to exact source text and a generic anchor type (`text`, `image`, `chart`, `table`). Text anchors may include normalized page rectangles for visual highlighting. Image/chart/table anchors are future seams, not active extraction paths.
- `DocumentKnowledgeRevision` is an append-only snapshot written on create, edit, archive, and re-ingest review transitions.
- `KnowledgeDocumentRecord.source_object_id` ties both the raw document vector and item vectors back to the uploaded object for scoped cleanup.

Generated content is replaced on re-ingest. Manual content is preserved and marked `needs_review`, because its anchor may no longer be valid for the new document version.

## Retrieval behavior

Facts and Q&A are indexed as individual vector documents using a richer embedding text (title, question, answer, generated retrieval queries) while returning the concise human-readable content as the excerpt. Bookmarks and notes are intentionally not indexed as research evidence.

All records use `case_id=StoredObject.id` and the underlag's module. Research receives that case id and module from Expertgranskning, so `case_knowledge` retrieval can discover document chunks and curated facts without making document knowledge global. Existing evidence assessment and freezing remain responsible for deciding whether a retrieved item actually answers the research question.

The same Supabase vector bucket is reused. `knowledge_kind=document_chunk` and `knowledge_kind=document_item` metadata distinguish these records from canonical research questions and other knowledge types; SQL remains authoritative for tenancy and scope.

## API and UI seam

`GET/POST /underlag/{object_id}/knowledge` and `PUT/DELETE /underlag/{object_id}/knowledge/{item_id}` expose owner-scoped CRUD. The PDF picker renders PDF.js text layers so a browser selection can be converted into exact text plus normalized page rectangles. Selecting an item restores its source highlight and scroll position.

This layer is mutable document understanding, not a frozen `EvidenceSet`. Research may retrieve it as a candidate source, assess it in the context of a question, and then freeze accepted evidence through the existing research pipeline.
