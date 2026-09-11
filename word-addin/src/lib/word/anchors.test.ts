import { describe, expect, it } from "vitest"

import {
  hashWordText,
  normalizeWordText,
  resolveWordAnchor,
  type WordAnchor,
  type WordDocumentParagraphState,
} from "./anchors"

function doc(
  ...rows: Array<[number, string] | [number, string, string]>
): WordDocumentParagraphState[] {
  return rows.map((row) =>
    row.length === 3
      ? { paragraph_index: row[0], text: row[1], unique_local_id: row[2] }
      : { paragraph_index: row[0], text: row[1] },
  )
}

function anchor(overrides: Partial<WordAnchor> = {}): WordAnchor {
  return {
    paragraph_index: 1,
    reviewed_text: "Första stycket.",
    text_hash: hashWordText("Första stycket."),
    previous_text_hash: hashWordText("Inledning"),
    next_text_hash: hashWordText("Samma text."),
    unique_local_id: "p-1",
    ...overrides,
  }
}

describe("hashWordText", () => {
  it("matches SHA-256 of normalized UTF-8", () => {
    expect(hashWordText("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    )
    expect(hashWordText("  Hej\r\n ")).toBe(hashWordText("Hej"))
    expect(normalizeWordText("  Hej\r\n ")).toBe("Hej")
  })
})

describe("resolveWordAnchor", () => {
  it("resolves an unchanged paragraph at the original index", () => {
    expect(resolveWordAnchor(anchor(), doc([0, "Inledning"], [1, "Första stycket."]))).toEqual({
      status: "resolved",
      paragraph_index: 1,
    })
  })

  it("resolves a moved unchanged paragraph by unique text", () => {
    expect(
      resolveWordAnchor(
        anchor({ unique_local_id: null }),
        doc([0, "Ny ingress"], [1, "Inledning"], [2, "Första stycket."]),
      ),
    ).toEqual({ status: "resolved", paragraph_index: 2 })
  })

  it("resolves when a valid local id still has the captured text", () => {
    expect(
      resolveWordAnchor(anchor(), doc([4, "Första stycket.", "p-1"], [5, "Annat."])),
    ).toEqual({ status: "resolved", paragraph_index: 4 })
  })

  it("returns stale when a valid local id has different text", () => {
    expect(
      resolveWordAnchor(anchor(), doc([1, "Ändrad text.", "p-1"], [2, "Första stycket."])),
    ).toEqual({ status: "stale" })
  })

  it("resolves after restart when exact captured text is unique", () => {
    expect(
      resolveWordAnchor(
        anchor({ unique_local_id: null }),
        doc([0, "Ny ingress"], [1, "Inledning"], [2, "Första stycket."]),
      ),
    ).toEqual({ status: "resolved", paragraph_index: 2 })
  })

  it("resolves duplicate text when previous/next context is unique", () => {
    const same = hashWordText("Samma text.")
    expect(
      resolveWordAnchor(
        {
          paragraph_index: 99,
          reviewed_text: "Samma text.",
          text_hash: same,
          previous_text_hash: hashWordText("Första stycket."),
          next_text_hash: same,
        },
        doc(
          [0, "Inledning"],
          [1, "Första stycket."],
          [2, "Samma text."],
          [3, "Samma text."],
          [4, "Sista stycket."],
        ),
      ),
    ).toEqual({ status: "resolved", paragraph_index: 2 })
  })

  it("does not pick duplicate text that now occupies the old index", () => {
    expect(
      resolveWordAnchor(
        {
          paragraph_index: 2,
          reviewed_text: "Samma text.",
          text_hash: hashWordText("Samma text."),
          previous_text_hash: hashWordText("Alpha"),
          next_text_hash: hashWordText("Beta"),
          word_session_id: "session-a",
        },
        doc(
          [0, "Avtal"],
          [1, "Ingress"],
          [2, "Samma text."],
          [3, "Zeta"],
          [9, "Alpha"],
          [10, "Samma text."],
          [11, "Beta"],
        ),
        "session-b",
      ),
    ).toEqual({ status: "resolved", paragraph_index: 10 })
  })

  it("returns ambiguous when duplicate context cannot decide", () => {
    expect(
      resolveWordAnchor(
        {
          paragraph_index: 99,
          reviewed_text: "Samma text.",
          text_hash: hashWordText("Samma text."),
          previous_text_hash: hashWordText("okänd"),
          next_text_hash: hashWordText("okänd"),
        },
        doc([0, "Samma text."], [1, "Samma text."]),
      ),
    ).toEqual({ status: "ambiguous" })
  })

  it("returns missing when the captured text is gone", () => {
    expect(resolveWordAnchor(anchor({ unique_local_id: null }), doc([0, "Inledning"], [1, "Kvar."]))).toEqual({
      status: "missing",
    })
  })

  it("ignores recycled local ids after a Word session change", () => {
    expect(
      resolveWordAnchor(
        anchor({ word_session_id: "session-a" }),
        doc([0, "Ny ingress"], [1, "Ändrad text.", "p-1"], [2, "Första stycket."]),
        "session-b",
      ),
    ).toEqual({ status: "resolved", paragraph_index: 2 })
  })

  it("keeps stale when the same session still owns the local id", () => {
    expect(
      resolveWordAnchor(
        anchor({ word_session_id: "session-a" }),
        doc([1, "Ändrad text.", "p-1"], [2, "Första stycket."]),
        "session-a",
      ),
    ).toEqual({ status: "stale" })
  })

  it("never falls back to a mismatched original index", () => {
    expect(
      resolveWordAnchor(
        anchor({ unique_local_id: null, previous_text_hash: null, next_text_hash: null }),
        doc([1, "Helt annan text."]),
      ),
    ).toEqual({ status: "missing" })
  })
})
