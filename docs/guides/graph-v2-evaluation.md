# Graph v2 evaluation: 36 § avtalslagen

Run `cd backend && uv run python scripts/evaluate_graph_v2.py` to reproduce the
measurements. This projects the seven recorded claims from
`tests/fixtures/research_eval/36_avtl.json` into an isolated SQLite graph with
deterministic vectors. It makes no network or model requests.

| Measure | Result |
| --- | ---: |
| First pass | 10 nodes, 7 fact edges, 7 provenance links |
| Second pass growth | 0 nodes, 0 fact edges, 0 provenance links |
| Lexical recall@3, query from each recorded fact value | 6/7 |
| Three facts about the positive case reached within two hops | 3/3 |
| Hits visible to another tenant | 0 |

These are contract measurements on a small synthetic scenario, not an end-to-end
accuracy estimate. The retrieval queries use the recorded English fact values;
the seven Swedish research questions have no calibrated embeddings in this fixture.
The positive-case traversal stays within one source. The fixture has no grounded
cross-document relationships, so cross-document multi-hop relevance is unmeasured.

Exact node and fact identity are deterministic, provenance is separate, and repeated
projection adds no rows. Semantic entity/fact resolution is covered by focused
regression tests, but has no labelled evaluation set here. The production judge
uses a versioned database prompt and needs measured precision/recall on human
labelled SAME, DISTINCT and CONTRADICTS pairs before its quality is known.

Postgres holds portable node/fact/source records; full-text ranking and vector
distance are retrieval adapters. Before Neo4j, preserve the stable IDs, scope,
occurrence, source links, contradiction relations and temporal properties; replace
the Postgres candidate queries, transactional uniqueness handling and graph
traversal with Neo4j implementations. Add an ANN index or a dedicated vector
column for large corpora; the current JSON-to-vector cast cannot use a pgvector
index. The outbox and legacy research claim reuse remain transitional bridges.
