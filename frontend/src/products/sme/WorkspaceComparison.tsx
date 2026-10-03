import type { Comparison, SourceReference } from "@/api/workspaces"
import { useLocale } from "@/i18n"
import { WorkspaceReferences } from "./WorkspaceReferences"

export function WorkspaceComparison({ comparison, references, onOpen }: { comparison: Comparison; references: SourceReference[]; onOpen: (id: string) => void }) {
  const { t } = useLocale()
  return <div className="overflow-auto p-5"><table className="w-full border-collapse text-left text-sm"><thead><tr><th className="border-b p-3" />{comparison.columns.map((column, i) => <th key={i} className="border-b bg-db-ink-50 p-3 font-semibold">{column}</th>)}</tr></thead><tbody>{comparison.rows.map((row) => <tr key={row.id}><th className="border-b p-3 font-medium">{row.label}</th>{row.cells.map((cell, i) => <td key={i} className="min-w-40 border-b p-3 align-top"><p className="mb-2 whitespace-pre-wrap">{cell.text ?? t("workspaceChat.unknown")}</p><WorkspaceReferences ids={cell.source_refs} references={references} onOpen={onOpen} /></td>)}</tr>)}</tbody></table></div>
}
