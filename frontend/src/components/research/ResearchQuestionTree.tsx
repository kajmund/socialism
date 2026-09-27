import type { ResearchOverviewQuestionNode, ResearchProgressEvent } from "@/api/execution"
import { questionActivity } from "@/components/research/questionActivity"
import { useLocale, type MessageKey } from "@/i18n"
import { cn } from "@/lib/utils"

type Props = { nodes: ResearchOverviewQuestionNode[]; events?: ResearchProgressEvent[] }

export function ResearchQuestionTree({ nodes, events = [] }: Props) {
  const children = new Map<string | null, ResearchOverviewQuestionNode[]>()
  for (const node of nodes) {
    const key = node.parent_question_id
    children.set(key, [...(children.get(key) ?? []), node])
  }
  const roots = children.get(null) ?? nodes.filter((node) => node.depth === 0)
  return <div className="space-y-3">{roots.map((node) => <TreeNode key={node.id} node={node} childMap={children} events={events ?? []} />)}</div>
}

function EvidenceList({ node }: { node: ResearchOverviewQuestionNode }) {
  const { t } = useLocale()
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("execution.researchMonitor.tree.evidence")}</h4>
      <div className="space-y-2">{node.sources.map((source) => <div key={source.id} className="rounded-lg border border-white/10 bg-black/10 p-3"><p className="text-sm font-medium">{source.title ?? source.provider ?? source.source_type}</p>{source.excerpt ? <p className="mt-1 text-sm text-muted-foreground">{source.excerpt}</p> : null}{source.source_url ? <a href={source.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-db-gold-500 hover:underline">{t("execution.researchMonitor.openSource")}</a> : null}</div>)}</div>
    </div>
  )
}

function unansweredCopy(node: ResearchOverviewQuestionNode): MessageKey {
  if (node.phase === "failed") return "execution.researchMonitor.tree.executionFailed"
  if (node.phase === "unresolved") return "execution.researchMonitor.tree.unresolved"
  if (node.phase === "not_required") return "execution.researchMonitor.tree.notRequired"
  if (node.completeness === "insufficient") return "execution.researchMonitor.tree.notSplitFurther"
  return "execution.researchMonitor.tree.noAnswer"
}

function TreeNode({ node, childMap, events }: { node: ResearchOverviewQuestionNode; childMap: Map<string | null, ResearchOverviewQuestionNode[]>; events: ResearchProgressEvent[] }) {
  const { t, intl } = useLocale()
  const descendants = childMap.get(node.id) ?? []
  const activity = questionActivity(node, events)
  const answer = node.current_answer
  const time = new Intl.DateTimeFormat(intl, { timeStyle: "short" })
  return (
    <div className={cn(node.depth > 0 && "ml-4 border-l border-white/10 pl-4")}>
      <details open={node.depth === 0} className="rounded-xl border border-white/10 bg-white/[0.025] open:border-db-gold-500/30">
        <summary className="cursor-pointer list-none p-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-db-gold-500/30 bg-db-gold-500/10 px-2 py-0.5 text-xs text-db-gold-500">{t(activity.statusKey, activity.statusParams)}</span>
            {node.created_from === "gap" ? <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-200">{t("execution.researchMonitor.tree.gapQuestion")}</span> : null}
            {node.completeness ? <span className="text-xs text-muted-foreground">{t("execution.researchMonitor.tree.completeness", { status: t(`execution.researchMonitor.tree.answerStatus.${node.completeness}` as MessageKey) })}</span> : null}
          </div>
          <h3 className="text-sm font-medium leading-6">{node.question}</h3>
        </summary>
        <div className="space-y-4 border-t border-white/10 p-4">
          {activity.lines.length > 0 ? <div><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("execution.researchMonitor.tree.activityTitle")}</h4><ol className="space-y-1">{activity.lines.map((line) => <li key={line.id} className="flex gap-3 text-sm leading-6"><time className="w-12 shrink-0 text-xs text-muted-foreground">{time.format(new Date(line.at))}</time><span>{t(line.key, line.params)}</span></li>)}</ol></div> : null}
          {!answer && node.sources.length > 0 ? <EvidenceList node={node} /> : null}
          {answer ? <div><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("execution.researchMonitor.tree.currentAnswer")}</h4><p className="text-sm leading-6">{answer.text}</p><p className="mt-1 text-xs text-muted-foreground">{t(`execution.researchMonitor.tree.answerStatus.${answer.status}` as MessageKey)}</p></div> : <p className="text-sm text-muted-foreground">{t(unansweredCopy(node))}</p>}
          {answer && node.sources.length > 0 ? <EvidenceList node={node} /> : null}
          {answer && answer.child_answer_ids.length > 0 ? <p className="text-xs text-muted-foreground">{t("execution.researchMonitor.tree.groundedInChildren", { count: answer.child_answer_ids.length })}</p> : null}
        </div>
      </details>
      {descendants.length > 0 ? <div className="mt-3 space-y-3">{descendants.map((child) => <TreeNode key={child.id} node={child} childMap={childMap} events={events} />)}</div> : null}
    </div>
  )
}
