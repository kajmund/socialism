import { useCallback, useEffect, useRef, useState } from "react"
import {
  getSuggestedQuestions,
  listPersonaMessages,
} from "@/api/personas"
import {
  listSmeInbox,
  listSmePanelMessages,
  markSmeThreadRead,
  sendSmePanelMessage,
  type SmeInboxFilter,
  type SmeInboxItem,
  type SmeMessage,
} from "@/api/sme"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { SmeChatPane } from "@/products/sme/SmeChatPane"
import { SmeConversationList } from "@/products/sme/SmeConversationList"
import { SmeUserMenu } from "@/products/sme/SmeUserMenu"
import { useSmeChatSocket } from "@/products/sme/useSmeChatSocket"

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function SmeMessengerPage() {
  const { locale, setLocale, t } = useLocale()
  const [filter, setFilter] = useState<SmeInboxFilter>("all")
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
  const initialSelectionDone = useRef(false)
  const selectedRef = useRef<SmeInboxItem | null>(null)
  const filterRef = useRef<SmeInboxFilter>("all")
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

  const loadInbox = useCallback(async (nextFilter: SmeInboxFilter) => {
    setLoadingInbox(true)
    try {
      const rows = await listSmeInbox(nextFilter)
      setInbox(rows)
      setInboxError(null)
      if (!initialSelectionDone.current) {
        setSelected(rows[0] ?? null)
        initialSelectionDone.current = true
      }
    } catch (error: unknown) {
      setInboxError(errorMessage(error, t("sme.loadError")))
    } finally {
      setLoadingInbox(false)
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
        if (!cancelled) setMessages(rows)
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

  const expertSocket = useSmeChatSocket({
    onDisconnected: () => {
      setPendingThreads(
        (current) =>
          new Set([...current].filter((key) => !key.startsWith("expert:"))),
      )
      setStreamByThread({})
      const active = selectedRef.current
      if (active?.thread_type === "expert") {
        void listPersonaMessages(active.thread_id, "interview")
          .then((rows) =>
            setMessages(
              rows.map((row) => ({
                id: row.id,
                role: row.role,
                content: row.content,
                created_at: row.created_at,
                persona_id:
                  row.role === "assistant" ? active.thread_id : null,
                persona_name: null,
                image_sha256: row.image_sha256,
              })),
            ),
          )
          .catch((error: unknown) =>
            setChatError(errorMessage(error, t("sme.chatError"))),
          )
      }
      void loadInbox(filterRef.current)
    },
    onToken: (threadId, text) => {
      setStreamByThread((current) => ({
        ...current,
        [threadId]: (current[threadId] ?? "") + text,
      }))
    },
    onDone: (threadId, rows) => {
      setThreadKeyPending(`expert:${threadId}`, false)
      setStreamByThread((current) => {
        const next = { ...current }
        delete next[threadId]
        return next
      })
      const active = selectedRef.current
      if (active?.thread_type === "expert" && active.thread_id === threadId) {
        setMessages(
          rows.map((row) => ({
            ...row,
            persona_id: row.role === "assistant" ? threadId : null,
          })),
        )
        void markSmeThreadRead("expert", threadId).then(() =>
          loadInbox(filterRef.current),
        )
      } else {
        void loadInbox(filterRef.current)
      }
    },
    onSuggestions: (threadId, questions) => {
      const active = selectedRef.current
      if (active?.thread_type === "expert" && active.thread_id === threadId) {
        setSuggestions(questions)
      }
    },
    onError: (threadId, detail) => {
      if (threadId) {
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
  })

  function selectThread(item: SmeInboxItem) {
    setSelected(item)
    setChatError(null)
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
      if (!expertSocket.send(thread.thread_id, message, imageSha256)) {
        setThreadPending(thread, false)
        setMessages((rows) => rows.filter((row) => row.id >= 0))
        setChatError(t("chat.notConnected"))
        return false
      }
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
      <header className="flex h-16 shrink-0 items-center bg-db-ink-950 px-4 text-db-ink-0 sm:px-6">
        <img
          src="/devbrains-logo-white.png"
          alt="Devbrains"
          className="h-8 w-auto"
        />
        <span className="mx-4 h-6 w-px bg-white/20" aria-hidden="true" />
        <span className="font-[var(--font-display)] text-sm font-medium tracking-wide text-white/80">
          {t("sme.productName")}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <LocaleSwitcher locale={locale} setLocale={setLocale} t={t} />
          <SmeUserMenu />
        </div>
      </header>
      <main className="flex min-h-0 flex-1">
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
        />
      </main>
    </div>
  )
}
