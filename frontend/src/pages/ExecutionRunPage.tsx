import { useEffect, useState } from "react"
import { useParams, useSearchParams } from "react-router-dom"
import {
  getExecutionAttempt,
  getExecutionEvidence,
  getExecutionResult,
  getExecutionRun,
  listExecutionAttempts,
  type AttemptResult,
  type EvidenceSet,
  type ExecutionAttempt,
  type ExecutionRun,
} from "@/api/execution"
import {
  ExecutionInspector,
  ExecutionLoadMessage,
  type ExecutionLoadState,
} from "@/components/execution/ExecutionInspector"
import {
  isExpectedMissing,
  loadStateFromError,
  sectionErrorMessage,
  shouldFetchEvidence,
  shouldFetchResult,
} from "@/components/execution/fetchPolicy"
import { AdminShell } from "@/components/layout/AdminShell"
import { useLocale } from "@/i18n"

export function ExecutionRunPage() {
  const { t } = useLocale()
  const { runId } = useParams<{ runId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedAttemptId = searchParams.get("attempt")

  const [run, setRun] = useState<ExecutionRun | null>(null)
  const [attempts, setAttempts] = useState<ExecutionAttempt[]>([])
  const [selected, setSelected] = useState<ExecutionAttempt | null>(null)
  const [evidence, setEvidence] = useState<EvidenceSet | null>(null)
  const [result, setResult] = useState<AttemptResult | null>(null)
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [resultError, setResultError] = useState<string | null>(null)
  const [state, setState] = useState<ExecutionLoadState>("loading")

  useEffect(() => {
    if (!runId) {
      setState("not_found")
      return
    }
    let cancelled = false
    setState("loading")
    setRun(null)
    setAttempts([])
    setSelected(null)
    setEvidence(null)
    setResult(null)
    setEvidenceError(null)
    setResultError(null)
    Promise.all([getExecutionRun(runId), listExecutionAttempts(runId)])
      .then(([nextRun, nextAttempts]) => {
        if (cancelled) return
        setRun(nextRun)
        setAttempts(nextAttempts)
        setState("ready")
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState(loadStateFromError(err))
      })
    return () => {
      cancelled = true
    }
  }, [runId])

  const selectedId =
    requestedAttemptId && attempts.some((attempt) => attempt.id === requestedAttemptId)
      ? requestedAttemptId
      : (attempts[0]?.id ?? null)

  useEffect(() => {
    if (state !== "ready" || selectedId == null) {
      setSelected(null)
      setEvidence(null)
      setResult(null)
      setEvidenceError(null)
      setResultError(null)
      return
    }
    let cancelled = false
    setSelected(null)
    setEvidence(null)
    setResult(null)
    setEvidenceError(null)
    setResultError(null)
    getExecutionAttempt(selectedId)
      .then(async (detail) => {
        if (cancelled) return
        setSelected(detail)
        const evidenceFallback = t("execution.evidence.loadError")
        const resultFallback = t("execution.result.loadError")
        const [nextEvidence, nextResult] = await Promise.all([
          shouldFetchEvidence(detail)
            ? getExecutionEvidence(detail.id)
                .then((value) => ({ value, error: null as string | null }))
                .catch((err: unknown) =>
                  isExpectedMissing(err)
                    ? { value: null, error: null }
                    : { value: null, error: sectionErrorMessage(err, evidenceFallback) },
                )
            : Promise.resolve({ value: null, error: null as string | null }),
          shouldFetchResult(detail)
            ? getExecutionResult(detail.id)
                .then((value) => ({ value, error: null as string | null }))
                .catch((err: unknown) =>
                  isExpectedMissing(err)
                    ? { value: null, error: null }
                    : { value: null, error: sectionErrorMessage(err, resultFallback) },
                )
            : Promise.resolve({ value: null, error: null as string | null }),
        ])
        if (cancelled) return
        setEvidence(nextEvidence.value)
        setEvidenceError(nextEvidence.error)
        setResult(nextResult.value)
        setResultError(nextResult.error)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState(loadStateFromError(err))
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, state, t])

  function selectAttempt(attemptId: string) {
    const next = new URLSearchParams(searchParams)
    next.set("attempt", attemptId)
    setSearchParams(next, { replace: true })
  }

  return (
    <AdminShell>
      {state !== "ready" || run == null ? (
        <div className="wrap">
          <ExecutionLoadMessage state={state === "ready" ? "error" : state} />
        </div>
      ) : (
        <ExecutionInspector
          run={run}
          attempts={attempts}
          selectedAttempt={selected}
          evidence={evidence}
          evidenceError={evidenceError}
          result={result}
          resultError={resultError}
          onSelectAttempt={selectAttempt}
        />
      )}
    </AdminShell>
  )
}
