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
import { loadStateFromError, shouldFetchEvidence, shouldFetchResult } from "@/components/execution/fetchPolicy"
import { AdminShell } from "@/components/layout/AdminShell"

export function ExecutionRunPage() {
  const { runId } = useParams<{ runId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedAttemptId = searchParams.get("attempt")

  const [run, setRun] = useState<ExecutionRun | null>(null)
  const [attempts, setAttempts] = useState<ExecutionAttempt[]>([])
  const [selected, setSelected] = useState<ExecutionAttempt | null>(null)
  const [evidence, setEvidence] = useState<EvidenceSet | null>(null)
  const [result, setResult] = useState<AttemptResult | null>(null)
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
      return
    }
    let cancelled = false
    setSelected(null)
    setEvidence(null)
    setResult(null)
    getExecutionAttempt(selectedId)
      .then(async (detail) => {
        if (cancelled) return
        setSelected(detail)
        if (shouldFetchEvidence(detail)) {
          try {
            const nextEvidence = await getExecutionEvidence(detail.id)
            if (!cancelled) setEvidence(nextEvidence)
          } catch {
            if (!cancelled) setEvidence(null)
          }
        }
        if (shouldFetchResult(detail)) {
          try {
            const nextResult = await getExecutionResult(detail.id)
            if (!cancelled) setResult(nextResult)
          } catch {
            if (!cancelled) setResult(null)
          }
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState(loadStateFromError(err))
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, state])

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
          result={result}
          onSelectAttempt={selectAttempt}
        />
      )}
    </AdminShell>
  )
}
