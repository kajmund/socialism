import { useCallback, useEffect, useMemo, useState } from "react"
import { clearHelpMessages, listHelpMessages, type HelpMessage } from "@/api/help"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { useChatSocket } from "@/components/chat/useChatSocket"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { getHelpSessionId } from "@/lib/helpSession"
import { useHelpView } from "@/lib/helpView"

type HelpChatPanelProps = {
  sessionId: string
  onClose: () => void
}

function doneToHelpMessages(
  rows: { id: number; role: "user" | "assistant"; content: string; created_at?: string }[],
): HelpMessage[] {
  return rows.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    created_at: m.created_at ?? "",
  }))
}

export function HelpChatPanel({ sessionId, onClose }: HelpChatPanelProps) {
  const { t, locale } = useLocale()
  const view = useHelpView()
  const [messages, setMessages] = useState<HelpMessage[]>([])
  const [draft, setDraft] = useState("")
  const [optimisticUser, setOptimisticUser] = useState<string | null>(null)
  const [restBusy, setRestBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const chatHello = useMemo(
    () =>
      sessionId
        ? ({ scope: "help" as const, session_id: sessionId, locale, view })
        : null,
    [sessionId, locale, view],
  )

  const sendExtras = useCallback(() => ({ view }), [view])

  const {
    ready: chatReady,
    busy: socketBusy,
    typing: chatTyping,
    streamText,
    send: socketSend,
  } = useChatSocket({
    hello: chatHello,
    sendExtras,
    onDone: (rows) => {
      setMessages(doneToHelpMessages(rows))
      setOptimisticUser(null)
    },
    onError: (detail) => {
      setOptimisticUser(null)
      setLoadError(detail || t("help.sendError"))
    },
  })

  const chatBusy = restBusy || socketBusy

  useEffect(() => {
    let cancelled = false
    setLoadError(null)
    listHelpMessages(sessionId)
      .then((rows) => {
        if (!cancelled) setMessages(rows)
      })
      .catch(() => {
        if (!cancelled) setLoadError(t("help.loadError"))
      })
    return () => {
      cancelled = true
    }
  }, [sessionId, t])

  const sendMessage = useCallback(() => {
    const trimmed = draft.trim()
    if (!trimmed || chatBusy) return
    setOptimisticUser(trimmed)
    setDraft("")
    setLoadError(null)
    if (!socketSend(trimmed)) {
      setOptimisticUser(null)
      setDraft(trimmed)
      setLoadError(t("chat.notConnected"))
    }
  }, [chatBusy, draft, socketSend, t])

  const handleClear = useCallback(async () => {
    if (chatBusy) return
    setRestBusy(true)
    setLoadError(null)
    try {
      await clearHelpMessages(sessionId)
      setMessages([])
      setOptimisticUser(null)
      setDraft("")
    } catch {
      setLoadError(t("help.clearError"))
    } finally {
      setRestBusy(false)
    }
  }, [chatBusy, sessionId, t])

  return (
    <div className="help-chat-panel" role="dialog" aria-label={t("help.panelAria")}>
      <div className="help-chat-panel-header">
        <div>
          <div className="help-chat-panel-title">{t("help.title")}</div>
          <div className="help-chat-panel-sub">
            {t("help.currentView", { view: view.label })}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <AdminButton
            variant="ghost"
            size="sm"
            disabled={chatBusy || messages.length === 0}
            onClick={() => void handleClear()}
          >
            {t("help.clear")}
          </AdminButton>
          <AdminButton variant="ghost" size="sm" onClick={onClose} aria-label={t("common.close")}>
            ✕
          </AdminButton>
        </div>
      </div>
      {loadError ? <div className="help-chat-panel-error">{loadError}</div> : null}
      <MessengerChat
        messages={messages}
        optimisticUser={optimisticUser}
        typing={chatTyping}
        streamText={streamText}
        draft={draft}
        onDraftChange={setDraft}
        onSend={sendMessage}
        busy={chatBusy}
        ready={chatReady}
        placeholder={t("help.placeholder")}
        empty={<div className="help-chat-empty">{t("help.empty")}</div>}
        className="help-chat-thread"
      />
    </div>
  )
}
