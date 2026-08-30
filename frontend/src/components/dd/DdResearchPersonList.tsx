import type { DdResearchPerson } from "@/api/dd"
import {
  appointmentBreakdown,
  personInvestigated,
  roleSummaryParts,
} from "@/components/dd/researchPeople"
import type { MessageKey, TranslateParams } from "@/i18n"
import { cn } from "@/lib/utils"

export function DdResearchPersonList({
  people,
  groupOrgnr,
  selected,
  activeId,
  disabled,
  onToggle,
  onSelect,
  onToggleAll,
  allSelected,
  t,
}: {
  people: DdResearchPerson[]
  groupOrgnr: Set<string>
  selected: Set<string>
  activeId: string | null
  disabled: boolean
  onToggle: (name: string, checked: boolean) => void
  onSelect: (id: string) => void
  onToggleAll: (checked: boolean) => void
  allSelected: boolean
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  return (
    <div className="dd-people-list">
      <div className="dd-people-list-head">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={allSelected}
            disabled={disabled || people.length === 0}
            onChange={(e) => onToggleAll(e.target.checked)}
          />
          {t("dd.panel.researchSelectAll")}
        </label>
        <span className="ml-auto">{t("dd.panel.researchColumnRole")}</span>
      </div>
      <ul className="dd-people-list-body divide-y divide-[color:var(--border-hairline)]">
        {people.map((person) => {
          const id = `${person.namn}-${person.roll}`
          const active = activeId === id
          const investigated = personInvestigated(person)
          const roles = roleSummaryParts(person)
          const roleLine = roles
            .map((row) =>
              row.count > 0
                ? t("dd.panel.researchRoleInCompanies", { roll: row.roll, count: row.count })
                : row.roll,
            )
            .join(" · ")
          const stats = appointmentBreakdown(person, groupOrgnr)
          return (
            <li key={id}>
              <div
                className={cn(
                  "flex items-start gap-3 px-3 py-3",
                  active && "bg-[color:var(--db-ink-100)]",
                )}
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.has(person.namn)}
                  disabled={disabled}
                  onChange={(e) => onToggle(person.namn, e.target.checked)}
                  aria-label={person.namn}
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  type="button"
                  className="min-w-0 flex-1 border-0 bg-transparent p-0 text-left"
                  onClick={() => onSelect(id)}
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-sm font-medium text-[color:var(--text-body)]">
                      {person.namn}
                    </span>
                    {investigated ? (
                      <span className="rounded-sm bg-[color:var(--db-ink-100)] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("dd.panel.researchInvestigated")}
                      </span>
                    ) : null}
                  </div>
                  {roleLine ? (
                    <div className="mt-0.5 text-xs text-muted-foreground">{roleLine}</div>
                  ) : null}
                  <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>
                      {t("dd.panel.researchInGroupCount", { count: stats.inGroupCount })}
                    </span>
                    <span>
                      {t("dd.panel.researchOutsideCount", { count: stats.outsideCount })}
                    </span>
                  </div>
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
