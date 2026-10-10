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
| Proposition source → `legal.consumer_protection.value:true` → statute source, two hops | reached |
| Hits visible to another tenant | 0 |

These are contract measurements on a small synthetic scenario, not an end-to-end
accuracy estimate. The retrieval queries use the recorded English fact values;
the seven Swedish research questions have no calibrated embeddings in this fixture.
The multi-hop assertion requires a traversal from one distinct source/context node,
through a shared predicate-typed value node, to a fact on a second source/context
node. It comes from the recorded `consumer_protection: true` fields in the
proposition and statute results. This measures cross-source value-node reuse, not a
citation or causal relation; relation-specific multi-hop relevance remains
unmeasured without grounded relation provenance in the fixture. The other seven
facts are recorded claims.

Exact node and fact identity are deterministic, provenance is separate, and repeated
projection adds no rows. Semantic entity/fact resolution is covered by focused
regression tests, but has no labelled evaluation set here. The production judge
uses a versioned database prompt and needs measured precision/recall on human
labelled SAME, DISTINCT and CONTRADICTS pairs before its quality is known.

Postgres holds portable node/fact/source records until research callers read
OverGraph. Preserve the stable IDs, scope, occurrence, source links, contradiction
relations and temporal properties; replace the Postgres candidate queries and
Python fusion with OverGraph hybrid search, PPR and traversal. The outbox and
legacy research claim reuse remain transitional bridges.
Legal entity relations await relation-specific TextUnit support before projection;
claim passages are not automatically evidence for a citation or court relation.
