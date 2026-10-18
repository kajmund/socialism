import { describe, expect, it } from "vitest"
import { markerOutsideViewport, pageAtViewportTop } from "./pdfPageScroll"

const pages = [
  { page: 1, top: 0, bottom: 400 },
  { page: 2, top: 416, bottom: 816 },
  { page: 3, top: 832, bottom: 1232 },
]

describe("page at the viewport top", () => {
  it("keeps the page that still crosses the top edge", () => {
    expect(pageAtViewportTop(pages, 0)).toBe(1)
    expect(pageAtViewportTop(pages, 390)).toBe(1)
    expect(pageAtViewportTop(pages, 410)).toBe(2)
  })

  it("uses the last page once the rest have passed", () => {
    expect(pageAtViewportTop(pages, 2000)).toBe(3)
    expect(pageAtViewportTop([], 0)).toBeNull()
  })
})

describe("marker outside the viewport", () => {
  const viewport = { top: 200, bottom: 700 }

  it("leaves a mark the reader is already looking at", () => {
    expect(markerOutsideViewport({ top: 240, bottom: 260 }, viewport)).toBe(false)
    expect(markerOutsideViewport({ top: 210, bottom: 230 }, viewport)).toBe(false)
  })

  it("asks to reveal a mark above or below the page", () => {
    expect(markerOutsideViewport({ top: 40, bottom: 60 }, viewport)).toBe(true)
    expect(markerOutsideViewport({ top: 740, bottom: 760 }, viewport)).toBe(true)
  })
})
