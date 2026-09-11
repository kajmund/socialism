import type { WordAnchor, WordParagraph } from "@/lib/types"
import {
  resolveWordAnchor,
  type WordDocumentParagraphState,
} from "@/lib/word/anchors"

const DOC_ID_KEY = "socialism_doc_id"

function requireOffice(): typeof Office {
  if (typeof Office === "undefined") {
    throw new Error("Office.js is not available")
  }
  return Office
}

export function officeReady(): Promise<void> {
  if (typeof Office === "undefined") {
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    Office.onReady(() => resolve())
  })
}

export function listStringFromLoaded(paragraph: {
  listItemOrNullObject: { isNullObject: boolean; listString?: string }
}): string {
  const item = paragraph.listItemOrNullObject
  if (item.isNullObject) return ""
  return typeof item.listString === "string" ? item.listString : ""
}

export function commentsApiSupported(): boolean {
  if (typeof Office === "undefined") return false
  return Office.context.requirements.isSetSupported("WordApi", "1.4")
}

export function uniqueLocalIdSupported(): boolean {
  if (typeof Office === "undefined") return false
  return Office.context.requirements.isSetSupported("WordApi", "1.6")
}

function uniqueLocalIdFromLoaded(paragraph: { uniqueLocalId?: number | string }): string | null {
  const value = paragraph.uniqueLocalId
  if (typeof value === "number" && Number.isFinite(value)) return String(value)
  if (typeof value === "string" && value.trim()) return value.trim()
  return null
}

export function getStoredDocId(): string {
  if (typeof Office === "undefined") return ""
  const value = Office.context.document.settings.get(DOC_ID_KEY)
  return typeof value === "string" ? value : ""
}

export function saveDocId(docId: string): Promise<void> {
  const office = requireOffice()
  office.context.document.settings.set(DOC_ID_KEY, docId)
  return new Promise((resolve, reject) => {
    office.context.document.settings.saveAsync((result) => {
      if (result.status === Office.AsyncResultStatus.Failed) {
        reject(new Error(result.error.message))
        return
      }
      resolve()
    })
  })
}

export async function getOrCreateDocId(): Promise<string> {
  const existing = getStoredDocId().trim()
  if (existing) return existing
  const created = crypto.randomUUID()
  await saveDocId(created)
  return created
}

export async function readDocumentParagraphs(): Promise<WordParagraph[]> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  return Word.run(async (context) => {
    const paragraphs = context.document.body.paragraphs
    const loadUniqueId = uniqueLocalIdSupported()
    paragraphs.load(
      loadUniqueId
        ? "items/text,items/style,items/listItemOrNullObject/listString,items/uniqueLocalId"
        : "items/text,items/style,items/listItemOrNullObject/listString",
    )
    await context.sync()
    return paragraphs.items.map((paragraph, index) => ({
      index,
      text: paragraph.text.replace(/\r/g, "").trimEnd(),
      style: paragraph.style ?? "",
      list_string: listStringFromLoaded(paragraph),
      unique_local_id: loadUniqueId ? uniqueLocalIdFromLoaded(paragraph) : null,
    }))
  })
}

export function paragraphStatesFromSnapshot(
  paragraphs: readonly WordParagraph[],
): WordDocumentParagraphState[] {
  return paragraphs.map((paragraph) => ({
    paragraph_index: paragraph.index,
    text: paragraph.text,
    unique_local_id: paragraph.unique_local_id ?? null,
  }))
}

async function loadDocumentParagraphs(
  context: Word.RequestContext,
): Promise<{
  items: Word.Paragraph[]
  states: WordDocumentParagraphState[]
}> {
  const paragraphs = context.document.body.paragraphs
  const loadUniqueId = uniqueLocalIdSupported()
  paragraphs.load(loadUniqueId ? "items/text,items/uniqueLocalId" : "items/text")
  await context.sync()
  return {
    items: paragraphs.items,
    states: paragraphs.items.map((paragraph, index) => ({
      paragraph_index: index,
      text: paragraph.text,
      unique_local_id: loadUniqueId ? uniqueLocalIdFromLoaded(paragraph) : null,
    })),
  }
}

export type WordMutationOutcome =
  | { status: "resolved"; commentId: string }
  | { status: "stale" | "ambiguous" | "missing"; commentId?: null }

function changeTrackingSupported(): boolean {
  return typeof Word !== "undefined" && typeof Word.ChangeTrackingMode !== "undefined"
}

export async function applyRewriteSuggestion(args: {
  anchor: WordAnchor
  foreslagenText: string
  motivering: string
  fallbackComment: string
}): Promise<WordMutationOutcome> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  return Word.run(async (context) => {
    const canTrack = changeTrackingSupported()
    if (canTrack) {
      context.document.load("changeTrackingMode")
    }
    const loaded = await loadDocumentParagraphs(context)
    const resolution = resolveWordAnchor(args.anchor, loaded.states)
    if (resolution.status !== "resolved") {
      return { status: resolution.status }
    }
    const paragraph = loaded.items[resolution.paragraph_index]
    if (!paragraph) {
      return { status: "missing" }
    }
    if (!canTrack) {
      const comment = paragraph.getRange().insertComment(args.fallbackComment)
      comment.load("id")
      await context.sync()
      return { status: "resolved", commentId: comment.id }
    }

    const previousMode = context.document.changeTrackingMode
    try {
      context.document.changeTrackingMode = Word.ChangeTrackingMode.trackAll
      paragraph.insertText(args.foreslagenText, Word.InsertLocation.replace)
      await context.sync()
      const comment = paragraph.getRange().insertComment(args.motivering)
      comment.load("id")
      await context.sync()
      return { status: "resolved", commentId: comment.id }
    } finally {
      context.document.changeTrackingMode = previousMode
      await context.sync()
    }
  })
}

export async function insertCommentForAnchor(
  anchor: WordAnchor,
  text: string,
): Promise<WordMutationOutcome> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  return Word.run(async (context) => {
    const loaded = await loadDocumentParagraphs(context)
    const resolution = resolveWordAnchor(anchor, loaded.states)
    if (resolution.status !== "resolved") {
      return { status: resolution.status }
    }
    const paragraph = loaded.items[resolution.paragraph_index]
    if (!paragraph) {
      return { status: "missing" }
    }
    const comment = paragraph.getRange().insertComment(text)
    comment.load("id")
    await context.sync()
    return { status: "resolved", commentId: comment.id }
  })
}

export async function resolveComment(commentId: string): Promise<void> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  await Word.run(async (context) => {
    const comments = context.document.body.getComments()
    comments.load("items/id")
    await context.sync()
    const match = comments.items.find((item) => item.id === commentId)
    if (!match) return
    match.resolved = true
    await context.sync()
  })
}
