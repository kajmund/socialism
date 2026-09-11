import { sha256Hex } from "@/lib/word/sha256"

export type WordAnchor = {
  paragraph_index: number
  unique_local_id?: string | null
  reviewed_text: string
  text_hash: string
  previous_text_hash?: string | null
  next_text_hash?: string | null
}

export type WordDocumentParagraphState = {
  paragraph_index: number
  text: string
  unique_local_id?: string | null
}

export type WordAnchorStatus = "resolved" | "stale" | "ambiguous" | "missing"

export type WordAnchorResolution =
  | { status: "resolved"; paragraph_index: number }
  | { status: "stale" | "ambiguous" | "missing"; paragraph_index?: null }

export function normalizeWordText(text: string): string {
  return text.replace(/\r/g, "").trim()
}

export function hashWordText(text: string): string {
  return sha256Hex(normalizeWordText(text))
}

function optionalId(value: string | null | undefined): string | null {
  if (value == null) return null
  const text = value.trim()
  return text || null
}

function neighborHashes(
  current: readonly WordDocumentParagraphState[],
  position: number,
): { previous: string | null; next: string | null } {
  return {
    previous: position > 0 ? hashWordText(current[position - 1].text) : null,
    next:
      position + 1 < current.length ? hashWordText(current[position + 1].text) : null,
  }
}

function contextMatches(
  anchor: WordAnchor,
  previous: string | null,
  next: string | null,
): boolean {
  const hasPrevious = anchor.previous_text_hash != null
  const hasNext = anchor.next_text_hash != null
  if (!hasPrevious && !hasNext) return false
  const previousOk = !hasPrevious || previous === anchor.previous_text_hash
  const nextOk = !hasNext || next === anchor.next_text_hash
  return previousOk && nextOk
}

export function resolveWordAnchor(
  anchor: WordAnchor,
  current: readonly WordDocumentParagraphState[],
): WordAnchorResolution {
  const reviewed = normalizeWordText(anchor.reviewed_text)
  if (!reviewed) return { status: "missing" }

  const localId = optionalId(anchor.unique_local_id)
  if (localId) {
    const hit = current.find((paragraph) => optionalId(paragraph.unique_local_id) === localId)
    if (hit) {
      if (normalizeWordText(hit.text) === reviewed) {
        return { status: "resolved", paragraph_index: hit.paragraph_index }
      }
      return { status: "stale" }
    }
  }

  const atIndex = current.find(
    (paragraph) => paragraph.paragraph_index === anchor.paragraph_index,
  )
  if (atIndex && normalizeWordText(atIndex.text) === reviewed) {
    return { status: "resolved", paragraph_index: atIndex.paragraph_index }
  }

  const matches = current
    .map((paragraph, position) => ({ paragraph, position }))
    .filter(({ paragraph }) => normalizeWordText(paragraph.text) === reviewed)
  if (matches.length === 1) {
    return { status: "resolved", paragraph_index: matches[0].paragraph.paragraph_index }
  }
  if (matches.length > 1) {
    const disambiguated = matches.filter(({ position }) => {
      const neighbors = neighborHashes(current, position)
      return contextMatches(anchor, neighbors.previous, neighbors.next)
    })
    if (disambiguated.length === 1) {
      return {
        status: "resolved",
        paragraph_index: disambiguated[0].paragraph.paragraph_index,
      }
    }
    return { status: "ambiguous" }
  }

  return { status: "missing" }
}
