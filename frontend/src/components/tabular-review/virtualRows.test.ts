import { describe, expect, it } from "vitest"
import { visibleRowWindow } from "./virtualRows"

describe("visibleRowWindow", () => {
  it("windows hundreds of rows", () => {
    const window = visibleRowWindow(720, 360, 240, 72, 2)
    expect(window.start).toBe(8)
    expect(window.end).toBeLessThan(240)
    expect(window.end - window.start).toBeLessThan(20)
  })
})
