import { describe, expect, it } from "vitest"
import { pdfSelectionGesture } from "./pdfSelectionGesture"

const click = { button: 0, started: true, moved: false, clickCount: 1, shiftKey: false }

describe("PDF selection gesture", () => {
  it("clears only an ordinary primary click started inside the PDF", () => {
    expect(pdfSelectionGesture(click)).toBe("clear")
    expect(pdfSelectionGesture({ ...click, started: false })).toBe("ignore")
    expect(pdfSelectionGesture({ ...click, button: 2 })).toBe("ignore")
    expect(pdfSelectionGesture({ ...click, button: 1 })).toBe("ignore")
  })
  it("preserves a drag, word selection and shift-extended selection", () => {
    expect(pdfSelectionGesture({ ...click, moved: true })).toBe("select")
    expect(pdfSelectionGesture({ ...click, clickCount: 2 })).toBe("select")
    expect(pdfSelectionGesture({ ...click, shiftKey: true })).toBe("select")
  })
})
