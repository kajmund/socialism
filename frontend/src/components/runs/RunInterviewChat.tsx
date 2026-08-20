import { useCallback, useEffect, useMemo, useState } from "react"
import {
  clearRunPersonaInterview,
  listRunPersonaInterviewMessages,
  type RunInterviewMessage,
} from "@/api/runs"
import { MessengerChat } from "@/components/chat/MessengerChat"
import { useChatSocket } from "@/components/chat/useChatSocket"
import { AdminButton } from "@/components/ui/admin-button"
import { ApiError } from "@/lib/api"
import type { OasisVariantResult } from "@/data/runs-types"
import { useLocale } from "@/i18n"

type RunInterviewChatProps = {
  runId: number
  attemptId: string
  variant: OasisVariantResult
  tickIndex: number
  onTickIndexChange?: (index: number) => void
  showTickSelect?: boolean
  initialPersonaId?: string | null
  compact?: boolean
  showClear?: boolean
  personaDisplayName?: string | null
}

export function RunInterviewChat({
  runId,
  attemptId,
  variant,
  tickIndex,
  onTickIndexChange,
  showTickSelect = false,
  initialPersonaId = null,
  compact = false,
  showClear = true,
  personaDisplayName = null,
}: RunInterviewChatProps) {
  const { t } = useLocale()
  const markers = variant.tick_markers ?? []
  const populationAgents = useMemo(
    () =>
      (variant.agents ?? []).filter(
        (agent) => agent.role !== "injector" && Boolean(agent.persona_id),
      ),
    [variant.agents],
  )

  const [personaId, setPersonaId] = useState("")
  const [messages, setMessages] = useState<RunInterviewMessage[]>([])
  const [optimisticUser, setOptimisticUser] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [restBusy, setRestBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (populationAgents.length === 0) return
    if (
      initialPersonaId &&
      populationAgents.some((agent) => agent.persona_id === initialPersonaId)
    ) {
      setPersonaId(initialPersonaId)
      return
    }
    setPersonaId((prev) => {
      if (prev && populationAgents.some((agent) => agent.persona_id === prev)) return prev
      return populationAgents[0]!.persona_id!
    })
  }, [populationAgents, initialPersonaId])

  const chatHello = useMemo(
    () =>
      personaId && markers.length > 0
        ? {
            scope: "run_interview" as const,
            run_id: runId,
            attempt_id: attemptId,
            variant_id: variant.id,
            persona_id: personaId,
            through_tick_index: tickIndex,
          }
        : null,
    [personaId, markers.length, runId, attemptId, variant.id, tickIndex],
  )

  const {
    ready: chatReady,
    busy: socketBusy,
    typing: chatTyping,
    streamText,
    send: socketSend,
  } = useChatSocket({
    hello: chatHello,
    onDone: (rows) => {
      setMessages(
        rows.map((message) => ({
          id: message.id,
          mode: "interview" as const,
          role: message.role,
          content: message.content,
          created_at: message.created_at ?? "",
          run_id: runId,
          attempt_id: attemptId,
          variant_id: variant.id,
          through_tick_index: tickIndex,
          asked_by: message.asked_by ?? null,
        })),
      )
      setOptimisticUser(null)
      setError(null)
    },
    onError: (detail) => {
      setOptimisticUser(null)
      setError(detail || t("runs.interview.sendError"))
    },
    onInterviewMessage: (message) => {
      setMessages((prev) => {
        if (prev.some((row) => row.id === message.id)) return prev
        return [
          ...prev,
          {
            id: message.id,
            mode: "interview" as const,
            role: message.role,
            content: message.content,
            created_at: message.created_at ?? "",
            run_id: runId,
            attempt_id: attemptId,
            variant_id: variant.id,
            through_tick_index: tickIndex,
            asked_by: message.asked_by ?? null,
          },
        ]
      })
      setError(null)
    },
  })

  const busy = restBusy || socketBusy

  const loadMessages = useCallback(async () => {
    if (!personaId || markers.length === 0) {
      setMessages([])
      return
    }
    setError(null)
    try {
      const rows = await listRunPersonaInterviewMessages(
        runId,
        attemptId,
        variant.id,
        personaId,
        tickIndex,
      )
      setMessages(rows)
      setOptimisticUser(null)
    } catch (err) {
      setMessages([])
      setError(err instanceof ApiError ? err.message : t("runs.interview.loadError"))
    }
  }, [runId, attemptId, variant.id, personaId, tickIndex, markers.length, t])

  useEffect(() => {
    if (!chatReady) {
      setOptimisticUser(null)
      return
    }
    void loadMessages()
  }, [chatReady, loadMessages])

  function send() {
    const trimmed = draft.trim()
    if (!trimmed || !personaId || busy) return
    setError(null)
    setOptimisticUser(trimmed)
    setDraft("")
    if (!socketSend(trimmed)) {
      setOptimisticUser(null)
      setDraft(trimmed)
      setError(t("chat.notConnected"))
    }
  }

  async function clearThread() {
    if (!personaId || busy) return
    setRestBusy(true)
    setError(null)
    try {
      await clearRunPersonaInterview(
        runId,
        attemptId,
        variant.id,
        personaId,
        tickIndex,
      )
      setMessages([])
      setOptimisticUser(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("runs.interview.clearError"))
    } finally {
      setRestBusy(false)
    }
  }

  if (populationAgents.length === 0 || markers.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("runs.interview.unavailable")}
      </p>
    )
  }

  const day = markers[tickIndex]?.day ?? tickIndex + 1

  return (
    <div>
      {!compact ? (
        <div
          className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-foreground"
          role="status"
        >
          {t("runs.interview.contextStatus", {
            day,
            tick: tickIndex + 1,
            nextDay: day + 1,
          })}
        </div>
      ) : null}

      {!compact && (showTickSelect || populationAgents.length > 1) ? (
        <div className="mb-3 flex flex-wrap gap-3">
          {populationAgents.length > 1 ? (
            <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-xs text-muted-foreground">
              {t("runs.interview.personaLabel")}
              <select
                className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-foreground"
                value={personaId}
                onChange={(event) => setPersonaId(event.target.value)}
              >
                {populationAgents.map((agent) => (
                  <option key={agent.persona_id!} value={agent.persona_id!}>
                    {agent.member_name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {showTickSelect ? (
            <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs text-muted-foreground">
              {t("runs.interview.tickLabel")}
              <select
                className="rounded border border-[color:var(--border-hairline)] bg-transparent px-2 py-1.5 text-sm text-foreground"
                value={tickIndex}
                onChange={(event) => onTickIndexChange?.(Number(event.target.value))}
              >
                {markers.map((marker) => (
                  <option key={marker.key || marker.tick_index} value={marker.tick_index}>
                    {t("runs.interview.tickOption", {
                      day: marker.day,
                      tick: marker.tick_index + 1,
                    })}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      ) : compact ? (
        <p className="mb-2 text-xs text-muted-foreground">
          {t("spinndoctor.grid.interviewContext", {
            day,
            tick: tickIndex + 1,
            persona:
              personaDisplayName ??
              populationAgents.find((agent) => agent.persona_id === personaId)?.member_name ??
              t("common.emDash"),
          })}
        </p>
      ) : null}

      {error ? (
        <p className="mb-2 text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <MessengerChat
        className="rounded border border-[color:var(--border-hairline)]"
        messagesClassName={compact ? "max-h-56" : "max-h-72"}
        messages={messages.map((message) => ({
          id: message.id,
          role: message.role,
          content: message.content,
          asked_by: message.asked_by ?? null,
        }))}
        optimisticUser={optimisticUser}
        typing={chatTyping}
        streamText={streamText}
        draft={draft}
        onDraftChange={setDraft}
        onSend={() => send()}
        busy={busy}
        ready={chatReady}
        placeholder={t("runs.interview.placeholder")}
        empty={
          <p className="text-xs text-muted-foreground">{t("runs.interview.empty")}</p>
        }
      />

      {showClear ? (
        <div className="mt-2 flex justify-end">
          <AdminButton
            type="button"
            variant="secondary"
            disabled={busy || messages.length === 0}
            onClick={() => void clearThread()}
          >
            {t("runs.interview.clear")}
          </AdminButton>
        </div>
      ) : null}
    </div>
  )
}
