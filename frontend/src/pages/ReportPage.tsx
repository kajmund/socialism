import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { deleteReport, getReportHtml, type Report } from "@/api/reports"
import { ReportCanvas, type ReportCanvasHandle } from "@/components/reports/ReportCanvas"
import { ReportVerdictCalibrationPanel } from "@/components/reports/ReportVerdictCalibrationPanel"
import { SpinndoktorPanel } from "@/components/reports/SpinndoktorPanel"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
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
  const navigate = useNavigate()
  const { t, locale } = useLocale()
  const { reports, status: wsStatus, connected } = useReportsRealtime()
  const report = id ? reports.find((r) => r.id === id) ?? null : null
  const [html, setHtml] = useState<string | null>(null)
  const [htmlError, setHtmlError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [viewMode, setViewMode] = useState<ReportViewMode>("report")
  const [canvasOpen, setCanvasOpen] = useState(false)
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
      setCanvasOpen(false)
    }
  }, [viewMode])

  const handleSectionRef = useCallback((sectionId: string) => {
    setCanvasOpen(true)
    window.setTimeout(() => {
      canvasRef.current?.scrollToSection(sectionId)
    }, 120)
  }, [])

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
      navigate("/reports")
    } catch (err) {
      setDeleting(false)
      setConfirmDelete(false)
      setActionError(err instanceof ApiError ? err.message : t("common.deleteError"))
    }
  }

  const duration = report ? formatReportDuration(report, t) : null

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: viewMode === "spinndoctor" ? 1400 : 1100 }}>
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
                <Link to="/reports">{t("reports.backToList")}</Link>
                {report ? ` · ${t(STATUS_KEY[report.status])}` : null}
                {duration ? ` · ${t("reports.took", { duration })}` : null}
              </p>
            </div>
            {spinndoktorReady ? (
              <div className="spinndoctor-view-toggle" role="tablist" aria-label={t("spinndoctor.title")}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={viewMode === "report"}
                  className={viewMode === "report" ? "active" : undefined}
                  onClick={() => setViewMode("report")}
                >
                  {t("spinndoctor.viewReport")}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={viewMode === "spinndoctor"}
                  className={viewMode === "spinndoctor" ? "active" : undefined}
                  onClick={() => setViewMode("spinndoctor")}
                >
                  {t("spinndoctor.viewSpinndoktor")}
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {report ? (
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

        {viewMode === "report" && report?.status === "succeeded" && html ? (
          <div className="mb-4 flex flex-wrap gap-3 text-sm">
            <button
              type="button"
              onClick={openInNewTab}
              className="text-db-gold-700 underline-offset-2 hover:underline"
            >
              {t("reports.openNewTab")}
            </button>
          </div>
        ) : null}

        {viewMode === "report" && report?.status === "succeeded" && id ? (
          <ReportVerdictCalibrationPanel reportId={id} />
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

        {viewMode === "report" && html ? (
          <iframe
            title={report?.title || t("reports.iframeTitle")}
            srcDoc={html}
            className="w-full rounded-md border border-db-ink-100 bg-white"
            style={{ minHeight: "80vh" }}
            sandbox="allow-same-origin allow-scripts allow-popups"
          />
        ) : null}

        {viewMode === "spinndoctor" && id && html ? (
          <div className={`spinndoctor-layout${canvasOpen ? " spinndoctor-layout--canvas-open" : ""}`}>
            <div className="spinndoctor-layout-chat">
              {spinndoktorReady ? (
                <>
                  <div className="spinndoctor-layout-toolbar">
                    <button
                      type="button"
                      className="spinndoctor-canvas-toggle"
                      aria-expanded={canvasOpen}
                      aria-controls="spinndoctor-canvas"
                      onClick={() => setCanvasOpen((open) => !open)}
                    >
                      {canvasOpen ? t("spinndoctor.hideCanvas") : t("spinndoctor.toggleCanvas")}
                    </button>
                  </div>
                  <SpinndoktorPanel
                    reportId={id}
                    locale={reportLocale}
                    onSectionRef={handleSectionRef}
                  />
                </>
              ) : (
                <p className="text-sm text-muted-foreground">{t("spinndoctor.unavailable")}</p>
              )}
            </div>
            {canvasOpen && html ? (
              <div className="spinndoctor-layout-canvas" id="spinndoctor-canvas">
                <ReportCanvas
                  ref={canvasRef}
                  html={html}
                  title={report?.title || t("reports.iframeTitle")}
                />
              </div>
            ) : null}
          </div>
        ) : null}

        {viewMode === "spinndoctor" && spinndoktorReady && id ? (
          <div className="mt-4">
            <ReportVerdictCalibrationPanel reportId={id} />
          </div>
        ) : null}
      </div>
    </AdminShell>
  )
}
