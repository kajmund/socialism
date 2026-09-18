import { Briefcase } from "lucide-react"
import { Link } from "react-router-dom"
import { useLocale } from "@/i18n"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

export function SmeJobsButton() {
  const { t } = useLocale()
  const { activeCount } = useJobsRealtime()
  return (
    <Link
      to="/jobs"
      className="relative grid size-9 place-items-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white"
      aria-label={
        activeCount > 0
          ? t("sme.activeJobs", { count: activeCount })
          : t("sme.jobsAria")
      }
      title={t("sme.jobs")}
    >
      <Briefcase size={18} aria-hidden="true" />
      {activeCount > 0 ? (
        <span
          className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-db-gold-500 px-1 text-center text-[10px] font-semibold leading-4 text-db-navy-ink"
          aria-hidden="true"
        >
          {activeCount}
        </span>
      ) : null}
    </Link>
  )
}
