import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getReport, getReportHtml, type Report } from "@/api/reports"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { ApiError } from "@/lib/api"

const STATUS_LABEL: Record<Report["status"], string> = {
  pending: "Väntar",
  running: "Genererar",
  succeeded: "Klar",
  failed: "Misslyckades",
}

function formatReportDuration(report: Report): string | null {
  if (!report.created_at || !report.finished_at) return null
  const ms =
    new Date(report.finished_at).getTime() - new Date(report.created_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec} s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return s > 0 ? `${m} min ${s} s` : `${m} min`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h} h ${rm} min` : `${h} h`
}

export function ReportPage() {
  const { id } = useParams<{ id: string }>()
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
        setError(err instanceof ApiError ? err.message : "Kunde inte hämta rapport")
        timer = window.setTimeout(load, 5000)
      }
    }

    void load()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [id])

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
          err instanceof ApiError ? err.message : "Kunde inte ladda rapport-HTML",
        )
      }
    })()
    return () => {
      cancelled = true
    }
  }, [report])

  function openInNewTab() {
    if (!html) return
    const blob = new Blob([html], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    window.open(url, "_blank", "noopener,noreferrer")
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 1100 }}>
        <div className="section-head">
          <span className="kicker">Rapport</span>
          <h1
            style={{
              font: "var(--text-h1)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
            }}
          >
            {report?.title || "Simuleringsrapport"}
          </h1>
          <p>
            <Link to="/jobs">← Bakgrundsjobb</Link>
            {report ? ` · ${STATUS_LABEL[report.status]}` : null}
            {report && formatReportDuration(report)
              ? ` · tog ${formatReportDuration(report)}`
              : null}
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
              {report.error || "Rapportgenereringen misslyckades."}
            </CardContent>
          </Card>
        ) : null}

        {report && (report.status === "pending" || report.status === "running") ? (
          <Card className="mb-4 gap-0 ring-1 ring-border">
            <CardContent className="px-5 py-4 text-sm text-muted-foreground">
              Rapporten genereras… Det kan ta några minuter.
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
              Öppna i ny flik →
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
              Laddar rapport…
            </CardContent>
          </Card>
        ) : null}

        {html ? (
          <iframe
            title={report?.title || "Rapport"}
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
