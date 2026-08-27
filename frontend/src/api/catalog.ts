import { api } from "@/lib/api"

export type CatalogSection =
  | "demografi"
  | "politik"
  | "varderingar"
  | "rost_media"
  | "simulering"
  | "dd_expertpanel"

export type GeoBounds = {
  south: number
  west: number
  north: number
  east: number
}

export type CatalogItem = {
  label: string
  description: string
  bounds: GeoBounds | null
  kompetensomrade?: string
  radgivningsstil?: string
  yrkesbakgrund?: string
  professionell_anekdot?: string
}

export type CatalogList = {
  key: string
  section: CatalogSection
  title: string
  items: CatalogItem[]
  updated_at: string
}

export const SECTION_ORDER: CatalogSection[] = [
  "demografi",
  "politik",
  "varderingar",
  "rost_media",
  "simulering",
  "dd_expertpanel",
]

export function listCatalog(): Promise<CatalogList[]> {
  return api.get<CatalogList[]>("/catalog")
}

export function getCatalogList(key: string): Promise<CatalogList> {
  return api.get<CatalogList>(`/catalog/${key}`)
}

export function updateCatalogList(
  key: string,
  items: CatalogItem[],
): Promise<CatalogList> {
  return api.put<CatalogList>(`/catalog/${key}`, { items })
}

/** Map catalog rows to field-key → option labels for persona composer selects. */
export function catalogToFieldOptions(
  lists: CatalogList[],
): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const list of lists) {
    out[list.key] = list.items.map((item) => item.label)
  }
  return out
}

export function blankCatalogItem(label = ""): CatalogItem {
  return { label, description: "", bounds: null }
}

export function blankExpertCatalogItem(label = ""): CatalogItem {
  return {
    label,
    description: "",
    bounds: null,
    kompetensomrade: "",
    radgivningsstil: "",
    yrkesbakgrund: "",
    professionell_anekdot: "",
  }
}
