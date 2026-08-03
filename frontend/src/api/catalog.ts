import { api } from "@/lib/api"

export type CatalogSection =
  | "demografi"
  | "politik"
  | "varderingar"
  | "rost_media"

export type CatalogList = {
  key: string
  section: CatalogSection
  title: string
  items: string[]
  updated_at: string
}

export const SECTION_ORDER: CatalogSection[] = [
  "demografi",
  "politik",
  "varderingar",
  "rost_media",
]

export const SECTION_LABELS: Record<CatalogSection, string> = {
  demografi: "Demografi",
  politik: "Politik",
  varderingar: "Värderingar",
  rost_media: "Röst & media",
}

export function listCatalog(): Promise<CatalogList[]> {
  return api.get<CatalogList[]>("/catalog")
}

export function getCatalogList(key: string): Promise<CatalogList> {
  return api.get<CatalogList>(`/catalog/${key}`)
}

export function updateCatalogList(
  key: string,
  items: string[],
): Promise<CatalogList> {
  return api.put<CatalogList>(`/catalog/${key}`, { items })
}

/** Map catalog rows to field-key → options for persona composer selects. */
export function catalogToFieldOptions(
  lists: CatalogList[],
): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const list of lists) {
    out[list.key] = list.items
  }
  return out
}
