import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { listJobs, type Job, type JobStatus } from "@/api/jobs"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { ApiError } from "@/lib/api"

const STATUS_LABEL: Record<JobStatus, string> = {
  pending: "Väntar",
  running: "Kör",
  succeeded: "Klar",
  failed: "Misslyckades",
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat("sv-SE", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(d)
}

/** Wall-clock duration from started→finished (falls back to created→finished). */
function formatJobDuration(job: Job): string | null {
  const startIso = job.started_at ?? job.created_at
  const endIso = job.finished_at
  if (!startIso || !endIso) return null
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
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

function statusClass(status: JobStatus): string {
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

export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    async function load() {
      try {
        const rows = await listJobs({ limit: 50 })
        if (cancelled) return
        setJobs(rows)
        setError(null)
        const active = rows.some((j) => j.status === "pending" || j.status === "running")
        timer = window.setTimeout(load, active ? 2000 : 8000)
      } catch (err) {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Kunde inte hämta jobb")
        timer = window.setTimeout(load, 8000)
      }
    }

    void load()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [])

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 960 }}>
        <div className="section-head">
          <span className="kicker">Bakgrundsjobb</span>
          <h1
            style={{
              font: "var(--text-h1)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
            }}
          >
            Jobb
          </h1>
          <p>Generering och andra långa körningar utan tidsbegränsning i webbläsaren.</p>
        </div>

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        {jobs.length === 0 && !error ? (
          <div className="no-match" style={{ textAlign: "left" }}>
            Inga bakgrundsjobb ännu.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {jobs.map((job) => {
              const popId = job.result?.population_id
              const runId =
                job.result?.run_id ??
                (typeof job.request.run_id === "number" ? job.request.run_id : null)
              const reportId =
                job.result?.report_id ??
                (typeof job.request.report_id === "string"
                  ? job.request.report_id
                  : null)
              const kindLabel =
                job.kind === "population_generate"
                  ? "Populationsgenerering"
                  : job.kind === "run_simulate"
                    ? "Simulering"
                    : job.kind === "report_generate"
                      ? "Rapport"
                      : job.kind
              const duration = formatJobDuration(job)
              return (
                <Card key={job.id} className="gap-0 py-4 ring-1 ring-border">
                  <CardContent className="px-5">
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 16,
                        flexWrap: "wrap",
                        alignItems: "baseline",
                      }}
                    >
                      <div>
                        <div style={{ font: "var(--text-h3)", marginBottom: 4 }}>
                          {job.label || job.id}
                        </div>
                        <div style={{ font: "var(--text-body-sm)", color: "var(--text-muted)" }}>
                          {kindLabel} · skapad {formatWhen(job.created_at)}
                          {duration ? ` · tog ${duration}` : null}
                        </div>
                      </div>
                      <span className={statusClass(job.status)}>
                        {STATUS_LABEL[job.status]}
                      </span>
                    </div>

                    {job.status === "succeeded" && popId != null && (
                      <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
                        {job.result?.member_count ?? "?"} personas ·{" "}
                        <Link to={`/populations/${popId}`}>Öppna population →</Link>
                        {Array.isArray(job.result?.warnings) &&
                        job.result.warnings.length > 0 ? (
                          <ul
                            className="mt-2 list-disc pl-5 text-amber-800 dark:text-amber-200"
                            style={{ font: "var(--text-body-sm)" }}
                          >
                            {job.result.warnings.map((w: string) => (
                              <li key={w}>{w}</li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    )}
                    {job.status === "succeeded" &&
                      job.kind === "run_simulate" &&
                      runId != null && (
                        <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
                          <Link to={`/runs/${runId}/edit?tab=results`}>
                            Öppna resultat →
                          </Link>
                        </div>
                      )}
                    {job.status === "succeeded" &&
                      job.kind === "report_generate" &&
                      reportId != null && (
                        <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
                          <Link to={`/reports/${reportId}`}>Öppna rapport →</Link>
                        </div>
                      )}
                    {job.status === "failed" && job.error && (
                      <div
                        style={{
                          marginTop: 12,
                          font: "var(--text-body-sm)",
                          color: "var(--db-error)",
                        }}
                      >
                        {job.error}
                      </div>
                    )}
                    {(job.status === "pending" || job.status === "running") && (
                      <div
                        style={{
                          marginTop: 12,
                          font: "var(--text-body-sm)",
                          color: "var(--text-muted)",
                        }}
                      >
                        {job.status === "running"
                          ? job.kind === "run_simulate"
                            ? "Simulerar…"
                            : job.kind === "report_generate"
                              ? "Genererar rapport…"
                              : "Genererar…"
                          : "I kö…"}{" "}
                        startad {formatWhen(job.started_at ?? job.created_at)}
                        {job.kind === "run_simulate" && runId != null ? (
                          <>
                            {" · "}
                            <Link to={`/runs/${runId}/edit?tab=results`}>
                              Öppna körning →
                            </Link>
                          </>
                        ) : null}
                        {job.kind === "report_generate" && reportId != null ? (
                          <>
                            {" · "}
                            <Link to={`/reports/${reportId}`}>Öppna rapport →</Link>
                          </>
                        ) : null}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </AdminShell>
  )
}
