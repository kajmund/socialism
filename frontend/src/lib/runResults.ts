import type { OasisRunResults, OasisVariantResult } from "@/data/runs-types"

export function findRunVariant(
  results: OasisRunResults | null | undefined,
  attemptId: string,
  variantId: string,
): OasisVariantResult | null {
  if (!results) return null
  for (const attempt of results.attempts ?? []) {
    if (attempt.id !== attemptId) continue
    return attempt.variants.find((variant) => variant.id === variantId) ?? null
  }
  if (attemptId !== "legacy") return null
  return results.variants?.find((variant) => variant.id === variantId) ?? null
}
