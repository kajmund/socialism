import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getReport, getReportHtml, type Report } from "@/api/reports"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

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
  const { t } = useLocale()
  const [report, setReport] = useState<Report | null>(null)
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [htmlError, setHtmlError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    let timer: number | undefined

    async function load() {
      try {
        const row = await getReport(id!)
        if (cancelled) return
        setReport(row)
        setError(null)
        if (row.status === "pending" || row.status === "running") {
          timer = window.setTimeout(load, 2000)
        }
      } catch (err) {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("reports.loadError"))
        timer = window.setTimeout(load, 5000)
      }
    }

    void load()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [id, t])

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

  function openInNewTab() {
    if (!html) return
    const blob = new Blob([html], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    window.open(url, "_blank", "noopener,noreferrer")
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  const duration = report ? formatReportDuration(report, t) : null

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 1100 }}>
        <div className="section-head">
          <span className="kicker">{t("reports.kicker")}</span>
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
            <Link to="/jobs">{t("reports.backToJobs")}</Link>
            {report ? ` · ${t(STATUS_KEY[report.status])}` : null}
            {duration ? ` · ${t("reports.took", { duration })}` : null}
          </p>
        </div>

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

        {report?.status === "succeeded" && html ? (
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

        {html ? (
          <iframe
            title={report?.title || t("reports.iframeTitle")}
            srcDoc={html}
            className="w-full rounded-md border border-border bg-white"
            style={{ minHeight: "80vh" }}
            sandbox="allow-same-origin allow-scripts allow-popups"
          />
        ) : null}
      </div>
    </AdminShell>
  )
}
