import { describe, expect, it } from "vitest"
import type { UnderlagFile } from "@/api/underlag"
import type { SourceReference, WorkspaceState } from "@/api/voiceWorkspaces"
import { clearWorkspaceDocumentSelection, workspaceFocusReference } from "./workspaceDocumentFocus"

const source: UnderlagFile = { id: "pdf", kind: "underlag", filename: "example.pdf", content_type: "application/pdf", size_bytes: 100, module: "sme", owner_user_id: null, folder_id: null, extraction_status: "ok", created_at: "2026-10-04T00:00:00Z" }
const reference: SourceReference = { reference_id: "passage", number: 1, source_id: source.id, source_kind: "underlag", title: source.filename, excerpt: "Period June 1–30", source_version: "v1", stale: false, anchor: { anchor_type: "text", locator: "page:1", page_number: 1, exact_text: "Period June 1–30", rects: [], prefix_text: null, suffix_text: null, asset_id: null } }
const workspace = { sources: [source], references: [reference] }

function documentState(): WorkspaceState {
  return {
    language: "sv", knowledge_scope: "workspace", view: "documents",
    documents: [{ source_id: source.id, page: 2, zoom: 1.1, reference_id: null }, { source_id: "other", page: 7, zoom: 0.8, reference_id: "other-passage" }],
    split_source_ids: [source.id, "other"], active_artifact_id: "draft", research_attempt_ids: ["research"], selection: null,
  }
}

describe("clearing a workspace document selection", () => {
  it("clears a cited selection linked through references without changing either pane's position", () => {
    const state = { ...documentState(), selection: { reference_id: reference.reference_id } }
    const before = structuredClone(state)
    const cleared = clearWorkspaceDocumentSelection(state, source.id, workspace.references)

    expect(cleared).toEqual({ ...state, selection: null })
    expect(cleared.documents[1]).toBe(state.documents[1])
    expect(workspace.references).toEqual([reference])
    expect(state).toEqual(before)
  })
  it("clears a manual selection linked directly to the clicked source", () => {
    const state = { ...documentState(), selection: { source_id: source.id, anchor: reference.anchor! } }
    const cleared = clearWorkspaceDocumentSelection(state, source.id, [])

    expect(cleared.selection).toBeNull()
    expect(cleared.documents).toEqual(state.documents)
    expect(state.selection.anchor).toBe(reference.anchor)
  })
  it("clears a queued citation using the document reference before reference metadata arrives", () => {
    const state = documentState()
    state.documents[0] = { ...state.documents[0], reference_id: "fresh-passage" }
    state.selection = { reference_id: "fresh-passage" }
    const cleared = clearWorkspaceDocumentSelection(state, source.id, [])

    expect(cleared.selection).toBeNull()
    expect(cleared.documents[0]).toEqual({ ...state.documents[0], reference_id: null })
    expect(cleared.documents[1]).toBe(state.documents[1])
    expect(state.documents[0].reference_id).toBe("fresh-passage")
  })
  it("preserves another pane's selection and returns the same state for an already clear document", () => {
    const state = documentState()
    state.documents[0] = { ...state.documents[0], reference_id: reference.reference_id }
    state.selection = { source_id: "other", reference_id: "other-passage" }
    const cleared = clearWorkspaceDocumentSelection(state, source.id, workspace.references)

    expect(cleared).toEqual({ ...state, documents: [{ ...state.documents[0], reference_id: null }, state.documents[1]] })
    expect(cleared.selection).toBe(state.selection)
    expect(cleared.documents[1]).toBe(state.documents[1])
    expect(clearWorkspaceDocumentSelection(cleared, source.id, workspace.references)).toBe(cleared)
  })
})

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
