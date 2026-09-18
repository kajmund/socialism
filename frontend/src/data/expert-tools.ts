export const EXPERT_TOOL_IDS = [
  "search_companies",
  "lookup_company",
  "validate_orgnr",
  "search_duckduckgo",
  "search_wiki",
  "start_research",
] as const

export type ExpertToolId = (typeof EXPERT_TOOL_IDS)[number]
export type ExpertToolGroup = "company" | "search" | "research"

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
  { id: "start_research", group: "research" },
] as const

export const DEFAULT_EXPERT_TOOLS: ExpertToolId[] = [...EXPERT_TOOL_IDS]

export function isExpertToolId(value: string): value is ExpertToolId {
  return (EXPERT_TOOL_IDS as readonly string[]).includes(value)
}

export function catalogExpertToolIds(): ExpertToolId[] {
  return EXPERT_TOOLS.map((tool) => tool.id)
}

function filterKnownTools(raw: string[]): ExpertToolId[] {
  const seen = new Set<ExpertToolId>()
  const out: ExpertToolId[] = []
  for (const name of raw) {
    if (!isExpertToolId(name) || seen.has(name)) continue
    seen.add(name)
    out.push(name)
  }
  return out
}

export function normalizeExpertTools(raw: string[] | null | undefined): ExpertToolId[] {
  if (raw == null) return [...DEFAULT_EXPERT_TOOLS]
  return filterKnownTools(raw)
}

export function normalizePersonaTools(raw: string[] | null | undefined): ExpertToolId[] {
  if (raw == null) return []
  return filterKnownTools(raw)
}

export function selectAllExpertTools(checked: boolean): ExpertToolId[] {
  return checked ? catalogExpertToolIds() : []
}

export function toggleExpertTool(
  current: readonly ExpertToolId[],
  id: ExpertToolId,
  checked: boolean,
): ExpertToolId[] {
  const selected = new Set(current)
  if (checked) selected.add(id)
  else selected.delete(id)
  return catalogExpertToolIds().filter((name) => selected.has(name))
}
