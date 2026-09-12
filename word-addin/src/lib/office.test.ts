import { describe, expect, it } from "vitest"

import { listStringFromLoaded, paragraphStatesFromSnapshot } from "./office"

describe("listStringFromLoaded", () => {
  it("returns an empty string when the paragraph is not in a list", () => {
    expect(
      listStringFromLoaded({
        listItemOrNullObject: { isNullObject: true, listString: "1." },
      }),
    ).toBe("")
  })

  it("returns Word's rendered list label when present", () => {
    expect(
      listStringFromLoaded({
        listItemOrNullObject: { isNullObject: false, listString: "2.1." },
      }),
    ).toBe("2.1.")
  })
})

describe("paragraphStatesFromSnapshot", () => {
  it("keeps captured unique_local_id for resolver input", () => {
    expect(
      paragraphStatesFromSnapshot([
        {
          index: 1,
          text: "Första stycket.",
          style: "Normal",
          list_string: "",
          unique_local_id: "p-1",
        },
      ]),
    ).toEqual([
      { paragraph_index: 1, text: "Första stycket.", unique_local_id: "p-1" },
    ])
  })
})
