import type { DdResultatFilter, DdSourcingCriteria } from "@/api/dd"
import { useLocale } from "@/i18n"

const RESULTAT_OPTIONS: DdResultatFilter[] = ["oavsett", "vinst", "förlust"]

export function DdSourcingCriteriaForm({
  criteria,
  onChange,
  disabled,
}: {
  criteria: DdSourcingCriteria
  onChange: (next: DdSourcingCriteria) => void
  disabled?: boolean
}) {
  const { t } = useLocale()

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium">{t("dd.sourcing.alderMin")}</span>
        <input
          className="dsearch"
          type="number"
          min={0}
          max={200}
          value={criteria.alder_min}
          disabled={disabled}
          onChange={(e) => onChange({ ...criteria, alder_min: Number(e.target.value) })}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium">{t("dd.sourcing.alderMax")}</span>
        <input
          className="dsearch"
          type="number"
          min={0}
          max={200}
          value={criteria.alder_max}
          disabled={disabled}
          onChange={(e) => onChange({ ...criteria, alder_max: Number(e.target.value) })}
        />
      </label>
      <label className="flex flex-col gap-1.5 md:col-span-2">
        <span className="text-xs font-medium">{t("dd.sourcing.omrade")}</span>
        <input
          className="dsearch"
          type="text"
          value={criteria.omrade}
          disabled={disabled}
          placeholder={t("dd.sourcing.omradePlaceholder")}
          onChange={(e) => onChange({ ...criteria, omrade: e.target.value })}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-xs font-medium">{t("dd.sourcing.resultat")}</span>
        <select
          className="dsel"
          value={criteria.resultat}
          disabled={disabled}
          onChange={(e) => onChange({ ...criteria, resultat: e.target.value as DdResultatFilter })}
        >
          {RESULTAT_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {t(`dd.sourcing.resultatOptions.${value}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 md:col-span-2">
        <span className="text-xs font-medium">{t("dd.sourcing.fritext")}</span>
        <textarea
          className="dsearch"
          rows={3}
          value={criteria.fritext}
          disabled={disabled}
          placeholder={t("dd.sourcing.fritextPlaceholder")}
          onChange={(e) => onChange({ ...criteria, fritext: e.target.value })}
        />
      </label>
    </div>
  )
}

export function DdSourcingCriteriaReadout({ criteria }: { criteria: DdSourcingCriteria }) {
  const { t } = useLocale()
  const brief = criteria.fritext.trim()

  return (
    <dl className="grid gap-3 text-sm">
      <div>
        <dt className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("dd.sourcing.briefLabel")}
        </dt>
        <dd className="whitespace-pre-wrap">{brief || t("common.emDash")}</dd>
      </div>
    </dl>
  )
}
