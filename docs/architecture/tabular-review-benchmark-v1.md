# Tabular Review real-corpus benchmark v1

Status: protocol and prerequisites. No benchmark has been run against real
contracts yet; the existing 200-document script is scripted and must not be
presented as product quality.

## Why this exists

Ticket 40 must measure the merged SSR-only Tabular Review on the real corpus,
not on synthetic vectors. Two prerequisites are missing in this environment:

1. A human-verified clause-localization facit with document positions.
2. The ~200-contract corpus ingested into the real Postgres + Overgraph stack.

The synthetic SME package has 424 contract files and a generator ground truth
with contract attributes (`notice_months`, `auto_renew_months`,
`liability_cap`, `pricing_model`, ...), but it has no human-verified
clause-location facit, and it is not the real customer corpus. Generator
metadata is not a substitute for human review.

## Facit schema (versioned)

One row per contract × clause category:

```json
{
  "facit_version": "v1",
  "corpus": "real-200-2026-10",
  "case_id": "CTR-...",
  "document_version_id": "...",
  "category": "termination_notice",
  "present": true,
  "clause_text": "ordagrann klausul",
  "locator": {"paragraph": 12, "char_start": 340, "char_end": 512,
              "page_start": 3, "page_end": 3},
  "verifier": "human-id",
  "reviewed_at": "2026-10-...",
  "review_method": "manual",
  "notes": ""
}
```

Rules:

- `present` means a human found the clause in that contract; absence is a real
  negative, not "not searched".
- `clause_text` must be verbatim and the locator must resolve to it.
- The corpus must be split before anchor building: holdout contracts/categories
  must not appear in the anchor library.
- Review must not use the same Jev/model judgement as the system under test.
- Categories at minimum: `termination_notice`, `price`, `automatic_renewal`,
  `liability_limitation`.

## Measurements

| Metric | Definition |
| --- | --- |
| Time to first row | UI/API time until the first usable row is visible |
| Time to complete table | 200 contracts × 3–10 columns, backend and rendered UI separately |
| Backend scoring time | cosine + cache lookup, excluding UI rendering |
| Cache hit rate | cold vs warm run, including TextUnit/embedding reuse |
| Clause Recall@1/3/5 | best returned clause matches a human facit hit |
| Abstention | fraction of cells reported as `Ingen träff`; separately evaluate correct negatives vs misses |
| Revocation | after an anchor is revoked, new runs cannot return it; locked history is preserved |
| UI performance | scroll, sort, PDF navigation, locked-cell rendering |

A low score must be reported as **Ingen träff**, never as “clause missing”.
Time to first row and time to complete table are separate; a fast cosine score
does not count if the UI waits for all documents.

## Acceptance

- Cold and warm runs on the same 200 documents.
- Human facit holdout evaluated after anchor creation; no test contracts in the
  anchor library.
- No Jev or narrative LLM calls in the benchmark.
- Revocation changes new match results immediately; reviewed/locked cells keep
  their history.
- Scripted timings are labelled as such and excluded from product claims.

## Blocker

Without human clause-localization facit and an ingested real corpus, only
synthetic/scripted timings are possible. Those are not accepted as ticket-40
evidence. Tickets 41 (facit) and 42 (real ingest + harness) must complete
first.
