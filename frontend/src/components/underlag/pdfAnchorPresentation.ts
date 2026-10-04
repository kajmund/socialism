import type { DocumentAnchorRect, DocumentKnowledgeAnchor } from "@/api/underlag"

type PdfAnchor = Pick<DocumentKnowledgeAnchor, "locator" | "rects"> & { page_number?: number | null }

export function pdfAnchorKind(anchor: PdfAnchor): "document" | "page" | "unlocatable" {
  if (typeof anchor.page_number === "number" && Number.isInteger(anchor.page_number) && anchor.page_number > 0) return "page"
  // read_source cites the whole document without inventing a PDF page or rectangle.
  if (anchor.locator === "document" && anchor.page_number == null && anchor.rects.length === 0) return "document"
  return "unlocatable"
}

export function pdfAnchorRectangles(anchor: PdfAnchor): DocumentAnchorRect[] {
  if (pdfAnchorKind(anchor) !== "page" || !anchor.rects.length) return []
  const valid = anchor.rects.every((rect) => [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)
    && rect.x >= 0 && rect.y >= 0 && rect.width > 0 && rect.height > 0
    && rect.x + rect.width <= 1 && rect.y + rect.height <= 1)
  return valid ? anchor.rects : []
}

export function pdfPresentationStatus(anchors: PdfAnchor[], renderComplete: boolean, matchedAnchors: number): "pending" | "ready" | "anchor_missing" {
  if (!renderComplete) return "pending"
  const required = anchors.filter((anchor) => pdfAnchorKind(anchor) !== "document")
  if (required.some((anchor) => !pdfAnchorRectangles(anchor).length) || matchedAnchors < required.length) return "anchor_missing"
  return "ready"
}
