import { describe, expect, it } from "vitest"
import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import { pdfAnchorKind, pdfAnchorRectangles, pdfPresentationStatus } from "./pdfAnchorPresentation"

const documentAnchor: DocumentKnowledgeAnchor = {
  anchor_type: "text", page_number: null, locator: "document", exact_text: "Document text",
  prefix_text: null, suffix_text: null, rects: [], asset_id: null,
}
const pageAnchor: DocumentKnowledgeAnchor = { ...documentAnchor, locator: "page:2", page_number: 2, rects: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.1 }] }

describe("PDF document presentation and anchor confirmation", () => {
  it("opens a read_source whole-document reference without claiming a highlight", () => {
    expect(pdfAnchorKind(documentAnchor)).toBe("document")
    expect(pdfPresentationStatus([documentAnchor], false, 0)).toBe("pending")
    expect(pdfPresentationStatus([documentAnchor], true, 0)).toBe("ready")
  })

  it("accepts the omitted PDF page field emitted by whole-document backend references", () => {
    const anchor = { ...documentAnchor, page_number: undefined }
    expect(pdfAnchorKind(anchor)).toBe("document")
    expect(pdfPresentationStatus([anchor], true, 0)).toBe("ready")
  })

  it("does not acknowledge an unrendered document with no reference", () => {
    expect(pdfPresentationStatus([], false, 0)).toBe("pending")
    expect(pdfPresentationStatus([], true, 0)).toBe("ready")
  })

  it("requires the cited PDF page to be rendered and its anchor to match", () => {
    expect(pdfAnchorKind(pageAnchor)).toBe("page")
    expect(pdfPresentationStatus([pageAnchor], false, 1)).toBe("pending")
    expect(pdfPresentationStatus([pageAnchor], true, 0)).toBe("anchor_missing")
    expect(pdfPresentationStatus([pageAnchor], true, 1)).toBe("ready")
  })

  it("keeps a missing real anchor visible alongside a whole-document reference", () => {
    expect(pdfPresentationStatus([documentAnchor, pageAnchor], true, 0)).toBe("anchor_missing")
    expect(pdfPresentationStatus([documentAnchor, pageAnchor], true, 1)).toBe("ready")
  })

  it("requires every requested page anchor rather than just one marker", () => {
    const second = { ...pageAnchor, page_number: 3, locator: "page:3" }
    expect(pdfPresentationStatus([pageAnchor, second], true, 1)).toBe("anchor_missing")
    expect(pdfPresentationStatus([pageAnchor, second], true, 2)).toBe("ready")
  })

  it("does not reconstruct geometry or acknowledge a quote-only PDF passage", () => {
    const unpositioned = { ...pageAnchor, rects: [] }
    expect(pdfAnchorRectangles(unpositioned)).toEqual([])
    expect(pdfPresentationStatus([unpositioned], true, 0)).toBe("anchor_missing")
    expect(pdfPresentationStatus([unpositioned], true, 1)).toBe("anchor_missing")
  })

  it("keeps a server-rejected ambiguous quote unresolved even beside a positioned quote", () => {
    const ambiguous = { ...pageAnchor, exact_text: "50 SEK", rects: [] }
    const positioned = { ...pageAnchor, exact_text: "50 SEK" }
    expect(pdfAnchorRectangles(ambiguous)).toEqual([])
    expect(pdfPresentationStatus([positioned, ambiguous], true, 1)).toBe("anchor_missing")
  })

  it("uses real selection or server rectangles without changing the saved anchor", () => {
    const snapshot = structuredClone(pageAnchor)
    expect(pdfAnchorRectangles(pageAnchor)).toBe(pageAnchor.rects)
    expect(pdfPresentationStatus([pageAnchor], true, 1)).toBe("ready")
    expect(pageAnchor).toEqual(snapshot)
  })

  it("rejects invalid or clipped-out geometry instead of acknowledging invisible markers", () => {
    const valid = pageAnchor.rects[0]
    for (const rect of [
      { ...valid, x: -0.1 }, { ...valid, y: -0.1 },
      { ...valid, width: 0 }, { ...valid, height: -0.1 },
      { ...valid, x: Number.NaN }, { ...valid, width: Number.POSITIVE_INFINITY },
      { ...valid, x: 0.9, width: 0.2 }, { ...valid, y: 0.9, height: 0.2 },
    ]) {
      const anchor = { ...pageAnchor, rects: [valid, rect] }
      expect(pdfAnchorRectangles(anchor)).toEqual([])
      expect(pdfPresentationStatus([anchor], true, 1)).toBe("anchor_missing")
    }
  })

  it("rejects a missing page unless the reference explicitly cites the whole document", () => {
    for (const anchor of [
      { ...documentAnchor, locator: null },
      { ...documentAnchor, locator: "page:2" },
      { ...documentAnchor, rects: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.1 }] },
    ]) {
      expect(pdfAnchorKind(anchor)).toBe("unlocatable")
      expect(pdfPresentationStatus([anchor], true, 0)).toBe("anchor_missing")
    }
  })

  it("rejects invalid PDF page numbers instead of treating them as whole-document references", () => {
    for (const page_number of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      const anchor = { ...documentAnchor, page_number }
      expect(pdfAnchorKind(anchor)).toBe("unlocatable")
      expect(pdfPresentationStatus([anchor], true, 0)).toBe("anchor_missing")
    }
  })
})
