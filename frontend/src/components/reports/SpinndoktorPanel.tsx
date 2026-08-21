import { useCallback, useEffect, useMemo, useState } from "react"
import {
  clearSpindoctorMessages,
  listSpindoctorMessages,
  type SpindoctorMessage,
} from "@/api/spindoctor"
import type { SpindoctorWidget } from "@/api/spindoctorWidgets"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { useChatSocket } from "@/components/chat/useChatSocket"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { getSpindoctorSessionId } from "@/lib/spindoctorSession"
import { lastSpindoctorRef, stripSpindoctorRefs } from "@/lib/spindoctorRefs"

type SpinndoktorPanelProps = {
  reportId: string
  locale: "sv" | "en"
  onSectionRef?: (sectionId: string) => void
  onWidget?: (widget: SpindoctorWidget) => void
  onViewReport?: () => void
}

function displayMessages(rows: SpindoctorMessage[]): SpindoctorMessage[] {
  return rows.map((m) =>
    m.role === "assistant"
      ? { ...m, content: stripSpindoctorRefs(m.content) }
      : m,
  )
}

export function SpinndoktorPanel({
  reportId,
  locale,
  onSectionRef,
  onWidget,
  onViewReport,
}: SpinndoktorPanelProps) {
  const { t } = useLocale()
  const sessionId = useMemo(() => getSpindoctorSessionId(), [])
  const [messages, setMessages] = useState<SpindoctorMessage[]>([])
  const [draft, setDraft] = useState("")
  const [optimisticUser, setOptimisticUser] = useState<string | null>(null)
  const [restBusy, setRestBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const chatHello = useMemo(
    () =>
      reportId
        ? ({
            scope: "spinndoctor" as const,
            session_id: sessionId,
            report_id: reportId,
            locale,
          })
        : null,
    [reportId, sessionId, locale],
  )

  const handleSectionRef = useCallback(
    (reply: string) => {
      const ref = lastSpindoctorRef(reply)
      if (ref) onSectionRef?.(ref)
    },
    [onSectionRef],
  )

  const {
    ready: chatReady,
    busy: socketBusy,
    typing: chatTyping,
    streamText,
    send: socketSend,
  } = useChatSocket({
    hello: chatHello,
    onWidget,
    onDone: (rows) => {
      const mapped = rows.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at ?? "",
      }))
      const lastAssistant = [...mapped].reverse().find((m) => m.role === "assistant")
      if (lastAssistant) handleSectionRef(lastAssistant.content)
      setMessages(displayMessages(mapped))
      setOptimisticUser(null)
    },
    onError: (detail) => {
      setOptimisticUser(null)
      setLoadError(detail || t("spinndoctor.sendError"))
    },
  })

  const chatBusy = restBusy || socketBusy
  const displayStream =
    streamText != null ? stripSpindoctorRefs(streamText) : null

  const loadHistory = useCallback(async () => {
    try {
      const rows = await listSpindoctorMessages(reportId)
      setMessages(displayMessages(rows))
      setLoadError(null)
    } catch (err) {
      if (err instanceof ApiError && err.isNetworkError) {
        setLoadError(t("spinndoctor.backendUnavailable"))
        return
      }
      setLoadError(t("spinndoctor.loadError"))
    }
  }, [reportId, t])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  useEffect(() => {
    if (!chatReady) {
      setOptimisticUser(null)
      return
    }
    void loadHistory()
  }, [chatReady, loadHistory])

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
      await clearSpindoctorMessages(reportId)
      setMessages([])
      setOptimisticUser(null)
      setDraft("")
    } catch {
      setLoadError(t("spinndoctor.clearError"))
    } finally {
      setRestBusy(false)
    }
  }, [chatBusy, reportId, t])

  return (
    <div className="spinndoctor-panel">
      <div className="spinndoctor-panel-header">
        <div>
          <div className="spinndoctor-panel-title">{t("spinndoctor.title")}</div>
          <div className="spinndoctor-panel-sub">{t("spinndoctor.subtitle")}</div>
        </div>
        <div className="spinndoctor-panel-header-actions">
          {onViewReport ? (
            <AdminButton variant="secondary" size="sm" onClick={onViewReport}>
              {t("spinndoctor.viewReport")}
            </AdminButton>
          ) : null}
          <AdminButton
            variant="secondary"
            size="sm"
            disabled={chatBusy || messages.length === 0}
            onClick={() => void handleClear()}
          >
            {t("spinndoctor.clear")}
          </AdminButton>
        </div>
      </div>
      {loadError ? <div className="spinndoctor-panel-error">{loadError}</div> : null}
      <MessengerChat
        messages={messages}
        optimisticUser={optimisticUser}
        typing={chatTyping}
        streamText={displayStream}
        draft={draft}
        onDraftChange={setDraft}
        onSend={sendMessage}
        busy={chatBusy}
        ready={chatReady}
        placeholder={t("spinndoctor.placeholder")}
        empty={<div className="spinndoctor-empty">{t("spinndoctor.empty")}</div>}
        className="spinndoctor-thread"
      />
    </div>
  )
}
