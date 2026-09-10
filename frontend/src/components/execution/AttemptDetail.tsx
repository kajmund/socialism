import type { AttemptResult, EvidenceSet, ExecutionAttempt } from "@/api/execution"
import { attemptOrdinal, formatWhen } from "@/components/execution/format"
import { ConfigurationSnapshotView } from "@/components/execution/ConfigurationSnapshotView"
import { EvidenceSetView } from "@/components/execution/EvidenceSetView"
import { ExecutionResultView } from "@/components/execution/ExecutionResultView"
import { InputSnapshotView } from "@/components/execution/InputSnapshotView"
import { ResearchPlanView } from "@/components/execution/ResearchPlanView"
import {
  attemptStatusLabelKey,
  attemptStatusTagClass,
  attemptTypeLabelKey,
  isAttemptStatus,
} from "@/components/execution/status"
import { useLocale } from "@/i18n"

export function AttemptDetail({
  attempt,
  attempts,
  evidence,
  result,
  highlightedItemId,
  onSelectRef,
}: {
  attempt: ExecutionAttempt
  attempts: ExecutionAttempt[]
  evidence: EvidenceSet | null
  result: AttemptResult | null
  highlightedItemId: string | null
  onSelectRef: (ref: string) => void
}) {
  const { t, intl } = useLocale()
  const emDash = t("common.emDash")
  const ids = attempts.map((row) => row.id)
  const n = attemptOrdinal(ids, attempt.id)
  const parentOrdinal = attempt.parent_attempt_id
    ? attemptOrdinal(ids, attempt.parent_attempt_id)
    : null
  const typeKey = attemptTypeLabelKey(attempt.attempt_type)
  const statusLabel = isAttemptStatus(attempt.status)
    ? t(attemptStatusLabelKey(attempt.status))
    : attempt.status

  return (
    <div className="grid gap-4" data-attempt-detail={attempt.id}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2
            style={{
              font: "var(--text-h2)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
              margin: 0,
            }}
          >
            Attempt {n ?? emDash}
            {typeKey ? ` · ${t(typeKey)}` : ` · ${attempt.attempt_type}`}
          </h2>
          <p className="mt-1 text-sm text-[color:var(--text-muted)]">
            {t("execution.attempt.created", {
              when: formatWhen(attempt.created_at, intl, emDash),
            })}
            {parentOrdinal != null
              ? ` · ${t("execution.attempt.lineage", { n: parentOrdinal })}`
              : null}
          </p>
        </div>
        <span className={attemptStatusTagClass(attempt.status)}>{statusLabel}</span>
      </div>

      <InputSnapshotView attemptType={attempt.attempt_type} input={attempt.input_snapshot} />
      <ConfigurationSnapshotView
        attemptType={attempt.attempt_type}
        configuration={attempt.configuration_snapshot}
        input={attempt.input_snapshot}
      />
      <ResearchPlanView snapshot={attempt.research_plan_snapshot} />
      <EvidenceSetView evidence={evidence} highlightedItemId={highlightedItemId} />
      <ExecutionResultView
        result={result}
        items={evidence?.items ?? []}
        onSelectRef={onSelectRef}
      />
    </div>
  )
}
