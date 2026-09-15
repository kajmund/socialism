# Evidence quality and source authority

Developer guide for the generic, auditable quality layer. Operator UI is unchanged.

## Why this exists

Retrieval persists that evidence *exists*. Local sufficiency then asks whether a ResearchNeed has supporting items. Neither judgment says whether those items are authoritative, relevant, current, primary, or independently corroborated.

Quality is a separate, persisted artifact. Downstream reporting and sufficiency can inspect dimensions. v1 does not discard evidence or flip a sufficient result from an aggregate score.

## Placement in the loop

```text
retrieve  →  persist EvidenceSet items  →  need-wave barrier
        →  EvidenceQualityAssessment   (this layer)
        →  local ResearchAssessment
        →  optional follow-up / global completeness
        →  freeze EvidenceSet
```

- Quality runs **after** items are persisted and the need barrier holds, **before** local sufficiency.
- It does not retrieve. It does not mutate `evidence_set_items`.
- Freeze still freezes item contents only. Quality rows are keyed to those items and remain readable after freeze.
- Follow-up waves score **new** items against the then-current set. Existing `(item, policy, model)` rows are not overwritten.

## Artifact

`research_evidence_quality` is immutable per `(evidence_set_item_id, scoring_policy_version, model_version_key)`.

| Field | Meaning |
| --- | --- |
| `authority` | `unknown` / `limited` / `official` from declared provider metadata only |
| `relevance` | `unknown` unless an injectable relevance assessor returns a structured level |
| `currentness` | `known` only when a parseable source timestamp is present; otherwise `unknown` |
| `source_nature` | `unknown` / `primary` / `secondary` from declared keys |
| `independence_key` | Canonical underlying-source identity (URL fragment stripped) |
| `independent_source_count` | Distinct keys among **found** items for the same ResearchNeed |
| `flags` | Explicit limitations (`not_official_publication`, `authority_warning`, …) |
| `declared_signals` | The authority keys actually used (audit) |
| `scoring_policy_version` | `1` today (`EVIDENCE_QUALITY_POLICY_VERSION`) |
| `model_*` | Relevance-model identity when a model ran; empty for programmatic scoring |

Retry with the same item + policy + model version returns the existing row. A new policy or model version may add a new row; old rows stay so earlier runs remain reproducible.

## Signals (programmatic first)

The scorer reads `KnowledgeProviderDescriptor.authority` when a descriptor matches the item (`provider_id`, `{provider}.{source_type}`, or `retrieval_provider` + evidence nature). It also copies the same keys from item provenance when the descriptor omitted them.

Recognized keys (generic, not legal-specific):

- `official_publication`, `not_official_publication`, `automated_corpus`
- `primary_source`, `source_nature`
- `authority_warning`, `authority_level`
- recency: `published_at`, `updated_at`, `document_date`, `source_date`, `issued_at`, `effective_date`

Missing keys stay `unknown`. The scorer does not invent official status, dates, or independence from excerpt text.

lagen.nu demonstrates this with the keys it already declares (`not_official_publication`, `automated_corpus`, `authority_warning`). The engine has no lagen.nu branch.

## Relevance seam

`EvidenceRelevanceAssessor.judge(need, item)` is optional structured output. The research package does not call an LLM. A production implementation may live under `app.llm/` and be injected into `execute_attempt_research`.

Model or parse failure records `relevance=unknown` plus `relevance_assessment_failed`. It must not become `high` and must not fail the Attempt.

## Local sufficiency (conservative)

Quality drafts are attached to `AssessableEvidence.quality` so an assessor can see dimensions and hard warnings. v1 programmatic sufficiency still means “at least one found item per need”. Hard warnings are not a discard rule and do not change a sufficient result.

## Reproducible policy changes

1. Keep `EVIDENCE_QUALITY_POLICY_VERSION = "1"` until the scoring rules change.
2. When rules change, bump the version string. New rows use the new version; old rows are left intact.
3. Read models expose `scoring_policy_version` and `model_version` so a later report can say which policy judged the item.
