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
| `build_research_registry(provider)` | Registers adapters from `standard_capability_descriptors()` (tenant knowledge plus official lagen.nu). Planner availability is derived from the same descriptors. |

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

`ResearchPlanner` and `ResearchCompletenessReviewer` are only offered natures the attempt's registry can execute. A concrete `ResearchRouter` exposes `available_source_types()` from `registered_evidence_natures()`. The production API path (`router_factory=build_standard_research_router`, `router=None`) introspects the same session-independent capability descriptors that `build_research_registry` registers (`standard_available_source_types()`). Catalog membership is not enough. A generated empty plan is invalid. A globally missing question whose only source types are unregistered stays an explicit capability/unavailable gap; it is not a runnable follow-up.

## Provider descriptor

`KnowledgeProviderDescriptor` is the registration contract:

- `provider_id` — stable registry id (`supabase.case_knowledge`)
- `domains` — generic tokens (`tenant`, `public`, …). Not a law/medicine enum.
- `modalities` — `text`, `image`, `tabular`, …
- `capabilities` — `search`, `similarity`, `retrieve`, …
- `evidence_natures` — logical source/evidence kinds the adapter can produce
- `authority` — generic metadata (`tenant_bound`, `requires_case`, `retrieval_provider`). Optional quality keys (`official_publication`, `not_official_publication`, `automated_corpus`, `primary_source`, `source_nature`, `authority_warning`) are copied into evidence-quality scoring; undeclared keys stay `unknown`. See [research-evidence-quality.md](research-evidence-quality.md).
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

`build_research_registry` composes each standard capability descriptor through its declared adapter. The production registry currently contains only lagen.nu capabilities; MCP is the access mechanism.

| Registry id | Evidence nature | Scope |
| --- | --- | --- |
| `lagen_nu.swedish_law` | `swedish_law` | public SFS via lagen.nu MCP |
| `lagen_nu.swedish_case_law` | `swedish_case_law` | public Swedish court decisions (`dv/case`) via lagen.nu MCP |
| `lagen_nu.swedish_preparatory_works` | `swedish_preparatory_works` | public förarbeten via lagen.nu MCP |

The `case_knowledge` and `customer_knowledge` adapters remain implemented for future policy work but are not registered in production. User uploads can contain arbitrary material, so they must not become research evidence until source classification, provenance, and trust rules exist. Uploaded documents remain analysis objects for document-understanding flows.

lagen.nu evidence `provider` is `lagen_nu`. The public adapter never receives `customer_id` / `case_id`.

The lagen.nu descriptors come from one production registration (`app.services.lagen_nu.registration`), while provider-owned retrieval lives in `app.services.lagen_nu.research_source`. Planner, follow-up planner, and completeness reviewer only see the evidence natures declared by the active registry and allowed by the Run scope.

For `swedish_case_law`, a named decision resolves directly. A question about a provision combines question-specific full-text search with the incoming citation graph, deduplicates by canonical document URI, and ranks overlap between both candidate lists ahead of search-only and citation-only hits. Named `prop.` / `SOU` citations resolve the same way. This provider-specific ranking never enters the generic `ResearchRouter`.

Search, citation-graph, and named-resolve hits go through a structured lagen.nu selector (`app.llm.lagen_nu_selector`) before `get_document`. The selector may only keep or drop already found candidate IDs; it does not search and it does not invent URIs. Omitted candidate IDs are dropped. Invented IDs are ignored. Named `prop.` / `SOU` / `NJA` resolves stay by identity; a later excerpt check drops the document if the span does not mention the provision. A question about förarbetena till a named provision resolves that statute and reads incoming forarbete citations in rail order (citation-count order surfaces later laws that merely mention the section). Preparatory search does not prefix `36 §`, which matches other SOU/prop numbers. Cover-page pinpoints (`huvudsakligt innehåll`) are ignored so the full document is fetched; the excerpt model windows around the provision itself, not every earlier `jämk` on the cover. Case excerpts come from the court's reasons when those mention the provision; party submissions are dropped. After fetch, a second structured call copies a contiguous excerpt that must already exist in the retrieved text and must mention the provision. A bad, empty, or front-matter excerpt skips that document instead of failing the whole need. Prompts live in `research.lagen_nu.select.*` and `research.lagen_nu.excerpt.*`.

The adapter fetches at most five unique documents and enforces a hard budget of twelve MCP calls per ResearchNeed. Evidence provenance records retrieval origins and ranks so the selection remains auditable.

lagen.nu republishes material collected from official sources. Its descriptors therefore declare `authority_level=trusted` and `source_nature=primary`; the evidence keeps the publisher URL and a publication note for audit, without treating the aggregation mechanism itself as a reliability defect.

## Semantic ranking seam

`rank_provider_candidates(candidates, constraints)` currently sorts by `(rank, provider_id, registration_index)`. Later work may re-rank that **already filtered** list with embeddings. Do not embed the full provider catalog as a substitute for metadata filters.
