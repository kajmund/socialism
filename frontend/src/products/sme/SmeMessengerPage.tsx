import { useCallback, useEffect, useRef, useState } from "react"
import {
  getSuggestedQuestions,
  listPersonaMessages,
  type PersonaMessage,
} from "@/api/personas"
import {
  getSmeExpertTurn,
  listSmeInbox,
  listSmePanelMessages,
  markSmeThreadRead,
  sendSmePanelMessage,
  type SmeInboxFilter,
  type SmeInboxItem,
  type SmeMessage,
} from "@/api/sme"
import { latestChatMessages } from "@/components/chat/chatWindow"
import { WorkspaceChatPanel } from "@/components/workspaces/WorkspaceChatPanel"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { SmeChatPane } from "@/products/sme/SmeChatPane"
import { SmeConversationList } from "@/products/sme/SmeConversationList"
import { SmeExpertEditorModal } from "@/products/sme/SmeExpertEditorModal"
import { SmeJobsButton } from "@/products/sme/SmeJobsButton"
import { SmeResearchJobsButton } from "@/products/sme/SmeResearchJobsButton"
import { SmeUserMenu } from "@/products/sme/SmeUserMenu"
import {
  smeTurnRecoveryAction,
  type SmeExpertTurnLookup,
} from "@/products/sme/smeTurnRecovery"
import { useSmeChatSocket } from "@/products/sme/useSmeChatSocket"

type PendingExpertTurn = {
  requestId: string
  threadId: string
  message: string
  imageSha256?: string | null
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function SmeMessengerPage() {
  const { locale, setLocale, t } = useLocale()
  const [filter, setFilter] = useState<SmeInboxFilter>("all")
  const [workspaceMode, setWorkspaceMode] = useState(false)
  const [inbox, setInbox] = useState<SmeInboxItem[]>([])
  const [selected, setSelected] = useState<SmeInboxItem | null>(null)
  const [messages, setMessages] = useState<SmeMessage[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [search, setSearch] = useState("")
  const [loadingInbox, setLoadingInbox] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [pendingThreads, setPendingThreads] = useState<Set<string>>(new Set())
  const [streamByThread, setStreamByThread] = useState<Record<string, string>>(
    {},
  )
  const [inboxError, setInboxError] = useState<string | null>(null)
  const [chatError, setChatError] = useState<string | null>(null)
  const [expertEditor, setExpertEditor] = useState<{
    id: string
    name: string
  } | null>(null)
  const initialSelectionDone = useRef(false)
  const selectedRef = useRef<SmeInboxItem | null>(null)
  const filterRef = useRef<SmeInboxFilter>("all")
  const pendingExpertTurnsRef = useRef<Map<string, PendingExpertTurn>>(
    new Map(),
  )
  const pollTimersRef = useRef<Map<string, number>>(new Map())
  const recoverPendingRef = useRef<() => void>(() => undefined)
  const resendRef = useRef<
    (
      requestId: string,
      threadId: string,
      message: string,
      imageSha256?: string | null,
    ) => boolean
  >(() => false)
  selectedRef.current = selected
  filterRef.current = filter

  function threadKey(thread: SmeInboxItem): string {
    return `${thread.thread_type}:${thread.thread_id}`
  }

  function setThreadPending(thread: SmeInboxItem, pending: boolean) {
    setThreadKeyPending(threadKey(thread), pending)
  }

  function setThreadKeyPending(key: string, pending: boolean) {
    setPendingThreads((current) => {
      const next = new Set(current)
      if (pending) next.add(key)
      else next.delete(key)
      return next
    })
  }

  const loadInbox = useCallback(async (
    nextFilter: SmeInboxFilter,
    options?: { silent?: boolean },
  ) => {
    if (!options?.silent) setLoadingInbox(true)
    try {
      const rows = await listSmeInbox(nextFilter)
      setInbox(rows)
      setSelected((current) => {
        if (!current) return current
        return (
          rows.find(
            (row) =>
              row.thread_type === current.thread_type &&
              row.thread_id === current.thread_id,
          ) ?? current
        )
      })
      setExpertEditor((current) => {
        if (!current) return current
        const row = rows.find(
          (item) => item.thread_type === "expert" && item.thread_id === current.id,
        )
        return row ? { id: row.thread_id, name: row.name } : current
      })
      setInboxError(null)
      if (!initialSelectionDone.current) {
        setSelected(rows[0] ?? null)
        initialSelectionDone.current = true
      }
    } catch (error: unknown) {
      setInboxError(errorMessage(error, t("sme.loadError")))
    } finally {
      if (!options?.silent) setLoadingInbox(false)
    }
  }, [t])

  useEffect(() => {
    void loadInbox(filter)
  }, [filter, loadInbox])

  useEffect(() => {
    if (!selected) {
      setMessages([])
      setSuggestions([])
      return
    }
    let cancelled = false
    const abort = new AbortController()
    setLoadingMessages(true)
    setChatError(null)
    setSuggestions([])
    const request =
      selected.thread_type === "expert"
        ? listPersonaMessages(selected.thread_id, "interview").then((rows) =>
            rows.map<SmeMessage>((row) => ({
              id: row.id,
              role: row.role,
              content: row.content,
              created_at: row.created_at,
              persona_id: row.role === "assistant" ? selected.thread_id : null,
              persona_name: null,
              image_sha256: row.image_sha256,
            })),
          )
        : listSmePanelMessages(selected.thread_id)
    request
      .then((rows) => {
        if (!cancelled) setMessages(latestChatMessages(rows))
      })
      .catch((error: unknown) => {
        if (!cancelled) setChatError(errorMessage(error, t("sme.chatError")))
      })
      .finally(() => {
        if (!cancelled) setLoadingMessages(false)
      })
    if (selected.thread_type === "expert") {
      void getSuggestedQuestions(selected.thread_id, "interview", {
        signal: abort.signal,
      })
        .then((response) => {
          if (!cancelled) setSuggestions(response.questions)
        })
        .catch(() => {
          if (!cancelled) setSuggestions([])
        })
    }
    void markSmeThreadRead(selected.thread_type, selected.thread_id)
      .then(() => {
        if (!cancelled) {
          setInbox((rows) =>
            rows.map((row) =>
              row.thread_type === selected.thread_type &&
              row.thread_id === selected.thread_id
                ? { ...row, unread_count: 0 }
                : row,
            ),
          )
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setChatError(errorMessage(error, t("sme.chatError")))
      })
    return () => {
      cancelled = true
      abort.abort()
    }
  }, [selected, t])

  const clearExpertTurn = useCallback((requestId: string, threadId: string) => {
    pendingExpertTurnsRef.current.delete(requestId)
    const timer = pollTimersRef.current.get(requestId)
    if (timer != null) {
      window.clearInterval(timer)
      pollTimersRef.current.delete(requestId)
    }
    const stillPending = [...pendingExpertTurnsRef.current.values()].some(
      (turn) => turn.threadId === threadId,
    )
    if (!stillPending) {
      setThreadKeyPending(`expert:${threadId}`, false)
      setStreamByThread((current) => {
        const next = { ...current }
        delete next[threadId]
        return next
      })
    }
  }, [])

  const applyExpertDone = useCallback(
    (threadId: string, rows: SmeMessage[], requestId: string) => {
      clearExpertTurn(requestId, threadId)
      const active = selectedRef.current
      if (active?.thread_type === "expert" && active.thread_id === threadId) {
        setMessages(
          latestChatMessages(
            rows.map((row) => ({
              ...row,
              persona_id: row.role === "assistant" ? threadId : null,
            })),
          ),
        )
        void markSmeThreadRead("expert", threadId).then(() =>
          loadInbox(filterRef.current),
        )
      } else {
        void loadInbox(filterRef.current)
      }
    },
    [clearExpertTurn, loadInbox],
  )

  const applyExpertError = useCallback(
    (threadId: string | null, detail: string, requestId: string | null) => {
      if (requestId && threadId) {
        clearExpertTurn(requestId, threadId)
      } else if (threadId) {
        setThreadKeyPending(`expert:${threadId}`, false)
        setStreamByThread((current) => {
          const next = { ...current }
          delete next[threadId]
          return next
        })
      }
      const active = selectedRef.current
      if (!threadId || active?.thread_id === threadId) {
        setMessages((rows) => rows.filter((row) => row.id >= 0))
        setChatError(detail)
      }
    },
    [clearExpertTurn],
  )

  const expertSocket = useSmeChatSocket({
    onDisconnected: () => {
      void loadInbox(filterRef.current)
    },
    onReady: () => {
      recoverPendingRef.current()
    },
    onToken: (threadId, text) => {
      setStreamByThread((current) => ({
        ...current,
        [threadId]: (current[threadId] ?? "") + text,
      }))
    },
    onDone: applyExpertDone,
    onSuggestions: (threadId, questions) => {
      const active = selectedRef.current
      if (active?.thread_type === "expert" && active.thread_id === threadId) {
        setSuggestions(questions)
      }
    },
    onThreadMessage: (threadId, rows) => {
      const active = selectedRef.current
      if (active?.thread_type === "expert" && active.thread_id === threadId) {
        setMessages(
          latestChatMessages(
            rows.map((row) => ({
              ...row,
              persona_id: row.role === "assistant" ? threadId : null,
            })),
          ),
        )
        void markSmeThreadRead("expert", threadId).then(() =>
          loadInbox(filterRef.current),
        )
      } else {
        void loadInbox(filterRef.current)
      }
    },
    onConsultAnswered: () => {
      void loadInbox(filterRef.current)
    },
    onError: applyExpertError,
  })

  const recoverOneExpertTurn = useCallback(
    async (pending: PendingExpertTurn) => {
      let lookup: SmeExpertTurnLookup | null = null
      try {
        lookup = await getSmeExpertTurn(pending.requestId)
      } catch (error: unknown) {
        if (!(error instanceof ApiError) || error.status !== 404) {
          return
        }
      }
      const action = smeTurnRecoveryAction(lookup)
      switch (action) {
        case "wait":
          if (!pollTimersRef.current.has(pending.requestId)) {
            const timer = window.setInterval(() => {
              void recoverOneExpertTurn(pending)
            }, 1000)
            pollTimersRef.current.set(pending.requestId, timer)
          }
          break
        case "apply":
          if (lookup) {
            applyExpertDone(pending.threadId, lookup.messages, pending.requestId)
          }
          break
        case "fail":
          applyExpertError(
            pending.threadId,
            lookup?.error ?? t("sme.chatError"),
            pending.requestId,
          )
          break
        case "resend":
          if (
            !resendRef.current(
              pending.requestId,
              pending.threadId,
              pending.message,
              pending.imageSha256,
            )
          ) {
            if (!pollTimersRef.current.has(pending.requestId)) {
              const timer = window.setInterval(() => {
                void recoverOneExpertTurn(pending)
              }, 1000)
              pollTimersRef.current.set(pending.requestId, timer)
            }
          }
          break
        default: {
          const _exhaustive: never = action
          return _exhaustive
        }
      }
    },
    [applyExpertDone, applyExpertError, t],
  )

  const recoverPendingExpertTurns = useCallback(async () => {
    const pending = [...pendingExpertTurnsRef.current.values()]
    await Promise.all(pending.map((turn) => recoverOneExpertTurn(turn)))
  }, [recoverOneExpertTurn])

  recoverPendingRef.current = () => {
    void recoverPendingExpertTurns()
  }
  resendRef.current = expertSocket.resend

  useEffect(() => {
    const timers = pollTimersRef
    return () => {
      for (const timer of timers.current.values()) {
        window.clearInterval(timer)
      }
      timers.current.clear()
    }
  }, [])

  function appendVoiceTranscript(personaId: string, saved: PersonaMessage[]) {
    if (saved.length === 0) return
    const active = selectedRef.current
    const viewing =
      active?.thread_type === "expert" && active.thread_id === personaId
    if (viewing) {
      setMessages((rows) => {
        const known = new Set(rows.map((message) => message.id))
        const added = saved.flatMap((message): SmeMessage[] =>
          known.has(message.id)
            ? []
            : [
                {
                  id: message.id,
                  role: message.role,
                  content: message.content,
                  created_at: message.created_at,
                  persona_id: message.role === "assistant" ? personaId : null,
                  persona_name: null,
                  image_sha256: message.image_sha256,
                },
              ],
        )
        return latestChatMessages(added.length === 0 ? rows : [...rows, ...added])
      })
      void markSmeThreadRead("expert", personaId).catch(() => undefined)
    }
    const last = saved[saved.length - 1]
    if (!last) return
    setInbox((rows) =>
      rows.map((row) =>
        row.thread_type === "expert" && row.thread_id === personaId
          ? {
              ...row,
              preview: last.content,
              last_message_at: last.created_at,
              unread_count: viewing ? 0 : row.unread_count + 1,
            }
          : row,
      ),
    )
  }

  function selectThread(item: SmeInboxItem) {
    setSelected(item)
    setChatError(null)
  }

  function openExpertEditor(item: SmeInboxItem) {
    if (item.thread_type !== "expert") return
    setExpertEditor({ id: item.thread_id, name: item.name })
  }

  function changeFilter(next: SmeInboxFilter) {
    setFilter(next)
    setSelected(null)
    setSearch("")
  }

  function send(message: string, imageSha256?: string | null): boolean {
    if (!selected) return false
    const thread = selected
    if (pendingThreads.has(threadKey(thread))) return false
    setChatError(null)
    setSuggestions([])
    setThreadPending(thread, true)
    if (thread.thread_type === "expert") {
      setMessages((rows) => [
        ...rows,
        {
          id: -Date.now(),
          role: "user",
          content: message,
          created_at: new Date().toISOString(),
          persona_id: null,
          persona_name: null,
          image_sha256: imageSha256,
        },
      ])
      const requestId = expertSocket.send(thread.thread_id, message, imageSha256)
      if (!requestId) {
        setThreadPending(thread, false)
        setMessages((rows) => rows.filter((row) => row.id >= 0))
        setChatError(t("chat.notConnected"))
        return false
      }
      pendingExpertTurnsRef.current.set(requestId, {
        requestId,
        threadId: thread.thread_id,
        message,
        imageSha256,
      })
      return true
    }
    void sendSmePanelMessage(thread.thread_id, message)
      .then(async (created) => {
        const active = selectedRef.current
        if (
          active?.thread_type === "panel" &&
          active.thread_id === thread.thread_id
        ) {
          setMessages((rows) => [...rows, ...created])
          await markSmeThreadRead("panel", thread.thread_id)
        }
        await loadInbox(filterRef.current)
      })
      .catch((error: unknown) => {
        const active = selectedRef.current
        if (
          active?.thread_type === "panel" &&
          active.thread_id === thread.thread_id
        ) {
          setChatError(errorMessage(error, t("sme.chatError")))
        }
      })
      .finally(() => setThreadPending(thread, false))
    return true
  }

  const selectedPending = selected
    ? pendingThreads.has(threadKey(selected))
    : false

  return (
    <div className="theme-admin flex h-dvh min-h-0 flex-col bg-db-ink-50 font-sans text-[color:var(--text-body)]">
      <header className="flex min-h-16 shrink-0 flex-wrap items-center gap-y-2 bg-db-ink-950 px-4 py-2 text-db-ink-0 sm:px-6">
        <img
          src="/devbrains-logo-white.png"
          alt="Devbrains"
          className="h-8 w-auto"
        />
        <span className="mx-4 h-6 w-px bg-white/20" aria-hidden="true" />
        <span className="hidden font-[var(--font-display)] text-sm font-medium tracking-wide text-white/80 sm:inline">
          {t("sme.productName")}
        </span>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1 sm:gap-2">
          <button type="button" className={`rounded px-2 py-1.5 text-xs ${workspaceMode ? "bg-db-gold-500 text-db-ink-950" : "text-white/80 hover:bg-white/10"}`} aria-pressed={workspaceMode} onClick={() => setWorkspaceMode(true)}>{t("workspaceChat.title")}</button>
          <button type="button" className={`rounded px-2 py-1.5 text-xs ${!workspaceMode ? "bg-db-gold-500 text-db-ink-950" : "text-white/80 hover:bg-white/10"}`} aria-pressed={!workspaceMode} onClick={() => setWorkspaceMode(false)}>{t("workspaceChat.experts")}</button>
          <SmeResearchJobsButton />
          <SmeJobsButton />
          <LocaleSwitcher locale={locale} setLocale={setLocale} t={t} />
          <SmeUserMenu />
        </div>
      </header>
      <main className="flex min-h-0 flex-1">
        {workspaceMode ? <WorkspaceChatPanel key="company" /> : <>
        <div className={selected ? "hidden md:contents" : "contents"}>
          <SmeConversationList
            filter={filter}
            items={inbox}
            selected={selected}
            search={search}
            loading={loadingInbox}
            error={inboxError}
            onFilterChange={changeFilter}
            onSearchChange={setSearch}
            onSelect={selectThread}
            onOpenExpertEditor={openExpertEditor}
          />
        </div>
        <SmeChatPane
          thread={selected}
          messages={messages}
          loading={loadingMessages}
          sending={selectedPending}
          typing={
            selectedPending &&
            !(
              selected?.thread_type === "expert" &&
              streamByThread[selected.thread_id]
            )
          }
          streamText={
            selected?.thread_type === "expert"
              ? streamByThread[selected.thread_id] ?? null
              : null
          }
          error={chatError}
          ready={
            selected?.thread_type === "expert" ? expertSocket.ready : true
          }
          suggestions={suggestions}
          onSend={send}
          onBack={() => setSelected(null)}
          onOpenExpertEditor={
            selected?.thread_type === "expert"
              ? () => openExpertEditor(selected)
              : undefined
          }
          onVoiceTranscript={appendVoiceTranscript}
        />
        </>}
      </main>
      {expertEditor ? (
        <SmeExpertEditorModal
          open
          expertId={expertEditor.id}
          expertName={expertEditor.name}
          onClose={() => setExpertEditor(null)}
          onSaved={() => {
            void loadInbox(filterRef.current, { silent: true })
          }}
        />
      ) : null}
    </div>
  )
}
