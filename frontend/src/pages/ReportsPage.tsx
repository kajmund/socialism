import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  bulkDeleteReports,
  deleteReport,
  type Report,
  type ReportStatus,
} from "@/api/reports"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

const STATUS_KEY: Record<ReportStatus, MessageKey> = {
  pending: "reports.status.pending",
  running: "reports.status.running",
  succeeded: "reports.status.succeeded",
  failed: "reports.status.failed",
}

function statusClass(status: ReportStatus): string {
  switch (status) {
    case "pending":
      return "job-status pending"
    case "running":
      return "job-status running"
    case "succeeded":
      return "job-status succeeded"
    case "failed":
      return "job-status failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function formatWhen(iso: string | null | undefined, intl: string, emDash: string): string {
  if (!iso) return emDash
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(intl, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(d)
}

function formatReportDuration(report: Report, t: Translate): string | null {
  if (!report.created_at || !report.finished_at) return null
  const ms =
    new Date(report.finished_at).getTime() - new Date(report.created_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return t("reports.duration.seconds", { n: sec })
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) {
    return s > 0
      ? t("reports.duration.minutesSeconds", { m, s })
      : t("reports.duration.minutes", { m })
  }
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0
    ? t("reports.duration.hoursMinutes", { h, m: rm })
    : t("reports.duration.hours", { h })
}

function modeLabel(mode: Report["mode"], t: Translate): string {
  return mode === "quick" ? t("reports.list.modeQuick") : t("reports.list.modeFull")
}

function sourcesLabel(report: Report, t: Translate): string {
  const n = report.sources.length
  if (n === 1) {
    const label = report.sources[0]?.label?.trim()
    if (label) return label
    return t("reports.list.sourcesOne")
  }
  return t("reports.list.sourcesMany", { count: n })
}

export function ReportsPage() {
  const { t, intl } = useLocale()
  const { reports, connected, status: wsStatus } = useReportsRealtime()
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [confirmBulk, setConfirmBulk] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const loading = wsStatus === "connecting" && reports.length === 0
  const error =
    !connected && wsStatus === "closed" && reports.length === 0
      ? t("reports.list.loadError")
      : null

  useEffect(() => {
    setSelected((prev) => {
      const ids = new Set(reports.map((r) => r.id))
      const next = new Set<string>()
      for (const id of prev) {
        if (ids.has(id)) next.add(id)
      }
      return next
    })
  }, [reports])

  const allSelected = useMemo(
    () => reports.length > 0 && reports.every((r) => selected.has(r.id)),
    [reports, selected],
  )
  const selectedCount = selected.size

  function showToast(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2400)
  }

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    setConfirmBulk(false)
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(reports.map((r) => r.id)))
    }
    setConfirmBulk(false)
  }

  async function handleDelete(id: string) {
    setDeleting(true)
    try {
      await deleteReport(id)
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      setConfirmId(null)
      showToast(t("reports.list.deleted"))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    } finally {
      setDeleting(false)
    }
  }

  async function handleBulkDelete() {
    const ids = [...selected]
    if (ids.length === 0 || deleting) return
    setDeleting(true)
    try {
      const result = await bulkDeleteReports(ids)
      setSelected(new Set())
      setConfirmBulk(false)
      showToast(t("reports.list.deletedMany", { count: result.deleted_ids.length }))
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : t("common.deleteError"))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 960 }}>
        <div className="section-head">
          <span className="kicker">{t("reports.list.kicker")}</span>
          <h1
            style={{
              font: "var(--text-h1)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
            }}
          >
            {t("reports.list.title")}
          </h1>
          <p>{t("reports.list.intro")}</p>
        </div>

        {toast ? (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {toast}
          </div>
        ) : null}

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        {loading && reports.length === 0 && !error ? (
          <div className="no-match" style={{ textAlign: "left" }}>
            {t("reports.list.loading")}
          </div>
        ) : null}

        {!loading && reports.length === 0 && !error ? (
          <div className="no-match" style={{ textAlign: "left" }}>
            {t("reports.list.empty")}
          </div>
        ) : null}

        {reports.length > 0 ? (
          <>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 12,
                alignItems: "center",
                marginBottom: 12,
                font: "var(--text-body-sm)",
              }}
            >
              <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label={t("reports.list.selectAll")}
                />
                {t("reports.list.selectAll")}
              </label>
              {selectedCount > 0 ? (
                <span style={{ color: "var(--text-muted)" }}>
                  {t("reports.list.selectedCount", { count: selectedCount })}
                </span>
              ) : null}
              {selectedCount > 0 && !confirmBulk ? (
                <button
                  type="button"
                  className="danger"
                  disabled={deleting}
                  onClick={() => {
                    setConfirmId(null)
                    setConfirmBulk(true)
                  }}
                >
                  {t("reports.list.deleteSelected")}
                </button>
              ) : null}
              {confirmBulk ? (
                <div className="confirm-row" style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    disabled={deleting}
                    onClick={() => setConfirmBulk(false)}
                  >
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="yes"
                    disabled={deleting}
                    onClick={() => void handleBulkDelete()}
                  >
                    {t("reports.list.deleteSelectedConfirm", { count: selectedCount })}
                  </button>
                </div>
              ) : null}
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {reports.map((report) => {
                const duration = formatReportDuration(report, t)
                const when = formatWhen(
                  report.finished_at ?? report.created_at,
                  intl,
                  t("common.emDash"),
                )
                const confirming = confirmId === report.id
                const isSelected = selected.has(report.id)
                return (
                  <Card key={report.id} className="gap-0 py-4 ring-1 ring-border">
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
                        <div style={{ display: "flex", gap: 12, minWidth: 0, flex: 1 }}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleOne(report.id)}
                            aria-label={t("reports.list.selectOne", {
                              title: report.title || t("reports.titleFallback"),
                            })}
                            style={{ marginTop: 6 }}
                          />
                          <div style={{ minWidth: 0 }}>
                            <div style={{ font: "var(--text-h3)", marginBottom: 4 }}>
                              {report.title || t("reports.titleFallback")}
                            </div>
                            <div
                              style={{
                                font: "var(--text-body-sm)",
                                color: "var(--text-muted)",
                              }}
                            >
                              {modeLabel(report.mode, t)} · {sourcesLabel(report, t)} ·{" "}
                              {t("reports.list.created", { when })}
                              {duration ? ` · ${t("reports.took", { duration })}` : null}
                            </div>
                          </div>
                        </div>
                        <span className={statusClass(report.status)}>
                          {t(STATUS_KEY[report.status])}
                        </span>
                      </div>

                      {report.status === "failed" && report.error ? (
                        <div
                          style={{
                            marginTop: 12,
                            font: "var(--text-body-sm)",
                            color: "var(--db-error)",
                          }}
                        >
                          {report.error}
                        </div>
                      ) : null}

                      {confirming ? (
                        <div
                          className="confirm-row"
                          style={{ marginTop: 12, display: "flex", gap: 8 }}
                        >
                          <button
                            type="button"
                            disabled={deleting}
                            onClick={() => setConfirmId(null)}
                          >
                            {t("common.cancel")}
                          </button>
                          <button
                            type="button"
                            className="yes"
                            disabled={deleting}
                            onClick={() => void handleDelete(report.id)}
                          >
                            {t("common.deleteConfirm")}
                          </button>
                        </div>
                      ) : (
                        <div
                          style={{
                            marginTop: 12,
                            font: "var(--text-body-sm)",
                            display: "flex",
                            gap: 16,
                            flexWrap: "wrap",
                            alignItems: "center",
                          }}
                        >
                          <Link to={`/reports/${report.id}`}>{t("reports.list.open")}</Link>
                          <button
                            type="button"
                            className="danger"
                            disabled={deleting}
                            onClick={() => {
                              setConfirmBulk(false)
                              setConfirmId(report.id)
                            }}
                          >
                            {t("common.delete")}
                          </button>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </>
        ) : null}
      </div>
    </AdminShell>
  )
}
