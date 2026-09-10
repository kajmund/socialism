import { JsonFallback } from "@/components/execution/JsonFallback"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLocale } from "@/i18n"

function readString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function GenericPanelInputView({ input }: { input: Record<string, unknown> }) {
  const { t } = useLocale()
  const topic = readString(input.topic) || readString(input.question)
  const brief = readString(input.brief)
  return (
    <dl className="grid gap-3 text-sm">
      <div>
        <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("execution.panel.topic")}
        </dt>
        <dd className="mt-1 whitespace-pre-wrap">{topic || t("common.emDash")}</dd>
      </div>
      <div>
        <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("execution.panel.brief")}
        </dt>
        <dd className="mt-1 whitespace-pre-wrap">{brief || t("common.emDash")}</dd>
      </div>
    </dl>
  )
}

export function InputSnapshotView({
  attemptType,
  input,
}: {
  attemptType: string
  input: Record<string, unknown>
}) {
  const { t } = useLocale()
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("execution.sections.input")}</CardTitle>
      </CardHeader>
      <CardContent>
        {attemptType === "generic_panel" ? (
          <GenericPanelInputView input={input} />
        ) : (
          <JsonFallback value={input} />
        )}
      </CardContent>
    </Card>
  )
}
