import { useEffect, useState, type ReactNode } from "react"
import { Link, NavLink, useLocation } from "react-router-dom"
import { listJobs, type Job, type JobStatus } from "@/api/jobs"
import { cn } from "@/lib/utils"

const LINKS = [
  { label: "Personas", to: "/personas", match: "/personas" },
  { label: "Populationer", to: "/populations", match: "/populations" },
  { label: "Budskap", to: "/messages", match: "/messages" },
  { label: "Konfiguration", to: "/config", match: "/config" },
  { label: "Körningar", to: "/runs", match: "/runs" },
  { label: "Bakgrundsjobb", to: "/jobs", match: "/jobs" },
  { label: "Simulator", to: "/simulator", match: "/simulator" },
] as const

const SEEN_KEY = "opinionssimulator.jobStatusSeen"

type AdminShellProps = {
  children: ReactNode
}

type ToastState = {
  kind: "ok" | "err"
  message: string
  href?: string
  hrefLabel?: string
}

function isSectionActive(pathname: string, match: string) {
  return pathname === match || pathname.startsWith(`${match}/`)
}

function readSeen(): Record<string, JobStatus> {
  try {
    const raw = sessionStorage.getItem(SEEN_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, JobStatus>
    return parsed && typeof parsed === "object" ? parsed : {}
  } catch {
    return {}
  }
}

function writeSeen(map: Record<string, JobStatus>) {
  sessionStorage.setItem(SEEN_KEY, JSON.stringify(map))
}

/** Call after creating a job so the global poller can toast on completion. */
export function rememberJobPending(jobId: string) {
  const seen = readSeen()
  seen[jobId] = "pending"
  writeSeen(seen)
}

function toastFromTransition(job: Job, prev: JobStatus | undefined): ToastState | null {
  if (job.status !== "succeeded" && job.status !== "failed") return null
  // Only notify when we observed a non-terminal status first (or never saw it and it's fresh).
  if (prev === "succeeded" || prev === "failed") return null
  if (prev == null && (job.status === "succeeded" || job.status === "failed")) {
    // First sight of an already-finished job: don't toast (page refresh / history).
    return null
  }
  if (job.status === "succeeded") {
    const popId = job.result?.population_id
    const runId = job.result?.run_id
    const reportId = job.result?.report_id
    if (job.kind === "run_simulate" && runId != null) {
      return {
        kind: "ok",
        message: `Simuleringen »${job.label}« är klar`,
        href: `/runs/${runId}/edit?tab=results`,
        hrefLabel: "Öppna resultat",
      }
    }
    if (job.kind === "report_generate" && reportId != null) {
      return {
        kind: "ok",
        message: `Rapporten »${job.label}« är klar`,
        href: `/reports/${reportId}`,
        hrefLabel: "Öppna rapport",
      }
    }
    return {
      kind: "ok",
      message: `Jobbet »${job.label}« är klart`,
      href: popId != null ? `/populations/${popId}` : "/jobs",
      hrefLabel: popId != null ? "Öppna population" : "Visa jobb",
    }
  }
  const runId = job.request?.run_id
  if (job.kind === "run_simulate" && typeof runId === "number") {
    return {
      kind: "err",
      message: `Simuleringen »${job.label}« misslyckades${job.error ? `: ${job.error}` : ""}`,
      href: `/runs/${runId}/edit?tab=results`,
      hrefLabel: "Öppna körning",
    }
  }
  const reportId = job.request?.report_id
  if (job.kind === "report_generate" && typeof reportId === "string") {
    return {
      kind: "err",
      message: `Rapporten »${job.label}« misslyckades${job.error ? `: ${job.error}` : ""}`,
      href: `/reports/${reportId}`,
      hrefLabel: "Öppna rapport",
    }
  }
  return {
    kind: "err",
    message: `Jobbet »${job.label}« misslyckades${job.error ? `: ${job.error}` : ""}`,
    href: "/jobs",
    hrefLabel: "Visa jobb",
  }
}

export function AdminShell({ children }: AdminShellProps) {
  const { pathname } = useLocation()
  const [activeCount, setActiveCount] = useState(0)
  const [toast, setToast] = useState<ToastState | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined

    async function tick() {
      try {
        const rows = await listJobs({ limit: 20 })
        if (cancelled) return
        const seen = readSeen()
        const nextSeen = { ...seen }
        let notify: ToastState | null = null
        for (const job of rows) {
          const prev = seen[job.id]
          const toastCandidate = toastFromTransition(job, prev)
          if (toastCandidate && !notify) notify = toastCandidate
          nextSeen[job.id] = job.status
        }
        writeSeen(nextSeen)
        setActiveCount(
          rows.filter((j) => j.status === "pending" || j.status === "running").length,
        )
        if (notify) {
          setToast(notify)
          window.setTimeout(() => setToast(null), 6000)
        }
        const active = rows.some((j) => j.status === "pending" || j.status === "running")
        timer = window.setTimeout(tick, active ? 2500 : 10000)
      } catch {
        if (!cancelled) timer = window.setTimeout(tick, 10000)
      }
    }

    void tick()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [])

  return (
    <div className="theme-admin">
      <header className="admin-topnav sticky top-0 z-50 bg-db-ink-950 text-db-ink-0">
        <div className="mx-auto flex max-w-[1240px] items-center justify-between gap-8 px-10 py-4">
          <NavLink to="/runs" className="admin-topnav-brand flex items-center gap-3 no-underline">
            <img
              src="/devbrains-logo-white.png"
              alt="Devbrains"
              className="h-7 w-auto"
            />
            <span className="hidden text-sm text-db-ink-0/70 lg:inline">
              Opinionssimulator
            </span>
          </NavLink>
          <nav className="flex items-center gap-7 text-sm" aria-label="Huvudmeny">
            {LINKS.map((link) => {
              const active = isSectionActive(pathname, link.match)
              return (
                <NavLink
                  key={link.to}
                  to={link.to}
                  className={cn(
                    "admin-topnav-link border-b-2 pb-0.5 no-underline transition-colors",
                    active
                      ? "is-active border-db-gold-500 text-db-ink-0"
                      : "border-transparent text-db-ink-0/75 hover:text-db-ink-0",
                  )}
                >
                  {link.label}
                  {link.to === "/jobs" && activeCount > 0 ? (
                    <span
                      className="ml-1.5 inline-grid h-4 min-w-4 place-items-center rounded-full bg-db-gold-500 px-1 text-[10px] font-semibold text-db-navy-ink"
                      aria-label={`${activeCount} aktiva jobb`}
                    >
                      {activeCount}
                    </span>
                  ) : null}
                </NavLink>
              )
            })}
          </nav>
        </div>
      </header>
      {children}
      {toast && (
        <div className="toast" role="status">
          <div className="ck">{toast.kind === "ok" ? "✓" : "!"}</div>
          <div>
            <div>{toast.message}</div>
            {toast.href && (
              <Link
                to={toast.href}
                style={{ color: "var(--db-gold-500)", marginTop: 4, display: "inline-block" }}
              >
                {toast.hrefLabel ?? "Öppna"} →
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
