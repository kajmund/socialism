import type { EvidenceSetItem } from "@/api/execution"

export type EvidenceRefTarget = {
  item_id?: unknown
  original_evidence_id?: unknown
  ordinal?: unknown
}

const REF_PATTERN = /^E(\d+)$/

export function evidenceItemDomId(itemId: string): string {
  return `execution-evidence-${itemId}`
}

export function parseEvidenceRef(raw: string): number | null {
  const match = REF_PATTERN.exec(raw.trim())
  if (match == null) return null
  const index = Number(match[1])
  if (!Number.isInteger(index) || index < 1) return null
  return index
}

export function citationForFoundItem(
  items: readonly EvidenceSetItem[],
  itemId: string,
): string | null {
  let foundIndex = 0
  const ordered = [...items].sort((a, b) => a.ordinal - b.ordinal || a.id.localeCompare(b.id))
  for (const item of ordered) {
    if (item.status !== "found") continue
    foundIndex += 1
    if (item.id === itemId) return `E${foundIndex}`
  }
  return null
}

export function foundItemsInOrdinalOrder(items: readonly EvidenceSetItem[]): EvidenceSetItem[] {
  return [...items]
    .filter((item) => item.status === "found")
    .sort((a, b) => a.ordinal - b.ordinal || a.id.localeCompare(b.id))
}

export function itemIdFromEvidenceRefs(
  ref: string,
  evidenceRefs: Record<string, unknown> | null | undefined,
): string | null {
  if (evidenceRefs == null) return null
  const raw = evidenceRefs[ref]
  if (raw == null || typeof raw !== "object") return null
  const itemId = (raw as EvidenceRefTarget).item_id
  return typeof itemId === "string" && itemId.length > 0 ? itemId : null
}

export function resolveEvidenceRef(
  ref: string,
  items: readonly EvidenceSetItem[],
  evidenceRefs?: Record<string, unknown> | null,
): EvidenceSetItem | null {
  const mappedId = itemIdFromEvidenceRefs(ref, evidenceRefs)
  if (mappedId != null) {
    return items.find((item) => item.id === mappedId) ?? null
  }
  const index = parseEvidenceRef(ref)
  if (index == null) return null
  return foundItemsInOrdinalOrder(items)[index - 1] ?? null
}

export function scrollToEvidenceItem(itemId: string): void {
  const node = document.getElementById(evidenceItemDomId(itemId))
  if (node == null) return
  node.scrollIntoView({ behavior: "smooth", block: "center" })
}
