import { GenericPanelFieldsView } from "@/components/execution/GenericPanelFieldsView"
import { JsonFallback } from "@/components/execution/JsonFallback"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLocale } from "@/i18n"

export function ConfigurationSnapshotView({
  attemptType,
  configuration,
  input,
}: {
  attemptType: string
  configuration: Record<string, unknown>
  input: Record<string, unknown>
}) {
  const { t } = useLocale()
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("execution.sections.configuration")}</CardTitle>
      </CardHeader>
      <CardContent>
        {attemptType === "generic_panel" ? (
          <GenericPanelFieldsView configuration={configuration} input={input} />
        ) : (
          <JsonFallback value={configuration} />
        )}
      </CardContent>
    </Card>
  )
}
