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
  office.context.roamingSettings.set(TOKEN_KEY, token)
  return new Promise((resolve, reject) => {
    office.context.roamingSettings.saveAsync((result) => {
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
    paragraphs.load("items/text,items/style")
    await context.sync()
    return paragraphs.items.map((paragraph, index) => ({
      index,
      text: paragraph.text.replace(/\r/g, "").trimEnd(),
      style: paragraph.style ?? "",
    }))
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
