import { useEffect, useMemo, useState } from "react"
import type { PromptCatalog, PromptField } from "@/api/configurations"
import { useLocale } from "@/i18n"
import { cn } from "@/lib/utils"

type PromptFieldsPanelProps = {
  catalog: PromptCatalog
  prompts: Record<string, string>
  onChange: (key: string, value: string) => void
}

type FieldRow = PromptField & { sectionLabel: string }

function extractPlaceholders(hint: string): string[] {
  const matches = hint.match(/\{[a-z_]+\}/g)
  return matches ? [...new Set(matches)] : []
}

function wordCount(text: string): number {
  const trimmed = text.trim()
  if (!trimmed) return 0
  return trimmed.split(/\s+/).length
}

function fieldMatches(field: FieldRow, query: string): boolean {
  if (!query) return true
  return (
    field.label.toLowerCase().includes(query) ||
    field.key.toLowerCase().includes(query) ||
    field.sectionLabel.toLowerCase().includes(query)
  )
}

export function PromptFieldsPanel({ catalog, prompts, onChange }: PromptFieldsPanelProps) {
  const { t } = useLocale()
  const [query, setQuery] = useState("")
  const [activeKey, setActiveKey] = useState<string | null>(catalog.fields[0]?.key ?? null)

  const allFields = useMemo<FieldRow[]>(
    () =>
      catalog.fields.map((field) => ({
        ...field,
        sectionLabel: catalog.sections.find((s) => s.id === field.section)?.label ?? field.section,
      })),
    [catalog],
  )

  const normalizedQuery = query.trim().toLowerCase()

  const groups = useMemo(() => {
    return catalog.sections
      .map((section) => ({
        id: section.id,
        label: section.label,
        fields: allFields.filter(
          (field) => field.section === section.id && fieldMatches(field, normalizedQuery),
        ),
      }))
      .filter((group) => group.fields.length > 0 || (group.id === "report" && !normalizedQuery))
  }, [allFields, catalog.sections, normalizedQuery])

  const visibleFields = useMemo(
    () => allFields.filter((field) => fieldMatches(field, normalizedQuery)),
    [allFields, normalizedQuery],
  )

  useEffect(() => {
    if (activeKey && visibleFields.some((field) => field.key === activeKey)) return
    setActiveKey(visibleFields[0]?.key ?? null)
  }, [activeKey, visibleFields])

  const selected = visibleFields.find((field) => field.key === activeKey) ?? null
  const placeholders = selected ? extractPlaceholders(selected.hint) : []

  return (
    <div>
      <p className="mb-4 max-w-[680px] text-[12.5px] text-muted-foreground">
        {t("configurations.editor.promptsIntro")}
      </p>
      <div className="relative mb-[18px] max-w-xs">
        <input
          className="w-full rounded-[var(--radius-md)] border-[1.5px] border-[color:var(--border-hairline)] px-3 py-[9px] text-[0.82rem]"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("configurations.editor.fieldSearchPlaceholder")}
          type="search"
        />
      </div>
      <div className="flex items-start gap-6">
        <div
          className="flex max-h-[600px] w-[250px] shrink-0 flex-col gap-3.5 overflow-auto pr-3"
          role="tablist"
          aria-label={t("configurations.editor.tablistAria")}
        >
          {groups.map((group) => (
            <div key={group.id}>
              <div className="mb-0.5 px-2 py-1 text-[10.5px] font-bold uppercase tracking-[0.05em] text-muted-foreground">
                {group.label}
              </div>
              {group.fields.map((field) => {
                const selectedRow = field.key === selected?.key
                return (
                  <button
                    key={field.key}
                    type="button"
                    role="tab"
                    aria-selected={selectedRow}
                    className={cn(
                      "block w-full rounded-[var(--radius-sm)] px-2 py-2 text-left text-[0.8rem] leading-[1.3]",
                      selectedRow
                        ? "bg-db-ink-950 font-semibold text-white"
                        : "bg-transparent font-normal text-[color:var(--text-body)]",
                    )}
                    onClick={() => setActiveKey(field.key)}
                  >
                    {field.label}
                  </button>
                )
              })}
            </div>
          ))}
          {visibleFields.length === 0 ? (
            <p className="px-2 text-xs text-muted-foreground">
              {t("configurations.editor.noFieldsMatch")}
            </p>
          ) : null}
        </div>

        <div className="min-w-0 flex-1">
          {selected ? (
            <div className="rounded-[var(--radius-lg)] border border-[color:var(--border-hairline)] px-[26px] py-[22px]">
              <div className="mb-1 flex items-start justify-between gap-3">
                <div>
                  <div className="text-[1.05rem] font-semibold text-[color:var(--text-body)]">
                    {selected.label}
                  </div>
                  <div className="mt-[3px] font-mono text-[11px] text-db-ink-400">{selected.key}</div>
                </div>
                <span className="shrink-0 rounded-full border border-[color:var(--border-hairline)] px-2.5 py-[3px] text-[11px] text-muted-foreground">
                  {selected.sectionLabel}
                </span>
              </div>
              {selected.hint ? (
                <p className="mb-3.5 mt-2.5 max-w-[560px] text-[12.5px] text-muted-foreground">
                  {selected.hint}
                </p>
              ) : null}
              {placeholders.length > 0 ? (
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {placeholders.map((ph) => (
                    <span
                      key={ph}
                      className="rounded-md bg-db-gold-100 px-2 py-[3px] font-mono text-[11px] text-db-gold-700"
                    >
                      {ph}
                    </span>
                  ))}
                </div>
              ) : null}
              <textarea
                key={selected.key}
                className="min-h-60 w-full resize-y whitespace-pre-wrap rounded-[var(--radius-md)] border-[1.5px] border-[color:var(--border-hairline)] px-4 py-3.5 font-mono text-[0.82rem] leading-[1.6] text-[color:var(--text-body)] focus:border-db-gold-700 focus:shadow-[0_0_0_3px_var(--db-gold-100)] focus:outline-none"
                value={prompts[selected.key] ?? ""}
                onChange={(e) => onChange(selected.key, e.target.value)}
              />
              <div className="mt-2.5 flex items-center justify-between">
                <span className="text-[11.5px] text-muted-foreground">
                  {t("configurations.editor.defaultWordCount", {
                    count: wordCount(selected.default),
                  })}
                </span>
                <button
                  type="button"
                  className="text-xs text-[color:var(--text-link)] hover:text-[color:var(--text-link-hover)]"
                  onClick={() => onChange(selected.key, selected.default)}
                >
                  {t("configurations.editor.resetDefault")}
                </button>
              </div>
            </div>
          ) : groups.some((group) => group.id === "report") ? (
            <p className="max-w-[520px] text-sm text-muted-foreground">
              {t("configurations.editor.emptySection")}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}
