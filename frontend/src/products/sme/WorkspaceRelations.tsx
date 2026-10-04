import { useMemo } from "react"
import { Background, Controls, ReactFlow, Position, MarkerType, type Node, type Edge } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import type { Relations, SourceReference, WorkspaceSelection } from "@/api/voiceWorkspaces"
import { WorkspaceReferences } from "./WorkspaceReferences"
import { useLocale } from "@/i18n"

export function WorkspaceRelations({ relations, references, selection, onSelect, onOpen }: { relations: Relations; references: SourceReference[]; selection?: WorkspaceSelection | null; onSelect: (selection: WorkspaceSelection) => void; onOpen: (id: string) => void }) {
  const { t } = useLocale()
  const nodes = useMemo<Node[]>(() => {
    const columns = new Map<number, number>()
    return relations.nodes.map((node) => {
      const column = node.kind === "event" ? 0 : node.kind === "condition" ? 1 : 2
      const row = columns.get(column) ?? 0; columns.set(column, row + 1)
      return { id: node.id, sourcePosition: Position.Right, targetPosition: Position.Left, position: { x: column * 420, y: row * 160 }, data: { label: <div className="space-y-2 text-left"><span className="block text-[10px] font-bold uppercase tracking-wider">{t(node.kind === "event" ? "voiceWorkspaceChat.event" : node.kind === "condition" ? "voiceWorkspaceChat.condition" : node.kind === "effect" ? "voiceWorkspaceChat.effect" : "voiceWorkspaceChat.interpretation")}</span><strong className="block">{node.label}</strong><WorkspaceReferences ids={node.source_refs} references={references} onOpen={onOpen} /></div> }, selected: node.id === selection?.node_id, style: { background: column === 0 ? "#f2d276" : column === 1 ? "#14161b" : "#fff", color: column === 1 ? "#fff" : "#14161b", border: node.id === selection?.node_id ? "2px solid #c79c3c" : "1px solid #dedee3", borderRadius: 12, width: 230, padding: 16 } }
    })
  }, [onOpen, references, relations.nodes, selection?.node_id, t])
  const edges = useMemo<Edge[]>(() => relations.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, label: edge.label, ariaLabel: edge.label, selected: edge.id === selection?.edge_id, markerEnd: { type: MarkerType.ArrowClosed, color: edge.interpretation ? "#c79c3c" : "#222", width: 18, height: 18 }, style: { stroke: edge.interpretation ? "#c79c3c" : "#222", strokeDasharray: edge.interpretation ? "6 4" : undefined, strokeWidth: 2 } })), [relations.edges, selection?.edge_id])
  const selectedEdge = relations.edges.find((edge) => edge.id === selection?.edge_id)
  return <div className="flex h-full min-h-0 flex-col">
    <div className="min-h-[280px] flex-1"><ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.15} nodesDraggable={false} deleteKeyCode={null} ariaLabelConfig={{ "node.a11yDescription.default": t("voiceWorkspaceChat.graphNodeInstructions"), "node.a11yDescription.keyboardDisabled": t("voiceWorkspaceChat.graphNodeInstructions"), "edge.a11yDescription.default": t("voiceWorkspaceChat.graphEdgeInstructions"), "controls.ariaLabel": t("voiceWorkspaceChat.graphControls"), "controls.zoomIn.ariaLabel": t("voiceWorkspaceChat.zoomIn"), "controls.zoomOut.ariaLabel": t("voiceWorkspaceChat.zoomOut"), "controls.fitView.ariaLabel": t("voiceWorkspaceChat.fitGraph") }} onNodeClick={(_, node) => onSelect({ node_id: node.id })} onEdgeClick={(_, edge) => onSelect({ edge_id: edge.id })}><Background color="#ccc" gap={28} /><Controls showInteractive={false} /></ReactFlow></div>
    <div className="flex flex-wrap gap-2 border-t border-[color:var(--border-hairline)] bg-white p-3">{relations.nodes.map((node) => <button key={node.id} type="button" className="rounded border px-2 py-1 text-xs focus-visible:ring-2 focus-visible:ring-db-gold-500" onClick={() => onSelect({ node_id: node.id })}>{node.label}</button>)}</div>
    {selectedEdge ? <div className="border-t bg-white p-3 text-sm"><strong>{selectedEdge.label}</strong>{selectedEdge.interpretation ? <span className="ml-2 text-db-gold-700">{t("voiceWorkspaceChat.interpretation")}</span> : null} <WorkspaceReferences ids={selectedEdge.source_refs} references={references} onOpen={onOpen} /></div> : null}
  </div>
}
