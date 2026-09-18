import { Link } from "react-router-dom"
import { ResearchEventLog } from "@/components/research/ResearchEventLog"
import { ResearchQuestionCard } from "@/components/research/ResearchQuestionCard"
import { useResearchMonitor } from "@/components/research/useResearchMonitor"
import { Card, CardContent } from "@/components/ui/card"
import { useLocale } from "@/i18n"
import { cn } from "@/lib/utils"

type Props = { attemptId: string; compact?: boolean; href?: string }

export function ResearchMonitorPanel({ attemptId, compact = false, href }: Props) {
  const { t } = useLocale()
  const live = useResearchMonitor(attemptId)
  if (live.loading) return <div className="no-match" role="status">{t("execution.researchMonitor.loading")}</div>
  if (live.error || !live.overview) return <div className="empty-state" role="alert">{t("execution.researchMonitor.loadError")}</div>

  const { overview } = live
  const isRunning = overview.phase === "researching"
  const hasGaps = overview.phase === "completed_with_gaps"
  const notNeeded = overview.phase === "not_needed"
  const gaps = overview.counts.insufficient + overview.counts.unanswered + overview.counts.failed + overview.counts.blocked
  const title = isRunning ? t("execution.researchMonitor.researchingTitle") : notNeeded ? t("execution.researchMonitor.notNeededTitle") : hasGaps ? t("execution.researchMonitor.gapsTitle") : t("execution.researchMonitor.completedTitle")
  const body = isRunning ? t("execution.researchMonitor.researchingBody") : notNeeded ? t("execution.researchMonitor.notNeededBody") : hasGaps ? t("execution.researchMonitor.gapsBody") : t("execution.researchMonitor.completedBody")
  const percent = overview.counts.total === 0 ? 0 : Math.round(((overview.counts.answered + gaps) / overview.counts.total) * 100)

  if (compact) {
    return (
      <Card className="border-db-gold-500/30 bg-db-gold-500/[0.04]">
        <CardContent className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <div className="mb-2 flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", isRunning ? "animate-pulse bg-db-gold-500" : hasGaps ? "bg-amber-400" : "bg-emerald-400")} />
                <h3 className="font-semibold">{title}</h3>
              </div>
              <p className="text-sm leading-6 text-muted-foreground">{body}</p>
              {!notNeeded ? <p className="mt-2 text-sm font-medium">{t("execution.researchMonitor.summary", { answered: overview.counts.answered, total: overview.counts.total, running: overview.counts.running, waiting: overview.counts.waiting })}</p> : null}
            </div>
            {href ? <Link className="text-sm font-medium text-db-gold-500 hover:underline" to={href}>{t("execution.researchMonitor.open")}</Link> : null}
          </div>
        </CardContent>
      </Card>
    )
  }

  const stats = [
    ["answered", overview.counts.answered, "execution.researchMonitor.counts.answered"],
    ["running", overview.counts.running, "execution.researchMonitor.counts.running"],
    ["waiting", overview.counts.waiting, "execution.researchMonitor.counts.waiting"],
    ["gaps", gaps, "execution.researchMonitor.counts.gaps"],
  ] as const

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden border-db-gold-500/30 bg-gradient-to-br from-db-gold-500/[0.09] to-transparent">
        <CardContent className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-db-gold-500">
                <span className={cn("h-2 w-2 rounded-full", live.wsStatus === "open" ? "bg-emerald-400" : "bg-amber-400")} />
                {live.wsStatus === "open" ? t("execution.researchMonitor.live") : t("execution.researchMonitor.reconnecting")}
              </div>
              <h1 className="text-2xl font-medium">{title}</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{body}</p>
            </div>
            <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-muted-foreground">{t("execution.researchMonitor.persisted")}</span>
          </div>
          {!notNeeded ? <div className="mt-6 h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-db-gold-500 transition-[width] duration-500" style={{ width: `${percent}%` }} /></div> : null}
          {!notNeeded ? <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {stats.map(([key, value, label]) => <div key={key} className="rounded-lg border border-white/10 bg-black/10 p-3"><div className="text-2xl font-medium">{value}</div><div className="text-xs text-muted-foreground">{t(label)}</div></div>)}
          </div> : null}
        </CardContent>
      </Card>
      <div className="grid grid-cols-4 gap-2" aria-label={t("execution.researchMonitor.progress")}>
        {(["questions", "evidence", "assessment", "review"] as const).map((stage, index) => <div key={stage} className={cn("rounded-lg border px-3 py-2 text-center text-xs", !notNeeded && (index < 3 || !isRunning) ? "border-db-gold-500/30 bg-db-gold-500/[0.06] text-db-gold-500" : "border-white/10 text-muted-foreground")}>{t(`execution.researchMonitor.stages.${stage}`)}</div>)}
      </div>
      <section>
        <h2 className="mb-3 text-lg font-medium">{t("execution.researchMonitor.questionsTitle")}</h2>
        {overview.questions.length === 0 ? <div className="empty-state">{t(notNeeded ? "execution.researchMonitor.questionsNotNeeded" : "execution.researchMonitor.questionsEmpty")}</div> : <div className="space-y-3">{overview.questions.map((question) => <ResearchQuestionCard key={question.id} question={question} />)}</div>}
      </section>
      <ResearchEventLog events={live.events} />
    </div>
  )
}
