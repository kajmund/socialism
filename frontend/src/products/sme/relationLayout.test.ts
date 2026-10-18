import { describe, expect, it } from "vitest"
import type { Relations } from "@/api/voiceWorkspaces"
import { layoutRelationNodes, placeRelationFocus, relationFocus, relationNodePitch } from "./relationLayout"

const node = (id: string, kind: string, label = id): Relations["nodes"][number] => ({ id, label, kind, source_refs: [] })

describe("relation layout", () => {
  it("keeps a wrapped label from covering the node above it", () => {
    const relations: Relations = { nodes: [node("a", "event", "Kort"), node("b", "event", "x".repeat(80))], edges: [] }
    const positions = layoutRelationNodes(relations)
    expect(positions.get("b")!.y).toBeGreaterThanOrEqual(positions.get("a")!.y + relationNodePitch("Kort", 0))
    expect(positions.get("b")!.x).toBe(positions.get("a")!.x)
  })

  it("places a consequence beside the event it belongs to", () => {
    const relations: Relations = {
      nodes: [node("a", "event"), node("c", "event"), node("early", "effect", "kopplad till sista"), node("late", "effect", "kopplad till första")],
      edges: [
        { id: "to-late", source: "a", target: "late", label: "ger", interpretation: false, source_refs: [] },
        { id: "to-early", source: "c", target: "early", label: "ger", interpretation: false, source_refs: [] },
      ],
    }
    const positions = layoutRelationNodes(relations)
    expect(positions.get("late")!.y).toBeLessThan(positions.get("early")!.y)
    expect(positions.get("late")!.x).toBeGreaterThan(positions.get("a")!.x)
  })

  it("focuses the relationships of the selected item", () => {
    const relations: Relations = {
      nodes: [node("a", "event"), node("b", "effect"), node("c", "effect")],
      edges: [
        { id: "ab", source: "a", target: "b", label: "ger", interpretation: false, source_refs: [] },
        { id: "ac", source: "a", target: "c", label: "ger", interpretation: true, source_refs: [] },
      ],
    }
    expect(relationFocus(relations, { node_id: "a" })).toEqual({ nodeIds: ["a", "b", "c"], edgeIds: ["ab", "ac"] })
    expect(relationFocus(relations, { edge_id: "ab" })).toEqual({ nodeIds: ["a", "b"], edgeIds: ["ab"] })
    expect(relationFocus(relations, { node_id: "missing" })).toBeNull()
    expect(relationFocus(relations, null)).toBeNull()
  })

  it("draws a selected relationship beside its endpoints instead of across the whole map", () => {
    const relations: Relations = {
      nodes: [node("a", "event", "Första händelsen"), node("b", "effect", "En konsekvens långt ner"), node("c", "effect", "x".repeat(80))],
      edges: [{ id: "ab", source: "a", target: "b", label: "ger", interpretation: false, source_refs: [] }],
    }
    const base = layoutRelationNodes(relations)
    const placed = placeRelationFocus(relations, { nodeIds: ["a", "b"], edgeIds: ["ab"] }, "a", base)
    expect(placed.get("a")).toEqual({ x: 0, y: 0 })
    expect(placed.get("b")!.x).toBeGreaterThan(placed.get("a")!.x)
    expect(placed.get("b")!.y).toBe(0)
    expect(placed.get("c")).toEqual(base.get("c"))
  })
})
