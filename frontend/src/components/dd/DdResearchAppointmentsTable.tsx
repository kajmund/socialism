import type { DdResearchPerson } from "@/api/dd"
import { DdAllabolagLink } from "@/components/dd/DdAllabolagLink"
import { sortPeopleAuditorsLast } from "@/components/dd/researchPeople"
import type { MessageKey, TranslateParams } from "@/i18n"

export function DdResearchAppointmentsTable({
  people,
  groupOrgnr,
  t,
}: {
  people: DdResearchPerson[]
  groupOrgnr: Set<string>
  t: (key: MessageKey, params?: TranslateParams) => string
}) {
  const rows = sortPeopleAuditorsLast(people).flatMap((person) =>
    person.bolag.map((row) => ({
      person: person.namn,
      namn: row.namn,
      orgnr: row.orgnr,
      inGroup: Boolean(row.orgnr && groupOrgnr.has(row.orgnr)),
    })),
  )
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("dd.panel.researchAppointmentsEmpty")}</p>
  }
  return (
    <div className="table-scroll">
      <table className="dd-accounts-table">
        <thead>
          <tr>
            <th>{t("dd.panel.researchAppointmentPerson")}</th>
            <th>{t("dd.panel.researchAppointmentCompany")}</th>
            <th>{t("dd.panel.researchAppointmentOrgnr")}</th>
            <th>{t("dd.panel.researchAppointmentInGroup")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.person}-${row.orgnr}-${row.namn}`}>
              <td>{row.person}</td>
              <th>
                <DdAllabolagLink namn={row.namn} orgnr={row.orgnr} />
              </th>
              <td>{row.orgnr || t("common.emDash")}</td>
              <td>
                {row.inGroup ? t("dd.panel.researchAppointmentInGroupYes") : t("common.emDash")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
