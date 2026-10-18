import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { Workspace } from "@/api/voiceWorkspaces"
import { LocaleProvider } from "@/i18n"
import { WorkspaceCanvas } from "./WorkspaceCanvas"

vi.mock("@/lib/api", () => ({ api: {}, ApiError: class ApiError extends Error {} }))
vi.mock("@/api/voiceWorkspaces", () => ({ voiceWorkspaces: {} }))
vi.mock("./WorkspaceSourcePane", () => ({ WorkspaceSourcePane: () => <div data-source-pane="true" /> }))
vi.mock("./ModelTraceButton", () => ({
  ModelTraceButton: () => <button type="button" aria-label="Modellens arbete" />,
}))

const workspace = {
  id: "voice", workspace_id: "parent", chat_id: "chat", customer_id: 1, title: "Arbetsyta", module: "dd", revision: 1,
  state: {
    language: "sv", knowledge_scope: "workspace", view: "documents",
    documents: [{ source_id: "avtal", page: 1, zoom: 1 }],
    split_source_ids: [], active_artifact_id: "points", open_artifact_ids: ["points", "diff"], selection: null, research_attempt_ids: [],
  },
  sources: [{ id: "avtal", kind: "underlag", filename: "Avtal_22.pdf", content_type: "application/pdf", size_bytes: 1, module: "dd", owner_user_id: "user", folder_id: null, extraction_status: "ok", knowledge_status: "ready", created_at: "2026-10-11T00:00:00Z" }],
  artifacts: [
    {
      id: "points", title: "Förhandlingspunkter", kind: "document", revision: 1, status: "ready", job_id: null, error: null,
      content: { blocks: [{ id: "rent", type: "paragraph", text: "8 600 kr i månaden", source_refs: [] }] },
    },
    { id: "diff", title: "Skillnader", kind: "comparison", revision: 1, status: "ready", job_id: null, error: null, content: {} },
  ],
  references: [], research: [],
} as Workspace

describe("WorkspaceCanvas", () => {
  it("shows open sources and artifacts as tabs with a close control that stays in the tab", () => {
    const html = renderToStaticMarkup(<LocaleProvider><WorkspaceCanvas
      workspace={workspace} knowledge={{ items: [], gaps: [] }} localSelection={null} trace={[]}
      onState={() => undefined} onSelection={() => undefined} onClearSelection={() => undefined}
      onOpen={() => undefined} onReady={() => undefined} onError={() => undefined} onSaved={() => undefined}
    /></LocaleProvider>)
    expect(html).toContain("Förhandlingspunkter")
    expect(html).toContain("Skillnader")
    expect(html).toContain("Avtal_22.pdf")
    expect(html).toContain("8 600 kr i månaden")
    expect(html).toContain('aria-label="Stäng dokument"')
    expect(html).toContain('aria-label="Stäng flik"')
    expect(html).toContain("grid size-7 shrink-0")
    expect(html).toContain("hidden=\"\"")
    expect(html).not.toContain(">Evidens<")
    expect(html).not.toContain(">Jämförelse<")
    expect(html).not.toContain(">Relationer<")
    expect(html.indexOf("Avtal_22.pdf")).toBeLessThan(html.indexOf('aria-label="Modellens arbete"'))
  })

  it("shows the document-set gallery when that view is active", () => {
    const gallery = {
      ...workspace,
      state: {
        ...workspace.state,
        view: "document_set" as const,
        document_sets: [{ id: "leases", title: "Hyresavtal under 2004", source_ids: ["avtal"] }],
        active_document_set_id: "leases",
        active_artifact_id: null,
        open_artifact_ids: [],
      },
    }
    const html = renderToStaticMarkup(<LocaleProvider><WorkspaceCanvas
      workspace={gallery} knowledge={{ items: [], gaps: [] }} localSelection={null} trace={[]}
      onState={() => undefined} onSelection={() => undefined} onClearSelection={() => undefined}
      onOpen={() => undefined} onReady={() => undefined} onError={() => undefined} onSaved={() => undefined}
    /></LocaleProvider>)
    expect(html).toContain("Hyresavtal under 2004")
    expect(html).toContain("Avtal_22.pdf")
    expect(html).toContain('aria-label="Stäng dokumentsamling"')
  })
})
