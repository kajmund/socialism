import { useState } from "react"
import { Check, Clipboard } from "lucide-react"

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
