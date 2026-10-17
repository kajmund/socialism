export type MarkAuthorKind = "user" | "expert" | "passage"

export type MarkColor = { fill: string; ring: string; ink: string }

const EXPERT_MARK_COLORS: MarkColor[] = [
  { fill: "rgba(14, 116, 144, 0.38)", ring: "#0e7490", ink: "#0e7490" },
  { fill: "rgba(37, 99, 235, 0.32)", ring: "#1d4ed8", ink: "#1d4ed8" },
  { fill: "rgba(109, 40, 217, 0.30)", ring: "#6d28d9", ink: "#6d28d9" },
  { fill: "rgba(190, 24, 93, 0.28)", ring: "#be185d", ink: "#be185d" },
  { fill: "rgba(22, 101, 52, 0.32)", ring: "#166534", ink: "#166534" },
  { fill: "rgba(194, 65, 12, 0.30)", ring: "#c2410c", ink: "#c2410c" },
]

export const USER_MARK_COLOR: MarkColor = { fill: "rgba(243, 206, 115, 0.72)", ring: "#d9a93c", ink: "#8a6a1f" }
export const PASSAGE_MARK_COLOR: MarkColor = { fill: "rgba(20, 22, 27, 0.14)", ring: "rgba(20, 22, 27, 0.45)", ink: "#3f4450" }

export function markColor(kind: MarkAuthorKind | undefined, authorId: string | null | undefined): MarkColor {
  if (kind === "expert" && authorId) {
    let hash = 0
    for (const char of authorId) hash = (Math.imul(hash, 31) + char.charCodeAt(0)) >>> 0
    return EXPERT_MARK_COLORS[hash % EXPERT_MARK_COLORS.length] ?? EXPERT_MARK_COLORS[0]
  }
  if (kind === "passage") return PASSAGE_MARK_COLOR
  return USER_MARK_COLOR
}

type CommentAuthor = { author_kind: string; author_id: string | null; expert_id?: string | null }

export function commentAuthorColor(comment: CommentAuthor): MarkColor {
  if (comment.author_kind === "expert") return markColor("expert", comment.expert_id)
  return markColor("user", comment.author_id)
}

export function sharedAuthorColor(comments: CommentAuthor[], fallback: MarkColor): MarkColor {
  const first = comments[0]
  if (!first) return fallback
  const key = authorKey(first)
  return comments.every((comment) => authorKey(comment) === key) ? commentAuthorColor(first) : fallback
}

function authorKey(comment: CommentAuthor): string {
  return comment.author_kind === "expert" ? `expert:${comment.expert_id ?? ""}` : `user:${comment.author_id ?? ""}`
}
