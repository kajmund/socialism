import { describe, expect, it } from "vitest"
import { PASSAGE_MARK_COLOR, USER_MARK_COLOR, commentAuthorColor, markColor, sharedAuthorColor } from "@/components/underlag/documentMarkColor"

describe("document mark colors", () => {
  it("keeps the reader's mark gold and gives each expert a stable color", () => {
    expect(markColor("user", "erik")).toBe(USER_MARK_COLOR)
    expect(markColor(undefined, null)).toBe(USER_MARK_COLOR)
    expect(markColor("expert", "karin")).toEqual(markColor("expert", "karin"))
    expect(markColor("expert", "karin")).not.toEqual(markColor("user", "erik"))
    expect(markColor("passage", null).fill).not.toBe(USER_MARK_COLOR.fill)
  })
  it("keeps one expert's comments in that expert's color when the passage was marked by someone else", () => {
    const frank = { author_kind: "expert", author_id: null, expert_id: "cm1f36" }
    const sara = { author_kind: "expert", author_id: null, expert_id: "co64e6" }
    expect(commentAuthorColor(frank)).toBe(markColor("expert", "cm1f36"))
    expect(sharedAuthorColor([frank, frank], markColor("expert", "co64e6"))).toBe(commentAuthorColor(frank))
    expect(sharedAuthorColor([sara, frank], PASSAGE_MARK_COLOR)).toBe(PASSAGE_MARK_COLOR)
  })
})
