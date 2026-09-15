# KnowledgeProvider capability registry

Developer guide for research source routing. Operator UI is unchanged.

## Why this exists

v1 research routing was a flat map: `ResearchNeed.source_types` → registered `ResearchSource` adapters. That cannot scale to many providers (law, medicine, procurement, datasets, APIs, vector stores, image similarity) without asking a model to pick from a huge list.

The replacement is a **capability registry** plus **deterministic candidate routing**:

```text
ResearchNeed
  ↓ NeedConstraints (programmatic)
  ↓ KnowledgeProvider capability registry
      domains / modalities / capabilities
      evidence natures / authority / access
  ↓ existing ResearchSource.research()
  ↓ ResearchEvidence (provider, source type, locator, ids, url, score)
```

Routing stays programmatic. An LLM is not used to select providers. Embeddings are not used to select providers in v1; `rank_provider_candidates` is the seam for later semantic ranking over an already-filtered set.

## Migration from the source-type registry

| Before | After |
| --- | --- |
| `ResearchSourceRegistry.register(source)` keyed only by `source.source_type` | Same call still works. A default descriptor is inferred (`{provider_id}.{source_type}`, evidence nature = `source_type`). |
| `sources_for(source_type)` | Still available. New path is `candidates_for(NeedConstraints)`. |
| Router looped `need.source_types` then `sources_for` | Router derives `NeedConstraints` and executes the ranked candidate list. |
| Unregistered `source_type` → `error` | Unchanged. |
| Empty `source_types` → no retrieval | Unchanged, unless the need also declares domain/modality/capability filters. |
| `build_research_registry(provider)` | Still registers `case_knowledge` and `customer_knowledge` adapters only. Each now carries tenant-bound text/search metadata. |

**Plan / runtime persistence:**

- `validate_research_plan` keeps `domains` / `modalities` / `capabilities`.
- `research_plan_snapshot` and `research_runtime_needs` persist those axes so `execute_attempt_research` reconstructs the same `ResearchNeed` the router filters on.
- Plan validation still rejects unknown `source_types`. Extra axes are free-form tokens, not a closed taxonomy.
- `ResearchSource` adapter seam and `KnowledgeResearchSource` tenant rules stay.

`source_types` remain the v1 **evidence nature** constraint. They are logical evidence kinds (`case_knowledge`, `swedish_law`, …), not MCP servers or vector-store brands.

## Need constraints

`constraints_from_need(need)` reads:

- `need.source_types` → ordered `evidence_natures`
- `need.domains` / `need.modalities` / `need.capabilities` when present

Filter rules (all programmatic):

1. Walk evidence natures in need order (stable, same as before).
2. Providers that do not declare that nature are ignored for that step.
3. If none are registered for the nature → `error` (`ResearchSourceNotRegisteredError`).
4. If some are registered but domain/modality/capability filters remove all of them → `not_found` (`ResearchCapabilityUnavailableError`). No substitute provider is chosen.
5. Remaining providers are ranked by `(rank, provider_id, registration_index)`.
6. If the need has no evidence natures but does declare other axes, the same filter/rank runs over the full registry.
7. If the need has no constraints at all, nothing is selected.

A provider that does not declare a required axis does not match it. Empty need-side axes mean “no filter”.

## Provider descriptor

`KnowledgeProviderDescriptor` is the registration contract:

- `provider_id` — stable registry id (`supabase.case_knowledge`)
- `domains` — generic tokens (`tenant`, `public`, …). Not a law/medicine enum.
- `modalities` — `text`, `image`, `tabular`, …
- `capabilities` — `search`, `similarity`, `retrieve`, …
- `evidence_natures` — logical source/evidence kinds the adapter can produce
- `authority` — generic metadata (`tenant_bound`, `requires_case`, `retrieval_provider`)
- `access` — `ProviderAccess(mechanism=..., adapter=...)`
- `rank` — integer tie-break before `provider_id`

`mechanism` values such as `adapter`, `api`, `mcp`, `vector_store`, and `dataset` describe **how** the provider is reached. They are not top-level architecture types and are not used as the primary routing key.

## How to plug in a future provider

1. Implement `ResearchSource` (`source_type` + `async research(need, context)`).
2. Register it with an explicit descriptor:

```python
registry.register(
    MySource(),
    descriptor=KnowledgeProviderDescriptor(
        provider_id="example.public_statutes",
        domains=frozenset({"public"}),
        modalities=frozenset({"text"}),
        capabilities=frozenset({"search"}),
        evidence_natures=frozenset({"swedish_law"}),
        authority={"retrieval_provider": "example"},
        access=ProviderAccess(mechanism="api", adapter="example_statute_client"),
        rank=10,
    ),
)
```

3. Do not add a vertical `if law` / `if image` branch to `ResearchRouter`. If the descriptor is complete, the existing filter/rank path will select it.
4. Never widen `ResearchContext.scope`. Drop `case_id` only when the adapter’s contract says so (`customer_knowledge`). Never change `customer_id`.
5. Return `ResearchEvidence` with provider id, logical source type, locator / source id / url / score. The router isolates adapter exceptions as `error` and empty hits as `not_found`.

A synthetic non-text provider (for example image similarity) is the same path: declare `modalities={"image"}` and `capabilities={"similarity"}`. The router does not need a new code path.

## Existing knowledge providers

`build_research_registry` still wraps the shared `KnowledgeProvider` in two `KnowledgeResearchSource` adapters:

| Registry id | Evidence nature | Scope |
| --- | --- | --- |
| `{provider}.case_knowledge` | `case_knowledge` | customer + case |
| `{provider}.customer_knowledge` | `customer_knowledge` | customer only (case dropped) |

Evidence `provider` remains the retrieval provider id (`supabase`). Tenant scope is identical or stricter than before.

## Semantic ranking seam

`rank_provider_candidates(candidates, constraints)` currently sorts by `(rank, provider_id, registration_index)`. Later work may re-rank that **already filtered** list with embeddings. Do not embed the full provider catalog as a substitute for metadata filters.
