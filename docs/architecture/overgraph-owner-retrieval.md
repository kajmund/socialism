# Owner graph reuse and hybrid retrieval

Status: implemented and verified in PR #432. The owner executes the existing
vector/hybrid search; the backend only hydrates the bounded candidate list and
applies the unchanged research filters/ranking.

## Migration

- `lookup_candidates` (used by graph reuse and shared graph) branches to owner
  reads when an owner is configured:
  - `graph_has_supported_facts` reads the scope index marker through the owner;
  - `question_facts` resolves the question through the owner and reads
    `DEPENDS_ON` neighbours;
  - `search_research_facts` calls the owner `hybrid_search` operation;
  - `neighbourhood_facts` reads seed entities and their `SUBJECT`/`OBJECT`
    neighbours through the owner;
  - merging/`setdefault` order is unchanged.
- `grounded_fact_evidence` loads supporting TextUnits through the owner, and
  `passages_allowed` resolves basis TextUnit ids through the owner.
- **Scope-index marker:** an owner fact write with at least one `text_unit`
  source now includes the `research-index:<scope>` marker node in the same
  atomic mutation as the fact and its provenance. Answer facts (episode-only
  sources) do not create the marker. The marker payload is deterministic for a
  given fact payload, so a duplicate `mutation_id`+payload retry is receipted
  without applying another marker write; a failed mutation leaves no marker.
- The owner `hybrid_search` operation runs the same per-kind scoped top-k merge
  as `retrieval.hybrid_search` and returns only the top `limit` hits. The full
  corpus is never transported. The implementation lives in the owner process so
  a read request does not import the research package (avoiding an owner
  process import cycle); a parity test keeps the two rankings identical.

## Quality

`backend/tests/test_owner_retrieval_parity.py` seeds identical direct and owner
catalogs, then compares every fact id and score for four golden vector queries.
Owner and direct results are identical, so recall/NDCG cannot regress through
the transport change.

`backend/scripts/benchmark_owner_retrieval.py` on a synthetic golden corpus
(1 000 facts, 10 groups, 10 relevant per group):

| Metric | Owner | Local catalog |
| --- | ---: | ---: |
| Recall@20 | 1.0 | 1.0 |
| Recall@50 | 1.0 | 1.0 |
| NDCG@20 | 1.0 | 1.0 |
| p50 latency | 0.81 ms | 0.38 ms |
| p95 latency | 0.99 ms | 0.53 ms |
| Owner read ops per query | 2 | — |
| Owner socket bytes per query | 7.9 KB | — |

The older 127.5 ms mutation "p95" was a max-like outlier from 20 samples; see
[the read/write profiling report](overgraph-owner-read-write-profiling.md) for
the corrected 100-sample measurement (mutation p95 ~18.7 ms at eight readers,
with queue wait and commit accounting for only ~6 ms). That contention remains
the next scaling question for many parallel SWE workflows.

The two-backend harness now also proves cross-process retrieval: A writes a fact
through the production owner writer, B runs `lookup_candidates` through its
owner path and finds it, with zero local knowledge-catalog opens.

## Scope limits / remaining

- **Tantivy result search is not migrated.** `hybrid_fact_hits` (RRF of Tantivy
  lexical and dense OverGraph hits) and `find_completed_research` still use a
  local catalog; owner mode fails those paths closed. Tantivy is still a derived
  index, not a new authoritative source.
- `document_find` hybrid search and other direct `retrieval.hybrid_search`
  callers are not migrated.
- The scope-index marker is now written atomically by owner text-unit fact
  writes and still by the legacy direct/legal publish paths. Facts with only an
  episode source intentionally do not set it.
- No retrieval algorithm, scoring, filter or ranking constant was changed.
