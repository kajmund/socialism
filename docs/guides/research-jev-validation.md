# Jev research validation — 2026-09-23

## Observed failures and fixes

Kibana showed four failed Jev assessments in one 15-need research attempt. The
attempt took roughly 25.6 minutes and ended with 54 evidence items and two
answered needs. The four LLM assessments took approximately 22.3, 31.9, 21.2 and
38.8 seconds. These are stage timings, not an end-to-end speed benchmark.

A synthetic request reproduced HTTP 400: the configured research default
`jev-1.12` was rejected as an unknown model. Research now inherits `JEV_MODEL`
unless `RESEARCH_JEV_MODEL` explicitly overrides it. Explicit invalid overrides
are still sent as configured and fail; no alternate model is retried.
Other fixes:

- HTTP 4xx usage errors are categorized as `invalid_request`, not `unknown`.
- Injected HTTP clients receive the requested per-call timeout.
- Nonfinite Noul probabilities are rejected.
- Evidence ranking survives compaction, instead of being replaced by ID sorting.
- A bounded, assessor-local cache reuses successful evidence-screen decisions
  only for the same model and exact compact input (including the objective and
  quality metadata). Changed inputs and failed requests are not reused.
- Compaction removes repeated context before discarding source excerpts.
- Oversized metadata is rejected before a network call. Any truncated input
  disables the automatic sufficient/complete shortcut, even if Jev returns
  confident positive probabilities.

## Read-only replay

The user authorized sending the existing questions and compact evidence to the
already configured Jev endpoint. No attempt, assessment or evidence was mutated.

The initial replay reproduced the Kibana input hash exactly, returned
`insufficient` in 1.837 seconds and agreed directionally with the saved LLM
assessment. That input was 8,427 characters despite a 6,000-character budget.
The old compaction had removed all source excerpts.

After the compaction fix, the same attempt produced 5,982 characters containing
one evidence excerpt and returned `insufficient` in 1.827 seconds. The provider
reported model `openjev-0.1` for the configured `jev-latest` request. These
measurements describe that configured endpoint and resolved model, not a claim
about every deployment of the public Jev API.

This is one negative case, not a calibration set or proof of legal correctness.
The large plan still leaves room for very little evidence. It remains in shadow
mode, and the truncation guard prevents activating a shortcut on this input.

## Further work

- Evaluate need-scoped compact states on positive, negative and contradictory
  cases, including the final-court/party-submission distinction.
- Measure the complete retrieval/extraction/assessment path, not just Jev time.
- Resolve passages inside named, truncated preparatory works. A live search
  demonstrated that a special-motivation keyword can return the table of contents
  rather than the substantive section. Exact document identity and grounded
  passage selection are necessary.
- Preserve separate metrics for missing evidence, malformed questions, failed
  retrieval and failed model calls.

## Local verification

The research/legal/provider suite passed (395 tests, nine opt-in live tests
skipped) before the final Jev additions. Dedicated Jev regressions cover model
selection, invalid requests, nonfinite values, timeout propagation, ranking,
cache invalidation, compaction and the truncated-input shortcut guard.

A full local backend run initially produced 1,992 passed and nine filesystem
permission failures. Rerunning the affected tests with permission resolved eight;
an existing OASIS test still expects follower text absent from its default
prompt template. The OASIS implementation and test were not changed here.

