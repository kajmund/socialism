import { describe, expect, it } from "vitest"
import { passageCommentKey } from "./passageCommentKey"

const anchor = {
  anchor_type: "text" as const,
  page_number: 1,
  locator: "page:1",
  exact_text: "Säljare",
  prefix_text: null,
  suffix_text: null,
  asset_id: null,
  rects: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.04 }],
}

describe("passage comment key", () => {
  it("matches the key the server stores for the same passage", () => {
    expect(passageCommentKey("pdf", anchor)).toBe('["pdf",1,[[100000,200000,300000,40000]]]')
    expect(passageCommentKey("pdf", { ...anchor, page_number: null, rects: [] })).toBe('["pdf",null,["","Säljare"]]')
  })
})
