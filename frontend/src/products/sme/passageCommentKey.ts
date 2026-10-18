import type { DocumentKnowledgeAnchor } from "@/api/underlag"

export function passageCommentKey(
  sourceId: string,
  anchor: Pick<DocumentKnowledgeAnchor, "page_number" | "exact_text" | "prefix_text" | "rects">,
): string {
  const basis = anchor.rects.length
    ? anchor.rects.map(({ x, y, width, height }) => [millionths(x), millionths(y), millionths(width), millionths(height)])
    : [words(anchor.prefix_text), words(anchor.exact_text)]
  return JSON.stringify([sourceId, anchor.page_number, basis])
}

function millionths(value: number): number {
  return Math.round(value * 1_000_000)
}

function words(value: string | null | undefined): string {
  return (value ?? "").trim().split(/\s+/).filter(Boolean).join(" ")
}
