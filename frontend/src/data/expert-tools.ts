export const EXPERT_TOOL_IDS = [
  "search_companies",
  "lookup_company",
  "validate_orgnr",
  "search_duckduckgo",
  "search_wiki",
] as const

export type ExpertToolId = (typeof EXPERT_TOOL_IDS)[number]
export type ExpertToolGroup = "company" | "search"

export type ExpertToolDef = {
  id: ExpertToolId
  group: ExpertToolGroup
}

export const EXPERT_TOOLS: readonly ExpertToolDef[] = [
  { id: "search_companies", group: "company" },
  { id: "lookup_company", group: "company" },
  { id: "validate_orgnr", group: "company" },
  { id: "search_duckduckgo", group: "search" },
  { id: "search_wiki", group: "search" },
] as const

export const DEFAULT_EXPERT_TOOLS: ExpertToolId[] = [...EXPERT_TOOL_IDS]

export function isExpertToolId(value: string): value is ExpertToolId {
  return (EXPERT_TOOL_IDS as readonly string[]).includes(value)
}

export function normalizeExpertTools(raw: string[] | null | undefined): ExpertToolId[] {
  if (raw == null) return [...DEFAULT_EXPERT_TOOLS]
  const seen = new Set<ExpertToolId>()
  const out: ExpertToolId[] = []
  for (const name of raw) {
    if (!isExpertToolId(name) || seen.has(name)) continue
    seen.add(name)
    out.push(name)
  }
  return out
}
