import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { Workspace } from "@/api/voiceWorkspaces"
import { LocaleProvider } from "@/i18n"
import { OpenDocumentsCatalog } from "./OpenDocumentsButton"

const workspace = {
  id: "voice", workspace_id: "parent", chat_id: "chat", customer_id: 1, title: "Arbetsyta", module: "dd", revision: 1,
  state: { language: "sv", knowledge_scope: "workspace", view: "documents", documents: [], split_source_ids: [], research_attempt_ids: [] },
  sources: [{ id: "avtal", kind: "underlag", filename: "Avtal_22.pdf", content_type: "application/pdf", size_bytes: 2048, module: "dd", owner_user_id: "user", folder_id: null, extraction_status: "ok", knowledge_status: "ready", created_at: "2026-10-10T00:00:00Z" }],
  artifacts: [
    { id: "points", title: "Förhandlingspunkter", kind: "document", revision: 2, status: "ready", job_id: null, error: null, created_at: "2026-10-11T00:00:00Z", content: { blocks: [{ id: "rent", type: "paragraph", text: "8 600 kr i månaden", source_refs: [] }] } },
    { id: "links", title: "Testrelation", kind: "relations", revision: 1, status: "ready", job_id: null, error: null, created_at: "2026-10-09T00:00:00Z", content: { nodes: [], edges: [] } },
  ],
  references: [], research: [],
} as Workspace

describe("OpenDocumentsCatalog", () => {
  it("shows sources and artifacts in one table with name, type and created date", () => {
    const html = renderToStaticMarkup(<LocaleProvider><OpenDocumentsCatalog
      workspace={workspace}
      onOpenSource={() => undefined}
      onOpenArtifact={() => undefined}
    /></LocaleProvider>)
    expect(html).toContain("<table")
    expect(html).toContain("Namn")
    expect(html).toContain("Typ")
    expect(html).toContain("Skapad")
    expect(html).toContain("Avtal_22.pdf")
    expect(html).toContain("Förhandlingspunkter")
    expect(html).toContain("Testrelation")
    expect(html).toContain("Underlag")
    expect(html).toContain("Dokument")
    expect(html).toContain("Relationer")
    expect(html).not.toContain("application/pdf")
    expect(html).not.toContain("8 600 kr i månaden")
    expect(html.indexOf("Förhandlingspunkter")).toBeLessThan(html.indexOf("Avtal_22.pdf"))
    expect(html.indexOf("Avtal_22.pdf")).toBeLessThan(html.indexOf("Testrelation"))
  })
})
