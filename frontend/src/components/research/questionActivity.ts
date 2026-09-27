import type { ResearchOverviewQuestionNode, ResearchProgressEvent } from "@/api/execution"
import type { MessageKey, TranslateParams } from "@/i18n"

export type QuestionActivityLine = {
  id: string
  at: string
  key: MessageKey
  params?: TranslateParams
}

export type QuestionActivity = {
  statusKey: MessageKey
  statusParams?: TranslateParams
  lines: QuestionActivityLine[]
}

const ACTIVITY_PREFIX = "execution.researchMonitor.tree.activity" as const

function activityKey(name: string): MessageKey {
  return `${ACTIVITY_PREFIX}.${name}` as MessageKey
}

function numberField(payload: Record<string, unknown>, name: string): number | null {
  const value = payload[name]
  return typeof value === "number" ? value : null
}

function belongsToQuestion(
  node: ResearchOverviewQuestionNode,
  event: ResearchProgressEvent,
): boolean {
  const { payload } = event
  if (payload.question_id === node.id) return true
  const needId = node.research_need_id
  if (!needId) return false
  if (payload.research_need_id === needId) return true
  return Array.isArray(payload.research_need_ids) && payload.research_need_ids.includes(needId)
}

function lineFor(event: ResearchProgressEvent): QuestionActivityLine | null {
  const base = { id: event.id, at: event.occurred_at }
  switch (event.event_type) {
    case "question_atomicity_started":
      return { ...base, key: activityKey("analyzing") }
    case "question_atomicity_completed":
      return { ...base, key: activityKey("analyzed") }
    case "question_decomposition_started":
      return { ...base, key: activityKey("splitting") }
    case "question_decomposed": {
      if (
        event.payload.decision === "rejected"
        && (event.payload.decomposition_result === "exhausted" || event.payload.fallback === "best_effort_retrieval")
      ) {
        return { ...base, key: activityKey("couldNotSplit") }
      }
      if (event.payload.decision === "rejected") {
        return { ...base, key: activityKey("keptWhole") }
      }
      const count = numberField(event.payload, "child_count")
      if (count == null || count < 2) return null
      return { ...base, key: activityKey("areas"), params: { count } }
    }
    case "question_research_started":
    case "need_running":
      return { ...base, key: activityKey("searching") }
    case "knowledge_reuse_completed": {
      const count = numberField(event.payload, "reused_count") ?? 0
      return count > 0
        ? { ...base, key: activityKey("reusing"), params: { count } }
        : { ...base, key: activityKey("noReuse") }
    }
    case "evidence_not_found":
      return { ...base, key: activityKey("evidenceMissing") }
    case "evidence_error":
      return { ...base, key: activityKey("evidenceError") }
    case "need_completed":
      return { ...base, key: activityKey("searchDone") }
    case "answer_synthesis_started":
      return { ...base, key: activityKey("writing") }
    case "answer_synthesized":
      return { ...base, key: activityKey("answerReady") }
    case "question_completeness_started":
      return { ...base, key: activityKey("checking") }
    case "question_completeness_completed":
      return { ...base, key: activityKey("checked") }
    case "question_gap_detected":
      return { ...base, key: activityKey("gap") }
    case "question_failed":
    case "need_failed":
      return { ...base, key: activityKey("failed") }
    case "question_tree_max_depth_reached":
      return { ...base, key: activityKey("unfinished") }
    default:
      return null
  }
}

function collapseEvidence(events: ResearchProgressEvent[]): QuestionActivityLine[] {
  const lines: QuestionActivityLine[] = []
  let found: ResearchProgressEvent[] = []
  let seenEvidence = false
  const flush = () => {
    if (found.length === 0) return
    const first = found[0]
    lines.push(
      found.length === 1
        ? { id: first.id, at: first.occurred_at, key: activityKey("evidenceFound") }
        : {
            id: first.id,
            at: found[found.length - 1].occurred_at,
            key: activityKey("evidenceFoundCount"),
            params: { count: found.length },
          },
    )
    found = []
    seenEvidence = true
  }
  for (const event of events) {
    if (event.event_type === "evidence_found") {
      found.push(event)
      continue
    }
    flush()
    if (seenEvidence && (event.event_type === "need_running" || event.event_type === "question_research_started")) {
      continue
    }
    const line = lineFor(event)
    if (line) lines.push(line)
  }
  flush()
  const compact: QuestionActivityLine[] = []
  for (const line of lines) {
    const previous = compact[compact.length - 1]
    if (previous && previous.key === line.key && previous.params?.count === line.params?.count) {
      continue
    }
    compact.push(line)
  }
  return compact
}

function statusWhileResearching(lines: QuestionActivityLine[]): {
  statusKey: MessageKey
  statusParams?: TranslateParams
} {
  const searching = activityKey("searching")
  let statusKey = searching
  let statusParams: TranslateParams | undefined
  let foundEvidence = false
  for (const line of lines) {
    if (line.key === activityKey("evidenceFound") || line.key === activityKey("evidenceFoundCount")) {
      foundEvidence = true
      statusKey = line.key
      statusParams = line.params
      continue
    }
    if (foundEvidence && line.key === searching) continue
    if (
      line.key === searching ||
      line.key === activityKey("reusing") ||
      line.key === activityKey("noReuse") ||
      line.key === activityKey("evidenceMissing") ||
      line.key === activityKey("evidenceError") ||
      line.key === activityKey("searchDone")
    ) {
      statusKey = line.key
      statusParams = line.params
    }
  }
  return { statusKey, statusParams }
}

export function questionActivity(
  node: ResearchOverviewQuestionNode,
  events: ResearchProgressEvent[],
): QuestionActivity {
  const lines = collapseEvidence(events.filter((event) => belongsToQuestion(node, event)))
  if (node.phase !== "researching") {
    return {
      statusKey: `execution.researchMonitor.tree.phase.${node.phase}` as MessageKey,
      lines,
    }
  }
  const status = statusWhileResearching(lines)
  return { ...status, lines }
}
