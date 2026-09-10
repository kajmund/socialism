import { describe, expect, it } from "vitest"

import {
  citationForFoundItem,
  foundItemsInOrdinalOrder,
  parseEvidenceRef,
  resolveEvidenceRef,
} from "./evidenceRefs"
import { fixtureEvidence, mixedEvidence } from "./executionFixtures"

describe("evidenceRefs", () => {
  it("assigns E-numbers only to found items in ordinal order", () => {
    const found = foundItemsInOrdinalOrder(mixedEvidence.items)
    expect(found.map((item) => item.id)).toEqual(["item-found"])
    expect(citationForFoundItem(mixedEvidence.items, "item-found")).toBe("E1")
    expect(citationForFoundItem(mixedEvidence.items, "item-missing")).toBeNull()
  })

  it("resolves E1 from persisted evidence_refs and from found order", () => {
    const fromMap = resolveEvidenceRef("E1", fixtureEvidence.items, {
      E1: { item_id: "item-e1", ordinal: 0 },
    })
    expect(fromMap?.id).toBe("item-e1")
    expect(resolveEvidenceRef("E2", fixtureEvidence.items)?.id).toBe("item-e2")
    expect(resolveEvidenceRef("E99", fixtureEvidence.items)).toBeNull()
    expect(resolveEvidenceRef("nope", fixtureEvidence.items)).toBeNull()
  })

  it("parses citation indexes", () => {
    expect(parseEvidenceRef("E1")).toBe(1)
    expect(parseEvidenceRef("E12")).toBe(12)
    expect(parseEvidenceRef("[E1]")).toBeNull()
  })
})
