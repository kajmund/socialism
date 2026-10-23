# Architecture review: PR #428 and PR #429

Reviewed 2026-10-23 against ticket 34 and the one-shared-SSR principle.

## Verified PR status

| PR | Branch | State | CI |
| --- | --- | --- | --- |
| #428 | `cursor/ssr-clause-anchor-library-2366` | OPEN, MERGEABLE | green (12 checks) |
| #429 | `cursor/tabular-review-ssr-6c10` | OPEN, MERGEABLE | green (12 checks) |

Both branches were fetched as `review/pr-428` and `review/pr-429`; neither is
merged. GitHub search alone was not sufficient; `gh pr view` gave the verifiable
status above.

## What each PR actually implements

**#428** adds an isolated `clause_ssr` service and `/clause-ssr` admin API. It
stores `SsrClassification`, `SsrVerification`,
`SsrVerificationRevision`, `SsrClauseAnchor`, `SsrClauseAnchorSet` and review
sessions in Overgraph, reusing TextUnits, tenant scope, stored TextUnit vectors
and `ssr.similarity.cosine_similarity`. YES/NO are verified labels; skip/unsure
are not; promotion to a draft anchor is explicit; anchor sets are versioned and
only active sets match. It is not wired into research/SWE and fails loud on
missing vectors. Tests cover admin auth, queue/undo, idempotence, tenant
isolation, source/model revocation and no research imports.

**#429** adds Tabular Review. Its reuse audit extends the existing SQL SSR
anchor library with `AnchorKind = Literal["tone", "style", "clause"]` and
Tabular Review columns reference `SsrAnchorSet(kind="clause")`; publishing a
clause set skips the tone/style calibration gate. Approve/reject writes a
tabular-review label, not an SSR anchor. It does **not** import `clause_ssr` and
does not use #428's verification queue, promotion or Overgraph anchor sets.

## Finding: the PRs create two clause-anchor systems

| Concern | #428 | #429 |
| --- | --- | --- |
| Clause anchor store | Overgraph `SsrClauseAnchor` / sets | SQL `SsrAnchorSet(kind="clause")` |
| Human verification | Ja/Nej/Osäker queue, revision history | No verification queue; admin-created anchor set |
| Activation | Explicit promote + active anchor set | Existing SQL publish path; calibration skipped |
| Matching | `/clause-ssr/match`, cosine, abstention | Tabular Review cell ranking over SQL anchor set |
| Versioning | Overgraph anchor-set version | SQL anchor-set version |
| Reuse of TextUnits/vectors/tenant | Yes | TextUnits reused; no clause verification/index reuse |

This is the duplication ticket 34 was meant to prevent. #429 has no dependency
on #428, so merging both as-is leaves two incompatible clause libraries and two
sources of truth for activation/quality.

## Reuse assessment

PR #428 deliberately does **not** extend the SQL tone/style library; its reuse
audit argues that report-reaction anchors and grounded clause anchors are
different domains. It nevertheless reuses the shared primitives (TextUnits,
tenant scope, stored embeddings, cosine, admin chrome) and adds no second
vector store. That is a defensible domain boundary, but it must be declared the
single clause-anchor subsystem.

PR #429 reuses the SQL library but bypasses precisely the properties ticket 34
required for clause anchors: human verification, explicit activation gate and a
searchable clause index. `kind="clause"` turns the report-SSR table into a
second clause anchor source.

## Recommendation

1. **Adopt #428 as the clause-anchor subsystem** after normal review. It already
   provides verification, revision, explicit promotion, versioned anchor sets,
   tenant isolation and a no-Jev match API, and it reuses TextUnits/vectors
   rather than adding a store. Revise the ticket-34 architecture: for the
   clause domain Overgraph is the authoritative store (no Postgres/Overgraph
   dual-write sync); Postgres `ssr_anchor_sets` remains the report tone/style
   authority.
2. **Do not merge #429 as-is.** Rework it on top of #428: clause columns should
   resolve their category/anchor set through the shared clause service (or a
   thin shared adapter), not through `SsrAnchorSet(kind="clause")`. Remove the
   SQL `kind="clause"` path or restrict it to non-anchor review metadata. Keep
   Tabular Review's own approve/reject row labels, but do not let them create
   anchors implicitly.
3. Merge order: merge #428 first; rebase #429 on it; keep the shared frontend
   integration tests; then merge #429.
4. Do not start tickets 35–37 as new implementations. They are covered by #428
   pending merge/review. Ticket 38 (D comparison) waits for the merged clause
   service and an unseen-contract benchmark.

Alternative if Postgres must be authoritative: refactor #428 into the SQL
anchor-set/verification model and add an Overgraph index sync. That is a larger,
dual-write design; the current evidence favors #428's single Overgraph clause
store.

## Blocking finding in #428: verification revocation does not cascade

Code review of the three requested properties:

| Property | Verdict |
| --- | --- |
| Verification and activation are separate | Pass. A YES creates a verification; `promote_anchor` creates a draft anchor; `build_anchor_set` is the explicit activation step. A YES alone is not an active anchor (`test_yes_is_not_an_active_anchor`). |
| Negative anchors are category-specific | Pass by design: anchors carry the verification `category`; sets are built per category; matching groups members by category and only applies negatives within that category. No explicit cross-category negative test exists — add one. |
| Revocation takes effect immediately | **Fail.** `revoke_verification` only writes the verification status `revoked`; it does not revoke anchors derived from that verification. `record_decision` with a changed answer archives the old revision but also leaves old promoted anchors untouched. An active anchor set can therefore keep scoring a revoked or superseded verification. `revoke_source_unit` happens to revoke anchors first, but normal undo/answer-change does not. |

This violates the requirement that a recalled anchor cannot keep influencing
matching through an older published set. The match path itself reads current
Overgraph state (no application cache), so fixing the anchor status is
sufficient: `revoke_verification` and answer changes must revoke every anchor
whose `verification_id` matches, and tests must cover undo and yes→no with a
promoted anchor + active set.

## Pre-merge checklist

- [ ] Run backend tests for `test_clause_ssr_*` and tabular review on the
      rebased branches (CI is green, but review locally after rebase).
- [ ] Confirm `/clause-ssr` remains admin-only and tenant-isolated.
- [ ] Confirm research/SWE imports do not include `clause_ssr`.
- [ ] Confirm matching uses stored vectors only and fails loud on missing/wrong
      model version; scores labelled cosine, not probability.
- [ ] Fix the revocation cascade in #428 (verification revoke and answer change
      revoke derived anchors; active sets can no longer return them).
- [ ] Add a cross-category negative-anchor test (NO for termination must not
      suppress pricing).
- [ ] Confirm only verified, explicitly promoted, active anchors match.
- [ ] Confirm Tabular Review has no independent clause-anchor source after the
      rework.
- [ ] Rebase #429 on #428 and resolve shared `App.tsx` / i18n / nav / docs
      conflicts.
