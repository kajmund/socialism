import type { AttemptResult, EvidenceSetItem } from "@/api/execution"
import { resolveEvidenceRef } from "@/components/execution/evidenceRefs"
import {
  GenericPanelResultView,
  parseGenericPanelPayload,
} from "@/components/execution/GenericPanelResultView"
import { UnknownResultView } from "@/components/execution/UnknownResultView"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLocale } from "@/i18n"

function resolvedRefSet(
  refs: string[],
  items: readonly EvidenceSetItem[],
  evidenceRefs: Record<string, unknown>,
): Set<string> {
  const resolved = new Set<string>()
  for (const ref of refs) {
    if (resolveEvidenceRef(ref, items, evidenceRefs) != null) resolved.add(ref)
  }
  return resolved
}

export function ExecutionResultView({
  result,
  items,
  onSelectRef,
}: {
  result: AttemptResult | null
  items: readonly EvidenceSetItem[]
  onSelectRef: (ref: string) => void
}) {
  const { t } = useLocale()
  const panel =
    result?.result_type === "generic_panel" ? parseGenericPanelPayload(result.payload) : null
  const allRefs = panel?.claims.flatMap((claim) => claim.evidence_refs) ?? []
  const resolvedRefs = result
    ? resolvedRefSet(allRefs, items, result.evidence_refs)
    : new Set<string>()

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("execution.sections.result")}</CardTitle>
      </CardHeader>
      <CardContent>
        {result == null ? (
          <p className="no-match m-0 text-left">{t("execution.result.empty")}</p>
        ) : panel != null ? (
          <GenericPanelResultView
            payload={panel}
            resolvedRefs={resolvedRefs}
            onSelectRef={onSelectRef}
          />
        ) : (
          <UnknownResultView
            resultType={result.result_type}
            payload={result.payload}
            evidenceRefs={result.evidence_refs}
          />
        )}
      </CardContent>
    </Card>
  )
}
