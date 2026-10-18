import { useEffect, useMemo } from "react"
import { Background, Controls, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import type { Relations, SourceReference, WorkspaceSelection } from "@/api/voiceWorkspaces"
import { useLocale } from "@/i18n"
import { layoutRelationNodes, placeRelationFocus, relationColumn, relationFocus, relationKindKey } from "./relationLayout"
import { WorkspaceReferences } from "./WorkspaceReferences"

export function WorkspaceRelations({ relations, references, selection, onSelect, onOpen }: { relations: Relations; references: SourceReference[]; selection?: WorkspaceSelection | null; onSelect: (selection: WorkspaceSelection | null) => void; onOpen: (id: string) => void }) {
  const focus = useMemo(() => relationFocus(relations, selection), [relations, selection])
  const positions = useMemo(() => {
    const placed = layoutRelationNodes(relations)
    return focus ? placeRelationFocus(relations, focus, selection?.node_id, placed) : placed
  }, [focus, relations, selection?.node_id])
  const nodes = useMemo<Node[]>(() => {
    const active = focus ? new Set(focus.nodeIds) : null
    return relations.nodes.map((node) => {
      const column = relationColumn(node.kind)
      const dimmed = active != null && !active.has(node.id)
      return {
        id: node.id,
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: positions.get(node.id) ?? { x: column * 480, y: 0 },
        hidden: dimmed,
        zIndex: dimmed ? 0 : 2,
        data: { label: <RelationNode node={node} references={references} onOpen={onOpen} /> },
        selected: node.id === selection?.node_id,
        style: { background: column === 0 ? "#f2d276" : column === 1 ? "#14161b" : "#fff", color: column === 1 ? "#fff" : "#14161b", border: node.id === selection?.node_id ? "2px solid #c79c3c" : "1px solid #dedee3", borderRadius: 12, width: 250, padding: 16 },
      }
    })
  }, [focus, onOpen, positions, references, relations.nodes, selection?.node_id])
  const edges = useMemo<Edge[]>(() => {
    const active = focus ? new Set(focus.edgeIds) : null
    return relations.edges.map((edge) => {
      const emphasized = active == null || active.has(edge.id)
      const color = edgeColor(edge, emphasized)
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "smoothstep",
        ariaLabel: edge.label,
        zIndex: emphasized && active ? 3 : 0,
        interactionWidth: 24,
        selected: edge.id === selection?.edge_id,
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 18, height: 18 },
        style: { stroke: color, strokeDasharray: edge.interpretation ? "6 4" : undefined, strokeWidth: emphasized && active ? 2.5 : 1.75 },
      }
    })
  }, [focus, relations.edges, selection?.edge_id])
  return <div className="flex h-full min-h-0 flex-col lg:flex-row">
    <div className="min-h-60 min-w-0 flex-1"><ReactFlowProvider><div className="h-full w-full"><RelationGraph nodes={nodes} edges={edges} focusKey={focus ? `${focus.nodeIds.join("\n")}|${focus.edgeIds.join("\n")}` : ""} onSelect={onSelect} /></div></ReactFlowProvider></div>
    <RelationshipList relations={relations} references={references} selection={selection} onSelect={onSelect} onOpen={onOpen} />
  </div>
}

function edgeColor(edge: Relations["edges"][number], emphasized: boolean): string {
  if (!emphasized) return "#d0d0d6"
  return edge.interpretation ? "#c79c3c" : "#222"
}

function RelationGraph({ nodes, edges, focusKey, onSelect }: { nodes: Node[]; edges: Edge[]; focusKey: string; onSelect: (selection: WorkspaceSelection | null) => void }) {
  const { t } = useLocale()
  const { fitView } = useReactFlow()
  useEffect(() => {
    const ids = focusKey ? focusKey.split("|")[0].split("\n") : undefined
    const frame = requestAnimationFrame(() => { void fitView({ nodes: ids?.map((id) => ({ id })), padding: 0.22, duration: 180, maxZoom: 1.05 }) })
    return () => cancelAnimationFrame(frame)
  }, [fitView, focusKey])
  return <ReactFlow className="h-full" nodes={nodes} edges={edges} fitView minZoom={0.4} nodesDraggable={false} edgesReconnectable={false} deleteKeyCode={null} ariaLabelConfig={{ "node.a11yDescription.default": t("voiceWorkspaceChat.graphNodeInstructions"), "node.a11yDescription.keyboardDisabled": t("voiceWorkspaceChat.graphNodeInstructions"), "edge.a11yDescription.default": t("voiceWorkspaceChat.graphEdgeInstructions"), "controls.ariaLabel": t("voiceWorkspaceChat.graphControls"), "controls.zoomIn.ariaLabel": t("voiceWorkspaceChat.zoomIn"), "controls.zoomOut.ariaLabel": t("voiceWorkspaceChat.zoomOut"), "controls.fitView.ariaLabel": t("voiceWorkspaceChat.fitGraph") }} onNodeClick={(_, node) => onSelect({ node_id: node.id })} onEdgeClick={(_, edge) => onSelect({ edge_id: edge.id })} onPaneClick={() => onSelect(null)}><Background color="#ccc" gap={28} /><Controls showInteractive={false} /></ReactFlow>
}

function RelationNode({ node, references, onOpen }: { node: Relations["nodes"][number]; references: SourceReference[]; onOpen: (id: string) => void }) {
  const { t } = useLocale()
  return <div className="space-y-2 text-left"><span className="block text-[10px] font-bold uppercase tracking-wider">{t(relationKindKey(node.kind))}</span><strong className="block">{node.label}</strong><WorkspaceReferences ids={node.source_refs} references={references} onOpen={onOpen} /></div>
}

function RelationshipList({ relations, references, selection, onSelect, onOpen }: { relations: Relations; references: SourceReference[]; selection?: WorkspaceSelection | null; onSelect: (selection: WorkspaceSelection | null) => void; onOpen: (id: string) => void }) {
  const { t } = useLocale()
  const focus = relationFocus(relations, selection)
  const edges = focus ? relations.edges.filter((edge) => focus.edgeIds.includes(edge.id)) : relations.edges
  const selectedNode = relations.nodes.find((node) => node.id === selection?.node_id)
  const selectedEdge = relations.edges.find((edge) => edge.id === selection?.edge_id)
  const nodes = new Map(relations.nodes.map((node) => [node.id, node]))
  return <section className="flex max-h-[40%] min-h-32 w-full min-w-0 shrink-0 flex-col overflow-hidden border-t border-[color:var(--border-hairline)] bg-white lg:max-h-none lg:w-[min(42%,28rem)] lg:border-t-0 lg:border-l">
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[color:var(--border-hairline)] px-3 py-2">
      <strong className="min-w-0 truncate text-sm" title={selectedNode?.label ?? selectedEdge?.label}>{selectedNode?.label ?? selectedEdge?.label ?? t("voiceWorkspaceChat.relationships")}</strong>
      {focus ? <button type="button" className="shrink-0 rounded border px-2 py-1 text-xs focus-visible:ring-2 focus-visible:ring-db-gold-500" onClick={() => onSelect(null)}>{t("voiceWorkspaceChat.showAllRelationships")}</button> : null}
    </header>
    <div className="min-h-0 flex-1 overflow-auto p-2">
      {edges.length ? <ul className="space-y-2">{edges.map((edge) => {
        const source = nodes.get(edge.source)
        const target = nodes.get(edge.target)
        return <li key={edge.id} className={`rounded border px-3 py-2 ${edge.id === selection?.edge_id ? "border-[#c79c3c]" : "border-[color:var(--border-hairline)]"}`}>
          {source ? <Endpoint node={source} selected={source.id === selection?.node_id} onSelect={onSelect} /> : null}
          <button type="button" className="my-1 flex w-full min-w-0 items-start gap-2 text-left text-xs font-semibold focus-visible:ring-2 focus-visible:ring-db-gold-500" onClick={() => onSelect({ edge_id: edge.id })}>
            <span className="min-w-0 flex-1 break-words">{edge.label}</span>
            {edge.interpretation ? <span className="shrink-0 text-db-gold-700">{t("voiceWorkspaceChat.interpretation")}</span> : null}
            <span className="shrink-0 text-base leading-none" aria-hidden="true">→</span>
          </button>
          {target ? <Endpoint node={target} selected={target.id === selection?.node_id} onSelect={onSelect} /> : null}
          {edge.source_refs.length ? <div className="mt-2"><WorkspaceReferences ids={edge.source_refs} references={references} onOpen={onOpen} /></div> : null}
        </li>
      })}</ul> : <p className="px-2 py-3 text-sm text-muted-foreground">{selectedNode ? t("voiceWorkspaceChat.noNodeRelationships") : t("voiceWorkspaceChat.noRelationships")}</p>}
    </div>
  </section>
}

function Endpoint({ node, selected, onSelect }: { node: Relations["nodes"][number]; selected: boolean; onSelect: (selection: WorkspaceSelection) => void }) {
  const { t } = useLocale()
  return <button type="button" className="block w-full min-w-0 text-left focus-visible:ring-2 focus-visible:ring-db-gold-500" onClick={() => onSelect({ node_id: node.id })}>
    <span className="block text-[10px] font-bold uppercase tracking-wider">{t(relationKindKey(node.kind))}</span>
    <span className={selected ? "block break-words font-semibold" : "block break-words"}>{node.label}</span>
  </button>
}
