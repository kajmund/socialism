import type { DdResearchPerson } from "@/api/dd"
import { DdAllabolagLink } from "@/components/dd/DdAllabolagLink"
import {
  appointmentBreakdown,
  appointmentCapNote,
  personInitials,
  personIsAuditor,
  roleSummaryParts,
} from "@/components/dd/researchPeople"
import type { MessageKey, TranslateParams } from "@/i18n"

export function DdResearchPersonDetail({
  person,
  groupOrgnr,
  groupSize,
  leftover,
  t,
}: {
  person: DdResearchPerson
  groupOrgnr: Set<string>
  groupSize: number
  leftover: string[]
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const stats = appointmentBreakdown(person, groupOrgnr)
  const roles = roleSummaryParts(person)
  const roleLine = roles
    .map((row) =>
      row.count > 0
        ? t("dd.panel.researchRoleInCompanies", { roll: row.roll, count: row.count })
        : row.roll,
    )
    .join(" · ")
  const capNote = appointmentCapNote(leftover, person.namn)

  return (
    <div className="dd-people-detail">
      <div className="flex items-start gap-3">
        <div
          className="flex size-12 shrink-0 items-center justify-center rounded-full bg-[color:var(--db-ink-100)] text-sm font-semibold text-[color:var(--text-body)]"
          aria-hidden
        >
          {personInitials(person.namn)}
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-medium text-[color:var(--text-body)]">{person.namn}</h3>
          {roleLine ? <p className="mt-0.5 text-sm text-muted-foreground">{roleLine}</p> : null}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2">
          <div className="text-xs text-muted-foreground">{t("dd.panel.researchSeats")}</div>
          <div className="mt-1 text-lg font-medium text-[color:var(--text-body)]">
            {t("dd.panel.researchInGroupOf", {
              count: stats.inGroupCount,
              total: groupSize,
            })}
          </div>
        </div>
        <div className="rounded-md border border-[color:var(--border-hairline)] px-3 py-2">
          <div className="text-xs text-muted-foreground">
            {t("dd.panel.researchOutsideCompanies")}
          </div>
          <div className="mt-1 text-lg font-medium text-[color:var(--text-body)]">
            {t("dd.panel.researchOutsideBolag", { count: stats.outsideCount })}
          </div>
        </div>
      </div>

      <div className="mt-5">
        <h4 className="text-sm font-medium text-[color:var(--text-body)]">
          {t("dd.panel.researchSeats")}
        </h4>
        {stats.inGroup.length > 0 ? (
          <ul className="mt-2 space-y-1.5 text-sm">
            {stats.inGroup.map((seat) => (
              <li key={`${seat.orgnr}-${seat.namn}`} className="flex flex-wrap gap-x-2">
                <DdAllabolagLink namn={seat.namn} orgnr={seat.orgnr} />
                {seat.rolls.length > 0 ? (
                  <span className="text-muted-foreground">{seat.rolls.join(", ")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">{t("common.emDash")}</p>
        )}
      </div>

      <div className="mt-5">
        <h4 className="text-sm font-medium text-[color:var(--text-body)]">
          {t("dd.panel.researchOutsideCompanies")}
        </h4>
        {stats.outside.length > 0 ? (
          <ul className="mt-2 space-y-1.5 text-sm">
            {stats.outside.map((row) => (
              <li key={`${row.orgnr}-${row.namn}`}>
                <DdAllabolagLink namn={row.namn} orgnr={row.orgnr} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">{t("common.emDash")}</p>
        )}
      </div>

      {personIsAuditor(person) ? (
        <p className="mt-4 text-sm text-muted-foreground">{t("dd.panel.researchAuditorNote")}</p>
      ) : null}
      {capNote ? <p className="mt-2 text-sm text-muted-foreground">{capNote}</p> : null}

      {person.web_hits.length > 0 ? (
        <div className="mt-5">
          <h4 className="text-sm font-medium text-[color:var(--text-body)]">
            {t("dd.panel.researchWeb")}
          </h4>
          <div className="table-scroll mt-2">
            <table className="dd-accounts-table">
              <thead>
                <tr>
                  <th>{t("dd.panel.researchSocialNetwork")}</th>
                  <th>{t("dd.panel.researchSocialHit")}</th>
                </tr>
              </thead>
              <tbody>
                {person.web_hits.map((hit) => (
                  <tr key={`${person.namn}-${hit.natverk}`}>
                    <th>{hit.natverk || t("dd.panel.researchWeb")}</th>
                    <td>
                      {hit.url ? (
                        <a href={hit.url} target="_blank" rel="noreferrer">
                          {hit.title || hit.url}
                        </a>
                      ) : (
                        t("dd.panel.researchSocialMiss")
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  )
}
