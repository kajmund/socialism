import { getJob, rerunJob, resumeJob, type Job } from "@/api/jobs"
import { Microscope, X } from "lucide-react"
import { useEffect, useState } from "react"
import { ResearchMonitorPanel } from "@/components/research/ResearchMonitorPanel"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import {
  isRerunnableResearchJob,
  isResumableResearchJob,
  researchAttemptId,
} from "@/products/sme/smeResearchJobs"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

export function SmeResearchModal({
  open,
  jobId,
  title,
  onClose,
  onOpenedJob,
}: {
  open: boolean
  jobId: string | null
  title: string
  onClose: () => void
  onOpenedJob?: (job: Job) => void
}) {
  const { t } = useLocale()
  const { jobs, applyJob } = useJobsRealtime()
  const [polledAttemptId, setPolledAttemptId] = useState<string | null>(null)
  const [resuming, setResuming] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const liveJob = jobId ? jobs.find((job) => job.id === jobId) : undefined
  const attemptId =
    (liveJob ? researchAttemptId(liveJob) : null) ?? polledAttemptId
  const canResume = liveJob != null && isResumableResearchJob(liveJob)
  const canRerun = liveJob != null && isRerunnableResearchJob(liveJob)
  const busy = resuming || rerunning

  useEffect(() => {
    setPolledAttemptId(null)
    setResuming(false)
    setRerunning(false)
    setActionError(null)
  }, [open, jobId])

  useEffect(() => {
    if (!open) return
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", closeOnEscape)
    return () => window.removeEventListener("keydown", closeOnEscape)
  }, [onClose, open])

  useEffect(() => {
    if (!open || !jobId || attemptId) return
    let cancelled = false
    async function poll() {
      try {
        const job = await getJob(jobId)
        if (cancelled) return
        const nextAttemptId = researchAttemptId(job)
        if (nextAttemptId) setPolledAttemptId(nextAttemptId)
      } catch {
        // Realtime + retry on next interval.
      }
    }
    void poll()
    const timer = window.setInterval(() => {
      void poll()
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [attemptId, jobId, open])

  if (!open || !jobId) return null

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sme-research-modal-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex h-[min(92vh,900px)] w-full max-w-5xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-white/15 bg-db-ink-0 shadow-2xl">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[color:var(--border-hairline)] bg-db-ink-950 px-4 text-db-ink-0">
          <Microscope size={18} className="shrink-0 text-db-gold-500" aria-hidden="true" />
          <h2
            id="sme-research-modal-title"
            className="min-w-0 truncate text-sm font-medium"
          >
            {title}
          </h2>
          {canResume ? (
            <AdminButton
              variant="accent"
              size="sm"
              className="ml-auto shrink-0"
              disabled={busy}
              onClick={() => {
                if (!jobId) return
                setResuming(true)
                setActionError(null)
                void resumeJob(jobId)
                  .then((updated) => {
                    applyJob(updated)
                  })
                  .catch((error: unknown) => {
                    setActionError(
                      error instanceof ApiError
                        ? error.message
                        : t("sme.resumeResearchError"),
                    )
                  })
                  .finally(() => {
                    setResuming(false)
                  })
              }}
            >
              {t("sme.resumeResearch")}
            </AdminButton>
          ) : null}
          {canRerun ? (
            <AdminButton
              variant="accent"
              size="sm"
              className={canResume ? "shrink-0" : "ml-auto shrink-0"}
              disabled={busy}
              onClick={() => {
                if (!jobId) return
                setRerunning(true)
                setActionError(null)
                void rerunJob(jobId)
                  .then((created) => {
                    applyJob(created)
                    onOpenedJob?.(created)
                  })
                  .catch((error: unknown) => {
                    setActionError(
                      error instanceof ApiError
                        ? error.message
                        : t("sme.rerunResearchError"),
                    )
                  })
                  .finally(() => {
                    setRerunning(false)
                  })
              }}
            >
              {t("sme.rerunResearch")}
            </AdminButton>
          ) : null}
          <AdminButton
            variant="accent"
            size="sm"
            className={canResume || canRerun ? "shrink-0 gap-1.5" : "ml-auto shrink-0 gap-1.5"}
            onClick={onClose}
          >
            <X size={15} aria-hidden="true" />
            {t("sme.closeResearch")}
          </AdminButton>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {actionError ? (
            <p className="border-b border-[color:var(--border-hairline)] px-4 py-2 text-sm text-[color:var(--db-error)]">
              {actionError}
            </p>
          ) : null}
          {attemptId ? (
            <div className="theme-admin px-5 py-5">
              <ResearchMonitorPanel attemptId={attemptId} />
            </div>
          ) : (
            <div className="flex min-h-full items-center justify-center px-6 text-sm text-[color:var(--text-muted)]">
              {t("sme.researchStarting")}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
