import { describe, expect, it } from "vitest"
import {
  activeDocumentQuery,
  documentMentionChoices,
  insertDocumentMention,
  resolveDocumentMentions,
} from "./documentMentions"

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

describe("document mention completion", () => {
  it("reads the query after an @ that starts a token", () => {
    expect(activeDocumentQuery("Visa @Ra", "Visa @Ra".length)).toEqual({ start: 5, query: "Ra" })
    expect(activeDocumentQuery("mail@domän.se", "mail@domän.se".length)).toBeNull()
  })

  it("offers unique filenames and prefers a prefix match", () => {
    expect(documentMentionChoices(files, "ram").map((file) => file.filename)).toEqual([
      "Ramavtal 2026.pdf",
      "Ramavtal.pdf",
    ])
    expect(documentMentionChoices(files, "").map((file) => file.id)).not.toContain("copy-a")
  })

  it("inserts the full filename so the mention resolves", () => {
    const next = insertDocumentMention("Visa @Ra", "Visa @Ra".length, "Ramavtal.pdf")
    expect(next).toEqual({ text: "Visa @Ramavtal.pdf ", caret: "Visa @Ramavtal.pdf ".length })
    expect(resolveDocumentMentions(next?.text ?? "", files)).toEqual([
      { display_name: "Ramavtal.pdf", source_object_id: "abc-123" },
    ])
  })
})
