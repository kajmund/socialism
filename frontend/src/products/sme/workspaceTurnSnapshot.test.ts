import process from "node:process"
import { setImmediate } from "node:timers"
import { describe, expect, it } from "vitest"
import { captureWorkspaceTurn, type WorkspaceTurnSnapshot } from "./workspaceTurnSnapshot"

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function verified(revision: number, reference: string, quote = "foobar"): WorkspaceTurnSnapshot {
  return {
    revision,
    state: {
      language: "sv", knowledge_scope: "workspace", view: "documents", expert_id: "expert",
      documents: [{ source_id: "synthetic-pdf", page: 1, zoom: 1, reference_id: reference }],
      split_source_ids: [], research_attempt_ids: [],
      selection: {
        source_id: "synthetic-pdf", reference_id: reference,
        anchor: {
          anchor_type: "text", page_number: 1, locator: "page:1", exact_text: quote,
          rects: [{ x: .1, y: .2, width: .3, height: .04 }],
          prefix_text: null, suffix_text: null, asset_id: null,
        },
      },
    },
  }
}

describe("captureWorkspaceTurn", () => {
  it("waits for the commit and returns its canonical server anchor and revision", async () => {
    const save = deferred<WorkspaceTurnSnapshot>()
    const server = verified(8, "verified-a")
    const captured = captureWorkspaceTurn(save.promise)
    let settled = false
    const observed = captured.then((value) => { settled = true; return value })

    await Promise.resolve()
    expect(settled).toBe(false)
    save.resolve(server)

    expect(await observed).toEqual(server)
    expect((await captured).state.selection).toMatchObject({
      reference_id: "verified-a", anchor: { exact_text: "foobar", locator: "page:1" },
    })
    expect((await captured).revision).toBe(8)
  })

  it("keeps turn A bound to commit A when a later queued B resolves first", async () => {
    const saveA = deferred<WorkspaceTurnSnapshot>(), saveB = deferred<WorkspaceTurnSnapshot>()
    let currentCommit = saveA.promise
    const turnA = captureWorkspaceTurn(currentCommit)
    currentCommit = saveB.promise
    const turnB = captureWorkspaceTurn(currentCommit)
    let aSettled = false
    const observedA = turnA.then((value) => { aSettled = true; return value })

    saveB.resolve(verified(10, "verified-b", "Later selection B"))
    expect((await turnB).state.selection?.reference_id).toBe("verified-b")
    expect(aSettled).toBe(false)
    saveA.resolve(verified(9, "verified-a", "Selection A"))

    expect(await observedA).toEqual(verified(9, "verified-a", "Selection A"))
    expect((await turnB).revision).toBe(10)
  })

  it("clones nested server state so later changes cannot rewrite the captured context", async () => {
    const server = verified(11, "verified-a")
    const before = structuredClone(server)
    const captured = await captureWorkspaceTurn(Promise.resolve(server))

    server.state.documents[0].zoom = 2
    server.state.selection!.reference_id = "verified-b"
    server.state.selection!.anchor!.rects[0].x = .7
    expect(captured).toEqual(before)

    captured.state.documents[0].page = 2
    captured.state.selection!.anchor!.exact_text = "Changed local copy"
    expect(server.state.documents[0].page).toBe(1)
    expect(server.state.selection!.anchor!.exact_text).toBe("foobar")
  })

  it("also clones an already committed snapshot", async () => {
    const committed = verified(12, "verified-current")
    const captured = await captureWorkspaceTurn(committed)

    expect(captured).toEqual(committed)
    expect(captured.state).not.toBe(committed.state)
    expect(captured.state.selection?.anchor?.rects).not.toBe(committed.state.selection?.anchor?.rects)
  })

  it("observes an unwaited rejection but preserves the original error without using a later commit", async () => {
    const saveA = deferred<WorkspaceTurnSnapshot>()
    const turnA = captureWorkspaceTurn(saveA.promise)
    const failure = new Error("selection_anchor_stale")
    const unhandled: unknown[] = []
    const onUnhandled = (reason: unknown) => { unhandled.push(reason) }
    process.on("unhandledRejection", onUnhandled)
    try {
      saveA.reject(failure)
      await new Promise<void>((resolve) => { setImmediate(resolve) })
      expect(unhandled).toEqual([])

      const later = await captureWorkspaceTurn(verified(13, "verified-b"))
      expect(later.state.selection?.reference_id).toBe("verified-b")
      await expect(turnA).rejects.toBe(failure)
      await expect(saveA.promise).rejects.toBe(failure)
    } finally {
      process.off("unhandledRejection", onUnhandled)
    }
  })
})
