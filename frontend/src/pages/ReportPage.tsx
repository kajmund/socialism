import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { deleteReport, getReport, getReportHtml, type Report } from "@/api/reports"
import { getJob, type Job } from "@/api/jobs"
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
import { formatElapsed } from "@/lib/formatDuration"
import { moduleForReport, reportModulesForUser } from "@/lib/report-modules"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"

type ReportViewMode = "report" | "spinndoctor"

function ReportShell({
  embedded,
  isBolagReport,
  children,
}: {
  embedded: boolean
  isBolagReport: boolean
  children: ReactNode
}) {
  if (embedded) return children
  if (isBolagReport) return <NestedBolagPage>{children}</NestedBolagPage>
  return <AdminShell>{children}</AdminShell>
}

const STATUS_KEY: Record<Report["status"], MessageKey> = {
  pending: "reports.status.pending",
  running: "reports.status.running",
  succeeded: "reports.status.succeeded",
  failed: "reports.status.failed",
}

function formatReportDuration(
  report: Report,
  job: Job | undefined,
  t: (key: MessageKey, params?: Record<string, string | number>) => string,
): string | null {
  if (report.job_id && !job) return null
  const start = job?.started_at ?? job?.created_at ?? report.created_at
  const end = job?.finished_at ?? report.finished_at
  return formatElapsed(start, end, t, "reports.duration")
}

export function ReportPage({
  reportId,
  embedded = false,
  initialViewMode = "spinndoctor",
}: {
  reportId?: string
  embedded?: boolean
  initialViewMode?: ReportViewMode
} = {}) {
  const { id: idFromRoute } = useParams<{ id: string }>()
  const id = reportId ?? idFromRoute
  const location = useLocation()
  const navigate = useNavigate()
  const { t } = useLocale()
  const { user } = useAuth()
  const { jobs } = useJobsRealtime()
  const isBolagReport = embedded || location.pathname.startsWith("/bolag/reports/")
  const reportsListLabel = isBolagReport ? t("bolag.nav.reports") : t("reports.backToList")
  const { reports } = useReportsRealtime()
  const [fetchedReport, setFetchedReport] = useState<Report | null>(null)
  const [reportMissing, setReportMissing] = useState(false)
  const [fetchedJob, setFetchedJob] = useState<Job | undefined>(undefined)
  const wsReport = id ? reports.find((r) => r.id === id) ?? null : null
  const report = wsReport ?? fetchedReport
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
  const [viewMode, setViewMode] = useState<ReportViewMode>(initialViewMode)
  const [reportPanelOpen, setReportPanelOpen] = useState(false)
  const [reportFullWidth, setReportFullWidth] = useState(false)
  const [chatPanelOpen, setChatPanelOpen] = useState(true)
  const [gridWidgets, setGridWidgets] = useState<SpindoctorWidget[]>([])
  const canvasRef = useRef<ReportCanvasHandle | null>(null)

  const reportLocale: "sv" | "en" = report?.locale === "en" ? "en" : "sv"
  const spinndoktorReady = report?.status === "succeeded" && html != null && id != null

  const error =
    actionError ?? (id && report == null && reportMissing ? t("reports.loadError") : null)

  useEffect(() => {
    if (!id) {
      setFetchedReport(null)
      setReportMissing(false)
      return
    }
    let cancelled = false
    setReportMissing(false)
    void getReport(id)
      .then((row) => {
        if (cancelled) return
        setFetchedReport(row)
        setReportMissing(false)
      })
      .catch(() => {
        if (cancelled) return
        setFetchedReport(null)
        setReportMissing(true)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  useEffect(() => {
    const jobId = report?.job_id
    if (!jobId) {
      setFetchedJob(undefined)
      return
    }
    const fromList = jobs.find((row) => row.id === jobId)
    if (fromList) {
      setFetchedJob(fromList)
      return
    }
    let cancelled = false
    void getJob(jobId)
      .then((row) => {
        if (!cancelled) setFetchedJob(row)
      })
      .catch(() => {
        if (!cancelled) setFetchedJob(undefined)
      })
    return () => {
      cancelled = true
    }
  }, [jobs, report?.job_id])

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

  const duration = report ? formatReportDuration(report, fetchedJob, t) : null

  const pageChrome = (
    <>
      {embedded ? null : (
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
      )}

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

      {id && !report && !error ? (
        <Card className="mb-4 gap-0 ring-1 ring-border">
          <CardContent className="px-5 py-4 text-sm text-muted-foreground">
            {t("reports.loadingHtml")}
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
      <ReportShell embedded={embedded} isBolagReport={isBolagReport}>
        <div className={"wrap spinndoctor-page" + (embedded ? " is-embedded" : "")}>
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
      </ReportShell>
    )
  }

  return (
    <ReportShell embedded={embedded} isBolagReport={isBolagReport}>
      <div
        className={embedded ? undefined : "wrap"}
        style={embedded ? undefined : { maxWidth: reportFullWidth ? "none" : 1100 }}
      >
        {pageChrome}

        {!embedded && report?.status === "succeeded" && html ? (
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
            className={
              embedded
                ? "dd-run-results-report w-full bg-white"
                : "w-full rounded-md border border-db-ink-100 bg-white"
            }
            style={{ minHeight: embedded ? "calc(100vh - 140px)" : "80vh" }}
            sandbox="allow-same-origin allow-scripts allow-popups"
          />
        ) : null}
      </div>
    </ReportShell>
  )
}
