# Document-tag experiment closed

No more Jev on the 16 documents. No new legal engine at ingest.
Carry the data model into the Socialism integration plan.
Do not import `overgraph_ingest` into `backend/app`.

## Carry forward

- Document catalog: type, tags, confidence, user corrections.
- Tabular Review: questions with citations from original text.
- Filter documents first, then ask what to know.
- Reuse Socialism `CanonicalDocument` and `DocumentVersion`.

## Identity

- Tag identity excludes origin. Keep proposer and reviewer history.
- User decisions belong on the logical document.
- Extracted properties and sources belong on the document version.
- Content hash is the version, not the document.

## Deletion

- Archive hides the document and keeps decisions.
- Purge must remove content, tags, and excerpts.
- Experiment delete is archive only. Purge is integration work.

## What this is not

- Not production ingest.
- Not a change to Tabular `answer_cell`.
- Not another quality run.
- Next: plan_socialism_integration.
