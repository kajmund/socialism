import { describe, expect, it } from "vitest"
import { isDocxSource, isPdfSource } from "./sourceKind"

describe("sourceKind", () => {
  it("recognizes PDF by type or name", () => {
    expect(isPdfSource({ content_type: "application/pdf", filename: "a.bin" })).toBe(true)
    expect(isPdfSource({ content_type: "application/octet-stream", filename: "avtal.pdf" })).toBe(true)
    expect(isPdfSource({ content_type: "text/plain", filename: "a.txt" })).toBe(false)
  })

  it("recognizes Word by type or name", () => {
    expect(isDocxSource({
      content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      filename: "avtal.bin",
    })).toBe(true)
    expect(isDocxSource({ content_type: "application/octet-stream", filename: "avtal.docx" })).toBe(true)
    expect(isDocxSource({ content_type: "application/pdf", filename: "avtal.pdf" })).toBe(false)
  })
})
