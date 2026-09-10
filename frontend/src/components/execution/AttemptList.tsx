import type { ExecutionAttempt } from "@/api/execution"
import { attemptOrdinal, formatWhen } from "@/components/execution/format"
import {
  attemptStatusLabelKey,
  attemptStatusTagClass,
  attemptTypeLabelKey,
  isAttemptStatus,
} from "@/components/execution/status"
import { cn } from "@/lib/utils"
import { useLocale } from "@/i18n"

export function AttemptList({
  attempts,
  selectedId,
  onSelect,
}: {
  attempts: ExecutionAttempt[]
  selectedId: string | null
  onSelect: (attemptId: string) => void
}) {
  const { t, intl } = useLocale()
  const emDash = t("common.emDash")
  const ids = attempts.map((attempt) => attempt.id)

  if (attempts.length === 0) {
    return <div className="no-match">{t("execution.attempt.empty")}</div>
  }

  return (
    <div className="admin-list-stack" role="list" aria-label={t("execution.attempt.listAria")}>
      {attempts.map((attempt, index) => {
        const n = index + 1
        const selected = attempt.id === selectedId
        const typeKey = attemptTypeLabelKey(attempt.attempt_type)
        const statusLabel = isAttemptStatus(attempt.status)
          ? t(attemptStatusLabelKey(attempt.status))
          : attempt.status
        const parentOrdinal = attempt.parent_attempt_id
          ? attemptOrdinal(ids, attempt.parent_attempt_id)
          : null
        const evidence = attempt.evidence
        return (
          <button
            key={attempt.id}
            type="button"
            role="listitem"
            data-attempt-id={attempt.id}
            data-attempt-status={attempt.status}
            aria-pressed={selected}
            aria-label={t("execution.attempt.selectAria", { n })}
            className={cn(
              "admin-list-row w-full cursor-pointer text-left",
              selected && "bg-[color-mix(in_srgb,var(--db-gold-100)_40%,transparent)]",
            )}
            onClick={() => onSelect(attempt.id)}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="nm">
                  Attempt {n}
                  {typeKey ? ` · ${t(typeKey)}` : ` · ${attempt.attempt_type}`}
                </span>
                <span className={attemptStatusTagClass(attempt.status)}>{statusLabel}</span>
              </div>
              <div className="meta mt-1">
                {t("execution.attempt.created", {
                  when: formatWhen(attempt.created_at, intl, emDash),
                })}
                {parentOrdinal != null
                  ? ` · ${t("execution.attempt.lineage", { n: parentOrdinal })}`
                  : null}
              </div>
              <div className="cell mt-1">
                {evidence
                  ? t("execution.attempt.evidenceCounts", {
                      found: evidence.found_count,
                      notFound: evidence.not_found_count,
                      error: evidence.error_count,
                    })
                  : t("execution.attempt.noEvidence")}
                {" · "}
                {attempt.result
                  ? t("execution.attempt.hasResult")
                  : t("execution.attempt.noResult")}
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
