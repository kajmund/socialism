import type { SourceReference, WorkspaceChart } from "@/api/voiceWorkspaces"
import { SpinndoktorChartSvg } from "@/components/reports/spinndoctorGrid/SpinndoktorChartSvg"
import { WorkspaceReferences } from "./WorkspaceReferences"

export function WorkspaceChartView({ chart, references, onOpen }: { chart: WorkspaceChart; references: SourceReference[]; onOpen: (id: string) => void }) {
  return <div className="p-6"><h3 className="mb-4 font-semibold">{chart.title}</h3><div className="rounded-xl border bg-white p-4"><SpinndoktorChartSvg chartType={chart.chart_type} series={chart.series} /></div><div className="mt-3"><WorkspaceReferences ids={chart.source_refs} references={references} onOpen={onOpen} /></div></div>
}
