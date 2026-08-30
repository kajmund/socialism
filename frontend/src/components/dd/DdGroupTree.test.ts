import { describe, expect, it } from "vitest"
import type { DdResearchCompany } from "@/api/dd"
import { childrenOf, rootCompanies } from "./researchGroup"

function company(
  namn: string,
  orgnr: string,
  parent_orgnr: string,
  relation: DdResearchCompany["relation"] = "dotterbolag",
): DdResearchCompany {
  return { namn, orgnr, parent_orgnr, relation, nyckeltal: [], styrelse: [] }
}

function walkCount(
  companies: DdResearchCompany[],
  node: DdResearchCompany,
  seen = new Set<string>(),
): number {
  const key = node.orgnr || `name:${node.namn}`
  if (seen.has(key)) return 0
  seen.add(key)
  return (
    1 +
    childrenOf(companies, node.orgnr).reduce(
      (sum, child) => sum + walkCount(companies, child, seen),
      0,
    )
  )
}

describe("researchGroup tree", () => {
  const groupLike: DdResearchCompany[] = [
    company("Akind Universe AB", "556944-8805", "", "moderbolag"),
    company("Academic Work Group AB", "556858-4188", "556944-8805"),
    company("Academic Work Norway A/S", "", "556858-4188"),
    company("Crowd Collective Linköping AB", "559334-2586", "556858-4188", "kandidat"),
  ]

  it("does not treat empty orgnr as parent of every unparented company", () => {
    expect(childrenOf(groupLike, "")).toEqual([])
    expect(childrenOf(groupLike, "556858-4188").map((row) => row.namn)).toEqual([
      "Academic Work Norway A/S",
      "Crowd Collective Linköping AB",
    ])
  })

  it("walks a group tree with nameless foreign companies in finite steps", () => {
    const roots = rootCompanies(groupLike)
    const seen = new Set<string>()
    const count = roots.reduce((sum, root) => sum + walkCount(groupLike, root, seen), 0)
    expect(count).toBe(4)
  })
})
