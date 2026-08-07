import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import type { Job, JobStatus } from "@/api/jobs"
import { listMessages } from "@/api/messages"
import { listPersonas } from "@/api/personas"
import { listPopulations } from "@/api/populations"
import { listReports, type Report } from "@/api/reports"
import { listRuns } from "@/api/runs"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { formatRunDate } from "@/data/runs"
import type { RunStatus, RunSummary } from "@/data/runs-types"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

type DashboardData = {
  runs: RunSummary[]
  personaCount: number
  populationCount: number
  unusedPopulationCount: number
  messageCount: number
  reports: Report[]
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

function runStatusLabel(status: RunStatus, t: Translate): string {
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

function runActionLabel(status: RunStatus, t: Translate): string {
  switch (status) {
    case "draft":
      return t("runs.list.continueConfig")
    case "running":
      return t("runs.list.seeStatus")
    case "failed":
      return t("runs.list.seeError")
    default:
      return t("runs.list.openResults")
  }
}

function runActionHref(run: RunSummary): string {
  if (run.status === "draft") return `/runs/${run.id}/edit`
  return `/runs/${run.id}/edit?tab=results`
}

function jobStatusLabel(status: JobStatus, t: Translate): string {
  switch (status) {
    case "pending":
      return t("jobs.status.pending")
    case "running":
      return t("jobs.status.running")
    case "succeeded":
      return t("jobs.status.succeeded")
    case "failed":
      return t("jobs.status.failed")
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function jobKindLabel(kind: string, t: Translate): string {
  switch (kind) {
    case "population_generate":
      return t("jobs.kind.population_generate")
    case "run_simulate":
      return t("jobs.kind.run_simulate")
    case "report_generate":
      return t("jobs.kind.report_generate")
    default:
      return kind
  }
}

function jobRunId(job: Job): number | null {
  return (
    job.result?.run_id ??
    (typeof job.request.run_id === "number" ? job.request.run_id : null)
  )
}

function jobReportId(job: Job): string | null {
  return (
    job.result?.report_id ??
    (typeof job.request.report_id === "string" ? job.request.report_id : null)
  )
}

function jobHref(job: Job): string | null {
  const runId = jobRunId(job)
  const reportId = jobReportId(job)
  if (job.kind === "run_simulate" && runId != null) {
    return `/runs/${runId}/edit?tab=results`
  }
  if (job.kind === "report_generate" && reportId != null) {
    return `/reports/${reportId}`
  }
  const popId = job.result?.population_id
  if (popId != null) return `/populations/${popId}`
  return null
}

function QuickAction({
  to,
  label,
  primary = false,
}: {
  to: string
  label: string
  primary?: boolean
}) {
  return (
    <Link
      to={to}
      className={
        primary
          ? "admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
          : "inline-flex h-9 items-center rounded-md border border-border px-4 text-sm text-foreground no-underline hover:bg-muted"
      }
    >
      {label}
    </Link>
  )
}

function StatTile({
  to,
  label,
  count,
  hint,
}: {
  to: string
  label: string
  count: number
  hint?: string
}) {
  return (
    <Link
      to={to}
      className="block rounded-lg border border-border bg-card px-4 py-3 no-underline transition-colors hover:border-db-gold-500/40"
    >
      <div className="text-2xl font-medium tabular-nums text-foreground">{count}</div>
      <div className="mt-1 text-sm text-foreground">{label}</div>
      {hint ? (
        <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
      ) : null}
    </Link>
  )
}

function OnboardingSteps({ t }: { t: Translate }) {
  const steps = [
    {
      n: 1,
      title: t("dashboard.onboardingStep1"),
      hint: t("dashboard.onboardingStep1Hint"),
      to: "/personas/new",
    },
    {
      n: 2,
      title: t("dashboard.onboardingStep2"),
      hint: t("dashboard.onboardingStep2Hint"),
      to: "/populations/new",
    },
    {
      n: 3,
      title: t("dashboard.onboardingStep3"),
      hint: t("dashboard.onboardingStep3Hint"),
      to: "/messages/new",
    },
    {
      n: 4,
      title: t("dashboard.onboardingStep4"),
      hint: t("dashboard.onboardingStep4Hint"),
      to: "/runs/new",
    },
  ]
  return (
    <Card className="gap-0 py-5 ring-1 ring-border">
      <CardContent className="px-5">
        <h2
          style={{
            font: "var(--text-h3)",
            fontFamily: "'Bai Jamjuree', sans-serif",
            fontWeight: 400,
            marginBottom: 8,
          }}
        >
          {t("dashboard.onboardingTitle")}
        </h2>
        <p style={{ font: "var(--text-body-sm)", color: "var(--text-muted)", marginBottom: 20 }}>
          {t("dashboard.onboardingIntro")}
        </p>
        <ol style={{ display: "flex", flexDirection: "column", gap: 12, listStyle: "none", padding: 0, margin: 0 }}>
          {steps.map((step) => (
            <li key={step.n}>
              <Link
                to={step.to}
                className="flex items-start gap-3 rounded-md border border-border px-4 py-3 no-underline transition-colors hover:border-db-gold-500/40"
              >
                <span
                  className="mt-0.5 inline-grid size-6 shrink-0 place-items-center rounded-full bg-db-gold-500 text-xs font-semibold text-db-navy-ink"
                  aria-hidden
                >
                  {step.n}
                </span>
                <span>
                  <span className="block text-sm font-medium text-foreground">{step.title}</span>
                  <span className="block text-xs text-muted-foreground">{step.hint}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const { t, intl } = useLocale()
  const { jobs } = useJobsRealtime()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    async function load() {
      try {
        const [runs, personas, populations, messages, reports] = await Promise.all([
          listRuns(),
          listPersonas(),
          listPopulations(),
          listMessages(),
          listReports({ status: "succeeded", limit: 5 }),
        ])
        if (cancelled) return
        setData({
          runs,
          personaCount: personas.length,
          populationCount: populations.length,
          unusedPopulationCount: populations.filter((p) => p.runs === 0).length,
          messageCount: messages.length,
          reports,
        })
        setError(null)
        setLoading(false)
        timer = window.setTimeout(load, 15000)
      } catch (err) {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("dashboard.loadError"))
        setLoading(false)
        timer = window.setTimeout(load, 15000)
      }
    }

    void load()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [t])

  const recentRuns = useMemo(() => {
    if (!data) return []
    return [...data.runs]
      .sort((a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime())
      .slice(0, 5)
  }, [data])

  const activeJobs = useMemo(
    () => jobs.filter((j) => j.status === "pending" || j.status === "running"),
    [jobs],
  )

  const showOnboarding =
    data != null &&
    data.personaCount === 0 &&
    data.populationCount === 0 &&
    data.runs.length === 0

  return (
    <AdminShell>
      <div className="wrap">
        <div className="section-head">
          <span className="kicker">{t("dashboard.kicker")}</span>
          <h1
            style={{
              font: "var(--text-h1)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
            }}
          >
            {t("dashboard.welcome")}
          </h1>
          <p>{t("dashboard.welcomeHint")}</p>
        </div>

        {error ? (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        ) : null}

        {loading && !data ? (
          <div className="no-match">{t("dashboard.loading")}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
            {showOnboarding ? <OnboardingSteps t={t} /> : null}

            <section>
              <h2
                style={{
                  font: "var(--text-h3)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                  marginBottom: 12,
                }}
              >
                {t("dashboard.quickStart")}
              </h2>
              <div className="flex flex-wrap gap-3">
                <QuickAction to="/runs/new" label={t("dashboard.newRun")} primary />
                <QuickAction to="/populations/new" label={t("dashboard.newPopulation")} />
                <QuickAction to="/messages/new" label={t("dashboard.newMessage")} />
              </div>
            </section>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                gap: 24,
              }}
            >
              <section>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    gap: 12,
                    marginBottom: 12,
                  }}
                >
                  <h2
                    style={{
                      font: "var(--text-h3)",
                      fontFamily: "'Bai Jamjuree', sans-serif",
                      fontWeight: 400,
                      margin: 0,
                    }}
                  >
                    {t("dashboard.recentRuns")}
                  </h2>
                  <Link to="/runs" style={{ font: "var(--text-body-sm)" }}>
                    {t("dashboard.viewAllRuns")}
                  </Link>
                </div>
                {recentRuns.length === 0 ? (
                  <div className="no-match" style={{ textAlign: "left" }}>
                    {t("dashboard.recentRunsEmpty")}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {recentRuns.map((run) => (
                      <Card key={run.id} className="gap-0 py-3 ring-1 ring-border">
                        <CardContent className="px-4">
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              gap: 12,
                              alignItems: "baseline",
                            }}
                          >
                            <div>
                              <div style={{ font: "var(--text-body)", fontWeight: 500 }}>
                                {run.name}
                              </div>
                              <div
                                style={{
                                  font: "var(--text-body-sm)",
                                  color: "var(--text-muted)",
                                  marginTop: 2,
                                }}
                              >
                                {run.population} · {formatRunDate(run.updated, intl)}
                              </div>
                            </div>
                            <span className={"status-tag " + run.status}>
                              {runStatusLabel(run.status, t)}
                            </span>
                          </div>
                          <div style={{ marginTop: 10 }}>
                            <Link to={runActionHref(run)} style={{ font: "var(--text-body-sm)" }}>
                              {runActionLabel(run.status, t)} →
                            </Link>
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </section>

              <section>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    gap: 12,
                    marginBottom: 12,
                  }}
                >
                  <h2
                    style={{
                      font: "var(--text-h3)",
                      fontFamily: "'Bai Jamjuree', sans-serif",
                      fontWeight: 400,
                      margin: 0,
                    }}
                  >
                    {t("dashboard.activeJobs")}
                  </h2>
                  <Link to="/jobs" style={{ font: "var(--text-body-sm)" }}>
                    {t("dashboard.viewAllJobs")}
                  </Link>
                </div>
                {activeJobs.length === 0 ? (
                  <div className="no-match" style={{ textAlign: "left" }}>
                    {t("dashboard.activeJobsEmpty")}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {activeJobs.map((job) => {
                      const href = jobHref(job)
                      return (
                        <Card key={job.id} className="gap-0 py-3 ring-1 ring-border">
                          <CardContent className="px-4">
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                gap: 12,
                                alignItems: "baseline",
                              }}
                            >
                              <div>
                                <div style={{ font: "var(--text-body)", fontWeight: 500 }}>
                                  {job.label || job.id}
                                </div>
                                <div
                                  style={{
                                    font: "var(--text-body-sm)",
                                    color: "var(--text-muted)",
                                    marginTop: 2,
                                  }}
                                >
                                  {jobKindLabel(job.kind, t)} ·{" "}
                                  {formatWhen(
                                    job.started_at ?? job.created_at,
                                    intl,
                                    t("common.emDash"),
                                  )}
                                </div>
                              </div>
                              <span className={"job-status " + job.status}>
                                {jobStatusLabel(job.status, t)}
                              </span>
                            </div>
                            {href ? (
                              <div style={{ marginTop: 10 }}>
                                <Link to={href} style={{ font: "var(--text-body-sm)" }}>
                                  {t("common.openArrow")}
                                </Link>
                              </div>
                            ) : null}
                          </CardContent>
                        </Card>
                      )
                    })}
                  </div>
                )}
              </section>
            </div>

            <section>
              <h2
                style={{
                  font: "var(--text-h3)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                  marginBottom: 12,
                }}
              >
                {t("dashboard.library")}
              </h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                  gap: 12,
                }}
              >
                <StatTile
                  to="/personas"
                  label={t("dashboard.libraryPersonas")}
                  count={data?.personaCount ?? 0}
                />
                <StatTile
                  to="/populations"
                  label={t("dashboard.libraryPopulations")}
                  count={data?.populationCount ?? 0}
                  hint={
                    data && data.unusedPopulationCount > 0
                      ? t("dashboard.libraryUnusedPopulations", {
                          count: data.unusedPopulationCount,
                        })
                      : undefined
                  }
                />
                <StatTile
                  to="/messages"
                  label={t("dashboard.libraryMessages")}
                  count={data?.messageCount ?? 0}
                />
              </div>
            </section>

            <section>
              <h2
                style={{
                  font: "var(--text-h3)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                  marginBottom: 12,
                }}
              >
                {t("dashboard.recentReports")}
              </h2>
              {!data?.reports.length ? (
                <div className="no-match" style={{ textAlign: "left" }}>
                  {t("dashboard.recentReportsEmpty")}
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {data.reports.map((report) => (
                    <Card key={report.id} className="gap-0 py-3 ring-1 ring-border">
                      <CardContent className="px-4">
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            gap: 12,
                            alignItems: "baseline",
                          }}
                        >
                          <div>
                            <div style={{ font: "var(--text-body)", fontWeight: 500 }}>
                              {report.title}
                            </div>
                            <div
                              style={{
                                font: "var(--text-body-sm)",
                                color: "var(--text-muted)",
                                marginTop: 2,
                              }}
                            >
                              {formatWhen(report.finished_at ?? report.created_at, intl, t("common.emDash"))}
                            </div>
                          </div>
                        </div>
                        <div style={{ marginTop: 10 }}>
                          <Link to={`/reports/${report.id}`} style={{ font: "var(--text-body-sm)" }}>
                            {t("toast.openReport")} →
                          </Link>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </AdminShell>
  )
}
