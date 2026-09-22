# 36 § AvtL research milestone

The live evaluation on 2026-09-22 used Cerebras `gpt-oss-120b`, the official lagen.nu MCP, seeded database prompts and an isolated temporary SQLite database. Base: `6b9f07d754b04a0f73ac5c7c2f205c75d88ddf12` (merged #288). The same credentials/model and source-specific questions were used in a detached baseline checkout. These are observed runs, not statistical guarantees or an independent legal correctness score.

## Results

The broad, unseeded seven-question search answered **6/7** needs. All 20 retrieved documents fetched and passed domain extraction (15 case-law, 5 preparatory works). The consumer-law question was rejected as irrelevant before document retrieval; it remains unanswered. Earlier development runs also reached 6/7 but failed a different topic, demonstrating search/model variability.

The eight named-source paths produced **8/8 found and grounded domain results**, up from **2/8** on the baseline. Need assessment accepted 7/8: the SOU result was valid but the assessor emitted an invalid supporting evidence ID, which the need-scoped sanitizer correctly rejected. The harness does not count that as answered.

| Source | Baseline | Current retrieval/extraction |
| --- | --- | --- |
| NJA 1987 s. 394 | not_found / no_fetchable_document | found |
| NJA 1992 s. 782 | found | found |
| NJA 2009 s. 672 | error / legal_domain_extraction_failed | found |
| NJA 2002 s. 244 | found | found |
| AD 1998 nr 109 | error / legal_domain_extraction_failed | found |
| SOU 1974:83 | error / legal_domain_extraction_failed | found; upstream truncated |
| NJA 2005 s. 142 | error / legal_domain_extraction_failed | found; authoritative adjustment_granted=false |
| Prop. 1975/76:81 | error / legal_domain_extraction_failed | found |

See [captured metrics, assessment and source URLs](research-36-eval.json). Found means a relevant, structurally valid interpretation with exact grounded citations; it does not mean statutory adjustment was granted or that every generated proposition has been independently legally reviewed.

## General fixes

- Retrieval no longer discards a document through a separate excerpt classifier before legal interpretation. A verified domain citation supplies the display excerpt.
- Whole case documents retain deciding-court context. Preparatory-work section anchors survive resolution. The MCP maximum is 200,000 characters; truncation is preserved and disclosed, never presented as a full-document review.
- The Legal result schema version is 3 (the extension of Legal v2). Court level, text role, decision basis and the authoritative holding are explicit. Outcome and adjustment claims are projected only from the authoritative statement. The model reasons about the deciding majority before producing that statement. No regex infers the legal outcome.
- Paragraph IDs let the model select an exact original source span. Code copies that paragraph and validates URI plus exact substring. Separate lower-court, party, reporter and dissent statements retain their own citations. Invalid grounding fails explicitly.
- Citation catalogues deduplicate repeated claim quotes in assessment/completeness inputs without changing frozen source text.
- Domain-neutral parent aggregation copies only supported knowledge from answered children, with child assessment, evidence/hash and claim provenance. It is marked derived/secondary, excluded from independent-source counts, and reassessed against the parent question. It cannot automatically promote a parent or use another derived answer as primary support.
- Historical dependency edges remain available; completed questions never display a waiting count. Pending/blocked questions expose only unresolved dependencies.

## Failure categories

`search_no_hit`: no search candidates. `resolve_no_document`: citation resolved to no retrievable document, including upstream not-found. `fetch_failed`: transport/tool failure. `unsupported_source_shape`: malformed MCP payload or unexpected source kind. `selection_failed`: candidate selection failed. `budget_exhausted`: no fetch remained within the call budget. `domain_schema_invalid`: interpretation could not satisfy its schema. `citation_grounding_failed`: citation URI/span did not match the retrieved source. `irrelevant_relation`: selected source did not address the requested legal issue.

Failures retain source URI when available, stage flags and diagnostic detail. Sibling document fetches continue; one failed document does not erase successful results. Cached domain results are reused only at schema version 3.

## Reproduce

From `backend`, with model credentials available through normal settings:

```sh
uv run pytest tests/test_research_36_integration.py --live-research-sources --live-research-model -q
uv run python -m scripts.evaluate_36_avtl --mode sources --output /tmp/36-sources.json
uv run python -m scripts.evaluate_36_avtl --mode topics --output /tmp/36-topics.json
```

The live flags are opt-in; normal CI tests use recorded actual MCP documents and mock the model boundary. The live source tests follow the Prop. 1975/76:81 → SOU 1974:83 citation chain. The model golden checks NJA 2005 s. 142 and SOU interpretation. Offline regression tests reject party statements as authoritative, contradictory adjustment/basis combinations and invented quotes, and verify two-child parent synthesis with persisted provenance.

`--artifacts /tmp/36-sources.json` explicitly reuses captured retrieval results for a new assessment only. Its mode/questions must match. This is never an automatic alternate path after a failure.

Metrics count observed fetch/extraction attempts by source type and sanitized answered needs. Derived evidence is excluded from source-success counters. This harness tests retrieval, extraction and assessment; it does not replay the entire production conversation/follow-up scheduling loop.
