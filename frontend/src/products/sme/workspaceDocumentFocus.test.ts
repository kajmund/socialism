import { describe, expect, it } from "vitest"
import type { UnderlagFile } from "@/api/underlag"
import type { SourceReference } from "@/api/voiceWorkspaces"
import { workspaceFocusReference } from "./workspaceDocumentFocus"

const source: UnderlagFile = { id: "pdf", kind: "underlag", filename: "example.pdf", content_type: "application/pdf", size_bytes: 100, module: "sme", owner_user_id: null, folder_id: null, extraction_status: "ok", created_at: "2026-10-04T00:00:00Z" }
const reference: SourceReference = { reference_id: "passage", number: 1, source_id: source.id, source_kind: "underlag", title: source.filename, excerpt: "Period June 1–30", source_version: "v1", stale: false, anchor: { anchor_type: "text", locator: "page:1", page_number: 1, exact_text: "Period June 1–30", rects: [], prefix_text: null, suffix_text: null, asset_id: null } }
const workspace = { sources: [source], references: [reference] }

describe("workspace focus confirmation", () => {
  it("requires a verified reference rather than acknowledging document opening as a highlight", () => {
    expect(() => workspaceFocusReference(workspace, undefined)).toThrow("document_anchor_position_required")
    expect(() => workspaceFocusReference(workspace, "unknown")).toThrow("document_anchor_position_required")
  })
  it("rejects a whole-document reference before changing the current document", () => {
    const whole = { ...reference, anchor: { ...reference.anchor!, page_number: null, locator: "document" } }
    expect(() => workspaceFocusReference({ ...workspace, references: [whole] }, whole.reference_id)).toThrow("document_anchor_position_required")
    expect(workspace.references).toEqual([reference])
  })
  it("accepts a localized passage for subsequent verification by the PDF renderer", () => {
    expect(workspaceFocusReference(workspace, reference.reference_id)).toBe(reference)
  })
  it("requires a valid page and nonempty position or text in a PDF passage", () => {
    for (const anchor of [{ ...reference.anchor!, page_number: null }, { ...reference.anchor!, page_number: 0 }, { ...reference.anchor!, exact_text: " " }]) {
      expect(() => workspaceFocusReference({ ...workspace, references: [{ ...reference, anchor }] }, reference.reference_id)).toThrow("document_anchor_position_required")
    }
  })
  it("allows an exact text passage without a page in a plain-text document", () => {
    const textReference = { ...reference, anchor: { ...reference.anchor!, page_number: null, locator: "line:4" } }
    expect(workspaceFocusReference({ sources: [{ ...source, content_type: "text/plain" }], references: [textReference] }, reference.reference_id)).toBe(textReference)
  })
})
