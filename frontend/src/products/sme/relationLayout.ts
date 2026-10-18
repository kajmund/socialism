import type { Relations } from "@/api/voiceWorkspaces"

export type RelationPoint = { x: number; y: number }

const COLUMN_GAP = 480
const CHARS_PER_LINE = 26

export function relationColumn(kind: string): number {
  if (kind === "event") return 0
  if (kind === "condition") return 1
  return 2
}

export function relationKindKey(kind: string): "voiceWorkspaceChat.event" | "voiceWorkspaceChat.condition" | "voiceWorkspaceChat.effect" | "voiceWorkspaceChat.interpretation" {
  if (kind === "event") return "voiceWorkspaceChat.event"
  if (kind === "condition") return "voiceWorkspaceChat.condition"
  if (kind === "effect") return "voiceWorkspaceChat.effect"
  return "voiceWorkspaceChat.interpretation"
}

/** Pitch matches a 250px node so a wrapped label does not cover the next row. */
export function relationNodePitch(label: string, referenceCount: number): number {
  const lines = Math.ceil(Math.max(label.length, 1) / CHARS_PER_LINE)
  return 96 + lines * 24 + (referenceCount > 0 ? 36 : 0)
}

export function layoutRelationNodes(relations: Relations): Map<string, RelationPoint> {
  const columns: string[][] = [[], [], []]
  const nodes = new Map(relations.nodes.map((node) => [node.id, node]))
  for (const node of relations.nodes) columns[relationColumn(node.kind)].push(node.id)
  const index = new Map(relations.nodes.map((node, position) => [node.id, position]))
  for (let sweep = 0; sweep < 4; sweep += 1) {
    const sequence = sweep % 2 === 0 ? [1, 2] : [1, 0]
    for (const column of sequence) alignColumn(columns, column, relations.edges, nodes, index)
  }
  const positions = new Map<string, RelationPoint>()
  columns.forEach((ids, column) => {
    let y = 0
    for (const id of ids) {
      positions.set(id, { x: column * COLUMN_GAP, y })
      const node = nodes.get(id)
      y += relationNodePitch(node?.label ?? "", node?.source_refs.length ?? 0)
    }
  })
  return positions
}

const FOCUS_ROWS = 4
const FOCUS_COLUMN = 360

/** Pulls the selected neighborhood together so a large map can zoom in on it. */
export function placeRelationFocus(relations: Relations, focus: { nodeIds: string[]; edgeIds: string[] }, selectedId: string | undefined, base: Map<string, RelationPoint>): Map<string, RelationPoint> {
  const positions = new Map(base)
  const anchor = selectedId && focus.nodeIds.includes(selectedId) ? selectedId : focus.nodeIds[0]
  if (!anchor) return positions
  positions.set(anchor, { x: 0, y: 0 })
  let column = 0
  let y = 0
  let row = 0
  for (const id of focus.nodeIds) {
    if (id === anchor) continue
    if (row >= FOCUS_ROWS) { column += 1; y = 0; row = 0 }
    positions.set(id, { x: FOCUS_COLUMN * (column + 1), y })
    const node = relations.nodes.find((item) => item.id === id)
    y += relationNodePitch(node?.label ?? "", node?.source_refs.length ?? 0)
    row += 1
  }
  return positions
}

export function relationFocus(relations: Relations, selection: { node_id?: string; edge_id?: string } | null | undefined): { nodeIds: string[]; edgeIds: string[] } | null {
  if (selection?.edge_id) {
    const edge = relations.edges.find((row) => row.id === selection.edge_id)
    return edge ? { nodeIds: [edge.source, edge.target], edgeIds: [edge.id] } : null
  }
  if (!selection?.node_id || !relations.nodes.some((node) => node.id === selection.node_id)) return null
  const edges = relations.edges.filter((edge) => edge.source === selection.node_id || edge.target === selection.node_id)
  return {
    nodeIds: [...new Set([selection.node_id, ...edges.flatMap((edge) => [edge.source, edge.target])])],
    edgeIds: edges.map((edge) => edge.id),
  }
}

function alignColumn(columns: string[][], column: number, edges: Relations["edges"], nodes: Map<string, Relations["nodes"][number]>, index: Map<string, number>) {
  const placed = new Map<string, number>()
  columns.forEach((ids, columnIndex) => {
    if (columnIndex === column) return
    for (const [id, y] of columnYs(ids, nodes)) placed.set(id, y)
  })
  const current = columnYs(columns[column], nodes)
  const ranked = columns[column].map((id) => ({ id, weight: medianNeighbor(id, edges, placed) ?? current.get(id) ?? 0 }))
  ranked.sort((a, b) => a.weight - b.weight || (index.get(a.id) ?? 0) - (index.get(b.id) ?? 0))
  columns[column] = ranked.map((row) => row.id)
}

function columnYs(ids: string[], nodes: Map<string, Relations["nodes"][number]>): Map<string, number> {
  const ys = new Map<string, number>()
  let y = 0
  for (const id of ids) {
    ys.set(id, y)
    const node = nodes.get(id)
    y += relationNodePitch(node?.label ?? "", node?.source_refs.length ?? 0)
  }
  return ys
}

function medianNeighbor(id: string, edges: Relations["edges"], placed: Map<string, number>): number | null {
  const weights = edges.flatMap((edge) => {
    if (edge.source === id && placed.has(edge.target)) return [placed.get(edge.target) ?? 0]
    if (edge.target === id && placed.has(edge.source)) return [placed.get(edge.source) ?? 0]
    return []
  })
  if (!weights.length) return null
  weights.sort((a, b) => a - b)
  return weights[Math.floor(weights.length / 2)]
}
