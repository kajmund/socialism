import type { DdAccountYear } from "@/api/dd"
import { useLocale, type Locale } from "@/i18n"

const CHART_W = 320
const CHART_H = 188
const PAD_L = 44
const PAD_R = 10
const PAD_T = 18
const PAD_B = 28

type YearColumnChartProps = {
  labels: string[]
  values: Array<number | null>
  title: string
  color: string
  formatTick: (value: number) => string
  signed?: boolean
}

function shortNumber(value: number, intl: string, decimals = 1): string {
  return new Intl.NumberFormat(intl, {
    maximumFractionDigits: decimals,
    minimumFractionDigits: 0,
  }).format(value)
}

function formatSekFull(value: number | null | undefined, locale: Locale): string {
  if (value == null) return "—"
  const text = new Intl.NumberFormat(locale === "en" ? "en-GB" : "sv-SE").format(value)
  return locale === "en" ? `SEK ${text}` : `${text} SEK`
}

function formatSekShort(value: number, locale: Locale, intl: string): string {
  const sign = value < 0 ? "−" : ""
  const n = Math.abs(value)
  if (n >= 1_000_000_000) {
    const amount = shortNumber(n / 1_000_000_000, intl)
    return locale === "sv" ? `${sign}${amount} mdkr` : `${sign}${amount} bn SEK`
  }
  if (n >= 1_000_000) {
    const amount = shortNumber(n / 1_000_000, intl)
    return locale === "sv" ? `${sign}${amount} mkr` : `${sign}${amount} M SEK`
  }
  if (n >= 1_000) {
    const amount = shortNumber(n / 1_000, intl, 0)
    return locale === "sv" ? `${sign}${amount} tkr` : `${sign}${amount}k SEK`
  }
  return formatSekFull(Math.round(value), locale)
}

function parsePct(raw: string | null | undefined): number | null {
  if (!raw) return null
  const text = raw.trim().replace("%", "").replace(",", ".")
  const n = Number(text)
  return Number.isFinite(n) ? n : null
}

function sortAccountYears(years: DdAccountYear[]): DdAccountYear[] {
  return [...years].sort((a, b) => {
    const digitsA = a.year.replace(/\D/g, "").slice(0, 4)
    const digitsB = b.year.replace(/\D/g, "").slice(0, 4)
    const yearA = digitsA.length >= 4 ? Number(digitsA) : 0
    const yearB = digitsB.length >= 4 ? Number(digitsB) : 0
    if (yearA !== yearB) return yearA - yearB
    return a.year.localeCompare(b.year)
  })
}

function YearColumnChart({
  labels,
  values,
  title,
  color,
  formatTick,
  signed = false,
}: YearColumnChartProps) {
  const present = values.filter((v): v is number => v != null)
  if (present.length === 0) return null

  let maxV = Math.max(...present)
  let minV = Math.min(...present)
  if (signed) {
    maxV = Math.max(0, maxV)
    minV = Math.min(0, minV)
  } else {
    maxV = Math.max(0, maxV)
    minV = 0
  }
  if (maxV === minV) maxV = minV + 1

  const plotW = CHART_W - PAD_L - PAD_R
  const plotH = CHART_H - PAD_T - PAD_B
  const span = maxV - minV
  const yOf = (value: number) => PAD_T + ((maxV - value) / span) * plotH
  const zeroY = yOf(0)
  const ticks = [maxV]
  if (minV < 0 && maxV > 0) ticks.push(0)
  ticks.push(minV)
  const slot = plotW / Math.max(labels.length, 1)
  const barW = Math.min(36, slot * 0.55)
  const aria = `${title}: ${labels
    .flatMap((label, i) => {
      const value = values[i]
      return value == null ? [] : [`${label} ${formatTick(value)}`]
    })
    .join(", ")}`

  return (
    <figure className="dd-year-chart">
      <h4>{title}</h4>
      <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} role="img" aria-label={aria}>
        {ticks.map((tick) => {
          const y = yOf(tick)
          return (
            <g key={tick}>
              <line className="dd-chart-grid" x1={PAD_L} y1={y} x2={CHART_W - PAD_R} y2={y} />
              <text className="dd-chart-tick" x={PAD_L - 6} y={y + 3} textAnchor="end">
                {formatTick(tick)}
              </text>
            </g>
          )
        })}
        <line className="dd-chart-zero" x1={PAD_L} y1={zeroY} x2={CHART_W - PAD_R} y2={zeroY} />
        {labels.map((label, i) => {
          const raw = values[i]
          const cx = PAD_L + slot * i + slot / 2
          if (raw == null) {
            return (
              <text key={label} className="dd-chart-year" x={cx} y={CHART_H - 8} textAnchor="middle">
                {label}
              </text>
            )
          }
          const y = yOf(raw)
          let top = Math.min(y, zeroY)
          let height = Math.abs(zeroY - y)
          if (height < 2) {
            height = 2
            top = raw >= 0 ? zeroY - 2 : zeroY
          }
          const fill = signed && raw < 0 ? "var(--db-error)" : color
          const labelY = raw >= 0 ? top - 4 : top + height + 11
          return (
            <g key={label}>
              <rect
                className="dd-chart-bar"
                x={cx - barW / 2}
                y={top}
                width={barW}
                height={height}
                rx={3}
                fill={fill}
              />
              <text className="dd-chart-val" x={cx} y={labelY} textAnchor="middle">
                {formatTick(raw)}
              </text>
              <text className="dd-chart-year" x={cx} y={CHART_H - 8} textAnchor="middle">
                {label}
              </text>
            </g>
          )
        })}
      </svg>
    </figure>
  )
}

export function DdAccountCharts({ years }: { years: DdAccountYear[] }) {
  const { t, locale, intl } = useLocale()
  const ordered = sortAccountYears(years)
  if (ordered.length === 0) return null

  const labels = ordered.map((year) => year.year)
  const sekTick = (value: number) => formatSekShort(value, locale, intl)
  const charts = [
    {
      title: t("dd.sourcing.candidateRevenue"),
      values: ordered.map((y) => (y.omsattning_sek != null ? y.omsattning_sek : null)),
      color: "var(--db-ink-950)",
      formatTick: sekTick,
    },
    {
      title: t("dd.sourcing.candidateResult"),
      values: ordered.map((y) => (y.resultat_sek != null ? y.resultat_sek : null)),
      color: "var(--db-success)",
      formatTick: sekTick,
      signed: true,
    },
    {
      title: t("dd.sourcing.candidateEbitda"),
      values: ordered.map((y) => (y.ebitda_sek != null ? y.ebitda_sek : null)),
      color: "var(--db-gold-700)",
      formatTick: sekTick,
      signed: true,
    },
    {
      title: t("dd.sourcing.candidateDividend"),
      values: ordered.map((y) => (y.utdelning_sek != null ? y.utdelning_sek : null)),
      color: "var(--warm-orange)",
      formatTick: sekTick,
    },
    {
      title: t("dd.sourcing.candidateEquity"),
      values: ordered.map((y) => (y.eget_kapital_sek != null ? y.eget_kapital_sek : null)),
      color: "var(--db-ink-400)",
      formatTick: sekTick,
    },
    {
      title: t("dd.sourcing.candidateEmployees"),
      values: ordered.map((y) => (y.anstallda != null ? y.anstallda : null)),
      color: "var(--db-ink-950)",
      formatTick: (v: number) => shortNumber(v, intl, 0),
    },
    {
      title: t("dd.sourcing.candidateSolidity"),
      values: ordered.map((y) => parsePct(y.soliditet_pct)),
      color: "var(--db-success)",
      formatTick: (v: number) => `${shortNumber(v, intl)} %`,
    },
  ]

  const tableRows: { label: string; cells: string[] }[] = [
    {
      label: t("dd.sourcing.candidateRevenue"),
      cells: ordered.map((y) => formatSekFull(y.omsattning_sek, locale)),
    },
    {
      label: t("dd.sourcing.candidateResult"),
      cells: ordered.map((y) => formatSekFull(y.resultat_sek, locale)),
    },
    {
      label: "EBITDA",
      cells: ordered.map((y) => formatSekFull(y.ebitda_sek, locale)),
    },
    {
      label: t("dd.sourcing.candidateDividend"),
      cells: ordered.map((y) => formatSekFull(y.utdelning_sek, locale)),
    },
    {
      label: t("dd.sourcing.candidateEmployees"),
      cells: ordered.map((y) => (y.anstallda != null ? String(y.anstallda) : "—")),
    },
    {
      label: t("dd.sourcing.candidateEquity"),
      cells: ordered.map((y) => formatSekFull(y.eget_kapital_sek, locale)),
    },
    {
      label: t("dd.sourcing.candidateSolidity"),
      cells: ordered.map((y) => (y.soliditet_pct ? `${y.soliditet_pct}%` : "—")),
    },
  ].filter((row) => row.cells.some((cell) => cell !== "—"))

  const rendered = charts.filter((chart) => chart.values.some((v) => v != null))

  return (
    <div className="dd-accounts">
      <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
        {t("dd.sourcing.candidateAccounts")}
      </h4>
      <p className="mt-1 text-sm text-muted-foreground">{t("dd.sourcing.accountsIntro")}</p>
      {rendered.length > 0 ? (
        <div className="dd-accounts-grid">
          {rendered.map((chart) => (
            <YearColumnChart
              key={chart.title}
              labels={labels}
              values={chart.values}
              title={chart.title}
              color={chart.color}
              formatTick={chart.formatTick}
              signed={chart.signed}
            />
          ))}
        </div>
      ) : null}
      {tableRows.length > 0 ? (
        <div className="table-scroll">
          <table className="dd-accounts-table">
            <thead>
              <tr>
                <th>{t("dd.sourcing.accountsMetric")}</th>
                {ordered.map((year) => (
                  <th key={year.year}>{year.year}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => (
                <tr key={row.label}>
                  <th>{row.label}</th>
                  {row.cells.map((cell, i) => (
                    <td key={`${row.label}-${ordered[i]?.year ?? i}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
