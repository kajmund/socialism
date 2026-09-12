import { describe, expect, it } from "vitest"

import { wordActionKind } from "./executeWordAction"

describe("wordActionKind", () => {
  it("dispatches comment and replace", () => {
    expect(wordActionKind("comment")).toBe("comment")
    expect(wordActionKind("replace")).toBe("replace")
  })

  it("fails closed on unknown action types", () => {
    expect(wordActionKind("insert")).toBe("unsupported")
    expect(wordActionKind("delete")).toBe("unsupported")
    expect(wordActionKind("")).toBe("unsupported")
  })
})
