import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deleteMessage, listMessages, type Message, type MessageType } from "@/api/messages"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { formatLibraryDate } from "@/data/library"
import { ApiError } from "@/lib/api"

const TYPE_LABEL: Record<MessageType, string> = {
  post: "Post",
  news: "Nyhet",
}

const VARIANT_LABEL: Record<string, string> = {
  analytical: "Analytisk",
  narrative: "Berättande",
  concise: "Koncis",
}

function variantFromMeta(meta: Record<string, unknown>): string | null {
  const v = meta.variant
  if (typeof v !== "string") return null
  return VARIANT_LABEL[v] ?? v
}

type MsgCardProps = {
  msg: Message
  onDelete: (id: string) => void
}

function MsgCard({ msg, onDelete }: MsgCardProps) {
  const [confirming, setConfirming] = useState(false)
  const variant = variantFromMeta(msg.metadata)
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{msg.title}</div>
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {TYPE_LABEL[msg.type]}
            </span>
          </div>
          <div className="meta-line">
            Skapad {formatLibraryDate(msg.created_at)}
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
                Avbryt
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(msg.id)}
              >
                Ta bort?
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                Ta bort
              </button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function MessagesPage() {
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
          setError(err instanceof ApiError ? err.message : "Kunde inte hämta budskap")
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
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
      setToast("Budskapet togs bort")
    } catch (err: unknown) {
      setToast(err instanceof ApiError ? err.message : "Kunde inte ta bort")
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>Budskap</h1>
            <p className="muted">
              Bibliotek med sparade poster och nyheter för körningskonfiguration.
            </p>
          </div>
        </div>

        <div className="controls-row">
          <input
            className="dsearch"
            placeholder="Sök titel eller innehåll…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="dsel"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as "" | MessageType)}
          >
            <option value="">Alla typer</option>
            <option value="post">Post</option>
            <option value="news">Nyhet</option>
          </select>
          <Link className="admin-cta" to="/messages/new">
            + Ny i verkstaden
          </Link>
        </div>

        {loading && <p className="muted">Hämtar budskap…</p>}
        {error && <p className="text-destructive">{error}</p>}
        {!loading && !error && filtered.length === 0 && (
          <div className="empty-state">
            <p>Inga budskap ännu.</p>
            <Link className="admin-cta" to="/messages/new">
              Öppna budskapsverkstaden
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
