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
                          {job.kind === "population_generate"
                            ? "Populationsgenerering"
                            : job.kind}{" "}
                          · skapad {formatWhen(job.created_at)}
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
                        {job.status === "running" ? "Genererar…" : "I kö…"} startad{" "}
                        {formatWhen(job.started_at ?? job.created_at)}
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
