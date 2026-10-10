import { api } from "@/lib/api"

export type OvergraphKind = "knowledge" | "memory"

export type OvergraphLabel = {
  label: string
  count: number
}

export type OvergraphCatalog = {
  kind: OvergraphKind
  dimension: number
  node_labels: OvergraphLabel[]
  edge_labels: OvergraphLabel[]
}

export type OvergraphNode = {
  id: number
  key: string
  labels: string[]
  weight: number
  preview: string
}

export type OvergraphNodePage = {
  nodes: OvergraphNode[]
  next_cursor: number | null
}

export type OvergraphEdge = {
  direction: "outgoing" | "incoming"
  edge_id: number
  label: string
  weight: number
  valid_from: number | null
  valid_to: number | null
  props: Record<string, unknown>
  node: OvergraphNode | null
}

export type OvergraphNodeDetail = OvergraphNode & {
  props: Record<string, unknown>
  created_at: number | null
  updated_at: number | null
  edges: OvergraphEdge[]
}

export function listOvergraphCatalogs(): Promise<{ catalogs: OvergraphCatalog[] }> {
  return api.get("/overgraph")
}

export function listOvergraphNodes(
  kind: OvergraphKind,
  query: { label: string; q?: string; limit?: number; after?: number | null },
): Promise<OvergraphNodePage> {
  return api.get(`/overgraph/${kind}/nodes`, {
    label: query.label,
    q: query.q,
    limit: query.limit,
    after: query.after ?? undefined,
  })
}

export function getOvergraphNode(kind: OvergraphKind, nodeId: number): Promise<OvergraphNodeDetail> {
  return api.get(`/overgraph/${kind}/nodes/${nodeId}`)
}
