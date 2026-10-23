# Tabular Review — SSR-only v1

Opt-in contract table. One agreement per row, one SSR category per column.
Cells show the best **verbatim** TextUnit, a cosine **similarity** score, and a
source locator that already exists on the unit.

This is not Legora and does not copy their visual language.

## What v1 does

- Persistent review: name, document set, columns, sort/filter, threshold, cell reviews.
- Columns reference the SSR anchor library (`kind=clause`) plus polarity.
- Ranking is deterministic: `(-similarity, text_unit_id)`.
- Below the threshold the cell is **Ingen träff**. That is not “clause missing”
  and not negative evidence.
- Unknown/abstain when the column allows it and the top two scores are too close.
- Negative columns can record a negative hit; absence of a hit is still no-hit.
- Review Mode reuses `PdfKnowledgeViewer`. Fallback is page or clause locator.
  Positions are never invented.
- Approve / reject writes a human verification label for exact category +
  TextUnit. It does **not** append `ssr_anchor_pool_items`.
- Locked cells are skipped on rerun.
- Cache key: TextUnit + content hash + AnchorSet id/version/pool revision +
  embedding model + label + polarity.

## What v1 does not do

- No Jev, SWE, research, retrieval, or evidence-sufficiency changes.
- No LLM fill. No price / notice-period extraction.
- No automatic SSR anchor activation.
- Admin is not auto-granted the module. Enable it on the kund.

## API

Prefix `/tabular-reviews`. Requires `available_modules` to include
`tabular_review`.

## Bench

`uv run python scripts/benchmark_tabular_review.py` is a **scripted** 200-document
timing/recall check. It is not a live embedding quality claim.

Reuse audit: [tabular-review-reuse-audit.md](../architecture/tabular-review-reuse-audit.md).
Later phases: [tabular-review-later-phases.md](tabular-review-later-phases.md).
