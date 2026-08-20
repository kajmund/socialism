import { memo } from "react"
import type { Node, NodeProps } from "@xyflow/react"
import type { SpindoctorWidget } from "@/api/spindoctorWidgets"
import { useLocale } from "@/i18n"
import { SpinndoktorChartSvg } from "./SpinndoktorChartSvg"
import { SpinndoktorInterviewWidget } from "./SpinndoktorInterviewWidget"

export type SpinndoktorWidgetNodeData = {
  widget: SpindoctorWidget
  onOpenSnippet?: (sectionId: string) => void
}

export type SpinndoktorWidgetNode = Node<SpinndoktorWidgetNodeData, "spinndoctorWidget">

function LatencyBadge({ latencyMs }: { latencyMs: number | null | undefined }) {
  const { t } = useLocale()
  if (latencyMs == null) return null
  return (
    <span className="spinndoctor-widget-latency" title={t("spinndoctor.grid.latencyHint")}>
      {t("spinndoctor.grid.latency", { ms: latencyMs })}
    </span>
  )
}

function SpinndoktorWidgetNodeInner({ data }: NodeProps<SpinndoktorWidgetNode>) {
  const { t } = useLocale()
  const { widget, onOpenSnippet } = data

  return (
    <div className={`spinndoctor-widget spinndoctor-widget--${widget.kind}`}>
      <div className="spinndoctor-widget-head">
        <div className="spinndoctor-widget-title">{widget.title}</div>
        <LatencyBadge latencyMs={widget.latency_ms} />
      </div>
      {widget.kind === "note" && widget.body ? (
        <p className="spinndoctor-widget-note">{widget.body}</p>
      ) : null}
      {widget.kind === "chart" && widget.chart_type && widget.series ? (
        <SpinndoktorChartSvg chartType={widget.chart_type} series={widget.series} />
      ) : null}
      {widget.kind === "report_snippet" && widget.section_id ? (
        <div className="spinndoctor-widget-snippet">
          <p>{t("spinndoctor.grid.snippetSection", { section: widget.section_id })}</p>
          <button
            type="button"
            className="spinndoctor-widget-snippet-btn"
            onClick={() => onOpenSnippet?.(widget.section_id!)}
          >
            {t("spinndoctor.grid.openSection")}
          </button>
        </div>
      ) : null}
      {widget.kind === "interview" ? <SpinndoktorInterviewWidget widget={widget} /> : null}
    </div>
  )
}

export const SpinndoktorWidgetNode = memo(SpinndoktorWidgetNodeInner)
