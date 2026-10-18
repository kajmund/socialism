import { describe, expect, it } from "vitest"
import type { PassageComment } from "@/api/voiceWorkspaces"
import { commentThreads, marksForComments, mergePassageComments, shownCommentThreads, stackCommentCards } from "./documentCommentLayout"
import type { DocumentMark } from "./workspaceDocumentFocus"

const anchor = {
  anchor_type: "text" as const, page_number: 1, locator: "page:1", exact_text: "Säljare",
  prefix_text: null, suffix_text: null, asset_id: null, rects: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.04 }],
}
const mark: DocumentMark = { anchor, authorKind: "expert", authorId: "alfons", authorName: "Alfons", passageKey: "expert-passage" }

function comment(id: string, key = "expert-passage", updated = "2026-10-11T20:00:00+00:00"): PassageComment {
  return { id, source_id: "pdf", passage_key: key, anchor, author_id: "user", author_kind: "user", author_name: "Erik Fremred", body: id, created_at: updated, updated_at: updated }
}

describe("comment layout", () => {
  it("keeps a saved comment's mark when the draft is gone", () => {
    const saved = comment("one", "kept")
    const marks = marksForComments([mark], [saved], "pdf")
    expect(marks.map((row) => row.passageKey)).toEqual(["expert-passage", "kept"])
    expect(marksForComments([mark], [comment("one")], "pdf")).toEqual([mark])
    const expertComment = { ...comment("expert", "kept"), author_id: null, author_kind: "expert" as const, expert_id: "karin", author_name: "Karin" }
    expect(marksForComments([], [expertComment], "pdf")[0]).toMatchObject({ authorKind: "expert", authorId: "karin", authorName: "Karin" })
  })

  it("puts both experts' comments on one passage card", () => {
    const karin = { ...mark, authorId: "karin", authorName: "Karin" }
    const threads = commentThreads([mark, karin], [comment("one"), { ...comment("two"), author_id: null, author_kind: "expert", expert_id: "karin" }], "pdf")
    expect(threads.map((thread) => thread.key)).toEqual(["expert-passage"])
    expect(threads[0].comments.map((row) => row.id)).toEqual(["one", "two"])
  })

  it("shows a card for a comment and for the passage being written", () => {
    const draft: DocumentMark = { ...mark, authorKind: "user", passageKey: "draft" }
    const threads = commentThreads([mark, draft], [comment("one")], "pdf")
    expect(shownCommentThreads(threads, null).map((thread) => thread.key)).toEqual(["expert-passage"])
    expect(shownCommentThreads(threads, "draft").map((thread) => thread.key)).toEqual(["expert-passage", "draft"])
  })

  it("pushes a lower card down so the balloons do not overlap", () => {
    const placed = stackCommentCards([
      { key: "b", anchorTop: 40, height: 80 },
      { key: "a", anchorTop: 30, height: 50 },
    ])
    expect(placed).toEqual([{ key: "a", top: 30 }, { key: "b", top: 90 }])
  })

  it("keeps a comment that was just saved when an older workspace snapshot arrives", () => {
    const guard = { saved: new Set(["new"]), removed: new Set(["gone"]) }
    const merged = mergePassageComments(
      [comment("old", "a", "2026-10-11T19:00:00+00:00"), comment("gone")],
      [comment("old", "a", "2026-10-11T21:00:00+00:00"), comment("new"), comment("gone")],
      guard,
    )
    expect(merged.map((row) => [row.id, row.updated_at])).toEqual([
      ["old", "2026-10-11T21:00:00+00:00"],
      ["new", "2026-10-11T20:00:00+00:00"],
    ])
  })
})
