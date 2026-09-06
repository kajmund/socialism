import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  archiveFinishedJobs,
  listJobs,
  setJobArchived,
  type Job,
  type JobStatus,
} from "@/api/jobs"
import { AdminShell } from "@/components/layout/AdminShell"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import {
  matchesCustomerScope,
  type CustomerScope,
} from "@/lib/scoping"
import { campaignJobHref } from "@/lib/dd-runs"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

type ShellComponent = ComponentType<{ children: ReactNode }>

type JobLinkPaths = {
  reports: string
  populations: string
  expertPanels: string
  campaigns: string
  runs: string
  expertgranskning: string
}

function jobLinkPaths(scope: CustomerScope): JobLinkPaths {
  if (scope === "bolag") {
    return {
      reports: "/bolag/reports",
      populations: "/bolag/expertpaneler",
      expertPanels: "/bolag/expertpaneler",
      campaigns: "/bolag/campaigns",
      runs: "/runs",
      expertgranskning: "/bolag/expertgranskning",
    }
  }
  return {
    reports: "/reports",
    populations: "/populations",
    expertPanels: "/bolag/expertpaneler",
    campaigns: "/bolag/campaigns",
    runs: "/runs",
    expertgranskning: "/expertgranskning",
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

function formatJobDuration(job: Job, t: Translate): string | null {
  const startIso = job.started_at ?? job.created_at
  const endIso = job.finished_at
  if (!startIso || !endIso) return null
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return t("jobs.duration.seconds", { n: sec })
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) {
    return s > 0
      ? t("jobs.duration.minutesSeconds", { m, s })
      : t("jobs.duration.minutes", { m })
  }
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0
    ? t("jobs.duration.hoursMinutes", { h, m: rm })
    : t("jobs.duration.hours", { h })
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

function statusLabel(status: JobStatus, t: Translate): string {
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

function kindLabel(kind: string, t: Translate): string {
  switch (kind) {
    case "population_generate":
      return t("jobs.kind.population_generate")
    case "run_simulate":
      return t("jobs.kind.run_simulate")
    case "report_generate":
      return t("jobs.kind.report_generate")
    case "panel_session_run":
      return t("jobs.kind.panel_session_run")
    case "dd_sourcing_run":
      return t("jobs.kind.dd_sourcing_run")
    case "dd_research":
      return t("jobs.kind.dd_research")
    default:
      return kind
  }
}

function progressLabel(job: Job, t: Translate): string {
  if (job.status === "pending") return t("jobs.progress.queued")
  switch (job.kind) {
    case "run_simulate":
      return t("jobs.progress.simulating")
    case "report_generate":
      return t("jobs.progress.reporting")
    case "panel_session_run":
      return t("jobs.progress.panel")
    case "dd_sourcing_run":
      return t("jobs.progress.sourcing")
    case "dd_research":
      return t("jobs.progress.research")
    default:
      return t("jobs.progress.generating")
  }
}

function jobIds(job: Job) {
  const popId = job.result?.population_id
  const runId =
    job.result?.run_id ??
    (typeof job.request.run_id === "number" ? job.request.run_id : null)
  const reportId =
    job.result?.report_id ??
    (typeof job.request.report_id === "string" ? job.request.report_id : null)
  const sessionId =
    typeof job.result?.session_id === "string"
      ? job.result.session_id
      : typeof job.request.session_id === "string"
        ? job.request.session_id
        : null
  const campaignId =
    typeof job.result?.campaign_id === "number"
      ? job.result.campaign_id
      : typeof job.request.campaign_id === "number"
        ? job.request.campaign_id
        : null
  const candidateId =
    typeof job.result?.candidate_id === "string"
      ? job.result.candidate_id
      : typeof job.request.candidate_id === "string"
        ? job.request.candidate_id
        : null
  return { popId, runId, reportId, sessionId, campaignId, candidateId }
}

function ddCampaignHref(job: Job): string | null {
  const { campaignId, candidateId } = jobIds(job)
  return campaignJobHref(campaignId, candidateId)
}

function ddCampaignLinkLabel(job: Job, t: Translate): string {
  const { candidateId } = jobIds(job)
  return candidateId ? t("jobs.openResults") : t("jobs.openCampaign")
}

function populationHref(
  job: Job,
  popId: number,
  paths: JobLinkPaths,
): string {
  if (job.result?.population_kind === "expert_panel") {
    return `${paths.expertPanels}/${popId}`
  }
  return `${paths.populations}/${popId}`
}

function isFinished(job: Job): boolean {
  return job.status === "succeeded" || job.status === "failed"
}

function JobArchiveButton({
  job,
  busy,
  onArchive,
  t,
}: {
  job: Job
  busy: boolean
  onArchive: (job: Job, archived: boolean) => void
  t: Translate
}) {
  if (job.archived_at) {
    return (
      <button type="button" disabled={busy} onClick={() => onArchive(job, false)}>
        {t("jobs.unarchive")}
      </button>
    )
  }
  if (!isFinished(job)) return null
  return (
    <button type="button" disabled={busy} onClick={() => onArchive(job, true)}>
      {t("jobs.archive")}
    </button>
  )
}

function JobActionLinks({
  job,
  t,
  paths,
}: {
  job: Job
  t: Translate
  paths: JobLinkPaths
}) {
  const { popId, runId, reportId, sessionId } = jobIds(job)
  const links: ReactNode[] = []

  if (job.status === "succeeded" && popId != null) {
    links.push(
      <Link key="pop" to={populationHref(job, popId, paths)}>
        {t("jobs.openPopulation")}
      </Link>,
    )
  }
  if (job.status === "succeeded" && job.kind === "run_simulate" && runId != null) {
    links.push(
      <Link key="results" to={`${paths.runs}/${runId}/edit?tab=results`}>
        {t("jobs.openResults")}
      </Link>,
    )
  }
  if (job.status === "succeeded" && job.kind === "report_generate" && reportId != null) {
    links.push(
      <Link key="report" to={`${paths.reports}/${reportId}`}>
        {t("jobs.openReport")}
      </Link>,
    )
  }
  if (
    job.status === "succeeded" &&
    (job.kind === "panel_session_run" ||
      job.kind === "dd_sourcing_run" ||
      job.kind === "dd_research")
  ) {
    const href = ddCampaignHref(job)
    if (href) {
      links.push(
        <Link key="campaign" to={href}>
          {ddCampaignLinkLabel(job, t)}
        </Link>,
      )
    } else if (job.kind === "panel_session_run") {
      const href = sessionId
        ? `${paths.expertgranskning}/${sessionId}?tab=results`
        : paths.expertgranskning
      links.push(
        <Link key="expertgranskning" to={href}>
          {t("jobs.openExpertgranskning")}
        </Link>,
      )
    }
  }
  if ((job.status === "pending" || job.status === "running") && job.kind === "run_simulate" && runId != null) {
    links.push(
      <Link key="run" to={`${paths.runs}/${runId}/edit?tab=results`}>
        {t("jobs.openRun")}
      </Link>,
    )
  }
  if (
    (job.status === "pending" || job.status === "running") &&
    job.kind === "report_generate" &&
    reportId != null
  ) {
    links.push(
      <Link key="report-live" to={`${paths.reports}/${reportId}`}>
        {t("jobs.openReport")}
      </Link>,
    )
  }
  if (
    (job.status === "pending" || job.status === "running") &&
    (job.kind === "panel_session_run" ||
      job.kind === "dd_sourcing_run" ||
      job.kind === "dd_research")
  ) {
    const href = ddCampaignHref(job)
    if (href) {
      links.push(
        <Link key="campaign-live" to={href}>
          {ddCampaignLinkLabel(job, t)}
        </Link>,
      )
    } else if (job.kind === "panel_session_run") {
      const liveHref = sessionId
        ? `${paths.expertgranskning}/${sessionId}?tab=results`
        : paths.expertgranskning
      links.push(
        <Link key="expertgranskning-live" to={liveHref}>
          {t("jobs.openExpertgranskning")}
        </Link>,
      )
    }
  }

  return <>{links}</>
}

function JobCard({
  job,
  t,
  intl,
  paths,
  busy,
  onArchive,
}: {
  job: Job
  t: Translate
  intl: string
  paths: JobLinkPaths
  busy: boolean
  onArchive: (job: Job, archived: boolean) => void
}) {
  const { popId, runId, reportId } = jobIds(job)
  const ddHref = ddCampaignHref(job)
  const duration = formatJobDuration(job, t)
  const whenCreated = formatWhen(job.created_at, intl, t("common.emDash"))
  return (
    <Card className="gap-0 py-4 ring-1 ring-border">
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
              {kindLabel(job.kind, t)} · {t("jobs.created", { when: whenCreated })}
              {duration ? ` · ${t("jobs.took", { duration })}` : null}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
            {job.archived_at ? (
              <span style={{ font: "var(--text-body-sm)", color: "var(--text-muted)" }}>
                {t("jobs.archived")}
              </span>
            ) : null}
            <span className={statusClass(job.status)}>{statusLabel(job.status, t)}</span>
          </div>
        </div>

        {job.status === "succeeded" && popId != null && (
          <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
            {t("jobs.personasCount", {
              count: job.result?.member_count ?? "?",
            })}{" "}
            ·{" "}
            <Link to={populationHref(job, popId, paths)}>{t("jobs.openPopulation")}</Link>
            {(() => {
              const warnings = (job.result as { warnings?: unknown } | null | undefined)
                ?.warnings
              if (!Array.isArray(warnings) || warnings.length === 0) return null
              return (
                <ul
                  className="mt-2 list-disc pl-5 text-amber-800 dark:text-amber-200"
                  style={{ font: "var(--text-body-sm)" }}
                >
                  {warnings.map((w) => (
                    <li key={String(w)}>{String(w)}</li>
                  ))}
                </ul>
              )
            })()}
          </div>
        )}
        {job.status === "succeeded" && job.kind === "run_simulate" && runId != null && (
          <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
            <Link to={`${paths.runs}/${runId}/edit?tab=results`}>{t("jobs.openResults")}</Link>
          </div>
        )}
        {job.status === "succeeded" && job.kind === "report_generate" && reportId != null && (
          <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
            <Link to={`${paths.reports}/${reportId}`}>{t("jobs.openReport")}</Link>
          </div>
        )}
        {job.status === "succeeded" &&
          (job.kind === "panel_session_run" ||
            job.kind === "dd_sourcing_run" ||
            job.kind === "dd_research") &&
          ddHref != null && (
            <div style={{ marginTop: 12, font: "var(--text-body-sm)" }}>
              <Link to={ddHref}>{ddCampaignLinkLabel(job, t)}</Link>
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
            {progressLabel(job, t)}{" "}
            {t("jobs.started", {
              when: formatWhen(job.started_at ?? job.created_at, intl, t("common.emDash")),
            })}
            {job.kind === "run_simulate" && runId != null ? (
              <>
                {" · "}
                <Link to={`${paths.runs}/${runId}/edit?tab=results`}>{t("jobs.openRun")}</Link>
              </>
            ) : null}
            {job.kind === "report_generate" && reportId != null ? (
              <>
                {" · "}
                <Link to={`${paths.reports}/${reportId}`}>{t("jobs.openReport")}</Link>
              </>
            ) : null}
            {(job.kind === "panel_session_run" ||
              job.kind === "dd_sourcing_run" ||
              job.kind === "dd_research") &&
            ddHref != null ? (
              <>
                {" · "}
                <Link to={ddHref}>{ddCampaignLinkLabel(job, t)}</Link>
              </>
            ) : null}
          </div>
        )}
        {isFinished(job) || job.archived_at ? (
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
            <JobArchiveButton job={job} busy={busy} onArchive={onArchive} t={t} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function JobListRow({
  job,
  t,
  intl,
  paths,
  busy,
  onArchive,
}: {
  job: Job
  t: Translate
  intl: string
  paths: JobLinkPaths
  busy: boolean
  onArchive: (job: Job, archived: boolean) => void
}) {
  const duration = formatJobDuration(job, t)
  const whenCreated = formatWhen(job.created_at, intl, t("common.emDash"))
  const meta = [
    kindLabel(job.kind, t),
    t("jobs.created", { when: whenCreated }),
    duration ? t("jobs.took", { duration }) : null,
    job.status === "failed" && job.error ? job.error : null,
    job.status === "pending" || job.status === "running" ? progressLabel(job, t) : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="admin-list-row admin-list-jobs">
      <div>
        <div className="nm">{job.label || job.id}</div>
      </div>
      <span className={statusClass(job.status)}>
        {job.archived_at ? `${t("jobs.archived")} · ` : null}
        {statusLabel(job.status, t)}
      </span>
      <div className="cell">{meta}</div>
      <div className="admin-list-actions">
        <JobActionLinks job={job} t={t} paths={paths} />
        <JobArchiveButton job={job} busy={busy} onArchive={onArchive} t={t} />
      </div>
    </div>
  )
}

export type JobsPageProps = {
  scope?: CustomerScope
  Shell?: ShellComponent
}

export function JobsPage({ scope = "admin", Shell = AdminShell }: JobsPageProps) {
  const { t, intl } = useLocale()
  const { jobs: liveJobs, applyJob, connected, status } = useJobsRealtime()
  const [showArchived, setShowArchived] = useState(false)
  const [archivedJobs, setArchivedJobs] = useState<Job[]>([])
  const [busyId, setBusyId] = useState<string | null>(null)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkConfirm, setBulkConfirm] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [view, setView] = useState<ListViewMode>("grid")

  useEffect(() => {
    if (!showArchived) {
      setArchivedJobs([])
      return
    }
    let cancelled = false
    void listJobs({ archived_only: true, limit: 100 })
      .then((rows) => {
        if (!cancelled) {
          setArchivedJobs(rows.filter((job) => matchesCustomerScope(job, scope)))
        }
      })
      .catch(() => {
        if (!cancelled) setToast(t("jobs.loadError"))
      })
    return () => {
      cancelled = true
    }
  }, [scope, showArchived, t])

  const jobs = useMemo(() => {
    const live = liveJobs.filter(
      (job) => matchesCustomerScope(job, scope) && !job.archived_at,
    )
    if (!showArchived) return live
    const byId = new Map<string, Job>()
    for (const job of live) byId.set(job.id, job)
    for (const job of archivedJobs) {
      if (matchesCustomerScope(job, scope)) byId.set(job.id, job)
    }
    return [...byId.values()].sort((a, b) => {
      const ta = new Date(a.created_at).getTime()
      const tb = new Date(b.created_at).getTime()
      return tb - ta
    })
  }, [archivedJobs, liveJobs, scope, showArchived])

  const finishedCount = useMemo(
    () => jobs.filter((job) => !job.archived_at && isFinished(job)).length,
    [jobs],
  )

  const paths = useMemo(() => jobLinkPaths(scope), [scope])
  const error =
    status === "closed" && liveJobs.length === 0 && !showArchived
      ? t("jobs.loadError")
      : null
  const reconnecting = !connected && status !== "open"

  async function onArchive(job: Job, archived: boolean) {
    setBusyId(job.id)
    try {
      const updated = await setJobArchived(job.id, archived)
      applyJob(updated)
      setArchivedJobs((prev) => {
        if (updated.archived_at) {
          if (!showArchived) return prev.filter((row) => row.id !== updated.id)
          const idx = prev.findIndex((row) => row.id === updated.id)
          if (idx === -1) return [updated, ...prev]
          const next = prev.slice()
          next[idx] = updated
          return next
        }
        return prev.filter((row) => row.id !== updated.id)
      })
      setToast(archived ? t("jobs.archivedToast") : t("jobs.unarchivedToast"))
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("jobs.archiveError"))
    } finally {
      setBusyId(null)
    }
  }

  async function onArchiveFinished() {
    setBulkBusy(true)
    try {
      const updated = await archiveFinishedJobs()
      for (const job of updated) applyJob(job)
      if (showArchived) {
        setArchivedJobs((prev) => {
          const byId = new Map(prev.map((row) => [row.id, row]))
          for (const job of updated) byId.set(job.id, job)
          return [...byId.values()]
        })
      }
      setBulkConfirm(false)
      setToast(t("jobs.archivedMany", { count: updated.length }))
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("jobs.archiveError"))
    } finally {
      setBulkBusy(false)
    }
  }

  const emptyCopy = showArchived
    ? t("jobs.emptyArchived")
    : scope === "bolag"
      ? t("jobs.emptyBolag")
      : t("jobs.empty")

  return (
    <Shell>
      <div className="wrap admin-page">
        <div className="admin-page-chrome">
          <div className="section-head">
            <span className="kicker">{t("jobs.kicker")}</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              {t("jobs.title")}
            </h1>
            <p>{scope === "bolag" ? t("jobs.introBolag") : t("jobs.intro")}</p>
          </div>

          <div className="controls-row">
            <div className="controls-left" style={{ alignItems: "center", gap: 12 }}>
              <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                />
                {t("jobs.showArchived")}
              </label>
              {finishedCount > 0 ? (
                bulkConfirm ? (
                  <div className="confirm-row">
                    <button
                      type="button"
                      disabled={bulkBusy}
                      onClick={() => setBulkConfirm(false)}
                    >
                      {t("common.cancel")}
                    </button>
                    <button
                      type="button"
                      className="yes"
                      disabled={bulkBusy}
                      onClick={() => void onArchiveFinished()}
                    >
                      {t("jobs.archiveFinishedConfirm")}
                    </button>
                  </div>
                ) : (
                  <button type="button" onClick={() => setBulkConfirm(true)}>
                    {t("jobs.archiveFinished")}
                  </button>
                )
              ) : null}
            </div>
            <div className="controls-right">
              <ViewToggle value={view} onChange={setView} />
            </div>
          </div>

          {toast ? (
            <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
              {toast}
            </div>
          ) : null}

          {reconnecting && (
            <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
              {t("jobs.reconnecting")}
            </div>
          )}

          {error && (
            <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
              {error}
            </div>
          )}
        </div>

        <div className="admin-page-body">
          {jobs.length === 0 && !error ? (
            <div className="no-match" style={{ textAlign: "left" }}>
              {emptyCopy}
            </div>
          ) : view === "grid" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {jobs.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  t={t}
                  intl={intl}
                  paths={paths}
                  busy={busyId === job.id}
                  onArchive={onArchive}
                />
              ))}
            </div>
          ) : (
            <div className="admin-list-stack">
              {jobs.map((job) => (
                <JobListRow
                  key={job.id}
                  job={job}
                  t={t}
                  intl={intl}
                  paths={paths}
                  busy={busyId === job.id}
                  onArchive={onArchive}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </Shell>
  )
}

export function BolagJobsPage() {
  return <JobsPage scope="bolag" Shell={NestedBolagPage} />
}
