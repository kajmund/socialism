import { describe, expect, it } from "vitest"
import { linkWorkspaceCitations } from "./workspaceCitations"

describe("workspace answer citations", () => {
  it("links a document reference to its frozen version and TextUnit", () => {
    expect(linkWorkspaceCitations("Sex månader [E1].", "chat-a", [{ label: "E1", source_object_id: "avtal", document_version_id: "version-1", text_unit_id: "unit-1", excerpt: "Sex månader" }])).toBe("Sex månader [E1](/workspace-chats/chat-a/sources/avtal?document_version_id=version-1&text_unit_id=unit-1).")
  })
  it("links global sources without making an unsafe URL clickable", () => {
    expect(linkWorkspaceCitations("[E1] [E2]", "chat", [{ label: "E1", excerpt: "", source_url: "https://lagen.nu/2020:1" }, { label: "E2", excerpt: "", source_url: "javascript:alert(1)" }])).toBe("[E1](https://lagen.nu/2020:1) [E2]")
  })
  it("preserves existing links and unknown evidence labels", () => {
    expect(linkWorkspaceCitations("[E1](https://example.com) [E99]", "chat", [{ label: "E1", excerpt: "", source_url: "https://lagen.nu" }])).toBe("[E1](https://example.com) [E99]")
  })
})
