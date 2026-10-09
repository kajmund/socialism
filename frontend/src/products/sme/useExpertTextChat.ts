import { useCallback, useRef } from "react"
import type { WorkspaceMessage, WorkspaceState } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { useSmeChatSocket } from "./useSmeChatSocket"
import type { ModelTraceEntry } from "./modelTrace"
import { interviewTranscriptMessage } from "./workspaceChatLogic"

type Handlers = {
  onMessages: (threadId: string, messages: WorkspaceMessage[]) => void
  onPreview: (threadId: string, text: string | null) => void
  onError: (message: string) => void
  onWorkspaceTool: (threadId: string, name: string, args: Record<string, unknown>) => void
  onModelTrace: (threadId: string, workspaceId: string, entry: ModelTraceEntry) => void
}

export function useExpertTextChat(handlers: Handlers) {
  const { t } = useLocale()
  const latest = useRef(handlers)
  latest.current = handlers
  const pending = useRef(new Map<string, { resolve: () => void; reject: (error: Error) => void }>())
  const settle = (threadId: string, error?: Error) => {
    const wait = pending.current.get(threadId)
    if (!wait) return
    pending.current.delete(threadId)
    if (error) wait.reject(error)
    else wait.resolve()
  }
  const failAll = (error: Error) => {
    for (const threadId of [...pending.current.keys()]) settle(threadId, error)
  }
  const socket = useSmeChatSocket({
    onDone: (threadId, messages) => {
      latest.current.onMessages(threadId, messages.map((row) => interviewTranscriptMessage(row)))
      latest.current.onPreview(threadId, null)
      settle(threadId)
    },
    onSuggestions: () => undefined,
    onError: (threadId, detail) => {
      const message = detail.trim() && detail !== "Chat error" ? detail : t("sme.chatError")
      latest.current.onError(message)
      if (threadId) settle(threadId, new Error(message))
      else failAll(new Error(message))
    },
    onToken: (threadId, text) => latest.current.onPreview(threadId, text),
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
