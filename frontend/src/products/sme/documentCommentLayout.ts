import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { PassageComment } from "@/api/voiceWorkspaces"
import type { DocumentMark } from "./workspaceDocumentFocus"

export type CommentGuard = { saved: Set<string>; removed: Set<string> }
export type MarkAnchor = { key: string; top: number; height: number }
export type CommentThread = {
  key: string
  anchor: DocumentKnowledgeAnchor
  mark: DocumentMark | null
  comments: PassageComment[]
}

export function marksForComments(marks: DocumentMark[], comments: PassageComment[], sourceId: string): DocumentMark[] {
  const seen = new Set(marks.map((mark) => mark.passageKey))
  const extra: DocumentMark[] = []
  for (const comment of comments) {
    if (comment.source_id !== sourceId || seen.has(comment.passage_key)) continue
    seen.add(comment.passage_key)
    const expert = comment.author_kind === "expert"
    extra.push({
      anchor: comment.anchor,
      authorKind: expert ? "expert" : "user",
      authorId: expert ? comment.expert_id ?? null : comment.author_id,
      authorName: comment.author_name,
      passageKey: comment.passage_key,
    })
  }
  return extra.length ? [...marks, ...extra] : marks
}

export function commentThreads(marks: DocumentMark[], comments: PassageComment[], sourceId: string): CommentThread[] {
  const grouped = new Map<string, PassageComment[]>()
  for (const comment of comments) {
    if (comment.source_id !== sourceId) continue
    const rows = grouped.get(comment.passage_key) ?? []
    rows.push(comment)
    grouped.set(comment.passage_key, rows)
  }
  const threads: CommentThread[] = []
  const seen = new Set<string>()
  for (const mark of marks) {
    if (seen.has(mark.passageKey)) continue
    seen.add(mark.passageKey)
    threads.push({ key: mark.passageKey, anchor: mark.anchor, mark, comments: grouped.get(mark.passageKey) ?? [] })
  }
  for (const [key, rows] of grouped) {
    const first = rows[0]
    if (!first || seen.has(key)) continue
    threads.push({ key, anchor: first.anchor, mark: null, comments: rows })
  }
  return threads
}

export function shownCommentThreads(threads: CommentThread[], activeKey: string | null): CommentThread[] {
  return threads.filter((thread) => thread.comments.length > 0 || thread.key === activeKey)
}

export function stackCommentCards(cards: { key: string; anchorTop: number; height: number }[], gap = 10, padding = 12): { key: string; top: number }[] {
  const ordered = [...cards].sort((left, right) => left.anchorTop - right.anchorTop || left.key.localeCompare(right.key))
  let next = padding
  return ordered.map((card) => {
    const top = Math.max(padding, card.anchorTop, next)
    next = top + card.height + gap
    return { key: card.key, top }
  })
}

export function mergePassageComments(server: PassageComment[] | undefined, local: PassageComment[] | undefined, guard: CommentGuard): PassageComment[] {
  const localRows = local ?? []
  const localById = new Map(localRows.map((row) => [row.id, row]))
  const merged = (server ?? []).filter((row) => !guard.removed.has(row.id)).map((row) => {
    const ours = localById.get(row.id)
    return ours && ours.updated_at > row.updated_at ? ours : row
  })
  const seen = new Set(merged.map((row) => row.id))
  for (const row of localRows) {
    if (!seen.has(row.id) && guard.saved.has(row.id) && !guard.removed.has(row.id)) merged.push(row)
  }
  return merged
}
