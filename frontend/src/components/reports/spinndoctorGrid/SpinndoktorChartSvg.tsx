import type { SpindoctorChartType } from "@/api/spindoctorWidgets"

type SeriesRow = { label: string; value: number }

function pct(value: number, total: number): string {
  if (total <= 0) return "0%"
  return `${Math.round((value / total) * 100)}%`
}

export function SpinndoktorChartSvg({
  chartType,
  series,
}: {
  chartType: SpindoctorChartType
  series: SeriesRow[]
}) {
  if (chartType === "stat_number") {
    const top = series[0]
    return (
      <div className="spinndoctor-chart-stat">
        <div className="spinndoctor-chart-stat-value">
          {top ? Math.round(top.value * (top.value <= 1 ? 100 : 1)) : 0}
          {top && top.value <= 1 ? "%" : ""}
        </div>
        <div className="spinndoctor-chart-stat-label">{top?.label ?? "—"}</div>
      </div>
    )
  }

  if (chartType === "donut") {
    const total = series.reduce((sum, row) => sum + Math.max(0, row.value), 0) || 1
    let cursor = 0
    const stops = series.map((row, index) => {
      const share = Math.max(0, row.value) / total
      const start = cursor * 360
      cursor += share
      const end = cursor * 360
      const hue = 38 + index * 47
      return `#hsl(${hue % 360} 45% 45%) ${start}deg ${end}deg`
    })
    const center = series[0] ? pct(series[0].value, total) : "—"
    return (
      <div className="spinndoctor-chart-donut">
        <div
          className="spinndoctor-chart-donut-ring"
          style={{ background: `conic-gradient(${stops.join(", ")})` }}
        >
          <div className="spinndoctor-chart-donut-hole">{center}</div>
        </div>
        <ul className="spinndoctor-chart-legend">
          {series.map((row) => (
            <li key={row.label}>
              <span>{row.label}</span>
              <strong>{pct(row.value, total)}</strong>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const max = Math.max(...series.map((row) => row.value), 0.0001)
  return (
    <div className="spinndoctor-chart-hbar">
      {series.map((row) => (
        <div className="spinndoctor-chart-hbar-row" key={row.label}>
          <div className="spinndoctor-chart-hbar-label">{row.label}</div>
          <div className="spinndoctor-chart-hbar-track">
            <div
              className="spinndoctor-chart-hbar-fill"
              style={{ width: `${Math.round((row.value / max) * 100)}%` }}
            />
          </div>
          <div className="spinndoctor-chart-hbar-val">
            {row.value <= 1 ? pct(row.value, 1) : Math.round(row.value)}
          </div>
        </div>
      ))}
    </div>
  )
}
