export type SpindoctorWidgetKind = "chart" | "note" | "report_snippet" | "interview"

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
  persona_id?: string | null
  persona_name?: string | null
  run_id?: number | null
  attempt_id?: string | null
  variant_id?: string | null
  through_tick_index?: number | null
}

const WIDGET_KINDS: SpindoctorWidgetKind[] = [
  "chart",
  "note",
  "report_snippet",
  "interview",
]

function isWidgetKind(value: unknown): value is SpindoctorWidgetKind {
  return typeof value === "string" && WIDGET_KINDS.includes(value as SpindoctorWidgetKind)
}

export function parseSpindoctorWidget(raw: unknown): SpindoctorWidget | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  if (typeof row.id !== "string") return null
  if (!isWidgetKind(row.kind)) return null
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
            const seriesRow = item as Record<string, unknown>
            if (typeof seriesRow.label !== "string") return null
            if (typeof seriesRow.value !== "number") return null
            return { label: seriesRow.label, value: seriesRow.value }
          })
          .filter((item): item is { label: string; value: number } => item != null)
      : null,
    body: typeof row.body === "string" ? row.body : null,
    section_id: typeof row.section_id === "string" ? row.section_id : null,
    persona_id: typeof row.persona_id === "string" ? row.persona_id : null,
    persona_name: typeof row.persona_name === "string" ? row.persona_name : null,
    run_id: typeof row.run_id === "number" ? row.run_id : null,
    attempt_id: typeof row.attempt_id === "string" ? row.attempt_id : null,
    variant_id: typeof row.variant_id === "string" ? row.variant_id : null,
    through_tick_index:
      typeof row.through_tick_index === "number" ? row.through_tick_index : null,
  }
}
