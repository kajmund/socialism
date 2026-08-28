import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { deleteReport, getReportHtml, type Report } from "@/api/reports"
import { ReportCanvas, type ReportCanvasHandle } from "@/components/reports/ReportCanvas"
import { SpinndoktorGrid } from "@/components/reports/spinndoctorGrid/SpinndoktorGrid"
import { SpinndoktorPanel } from "@/components/reports/SpinndoktorPanel"
import {
  clearSpindoctorWidgets,
  deleteSpindoctorWidget,
  listSpindoctorWidgets,
  parseSpindoctorWidget,
  updateSpindoctorWidgetPosition,
  type SpindoctorWidget,
} from "@/api/spindoctorWidgets"
import { useAuth } from "@/auth/AuthProvider"
import { AdminShell } from "@/components/layout/AdminShell"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { moduleForReport, reportModulesForUser } from "@/lib/report-modules"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"

type ReportViewMode = "report" | "spinndoctor"

const STATUS_KEY: Record<Report["status"], MessageKey> = {
  pending: "reports.status.pending",
  running: "reports.status.running",
  succeeded: "reports.status.succeeded",
  failed: "reports.status.failed",
}

function formatReportDuration(
  report: Report,
  t: (key: MessageKey, params?: Record<string, string | number>) => string,
): string | null {
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

export function ReportPage() {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { t } = useLocale()
  const { user } = useAuth()
  const isBolagReport = location.pathname.startsWith("/bolag/reports/")
  const Shell = isBolagReport ? NestedBolagPage : AdminShell
  const reportsListLabel = isBolagReport ? t("bolag.nav.reports") : t("reports.backToList")
  const { reports, status: wsStatus, connected } = useReportsRealtime()
  const report = id ? reports.find((r) => r.id === id) ?? null : null
  const reportModules = reportModulesForUser(user)
  const reportsListPath = isBolagReport
    ? "/bolag/reports"
    : report && reportModules.length > 1
      ? `/reports?tab=${moduleForReport(report)}`
      : "/reports"
  const [html, setHtml] = useState<string | null>(null)
  const [htmlError, setHtmlError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [viewMode, setViewMode] = useState<ReportViewMode>("spinndoctor")
  const [reportPanelOpen, setReportPanelOpen] = useState(false)
  const [reportFullWidth, setReportFullWidth] = useState(false)
  const [chatPanelOpen, setChatPanelOpen] = useState(true)
  const [gridWidgets, setGridWidgets] = useState<SpindoctorWidget[]>([])
  const canvasRef = useRef<ReportCanvasHandle | null>(null)

  const reportLocale: "sv" | "en" = report?.locale === "en" ? "en" : "sv"
  const spinndoktorReady = report?.status === "succeeded" && html != null && id != null

  const error =
    actionError ??
    (id && report == null && !connected && wsStatus === "closed"
      ? t("reports.loadError")
      : id && report == null && wsStatus === "open"
        ? t("reports.loadError")
        : null)

  useEffect(() => {
    if (!report || report.status !== "succeeded") {
      setHtml(null)
      setHtmlError(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const body = await getReportHtml(report.id)
        if (cancelled) return
        setHtml(body)
        setHtmlError(null)
      } catch (err) {
        if (cancelled) return
        setHtml(null)
        setHtmlError(
          err instanceof ApiError
            ? t("reports.htmlMissing")
            : t("reports.htmlLoadError"),
        )
      }
    })()
    return () => {
      cancelled = true
    }
  }, [report, t])

  useEffect(() => {
    if (viewMode === "report") {
      setReportPanelOpen(false)
      setReportFullWidth(false)
      setChatPanelOpen(true)
    }
  }, [viewMode])

  useEffect(() => {
    if (viewMode !== "spinndoctor" || !id) return
    let cancelled = false
    void listSpindoctorWidgets(id)
      .then((rows) => {
        if (cancelled) return
        setGridWidgets(
          rows
            .map((row) => parseSpindoctorWidget(row))
            .filter((row): row is SpindoctorWidget => row != null),
        )
      })
      .catch((err) => {
        if (cancelled) return
        setActionError(
          err instanceof ApiError ? err.message : t("spinndoctor.grid.boardLoadError"),
        )
      })
    return () => {
      cancelled = true
    }
  }, [viewMode, id, t])

  const handleSectionRef = useCallback((sectionId: string) => {
    setReportPanelOpen(true)
    window.setTimeout(() => {
      canvasRef.current?.scrollToSection(sectionId)
    }, 120)
  }, [])

  const handleGridWidget = useCallback((widget: SpindoctorWidget) => {
    setGridWidgets((prev) => {
      if (prev.some((row) => row.id === widget.id)) return prev
      return [...prev, widget]
    })
  }, [])

  const handleCloseWidget = useCallback(
    async (widgetId: string) => {
      if (!id) return
      try {
        await deleteSpindoctorWidget(id, widgetId)
        setGridWidgets((prev) => prev.filter((row) => row.id !== widgetId))
      } catch (err) {
        setActionError(
          err instanceof ApiError ? err.message : t("spinndoctor.grid.boardCloseError"),
        )
      }
    },
    [id, t],
  )

  const handleMoveWidget = useCallback(
    (widgetId: string, position: { x: number; y: number }) => {
      if (!id) return
      setGridWidgets((prev) =>
        prev.map((row) =>
          row.id === widgetId ? { ...row, pos_x: position.x, pos_y: position.y } : row,
        ),
      )
      void updateSpindoctorWidgetPosition(id, widgetId, position).catch((err) => {
        setActionError(
          err instanceof ApiError ? err.message : t("spinndoctor.grid.boardMoveError"),
        )
      })
    },
    [id, t],
  )

  const handleClearBoard = useCallback(async () => {
    if (!id) return
    try {
      await clearSpindoctorWidgets(id)
      setGridWidgets([])
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t("spinndoctor.grid.boardClearError"),
      )
    }
  }, [id, t])

  const handleOpenSnippet = useCallback((sectionId: string) => {
    handleSectionRef(sectionId)
  }, [handleSectionRef])

  function openInNewTab() {
    if (!html) return
    const blob = new Blob([html], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    window.open(url, "_blank", "noopener,noreferrer")
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  async function handleDelete() {
    if (!id || deleting) return
    setDeleting(true)
    try {
      await deleteReport(id)
      navigate(reportsListPath)
    } catch (err) {
      setDeleting(false)
      setConfirmDelete(false)
      setActionError(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  const duration = report ? formatReportDuration(report, t) : null

  const pageChrome = (
    <>
      <div className="section-head">
        <span className="kicker">{t("reports.kicker")}</span>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              {report?.title || t("reports.titleFallback")}
            </h1>
            <p>
              <Link to={reportsListPath}>{reportsListLabel}</Link>
              {report ? ` · ${t(STATUS_KEY[report.status])}` : null}
              {duration ? ` · ${t("reports.took", { duration })}` : null}
            </p>
          </div>
          {spinndoktorReady && viewMode === "report" ? (
            <AdminButton
              variant="secondary"
              onClick={() => setViewMode("spinndoctor")}
            >
              {t("spinndoctor.viewSpinndoktor")}
            </AdminButton>
          ) : null}
        </div>
      </div>

      {report && !isBolagReport ? (
        confirmDelete ? (
          <div
            className="confirm-row mb-4"
            style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
          >
            <button
              type="button"
              disabled={deleting}
              onClick={() => setConfirmDelete(false)}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="yes"
              disabled={deleting}
              onClick={() => void handleDelete()}
            >
              {t("common.deleteConfirm")}
            </button>
          </div>
        ) : (
          <div className="mb-4">
            <button
              type="button"
              className="danger"
              onClick={() => setConfirmDelete(true)}
            >
              {t("common.delete")}
            </button>
          </div>
        )
      ) : null}

      {error ? (
        <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
          {error}
        </div>
      ) : null}

      {report?.status === "failed" ? (
        <Card className="mb-4 gap-0 ring-1 ring-border">
          <CardContent className="px-5 py-4 text-sm text-destructive">
            {report.error || t("reports.generateFailed")}
          </CardContent>
        </Card>
      ) : null}

      {report && (report.status === "pending" || report.status === "running") ? (
        <Card className="mb-4 gap-0 ring-1 ring-border">
          <CardContent className="px-5 py-4 text-sm text-muted-foreground">
            {t("reports.generating")}
          </CardContent>
        </Card>
      ) : null}

      {htmlError ? (
        <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
          {htmlError}
        </div>
      ) : null}

      {report?.status === "succeeded" && !html && !htmlError ? (
        <Card className="mb-4 gap-0 ring-1 ring-border">
          <CardContent className="px-5 py-4 text-sm text-muted-foreground">
            {t("reports.loadingHtml")}
          </CardContent>
        </Card>
      ) : null}
    </>
  )

  if (viewMode === "spinndoctor" && id && html) {
    return (
      <Shell>
        <div className="wrap spinndoctor-page">
          <div className="spinndoctor-workspace">
            <main className="spinndoctor-workspace-grid">
              <SpinndoktorGrid
                widgets={gridWidgets}
                onOpenSnippet={handleOpenSnippet}
                onCloseWidget={(widgetId) => void handleCloseWidget(widgetId)}
                onMoveWidget={handleMoveWidget}
              />
            </main>
            <div className="spinndoctor-workspace-overlays">
              <div className="spinndoctor-workspace-grid-toolbar">
                <button
                  type="button"
                  className="spinndoctor-canvas-toggle"
                  aria-expanded={chatPanelOpen}
                  aria-controls="spinndoctor-chat-panel"
                  onClick={() => setChatPanelOpen((open) => !open)}
                >
                  {chatPanelOpen
                    ? t("spinndoctor.hideChatPanel")
                    : t("spinndoctor.showChatPanel")}
                </button>
                <button
                  type="button"
                  className="spinndoctor-canvas-toggle"
                  disabled={gridWidgets.length === 0}
                  onClick={() => void handleClearBoard()}
                >
                  {t("spinndoctor.clearBoard")}
                </button>
                {actionError ? (
                  <span className="spinndoctor-workspace-board-error" role="alert">
                    {actionError}
                  </span>
                ) : null}
                <button
                  type="button"
                  className="spinndoctor-canvas-toggle"
                  aria-expanded={reportPanelOpen}
                  aria-controls="spinndoctor-report-panel"
                  onClick={() => setReportPanelOpen((open) => !open)}
                >
                  {reportPanelOpen
                    ? t("spinndoctor.hideReportPanel")
                    : t("spinndoctor.showReportPanel")}
                </button>
              </div>
              <div className="spinndoctor-workspace-overlays-body">
                <aside
                  className={
                    "spinndoctor-workspace-chat" +
                    (chatPanelOpen ? "" : " is-collapsed")
                  }
                  id="spinndoctor-chat-panel"
                  hidden={!chatPanelOpen}
                >
                  {spinndoktorReady ? (
                    <SpinndoktorPanel
                      reportId={id}
                      locale={reportLocale}
                      onSectionRef={handleSectionRef}
                      onWidget={handleGridWidget}
                      onViewReport={() => setViewMode("report")}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {t("spinndoctor.unavailable")}
                    </p>
                  )}
                </aside>
                {reportPanelOpen ? (
                  <aside
                    className={
                      "spinndoctor-workspace-report" +
                      (reportFullWidth ? " is-full-width" : "")
                    }
                    id="spinndoctor-report-panel"
                  >
                    <div className="spinndoctor-report-toolbar">
                      <button
                        type="button"
                        className="spinndoctor-canvas-toggle"
                        aria-pressed={reportFullWidth}
                        onClick={() => setReportFullWidth((wide) => !wide)}
                      >
                        {reportFullWidth
                          ? t("reports.normalWidth")
                          : t("reports.fullWidth")}
                      </button>
                    </div>
                    <ReportCanvas
                      ref={canvasRef}
                      html={html}
                      title={report?.title || t("reports.iframeTitle")}
                    />
                  </aside>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </Shell>
    )
  }

  return (
    <Shell>
      <div className="wrap" style={{ maxWidth: reportFullWidth ? "none" : 1100 }}>
        {pageChrome}

        {report?.status === "succeeded" && html ? (
          <div className="mb-4 flex flex-wrap gap-3 text-sm">
            <button
              type="button"
              onClick={() => setReportFullWidth((wide) => !wide)}
              className="text-db-gold-700 underline-offset-2 hover:underline"
              aria-pressed={reportFullWidth}
            >
              {reportFullWidth ? t("reports.normalWidth") : t("reports.fullWidth")}
            </button>
            <button
              type="button"
              onClick={openInNewTab}
              className="text-db-gold-700 underline-offset-2 hover:underline"
            >
              {t("reports.openNewTab")}
            </button>
          </div>
        ) : null}

        {html ? (
          <iframe
            title={report?.title || t("reports.iframeTitle")}
            srcDoc={html}
            className="w-full rounded-md border border-db-ink-100 bg-white"
            style={{ minHeight: "80vh" }}
            sandbox="allow-same-origin allow-scripts allow-popups"
          />
        ) : null}
      </div>
    </Shell>
  )
}
