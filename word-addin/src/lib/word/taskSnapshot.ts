import {
  uniqueLocalIdFromLoaded,
  uniqueLocalIdSupported,
  wordParagraphFromLoaded,
} from "@/lib/office"
import type { WordParagraph, WordTaskScope, WordTaskScopeType } from "@/lib/types"

export class EmptyWordSelectionError extends Error {
  override name = "EmptyWordSelectionError"
  constructor() {
    super("empty_selection")
  }
}

export class UnresolvedWordSelectionError extends Error {
  override name = "UnresolvedWordSelectionError"
  constructor() {
    super("unresolved_selection")
  }
}

export type WordTaskSnapshot = {
  paragraphs: WordParagraph[]
  scope: WordTaskScope
}

function uniqueSorted(indexes: number[]): number[] {
  return [...new Set(indexes)].sort((left, right) => left - right)
}

export function mapSelectionByUniqueLocalId(
  bodyIds: Array<string | null>,
  selectedIds: Array<string | null>,
): number[] | null {
  if (selectedIds.length === 0) return null
  if (selectedIds.some((id) => !id) || bodyIds.some((id) => !id)) return null
  const counts = new Map<string, number>()
  for (const id of bodyIds) {
    counts.set(id as string, (counts.get(id as string) ?? 0) + 1)
  }
  if ([...counts.values()].some((count) => count > 1)) return null
  const indexById = new Map(bodyIds.map((id, index) => [id as string, index]))
  const indexes: number[] = []
  for (const id of selectedIds) {
    const index = indexById.get(id as string)
    if (index == null) return null
    indexes.push(index)
  }
  return uniqueSorted(indexes)
}

export function mapSelectionByEqualRanges(equalBodyIndexes: number[][]): number[] | null {
  if (equalBodyIndexes.length === 0) return null
  const indexes: number[] = []
  for (const matches of equalBodyIndexes) {
    if (matches.length !== 1) return null
    indexes.push(matches[0])
  }
  return uniqueSorted(indexes)
}

export async function captureWordTaskSnapshot(
  scopeType: WordTaskScopeType,
): Promise<WordTaskSnapshot> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  return Word.run(async (context) => {
    const loadUniqueId = uniqueLocalIdSupported()
    const bodyLoad = loadUniqueId
      ? "items/text,items/style,items/listItemOrNullObject/listString,items/uniqueLocalId"
      : "items/text,items/style,items/listItemOrNullObject/listString"
    const bodyParagraphs = context.document.body.paragraphs
    bodyParagraphs.load(bodyLoad)

    const selection = context.document.getSelection()
    selection.load("isEmpty")
    const selectedParagraphs = selection.paragraphs
    selectedParagraphs.load(
      loadUniqueId ? "items/uniqueLocalId,items/text" : "items/text",
    )
    await context.sync()

    const paragraphs = bodyParagraphs.items.map((paragraph, index) =>
      wordParagraphFromLoaded(paragraph, index, loadUniqueId),
    )

    if (scopeType === "document") {
      return { paragraphs, scope: { type: "document" } }
    }

    if (selection.isEmpty || selectedParagraphs.items.length === 0) {
      throw new EmptyWordSelectionError()
    }

    const byLocalId = mapSelectionByUniqueLocalId(
      paragraphs.map((paragraph) => paragraph.unique_local_id ?? null),
      selectedParagraphs.items.map((paragraph) =>
        loadUniqueId ? uniqueLocalIdFromLoaded(paragraph) : null,
      ),
    )
    let indexes = byLocalId
    if (indexes == null) {
      const comparisons = selectedParagraphs.items.map((selected) =>
        bodyParagraphs.items.map((body) =>
          selected.getRange().compareLocationWith(body.getRange()),
        ),
      )
      await context.sync()
      const equalIndexes = comparisons.map((row) =>
        row.flatMap((result, bodyIndex) =>
          result.value === Word.LocationRelation.equal ? [bodyIndex] : [],
        ),
      )
      indexes = mapSelectionByEqualRanges(equalIndexes)
    }
    if (indexes == null) {
      throw new UnresolvedWordSelectionError()
    }
    return {
      paragraphs,
      scope: { type: "selection", paragraph_indexes: indexes },
    }
  })
}
