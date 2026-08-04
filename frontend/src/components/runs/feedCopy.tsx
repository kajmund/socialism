import { useState } from "react"
import { Check, Clipboard } from "lucide-react"
import {
  buildTimelineItems,
  groupTimelineSegments,
  type PostRow,
} from "@/components/runs/activityFeed"
import type {
  OasisAttemptResult,
  OasisVariantResult,
  QualityWarnings,
} from "@/data/runs-types"

export function formatCommentForClipboard(
  author: string,
  content: string,
): string {
  return `${author}\n${content.trim()}`
}

export function formatPostForClipboard(
  author: string,
  body: string,
  comments: Array<{ author: string; content: string }>,
): string {
  const parts = [`${author}`, body.trim()]
  if (comments.length > 0) {
    parts.push("")
    for (const comment of comments) {
      parts.push(comment.author, comment.content.trim(), "")
    }
  }
  return parts.join("\n").trimEnd()
}

export function postBodyTextForCopy(
  post: PostRow,
  opts: {
    isQuote: boolean
    isRepost: boolean
    quote: string
    originalAuthor: string | null
    originalId: number | null
  },
): string {
  if (opts.isQuote) {
    const cite = opts.originalAuthor ?? "okänd"
    const id = opts.originalId ?? "?"
    return `${opts.quote}\n\n(Citerar ${cite} #${id})`
  }
  if (opts.isRepost) {
    const cite = opts.originalAuthor ?? "okänd"
    const id = opts.originalId ?? "?"
    return `Delade inlägg från ${cite} #${id}`
  }
  return post.content.trim()
}

function agentLabel(
  agents: NonNullable<OasisVariantResult["agents"]>,
  userId: number,
): string {
  return agents.find((a) => a.index === userId)?.member_name ?? `agent ${userId}`
}

function formatQualityWarnings(data: QualityWarnings): string[] {
  const warnings = data.warnings ?? []
  if (warnings.length === 0) return []
  const thresholdPct = Math.round(data.threshold * 100)
  const lines = [
    `Lexikal konvergens (≥${thresholdPct}%, ${data.population_agents} agenter):`,
  ]
  for (const w of warnings) {
    const kind =
      w.kind === "source_phrase_echo" ? "eko av injektion" : "gemensam fras"
    const source = w.source ? ` (${w.source})` : ""
    lines.push(
      `- «${w.phrase}» — ${w.agent_count}/${data.population_agents} (${Math.round(w.agent_share * 100)}%) · ${kind}${source}`,
    )
  }
  return lines
}

function formatVariantForClipboard(variant: OasisVariantResult): string {
  if (variant.error) return variant.error

  const lines: string[] = []
  const posts = variant.posts ?? []
  const comments = variant.comments ?? []
  const agents = variant.agents ?? []
  const commentsByPostId = new Map<number, typeof comments>()
  for (const comment of comments) {
    const bucket = commentsByPostId.get(comment.post_id)
    if (bucket) bucket.push(comment)
    else commentsByPostId.set(comment.post_id, [comment])
  }
  const postsById = new Map(posts.map((p) => [p.post_id, p]))

  if (variant.quality_warnings) {
    lines.push(...formatQualityWarnings(variant.quality_warnings), "")
  }

  const platform =
    variant.platform ?? variant.oasis_options?.platform ?? "twitter"
  lines.push(`Plattform: ${platform === "reddit" ? "Reddit" : "Twitter"}`, "")

  const timeline = buildTimelineItems(variant, {
    hideNoise: false,
    agentName: (userId) => agentLabel(agents, userId),
  })
  const segments = groupTimelineSegments(timeline)

  if (posts.length === 0 && segments.every((s) => s.kind !== "actions")) {
    lines.push("Inga inlägg sparades.")
    return lines.join("\n").trimEnd()
  }

  lines.push("Flöde:", "")

  for (const segment of segments) {
    if (segment.kind === "tick") {
      const tick = segment.tick
      const label = tick.silent ? "tyst" : "tick"
      lines.push(`--- Dag ${tick.day} (${label}, ${tick.rounds} ronder) ---`, "")
      continue
    }
    if (segment.kind === "actions") {
      for (const action of segment.actions) {
        const detail = action.detail ? `: ${action.detail}` : ""
        lines.push(
          `[${action.label}] ${agentLabel(agents, action.userId)}${detail}`,
        )
      }
      lines.push("")
      continue
    }

    const post = segment.post
    const author = agentLabel(agents, post.user_id)
    const originalId = post.original_post_id ?? null
    const original =
      originalId != null ? postsById.get(originalId) : undefined
    const originalAuthor =
      original != null ? agentLabel(agents, original.user_id) : null
    const quote = (post.quote_content ?? "").trim()
    const isQuote = originalId != null && quote.length > 0
    const isRepost = originalId != null && quote.length === 0
    const postComments = commentsByPostId.get(post.post_id) ?? []
    const body = postBodyTextForCopy(post, {
      isQuote,
      isRepost,
      quote,
      originalAuthor,
      originalId,
    })

    lines.push(
      formatPostForClipboard(
        author,
        body,
        postComments.map((c) => ({
          author: agentLabel(agents, c.user_id),
          content: c.content,
        })),
      ),
      "",
    )
  }

  return lines.join("\n").trimEnd()
}

export function formatAttemptForClipboard(attempt: OasisAttemptResult): string {
  const lines: string[] = []
  if (attempt.finished_at) lines.push(`Körning: ${attempt.finished_at}`)
  if (attempt.engine) lines.push(`Motor: ${attempt.engine}`)
  if (attempt.error) lines.push(`Fel: ${attempt.error}`)
  lines.push("")

  const variants = attempt.variants ?? []
  variants.forEach((variant, index) => {
    if (index > 0) lines.push("")
    lines.push(`=== ${variant.label} (${variant.id}) ===`, "")
    lines.push(formatVariantForClipboard(variant))
  })

  return lines.join("\n").trimEnd()
}

export function CopyFeedTextButton({
  text,
  label,
}: {
  text: string
  label: string
}) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard blocked — ignore silently.
    }
  }

  return (
    <button
      type="button"
      className="shrink-0 rounded p-1 text-muted-foreground/40 transition-colors hover:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
      title={copied ? "Kopierat" : label}
      aria-label={copied ? "Kopierat" : label}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        void handleCopy()
      }}
    >
      {copied ? (
        <Check className="size-3.5" aria-hidden />
      ) : (
        <Clipboard className="size-3.5" aria-hidden />
      )}
    </button>
  )
}

export function CopyAttemptButton({
  attempt,
  disabled = false,
}: {
  attempt: OasisAttemptResult
  disabled?: boolean
}) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(formatAttemptForClipboard(attempt))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard blocked — ignore silently.
    }
  }

  return (
    <button
      type="button"
      className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
      disabled={disabled}
      title={copied ? "Kopierat" : "Kopiera hela resultatet"}
      aria-label={copied ? "Kopierat" : "Kopiera hela resultatet"}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        void handleCopy()
      }}
    >
      {copied ? "Kopierat" : "Kopiera"}
    </button>
  )
}
