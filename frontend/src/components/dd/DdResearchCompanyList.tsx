import type { DdResearchCompany, DdResearchRelation } from "@/api/dd"
import {
  childrenOf,
  companyKey,
  descendantCount,
  formatCompactEmployees,
  formatCompactSek,
  parseCompanyFigures,
  rootCompanies,
} from "@/components/dd/researchGroup"
import type { MessageKey, TranslateParams } from "@/i18n"
import { cn } from "@/lib/utils"

function relationLabel(
  relation: DdResearchRelation,
  t: (key: MessageKey, params?: TranslateParams) => string,
): string {
  switch (relation) {
    case "kandidat":
      return t("dd.panel.researchRelation.kandidat")
    case "moderbolag":
      return t("dd.panel.researchRelation.moderbolag")
    case "dotterbolag":
      return t("dd.panel.researchRelation.dotterbolag")
    default: {
      const _exhaustive: never = relation
      return _exhaustive
    }
  }
}

function badgeClass(relation: DdResearchRelation): string {
  switch (relation) {
    case "kandidat":
      return "border-[color:var(--db-gold-500)] bg-[color:var(--db-gold-500)]/10 text-[color:var(--db-gold-700)]"
    case "moderbolag":
      return "border-[color:var(--db-ink-950)] bg-[color:var(--db-ink-100)] text-[color:var(--text-body)]"
    case "dotterbolag":
      return "border-[color:var(--border-hairline)] bg-transparent text-muted-foreground"
    default: {
      const _exhaustive: never = relation
      return _exhaustive
    }
  }
}

function CompanyRow({
  company,
  treeCompanies,
  allCompanies,
  depth,
  activeKey,
  expanded,
  onSelect,
  onToggleExpand,
  t,
  seen,
}: {
  company: DdResearchCompany
  treeCompanies: DdResearchCompany[]
  allCompanies: DdResearchCompany[]
  depth: number
  activeKey: string | null
  expanded: Set<string>
  onSelect: (key: string) => void
  onToggleExpand: (key: string) => void
  t: (key: MessageKey, params?: TranslateParams) => string
  seen: ReadonlySet<string>
}) {
  const key = companyKey(company)
  if (seen.has(key)) return null
  const nextSeen = new Set(seen)
  nextSeen.add(key)
  const kids = childrenOf(treeCompanies, company.orgnr)
  const isExpanded = expanded.has(key)
  const active = activeKey === key
  const figures = parseCompanyFigures(company.nyckeltal)
  const descendants = descendantCount(allCompanies, company)

  return (
    <li>
      <div
        className={cn(
          "flex items-start gap-2 border-b border-[color:var(--border-hairline)] px-2 py-2.5",
          active && "bg-[color:var(--db-ink-100)]",
        )}
        style={{ paddingLeft: `${0.5 + depth * 1.1}rem` }}
      >
        {kids.length > 0 ? (
          <button
            type="button"
            className="mt-0.5 size-5 shrink-0 border-0 bg-transparent p-0 text-muted-foreground"
            aria-expanded={isExpanded}
            aria-label={
              isExpanded
                ? t("dd.panel.researchCollapseCompany", { name: company.namn })
                : t("dd.panel.researchExpandCompany", { name: company.namn })
            }
            onClick={(e) => {
              e.stopPropagation()
              onToggleExpand(key)
            }}
          >
            {isExpanded ? "▾" : "▸"}
          </button>
        ) : (
          <span className="mt-0.5 size-5 shrink-0" aria-hidden />
        )}
        <button
          type="button"
          className="min-w-0 flex-1 border-0 bg-transparent p-0 text-left"
          onClick={() => onSelect(key)}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[color:var(--text-body)]">{company.namn}</span>
            <span
              className={cn(
                "rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                badgeClass(company.relation),
              )}
            >
              {relationLabel(company.relation, t)}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            {company.orgnr ? <span>{company.orgnr}</span> : null}
            {descendants > 0 ? (
              <span>{t("dd.panel.researchOwnCompanies", { count: descendants })}</span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            <span>{formatCompactSek(figures.omsattningSek)}</span>
            <span>
              {figures.anstallda != null
                ? t("dd.panel.researchEmployeesShort", {
                    count: formatCompactEmployees(figures.anstallda),
                  })
                : t("dd.panel.researchEmployeesShort", { count: "—" })}
            </span>
            <span
              className={
                figures.resultatSek != null && figures.resultatSek < 0
                  ? "text-[#b42318]"
                  : undefined
              }
            >
              {formatCompactSek(figures.resultatSek)}
            </span>
          </div>
        </button>
      </div>
      {kids.length > 0 && isExpanded ? (
        <ul>
          {kids.map((child) => (
            <CompanyRow
              key={companyKey(child)}
              company={child}
              treeCompanies={treeCompanies}
              allCompanies={allCompanies}
              depth={depth + 1}
              activeKey={activeKey}
              expanded={expanded}
              onSelect={onSelect}
              onToggleExpand={onToggleExpand}
              t={t}
              seen={nextSeen}
            />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function DdResearchCompanyList({
  companies,
  allCompanies,
  activeKey,
  expanded,
  onSelect,
  onToggleExpand,
  t,
}: {
  companies: DdResearchCompany[]
  allCompanies: DdResearchCompany[]
  activeKey: string | null
  expanded: Set<string>
  onSelect: (key: string) => void
  onToggleExpand: (key: string) => void
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const roots = rootCompanies(companies)
  return (
    <div className="dd-group-list">
      <ul className="dd-group-list-body">
        {roots.map((root) => (
          <CompanyRow
            key={companyKey(root)}
            company={root}
            treeCompanies={companies}
            allCompanies={allCompanies}
            depth={0}
            activeKey={activeKey}
            expanded={expanded}
            onSelect={onSelect}
            onToggleExpand={onToggleExpand}
            t={t}
            seen={new Set()}
          />
        ))}
      </ul>
    </div>
  )
}
