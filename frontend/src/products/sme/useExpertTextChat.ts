import { useCallback, useRef } from "react"
import type { WorkspaceMessage, WorkspaceState } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { useSmeChatSocket } from "./useSmeChatSocket"
import type { ModelTraceEntry } from "./modelTrace"
import { interviewTranscriptMessage } from "./workspaceChatLogic"
import {
  INITIAL_DRAFT_STATE,
  reduceDraftPreview,
  type DraftStreamEvent,
  type DraftStreamState,
} from "./smeDraftState"

type Handlers = {
  onMessages: (threadId: string, messages: WorkspaceMessage[]) => void
  onPreview: (threadId: string, text: string | null) => void
  onDraftPreview: (threadId: string, text: string | null) => void
  onError: (message: string) => void
  onWorkspaceTool: (threadId: string, name: string, args: Record<string, unknown>) => void
  onModelTrace: (threadId: string, workspaceId: string, entry: ModelTraceEntry) => void
}

/** A finished acknowledgment becomes a local message right before the reply. */
function withAcknowledgment(threadId: string, rows: WorkspaceMessage[], draft: string | null): WorkspaceMessage[] {
  const ack = (draft ?? "").trim()
  if (!ack || rows.length === 0) return rows
  const last = rows[rows.length - 1]
  const ackRow: WorkspaceMessage = {
    id: last.id - 0.5,
    role: "agent",
    content: ack,
    created_at: last.created_at,
    event_key: `quick-ack:${threadId}:${last.id}`,
    session_id: "quick-ack",
  }
  return [...rows.slice(0, -1), ackRow, last]
}

export function useExpertTextChat(handlers: Handlers) {
  const { t } = useLocale()
  const latest = useRef(handlers)
  latest.current = handlers
  const pending = useRef(new Map<string, { resolve: () => void; reject: (error: Error) => void }>())
  const drafts = useRef(new Map<string, DraftStreamState>())
  const settle = (threadId: string, error?: Error) => {
    const wait = pending.current.get(threadId)
    if (!wait) return
    pending.current.delete(threadId)
    if (error) wait.reject(error)
    else wait.resolve()
  }
  const clearDrafts = () => {
    for (const threadId of drafts.current.keys()) {
      latest.current.onDraftPreview(threadId, null)
    }
    drafts.current.clear()
  }
  const reduceDraft = (threadId: string, event: DraftStreamEvent) => {
    const next = reduceDraftPreview(
      drafts.current.get(threadId) ?? INITIAL_DRAFT_STATE,
      event,
    )
    drafts.current.set(threadId, next)
    latest.current.onDraftPreview(threadId, next.draft)
  }
  const failAll = (error: Error) => {
    clearDrafts()
    for (const threadId of [...pending.current.keys()]) settle(threadId, error)
  }
  const socket = useSmeChatSocket({
    onDone: (threadId, messages) => {
      const draft = (drafts.current.get(threadId) ?? INITIAL_DRAFT_STATE).draft
      reduceDraft(threadId, { type: "close" })
      const rows = messages.map((row) => interviewTranscriptMessage(row))
      latest.current.onMessages(threadId, withAcknowledgment(threadId, rows, draft))
      latest.current.onPreview(threadId, null)
      settle(threadId)
    },
    onSuggestions: () => undefined,
    onError: (threadId, detail) => {
      const message = detail.trim() && detail !== "Chat error" ? detail : t("sme.chatError")
      latest.current.onError(message)
      if (threadId) {
        reduceDraft(threadId, { type: "close" })
        latest.current.onPreview(threadId, null)
        settle(threadId, new Error(message))
      } else failAll(new Error(message))
    },
    onToken: (threadId, text) => {
      latest.current.onPreview(threadId, text)
    },
    onDraftToken: (threadId, text) => reduceDraft(threadId, { type: "draft_token", text }),
    onThreadMessage: (threadId, messages) => latest.current.onMessages(threadId, messages.map((row) => interviewTranscriptMessage(row))),
    onConsultAnswered: () => undefined,
    onWorkspaceTool: (threadId, name, args) => latest.current.onWorkspaceTool(threadId, name, args),
    onModelTrace: (threadId, workspaceId, entry) => {
      latest.current.onModelTrace(threadId, workspaceId, entry)
    },
    onReady: () => undefined,
    onDisconnected: () => failAll(new Error(t("sme.chatError"))),
  })
  const readyRef = useRef(socket.ready)
  const sendRef = useRef(socket.send)
  readyRef.current = socket.ready
  sendRef.current = socket.send
  const send = useCallback(async (threadId: string, text: string, workspace?: { id: string; state: WorkspaceState }) => {
    const started = Date.now()
    while (!readyRef.current) {
      if (Date.now() - started > 4000) throw new Error(t("sme.chatError"))
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
    drafts.current.set(threadId, INITIAL_DRAFT_STATE)
    await new Promise<void>((resolve, reject) => {
      pending.current.set(threadId, { resolve, reject })
      if (!sendRef.current(threadId, text, null, workspace)) {
        pending.current.delete(threadId)
        reject(new Error(t("sme.chatError")))
      }
    })
  }, [t])
  return { send }
}
