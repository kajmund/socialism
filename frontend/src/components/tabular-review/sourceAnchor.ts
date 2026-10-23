import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { TabularReviewSource } from "@/api/tabularReviews"

export function sourceToFocusAnchor(source: TabularReviewSource | undefined): DocumentKnowledgeAnchor | null {
  if (!source) return null
  const page = source.page_start ?? null
  const rects = source.rects ?? []
  return {
    anchor_type: "text",
    page_number: page,
    locator: source.locator ?? null,
    exact_text: source.exact_text ?? null,
    prefix_text: null,
    suffix_text: null,
    rects,
    asset_id: null,
  }
}

export function sourcePage(source: TabularReviewSource | undefined): number | undefined {
  return source?.page_start ?? undefined
}
