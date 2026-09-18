import type { ResearchOverviewQuestion } from "@/api/execution"
import { useLocale, type MessageKey } from "@/i18n"
import { cn } from "@/lib/utils"

const statusKeys: Record<string, MessageKey> = {
  answered: "execution.researchMonitor.status.answered", running: "execution.researchMonitor.status.running", waiting: "execution.researchMonitor.status.waiting", insufficient: "execution.researchMonitor.status.insufficient", unanswered: "execution.researchMonitor.status.unanswered", failed: "execution.researchMonitor.status.failed", blocked: "execution.researchMonitor.status.blocked",
}

function statusTone(status: string): string {
  if (status === "answered") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
  if (status === "running") return "border-db-gold-500/40 bg-db-gold-500/10 text-db-gold-500"
  if (status === "waiting") return "border-slate-500/30 bg-slate-500/10 text-slate-300"
  return "border-amber-500/30 bg-amber-500/10 text-amber-300"
}

export function ResearchQuestionCard({ question }: { question: ResearchOverviewQuestion }) {
  const { t } = useLocale()
  const foundSources = question.sources.filter((source) => source.status === "found")
  return (
    <details className="group rounded-xl border border-white/10 bg-white/[0.025] open:border-db-gold-500/30">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-4 p-4">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2"><span className={cn("rounded-full border px-2 py-0.5 text-xs font-medium", statusTone(question.status))}>{t(statusKeys[question.status] ?? "execution.researchMonitor.status.waiting")}</span>{question.assigned_to ? <span className="text-xs text-muted-foreground">{t("execution.researchMonitor.assignedTo", { name: question.assigned_to.name })}</span> : null}</div>
          <h3 className="text-sm font-medium leading-6 text-foreground">{question.question}</h3>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">{question.raised_by.length > 0 ? <span>{t("execution.researchMonitor.raisedBy", { names: question.raised_by.map((expert) => expert.name).join(", ") })}</span> : null}{question.dependency_ids.length > 0 ? <span>{t("execution.researchMonitor.dependsOn", { count: question.dependency_ids.length })}</span> : null}<span>{t("execution.researchMonitor.sources", { count: foundSources.length })}</span></div>
        </div>
        <span className="mt-1 text-db-gold-500 transition-transform group-open:rotate-90">›</span>
      </summary>
      <div className="grid gap-4 border-t border-white/10 px-4 py-4 lg:grid-cols-2">
        <div className="space-y-4">{question.why_needed ? <Info label={t("execution.researchMonitor.whyNeeded")} text={question.why_needed} /> : null}<Info label={t("execution.researchMonitor.specificQuestion")} text={question.specific_question} />{question.outcome_reason ? <Info label={t("execution.researchMonitor.reason")} text={question.outcome_reason} warning /> : null}{question.assessment_rationale ? <Info label={t("execution.researchMonitor.assessment")} text={question.assessment_rationale} /> : null}{question.completeness_rationale ? <Info label={t("execution.researchMonitor.completeness")} text={question.completeness_rationale} /> : null}</div>
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("execution.researchMonitor.sources", { count: question.sources.length })}</h4>
          {question.sources.length === 0 ? <p className="text-sm text-muted-foreground">{t("execution.researchMonitor.noSources")}</p> : <div className="space-y-2">{question.sources.map((source) => <div key={source.id} className="rounded-lg border border-white/10 bg-black/10 p-3"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium">{source.title ?? source.provider ?? source.source_type}</p><p className="mt-1 text-xs text-muted-foreground">{source.provider ?? source.source_type}{source.locator ? ` · ${source.locator}` : ""}</p></div><span className="text-xs text-muted-foreground">{t(source.status === "found" ? "execution.researchMonitor.sourceStatus.found" : source.status === "error" ? "execution.researchMonitor.sourceStatus.error" : "execution.researchMonitor.sourceStatus.notFound")}</span></div>{source.excerpt ? <p className="mt-2 text-sm leading-5 text-muted-foreground">{source.excerpt}</p> : null}{source.source_url ? <a className="mt-2 inline-block text-xs font-medium text-db-gold-500 hover:underline" href={source.source_url} target="_blank" rel="noreferrer">{t("execution.researchMonitor.openSource")}</a> : null}</div>)}</div>}
        </div>
      </div>
    </details>
  )
}

function Info({ label, text, warning = false }: { label: string; text: string; warning?: boolean }) {
  return <div><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</h4><p className={cn("text-sm leading-6", warning && "text-amber-200")}>{text}</p></div>
}
