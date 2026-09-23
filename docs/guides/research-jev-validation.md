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



## Compact legal context

The compact Jev payload now preserves legal relation, confidence, a bounded explanation, up to three bounded unresolved questions, source truncation, and (when available) preparatory-work speaker, source text role and requested text role. This applies both to evidence screening and state assessment. Changes to the legal interpretation alter the compact-input digest, so a cached item score is not reused merely because the displayed excerpt stayed the same. Full source bodies and attribution quotations are not sent in this context block.

A paired live probe used the same public question about the special commentary in prop. 1975/76:81 and the same 280-character excerpt of consultation responses from the earlier provider probe. The second input added the verified consultation/contextual classification. With the configured `jev-latest` request resolving to `openjev-0.1`, `answerable_now` changed from 0.7778 to 0.0925, `material_gap` from 0.8834 to 0.9951, and `follow_up_change` from 0.1213 to 0.9523. Input size was 750 versus 1,278 characters; observed latency 1.92 versus 1.38 seconds. The context in this diagnostic pair was explicitly assembled from the verified source role and prior provider result, rather than replaying an entire stored research attempt. These are uncalibrated Noul scores from one pair, not probabilities of correctness or evidence of a general latency improvement. Shadow mode remains appropriate.

Focused Jev/controller tests: 34 passed, including preserved text roles, interpretation-sensitive input digests, and bounded context for large explanations.


## Per-need replay and exclusion regression

A read-only replay of the same stored attempt partitioned the plan by ResearchNeed and included evidence linked through either `research_need_ids` or the primary `research_need_id`. With configured bounded concurrency, 15 Jev requests completed in 5.63 seconds and represented 52 of 54 unique evidence items; one scoped input was still clipped. Outcomes were eight uncertain and seven insufficient, with no sufficient shortcuts. Total reported tokens were 24,787. The replay included existing questions, compact excerpts and quality metadata, but not stored structured legal analyses. Therefore it is a coverage experiment, not an exact replay of the latest production input format or a quality calibration.

One disagreement exposed an actual stored assessment error. `followup_10` asks for HD cases *other than* NJA 1983 s. 332 and NJA 1989 s. 346. The stored assessment says `sufficient=true` and lists those same two cases as supporting evidence. Its own `missing_or_weak` says that only the excluded cases are present and that further cases are required. Both stored domain relations also incorrectly call those cases support for the request for additional cases. Jev's per-need `answerable_now` score was approximately 0.000072 and its outcome insufficient. The stored LLM label is therefore not a trustworthy gold label for this case.

The remaining retrieval fix must preserve citation intent: a citation explicitly excluded by a question must not be interpreted as a requested direct lookup, and a named-citation shortcut must not replace the search for additional cases. This requires semantic interpretation of the question's constraints; a blanket rule that any non-empty `missing_or_weak` invalidates sufficiency would also reject acceptable answers with minor caveats.

The user subsequently authorized the derived legal-analysis metadata transfer. The prepared 15-need replay completed in 5.39 seconds with 28,021 reported tokens: 13 insufficient, one uncertain and one sufficient score classification. Local preparation loaded 47 structured legal results; their bounded context increased input size, reducing represented evidence from 52 to 41 of 54 unique items and increasing clipped states from one to six under the same budgets. Consequently this is not a controlled metadata-only comparison or a calibrated quality result.

The only sufficient classification (`research_4`) had clipped input. Production's existing truncation guard would prevent the positive shortcut; this diagnostic script reports raw score classifications rather than applying the full production gate. There were no positive classifications on complete inputs. `followup_10` remained insufficient on an unclipped 3,506-character input, with answerability about 0.0000021 and material-gap score about 0.9999978. These are model scores, not calibrated correctness probabilities. No stored assessment or attempt was modified, and Jev remains in shadow mode.

Inspection confirmed the retrieval mechanism behind the exclusion regression: `_case_law_candidates` resolves every named case and returns immediately when any resolves, while `_select_candidates` retains direct hits unconditionally. Thus named exclusions can both enter the evidence and prevent discovery of additional cases. The repair must distinguish citation intent before the direct-lookup shortcut, preserve exclusions when searching, and verify that excluded canonical sources cannot re-enter through search or citation-graph results. That repair is not implemented yet. Backend `/health` returned `ok`; PR #297's updated concurrency commit passed CI.

## Citation-intent repair (local, migration 117)

Named case-law questions now pass through a structured, provider-owned citation
intent planner. Every recognized citation must be classified exactly once as a
requested target, an explicit exclusion, or contextual example. Discovery queries
are required for non-target roles. Direct-lookup completion applies only when no
additional search is requested. Exclusions are resolved to canonical document
identities and filtered from merged candidates, including fragment URLs. An
unresolvable exclusion or failed intent call produces an explicit selection
failure before an unsafe search can proceed. Questions without named cases incur
no additional intent call. The generic research engine is unchanged.

The first live intent probe exposed model errors despite passing boundary tests:
"utöver" was classified as context, and an open question with examples was
restricted to named targets. Explicit prompt examples corrected these three
observed cases: exclusions, a comparison of named cases, and open discovery with
examples. The corrected three-call probe took 1.87, 1.18 and 3.05 seconds
respectively. These observations do not establish general semantic accuracy.

A discovery query containing the entire requested analysis produced zero hits.
The prompt now asks for a short substantive query, retaining detailed constraints
in the original question for selection. A subsequent live candidate probe took
2.58 seconds, resolved both excluded cases, searched `36 § avtalslagen`, and
returned ten other candidates. Neither excluded case was returned. Candidates
included lower-court and irrelevant-number matches, so candidate counts are not
evidence counts.

The full provider probe took 5.50 seconds and returned `not_found` with
`irrelevant_relation`: selection discarded the candidates before full-text
retrieval. That call generated a somewhat longer search query despite the revised
instruction. The original false direct-answer path is addressed, but discovery
quality and restrictive snippet selection still need investigation. No claim is
made that this question is now answered, and no stored run was changed.

Local verification: 117 tests passed across citation intent, provider, selector,
passage retrieval, Jev controller and source attribution; targeted Ruff checks and
`git diff --check` passed. Migration 117 was applied to the local PostgreSQL
database and backend health returned `ok`. This legal retrieval change remains
local and is not part of the independent Jev PR #297.

## Grounded selection triage (local, migration 118)

A fresh diagnostic disproved a blanket conclusion that selection always rejects
all candidates. The same question generated a different discovery query
(`36 § avtalslagen oskälighetsbedömning`), and the old selector kept two HD cases.
The complete provider probe took 20.25 seconds and returned one model-classified
supporting result (NJA 1999 s. 408) and one contextual result (NJA 2010 s. 467).
These are interpreter outputs, not an independently verified legal gold set.
Search-query variation prevents treating this as a controlled improvement over
the prior 5.50-second empty result.

The recorded selector explanations exposed a separate issue: they asserted that
the final court used section 36 decisively and identified the weightiest factors,
although the supplied snippets did not establish those claims. The new required
DB prompt `research.lagen_nu.select.triage` makes this a pre-full-text decision.
`potentially_relevant` is now a supported selector role. The model may retain a
plausible source for inspection while explicitly listing what still needs checking;
missing detail in a snippet is not itself proof of irrelevance. Proven wrong
courts/subjects and exclusions still warrant rejection. This does not grant
supporting-evidence status, alter the interpreter, or increase retrieval budgets.

A paired diagnostic reused exactly the same seven saved candidate snippets,
question and configured model, with the new triage instruction. In 2.24 seconds it
kept the same two HD candidates as `potentially_relevant`, explicitly requiring
full text to verify the requested circumstances. It rejected the other five
candidates for the court mismatch. Unlike the previous explanations, it did not
claim the full question was already established. This is one paired example, not
a calibration or an end-to-end latency benchmark.

Local validation: 118 relevant tests passed, including preservation of the new
role across the structured-model boundary; Ruff and diff whitespace checks passed.
Migration 118 was applied locally. A narrow Kibana query for selection/extraction
failures over the preceding 30 minutes returned no matches; the standalone probes
are separate from normal runtime logging, so that absence does not prove success.
