import { useEffect, useState } from "react"
import type { AttemptResult, EvidenceSet, ExecutionAttempt, ExecutionRun } from "@/api/execution"
import { AttemptDetail } from "@/components/execution/AttemptDetail"
import { AttemptList } from "@/components/execution/AttemptList"
import { resolveEvidenceRef, scrollToEvidenceItem } from "@/components/execution/evidenceRefs"
import { RunHeader } from "@/components/execution/RunHeader"
import { useLocale } from "@/i18n"

export type ExecutionLoadState = "loading" | "ready" | "not_found" | "forbidden" | "error"

export function ExecutionLoadMessage({ state }: { state: Exclude<ExecutionLoadState, "ready"> }) {
  const { t } = useLocale()
  const key =
    state === "loading"
      ? "execution.page.loading"
      : state === "not_found"
        ? "execution.page.notFound"
        : state === "forbidden"
          ? "execution.page.forbidden"
          : "execution.page.loadError"
  const className = state === "loading" ? "no-match" : "empty-state"
  return (
    <div className={className} data-execution-state={state} role={state === "loading" ? "status" : "alert"}>
      {t(key)}
    </div>
  )
}

export function ExecutionInspector({
  run,
  attempts,
  selectedAttempt,
  evidence,
  result,
  evidenceError = null,
  resultError = null,
  onSelectAttempt,
}: {
  run: ExecutionRun
  attempts: ExecutionAttempt[]
  selectedAttempt: ExecutionAttempt | null
  evidence: EvidenceSet | null
  result: AttemptResult | null
  evidenceError?: string | null
  resultError?: string | null
  onSelectAttempt: (attemptId: string) => void
}) {
  const { t } = useLocale()
  const [highlightedItemId, setHighlightedItemId] = useState<string | null>(null)

  useEffect(() => {
    setHighlightedItemId(null)
  }, [selectedAttempt?.id])

  function selectRef(ref: string) {
    const item = resolveEvidenceRef(ref, evidence?.items ?? [], result?.evidence_refs)
    if (item == null) return
    setHighlightedItemId(item.id)
    scrollToEvidenceItem(item.id)
  }

  return (
    <div className="wrap admin-page">
      <div className="admin-page-chrome">
        <div className="crumb">{t("execution.page.crumb")}</div>
        <RunHeader run={run} />
      </div>
      <div className="admin-page-body grid gap-6">
        <section>
          <h2
            className="mb-3"
            style={{
              font: "var(--text-h3)",
              fontFamily: "'Bai Jamjuree', sans-serif",
              fontWeight: 400,
              margin: 0,
            }}
          >
            {t("execution.attempt.listTitle")}
          </h2>
          <AttemptList
            attempts={attempts}
            selectedId={selectedAttempt?.id ?? null}
            onSelect={onSelectAttempt}
          />
        </section>
        {selectedAttempt ? (
          <AttemptDetail
            attempt={selectedAttempt}
            attempts={attempts}
            evidence={evidence}
            result={result}
            evidenceError={evidenceError}
            resultError={resultError}
            highlightedItemId={highlightedItemId}
            onSelectRef={selectRef}
          />
        ) : null}
      </div>
    </div>
  )
}
