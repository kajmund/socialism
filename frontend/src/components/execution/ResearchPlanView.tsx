import { JsonFallback } from "@/components/execution/JsonFallback"
import { researchNeedsFromSnapshot } from "@/components/execution/panelConfig"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLocale } from "@/i18n"

export function ResearchPlanView({
  snapshot,
}: {
  snapshot: Record<string, unknown> | null
}) {
  const { t } = useLocale()
  const needs = researchNeedsFromSnapshot(snapshot)
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("execution.sections.research")}</CardTitle>
      </CardHeader>
      <CardContent>
        {needs == null ? (
          <JsonFallback value={snapshot} />
        ) : needs.length === 0 ? (
          <p className="no-match m-0 text-left">{t("execution.research.empty")}</p>
        ) : (
          <ol className="grid gap-4">
            {needs.map((need) => (
              <li
                key={need.id}
                className="rounded-md border border-[color:var(--border-hairline)] bg-muted/30 p-3"
              >
                <p className="text-sm font-medium">{need.question || t("common.emDash")}</p>
                <dl className="mt-2 grid gap-2 text-sm text-[color:var(--text-muted)]">
                  <div>
                    <dt className="text-xs uppercase tracking-wide">{t("execution.research.whyNeeded")}</dt>
                    <dd className="mt-1 text-[color:var(--text-body)]">
                      {need.why_needed || t("common.emDash")}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide">
                      {t("execution.research.requestedBy")}
                    </dt>
                    <dd className="mt-1">{need.requested_by.join(", ") || t("common.emDash")}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide">
                      {t("execution.research.sourceTypes")}
                    </dt>
                    <dd className="mt-1">{need.source_types.join(", ") || t("common.emDash")}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}
