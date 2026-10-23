/** Display raw cosine similarity, never a probability percentage. */

export function formatSimilarity(score: number | null | undefined, locale: string): string {
  if (score == null || Number.isNaN(score)) return "—"
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(score)
}
