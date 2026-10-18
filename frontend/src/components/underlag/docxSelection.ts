import type { DocumentKnowledgeAnchor } from "@/api/underlag"

export function docxSelectionAnchor(root: HTMLElement, selection: Selection): DocumentKnowledgeAnchor | null {
  if (!selection.anchorNode || !selection.focusNode) return null
  if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null
  if (selection.isCollapsed) return null
  const exact = selection.toString().replace(/\s+/g, " ").trim()
  if (!exact) return null
  const prefix = plainTextBefore(root, selection.anchorNode, selection.anchorOffset).slice(-80) || null
  return {
    anchor_type: "text",
    page_number: null,
    locator: "document",
    rects: [],
    suffix_text: null,
    asset_id: null,
    exact_text: exact,
    prefix_text: prefix,
  }
}

function plainTextBefore(root: HTMLElement, node: Node, offset: number): string {
  const range = root.ownerDocument.createRange()
  range.setStart(root, 0)
  range.setEnd(node, offset)
  const copy = range.cloneContents()
  copy.querySelectorAll("[data-mark-label]").forEach((label) => label.remove())
  return (copy.textContent ?? "").replace(/\s+/g, " ")
}
