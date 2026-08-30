import { useEffect, useMemo, useState } from "react"
import type { DdResearchCompany, DdResearchPerson } from "@/api/dd"
import { DdResearchPersonDetail } from "@/components/dd/DdResearchPersonDetail"
import { DdResearchPersonList } from "@/components/dd/DdResearchPersonList"
import {
  filterPeople,
  sortPeopleAuditorsLast,
  type PeopleFilter,
} from "@/components/dd/researchPeople"
import type { MessageKey, TranslateParams } from "@/i18n"
import { cn } from "@/lib/utils"

function personKey(person: DdResearchPerson): string {
  return `${person.namn}-${person.roll}`
}

export function DdResearchPeoplePanel({
  people,
  companies,
  leftover,
  selected,
  disabled,
  onToggle,
  t,
}: {
  people: DdResearchPerson[]
  companies: DdResearchCompany[]
  leftover: string[]
  selected: Set<string>
  disabled: boolean
  onToggle: (name: string, checked: boolean) => void
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const ordered = useMemo(() => sortPeopleAuditorsLast(people), [people])
  const groupOrgnr = useMemo(
    () => new Set(companies.map((row) => row.orgnr).filter(Boolean)),
    [companies],
  )
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<PeopleFilter>("all")
  const [activeId, setActiveId] = useState<string | null>(null)

  const visible = useMemo(
    () => filterPeople(ordered, query, filter),
    [ordered, query, filter],
  )

  useEffect(() => {
    if (visible.length === 0) {
      setActiveId(null)
      return
    }
    if (activeId && visible.some((person) => personKey(person) === activeId)) return
    setActiveId(personKey(visible[0]))
  }, [visible, activeId])

  if (people.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("dd.panel.researchEmptyPeople")}</p>
  }

  const activePerson = visible.find((person) => personKey(person) === activeId) ?? null
  const allVisibleSelected =
    visible.length > 0 && visible.every((person) => selected.has(person.namn))

  function toggleAll(checked: boolean) {
    for (const person of visible) {
      onToggle(person.namn, checked)
    }
  }

  return (
    <div className="dd-people-panel">
      <div className="flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <input
          type="search"
          className="dsel w-full max-w-md"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("dd.panel.researchSearchPlaceholder")}
          aria-label={t("dd.panel.researchSearchPlaceholder")}
        />
        <div
          className="flex flex-wrap gap-1"
          role="group"
          aria-label={t("dd.panel.researchFilterAria")}
        >
          {(
            [
              { id: "all" as const, label: t("dd.panel.researchFilterAll") },
              {
                id: "notInvestigated" as const,
                label: t("dd.panel.researchFilterNotInvestigated"),
              },
            ] as const
          ).map((chip) => (
            <button
              key={chip.id}
              type="button"
              className={cn(
                "rounded-full border px-3 py-1 text-xs",
                filter === chip.id
                  ? "border-[color:var(--db-ink-950)] bg-[color:var(--db-ink-950)] text-white"
                  : "border-[color:var(--border-hairline)] text-muted-foreground hover:text-[color:var(--text-body)]",
              )}
              aria-pressed={filter === chip.id}
              onClick={() => setFilter(chip.id)}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("dd.panel.researchPeopleFilterEmpty")}</p>
      ) : (
        <div className="dd-people-split">
          <DdResearchPersonList
            people={visible}
            groupOrgnr={groupOrgnr}
            selected={selected}
            activeId={activeId}
            disabled={disabled}
            onToggle={onToggle}
            onSelect={setActiveId}
            onToggleAll={toggleAll}
            allSelected={allVisibleSelected}
            t={t}
          />
          {activePerson ? (
            <DdResearchPersonDetail
              person={activePerson}
              groupOrgnr={groupOrgnr}
              groupSize={companies.length}
              leftover={leftover}
              t={t}
            />
          ) : (
            <p className="dd-people-detail text-sm text-muted-foreground">
              {t("dd.panel.researchNoPersonSelected")}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
