import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { SmeInboxFilter, SmeInboxItem } from "@/api/sme"
import { LocaleProvider } from "@/i18n"
import { SmeConversationList } from "./SmeConversationList"

vi.mock("@/lib/api", () => ({ api: {} }))

const expert: SmeInboxItem = {
  thread_type: "expert", thread_id: "same-id", name: "Anna", initials: "A",
  subtitle: "Jurist", kompetensomrade: "Avtal", avatar_url: null,
  preview: "Avtalet har granskats", last_message_at: "2026-10-04T09:00:00Z",
  unread_count: 2, member_names: [],
}
const panel: SmeInboxItem = { ...expert, thread_type: "panel", name: "Expertpanel", preview: "Panelens svar", unread_count: 0 }
const readExpert: SmeInboxItem = { ...expert, thread_id: "read-expert", name: "Erik", unread_count: 0 }

function render({ compact = false, filter = "all", search = "" }: { compact?: boolean; filter?: SmeInboxFilter; search?: string } = {}) {
  return renderToStaticMarkup(<LocaleProvider><SmeConversationList
    compact={compact} scopeLabel="Klient A" filter={filter} items={[expert, panel, readExpert]}
    selected={expert} search={search} loading={false} error={null}
    onFilterChange={() => undefined} onSearchChange={() => undefined}
    onSelect={() => undefined} onOpenExpertEditor={() => undefined}
  /></LocaleProvider>)
}

describe("SME conversation navigation", () => {
  it("keeps the compact rail, inbox search entry, preview and unread badge", () => {
    const html = render({ compact: true })
    expect(html).toContain("w-16")
    expect(html).toContain('aria-label="Sök och filtrera chattar"')
    expect(html).toContain('title="Chattar i Klient A"')
    expect(html).toContain("Avtalet har granskats")
    expect(html).toContain('aria-label="2 olästa"')
    expect(html).toContain("Erik · Läst")
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
  })

  it("filters unread conversations and groups in both layouts", () => {
    for (const compact of [false, true]) {
      const unread = render({ compact, filter: "unread" })
      expect(unread).toContain("Anna")
      expect(unread).not.toContain("Expertpanel")
      expect(unread).not.toContain("Erik")
      const groups = render({ compact, filter: "groups" })
      expect(groups).toContain("Expertpanel")
      expect(groups).not.toContain("Anna")
      expect(groups).not.toContain("Erik")
    }
  })

  it("searches message previews as well as expert names", () => {
    const html = render({ search: "GRANSKATS" })
    expect(html).toContain("Anna")
    expect(html).not.toContain("Expertpanel")
  })
})
