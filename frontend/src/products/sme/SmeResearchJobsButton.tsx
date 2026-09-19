import type { Job } from "@/api/jobs"
import { Microscope } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useLocale } from "@/i18n"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import {
  listSmeResearchJobs,
} from "@/products/sme/smeResearchJobs"
import { SmeResearchModal } from "@/products/sme/SmeResearchModal"

type SelectedResearch = {
  jobId: string
  title: string
}

function jobStatusLabel(
  job: Job,
  t: (key: "sme.researchStatusPending" | "sme.researchStatusRunning" | "sme.researchStatusSucceeded" | "sme.researchStatusFailed") => string,
): string {
  switch (job.status) {
    case "pending":
      return t("sme.researchStatusPending")
    case "running":
      return t("sme.researchStatusRunning")
    case "succeeded":
      return t("sme.researchStatusSucceeded")
    case "failed":
      return t("sme.researchStatusFailed")
    default: {
      const exhaustive: never = job.status
      return exhaustive
    }
  }
}

export function SmeResearchJobsButton() {
  const { t } = useLocale()
  const { jobs } = useJobsRealtime()
  const [menuOpen, setMenuOpen] = useState(false)
  const [selected, setSelected] = useState<SelectedResearch | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const { ongoing, finished } = useMemo(() => listSmeResearchJobs(jobs), [jobs])

  useEffect(() => {
    if (!menuOpen) return
    function closeOutside(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false)
    }
    document.addEventListener("pointerdown", closeOutside)
    window.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOutside)
      window.removeEventListener("keydown", closeOnEscape)
    }
  }, [menuOpen])

  function openResearch(job: Job) {
    setMenuOpen(false)
    setSelected({ jobId: job.id, title: job.label })
  }

  function renderJob(job: Job) {
    return (
      <button
        key={job.id}
        type="button"
        role="menuitem"
        className="flex w-full flex-col gap-0.5 px-3 py-2.5 text-left hover:bg-db-ink-100"
        onClick={() => openResearch(job)}
      >
        <span className="truncate text-sm text-[color:var(--text-body)]">
          {job.label}
        </span>
        <span className="text-xs text-[color:var(--text-muted)]">
          {jobStatusLabel(job, t)}
        </span>
      </button>
    )
  }

  return (
    <>
      <div ref={rootRef} className="relative">
        <button
          type="button"
          className="relative grid size-9 place-items-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white"
          aria-label={
            ongoing.length > 0
              ? t("sme.activeResearchJobs", { count: ongoing.length })
              : t("sme.researchJobsAria")
          }
          title={t("sme.researchJobs")}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((current) => !current)}
        >
          <Microscope size={18} aria-hidden="true" />
          {ongoing.length > 0 ? (
            <span
              className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-db-gold-500 px-1 text-center text-[10px] font-semibold leading-4 text-db-navy-ink"
              aria-hidden="true"
            >
              {ongoing.length}
            </span>
          ) : null}
        </button>
        {menuOpen ? (
          <div
            className="absolute right-0 top-11 z-50 max-h-[min(420px,70vh)] w-72 overflow-y-auto rounded-[var(--radius-md)] border border-[color:var(--border-hairline)] bg-db-ink-0 py-1 text-[color:var(--text-body)] shadow-[var(--shadow-lg)]"
            role="menu"
            aria-label={t("sme.researchJobs")}
          >
            {ongoing.length === 0 && finished.length === 0 ? (
              <p className="px-3 py-4 text-sm text-[color:var(--text-muted)]">
                {t("sme.researchJobsEmpty")}
              </p>
            ) : null}
            {ongoing.length > 0 ? (
              <div>
                <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">
                  {t("sme.researchJobsOngoing")}
                </p>
                {ongoing.map(renderJob)}
              </div>
            ) : null}
            {finished.length > 0 ? (
              <div className={ongoing.length > 0 ? "mt-1 border-t border-[color:var(--border-hairline)] pt-1" : ""}>
                <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--text-muted)]">
                  {t("sme.researchJobsFinished")}
                </p>
                {finished.map(renderJob)}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      <SmeResearchModal
        open={selected != null}
        jobId={selected?.jobId ?? null}
        title={selected?.title ?? t("sme.researchJobs")}
        onClose={() => setSelected(null)}
        onOpenedJob={(job) => setSelected({ jobId: job.id, title: job.label })}
      />
    </>
  )
}
