import type { DdAccountFigure, DdCandidateCompany } from "@/api/dd"
import { useLocale, type MessageKey } from "@/i18n"

const SUMMARY_ACCOUNT_CODES = new Set(["SDI", "DR", "SUB", "EBITDA", "ANT", "SEK", "EKA"])

function formatSek(value: number | null | undefined, intl: string): string {
  if (value == null) return "—"
  return `${new Intl.NumberFormat(intl).format(value)} kr`
}

function formatFigure(figure: DdAccountFigure, intl: string): string {
  switch (figure.enhet) {
    case "sek":
      return `${figure.namn}: ${formatSek(figure.sek, intl)}`
    case "pct":
      return `${figure.namn}: ${figure.tal ?? "—"}%`
    case "antal":
    case "tal":
      return `${figure.namn}: ${figure.tal ?? "—"}`
    default: {
      const _never: never = figure.enhet
      return _never
    }
  }
}

function registeredLabel(
  value: boolean | null | undefined,
  t: (key: MessageKey) => string,
): string | null {
  if (value == null) return null
  return value ? t("dd.sourcing.registeredYes") : t("dd.sourcing.registeredNo")
}

function FactList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <h4 className="text-xs uppercase tracking-wide text-muted-foreground">{title}</h4>
      <ul className="mt-1 grid gap-0.5 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export function DdCandidateFacts({
  candidate,
  compact = false,
}: {
  candidate: DdCandidateCompany
  compact?: boolean
}) {
  const { t, intl } = useLocale()
  const officers = candidate.styrelse ?? []
  const marks = candidate.varumarken ?? []
  const accounts = candidate.rakenskaper ?? []
  const signatories = candidate.firmateckning ?? []
  const sni = candidate.sni ?? []
  const events = candidate.handelser ?? []
  const sites = candidate.arbetsstallen ?? []
  const related = candidate.relaterade_bolag ?? []
  const fskatt = registeredLabel(candidate.fskatt, t)
  const moms = registeredLabel(candidate.moms, t)
  const payroll = registeredLabel(candidate.arbetsgivaravgift, t)
  const mortgage = registeredLabel(candidate.foretagshypotek, t)
  const remark = registeredLabel(candidate.betalningsanmarkning, t)
  const gazelle = registeredLabel(candidate.gasell, t)
  const resultatKey = `dd.sourcing.resultatOptions.${candidate.resultat}` as MessageKey

  return (
    <div className="grid gap-3">
      <dl className="grid gap-1 text-sm md:grid-cols-2">
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("dd.sourcing.candidateAge")}
          </dt>
          <dd>{t("dd.sourcing.candidateAgeValue", { years: candidate.alder_ar })}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("dd.sourcing.candidateRegion")}
          </dt>
          <dd>{candidate.omrade || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("dd.sourcing.candidateResult")}
          </dt>
          <dd>{t(resultatKey)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("dd.sourcing.candidateRevenue")}
          </dt>
          <dd>{formatSek(candidate.omsattning_sek, intl)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("dd.sourcing.candidateEmployees")}
          </dt>
          <dd>{candidate.anstallda ?? "—"}</dd>
        </div>
        {candidate.telefon ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidatePhone")}
            </dt>
            <dd>{candidate.telefon}</dd>
          </div>
        ) : null}
        {fskatt ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidateFskatt")}
            </dt>
            <dd>{fskatt}</dd>
          </div>
        ) : null}
        {moms ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidateMoms")}
            </dt>
            <dd>{moms}</dd>
          </div>
        ) : null}
        {payroll ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidatePayroll")}
            </dt>
            <dd>{payroll}</dd>
          </div>
        ) : null}
        {mortgage ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidateMortgage")}
            </dt>
            <dd>{mortgage}</dd>
          </div>
        ) : null}
        {remark ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidatePaymentRemark")}
            </dt>
            <dd>{remark}</dd>
          </div>
        ) : null}
        {gazelle ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidateGazelle")}
            </dt>
            <dd>{gazelle}</dd>
          </div>
        ) : null}
        {candidate.koncern_bolag != null || candidate.koncern_dotter != null ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidateGroup")}
            </dt>
            <dd>
              {t("dd.sourcing.candidateGroupValue", {
                companies: candidate.koncern_bolag ?? "—",
                subsidiaries: candidate.koncern_dotter ?? "—",
              })}
            </dd>
          </div>
        ) : null}
        {candidate.moderbolag ? (
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("dd.sourcing.candidateParent")}
            </dt>
            <dd>{candidate.moderbolag}</dd>
          </div>
        ) : null}
      </dl>

      {compact ? null : (
        <>
          {officers.length > 0 ? (
            <div>
              <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("dd.sourcing.candidateBoard")}
              </h4>
              <ul className="mt-1 grid gap-0.5 text-sm">
                {officers.map((officer) => (
                  <li key={`${officer.grupp}-${officer.roll}-${officer.namn}`}>
                    {officer.roll ? `${officer.roll}: ${officer.namn}` : officer.namn}
                    {officer.grupp ? ` (${officer.grupp})` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {signatories.length > 0 ? (
            <div>
              <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("dd.sourcing.candidateSignatories")}
              </h4>
              <p className="mt-1 text-sm">{signatories.join(" ")}</p>
            </div>
          ) : null}
          {marks.length > 0 ? (
            <div>
              <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("dd.sourcing.candidateTrademarks")}
              </h4>
              <p className="mt-1 text-sm">{marks.join(", ")}</p>
            </div>
          ) : null}
          <FactList title={t("dd.sourcing.candidateSni")} items={sni} />
          <FactList title={t("dd.sourcing.candidateSites")} items={sites} />
          <FactList title={t("dd.sourcing.candidateRelated")} items={related} />
          <FactList title={t("dd.sourcing.candidateEvents")} items={events} />
          {accounts.length > 0 ? (
            <div>
              <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("dd.sourcing.candidateAccounts")}
              </h4>
              <ul className="mt-1 grid gap-2 text-sm">
                {accounts.map((year) => {
                  const extra = (year.poster ?? []).filter(
                    (fig) => !SUMMARY_ACCOUNT_CODES.has(fig.kod),
                  )
                  return (
                    <li key={year.year}>
                      <div className="font-medium">{year.year}</div>
                      <div className="text-muted-foreground">
                        {t("dd.sourcing.candidateRevenue")}: {formatSek(year.omsattning_sek, intl)}
                        {" · "}
                        {t("dd.sourcing.candidateResult")}: {formatSek(year.resultat_sek, intl)}
                        {" · "}
                        {t("dd.sourcing.candidateDividend")}: {formatSek(year.utdelning_sek, intl)}
                        {year.ebitda_sek != null
                          ? ` · ${t("dd.sourcing.candidateEbitda")}: ${formatSek(year.ebitda_sek, intl)}`
                          : ""}
                        {year.anstallda != null
                          ? ` · ${t("dd.sourcing.candidateEmployees")}: ${year.anstallda}`
                          : ""}
                        {year.eget_kapital_sek != null
                          ? ` · ${t("dd.sourcing.candidateEquity")}: ${formatSek(year.eget_kapital_sek, intl)}`
                          : ""}
                        {year.soliditet_pct
                          ? ` · ${t("dd.sourcing.candidateSolidity")}: ${year.soliditet_pct}%`
                          : ""}
                      </div>
                      {extra.length > 0 ? (
                        <div className="mt-1">
                          <div className="text-xs uppercase tracking-wide text-muted-foreground">
                            {t("dd.sourcing.candidateOtherAccounts")}
                          </div>
                          <ul className="mt-0.5 grid gap-0.5 text-muted-foreground md:grid-cols-2">
                            {extra.map((fig) => (
                              <li key={fig.kod}>{formatFigure(fig, intl)}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
