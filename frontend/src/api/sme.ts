import { api } from "@/lib/api"

export type SmeThreadType = "expert" | "panel"
export type SmeInboxFilter = "all" | "unread" | "groups"

export type SmeInboxItem = {
  thread_type: SmeThreadType
  thread_id: string
  name: string
  initials: string
  subtitle: string
  preview: string
  last_message_at: string | null
  unread_count: number
  member_names: string[]
}

export type SmeMessage = {
  id: number
  role: "user" | "assistant"
  content: string
  created_at: string
  persona_id: string | null
  persona_name: string | null
  image_sha256?: string | null
}

export function listSmeInbox(filter: SmeInboxFilter): Promise<SmeInboxItem[]> {
  return api.get<SmeInboxItem[]>("/sme/inbox", { filter })
}

export function listSmePanelMessages(panelId: string): Promise<SmeMessage[]> {
  return api.get<SmeMessage[]>(`/sme/panels/${panelId}/messages`)
}

export function sendSmePanelMessage(
  panelId: string,
  message: string,
): Promise<SmeMessage[]> {
  return api.post<SmeMessage[]>(
    `/sme/panels/${panelId}/messages`,
    { message },
    { timeoutMs: 120_000 },
  )
}

export function markSmeThreadRead(
  type: SmeThreadType,
  id: string,
): Promise<{ last_read_message_id: number | null }> {
  return api.post(`/sme/threads/${type}/${id}/read`)
}
