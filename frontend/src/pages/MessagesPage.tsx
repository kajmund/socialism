import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deleteMessage, listMessages, type Message, type MessageType } from "@/api/messages"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { formatLibraryDate } from "@/data/library"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: TranslateParams) => string

function typeLabel(type: MessageType, t: Translate): string {
  switch (type) {
    case "post":
      return t("messages.list.typePost")
    case "news":
      return t("messages.list.typeNews")
    default: {
      const exhaustive: never = type
      return exhaustive
    }
  }
}

const VARIANT_KEY: Record<string, MessageKey> = {
  analytical: "messages.list.variantAnalytical",
  narrative: "messages.list.variantNarrative",
  concise: "messages.list.variantConcise",
}

function variantFromMeta(meta: Record<string, unknown>, t: Translate): string | null {
  const v = meta.variant
  if (typeof v !== "string") return null
  const key = VARIANT_KEY[v]
  return key ? t(key) : v
}

type MsgCardProps = {
  msg: Message
  onDelete: (id: string) => void
}

function MsgCard({ msg, onDelete }: MsgCardProps) {
  const { t } = useLocale()
  const [confirming, setConfirming] = useState(false)
  const variant = variantFromMeta(msg.metadata, t)
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{msg.title}</div>
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {typeLabel(msg.type, t)}
            </span>
          </div>
          <div className="meta-line">
            {t("messages.list.createdOn", { date: formatLibraryDate(msg.created_at) })}
            {variant ? ` · ${variant}` : ""}
          </div>
          <p className="mt-2 line-clamp-3 text-sm text-muted-foreground whitespace-pre-wrap">
            {msg.body}
          </p>
          {msg.source_url && (
            <div className="usage-row mt-2">
              <span className="unused truncate" title={msg.source_url}>
                {msg.source_url}
              </span>
            </div>
          )}
          {confirming ? (
            <div className="confirm-row" style={{ marginTop: "auto" }}>
              <button type="button" style={{ flex: 1 }} onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(msg.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/messages/${msg.id}/edit`}>
                {t("messages.list.edit")}
              </Link>
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                {t("common.delete")}
              </button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function MessagesPage() {
  const { t } = useLocale()
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [typeFilter, setTypeFilter] = useState<"" | MessageType>("")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listMessages(typeFilter ? { type: typeFilter } : undefined)
      .then((data) => {
        if (!cancelled) {
          setMessages(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("messages.list.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(t)
  }, [toast])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return messages
    return messages.filter(
      (m) =>
        m.title.toLowerCase().includes(q) || m.body.toLowerCase().includes(q),
    )
  }, [messages, query])

  async function onDelete(id: string) {
    try {
      await deleteMessage(id)
      setMessages((prev) => prev.filter((m) => m.id !== id))
      setToast(t("messages.list.deleted"))
    } catch (err: unknown) {
      setToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>{t("messages.list.title")}</h1>
            <p className="muted">{t("messages.list.intro")}</p>
          </div>
        </div>

        <div className="controls-row">
          <div className="controls-left">
            <input
              className="dsearch"
              placeholder={t("messages.list.searchPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              className="dsel"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as "" | MessageType)}
            >
              <option value="">{t("messages.list.allTypes")}</option>
              <option value="post">{t("messages.list.typePost")}</option>
              <option value="news">{t("messages.list.typeNews")}</option>
            </select>
          </div>
          <Link
            to="/messages/new"
            className="admin-cta inline-flex h-9 shrink-0 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
          >
            {t("messages.list.newInWorkshop")}
          </Link>
        </div>

        {loading && <p className="muted">{t("messages.list.loading")}</p>}
        {error && <p className="text-destructive">{error}</p>}
        {!loading && !error && filtered.length === 0 && (
          <div className="empty-state">
            <p>{t("messages.list.empty")}</p>
            <Link
              to="/messages/new"
              className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
            >
              {t("messages.list.openWorkshop")}
            </Link>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((msg) => (
            <MsgCard key={msg.id} msg={msg} onDelete={onDelete} />
          ))}
        </div>
      </div>
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-md bg-db-ink-950 px-4 py-2 text-sm text-db-ink-0">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
