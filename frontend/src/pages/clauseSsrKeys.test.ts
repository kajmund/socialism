import { describe, expect, it } from "vitest"
import { isTypingTarget, keyToQueueAction } from "./clauseSsrKeys"

describe("clauseSsrKeys", () => {
  it("maps ja/nej and navigation keys", () => {
    expect(keyToQueueAction("j")).toBe("yes")
    expect(keyToQueueAction("N")).toBe("no")
    expect(keyToQueueAction("s")).toBe("skip")
    expect(keyToQueueAction("ArrowRight")).toBe("skip")
    expect(keyToQueueAction("u")).toBe("unsure")
    expect(keyToQueueAction("ArrowLeft")).toBe("prev")
    expect(keyToQueueAction("z")).toBe("undo")
    expect(keyToQueueAction("x")).toBeNull()
  })

  it("ignores typing targets", () => {
    expect(isTypingTarget({ tagName: "INPUT" } as unknown as EventTarget)).toBe(true)
    expect(isTypingTarget({ tagName: "DIV" } as unknown as EventTarget)).toBe(false)
    expect(isTypingTarget(null)).toBe(false)
  })
})
