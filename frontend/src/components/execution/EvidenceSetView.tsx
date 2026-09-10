import type { EvidenceSet } from "@/api/execution"
import { EvidenceItemCard } from "@/components/execution/EvidenceItemCard"
import { formatWhen } from "@/components/execution/format"
import {
  evidenceSetStatusLabelKey,
  isEvidenceSetStatus,
} from "@/components/execution/status"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLocale } from "@/i18n"

export function EvidenceSetView({
  evidence,
  highlightedItemId,
}: {
  evidence: EvidenceSet | null
  highlightedItemId: string | null
}) {
  const { t, intl } = useLocale()
  const emDash = t("common.emDash")
  const items = evidence
    ? [...evidence.items].sort((a, b) => a.ordinal - b.ordinal || a.id.localeCompare(b.id))
    : []
  const setStatus =
    evidence && isEvidenceSetStatus(evidence.status)
      ? t(evidenceSetStatusLabelKey(evidence.status))
      : evidence?.status

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("execution.sections.evidence")}</CardTitle>
        {evidence ? (
          <p className="text-sm text-[color:var(--text-muted)]">
            {setStatus}
            {evidence.frozen_at
              ? ` · ${t("execution.evidence.frozenAt", {
                  when: formatWhen(evidence.frozen_at, intl, emDash),
                })}`
              : null}
          </p>
        ) : null}
      </CardHeader>
      <CardContent>
        {evidence == null || items.length === 0 ? (
          <p className="no-match m-0 text-left">{t("execution.evidence.empty")}</p>
        ) : (
          <div className="grid gap-3">
            {items.map((item) => (
              <EvidenceItemCard
                key={item.id}
                item={item}
                items={items}
                highlighted={item.id === highlightedItemId}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
