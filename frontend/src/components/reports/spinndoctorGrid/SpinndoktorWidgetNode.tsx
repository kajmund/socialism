import { memo, useState } from "react"
import type { Node, NodeProps } from "@xyflow/react"
import { Check, Clipboard, X } from "lucide-react"
import type { SpindoctorWidget } from "@/api/spindoctorWidgets"
import { useLocale } from "@/i18n"
import { SpinndoktorChartSvg } from "./SpinndoktorChartSvg"
import { SpinndoktorInterviewWidget } from "./SpinndoktorInterviewWidget"

export type SpinndoktorWidgetNodeData = {
  widget: SpindoctorWidget
  onOpenSnippet?: (sectionId: string) => void
  onCloseWidget?: (widgetId: string) => void
}

export type SpinndoktorWidgetNode = Node<SpinndoktorWidgetNodeData, "spinndoctorWidget">

function formatWidgetCopyText(
  widget: SpindoctorWidget,
  t: (key: "spinndoctor.grid.snippetSection", params: { section: string }) => string,
): string {
  const lines = [widget.title]
  switch (widget.kind) {
    case "note":
      if (widget.body) lines.push(widget.body)
      break
    case "chart":
      for (const row of widget.series ?? []) {
        const value =
          row.value <= 1 ? `${Math.round(row.value * 100)}%` : String(Math.round(row.value))
        lines.push(`${row.label}: ${value}`)
      }
      break
    case "report_snippet":
      if (widget.section_id) {
        lines.push(t("spinndoctor.grid.snippetSection", { section: widget.section_id }))
      }
      break
    case "interview":
      if (widget.persona_name) lines.push(widget.persona_name)
      break
    default: {
      const _never: never = widget.kind
      return _never
    }
  }
  return lines.join("\n")
}

function WidgetCopyButton({ widget }: { widget: SpindoctorWidget }) {
  const { t } = useLocale()
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(formatWidgetCopyText(widget, t))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard blocked — ignore silently.
    }
  }

  return (
    <button
      type="button"
      className="spinndoctor-widget-copy nodrag nopan"
      title={copied ? t("spinndoctor.grid.copied") : t("spinndoctor.grid.copy")}
      aria-label={copied ? t("spinndoctor.grid.copied") : t("spinndoctor.grid.copy")}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        void handleCopy()
      }}
    >
      {copied ? <Check className="size-3.5" aria-hidden /> : <Clipboard className="size-3.5" aria-hidden />}
    </button>
  )
}

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
  const { widget, onOpenSnippet, onCloseWidget } = data

  return (
    <div className={`spinndoctor-widget spinndoctor-widget--${widget.kind}`}>
      <div className="spinndoctor-widget-head">
        <div className="spinndoctor-widget-title">{widget.title}</div>
        <div className="spinndoctor-widget-head-actions">
          <LatencyBadge latencyMs={widget.latency_ms} />
          <WidgetCopyButton widget={widget} />
          {onCloseWidget ? (
            <button
              type="button"
              className="spinndoctor-widget-copy nodrag nopan"
              title={t("spinndoctor.grid.close")}
              aria-label={t("spinndoctor.grid.close")}
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                onCloseWidget(widget.id)
              }}
            >
              <X className="size-3.5" aria-hidden />
            </button>
          ) : null}
        </div>
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
      {widget.kind === "interview" ? (
        <div className="spinndoctor-widget-interview nowheel nodrag nopan">
          <SpinndoktorInterviewWidget widget={widget} />
        </div>
      ) : null}
    </div>
  )
}

export const SpinndoktorWidgetNode = memo(SpinndoktorWidgetNodeInner)
