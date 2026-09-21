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
  error = null,
}: {
  evidence: EvidenceSet | null
  highlightedItemId: string | null
  error?: string | null
}) {
  const { t, intl } = useLocale()
  const emDash = t("common.emDash")
  const items = evidence
    ? [...evidence.items].sort((a, b) => a.ordinal - b.ordinal || a.id.localeCompare(b.id))
    : []
  const byId = new Map(items.map((item) => [item.id, item]))
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
        {error ? (
          <p className="no-match m-0 text-left" role="alert" data-section-error="evidence">
            {error}
          </p>
        ) : evidence == null || items.length === 0 ? (
          <p className="no-match m-0 text-left">{t("execution.evidence.empty")}</p>
        ) : (
          <div className="grid gap-3">
            {evidence?.sources.map((source) => {
              const sourceItems = source.item_ids.flatMap((id) => {
                const item = byId.get(id)
                return item ? [item] : []
              })
              return (
                <section key={source.source_key} className="rounded-md border border-[color:var(--border-hairline)] p-3">
                  <h3 className="text-sm font-semibold">{source.title || t("common.emDash")}</h3>
                  <p className="mt-1 text-xs text-[color:var(--text-muted)]">
                    {t("execution.evidence.sourceSummary", {
                      needs: source.research_need_ids.length,
                      analyses: source.successful_analyses,
                      errors: source.error_count,
                    })}
                  </p>
                  <details className="mt-2" open={source.item_ids.includes(highlightedItemId ?? "")}>
                    <summary className="cursor-pointer text-xs underline">{t("execution.evidence.sourceDetails")}</summary>
                    <div className="mt-2 grid gap-2">
                      {sourceItems.map((item) => (
                        <EvidenceItemCard key={item.id} item={item} items={items} highlighted={item.id === highlightedItemId} />
                      ))}
                    </div>
                  </details>
                </section>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
