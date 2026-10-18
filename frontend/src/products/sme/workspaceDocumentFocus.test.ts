import { describe, expect, it } from "vitest"
import type { UnderlagFile } from "@/api/underlag"
import type { SourceReference, WorkspaceState } from "@/api/voiceWorkspaces"
import { passageCommentKey } from "./passageCommentKey"
import { clearWorkspaceDocumentSelection, foreignPassage, textMarkSegments, textOccurrenceIndex, visibleDocumentMarks, workspaceFocusReference } from "./workspaceDocumentFocus"

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

const reader = { id: "user", name: "Erik Fremred" }
const rect = { x: 0.1, y: 0.2, width: 0.3, height: 0.04 }

describe("visible document marks", () => {
  const marked = { ...reference, reference_id: "marked", anchor: { ...reference.anchor!, rects: [rect] } }
  const otherPage = { ...marked, reference_id: "other-page", anchor: { ...marked.anchor!, page_number: 2, rects: [{ x: 0.2, y: 0.3, width: 0.2, height: 0.05 }] } }
  const expert = { ...marked, reference_id: "expert", marked_by: { kind: "expert" as const, id: "karin", name: "Karin" }, anchor: { ...marked.anchor!, rects: [{ x: 0.4, y: 0.5, width: 0.2, height: 0.04 }] } }
  it("keeps every passage the reader marked", () => {
    const second = { ...rect, y: 0.6 }
    const marks = visibleDocumentMarks([expert], source.id, null, null, {
      cleared: false, manual: true, user: reader,
      drafts: [marked.anchor!, { ...marked.anchor!, rects: [second], exact_text: "Andra stycket" }],
    })
    expect(marks.map((mark) => mark.authorName)).toEqual(["Erik Fremred", "Erik Fremred", "Karin"])
    expect(marks[0].anchor.rects).toEqual([rect])
    expect(marks[1].anchor.exact_text).toBe("Andra stycket")
  })
  it("shows the reader's own selection and named expert marks, not every citation", () => {
    const marks = visibleDocumentMarks([marked, expert], source.id, null, marked.anchor, { cleared: false, manual: true, user: reader })
    expect(marks.map((mark) => mark.authorName)).toEqual(["Erik Fremred", "Karin"])
    expect(marks[0]).toMatchObject({ authorKind: "user", anchor: marked.anchor })
    expect(marks[1]).toMatchObject({ authorKind: "expert", authorId: "karin" })
  })
  it("treats someone else's passage as a comment target", () => {
    const marks = visibleDocumentMarks([expert], source.id, null, null, { cleared: false, manual: false, user: reader })
    expect(foreignPassage(marks, expert.anchor!, source.id, reader.id)?.authorName).toBe("Karin")
    expect(foreignPassage(marks, { ...expert.anchor!, exact_text: "Annat stycke", rects: [{ x: 0.1, y: 0.1, width: 0.1, height: 0.02 }] }, source.id, reader.id)).toBeNull()
    const own = visibleDocumentMarks([], source.id, null, null, { cleared: false, manual: true, user: reader, drafts: [expert.anchor!] })
    expect(foreignPassage(own, expert.anchor!, source.id, reader.id)).toBeNull()
  })
  it("keeps an opened citation visible without calling it the reader's mark", () => {
    const marks = visibleDocumentMarks([marked, otherPage], source.id, null, marked.anchor, { cleared: false, manual: false, user: reader })
    expect(marks).toEqual([{ anchor: marked.anchor, authorKind: "passage", authorId: null, authorName: null, passageKey: passageCommentKey(source.id, marked.anchor!) }])
  })
  it("keeps overlapping marks from every expert", () => {
    const alfons = { ...expert, reference_id: "alfons", marked_by: { kind: "expert" as const, id: "alfons", name: "Alfons" } }
    const marks = visibleDocumentMarks([expert, alfons], source.id, null, null, { cleared: false, manual: false, user: reader })
    expect(marks.map((mark) => mark.authorName)).toEqual(["Karin", "Alfons"])
  })
  it("keeps expert marks after the reader clears their own selection", () => {
    const marks = visibleDocumentMarks([expert], source.id, 1, null, { cleared: true, manual: false, user: reader })
    expect(marks.map((mark) => mark.authorName)).toEqual(["Karin"])
  })
  it("shows a text selection that has no page rectangles", () => {
    const textAnchor = { ...reference.anchor!, page_number: null, locator: "document", rects: [], exact_text: "Priset är 50" }
    const marks = visibleDocumentMarks([], source.id, null, textAnchor, { cleared: false, manual: true, user: reader })
    expect(marks).toEqual([{ anchor: textAnchor, authorKind: "user", authorId: "user", authorName: "Erik Fremred", passageKey: passageCommentKey(source.id, textAnchor) }])
  })
  it("highlights each marked passage in a text document", () => {
    const first = { anchor: { ...reference.anchor!, exact_text: "Priset är 50", prefix_text: "Villkor." }, authorKind: "user" as const, authorId: "user", authorName: "Erik Fremred", passageKey: "first" }
    const second = { anchor: { ...reference.anchor!, exact_text: "Priset är 80", prefix_text: "Övrigt." }, authorKind: "user" as const, authorId: "user", authorName: "Erik Fremred", passageKey: "second" }
    const segments = textMarkSegments("Villkor. Priset är 50. Övrigt. Priset är 80.", [first, second])
    expect(segments.filter((segment) => segment.mark).map((segment) => segment.text)).toEqual(["Priset är 50", "Priset är 80"])
  })
  it("finds a repeated phrase after the text that precedes the selection", () => {
    const text = "Villkor. Priset är 50. Övrigt. Priset är 80."
    expect(textOccurrenceIndex(text, "Priset är", null)).toBe(text.indexOf("Priset är"))
    expect(textOccurrenceIndex(text, "Priset är", "Övrigt.")).toBe(text.lastIndexOf("Priset är"))
  })
})

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
