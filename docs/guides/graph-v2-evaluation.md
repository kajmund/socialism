# Graph v2 evaluation: 36 § avtalslagen

Run `cd backend && uv run pytest -q tests/test_graph_v2_evaluation.py` to reproduce
the assertions in the isolated test environment. With a configured backend
environment, `uv run python scripts/evaluate_graph_v2.py` prints the measurements.
This projects the seven recorded claims from
`tests/fixtures/research_eval/36_avtl.json` into an isolated SQLite graph with
deterministic vectors. It makes no network or model requests.

| Measure | Result |
| --- | ---: |
| First pass | 12 nodes, 9 fact edges, 9 provenance links |
| Second pass growth | 0 nodes, 0 fact edges, 0 provenance links |
| Lexical recall@3, query from each recorded fact value | 6/7 |
| Proposition → shared consumer protection value → statute, two hops | reached |
| Three facts about the positive case reached within two hops | 3/3 |
| Hits visible to another tenant | 0 |

These are contract measurements on a small synthetic scenario, not an end-to-end
accuracy estimate. The retrieval queries use the recorded English fact values;
the seven Swedish research questions have no calibrated embeddings in this fixture.
The cross-source path comes from two recorded `consumer_protection: true` fields
in the proposition and statute results. It tests value-node reuse between sources,
not a citation or causal relation. The other seven facts are recorded claims.
Relation-specific multi-hop relevance remains unmeasured without grounded relation
provenance in the fixture.

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
Legal entity relations await relation-specific TextUnit support before projection;
claim passages are not automatically evidence for a citation or court relation.
