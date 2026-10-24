# Research fact writing through the Overgraph owner

Status: implementation note (PR #432, ticket 51 / research step).

## Live write path

Production research fact writing is the frozen-answer publication path:

```text
research execution freeze
  → research/answer_capture.project_groups
  → research/answer_graph.publish_answer
  → overgraph/owner_facts.publish_answer_via_owner
  → overgraph/owner_facts.write_fact_via_owner      (the common fact writer)
  → OwnerClient.mutate(kind="batch")                (one atomic WriteTxn)
```

`publish_answer` no longer writes question/answer entities, the fact or the
dependency edges directly. It requires the owner client
(`get_owner_runtime().require_client()`); a missing owner is a hard failure and
there is no direct fallback.

Question decomposition is the second research fact write:

```text
research/question_iteration.record_question_lineage
  → graph_v2/questions.link_decomposition
  → overgraph/owner_facts.write_fact_via_owner       (one atomic mutation)
```

`overgraph/research.py::persist_research_fact` is **not** the live path. It has
no production caller (only tests), so it was left untouched instead of building
a second async variant for dead code. Its `attach_question_dependency` helper is
still used by the legal writeback (a later ticket).

## One atomic mutation

`publish_answer_via_owner` sends one owner batch containing:

- question `Entity` + `Identifier` alias (`research.question_id`),
- answer `Entity` + `Identifier` alias (`research.answer_id`),
- episode `Entity` for the frozen EvidenceSet,
- the answer `Fact` node with merged props/vector,
- `SUBJECT` (fact → question), `OBJECT` (fact → answer), `SUPPORTS`
  (episode → fact), and `DEPENDS_ON` (question → known dependency fact) edges.

`write_fact_via_owner` also accepts `entities` and `dependency_ids` so the same
writer handles plain facts and this structured publication. Dependency facts are
read through the owner; missing candidates are dropped exactly like the direct
path's existence filter.

## Identity and merge reuse

- `write.py::entity_nodes` / `entity_key` are the single builders for entity and
  identifier-alias identity/props. Direct `upsert_entity` and the owner writer
  both use them.
- `fact_key_from_anchor` remains the single fact-identity function.
- `_merged_fact_props` remains the single merge function: re-writes preserve
  `created_at_ms`, `source_refs_json`, `status` and the temporal fields just like
  the direct writer.
- Fact-edges now match the direct writer: `SUBJECT`/`OBJECT`/`CONTEXT` carry
  `valid_from` from `valid_at`; `SUPPORTS` carries
  `source_kind`/`source_ref`/`recorded_at`; episode nodes have the same props.

## Concurrency contract

The owner serializes mutations, so the read-modify-write merge is guarded by
batch preconditions:

- existing fact: expected `source_refs_json` + `status` (a concurrent provenance
  merge fails and is re-read);
- new fact: `expected_absent`;
- text-unit-anchored facts: expected `TextUnit.document_version_id` on the source
  unit. The anchor is re-read on every attempt, so a concurrent re-ingest moves
  the fact to the new version's key instead of writing under a stale anchor.

A precondition failure re-reads, rebuilds the patch and retries at most three
times; exceeding the bound is a hard error. A precondition conflict therefore
produces a **new** mutation attempt with a new mutation id.

## Idempotency and restart

The default mutation id is `sha256(kind + full canonical patch)`. Transport
retries use `OwnerClient.mutate_with_retry`, which replays the *same* mutation id
and payload, so an owner that committed before the response was lost returns the
existing receipt (`duplicate: true`) and does not write twice. Receipts live in
the same `WriteTxn` as the data and survive an owner restart. Re-running a
logical merge after a conflict is a new attempt with a new id, not a transport
retry.

Every non-success owner response is raised as `OwnerProtocolError`; the writer
never reports a rejected mutation as success.

## Differential fidelity

`backend/tests/test_overgraph_owner_fact_differential.py` writes the same frozen
fact sequence through the direct writers and through the owner in two isolated
catalogs and compares a semantic snapshot (nodes, labels, props, dense vectors,
edge endpoints, edge props, validity windows, provenance). Only non-semantic
values are normalized: owner receipts and the creation instant OverGraph stamps
on edges without an explicit `valid_from`. Fact↔Fact `CONTRADICTS` uses one
canonical key-sorted orientation in both writers and is compared directed.

## Tests

| Test | Proves |
| --- | --- |
| `test_overgraph_owner_fact_differential.py` | direct/owner semantic parity incl. temporal windows, SUPPORTS props, CONTRADICTS, provenance |
| `test_overgraph_owner_fact_concurrency.py` | one-shot barrier after read before mutation; both writers read the original revision; exactly one precondition conflict; loser re-reads and merges; final refs + SUPPORTS edges for `u0/ux/uy` |
| `test_overgraph_owner_fact_restart.py` | committed-but-unseen mutation replays the same id/payload after owner restart and returns the receipt without a second write |
| `test_overgraph_owner_fact_stale_anchor.py` | a concurrent TextUnit re-ingest fails the v1 precondition, the writer re-reads the anchor and writes the fact under the v2 key |
| `test_overgraph_owner_answer_publish.py` | answer publication is one owner mutation, matches the direct writer, fails closed on rejection |
| `test_overgraph_owner_decomposition.py` | follow-up decomposition writes entities, fact, provenance and the parent→fact dependency edge in one mutation, with the direct writer forbidden |
| `research_reuse/test_06_overgraph_parity.py` | the real freeze path publishes its answers through the owner |

## Remaining risks

- **Durability**: the owner now fsyncs before acknowledging a mutation
  (`sync_on_commit`, `--no-sync` opt-out). Process-crash recovery after an ack is
  tested; power-loss durability is vendor-documented only. See
  [overgraph-owner-multiprocess-hardening.md](overgraph-owner-multiprocess-hardening.md).
- **Connection rule**: `publish_answer` still awaits the local owner while its
  `AsyncSession` is open (measured in the hardening note); the freeze caller
  chooses the transaction boundary, so the safe fix is a caller-level commit
  before publication, tracked in
  [overgraph-owner-multiprocess-hardening.md](overgraph-owner-multiprocess-hardening.md).
- **Cross-process read visibility**: a backend-local catalog is a stale snapshot
  of an owner-written catalog. Ingest/embedding readbacks now go through the
  owner; other local reads remain open and are the main blocker before
  `write_paths_ready=true` (see the hardening note).
- **Still direct**: legal writeback/claims/evidence (`graph_v2/legal_writeback.py`,
  `overgraph/legal_claims.py`, `claims.py`, `claim_answers.py`), memory, document
  QA and the dead `persist_research_fact` helper. Ticket 51 continues with those.
- **Benchmark harnesses** now open an in-process owner for each runtime they
  create (`scripts/benchmark_research_loop.open_owner_for_runtime`), because the
  research freeze path requires an owner. This is benchmark tooling, not a
  production write path.
- **Receipts** are never pruned; every distinct fact/ref payload adds one
  receipt node.
- `write_paths_ready` stays `false`; tickets 46 and 45 stay blocked.
