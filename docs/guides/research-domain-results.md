# Persistent research domain results

Research retrieval still runs through the domain-neutral `ResearchRouter`. The lagen.nu provider produces a validated `LegalResearchResult` in memory. Persistence then writes three immutable layers:

1. `raw_sources` stores the full retrieved text, keyed by canonical source and text hash. A changed document produces a new row; old versions remain reviewable.
2. `domain_research_results` stores the structured interpretation without `raw_text`, keyed by raw version, `research_need_id`, and interpretation content. Separate questions about one document keep separate analyses.
3. `research_claims` stores domain-neutral predicate/value assertions, relation to the need, and verified citation objects. The legal resolver projects explicit fields from the validated result; it does not infer outcomes from excerpts.

`evidence_set_items.domain_result_id` fixes the exact interpretation seen by a frozen attempt. Evidence passages and question reuse links keep source lineage; they no longer store `legal_result` or `raw_text` in provenance. Assessment and completeness receive claims alongside compact legal results. Frozen expert context reads the same stored result and claims.

Authenticated review endpoints are:

- `GET /execution/attempts/{attempt_id}/evidence/items/{item_id}/raw-source`
- `GET /execution/attempts/{attempt_id}/evidence/items/{item_id}/domain-result`

Both require access to the attempt's customer and item. The raw source endpoint returns the source version and full text; the domain endpoint returns the question-specific interpretation and its claims.

Migration `111_raw_domain_claims` creates the tables and moves existing legal blobs out of item, passage, and question-link provenance. The legacy data is validated with the same exact-span citation contract. The downgrade drops the new records, so a production rollback should restore from a database backup.
On PostgreSQL the migration enables row-level security for all three new tables; the authenticated execution API remains the review surface.

Run the deterministic 36 § AvtL contract case with:

```sh
cd backend
python -m app.services.research_eval_harness tests/fixtures/research_eval/36_avtl.json
```

Pass `--artifacts output.json` to score pipeline output against the pinned expectations. The fixture uses synthetic case excerpts to test positive and negative outcomes, context, agreement types and citations; its proposition identities are real. Each stage reports its own regressions. The harness does not measure live lagen.nu retrieval or LLM variance.
