import { useState } from "react"
import type { DdResearchCompany, DdResearchPerson, DdResearchRelation } from "@/api/dd"
import { DdAllabolagLink } from "@/components/dd/DdAllabolagLink"
import {
  boardRowsForCompany,
  childrenOf,
  companyKey,
  companyLevel,
  findParent,
  formatCompactEmployees,
  formatCompactSek,
  parseCompanyFigures,
  percentOf,
  rootCompanies,
} from "@/components/dd/researchGroup"
import { personInitials } from "@/components/dd/researchPeople"
import type { MessageKey, TranslateParams } from "@/i18n"
import { cn } from "@/lib/utils"

type DetailTab = "board" | "structure"

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

function StructureNodes({
  company,
  companies,
  depth,
  seen,
  activeKey,
}: {
  company: DdResearchCompany
  companies: DdResearchCompany[]
  depth: number
  seen: ReadonlySet<string>
  activeKey: string
}) {
  const key = companyKey(company)
  if (seen.has(key)) return null
  const nextSeen = new Set(seen)
  nextSeen.add(key)
  const kids = childrenOf(companies, company.orgnr)
  const active = key === activeKey
  return (
    <li>
      <div
        style={{ paddingLeft: `${depth * 0.85}rem` }}
        className={cn("py-1 text-sm", active && "rounded-sm bg-[color:var(--db-ink-100)] font-medium")}
        aria-current={active ? "true" : undefined}
      >
        <DdAllabolagLink namn={company.namn} orgnr={company.orgnr} />
        {company.orgnr ? (
          <span className="ml-2 text-xs font-normal text-muted-foreground">{company.orgnr}</span>
        ) : null}
      </div>
      {kids.length > 0 ? (
        <ul>
          {kids.map((child) => (
            <StructureNodes
              key={companyKey(child)}
              company={child}
              companies={companies}
              depth={depth + 1}
              seen={nextSeen}
              activeKey={activeKey}
            />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function DdResearchCompanyDetail({
  company,
  companies,
  people,
  groupOmsattningSek,
  groupAnstallda,
  t,
}: {
  company: DdResearchCompany
  companies: DdResearchCompany[]
  people: DdResearchPerson[]
  groupOmsattningSek: number | null
  groupAnstallda: number | null
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const [tab, setTab] = useState<DetailTab>("board")
  const figures = parseCompanyFigures(company.nyckeltal)
  const byOrgnr = new Map(
    companies.filter((row) => row.orgnr).map((row) => [row.orgnr, row]),
  )
  const level = companyLevel(company, byOrgnr)
  const parent = findParent(companies, company)
  const boardRows = boardRowsForCompany(company, people, companies.length, personInitials)
  const omsPct = percentOf(figures.omsattningSek, groupOmsattningSek)
  const empPct = percentOf(figures.anstallda, groupAnstallda)
  return (
    <div className="dd-group-detail">
      <div className="dd-group-detail-chrome">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-medium text-[color:var(--text-body)]">
            <DdAllabolagLink namn={company.namn} orgnr={company.orgnr} />
          </h3>
          <span
            className={cn(
              "rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              badgeClass(company.relation),
            )}
          >
            {relationLabel(company.relation, t)}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {[
            company.orgnr || null,
            parent
              ? t("dd.panel.researchOwnedBy", { name: parent.namn })
              : t("dd.panel.researchNoParent"),
            t("dd.panel.researchLevel", { level }),
            t("dd.panel.researchBoardCountMeta", { count: boardRows.length }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2">
            <div className="text-xs text-muted-foreground">{t("dd.panel.researchKpiOms")}</div>
            <div className="mt-1 text-lg font-medium text-[color:var(--text-body)]">
              {formatCompactSek(figures.omsattningSek)}
            </div>
            <div className="text-xs text-muted-foreground">
              {omsPct != null
                ? t("dd.panel.researchPctOfGroup", { pct: omsPct })
                : t("common.emDash")}
            </div>
          </div>
          <div className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2">
            <div className="text-xs text-muted-foreground">{t("dd.panel.researchKpiEmployees")}</div>
            <div className="mt-1 text-lg font-medium text-[color:var(--text-body)]">
              {formatCompactEmployees(figures.anstallda)}
            </div>
            <div className="text-xs text-muted-foreground">
              {empPct != null
                ? t("dd.panel.researchPctOfGroup", { pct: empPct })
                : t("common.emDash")}
            </div>
          </div>
          <div className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2">
            <div className="text-xs text-muted-foreground">
              {figures.resultatYear
                ? t("dd.panel.researchKpiResultYear", { year: figures.resultatYear })
                : t("dd.panel.researchKpiResult")}
            </div>
            <div
              className={cn(
                "mt-1 text-lg font-medium",
                figures.resultatSek != null && figures.resultatSek < 0
                  ? "text-[#b42318]"
                  : "text-[color:var(--text-body)]",
              )}
            >
              {formatCompactSek(figures.resultatSek)}
            </div>
            <div className="text-xs text-muted-foreground">
              {figures.resultatSek != null && figures.resultatSek < 0
                ? t("dd.panel.researchResultNegative")
                : t("common.emDash")}
            </div>
          </div>
          <div className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2">
            <div className="text-xs text-muted-foreground">{t("dd.panel.researchKpiBoard")}</div>
            <div className="mt-1 text-lg font-medium text-[color:var(--text-body)]">
              {boardRows.length}
            </div>
            <div className="text-xs text-muted-foreground">
              {t("dd.panel.researchBoardPeopleHint")}
            </div>
          </div>
        </div>

        <div
          role="tablist"
          aria-label={t("dd.panel.researchCompanyDetailTabsAria")}
          className="mt-5 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
        >
          {(
            [
              {
                id: "board" as const,
                label: t("dd.panel.researchDetailBoard", { count: boardRows.length }),
              },
              {
                id: "structure" as const,
                label: t("dd.panel.researchDetailStructure", { count: companies.length }),
              },
            ] as const
          ).map((item) => {
            const selected = item.id === tab
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={selected}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm",
                  selected
                    ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                    : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
                )}
                onClick={() => setTab(item.id)}
              >
                {item.label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="dd-group-detail-body">
        {tab === "board" ? (
          <div>
            <p className="mb-2 text-xs text-muted-foreground">
              {t("dd.panel.researchBoardMergedNote")}
            </p>
            {boardRows.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("common.emDash")}</p>
            ) : (
              <div className="table-scroll">
                <table className="dd-accounts-table">
                  <thead>
                    <tr>
                      <th>{t("dd.panel.researchBoardColPerson")}</th>
                      <th>{t("dd.panel.researchBoardColRole")}</th>
                      <th>{t("dd.panel.researchBoardColInGroup")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {boardRows.map((row) => (
                      <tr key={row.namn}>
                        <td>
                          <span className="mr-2 inline-flex size-7 items-center justify-center rounded-full bg-[color:var(--db-ink-100)] text-[10px] font-semibold">
                            {row.initials}
                          </span>
                          {row.namn}
                        </td>
                        <td>{row.rolls.length > 0 ? row.rolls.join(" · ") : t("common.emDash")}</td>
                        <td>
                          {t("dd.panel.researchInGroupOf", {
                            count: row.companyCount,
                            total: companies.length,
                          })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : (
          <ul>
            {rootCompanies(companies).map((root) => (
              <StructureNodes
                key={companyKey(root)}
                company={root}
                companies={companies}
                depth={0}
                seen={new Set()}
                activeKey={companyKey(company)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
