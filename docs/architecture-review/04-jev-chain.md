# 04 — Jev semantic verification chain (document properties)

Read-only inventory of the Jev verification chain per spec §9:

```
Deterministic discovery → Jev verification → SUPPORTED | not verified → document-local dense → Jev verification
```

This maps the **production** chain (`backend/app/jev/`, `backend/app/services/document_properties/`,
`backend/app/services/knowledge/`, `backend/app/services/graph_v2/`) and the **experiment**
(`experiments/overgraph_ingest/`) that produced the frozen baselines it was built from.

> Scope note: this inventory was produced without modifying any source. Only this one
> Markdown file was written.

---

## 1. What Jev is, and how it is called in production

**Jev is a remote classification service, not an in-process LLM.** It is "TypeSafe System One",
an HTTP API at `POST {base_url}/v1/systemone` that answers a set of *questions* against a
*state* in a single request — it returns structured decisions ("control decisions, not chat
completions", `backend/app/jev/system.py:1`). There is no model call from the application
itself; the application POSTs JSON and validates the structured answer.

Production adapter: `backend/app/jev/system.py`.

| Concern | Behavior | Reference |
|---|---|---|
| Transport | `httpx` (async) `POST {base}/v1/systemone`, body `{"model","state","questions"}` | `system.py:165`, `system.py:198-210` |
| Auth | `settings.typesafe_api_key`; empty key → `JevClientError(auth)` (fail loudly, no fallback) | `system.py:159-164` |
| Endpoint | `settings.typesafe_base_url` (default `https://api.typesafe.ai`) + `/v1/systemone` | `system.py:204-205`, `config.py:55` |
| Timeout | `timeout_seconds` arg applied to the httpx call; default `jev_timeout_seconds=3.0` (bounded 0..30) | `system.py:208-210`, `config.py:58` |
| Retry | **None in `system.py`.** Retry/backoff exists only in the answer-review TTL worker (`answer_review_classification.py:28-30`, 5 min→6 h), not in the document-property path | `system.py` (no retry), `answer_review_classification.py:23-30` |
| Schema validation | HTTP status → typed category; body must be JSON object; `answers` must be a dict | `system.py:213-231`, `system.py:182-187` |
| Per-question validation | Not in `system.py` — each caller validates the returned `choice`/`noul` (e.g. `verification.py:124-137`, `parse_noul` `system.py:73-92`) | — |
| Model | `settings.jev_model` default `"jev-latest"`; the *resolved* model is read back from `payload["model"]` or echoed | `system.py:188`, `config.py:56` |
| Version | No explicit version field — the model string `jev-latest` is the only versioning | `config.py:56` |
| Error categories | `timeout, auth, rate_limit, invalid_request, invalid_response, schema_validation, transport, unknown` | `system.py:15-24`, `system.py:133-142` |
| Usage/telemetry | `JevUsage` (prompt/completion/total tokens), `latency_ms`, `input_chars` | `system.py:35-49`, `system.py:99-114`, `system.py:234-243` |

The result is `JevSystemOneResult(answers, model, latency_ms, input_chars, usage, raw)`
(`system.py:42-49`). The protocol `JevSystemOne.ask(*, state, questions, model, timeout_seconds)`
(`system.py:52-60`) is the seam every caller depends on — the document-property pipeline,
the graph-v2 judges, and the answer-review classifier all implement against it.

---

## 2. Decision semantics (SUPPORTED / UNSUPPORTED / UNDECIDED)

**They are plain string constants, not an enum.** Defined once for the production document-property
chain in `backend/app/services/document_properties/model.py`:

- `SUPPORTED = "SUPPORTED"`, `UNSUPPORTED = "UNSUPPORTED"`, `UNDECIDED = "UNDECIDED"` — `model.py:7-9`
- `VERIFICATION_DECISIONS = frozenset({SUPPORTED, UNSUPPORTED, UNDECIDED})` — `model.py:11`

Semantics (from the Jev prompt and the module docstring):

| Decision | Meaning | Reference |
|---|---|---|
| `SUPPORTED` | A clause text *itself* asserts the property with the stated polarity. Requires a grounded source. | `verification.py:27-35`, `verification.py:97` |
| `UNSUPPORTED` | No clause asserts the property. Means **"the evidence did not support it"**, never "the property is absent". | `verification.py:98`, `model.py` / `verification.py:5-6` |
| `UNDECIDED` | Unclear without more context; **also** the downgrade when Jev says SUPPORTED but the chosen source is ungrounded. | `verification.py:99`, `verification.py:65-66` |

Two hard rules enforced in code:

1. **`SUPPORTED` requires a grounded source.** `verification.py:65-66` downgrades `SUPPORTED → UNDECIDED`
   when the cited source is not a valid substring of a candidate unit.
2. **A provider failure is a technical error, never `UNSUPPORTED`.** `verification.py:5-6`
   (`JevClientError` propagates; the caller treats it as an error, not a verdict).

How each decision is persisted — the core claim-vs-observation split:

| Decision | Persisted as | Table | Function |
|---|---|---|---|
| `SUPPORTED` | Durable claim `persistence_class="domain_knowledge"`, `predicate=class_id`, `SUPPORTED_BY` TextUnits **plus** a verification-trace observation | `knowledge_claims` + `knowledge_claim_text_units` + `knowledge_observations` | `persistence.py:74-93` (`persist_supported_property`) |
| `UNSUPPORTED` / `UNDECIDED` | Two observations (candidate + verification), **no claim** | `knowledge_observations` | `persistence.py:96-146`, `pipeline.py:144-148` |

Key identity constraint: **verification status must not enter claim identity.** The claim value is
`{document_id, value, polarity, taxonomy_version}` only — no `decision`, no excerpt
(`persistence.py:50-57`). This mirrors the design decision in
`docs/document-property-phase1-design.md:26-29`.

> Distinct decision spaces that are **not** the document-property semantics (do not conflate):
> - Graph-v2 semantic judge: `SAME | DISTINCT | CONTRADICTS` (`graph_v2/jev_judge.py:25`, `:45`)
> - Answer-review TTL: `soon | later | never` (`answer_review.py:20-21`)
> - Knowledge relation `SUPPORTED_BY` is a *claim→TextUnit edge*, not a verdict
>   (`claims.py:42`, `knowledge/__init__.py`).

---

## 3. Discovery step (`discovery.py`)

**Deterministic and LLM-free.** Module docstring: *"Deterministic document-property discovery.
No LLM."* (`discovery.py:1-6`). It is high-recall lexical matching; it never turns a lexical
match into a verified legal fact on its own (`discovery.py:5-6`).

Flow (`extract_document_properties`, `discovery.py:35-50`):

1. Group TextUnits by `document_version_id` (`discovery.py:40-42`).
2. Per version, `_propose` walks every taxonomy class and `_match_units` classifies each unit:
   negative markers win, else positive markers (`discovery.py:53-88`).
3. `_property` builds a `DocumentProperty` with `class_id`, `document_id`, `document_version_id`,
   `value`, `polarity`, `taxonomy_version`, `source_unit_keys` (tuple of unit ids),
   `extraction_origin=EXTRACTION_DETERMINISTIC` (`discovery.py:91-108`).
4. `_apply_composites` downgrades a positive composite whose `composite_requires` are not all
   present to `polarity=unclear` with empty source keys (`discovery.py:119-135`).

Matching is `casefold()` + whitespace collapse, then substring (`discovery.py:138-144`).

**What a candidate looks like** — the `DocumentProperty` dataclass (`model.py:25-40`):

```text
class_id: str            e.g. "confidentiality_obligation"
document_id: str
document_version_id: str
value: object            bool (True/False) or jurisdiction string ("Sweden"/"Other")
polarity: str            "positive" | "negative" | "unclear"
taxonomy_version: str    "v1"
source_unit_keys: tuple[str, ...]
extraction_origin: str   "deterministic_discovery"
```

Value derivation (`discovery.py:111-116`): `value_type="jurisdiction"` → `"Sweden"` when a matched
unit contains `"svensk"`, else `"Other"`; `"boolean"` → `polarity == "positive"`; otherwise `""`.

**Taxonomy** (`taxonomy.py`): `PropertyClass` dataclass (`class_id, label, definition, value_type,
positive_markers, negative_markers, composite_requires`) at `taxonomy.py:15-23`. It is **frozen
v1**, 9 contract properties, hardcoded in Python (`taxonomy.py:26-178`) and byte-for-byte equal to
the frozen experiment file `experiments/overgraph_ingest/retrieval_gold/document_properties/taxonomy-v1.json`
(same 9 `class_id`s and markers). Docstring: *"Source of truth is the frozen experiment taxonomy;
do not tune markers from verification results."* (`taxonomy.py:1-6`). The only composite is
`liability_secrecy_carveout` → `composite_requires=("liability_limitation",)`
(`taxonomy.py:115-128`; `taxonomy-v1.json:96-109`).

`polarity` constants: `POLARITY_POSITIVE="positive"`, `POLARITY_NEGATIVE="negative"`,
`POLARITY_UNCLEAR="unclear"` (`model.py:13-15`).

---

## 4. Verification step (`verification.py` + `pipeline.py`)

`verify_document_property` (`verification.py:46-72`) verifies **one** document-property pair per
Jev call.

**Discovery feeds Jev** through `pipeline.discover_and_verify` (`pipeline.py:84-154`):

1. `load_document_units` materializes TextUnits (+ section titles) into `MaterializedUnit`
   **outside any external call** (`pipeline.py:58-81`) — satisfies the AGENTS.md
   "release DB connections before external calls" rule.
2. `extract_document_properties(units)` → candidates (`pipeline.py:96`).
3. For each candidate, evidence = the units named by `candidate.source_unit_keys`
   (`pipeline.py:101`); empty evidence is skipped.
4. `verify_document_property` presents evidence as `evidence_clauses` (full clause text + heading)
   — the "presentation fix" (`verification.py:85-87`, `verification.py:75-88`).

**The Jev contract** (`verification.py:91-108`) is two `choice` questions:

- `verdict`: criteria `SUPPORTED / UNSUPPORTED / UNDECIDED`.
- `source`: criteria = one `span.id` per sentence span, plus `"none"`.

**Source grounding** (`_ground_source`, `verification.py:140-153`):

- `source_id == "none"` → invalid.
- The chosen span must resolve to a candidate unit **and** the span text must be an exact
  substring of that unit's text (`span["text"] not in unit.text` → invalid, `verification.py:151`).
- This is the production analogue of the experiment's `validate_source`
  (`doctags/source.py:20-35`, `unit.text.find(text)`).

`supporting_text_unit_ids` grounding: the **durable claim** is `SUPPORTED_BY` the discovery-matched
`prop.source_unit_keys` (`persistence.py:60-67`); the **verification trace** records the *single*
Jev-chosen grounded unit (`pipeline.py:157-165` → `verification.source_unit_keys`, one element).

**How SUPPORTED becomes a claim, UNSUPPORTED/UNDECIDED become observations** (`pipeline.py:135-148`):

```text
outcome.decision == SUPPORTED  → persist_supported_property(claim + verification trace)
else (UNSUPPORTED | UNDECIDED) → persist_candidate_property + persist_property_verification
```

`persist_supported_property` (`persistence.py:74-93`) calls `persist_extracted_claim` (which
classifies `domain_knowledge` and writes `knowledge_claims` + `SUPPORTED_BY` links), then
`persist_property_verification`. It raises if no claim was produced (`persistence.py:88-89`).

---

## 5. Document-local dense step (`local_dense.py`)

**Runs only when the first Jev verdict is not `SUPPORTED`** (`pipeline.py:112`), and only when a
`LocalDenseConfig` is supplied (`pipeline.py:92`). Module docstring: *"Runs only when the first Jev
verification is not SUPPORTED."* (`local_dense.py:5`).

`top_k_dense` (`local_dense.py:17-45`):

- Guards: requires units, `k >= 1`, and a **single** `document_id` + `document_version_id`
  (rejects multi-document batches, `local_dense.py:27-32`).
- Embeds the user question via `EmbeddingProvider.embed` (`local_dense.py:33`).
- Reads stored ingest vectors for that version's units via `TextUnitEmbeddingReader.get_text_unit_embeddings`
  (`local_dense.py:34-38`).
- Cosine-ranks (`cosine_score`), **excluding** already-cited units (`exclude`), returns up to `k` ids
  (`local_dense.py:39-45`). Default `k=5`.

The second Jev call appends the dense top-k to the discovery evidence and re-verifies
(`pipeline.py:112-133`). A recovered `SUPPORTED` increments `PipelineResult.recovered`
(`pipeline.py:130-131`). The final outcome becomes the second verdict (`pipeline.py:132`).

**UNSUPPORTED does NOT remove documents from inventory.** The experiment docstring states it as a
rule: *"A second UNSUPPORTED means NOT_VERIFIED (the document stays a candidate), not that the
property is absent."* (`experiments/.../jev_end_to_end.py:1-7`). In production the same rule is
enforced by persisting every non-SUPPORTED candidate as a `document_property_candidate` observation
(`pipeline.py:144-148`), so the document remains findable via the candidate lookup (see §8).

---

## 6. Data structures and persistence (`model.py` + `persistence.py`)

### Domain types (`model.py`)

| Type | Fields | Reference |
|---|---|---|
| `DocumentProperty` | class_id, document_id, document_version_id, value, polarity, taxonomy_version, source_unit_keys, extraction_origin | `model.py:25-40` |
| `PropertyVerification` | decision, source_unit_keys, verification_method, verification_version, supporting_excerpt?, reason_code? | `model.py:43-52` |
| `MaterializedUnit` | id, text, document_id, document_version_id, section_title | `model.py:55-62` |

Observation constants (`model.py:19-22`): `OBSERVATION_CLASS="research_observation"`,
`CANDIDATE_KIND="document_property_candidate"`, `VERIFICATION_KIND="document_property_verification"`.

### Persistence (`persistence.py`)

| Function | Writes | Reference |
|---|---|---|
| `persist_supported_property` | `KnowledgeClaimRecord` (`knowledge_claims`) + `KnowledgeClaimTextUnit` (`knowledge_claim_text_units`, `relation=SUPPORTED_BY`) + a verification observation | `persistence.py:74-93` |
| `persist_candidate_property` | `KnowledgeObservationRecord`, kind `document_property_candidate` | `persistence.py:96-117` |
| `persist_property_verification` | `KnowledgeObservationRecord`, kind `document_property_verification`, `extra.decision` | `persistence.py:120-146` |
| `lookup_document_properties` | Read: claims + candidates → `DocumentPropertyHit` | `persistence.py:178-196` |

**Tables** (not OverGraph/mem0 — the phase-1 design deliberately chose the existing knowledge
relational store; `docs/document-property-phase1-design.md:79-90` D1/D3):

| Table | Model | Purpose |
|---|---|---|
| `knowledge_claims` | `KnowledgeClaimRecord` (`models.py:1760-1808`) | Verified property claim. `predicate=class_id`, `value` JSON, `superseded_at`/`successor_id` temporal lifecycle, no status column |
| `knowledge_claim_text_units` | `KnowledgeClaimTextUnit` (`models.py:1811-1834`) | Claim→TextUnit `SUPPORTED_BY` links |
| `knowledge_observations` | `KnowledgeObservationRecord` (`knowledge_observation.py:21-71`) | Candidates and verification traces (`observation_class=research_observation`) |

Claim identity = `sha256(scope_key \0 predicate \0 canonical_json(normalize_assertion(value)))`
(`identity.py:67-76`). `value = {document_id, value, polarity, taxonomy_version}` — document identity
is inside `value`, verification fields are excluded (`persistence.py:50-57`,
`docs/document-property-phase1-design.md:22-29`).

Observation identity = `sha256(scope_key \0 class \0 kind \0 document_version_id \0 question_key \0 statement_normalized)`
(`identity.py:79-92`). `question_key = prop.class_id` (`persistence.py:169`); `statement` is the
assertion (`"{class_id} {value}"`), extended with `{decision} {version}` for the verification kind
(`persistence.py:158-161`). Tenant scope via `require_persist_scope(customer_id)` (`persistence.py:70-71`).

---

## 7. Production Jev schema vs experiment schema

### Request/response contract (identical wire format)

| Aspect | Production | Experiment | Notes |
|---|---|---|---|
| Endpoint | `POST {base}/v1/systemone` | same (`client.py:65-66`) | identical |
| Body | `{"model","state","questions"}` | same (`client.py:61-64`) | identical |
| Question shape | `{"type":"choice"|"noul", "instructions", "criteria"}` | `{"type":"choice", ...}` | production also has `noul` (`system.py:73-92`, `result_prompts.py:16-21`) |
| Answer parse | `answers[key]["choice"]` | `answers[key]["choice"]` | identical |
| Model default | `settings.jev_model` = `jev-latest` | `jev-latest` (`jev_property_verify.py:311`) | identical |
| Client | async `httpx` | sync `urllib` | transport only |

### Document-property verification questions — production vs experiment

The production `verification.py` question set is the *presentation-fix* variant:

- **State**: `task="document_property_verification"`, `property{class_id,label,definition,value,polarity}`,
  `evidence_clauses=[{heading,text},...]` (`verification.py:75-88`).
  This is the `evidence_clauses` primary-evidence presentation from
  `jev_presentation_v1.py:240-256` (the older experiment state used `text`/`previous_text`/`next_text`
  in `jev_property_verify.py:248-262`).
- **Questions**: `verdict` (choice, `SUPPORTED|UNSUPPORTED|UNDECIDED`) + `source` (choice over sentence
  spans ∪ `none`) — `verification.py:91-108`, mirroring `jev_presentation_v1.py:224-239`.

### Schema-validation strictness — this is the main divergence

| Behavior | Production | Experiment |
|---|---|---|
| Invalid `verdict` | raises `JevClientError(schema_validation)` | `_choice` silently defaults to `UNDECIDED` (`jev_property_verify.py:504-509`) |
| Invalid `source` | raises `JevClientError(schema_validation)` | `_choice` silently defaults to `"none"` |
| Provider error | propagates as technical error (never `UNSUPPORTED`) | caught, mapped to an `ERROR` verdict + `effective` field (`jev_property_verify.py:267-278`) |
| Ungrounded `SUPPORTED` | downgraded to `UNDECIDED`, `source_valid=False` | downgraded to `UNDECIDED` via `effective` (`jev_property_verify.py:283-286`) |

Production dropped the experiment's `ERROR` verdict/`effective` indirection in favor of raising
typed errors and keeping a single `decision` (`VerificationOutcome`, `verification.py:38-43`).

---

## 8. Confirmation: no code changes Jev's decision semantics or treats UNSUPPORTED as "absent"

**Answer: no production code changes the three-way semantics, and no production code drops a
document from inventory on `UNSUPPORTED`.** The semantics are used exactly once, in the
persistence branch (`pipeline.py:139-148`):

- `SUPPORTED` → durable claim.
- `UNSUPPORTED` / `UNDECIDED` → candidate observation + verification observation (document stays findable).

Specific evidence and the one caveat to watch:

1. **`UNDECIDED` is never `UNSUPPORTED`.** `verification.py:65-66` only downgrades `SUPPORTED → UNDECIDED`;
   the two non-supported states are never collapsed. The experiment freezes this as
   `"undecided_is_not_unsupported": True` (`jev_property_verify.py:564`, `jev_end_to_end.py:506`).
2. **`UNSUPPORTED` never supersedes an existing claim.** `persistence.py:127` docstring; a
   `UNSUPPORTED` write is a *new observation*, not a claim mutation.
3. **Non-SUPPORTED candidates remain in lookup by default.** `lookup_document_properties(..., include_candidates=True)`
   (`persistence.py:178-196`), and `_candidate_hits` reads `document_property_candidate` observations
   (`persistence.py:238-274`).
4. **The only "drop" is an explicit opt-in read filter**, `include_candidates=False`
   (`persistence.py:182-195`), which returns supported-only rows for a caller that asks for them — it
   does not delete anything from inventory.
5. **Experiment-side "lost documents" is a simulated measurement, not behavior.**
   `jev_property_verify._lost_documents` (`jev_property_verify.py:440-445`) reports documents that
   *would* be lost under a hypothetical soft filter, labeled *"Lost documents under a simulated soft
   filter"* (`jev_property_verify.py:674-678`). It does not filter anything.
6. **Naming collision to be aware of (experiment only).** The experiment's *discovery* registry uses a
   different `support` field with its own `SUPPORTED / SUPPORTED_NEGATIVE / UNDECIDED` constants
   (`document_properties.py:34-37`), and `ranked_documents` / `lookup_documents` filter to
   `support == SUPPORTED` (`document_properties.py:163-187`). That `SUPPORTED` is a **rule-level
   lexical match**, not the Jev verification verdict — and it is the discovery index, not the Jev chain.
   The production code does **not** carry this collision: production has a single verdict namespace
   (`model.py:7-11`) and persistence never filters a document out on `UNSUPPORTED`.

---

## Appendix — file inventory read

**Production**
- `backend/app/jev/system.py` — TypeSafe System One HTTP adapter
- `backend/app/services/document_properties/{__init__,model,taxonomy,discovery,verification,local_dense,pipeline,persistence}.py` — new chain (created today)
- `backend/app/services/knowledge/{claims,observations,persist,identity,answer_review,answer_review_classification,answer_review_worker}.py`
- `backend/app/services/graph_v2/{jev_judge,questions,result_prompts}.py`
- `backend/app/database/{models,knowledge_observation,answer_review}.py`
- `backend/app/config.py` (Jev settings)
- `backend/tests/test_document_properties_{verification,persistence,pipeline}.py`

**Docs**
- `docs/document-property-phase1-design.md`, `docs/document-property-integration-inventory.md`, `docs/guides/text-unit-knowledge.md`

**Experiment**
- `experiments/overgraph_ingest/overgraph_ingest/jev/{client,questions,__init__}.py`
- `experiments/overgraph_ingest/overgraph_ingest/retrieval/{document_properties,jev_property_verify,jev_end_to_end,jev_local_query_abc,jev_presentation_v1,jev_validation_v1}.py`
- `experiments/overgraph_ingest/overgraph_ingest/doctags/source.py`
- `experiments/overgraph_ingest/retrieval_gold/document_properties/taxonomy-v1.json`
