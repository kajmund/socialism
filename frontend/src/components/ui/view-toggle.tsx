import { useLocale } from "@/i18n"
import { cn } from "@/lib/utils"

export type ListViewMode = "grid" | "list"

type ViewToggleProps = {
  value: ListViewMode
  onChange: (value: ListViewMode) => void
  className?: string
}

export function ViewToggle({ value, onChange, className }: ViewToggleProps) {
  const { t } = useLocale()
  return (
    <div className={cn("view-toggle", className)} role="group" aria-label={t("common.viewToggleAria")}>
      <button
        type="button"
        className={value === "grid" ? "on" : undefined}
        aria-pressed={value === "grid"}
        onClick={() => onChange("grid")}
      >
        {t("common.gridView")}
      </button>
      <button
        type="button"
        className={value === "list" ? "on" : undefined}
        aria-pressed={value === "list"}
        onClick={() => onChange("list")}
      >
        {t("common.listView")}
      </button>
    </div>
  )
}
