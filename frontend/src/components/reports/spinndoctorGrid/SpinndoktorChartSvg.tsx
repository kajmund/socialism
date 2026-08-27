import type { SpindoctorChartType } from "@/api/spindoctorWidgets"

type SeriesRow = { label: string; value: number }

function pct(value: number, total: number): string {
  if (total <= 0) return "0%"
  return `${Math.round((value / total) * 100)}%`
}

function formatChartValue(chartType: SpindoctorChartType, value: number): string {
  if (chartType === "radar") return `${Math.round(value * 10) / 10}/10`
  if (value <= 1) return pct(value, 1)
  return String(Math.round(value))
}

function RadarChart({ series }: { series: SeriesRow[] }) {
  const size = 220
  const cx = size / 2
  const cy = size / 2
  const maxRadius = 78
  const maxValue = 10
  const count = Math.max(series.length, 3)
  const angleStep = (Math.PI * 2) / count

  const pointFor = (index: number, value: number) => {
    const angle = -Math.PI / 2 + index * angleStep
    const radius = (Math.max(0, Math.min(value, maxValue)) / maxValue) * maxRadius
    return {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    }
  }

  const gridLevels = [2, 4, 6, 8, 10]
  const polygonPoints = series
    .map((row, index) => {
      const { x, y } = pointFor(index, row.value)
      return `${x},${y}`
    })
    .join(" ")

  return (
    <div className="spinndoctor-chart-radar">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="spinndoctor-chart-radar-svg"
        role="img"
        aria-hidden
      >
        {gridLevels.map((level) => {
          const ring = Array.from({ length: count }, (_, index) => {
            const { x, y } = pointFor(index, level)
            return `${x},${y}`
          }).join(" ")
          return (
            <polygon
              key={level}
              points={ring}
              className="spinndoctor-chart-radar-grid"
            />
          )
        })}
        {series.map((row, index) => {
          const outer = pointFor(index, maxValue)
          return (
            <line
              key={row.label}
              x1={cx}
              y1={cy}
              x2={outer.x}
              y2={outer.y}
              className="spinndoctor-chart-radar-axis"
            />
          )
        })}
        {polygonPoints ? (
          <polygon points={polygonPoints} className="spinndoctor-chart-radar-fill" />
        ) : null}
        {series.map((row, index) => {
          const { x, y } = pointFor(index, row.value)
          return <circle key={`${row.label}-dot`} cx={x} cy={y} r={3.5} className="spinndoctor-chart-radar-dot" />
        })}
      </svg>
      <ul className="spinndoctor-chart-legend">
        {series.map((row) => (
          <li key={row.label}>
            <span>{row.label}</span>
            <strong>{formatChartValue("radar", row.value)}</strong>
          </li>
        ))}
      </ul>
    </div>
  )
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

  if (chartType === "radar") {
    return <RadarChart series={series} />
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
            {formatChartValue("hbar", row.value)}
          </div>
        </div>
      ))}
    </div>
  )
}
