import { describe, expect, it } from "vitest"
import { pdfSelectionText } from "./pdfSelectionText"

describe("PDF selection text", () => {
  it("uses visible reading order when PDF drawing order differs", () => {
    const fragments = [
      { text: "Footer", x: 10, y: 200, width: 30 },
      { text: "Date:", x: 100, y: 10, width: 25 },
      { text: "Receipt", x: 10, y: 10, width: 35 },
      { text: "2026-06-02", x: 135, y: 10, width: 60 },
      { text: "Period:", x: 100, y: 30, width: 30 },
      { text: "2026-06-01 – 2026-06-30", x: 140, y: 30, width: 120 },
    ]
    expect(pdfSelectionText(fragments)).toBe("Receipt Date: 2026-06-02 Period: 2026-06-01 – 2026-06-30 Footer")
    expect(fragments[0].text).toBe("Footer")
  })
  it("restores word spaces between separated text spans without splitting adjacent word pieces", () => {
    expect(pdfSelectionText([
      { text: "Park", x: 10, y: 10, width: 20 },
      { text: "ing", x: 30, y: 10, width: 10 },
      { text: "receipt", x: 50, y: 11, width: 30 },
    ])).toBe("Parking receipt")
  })
  it("preserves selected partial words, numbers and punctuation exactly", () => {
    expect(pdfSelectionText([
      { text: "arking", x: 15, y: 10, width: 30 },
      { text: "96,00 SEK (25%)", x: 60, y: 10, width: 80 },
    ])).toBe("arking 96,00 SEK (25%)")
    expect(pdfSelectionText([])).toBe("")
  })
})
