import { extractGenericPanelFields } from "@/components/execution/panelConfig"
import { useLocale } from "@/i18n"

export function GenericPanelFieldsView({
  configuration,
  input,
}: {
  configuration: Record<string, unknown>
  input: Record<string, unknown>
}) {
  const { t } = useLocale()
  const fields = extractGenericPanelFields(configuration, input)
  return (
    <dl className="grid gap-3 text-sm">
      <div>
        <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("execution.panel.topic")}
        </dt>
        <dd className="mt-1 whitespace-pre-wrap">{fields.topic || t("common.emDash")}</dd>
      </div>
      <div>
        <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("execution.panel.brief")}
        </dt>
        <dd className="mt-1 whitespace-pre-wrap">{fields.brief || t("common.emDash")}</dd>
      </div>
      <div>
        <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("execution.panel.maxRounds")}
        </dt>
        <dd className="mt-1">{fields.max_rounds ?? t("common.emDash")}</dd>
      </div>
      <div>
        <dt className="text-xs uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("execution.panel.expertSlots")}
        </dt>
        <dd className="mt-1">
          {fields.expert_slots.length === 0 ? (
            <p className="text-[color:var(--text-muted)]">{t("execution.panel.expertsEmpty")}</p>
          ) : (
            <ul className="grid gap-2">
              {fields.expert_slots.map((slot) => (
                <li key={slot.slot_id || slot.label}>
                  <span className="font-medium">{slot.label || slot.slot_id}</span>
                  {slot.profile ? (
                    <span className="text-[color:var(--text-muted)]"> — {slot.profile}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </dd>
      </div>
    </dl>
  )
}
