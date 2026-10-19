import { useState } from "react"
import { Check, Clipboard } from "lucide-react"
import type { PostRow } from "@/components/runs/activityFeed"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

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
  t: Translate,
  opts: {
    isQuote: boolean
    isRepost: boolean
    quote: string
    originalAuthor: string | null
    originalId: number | null
  },
): string {
  if (opts.isQuote) {
    const cite = opts.originalAuthor ?? t("runs.feed.unknown")
    const id = opts.originalId ?? "?"
    return `${opts.quote}\n\n(${t("runs.feed.quotePrefix", { author: cite, postId: id })})`
  }
  if (opts.isRepost) {
    const cite = opts.originalAuthor ?? t("runs.feed.unknown")
    const id = opts.originalId ?? "?"
    return t("runs.feed.repostPrefix", { author: cite, postId: id })
  }
  return post.content.trim()
}

export function CopyFeedTextButton({
  text,
  label,
}: {
  text: string
  label: string
}) {
  const { t } = useLocale()
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
      title={copied ? t("runs.feed.copied") : label}
      aria-label={copied ? t("runs.feed.copied") : label}
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
