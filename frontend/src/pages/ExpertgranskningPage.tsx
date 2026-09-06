import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react"
import { Link, Navigate } from "react-router-dom"
import {
  deleteExpertgranskningSession,
  listExpertgranskningSessions,
  type ExpertgranskningSessionStatus,
  type ExpertgranskningSessionSummary,
} from "@/api/expertgranskning"
import { useAuth } from "@/auth/AuthProvider"
import { AdminShell } from "@/components/layout/AdminShell"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { formatLibraryDate } from "@/data/library"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type ShellComponent = ComponentType<{ children: ReactNode }>
type Translate = (key: MessageKey, params?: Record<string, string | number>) => string
type ListStatus = "all" | "draft" | "running" | "done" | "failed"

function expertgranskningBase(bolag: boolean): string {
  return bolag ? "/bolag/expertgranskning" : "/expertgranskning"
}

function toListStatus(status: ExpertgranskningSessionStatus): Exclude<ListStatus, "all"> {
  switch (status) {
    case "draft":
      return "draft"
    case "pending":
    case "running":
      return "running"
    case "succeeded":
      return "done"
    case "failed":
      return "failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function statusLabel(status: Exclude<ListStatus, "all">, t: Translate): string {
  switch (status) {
    case "done":
      return t("runs.status.done")
    case "running":
      return t("runs.status.running")
    case "draft":
      return t("runs.status.draft")
    case "failed":
      return t("runs.status.failed")
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function primaryResultsLabel(status: Exclude<ListStatus, "all">, t: Translate): string {
  switch (status) {
    case "running":
      return t("runs.list.seeStatus")
    case "failed":
      return t("runs.list.seeError")
    default:
      return t("runs.list.openResults")
  }
}

type RowProps = {
  row: ExpertgranskningSessionSummary
  base: string
  intl: string
  t: Translate
  confirming: boolean
  onAskDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}

function SessionActions({
  row,
  base,
  t,
  confirming,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: Omit<RowProps, "intl">) {
  const listStatus = toListStatus(row.status)
  if (confirming) {
    return (
      <>
        <button type="button" onClick={onCancelDelete}>
          {t("common.cancel")}
        </button>
        <button type="button" className="yes" onClick={onConfirmDelete}>
          {t("common.deleteConfirm")}
        </button>
      </>
    )
  }
  if (listStatus === "draft") {
    return (
      <>
        <Link className="primary full" to={`${base}/${row.id}?tab=config`}>
          {t("runs.list.continueConfig")}
        </Link>
        <button type="button" onClick={onAskDelete}>
          {t("common.delete")}
        </button>
      </>
    )
  }
  return (
    <>
      <Link className="primary" to={`${base}/${row.id}?tab=results`}>
        {primaryResultsLabel(listStatus, t)}
      </Link>
      <Link to={`${base}/${row.id}?tab=config`}>{t("runs.list.configuration")}</Link>
      <button type="button" onClick={onAskDelete}>
        {t("common.delete")}
      </button>
    </>
  )
}

function SessionCard(props: RowProps) {
  const { row, intl, t, confirming } = props
  const listStatus = toListStatus(row.status)
  return (
    <div className="run-card">
      <Card className="relative h-full gap-0 rounded-[var(--radius-md)] py-4">
        <span className={"status-tag absolute right-4 top-4 " + listStatus}>
          {statusLabel(listStatus, t)}
        </span>
        <CardContent className="run-inner px-4">
          <div className="run-top">
            <div className="run-nm">{row.topic}</div>
          </div>
          <div className="run-meta">
            {t("expertgranskning.list.panel")}{" "}
            <b>{row.panel_name || t("common.emDash")}</b>
          </div>
          <div className="run-details">
            <div className="row">
              <span>{t("runs.list.updated")}</span>
              <span className="v">{formatLibraryDate(row.updated_at, intl)}</span>
            </div>
          </div>
          <div className={confirming ? "confirm-row" : "run-actions"}>
            <SessionActions {...props} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function SessionListRow(props: RowProps) {
  const { row, intl, t, confirming } = props
  const listStatus = toListStatus(row.status)
  return (
    <div className="admin-list-row admin-list-runs">
      <div>
        <div className="nm">{row.topic}</div>
        <div className="meta">{row.panel_name || t("common.emDash")}</div>
      </div>
      <span className={"status-tag " + listStatus}>{statusLabel(listStatus, t)}</span>
      <div className="cell">{formatLibraryDate(row.updated_at, intl)}</div>
      <div className={confirming ? "confirm-row" : "admin-list-actions"}>
        <SessionActions {...props} />
      </div>
    </div>
  )
}

export function ExpertgranskningPage({
  Shell = AdminShell,
  redirectBolag = true,
  bolag = false,
}: {
  Shell?: ShellComponent
  redirectBolag?: boolean
  bolag?: boolean
} = {}) {
  const { t, intl } = useLocale()
  const { role, hasModule } = useAuth()
  const base = expertgranskningBase(bolag)

  const [rows, setRows] = useState<ExpertgranskningSessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<ListStatus>("all")
  const [view, setView] = useState<ListViewMode>("grid")
  const [toast, setToast] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listExpertgranskningSessions()
      .then((data) => {
        if (cancelled) return
        setRows(data)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("expertgranskning.list.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((row) => {
      const listStatus = toListStatus(row.status)
      if (status !== "all" && listStatus !== status) return false
      if (!q) return true
      const haystack = `${row.topic} ${row.panel_name ?? ""}`.toLowerCase()
      return haystack.includes(q)
    })
  }, [query, rows, status])

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2400)
  }

  async function handleDelete(id: string) {
    try {
      await deleteExpertgranskningSession(id)
      setRows((prev) => prev.filter((row) => row.id !== id))
      setConfirmId(null)
      showToast(t("expertgranskning.list.deleted"))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  if (redirectBolag && role === "bolag" && hasModule("dd")) {
    return <Navigate to="/bolag/expertgranskning" replace />
  }

  return (
    <Shell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>{t("expertgranskning.list.title")}</h1>
            <p>{t("expertgranskning.list.intro")}</p>
          </div>
        </div>

        {error ? (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        ) : null}

        <div className="controls-row">
          <div className="controls-left">
            <input
              className="dsearch"
              placeholder={t("expertgranskning.list.searchPlaceholder")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <select
              className="dsel"
              value={status}
              onChange={(event) => setStatus(event.target.value as ListStatus)}
            >
              <option value="all">{t("runs.list.statusAll")}</option>
              <option value="done">{t("runs.list.statusDone")}</option>
              <option value="running">{t("runs.list.statusRunning")}</option>
              <option value="draft">{t("runs.list.statusDraft")}</option>
              <option value="failed">{t("runs.list.statusFailed")}</option>
            </select>
          </div>
          <div className="controls-right">
            <ViewToggle value={view} onChange={setView} />
            <Link
              to={`${base}/new`}
              className="admin-cta inline-flex h-9 items-center rounded-[var(--radius-md)] bg-db-black px-[18px] text-[0.85rem] text-db-ink-0 no-underline hover:bg-db-ink-800"
            >
              {t("expertgranskning.list.newRun")}
            </Link>
          </div>
        </div>

        {loading ? (
          <div className="no-match">{t("expertgranskning.list.loading")}</div>
        ) : list.length === 0 ? (
          <div className="no-match">{t("expertgranskning.list.emptyFilter")}</div>
        ) : view === "grid" ? (
          <div className="run-grid">
            {list.map((row) => (
              <SessionCard
                key={row.id}
                row={row}
                base={base}
                intl={intl}
                t={t}
                confirming={confirmId === row.id}
                onAskDelete={() => setConfirmId(row.id)}
                onCancelDelete={() => setConfirmId(null)}
                onConfirmDelete={() => void handleDelete(row.id)}
              />
            ))}
          </div>
        ) : (
          <div className="admin-list-stack">
            {list.map((row) => (
              <SessionListRow
                key={row.id}
                row={row}
                base={base}
                intl={intl}
                t={t}
                confirming={confirmId === row.id}
                onAskDelete={() => setConfirmId(row.id)}
                onCancelDelete={() => setConfirmId(null)}
                onConfirmDelete={() => void handleDelete(row.id)}
              />
            ))}
          </div>
        )}
      </div>

      {toast ? (
        <div className="fixed bottom-6 right-6 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      ) : null}
    </Shell>
  )
}

export function BolagExpertgranskningPage() {
  return <ExpertgranskningPage Shell={NestedBolagPage} redirectBolag={false} bolag />
}
