import type { WordParagraph } from "@/lib/types"

const DOC_ID_KEY = "socialism_doc_id"
const TOKEN_KEY = "access_token"

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

export function getRoamingToken(): string {
  if (typeof Office === "undefined") return ""
  const value = Office.context.roamingSettings.get(TOKEN_KEY)
  return typeof value === "string" ? value : ""
}

export function saveRoamingToken(token: string): Promise<void> {
  const office = requireOffice()
  const settings = office.context.roamingSettings
  if (!settings) {
    throw new Error("Office roamingSettings is not available")
  }
  settings.set(TOKEN_KEY, token)
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error("Timed out saving token to Word"))
    }, 5000)
    settings.saveAsync((result) => {
      window.clearTimeout(timer)
      if (result.status === Office.AsyncResultStatus.Failed) {
        reject(new Error(result.error.message))
        return
      }
      resolve()
    })
  })
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
    paragraphs.load("items/text,items/style,items/listItemOrNullObject/listString")
    await context.sync()
    return paragraphs.items.map((paragraph, index) => ({
      index,
      text: paragraph.text.replace(/\r/g, "").trimEnd(),
      style: paragraph.style ?? "",
      list_string: listStringFromLoaded(paragraph),
    }))
  })
}

export function normalizeParagraphText(text: string): string {
  return text.replace(/\r/g, "").trim()
}

export function paragraphTextMatchesReviewed(
  current: string,
  reviewed: string | null | undefined,
): boolean {
  if (reviewed == null || !reviewed.trim()) return false
  return normalizeParagraphText(current) === normalizeParagraphText(reviewed)
}

export function findRewriteTargetIndex(
  paragraphTexts: readonly string[],
  requestedIndex: number,
  reviewedText: string | null | undefined,
): number | null {
  if (reviewedText == null || !reviewedText.trim()) return null
  const requested = paragraphTexts[requestedIndex]
  if (
    requested != null &&
    paragraphTextMatchesReviewed(requested, reviewedText)
  ) {
    return requestedIndex
  }
  const matches: number[] = []
  for (let index = 0; index < paragraphTexts.length; index += 1) {
    if (paragraphTextMatchesReviewed(paragraphTexts[index], reviewedText)) {
      matches.push(index)
    }
  }
  return matches.length === 1 ? matches[0] : null
}

function changeTrackingSupported(): boolean {
  return typeof Word !== "undefined" && typeof Word.ChangeTrackingMode !== "undefined"
}

export async function applyRewriteSuggestion(args: {
  paragraphIndex: number
  foreslagenText: string
  motivering: string
  reviewedText: string | null | undefined
  fallbackComment: string
}): Promise<string | null> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  return Word.run(async (context) => {
    const paragraphs = context.document.body.paragraphs
    paragraphs.load("items/text")
    const canTrack = changeTrackingSupported()
    if (canTrack) {
      context.document.load("changeTrackingMode")
    }
    await context.sync()

    const targetIndex = findRewriteTargetIndex(
      paragraphs.items.map((item) => item.text),
      args.paragraphIndex,
      args.reviewedText,
    )
    if (targetIndex == null) {
      return null
    }
    const paragraph = paragraphs.items[targetIndex]
    if (!canTrack) {
      const comment = paragraph.getRange().insertComment(args.fallbackComment)
      comment.load("id")
      await context.sync()
      return comment.id
    }

    const previousMode = context.document.changeTrackingMode
    try {
      context.document.changeTrackingMode = Word.ChangeTrackingMode.trackAll
      paragraph.insertText(args.foreslagenText, Word.InsertLocation.replace)
      await context.sync()
      const comment = paragraph.getRange().insertComment(args.motivering)
      comment.load("id")
      await context.sync()
      return comment.id
    } finally {
      context.document.changeTrackingMode = previousMode
      await context.sync()
    }
  })
}

export async function insertCommentAt(
  paragraphIndex: number,
  text: string,
): Promise<string> {
  if (typeof Word === "undefined") {
    throw new Error("Word API is not available")
  }
  return Word.run(async (context) => {
    const paragraphs = context.document.body.paragraphs
    paragraphs.load("items")
    await context.sync()
    const paragraph = paragraphs.items[paragraphIndex]
    if (!paragraph) {
      throw new Error(`Paragraph ${paragraphIndex} not found`)
    }
    const comment = paragraph.getRange().insertComment(text)
    comment.load("id")
    await context.sync()
    return comment.id
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
