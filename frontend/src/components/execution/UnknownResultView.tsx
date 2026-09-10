import { JsonFallback } from "@/components/execution/JsonFallback"
import { useLocale } from "@/i18n"

export function UnknownResultView({
  resultType,
  payload,
  evidenceRefs,
}: {
  resultType: string
  payload: Record<string, unknown>
  evidenceRefs: Record<string, unknown>
}) {
  const { t } = useLocale()
  return (
    <div className="grid gap-3">
      <p className="text-sm text-[color:var(--text-muted)]">
        {t("execution.result.unknownType", { type: resultType })}
      </p>
      <JsonFallback value={{ payload, evidence_refs: evidenceRefs }} />
    </div>
  )
}
