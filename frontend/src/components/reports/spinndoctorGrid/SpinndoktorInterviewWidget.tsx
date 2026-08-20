import { useEffect, useState } from "react"
import { getRun } from "@/api/runs"
import type { SpindoctorWidget } from "@/api/spindoctorWidgets"
import { RunInterviewChat } from "@/components/runs/RunInterviewChat"
import { ApiError } from "@/lib/api"
import { findRunVariant } from "@/lib/runResults"
import type { OasisVariantResult } from "@/data/runs-types"
import { useLocale } from "@/i18n"

type SpinndoktorInterviewWidgetProps = {
  widget: SpindoctorWidget
}

export function SpinndoktorInterviewWidget({ widget }: SpinndoktorInterviewWidgetProps) {
  const { t } = useLocale()
  const [variant, setVariant] = useState<OasisVariantResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (
      widget.run_id == null ||
      !widget.attempt_id ||
      !widget.variant_id ||
      widget.through_tick_index == null
    ) {
      setVariant(null)
      setError(t("spinndoctor.grid.interviewMissingContext"))
      return
    }

    let cancelled = false
    void (async () => {
      try {
        const run = await getRun(widget.run_id!)
        if (cancelled) return
        const resolved = findRunVariant(run.results, widget.attempt_id!, widget.variant_id!)
        if (!resolved) {
          setVariant(null)
          setError(t("spinndoctor.grid.interviewVariantMissing"))
          return
        }
        setVariant(resolved)
        setError(null)
      } catch (err) {
        if (cancelled) return
        setVariant(null)
        setError(err instanceof ApiError ? err.message : t("spinndoctor.grid.interviewLoadError"))
      }
    })()

    return () => {
      cancelled = true
    }
  }, [
    widget.attempt_id,
    widget.run_id,
    widget.through_tick_index,
    widget.variant_id,
    t,
  ])

  if (error) {
    return (
      <p className="spinndoctor-widget-interview-error" role="alert">
        {error}
      </p>
    )
  }

  if (
    !variant ||
    widget.run_id == null ||
    !widget.attempt_id ||
    widget.through_tick_index == null
  ) {
    return (
      <p className="text-xs text-muted-foreground">{t("spinndoctor.grid.interviewLoading")}</p>
    )
  }

  return (
    <RunInterviewChat
      runId={widget.run_id}
      attemptId={widget.attempt_id}
      variant={variant}
      tickIndex={widget.through_tick_index}
      initialPersonaId={widget.persona_id}
      personaDisplayName={widget.persona_name}
      compact
      showClear={false}
    />
  )
}
