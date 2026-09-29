# Knowledge persistence gate

Durable knowledge is **classified before persist**, then upserted by a stable identity. Re-running the same research over the same source must not mint new claims, entities, or edges because LLM wording, question phrasing, attempt IDs, or excerpts changed.

This is the same identity principle as answer-review TTL ([answer-review-ttl.md](answer-review-ttl.md)): hash **scope + provenance + structured assertion**, not display prose.

## Persistence classes

Every extracted assertion is classified as one of:

| Class | Stored as | Meaning |
| --- | --- | --- |
| `domain_knowledge` | `knowledge_claims` | Durable fact, rule, or outcome |
| `source_quality` | `knowledge_observations` | Truncation, OCR, incomplete/incorrect source, retrieval limits |
| `research_observation` | `knowledge_observations` | Question-relative gap / “this source does not answer X” |

The classifier is domain-free. Producers may declare a class and kind. Otherwise the gate uses structured `kind` values, then source-quality / gap markers in the normalized statement. It does not special-case legal predicates.

## Claim identity

`knowledge_claims.identity_key` is SHA-256 of:

```text
scope_key + document_id + document_version_id + predicate + normalize(assertion)
```

`normalize` drops volatile keys (`excerpt`, `quote`, `question`, `attempt_id`, `run_id`, `rationale`, …) and casefolds / collapses whitespace on strings.

Re-extraction of the same assertion attaches additional TextUnit / question links to the existing row. It does not replace support and does not change the identity.

## Entities and relationships

- Entity identity stays `(scope_key, entity_type, entity_key)` with a deterministic normalized key. Do not create a second entity for the same canonical key (store aliases in `extra`).
- Relationship identity is `(scope_key, relation, from_kind, from_id, to_kind, to_id, temporal_key)`. Rediscovery merges `extra` / support lists.

## Audit / cleanup

```text
python -m app.services.knowledge.audit_cli audit
python -m app.services.knowledge.audit_cli cleanup          # dry-run
python -m app.services.knowledge.audit_cli cleanup --apply  # rewire, then delete
```

The report lists exact duplicate claims, same-provenance normalizable claims, duplicate entities/edges, and how many source-quality / research-observation rows are still stored as `knowledge_claims`. `--apply` rewires answers, lineage, runtime needs, relationships, and graph events before removing losers. No cleanup without that dry-run path.

## Observability

Persist emits `knowledge.persist.decision` / `knowledge.persist.rejected` with counters for proposed / accepted / reused / rejected-by-class / merged claims, entities, and relationships. Logs include class, reason, predicate, and identity key — never document text.
