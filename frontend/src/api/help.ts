import { api } from "@/lib/api"

export type HelpLocale = "sv" | "en"
export type HelpRole = "user" | "assistant"

export type HelpMessage = {
  id: number
  role: HelpRole
  content: string
  created_at: string
}

export function listHelpMessages(sessionId: string): Promise<HelpMessage[]> {
  return api.get<HelpMessage[]>("/help/messages", { session_id: sessionId })
}

export function clearHelpMessages(sessionId: string): Promise<void> {
  return api.delete<void>("/help/messages", { session_id: sessionId })
}
