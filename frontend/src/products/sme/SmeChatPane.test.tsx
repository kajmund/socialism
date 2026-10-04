import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { SmeInboxItem } from "@/api/sme"
import { LocaleProvider } from "@/i18n"
import { SmeChatPane } from "./SmeChatPane"

vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({ refreshProfile: vi.fn() }),
}))
vi.mock("@/lib/api", () => ({ api: {}, ApiError: class extends Error {} }))
vi.mock("@/api/messages", () => ({
  uploadMessageImageRaw: vi.fn(), fetchCachedImageBlob: vi.fn(),
}))
vi.mock("@/components/chat/useLlmCapabilities", () => ({
  useLlmCapabilities: () => ({ allowImageAttach: true, imageAccept: "image/png" }),
}))

const expert: SmeInboxItem = {
  thread_type: "expert", thread_id: "expert-a", name: "Anna", initials: "A",
  subtitle: "Jurist", kompetensomrade: "Avtal", avatar_url: null, preview: "",
  last_message_at: null, unread_count: 0, member_names: [],
}

function render(thread: SmeInboxItem, ready = true) {
  return renderToStaticMarkup(<LocaleProvider><SmeChatPane
    thread={thread} messages={[]} loading={false} sending={false} typing={false}
    streamText={null} error={null} ready={ready} suggestions={["Vilka villkor gäller?"]}
    onSend={() => true} onBack={() => undefined} onVoiceTranscript={() => undefined}
  /></LocaleProvider>)
}

describe("SME expert conversation controls", () => {
  it("retains voice, memory, tools, editor, image attachments and follow-up questions", () => {
    const html = render(expert)
    for (const label of [
      "Starta röstsamtal med experten", "Visa minneslogg för Anna", "Välj verktyg",
      "Redigera Anna", "Bifoga bild", "Föreslagna följdfrågor",
    ]) expect(html).toContain(`aria-label="${label}"`)
    expect(html).toContain("Vilka villkor gäller?")
  })

  it("keeps the reconnect notice in an expert conversation", () => {
    expect(render(expert, false)).toContain("Ansluter till chatten…")
  })

  it("does not expose expert voice or memories in panel conversations", () => {
    const html = render({ ...expert, thread_type: "panel", member_names: ["Anna", "Erik"] })
    expect(html).not.toContain("Starta röstsamtal med experten")
    expect(html).not.toContain("Visa minneslogg")
    expect(html).not.toContain("Välj verktyg")
  })
})
