# Remaining direct Overgraph writes (post ticket 50)

Status: inventory. Read-only access and scoring are not migrations; only direct
graph mutations must move behind the owner.

## Direct write sites found

| Area | Files / functions | Kind |
| --- | --- | --- |
| Research graph | `overgraph/research.py` (question/fact/unit refs) | direct upsert/delete, links |
| Facts/relations | `overgraph/write.py` (`write_fact`, entities, unit upserts) | multi-node + edges |
| Legal claims/evidence | `overgraph/legal_claims.py` | upsert nodes/links, deletes |
| Claims | `overgraph/claims.py`, `claim_answers.py` | upserts + edges |
| Memory | `overgraph/mem0_store.py` | upsert/delete + edges |
| Document QA | `document_qa/store.py`, `catalog_write.py`, `review.py`, `lifecycle.py` | nodes/edges, review updates |
| Knowledge backfill | `knowledge/backfill_text_units.py` | direct TextUnit upserts |
| Remaining TextUnit writes | `overgraph/text_units.py` delete helpers | direct deletes |
| Graph v2 worker | `graph_v2/worker.py` | SQL worker; no Overgraph direct? verify |
| Document ingest catalog job | `document_qa` catalog write path | graph nodes/edges |

## Classification required before migration

For each site decide:

- **direct write** → owner batch, receipt, one atomic mutation per logical unit
- **read-modify-write** → owner conditional/expected revision
- **pure read / scoring** → may stay direct provisionally; must not write

Research runs must not split one logical result (facts + evidence refs +
provenance edges) into unrelated mutations; group them into one owner batch.

## Order

1. Research graph + facts/relations
2. Legal claims/evidence
3. Claims/answers/memory
4. Document QA/catalog writes/backfill
5. Architecture test forbidding any new direct `Catalog` mutation outside the
   owner allowlist
6. Two FastAPI processes against one owner

`write_paths_ready` remains false until the allowlist is empty for required
write paths.
