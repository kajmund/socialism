import { useLocale } from "@/i18n"

export type ReportDocumentTab = "html" | "pdf"

type ReportDocumentTabsProps = {
  active: ReportDocumentTab
  onChange: (tab: ReportDocumentTab) => void
  className?: string
}

export function ReportDocumentTabs({
  active,
  onChange,
  className,
}: ReportDocumentTabsProps) {
  const { t } = useLocale()
  const items = [
    { id: "html" as const, label: t("reports.tabReport") },
    { id: "pdf" as const, label: t("reports.tabPdf") },
  ]

  return (
    <div
      className={
        className ??
        "mb-3 flex gap-1 border-b border-[color:var(--border-hairline)]"
      }
      role="tablist"
      aria-label={t("reports.documentTabsAria")}
    >
      {items.map((item) => {
        const selected = item.id === active
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            className={
              "-mb-px border-b-2 px-3 py-1.5 text-sm " +
              (selected
                ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]")
            }
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
