import { useLayoutEffect, useRef, useState } from "react"
import { MessageSquare, Send, X } from "lucide-react"
import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { PassageComment } from "@/api/voiceWorkspaces"
import { PASSAGE_MARK_COLOR, commentAuthorColor, markColor, sharedAuthorColor } from "@/components/underlag/documentMarkColor"
import { useLocale } from "@/i18n"
import { stackCommentCards, type CommentThread, type MarkAnchor } from "./documentCommentLayout"

export function DocumentCommentButton({ open, count, onClick }: { open: boolean; count: number; onClick: () => void }) {
  const { t } = useLocale()
  return <button type="button" aria-pressed={open} aria-label={t(open ? "voiceWorkspaceChat.hideComments" : "voiceWorkspaceChat.showComments")} className={`relative grid size-6 shrink-0 place-items-center rounded ${open ? "bg-db-ink-950 text-white" : ""}`} onClick={onClick}><MessageSquare size={15} />{!open && count > 0 ? <span className="absolute right-0.5 top-0.5 size-1.5 rounded-full bg-db-gold-500" /> : null}</button>
}

export function DocumentCommentMargin({ threads, anchors, activeKey, reader, pending, onActivate, onSubmit, onEdit, onDelete }: {
  threads: CommentThread[]
  anchors: MarkAnchor[]
  activeKey: string | null
  reader: { id: string; name: string } | null
  pending: boolean
  onActivate: (key: string) => void
  onSubmit: (anchor: DocumentKnowledgeAnchor, body: string) => Promise<void>
  onEdit: (id: string, body: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}) {
  const { t, intl } = useLocale()
  const railRef = useRef<HTMLDivElement>(null)
  const focusedComposer = useRef<string | null>(null)
  const [heights, setHeights] = useState<Record<string, number>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<string | null>(null)
  const threadKey = threads.map((thread) => `${thread.key}:${thread.comments.length}`).join("|")
  useLayoutEffect(() => {
    const root = railRef.current
    if (!root) return
    const read = () => {
      const next: Record<string, number> = {}
      for (const node of root.querySelectorAll<HTMLElement>("[data-comment-card]")) {
        const key = node.dataset.commentCard
        if (key) next[key] = node.offsetHeight
      }
      setHeights((current) => sameHeights(current, next) ? current : next)
    }
    read()
    const observer = new ResizeObserver(read)
    for (const node of root.querySelectorAll("[data-comment-card]")) observer.observe(node)
    return () => observer.disconnect()
  }, [threadKey, drafts, editing, activeKey])
  const boxes = threads.map((thread, index) => {
    const anchor = anchors.find((row) => row.key === thread.key)
    return { key: thread.key, anchorTop: anchor?.top ?? 12, anchorHeight: anchor?.height ?? 16, height: heights[thread.key] ?? 112, index }
  })
  const placed = new Map(stackCommentCards(boxes).map((row) => [row.key, row.top]))
  const extent = boxes.reduce((max, box) => Math.max(max, (placed.get(box.key) ?? 0) + box.height + 16), 0)
  const time = new Intl.DateTimeFormat(intl, { dateStyle: "medium", timeStyle: "short" })
  useLayoutEffect(() => {
    const root = railRef.current
    if (!root || !activeKey || focusedComposer.current === activeKey || !anchors.some((row) => row.key === activeKey)) return
    const field = [...root.querySelectorAll<HTMLTextAreaElement>("textarea[data-new-comment]")].find((node) => node.dataset.newComment === activeKey)
    if (!field) return
    focusedComposer.current = activeKey
    if (document.activeElement !== field) field.focus({ preventScroll: true })
  }, [activeKey, anchors, threadKey])
  return <div ref={railRef} className="relative min-h-full" data-comment-margin="">
    <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      {boxes.map((box) => {
        const top = placed.get(box.key) ?? box.anchorTop
        const tone = toneOf(threads.find((thread) => thread.key === box.key))
        const from = box.anchorTop + box.anchorHeight / 2
        const to = top + 22
        return <path key={box.key} d={`M 0 ${from} H 12 V ${to} H 18`} fill="none" stroke={tone.ring} strokeWidth="1" />
      })}
    </svg>
    <div style={{ height: extent }} />
    {threads.map((thread) => {
      const tone = toneOf(thread)
      const top = placed.get(thread.key) ?? 12
      const active = thread.key === activeKey
      const draft = drafts[thread.key] ?? ""
      return <article key={thread.key} data-comment-card={thread.key} className="absolute left-3 right-3 rounded-lg bg-white" style={{ top, borderLeft: `4px solid ${tone.ring}`, boxShadow: active ? `0 0 0 1px ${tone.ring}, 0 1px 4px rgba(20,22,27,0.18)` : "0 1px 3px rgba(20,22,27,0.16)" }} onMouseDown={() => onActivate(thread.key)}>
        {thread.comments.length ? thread.comments.map((comment) => <div key={comment.id} className="px-3 pt-2.5" style={tone === PASSAGE_MARK_COLOR ? { borderLeft: `4px solid ${commentAuthorColor(comment).ring}` } : undefined}>
          <header className="flex items-center gap-2">
            <span className="grid size-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white" style={{ backgroundColor: commentAuthorColor(comment).ink }}>{initials(comment.author_name)}</span>
            <strong className="min-w-0 flex-1 truncate text-[13px]">{comment.author_name}</strong>
            <time className="shrink-0 text-[10px] text-muted-foreground" dateTime={comment.created_at}>{time.format(new Date(comment.created_at))}</time>
            {canDeleteComment(comment, reader?.id) ? <button type="button" aria-label={t("voiceWorkspaceChat.deleteComment")} className="grid size-5 place-items-center text-muted-foreground" onClick={() => { void onDelete(comment.id) }}><X size={12} /></button> : null}
          </header>
          {editing === comment.id ? <textarea className="mt-1 w-full resize-none rounded border border-[color:var(--border-hairline)] px-2 py-1 text-[13px] leading-snug outline-none" rows={3} defaultValue={comment.body} aria-label={t("voiceWorkspaceChat.commentPlaceholder")} onBlur={(event) => { const body = event.target.value; setEditing(null); if (body.trim() && body.trim() !== comment.body) void onEdit(comment.id, body) }} /> : <p className="py-1.5 text-[13px] leading-snug" onClick={() => { if (canEditComment(comment, reader?.id)) setEditing(comment.id) }}>{comment.body}</p>}
        </div>) : <header className="flex items-center gap-2 px-3 pt-2.5"><span className="grid size-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white" style={{ backgroundColor: tone.ink }}>{initials(reader?.name ?? "")}</span><strong className="truncate text-[13px]">{reader?.name}</strong></header>}
        <form className="px-3 pb-2.5" onSubmit={(event) => { event.preventDefault(); const body = draft.trim(); if (!body || pending) return; void onSubmit(thread.anchor, body).then(() => setDrafts((current) => ({ ...current, [thread.key]: "" })), () => undefined) }}>
          <textarea className="mt-1 w-full resize-none rounded border border-[color:var(--border-hairline)] px-2 py-1 text-[13px] leading-snug outline-none focus:border-db-ink-950" rows={thread.comments.length ? 2 : 3} placeholder={t(thread.comments.length ? "voiceWorkspaceChat.commentReply" : "voiceWorkspaceChat.commentPlaceholder")} aria-label={t(thread.comments.length ? "voiceWorkspaceChat.commentReply" : "voiceWorkspaceChat.commentPlaceholder")} value={draft} data-new-comment={thread.comments.length ? undefined : thread.key} onChange={(event) => setDrafts((current) => ({ ...current, [thread.key]: event.target.value }))} onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) event.currentTarget.form?.requestSubmit() }} />
          {draft.trim() ? <div className="mt-1 flex justify-end"><button type="submit" className="flex items-center gap-1 rounded bg-db-ink-950 px-2 py-1 text-[11px] text-white" disabled={pending}><Send size={12} />{t(thread.comments.length ? "voiceWorkspaceChat.commentReply" : "voiceWorkspaceChat.commentSend")}</button></div> : null}
        </form>
      </article>
    })}
  </div>
}

function canEditComment(comment: PassageComment, readerId: string | undefined): boolean {
  return comment.author_kind !== "expert" && comment.author_id != null && comment.author_id === readerId
}

function canDeleteComment(comment: PassageComment, readerId: string | undefined): boolean {
  if (!readerId) return false
  if (comment.author_kind === "expert") return true
  return comment.author_id === readerId
}

function toneOf(thread: CommentThread | undefined) {
  const markTone = markColor(thread?.mark?.authorKind, thread?.mark?.authorId)
  if (!thread?.comments.length) return markTone
  return sharedAuthorColor(thread.comments, PASSAGE_MARK_COLOR)
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return parts.slice(0, 2).map((part) => part[0] ?? "").join("").toUpperCase() || "?"
}

function sameHeights(left: Record<string, number>, right: Record<string, number>): boolean {
  const keys = Object.keys(left)
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key])
}
