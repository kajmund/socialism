export type SpindoctorWidgetKind = "chart" | "note" | "report_snippet"

export type SpindoctorChartType = "hbar" | "donut" | "stat_number"

export type SpindoctorWidget = {
  id: string
  kind: SpindoctorWidgetKind
  title: string
  created_at: string
  question_sent_at?: string | null
  latency_ms?: number | null
  chart_type?: SpindoctorChartType | null
  series?: Array<{ label: string; value: number }> | null
  body?: string | null
  section_id?: string | null
}

export function parseSpindoctorWidget(raw: unknown): SpindoctorWidget | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  if (typeof row.id !== "string") return null
  if (row.kind !== "chart" && row.kind !== "note" && row.kind !== "report_snippet") {
    return null
  }
  if (typeof row.title !== "string") return null
  if (typeof row.created_at !== "string") return null
  return {
    id: row.id,
    kind: row.kind,
    title: row.title,
    created_at: row.created_at,
    question_sent_at:
      typeof row.question_sent_at === "string" ? row.question_sent_at : null,
    latency_ms: typeof row.latency_ms === "number" ? row.latency_ms : null,
    chart_type:
      row.chart_type === "hbar" ||
      row.chart_type === "donut" ||
      row.chart_type === "stat_number"
        ? row.chart_type
        : null,
    series: Array.isArray(row.series)
      ? row.series
          .map((item) => {
            if (!item || typeof item !== "object") return null
            const s = item as Record<string, unknown>
            if (typeof s.label !== "string") return null
            if (typeof s.value !== "number") return null
            return { label: s.label, value: s.value }
          })
          .filter((item): item is { label: string; value: number } => item != null)
      : null,
    body: typeof row.body === "string" ? row.body : null,
    section_id: typeof row.section_id === "string" ? row.section_id : null,
  }
}
