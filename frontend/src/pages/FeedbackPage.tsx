import { useCallback, useEffect, useState } from "react"
import {
  listFeedback,
  updateFeedback,
  type FeedbackItem,
  type FeedbackKind,
  type FeedbackStatus,
} from "@/api/feedback"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

const STATUS_KEY: Record<FeedbackStatus, MessageKey> = {
  open: "feedback.status.open",
  in_progress: "feedback.status.inProgress",
  done: "feedback.status.done",
  archived: "feedback.status.archived",
}

const KIND_KEY: Record<FeedbackKind, MessageKey> = {
  bug: "feedback.kind.bug",
  idea: "feedback.kind.idea",
  opinion: "feedback.kind.opinion",
}

function statusClass(status: FeedbackStatus): string {
  switch (status) {
    case "open":
      return "job-status pending"
    case "in_progress":
      return "job-status running"
    case "done":
      return "job-status succeeded"
    case "archived":
      return "job-status failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function formatWhen(iso: string, locale: string, emDash: string): string {
  if (!iso) return emDash
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(d)
}

function truncate(text: string, max = 160): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max - 1)}…`
}

export function FeedbackPage() {
  const { t, intl } = useLocale()
  const [items, setItems] = useState<FeedbackItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<FeedbackStatus | "">("")
  const [kindFilter, setKindFilter] = useState<FeedbackKind | "">("")
  const [showArchived, setShowArchived] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const rows = await listFeedback({
        status: statusFilter || undefined,
        kind: kindFilter || undefined,
        include_archived: showArchived || statusFilter === "archived",
        limit: 100,
      })
      setItems(rows)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("feedback.loadError"))
    } finally {
      setLoading(false)
    }
  }, [kindFilter, showArchived, statusFilter, t])

  useEffect(() => {
    setLoading(true)
    void load()
  }, [load])

  function showToast(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2400)
  }

  async function setStatus(item: FeedbackItem, status: FeedbackStatus) {
    if (busyId != null) return
    setBusyId(item.id)
    try {
      const updated = await updateFeedback(item.id, { status })
      setItems((prev) => {
        if (status === "archived" && !showArchived && statusFilter !== "archived") {
          return prev.filter((row) => row.id !== item.id)
        }
        return prev.map((row) => (row.id === item.id ? updated : row))
      })
      showToast(t("feedback.statusUpdated"))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("feedback.updateError"))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 960 }}>
        <div className="section-head">
          <span className="kicker">{t("feedback.kicker")}</span>
          <h1
            style={{
              font: "var(--text-h1)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
            }}
          >
            {t("feedback.title")}
          </h1>
          <p>{t("feedback.intro")}</p>
        </div>

        {toast ? (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {toast}
          </div>
        ) : null}

        {error ? (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        ) : null}

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            alignItems: "center",
            marginBottom: 16,
            font: "var(--text-body-sm)",
          }}
        >
          <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <span style={{ color: "var(--text-muted)" }}>{t("feedback.filterStatus")}</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as FeedbackStatus | "")}
            >
              <option value="">{t("feedback.filterAll")}</option>
              <option value="open">{t("feedback.status.open")}</option>
              <option value="in_progress">{t("feedback.status.inProgress")}</option>
              <option value="done">{t("feedback.status.done")}</option>
              <option value="archived">{t("feedback.status.archived")}</option>
            </select>
          </label>
          <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <span style={{ color: "var(--text-muted)" }}>{t("feedback.filterKind")}</span>
            <select
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value as FeedbackKind | "")}
            >
              <option value="">{t("feedback.filterAll")}</option>
              <option value="bug">{t("feedback.kind.bug")}</option>
              <option value="idea">{t("feedback.kind.idea")}</option>
              <option value="opinion">{t("feedback.kind.opinion")}</option>
            </select>
          </label>
          <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            {t("feedback.showArchived")}
          </label>
        </div>

        {loading && items.length === 0 && !error ? (
          <div className="no-match" style={{ textAlign: "left" }}>
            {t("feedback.loading")}
          </div>
        ) : null}

        {!loading && items.length === 0 && !error ? (
          <div className="no-match" style={{ textAlign: "left" }}>
            {t("feedback.empty")}
          </div>
        ) : null}

        {items.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {items.map((item) => {
              const open = expandedId === item.id
              const when = formatWhen(item.created_at, intl, t("common.emDash"))
              return (
                <Card key={item.id} className="gap-0 py-4 ring-1 ring-border">
                  <CardContent className="px-5">
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 16,
                        flexWrap: "wrap",
                        alignItems: "flex-start",
                      }}
                    >
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ font: "var(--text-body-sm)", color: "var(--text-muted)" }}>
                          {t(KIND_KEY[item.kind])} · {when}
                        </div>
                        <button
                          type="button"
                          onClick={() => setExpandedId(open ? null : item.id)}
                          style={{
                            background: "none",
                            border: "none",
                            padding: 0,
                            marginTop: 4,
                            font: "var(--text-h3)",
                            textAlign: "left",
                            cursor: "pointer",
                            color: "inherit",
                          }}
                        >
                          {item.title}
                        </button>
                        <div
                          style={{
                            marginTop: 6,
                            font: "var(--text-body-sm)",
                            color: "var(--text-muted)",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {open ? item.body || t("common.emDash") : truncate(item.body || "")}
                        </div>
                        {open && item.view_path ? (
                          <div
                            style={{
                              marginTop: 6,
                              font: "var(--text-body-sm)",
                              color: "var(--text-muted)",
                            }}
                          >
                            {t("feedback.viewPath", { path: item.view_path })}
                          </div>
                        ) : null}
                      </div>
                      <span className={statusClass(item.status)}>{t(STATUS_KEY[item.status])}</span>
                    </div>

                    <div
                      style={{
                        marginTop: 12,
                        font: "var(--text-body-sm)",
                        display: "flex",
                        gap: 8,
                        flexWrap: "wrap",
                        alignItems: "center",
                      }}
                    >
                      {item.status !== "in_progress" ? (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busyId === item.id}
                          onClick={() => void setStatus(item, "in_progress")}
                        >
                          {t("feedback.action.inProgress")}
                        </button>
                      ) : null}
                      {item.status !== "done" ? (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busyId === item.id}
                          onClick={() => void setStatus(item, "done")}
                        >
                          {t("feedback.action.done")}
                        </button>
                      ) : null}
                      {item.status !== "open" ? (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busyId === item.id}
                          onClick={() => void setStatus(item, "open")}
                        >
                          {t("feedback.action.reopen")}
                        </button>
                      ) : null}
                      {item.status !== "archived" ? (
                        <button
                          type="button"
                          className="danger"
                          disabled={busyId === item.id}
                          onClick={() => void setStatus(item, "archived")}
                        >
                          {t("feedback.action.archive")}
                        </button>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        ) : null}
      </div>
    </AdminShell>
  )
}
