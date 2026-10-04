import { describe, expect, it } from "vitest"
import type { SourceReference, WorkspaceState } from "@/api/voiceWorkspaces"
import { captureDocumentTurn, clearLocalDocumentSelection, localSelectionMatchesReference, withLocalDocumentSelection, type LocalDocumentSelection } from "./workspaceLocalSelection"
import type { WorkspaceTurnSnapshot } from "./workspaceTurnSnapshot"

const anchor = { anchor_type: "text" as const, page_number: 1, locator: "page:1", exact_text: "Synthetic passage A",
  rects: [{ x: .1, y: .2, width: .3, height: .04 }], prefix_text: null, suffix_text: null, asset_id: null }
const local = (): LocalDocumentSelection => ({ sourceId: "pdf", selection: { source_id: "pdf", source_version: "version-a", source_file_sha256: "c".repeat(64), anchor: structuredClone(anchor) } })
const state = (): WorkspaceState => ({ language: "sv", knowledge_scope: "workspace", view: "documents", expert_id: "expert", documents: [
  { source_id: "pdf", page: 1, zoom: 1, reference_id: "old-reference" }, { source_id: "other", page: 2, zoom: .8, reference_id: "other-reference" },
], split_source_ids: ["pdf", "other"], research_attempt_ids: [], selection: { reference_id: "old-reference" } })
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const reference = (): SourceReference => ({ reference_id: "verified", number: 1, source_kind: "underlag", source_id: "pdf", source_version: "version-a", title: "Synthetic", excerpt: anchor.exact_text, anchor: structuredClone(anchor), stale: false })

describe("local document selection", () => {
  it("overlays a captured question without modifying persisted navigation or another pane", () => {
    const stored = state(), before = structuredClone(stored), selected = local()
    const question = withLocalDocumentSelection(stored, selected)
    expect(question.selection).toEqual(selected.selection)
    expect(question.documents[0]).toEqual({ ...stored.documents[0], reference_id: null })
    expect(question.documents[1]).toBe(stored.documents[1])
    expect(stored).toEqual(before)
  })
  it("keeps the local selection across changed view, zoom, page and refreshed old references", () => {
    const selected = local()
    for (const view of ["documents", "evidence", "relations"] as const) {
      const refreshed = { ...state(), view, documents: [{ source_id: "pdf", page: 3, zoom: 1.8, reference_id: "old-server-reference" }] }
      const question = withLocalDocumentSelection(refreshed, selected)
      expect(question.selection?.anchor).toEqual(anchor)
      expect(question.documents[0]).toMatchObject({ page: 3, zoom: 1.8, reference_id: null })
      expect(question.view).toBe(view)
    }
  })
  it("keeps an explicit clear instead of restoring a saved reference", async () => {
    const clear = { sourceId: "pdf", selection: null }
    const question = await captureDocumentTurn(Promise.resolve({ workspaceId: "canvas", revision: 4, state: state() }), clear)
    expect(question?.state.selection).toBeNull()
    expect(question?.state.documents[0].reference_id).toBeNull()
    expect(question?.state.documents[1].reference_id).toBe("other-reference")
    expect(withLocalDocumentSelection(state(), clear).selection).toBeNull()
  })
  it("clears another pane's old reference without dropping the active manual selection", () => {
    const stored = state(), selected = local()
    const cleared = clearLocalDocumentSelection(stored, [], selected, "other")
    expect(cleared.selection).toEqual(selected.selection)
    expect(cleared.sourceId).toBe("pdf")
    expect(cleared.clearedSourceIds).toEqual(["other"])
    expect(withLocalDocumentSelection(stored, cleared).documents.map((row) => row.reference_id)).toEqual([null, null])
    expect(stored.documents[1].reference_id).toBe("other-reference")
  })
  it("clears an old document highlight while retaining another pane's selected citation", () => {
    const stored = state()
    stored.selection = { reference_id: "other-reference" }
    const other = { ...reference(), reference_id: "other-reference", source_id: "other" }
    const cleared = clearLocalDocumentSelection(stored, [other], null, "pdf")
    expect(withLocalDocumentSelection(stored, cleared).selection).toEqual(stored.selection)
    expect(cleared.sourceId).toBe("pdf")
    expect(cleared.selection).toEqual({ reference_id: "other-reference" })
  })
  it("locks A immediately while its navigation commit waits and B is selected later", async () => {
    const commit = deferred<WorkspaceTurnSnapshot | null>(), selected = local()
    const capturedA = captureDocumentTurn(commit.promise, selected)
    selected.selection!.anchor!.exact_text = "Later passage B"
    selected.selection!.source_version = "version-b"
    selected.selection!.source_file_sha256 = "d".repeat(64)
    selected.selection!.anchor!.rects[0].x = .7
    commit.resolve({ workspaceId: "canvas", revision: 8, state: { ...state(), view: "evidence" } })
    const question = await capturedA
    expect(question?.revision).toBe(8)
    expect(question?.workspaceId).toBe("canvas")
    expect(question?.state.view).toBe("evidence")
    expect(question?.state.selection).toMatchObject({ source_version: "version-a", source_file_sha256: "c".repeat(64), anchor: { exact_text: anchor.exact_text, rects: anchor.rects } })
  })
  it("deeply isolates both the persisted commit and local selection", async () => {
    const stored = state(), selected = local()
    const question = await captureDocumentTurn(Promise.resolve({ workspaceId: "canvas", revision: 2, state: stored }), selected)
    question!.state.documents[1].zoom = 2
    question!.state.selection!.anchor!.rects[0].x = .9
    expect(stored.documents[1].zoom).toBe(.8)
    expect(selected.selection!.anchor!.rects[0].x).toBe(.1)
  })
  it("preserves a failed navigation commit instead of sending local A with another state", async () => {
    const commit = deferred<WorkspaceTurnSnapshot | null>(), failure = new Error("workspace_revision_conflict")
    const question = captureDocumentTurn(commit.promise, local())
    commit.reject(failure)
    await expect(question).rejects.toBe(failure)
  })
  it("preserves server selections when there is no local overlay", async () => {
    const stored = state()
    expect(withLocalDocumentSelection(stored, null)).toBe(stored)
    expect(await captureDocumentTurn(Promise.resolve({ workspaceId: "canvas", revision: 1, state: stored }), null)).toEqual({ workspaceId: "canvas", revision: 1, state: stored })
    expect(await captureDocumentTurn(Promise.resolve(null), local())).toBeNull()
  })
})

describe("reference presentation while a local selection remains", () => {
  it("acknowledges the same version, original quote and geometry", () => {
    const verified = reference()
    verified.anchor!.exact_text = "synthetic\npassage A"
    expect(localSelectionMatchesReference(local(), verified)).toBe(true)
  })
  it("does not acknowledge a different reference position, source, version or text", () => {
    for (const changed of [
      { ...reference(), source_id: "other" }, { ...reference(), source_version: "other-version" },
      { ...reference(), anchor: { ...anchor, page_number: 2 } }, { ...reference(), anchor: { ...anchor, exact_text: "Synthetic passage B" } },
      { ...reference(), anchor: { ...anchor, exact_text: "Synthetic passage A." } },
      { ...reference(), anchor: { ...anchor, rects: [{ ...anchor.rects[0], x: .4 }] } },
    ]) expect(localSelectionMatchesReference(local(), changed)).toBe(false)
    expect(localSelectionMatchesReference({ sourceId: "pdf", selection: null }, reference())).toBe(false)
  })
})
