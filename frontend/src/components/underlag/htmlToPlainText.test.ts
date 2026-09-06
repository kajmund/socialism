import { describe, expect, it } from "vitest"
import { htmlToPlainText } from "./htmlToPlainText"

describe("htmlToPlainText", () => {
  it("strips tags and collapses blank lines", () => {
    expect(htmlToPlainText("<p>Hej</p><p>värld</p>\n\n\n")).toBe("Hej\nvärld")
  })

  it("drops script bodies", () => {
    expect(htmlToPlainText("<p>ok</p><script>alert(1)</script>")).toBe("ok")
  })
})
