import { describe, expect, it, vi } from "vitest"
import type { SmeInboxItem } from "@/api/sme"
import type { WorkspaceMessage } from "@/api/voiceWorkspaces"
import { createVoiceInboxReads, voiceInboxItems } from "./useVoiceWorkspaceInbox"

vi.mock("@/lib/api", () => ({ api: {} }))

const expert: SmeInboxItem = {
  thread_type: "expert", thread_id: "jurist", name: "Karin", initials: "K",
  subtitle: "Juridisk expert", kompetensomrade: "Avtal", avatar_url: null,
  preview: "Company interview content", last_message_at: "2026-10-03T10:00:00Z", unread_count: 9, member_names: [],
}
const message: WorkspaceMessage = { id: 12, role: "agent", content: "Private answer", created_at: "2026-10-04T10:00:00Z", event_key: "agent:1", session_id: "session-a" }

describe("private voice workspace inbox", () => {
  it("uses only native expert previews and unread counts while preserving panel records", () => {
    const panel = { ...expert, thread_type: "panel" as const }
    const empty = voiceInboxItems([expert, panel], [])
    expect(empty[0]).toEqual({ ...expert, preview: "", last_message_at: null, unread_count: 0 })
    expect(empty[1]).toBe(panel)
    const rows = voiceInboxItems([expert], [{ expert_id: "jurist", preview: "Private contract answer", last_message_at: message.created_at, unread_count: 2 }])
    expect(rows[0]).toEqual({ ...expert, preview: "Private contract answer", last_message_at: message.created_at, unread_count: 2 })
    expect(expert.preview).toBe("Company interview content")
  })

  it("marks only successfully viewed history and persisted messages read", async () => {
    const read = vi.fn().mockResolvedValue({ last_read_message_id: 12 }), refresh = vi.fn().mockResolvedValue(undefined)
    const inbox = createVoiceInboxReads(read, refresh)
    inbox.select("canvas-a", "jurist")
    await inbox.persisted(message)
    expect(read).not.toHaveBeenCalled()
    await inbox.historyLoaded(inbox.selection())
    expect(read).toHaveBeenCalledWith("canvas-a", "jurist")
    await inbox.persisted({ ...message, id: -1 })
    expect(read).toHaveBeenCalledTimes(1)
    await inbox.persisted(message)
    expect(read).toHaveBeenCalledTimes(2)
    expect(refresh).toHaveBeenCalledWith("canvas-a")
  })

  it("ignores old history after changing canvas or expert, including returning to the same selection", async () => {
    const read = vi.fn().mockResolvedValue(undefined), refresh = vi.fn().mockResolvedValue(undefined)
    const inbox = createVoiceInboxReads(read, refresh)
    inbox.select("canvas-a", "jurist")
    const old = inbox.selection()
    inbox.select("canvas-b", "jurist")
    await inbox.historyLoaded(old)
    inbox.select("canvas-a", "jurist")
    await inbox.historyLoaded(old)
    const previousExpert = inbox.selection()
    inbox.select("canvas-a", "economist")
    await inbox.historyLoaded(previousExpert)
    await inbox.persisted(message)
    expect(read).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
  })

  it("does not refresh a newly selected canvas when an old read acknowledgement arrives", async () => {
    let complete!: () => void
    const read = vi.fn(() => new Promise<void>((resolve) => { complete = resolve })), refresh = vi.fn().mockResolvedValue(undefined)
    const inbox = createVoiceInboxReads(read, refresh)
    inbox.select("canvas-a", "jurist")
    const pending = inbox.historyLoaded(inbox.selection())
    inbox.select("canvas-b", "jurist")
    complete()
    await pending
    expect(read).toHaveBeenCalledWith("canvas-a", "jurist")
    expect(refresh).not.toHaveBeenCalled()
    await inbox.persisted(message)
    expect(read).toHaveBeenCalledTimes(1)
  })
})
