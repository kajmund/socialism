import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom"
import type { Job, JobStatus } from "@/api/jobs"
import { useAuth } from "@/auth/AuthProvider"
import { LocaleSwitcher } from "@/components/layout/LocaleSwitcher"
import { useLocale, type MessageKey } from "@/i18n"
import type { Role } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

const NAV_ITEMS = [
  { key: "nav.personas" as const, to: "/personas", match: "/personas" },
  { key: "nav.populations" as const, to: "/populations", match: "/populations" },
  { key: "nav.messages" as const, to: "/messages", match: "/messages" },
  { key: "nav.tools" as const, to: "/tools", match: "/tools" },
  { key: "nav.runs" as const, to: "/runs", match: "/runs" },
  { key: "nav.reports" as const, to: "/reports", match: "/reports" },
  { key: "nav.feedback" as const, to: "/feedback", match: "/feedback" },
  { key: "nav.jobs" as const, to: "/jobs", match: "/jobs" },
]

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

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

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

function toastFromTransition(
  job: Job,
  prev: JobStatus | undefined,
  t: Translate,
): ToastState | null {
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
        message: t("toast.simulationDone", { label: job.label }),
        href: `/runs/${runId}/edit?tab=results`,
        hrefLabel: t("toast.openResults"),
      }
    }
    if (job.kind === "report_generate" && reportId != null) {
      return {
        kind: "ok",
        message: t("toast.reportDone", { label: job.label }),
        href: `/reports/${reportId}`,
        hrefLabel: t("toast.openReport"),
      }
    }
    return {
      kind: "ok",
      message: t("toast.jobDone", { label: job.label }),
      href: popId != null ? `/populations/${popId}` : "/jobs",
      hrefLabel: popId != null ? t("toast.openPopulation") : t("toast.viewJobs"),
    }
  }
  const detail = job.error ? `: ${job.error}` : ""
  const runId = job.request?.run_id
  if (job.kind === "run_simulate" && typeof runId === "number") {
    return {
      kind: "err",
      message: t("toast.simulationFailed", { label: job.label, detail }),
      href: `/runs/${runId}/edit?tab=results`,
      hrefLabel: t("toast.openRun"),
    }
  }
  const reportId = job.request?.report_id
  if (job.kind === "report_generate" && typeof reportId === "string") {
    return {
      kind: "err",
      message: t("toast.reportFailed", { label: job.label, detail }),
      href: `/reports/${reportId}`,
      hrefLabel: t("toast.openReport"),
    }
  }
  return {
    kind: "err",
    message: t("toast.jobFailed", { label: job.label, detail }),
    href: "/jobs",
    hrefLabel: t("toast.viewJobs"),
  }
}

function NavItems({
  pathname,
  activeCount,
  variant,
  t,
  showTools,
  onNavigate,
}: {
  pathname: string
  activeCount: number
  variant: "inline" | "panel"
  t: Translate
  showTools: boolean
  onNavigate?: () => void
}) {
  const items = showTools ? NAV_ITEMS : NAV_ITEMS.filter((link) => link.to !== "/tools")
  return (
    <>
      {items.map((link) => {
        const active = isSectionActive(pathname, link.match)
        return (
          <NavLink
            key={link.to}
            to={link.to}
            className={cn(
              "admin-topnav-link",
              variant === "inline"
                ? "admin-topnav-link-inline"
                : "admin-topnav-link-panel",
              active && "is-active",
            )}
            onClick={onNavigate}
          >
            {t(link.key)}
            {link.to === "/jobs" && activeCount > 0 ? (
              <span
                className="inline-grid h-5 min-w-5 place-items-center rounded-full bg-[#fbd37b] px-1.5 text-[11px] font-semibold text-[#1b1e2a]"
                aria-label={t("nav.activeJobs", { count: activeCount })}
              >
                {activeCount}
              </span>
            ) : null}
          </NavLink>
        )
      })}
    </>
  )
}

function MenuIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6z"
        />
      </svg>
    )
  }
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
      <rect x="4" y="8" width="22" height="2" fill="currentColor" />
      <rect x="4" y="14" width="22" height="2" fill="currentColor" />
      <rect x="4" y="20" width="22" height="2" fill="currentColor" />
    </svg>
  )
}

function roleLabel(role: Role, t: Translate): string {
  switch (role) {
    case "admin":
      return t("auth.roleAdmin")
    case "user":
      return t("auth.roleUser")
    default: {
      const _exhaustive: never = role
      return _exhaustive
    }
  }
}

function SessionActions({
  compact,
}: {
  compact?: boolean
}) {
  const { t, locale, setLocale } = useLocale()
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  async function onSignOut() {
    await signOut()
    navigate("/login", { replace: true })
  }

  return (
    <div className={cn("flex items-center gap-4", compact && "flex-wrap")}>
      {user ? (
        <span className="text-xs text-white/55">
          {t("auth.signedInAs", { name: user.username })}
          <span className="text-white/35"> · {roleLabel(user.role, t)}</span>
        </span>
      ) : null}
      <button
        type="button"
        className="rounded border border-white/25 bg-black/40 px-3 py-1.5 text-sm text-white hover:border-db-gold-500/70 hover:text-db-gold-500"
        onClick={() => void onSignOut()}
      >
        {t("auth.signOut")}
      </button>
      <LocaleSwitcher locale={locale} setLocale={setLocale} t={t} />
    </div>
  )
}

export function AdminShell({ children }: AdminShellProps) {
  const { pathname } = useLocation()
  const { t } = useLocale()
  const { isAdmin } = useAuth()
  const { jobs, activeCount } = useJobsRealtime()
  const [toast, setToast] = useState<ToastState | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const jobsRef = useRef(jobs)
  jobsRef.current = jobs

  useEffect(() => {
    setMenuOpen(false)
  }, [pathname])

  // Nav is inline from xl up — drop the mobile panel (and its scroll lock) there.
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1280px)")
    function sync() {
      if (desktop.matches) setMenuOpen(false)
    }
    sync()
    desktop.addEventListener("change", sync)
    return () => desktop.removeEventListener("change", sync)
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false)
    }
    window.addEventListener("keydown", onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prev
    }
  }, [menuOpen])

  useEffect(() => {
    const rows = jobsRef.current
    const seen = readSeen()
    const nextSeen = { ...seen }
    let notify: ToastState | null = null
    for (const job of rows) {
      const prev = seen[job.id]
      const toastCandidate = toastFromTransition(job, prev, t)
      if (toastCandidate && !notify) notify = toastCandidate
      nextSeen[job.id] = job.status
    }
    writeSeen(nextSeen)
    if (notify) {
      setToast(notify)
      const hide = window.setTimeout(() => setToast(null), 6000)
      return () => window.clearTimeout(hide)
    }
  }, [jobs, t])

  return (
    <div className="theme-admin">
      <header className="admin-topnav relative sticky top-0 z-50 text-white">
        <div className="mx-auto flex h-[88px] max-w-[1440px] items-center justify-between gap-8 px-6 md:h-[100px] md:px-10 2xl:px-[90px]">
          <NavLink
            to="/"
            className="admin-topnav-brand no-underline"
            onClick={() => setMenuOpen(false)}
          >
            <img
              src="/devbrains-logo-white.png"
              alt="Devbrains"
              className="h-10 w-auto md:h-[50px]"
            />
          </NavLink>
          <div className="hidden items-center gap-6 xl:flex">
            <nav className="flex items-center gap-6" aria-label={t("nav.ariaMain")}>
              <NavItems
                pathname={pathname}
                activeCount={activeCount}
                variant="inline"
                t={t}
                showTools={isAdmin}
              />
            </nav>
            <SessionActions />
          </div>
          <button
            type="button"
            className="admin-topnav-burger flex xl:hidden"
            aria-expanded={menuOpen}
            aria-controls="admin-main-menu"
            aria-label={menuOpen ? t("nav.closeMenu") : t("nav.openMenu")}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MenuIcon open={menuOpen} />
          </button>
        </div>
        {menuOpen ? (
          <div
            id="admin-main-menu"
            className="admin-topnav-panel absolute inset-x-0 top-full z-50 max-h-[calc(100vh-88px)] overflow-y-auto md:max-h-[calc(100vh-100px)] xl:hidden"
          >
            <div className="mx-auto flex max-w-[1440px] flex-col gap-8 px-6 py-10 md:px-10 md:py-12">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#fbd37b]">
                {t("brand.product")}
              </p>
              <nav className="flex flex-col gap-1" aria-label={t("nav.ariaMain")}>
                <NavItems
                  pathname={pathname}
                  activeCount={activeCount}
                  variant="panel"
                  t={t}
                  showTools={isAdmin}
                  onNavigate={() => setMenuOpen(false)}
                />
              </nav>
              <SessionActions compact />
            </div>
          </div>
        ) : null}
      </header>
      {menuOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/40 xl:hidden"
          aria-label={t("nav.closeMenu")}
          onClick={() => setMenuOpen(false)}
        />
      ) : null}
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
                {toast.hrefLabel ?? t("common.open")} →
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
