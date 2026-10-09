import { describe, expect, it } from "vitest"
import { resolveDocumentMentions } from "./documentMentions"

const files = [
  { id: "abc-123", filename: "Ramavtal.pdf" },
  { id: "other", filename: "Bilaga.pdf" },
  { id: "copy-a", filename: "Kopia.pdf" },
  { id: "copy-b", filename: "Kopia.pdf" },
  { id: "spaced", filename: "Ramavtal 2026.pdf" },
]

describe("resolveDocumentMentions", () => {
  it("resolves an exact filename to the canonical source id", () => {
    expect(resolveDocumentMentions("Visa klausulen i @Ramavtal.pdf.", files)).toEqual([
      { display_name: "Ramavtal.pdf", source_object_id: "abc-123" },
    ])
  })

  it("does not fuzzy-match a partial name or an ambiguous filename", () => {
    expect(resolveDocumentMentions("Öppna @Ramavtal och @Kopia.pdf", files)).toEqual([])
  })

  it("resolves exact filenames containing spaces", () => {
    expect(resolveDocumentMentions("Läs @Ramavtal 2026.pdf noggrant", files)).toEqual([
      { display_name: "Ramavtal 2026.pdf", source_object_id: "spaced" },
    ])
  })
})
