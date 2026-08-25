import { useEffect, useRef, useState } from "react"
import {
  buildMentionAliases,
  CommentBody,
  getMentionMatcher,
} from "@/components/runs/commentMentions"
import { personaInitials } from "@/data/library"
import type { OasisVariantResult } from "@/data/runs-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

export type FeedAgent = {
  index: number
  member_name: string
  persona_id?: string | null
  role?: string | null
}

export type FeedPost = NonNullable<OasisVariantResult["posts"]>[number]
export type FeedComment = NonNullable<OasisVariantResult["comments"]>[number]

export function agentLabel(
  agents: FeedAgent[],
  userId: number,
  t: Translate,
): string {
  return (
    agents.find((agent) => agent.index === userId)?.member_name ??
    t("runs.feed.agentFallback", { userId })
  )
}

export function agentIsInjector(agents: FeedAgent[], userId: number): boolean {
  return agents.find((agent) => agent.index === userId)?.role === "injector"
}

export function AgentAvatar({
  name,
  size = "sm",
}: {
  name: string
  size?: "xs" | "sm" | "md"
}) {
  let box = "h-8 w-8 text-[10px]"
  if (size === "xs") box = "h-5 w-5 text-[9px]"
  else if (size === "md") box = "h-10 w-10 text-[12px]"
  return (
    <span
      aria-hidden
      className={
        "inline-grid shrink-0 place-items-center rounded-full bg-db-ink-950 font-semibold uppercase leading-none text-white " +
        box
      }
    >
      {personaInitials(name)}
    </span>
  )
}

export function AgentNameButton({
  name,
  onOpen,
  className,
  size = "xs",
  showAvatar = true,
}: {
  name: string
  onOpen: () => void
  className?: string
  size?: "xs" | "sm" | "md"
  showAvatar?: boolean
}) {
  return (
    <button
      type="button"
      className={
        "inline-flex items-center gap-1.5 font-medium text-foreground underline-offset-2 hover:underline " +
        (className ?? "")
      }
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onOpen()
      }}
    >
      {showAvatar ? <AgentAvatar name={name} size={size} /> : null}
      <span>{name}</span>
    </button>
  )
}

function ActorList({
  agents,
  userIds,
  emptyLabel,
  onOpenAgent,
}: {
  agents: FeedAgent[]
  userIds: number[]
  emptyLabel: string
  onOpenAgent: (userId: number) => void
}) {
  const { t } = useLocale()
  if (userIds.length === 0) {
    return <p className="px-1 py-0.5 text-xs text-muted-foreground">{emptyLabel}</p>
  }
  return (
    <ul className="max-h-40 overflow-auto py-0.5">
      {userIds.map((id) => (
        <li key={id} className="rounded px-2 py-0.5 text-xs hover:bg-muted/60">
          <AgentNameButton
            name={agentLabel(agents, id, t)}
            className="w-full px-0 py-1 text-left text-xs"
            showAvatar={!agentIsInjector(agents, id)}
            onOpen={() => onOpenAgent(id)}
          />
        </li>
      ))}
    </ul>
  )
}

export function LikeShareBar({
  agents,
  likedBy,
  dislikedBy,
  sharedBy,
  compact = false,
  onOpenAgent,
}: {
  agents: FeedAgent[]
  likedBy?: number[]
  dislikedBy?: number[]
  sharedBy?: Array<{
    user_id: number
    kind: "repost" | "quote"
    share_post_id?: number
  }>
  compact?: boolean
  onOpenAgent: (userId: number) => void
}) {
  const { t } = useLocale()
  const likes = likedBy ?? []
  const dislikes = dislikedBy ?? []
  const shares = sharedBy ?? []
  const [open, setOpen] = useState<"like" | "dislike" | "share" | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  function toggle(kind: "like" | "dislike" | "share") {
    setOpen((prev) => (prev === kind ? null : kind))
  }

  useEffect(() => {
    if (open == null) return
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(null)
      }
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [open])

  function openAgentAndClose(userId: number) {
    setOpen(null)
    onOpenAgent(userId)
  }

  return (
    <div
      ref={rootRef}
      className={
        "relative " + (compact ? "mt-1" : "mt-2 border-t border-border/60 pt-2")
      }
    >
      <div className="flex items-center gap-1">
        <div className="relative">
          <button
            type="button"
            disabled={likes.length === 0}
            aria-expanded={open === "like"}
            aria-label={t("runs.feed.likeAria", { count: likes.length })}
            className={
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors " +
              (open === "like"
                ? "bg-[#e7f3ff] text-[#0866ff]"
                : likes.length > 0
                  ? "text-[#0866ff] hover:bg-[#e7f3ff]"
                  : "cursor-default text-muted-foreground opacity-50")
            }
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              if (likes.length > 0) toggle("like")
            }}
          >
            <span
              aria-hidden
              className={
                "inline-grid h-5 w-5 place-items-center rounded-full text-[11px] leading-none " +
                (likes.length > 0
                  ? "bg-[#0866ff] text-white"
                  : "bg-muted text-muted-foreground")
              }
            >
              👍
            </span>
            <span className="tabular-nums">{likes.length}</span>
            {!compact ? <span>{t("runs.feed.like")}</span> : null}
          </button>
          {open === "like" ? (
            <div
              className="absolute bottom-full left-0 z-20 mb-1.5 min-w-[12rem] max-w-[16rem] rounded-lg border border-border bg-card p-1.5 shadow-lg"
              role="dialog"
              aria-label={t("runs.feed.likedBy")}
            >
              <div className="border-b border-border/60 px-2 py-1 text-[11px] font-semibold text-muted-foreground">
                {t("runs.feed.likedBy")}
              </div>
              <ActorList
                agents={agents}
                userIds={likes}
                emptyLabel={t("runs.feed.noLikes")}
                onOpenAgent={openAgentAndClose}
              />
            </div>
          ) : null}
        </div>

        <div className="relative">
          <button
            type="button"
            disabled={dislikes.length === 0}
            aria-expanded={open === "dislike"}
            aria-label={t("runs.feed.dislikeAria", { count: dislikes.length })}
            className={
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors " +
              (open === "dislike"
                ? "bg-[#fde8e8] text-[#e41e3f]"
                : dislikes.length > 0
                  ? "text-[#e41e3f] hover:bg-[#fde8e8]"
                  : "cursor-default text-muted-foreground opacity-50")
            }
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              if (dislikes.length > 0) toggle("dislike")
            }}
          >
            <span
              aria-hidden
              className={
                "inline-grid h-5 w-5 place-items-center rounded-full text-[11px] leading-none " +
                (dislikes.length > 0
                  ? "bg-[#e41e3f] text-white"
                  : "bg-muted text-muted-foreground")
              }
            >
              👎
            </span>
            <span className="tabular-nums">{dislikes.length}</span>
            {!compact ? <span>{t("runs.feed.dislike")}</span> : null}
          </button>
          {open === "dislike" ? (
            <div
              className="absolute bottom-full left-0 z-20 mb-1.5 min-w-[12rem] max-w-[16rem] rounded-lg border border-border bg-card p-1.5 shadow-lg"
              role="dialog"
              aria-label={t("runs.feed.dislikedBy")}
            >
              <div className="border-b border-border/60 px-2 py-1 text-[11px] font-semibold text-muted-foreground">
                {t("runs.feed.dislikedBy")}
              </div>
              <ActorList
                agents={agents}
                userIds={dislikes}
                emptyLabel={t("runs.feed.noDislikes")}
                onOpenAgent={openAgentAndClose}
              />
            </div>
          ) : null}
        </div>

        {!compact ? (
          <div className="relative">
            <button
              type="button"
              disabled={shares.length === 0}
              aria-expanded={open === "share"}
              aria-label={t("runs.feed.shareAria", { count: shares.length })}
              className={
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors " +
                (open === "share"
                  ? "bg-muted text-foreground"
                  : shares.length > 0
                    ? "text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                    : "cursor-default text-muted-foreground opacity-50")
              }
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                if (shares.length > 0) toggle("share")
              }}
            >
              <span aria-hidden className="text-sm leading-none">
                ↗
              </span>
              <span className="tabular-nums">{shares.length}</span>
              <span>{t("runs.feed.shareVerb")}</span>
            </button>
            {open === "share" ? (
              <div
                className="absolute bottom-full left-0 z-20 mb-1.5 min-w-[12rem] max-w-[16rem] rounded-lg border border-border bg-card p-1.5 shadow-lg"
                role="dialog"
                aria-label={t("runs.feed.sharedBy")}
              >
                <div className="border-b border-border/60 px-2 py-1 text-[11px] font-semibold text-muted-foreground">
                  {t("runs.feed.sharedBy")}
                </div>
                <ul className="max-h-40 overflow-auto py-0.5">
                  {shares.map((s) => (
                    <li
                      key={`${s.user_id}-${s.kind}-${s.share_post_id ?? ""}`}
                      className="flex items-center justify-between gap-2 rounded px-2 py-0.5 text-xs hover:bg-muted/60"
                    >
                      <AgentNameButton
                        name={agentLabel(agents, s.user_id, t)}
                        className="px-0 py-1 text-left text-xs"
                        showAvatar={!agentIsInjector(agents, s.user_id)}
                        onOpen={() => openAgentAndClose(s.user_id)}
                      />
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        {s.kind === "quote"
                          ? t("runs.feed.quote")
                          : t("runs.feed.share")}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function mentionMatcherFor(agents: FeedAgent[]) {
  return getMentionMatcher(buildMentionAliases(agents))
}

export function FeedCommentCard({
  comment,
  agents,
  onOpenAgent,
}: {
  comment: FeedComment
  agents: FeedAgent[]
  onOpenAgent: (userId: number) => void
}) {
  const { t } = useLocale()
  const name = agentLabel(agents, comment.user_id, t)
  const injector = agentIsInjector(agents, comment.user_id)
  const matcher = mentionMatcherFor(agents)
  const hasAuthor = Number.isFinite(comment.user_id)
  return (
    <div className="flex items-start gap-1.5">
      {hasAuthor && !injector ? <AgentAvatar name={name} size="sm" /> : null}
      <div className="min-w-0 flex-1 rounded-2xl bg-muted/50 px-3 py-2">
        {hasAuthor ? (
          <button
            type="button"
            className="text-xs font-semibold text-foreground underline-offset-2 hover:underline"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onOpenAgent(comment.user_id)
            }}
          >
            {name}
          </button>
        ) : null}
        <CommentBody
          text={comment.content}
          matcher={matcher}
          onOpenMention={(userIds) => {
            if (userIds[0] != null) onOpenAgent(userIds[0])
          }}
          className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed text-foreground"
        />
        <LikeShareBar
          agents={agents}
          likedBy={comment.liked_by}
          dislikedBy={comment.disliked_by}
          compact
          onOpenAgent={onOpenAgent}
        />
      </div>
    </div>
  )
}

export function FeedPostSnippet({
  post,
  agents,
  onOpenAgent,
}: {
  post: FeedPost
  agents: FeedAgent[]
  onOpenAgent: (userId: number) => void
}) {
  const { t } = useLocale()
  const name = agentLabel(agents, post.user_id, t)
  const injector = agentIsInjector(agents, post.user_id)
  const matcher = mentionMatcherFor(agents)
  const hasAuthor = Number.isFinite(post.user_id)
  return (
    <div className="space-y-1.5">
      {hasAuthor ? (
        <div className="flex items-start gap-2">
          {injector ? null : <AgentAvatar name={name} size="sm" />}
          <button
            type="button"
            className="text-sm font-semibold text-foreground underline-offset-2 hover:underline"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onOpenAgent(post.user_id)
            }}
          >
            {name}
          </button>
        </div>
      ) : null}
      <CommentBody
        text={post.content}
        matcher={matcher}
        onOpenMention={(userIds) => {
          if (userIds[0] != null) onOpenAgent(userIds[0])
        }}
        className="whitespace-pre-wrap text-sm leading-relaxed text-foreground"
      />
      <LikeShareBar
        agents={agents}
        likedBy={post.liked_by}
        dislikedBy={post.disliked_by}
        sharedBy={post.shared_by}
        onOpenAgent={onOpenAgent}
      />
    </div>
  )
}
