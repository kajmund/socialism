import { useEffect, useMemo, useState } from "react"
import type { DdResearchCompany, DdResearchPending, DdResearchPerson } from "@/api/dd"
import { DdAllabolagLink } from "@/components/dd/DdAllabolagLink"
import { DdResearchCompanyDetail } from "@/components/dd/DdResearchCompanyDetail"
import { DdResearchCompanyList } from "@/components/dd/DdResearchCompanyList"
import {
  companyKey,
  computeGroupKpis,
  defaultExpandedKeys,
  filterGroupCompanies,
  findKandidat,
  formatCompactEmployees,
  formatCompactSek,
  type GroupCompanyFilter,
} from "@/components/dd/researchGroup"
import { leftoverMisses } from "@/components/dd/researchPeople"
import type { MessageKey, TranslateParams } from "@/i18n"
import { cn } from "@/lib/utils"

function KpiCard({
  label,
  value,
  hint,
  valueClassName,
}: {
  label: string
  value: string
  hint: string
  valueClassName?: string
}) {
  return (
    <div className="rounded-md border border-[color:var(--border-hairline)] bg-[var(--db-ink-0)] px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 text-xl font-medium tabular-nums text-[color:var(--text-body)]",
          valueClassName,
        )}
      >
        {value}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
    </div>
  )
}

export function DdResearchGroupPanel({
  companies,
  people,
  leftover,
  pending,
  t,
}: {
  companies: DdResearchCompany[]
  people: DdResearchPerson[]
  leftover: string[]
  pending: DdResearchPending[]
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<GroupCompanyFilter>("all")
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => defaultExpandedKeys(companies))

  useEffect(() => {
    setExpanded(defaultExpandedKeys(companies))
    const kandidat = findKandidat(companies)
    setActiveKey(kandidat ? companyKey(kandidat) : companies[0] ? companyKey(companies[0]) : null)
  }, [companies])

  const kpis = useMemo(() => computeGroupKpis(companies), [companies])
  const visible = useMemo(
    () => filterGroupCompanies(companies, query, filter, people),
    [companies, query, filter, people],
  )

  useEffect(() => {
    if (visible.length === 0) {
      setActiveKey(null)
      return
    }
    if (activeKey && visible.some((row) => companyKey(row) === activeKey)) return
    const kandidat = findKandidat(visible)
    setActiveKey(companyKey(kandidat ?? visible[0]))
  }, [visible, activeKey])

  if (companies.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("dd.panel.researchEmptyGroup")}</p>
  }

  const leftoverVisible = leftoverMisses(leftover)
  const activeCompany = visible.find((row) => companyKey(row) === activeKey) ?? null

  function toggleExpand(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const filterChips: { id: GroupCompanyFilter; label: string }[] = [
    { id: "all", label: t("dd.panel.researchGroupFilterAll") },
    { id: "withFigures", label: t("dd.panel.researchGroupFilterWithFigures") },
    { id: "withoutFigures", label: t("dd.panel.researchGroupFilterWithoutFigures") },
    { id: "negativeResult", label: t("dd.panel.researchGroupFilterNegative") },
  ]

  return (
    <div className="dd-group-panel">
      <div className="dd-group-chrome space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <KpiCard
            label={t("dd.panel.researchKpiCompanies")}
            value={String(kpis.companyCount)}
            hint={t("dd.panel.researchKpiCompaniesHint", {
              levels: kpis.levels,
              holdings: kpis.midHoldings,
            })}
          />
          <KpiCard
            label={t("dd.panel.researchKpiOms")}
            value={formatCompactSek(kpis.omsattningSek)}
            hint={t("dd.panel.researchKpiOmsHint", { count: kpis.omsattningCount })}
          />
          <KpiCard
            label={t("dd.panel.researchKpiEmployees")}
            value={formatCompactEmployees(kpis.anstallda)}
            hint={
              kpis.anstalldaMaxName
                ? t("dd.panel.researchKpiEmployeesHint", {
                    name: kpis.anstalldaMaxName,
                    count: formatCompactEmployees(kpis.anstalldaMax),
                  })
                : t("common.emDash")
            }
          />
          <KpiCard
            label={t("dd.panel.researchKpiResult")}
            value={formatCompactSek(kpis.resultatSek)}
            hint={
              kpis.resultatDriverName
                ? t("dd.panel.researchKpiResultHint", { name: kpis.resultatDriverName })
                : t("common.emDash")
            }
            valueClassName={
              kpis.resultatSek != null && kpis.resultatSek < 0 ? "text-[#b42318]" : undefined
            }
          />
          <KpiCard
            label={t("dd.panel.researchKpiMissing")}
            value={String(kpis.withoutFigures)}
            hint={t("dd.panel.researchKpiMissingHint")}
          />
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <input
            type="search"
            className="dsel w-full max-w-md"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("dd.panel.researchGroupSearchPlaceholder")}
            aria-label={t("dd.panel.researchGroupSearchPlaceholder")}
          />
          <div className="flex flex-wrap items-center gap-2">
            <div
              className="flex flex-wrap gap-1"
              role="group"
              aria-label={t("dd.panel.researchGroupFilterAria")}
            >
              {filterChips.map((chip) => (
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
            <span className="text-xs text-muted-foreground">
              {t("dd.panel.researchGroupListCaption", { count: visible.length })}
            </span>
          </div>
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("dd.panel.researchGroupFilterEmpty")}</p>
      ) : (
        <div className="dd-group-split">
          <DdResearchCompanyList
            companies={visible}
            allCompanies={companies}
            activeKey={activeKey}
            expanded={expanded}
            onSelect={setActiveKey}
            onToggleExpand={toggleExpand}
            t={t}
          />
          {activeCompany ? (
            <DdResearchCompanyDetail
              company={activeCompany}
              companies={companies}
              people={people}
              groupOmsattningSek={kpis.omsattningSek}
              groupAnstallda={kpis.anstallda}
              t={t}
            />
          ) : (
            <p className="dd-group-detail flex items-start p-4 text-sm text-muted-foreground">
              {t("dd.panel.researchNoCompanySelected")}
            </p>
          )}
        </div>
      )}

      {pending.length > 0 || leftoverVisible.length > 0 ? (
        <div className="dd-group-footer space-y-3">
          {pending.length > 0 ? (
            <div>
              <h3 className="text-sm text-muted-foreground">{t("dd.panel.researchPending")}</h3>
              <ul className="mt-1 list-disc pl-5 text-sm text-muted-foreground">
                {pending.map((row) => (
                  <li key={row.orgnr}>
                    {row.namn ? (
                      <>
                        <DdAllabolagLink namn={row.namn} orgnr={row.orgnr} /> ({row.orgnr})
                      </>
                    ) : (
                      row.orgnr
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {leftoverVisible.length > 0 ? (
            <div>
              <h3 className="text-sm text-muted-foreground">{t("dd.panel.researchLeftover")}</h3>
              <ul className="mt-1 list-disc pl-5 text-sm text-muted-foreground">
                {leftoverVisible.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
