import { useEffect, useMemo, useRef, useState, type ReactElement } from "react"
import { Loader2 } from "lucide-react"
import {
  buildSimulatedTimeLabels,
  describeTimelineAction,
  formatFeedWhenDisplay,
  isSimulatedClockTimestamp,
  type FollowRow,
  type MuteRow,
  type PostRow,
  type ReportRow,
  type SimulatedClockEvent,
} from "@/components/runs/activityFeed"
import {
  FeedCommentCard,
  FeedPostSnippet,
  type FeedAgent,
  type FeedComment,
  type FeedPost,
} from "@/components/runs/feedChrome"
import { collectLiveEvents } from "@/components/runs/liveFeedFromVariant"
import type {
  RunWatchActivityItem,
  RunWatchAgent,
  RunWatchTick,
  RunWatchRound,
} from "@/data/runWatch-types"
import { useLocale, type Locale, type MessageKey } from "@/i18n"

const POST_TARGET_ACTIONS = new Set([
  "like_post",
  "dislike_post",
  "unlike_post",
  "undo_dislike_post",
  "report_post",
  "repost",
  "quote_post",
])

const COMMENT_TARGET_ACTIONS = new Set([
  "like_comment",
  "dislike_comment",
  "unlike_comment",
  "undo_dislike_comment",
])

const TARGETED_ACTION_LABELS: Record<string, MessageKey> = {
  like_post: "runs.feed.actionLikePostOf",
  dislike_post: "runs.feed.actionDislikePostOf",
  unlike_post: "runs.feed.actionUnlikePostOf",
  undo_dislike_post: "runs.feed.actionUndoDislikePostOf",
  like_comment: "runs.feed.actionLikeCommentOf",
  dislike_comment: "runs.feed.actionDislikeCommentOf",
  unlike_comment: "runs.feed.actionUnlikeCommentOf",
  undo_dislike_comment: "runs.feed.actionUndoDislikeCommentOf",
  repost: "runs.feed.actionRepostOf",
  quote_post: "runs.feed.actionQuotePostOf",
  report_post: "runs.feed.actionReportOf",
}

function asInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function firstId(...values: unknown[]): number | null {
  for (const value of values) {
    const id = asInt(value)
    if (id != null) return id
  }
  return null
}

function possessiveName(name: string, locale: Locale): string {
  const trimmed = name.trim()
  if (!trimmed) return trimmed
  const last = trimmed.split(/\s+/).at(-1) ?? trimmed
  if (locale === "en") {
    return /s$/i.test(last) ? `${trimmed}'` : `${trimmed}'s`
  }
  return /[sxz]$/i.test(last) ? trimmed : `${trimmed}s`
}

export type LiveFeedCatalog = {
  posts?: FeedPost[]
  comments?: FeedComment[]
  follows?: FollowRow[]
  mutes?: MuteRow[]
  reports?: ReportRow[]
}

function asFeedAgents(agents: RunWatchAgent[]): FeedAgent[] {
  return agents
}

function agentName(
  agents: RunWatchAgent[],
  userId: number,
  t: (key: "runs.feed.agentFallback", params?: { userId: number }) => string,
): string {
  const name = agents.find((agent) => agent.index === userId)?.member_name.trim()
  return name || t("runs.feed.agentFallback", { userId })
}

function tickMeta(
  tickIndex: number,
  ticks: RunWatchTick[],
): RunWatchTick | undefined {
  return ticks.find((tick) => tick.tickIndex === tickIndex)
}

function postFromCatalog(
  item: RunWatchActivityItem,
  catalog: LiveFeedCatalog | undefined,
): FeedPost | null {
  const postId = firstId(item.post_id, item.info?.post_id)
  const found =
    postId != null
      ? catalog?.posts?.find((post) => post.post_id === postId)
      : undefined
  const preview =
    item.post_preview ??
    (item.action === "create_post" ? item.content : undefined) ??
    found?.content
  if (!found && !preview && postId == null) return null
  const likedBy = [...(found?.liked_by ?? [])]
  const action = item.action.trim().toLowerCase()
  if (action === "like_post" && !likedBy.includes(item.user_id)) {
    likedBy.push(item.user_id)
  }
  const dislikedBy = [...(found?.disliked_by ?? [])]
  if (action === "dislike_post" && !dislikedBy.includes(item.user_id)) {
    dislikedBy.push(item.user_id)
  }
  return {
    ...(found ?? {
      post_id: postId ?? 0,
      original_post_id: null,
      quote_content: null,
      num_likes: 0,
      num_dislikes: 0,
      num_shares: 0,
      created_at: 0,
    }),
    post_id: found?.post_id ?? postId ?? 0,
    user_id: firstId(
      found?.user_id,
      item.action === "create_post" ? item.user_id : null,
      item.info?.post_user_id,
    ) ?? 0,
    content: found?.content || preview || "",
    liked_by: likedBy,
    disliked_by: dislikedBy,
    shared_by: found?.shared_by,
  }
}

function commentFromCatalog(
  item: RunWatchActivityItem,
  catalog: LiveFeedCatalog | undefined,
): FeedComment | null {
  const commentId = firstId(item.comment_id, item.info?.comment_id)
  const found =
    commentId != null
      ? catalog?.comments?.find((comment) => comment.comment_id === commentId)
      : undefined
  const preview =
    item.comment_preview ??
    (item.action === "create_comment" ? item.content : undefined) ??
    found?.content
  const userId = firstId(
    found?.user_id,
    item.info?.comment_user_id,
    item.action === "create_comment" ? item.user_id : null,
  )
  if (!found && !preview && commentId == null) return null
  if (!found && !preview && userId == null) return null
  const likedBy = [...(found?.liked_by ?? [])]
  const action = item.action.trim().toLowerCase()
  if (
    (action === "like_comment" || action === "dislike_comment") &&
    !likedBy.includes(item.user_id)
  ) {
    if (action === "like_comment") likedBy.push(item.user_id)
  }
  const dislikedBy = [...(found?.disliked_by ?? [])]
  if (action === "dislike_comment" && !dislikedBy.includes(item.user_id)) {
    dislikedBy.push(item.user_id)
  }
  return {
    comment_id: found?.comment_id ?? commentId ?? 0,
    post_id: found?.post_id ?? item.post_id ?? 0,
    user_id: userId ?? 0,
    content: found?.content || preview || "",
    liked_by: likedBy,
    disliked_by: dislikedBy,
  }
}

function postsByIdFromItem(
  item: RunWatchActivityItem,
  catalog: LiveFeedCatalog | undefined,
): Map<number, PostRow> {
  const map = new Map<number, PostRow>()
  for (const post of catalog?.posts ?? []) map.set(post.post_id, post)
  const fallback = postFromCatalog(item, catalog)
  if (fallback && fallback.post_id > 0 && !map.has(fallback.post_id)) {
    map.set(fallback.post_id, fallback)
  }
  return map
}

function followsById(catalog: LiveFeedCatalog | undefined): Map<number, FollowRow> {
  const map = new Map<number, FollowRow>()
  for (const follow of catalog?.follows ?? []) {
    if (follow.follow_id != null) map.set(follow.follow_id, follow)
  }
  return map
}

function mutesById(catalog: LiveFeedCatalog | undefined): Map<number, MuteRow> {
  const map = new Map<number, MuteRow>()
  for (const mute of catalog?.mutes ?? []) {
    if (mute.mute_id != null) map.set(mute.mute_id, mute)
  }
  return map
}

function reportsById(catalog: LiveFeedCatalog | undefined): Map<number, ReportRow> {
  const map = new Map<number, ReportRow>()
  for (const report of catalog?.reports ?? []) {
    if (report.report_id != null) map.set(report.report_id, report)
  }
  return map
}

function lastWordSplit(
  label: string,
  word: string,
): { before: string; word: string; after: string } | null {
  const lower = label.toLocaleLowerCase("sv-SE")
  const needle = word.toLocaleLowerCase("sv-SE")
  const idx = lower.lastIndexOf(needle)
  if (idx < 0) return null
  const beforeChar = idx === 0 ? "" : label[idx - 1] ?? ""
  const afterChar = label[idx + word.length] ?? ""
  const isLetter = (char: string) => char !== "" && /\p{L}/u.test(char)
  if (isLetter(beforeChar) || isLetter(afterChar)) return null
  return {
    before: label.slice(0, idx),
    word: label.slice(idx, idx + word.length),
    after: label.slice(idx + word.length),
  }
}

type LabelToggle = {
  word: string
  expanded: boolean
  expandAria: string
  collapseAria: string
  onToggle: () => void
}

function ActionLabelToggles({
  label,
  targets,
}: {
  label: string
  targets: LabelToggle[]
}) {
  const hits = targets
    .map((target, index) => {
      const parts = lastWordSplit(label, target.word)
      if (!parts) return null
      const start = parts.before.length
      return {
        index,
        start,
        end: start + parts.word.length,
        display: parts.word,
        target,
      }
    })
    .filter((hit): hit is NonNullable<typeof hit> => hit != null)
    .sort((a, b) => a.start - b.start)

  function wordButton(target: LabelToggle, display: string, key: string) {
    return (
      <button
        key={key}
        type="button"
        aria-expanded={target.expanded}
        aria-label={target.expanded ? target.collapseAria : target.expandAria}
        className="font-medium text-foreground underline decoration-foreground/40 underline-offset-2 hover:decoration-foreground"
        onClick={(event) => {
          event.preventDefault()
          target.onToggle()
        }}
      >
        {display}
      </button>
    )
  }

  if (hits.length === 0) {
    return (
      <span className="text-foreground">
        {label}
        {targets.map((target) => (
          <span key={target.word}> {wordButton(target, target.word, target.word)}</span>
        ))}
      </span>
    )
  }

  const nodes: Array<string | ReactElement> = []
  let cursor = 0
  for (const hit of hits) {
    if (hit.start < cursor) continue
    if (hit.start > cursor) nodes.push(label.slice(cursor, hit.start))
    nodes.push(wordButton(hit.target, hit.display, `${hit.index}-${hit.start}`))
    cursor = hit.end
  }
  if (cursor < label.length) nodes.push(label.slice(cursor))
  return <span className="text-foreground">{nodes}</span>
}

function LiveActivityRow({
  item,
  agents,
  catalog,
  simulatedWhen,
  onOpenAgent,
}: {
  item: RunWatchActivityItem
  agents: RunWatchAgent[]
  catalog?: LiveFeedCatalog
  simulatedWhen?: string | null
  onOpenAgent: (userId: number) => void
}) {
  const { t, locale, intl } = useLocale()
  const [openPost, setOpenPost] = useState(false)
  const [openComment, setOpenComment] = useState(false)
  const action = item.action.trim().toLowerCase()
  const author = agentName(agents, item.user_id, t)
  const feedAgents = asFeedAgents(agents)
  const createdAt = formatFeedWhenDisplay(item.created_at, intl, simulatedWhen)
  const post = postFromCatalog(item, catalog)
  const comment = commentFromCatalog(item, catalog)

  const desc = describeTimelineAction(action, item.user_id, t, {
    info: {
      ...(item.info ?? {}),
      ...(item.post_id != null ? { post_id: item.post_id } : {}),
      ...(item.comment_id != null ? { comment_id: item.comment_id } : {}),
    },
    followsById: followsById(catalog),
    mutesById: mutesById(catalog),
    reportsById: reportsById(catalog),
    followsLoose: catalog?.follows ?? [],
    mutesLoose: catalog?.mutes ?? [],
    postsById: postsByIdFromItem(item, catalog),
    agentName: (userId) => agentName(agents, userId, t),
  })

  const parentUserId = firstId(post?.user_id, item.info?.post_user_id)
  let actionLabel = desc.label
  let showPost = POST_TARGET_ACTIONS.has(action) && post != null
  let showComment = COMMENT_TARGET_ACTIONS.has(action) && comment != null

  if (action === "create_comment") {
    showComment = comment != null
    showPost = post != null && Boolean(post.content)
    if (parentUserId != null) {
      actionLabel =
        parentUserId === item.user_id
          ? t("runs.feed.actionCreateCommentOwn")
          : t("runs.feed.actionCreateCommentOf", {
              whose: possessiveName(agentName(agents, parentUserId, t), locale),
            })
    } else {
      actionLabel = t("runs.feed.actionCreateComment")
    }
  } else if (action === "create_post") {
    showPost = post != null && Boolean(post.content)
    showComment = false
    actionLabel = t("runs.feed.actionCreatePost")
  } else {
    const targetUserId = COMMENT_TARGET_ACTIONS.has(action)
      ? firstId(comment?.user_id, item.info?.comment_user_id)
      : parentUserId
    const whose =
      targetUserId != null
        ? possessiveName(agentName(agents, targetUserId, t), locale)
        : null
    const namedKey = TARGETED_ACTION_LABELS[action]
    if (whose && namedKey) actionLabel = t(namedKey, { whose })
  }

  const toggles: LabelToggle[] = []
  if (showComment) {
    toggles.push({
      word: t("runs.live.createComment"),
      expanded: openComment,
      expandAria: t("runs.live.expandComment"),
      collapseAria: t("runs.live.collapseComment"),
      onToggle: () => setOpenComment((open) => !open),
    })
  }
  if (showPost) {
    toggles.push({
      word: t("runs.live.createPost"),
      expanded: openPost,
      expandAria: t("runs.live.expandPost"),
      collapseAria: t("runs.live.collapsePost"),
      onToggle: () => setOpenPost((open) => !open),
    })
  }

  return (
    <li className="list-none rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-medium text-foreground">{author}</span>
        {toggles.length > 0 ? (
          <ActionLabelToggles label={actionLabel} targets={toggles} />
        ) : (
          <span className="text-foreground">{actionLabel}</span>
        )}
        {desc.detail ? (
          <span className="text-muted-foreground">{desc.detail}</span>
        ) : null}
        {createdAt ? <span className="text-xs text-muted-foreground">{createdAt}</span> : null}
      </div>
      {openComment && showComment && comment ? (
        <div className="mt-2 rounded-md border border-border/70 bg-background/60 px-2.5 py-2">
          <FeedCommentCard
            comment={comment}
            agents={feedAgents}
            onOpenAgent={onOpenAgent}
          />
        </div>
      ) : null}
      {openPost && showPost && post ? (
        <div className="mt-2 rounded-md border border-border/70 bg-background/60 px-2.5 py-2">
          <FeedPostSnippet post={post} agents={feedAgents} onOpenAgent={onOpenAgent} />
        </div>
      ) : null}
    </li>
  )
}

type LiveFeedEvent = ReturnType<typeof collectLiveEvents>[number]

function simulatedLabelsForTickEvents(events: LiveFeedEvent[]): Map<string, string> {
  const clockEvents: SimulatedClockEvent[] = []
  for (const event of events) {
    if (!isSimulatedClockTimestamp(event.item.created_at)) continue
    clockEvents.push({ key: event.key, createdAt: event.item.created_at })
  }
  return buildSimulatedTimeLabels(clockEvents)
}

function LiveTickSection({
  tickIndex,
  events,
  ticks,
  agents,
  catalog,
  expanded,
  onToggle,
  onOpenAgent,
}: {
  tickIndex: number
  events: LiveFeedEvent[]
  ticks: RunWatchTick[]
  agents: RunWatchAgent[]
  catalog?: LiveFeedCatalog
  expanded: boolean
  onToggle: () => void
  onOpenAgent: (userId: number) => void
}) {
  const { t } = useLocale()
  const tick = tickMeta(tickIndex, ticks)
  const day = tick?.day ?? tickIndex + 1
  const silent = tick?.silent === true
  const inProgress = tick != null && !tick.completed
  const simulatedLabels = useMemo(
    () => simulatedLabelsForTickEvents(events),
    [events],
  )
  const sectionId = `live-tick-${tickIndex}`

  return (
    <section className="rounded-lg border border-border bg-card/40">
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-2 px-4 py-3 text-left"
        aria-expanded={expanded}
        aria-controls={sectionId}
        onClick={onToggle}
      >
        <h3 className="text-sm font-semibold text-foreground">
          {t("runs.results.dayLabel", { day })}
        </h3>
        {silent ? (
          <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            {t("runs.results.silentTick")}
          </span>
        ) : null}
        {inProgress ? (
          <span className="inline-flex items-center gap-1 text-xs text-db-gold-700">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            {t("runs.live.tickInProgress")}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {expanded ? t("runs.live.collapseDay") : t("runs.live.expandDay")}
        </span>
      </button>
      {expanded ? (
        <ul id={sectionId} className="flex flex-col gap-2 border-t border-border/60 px-4 py-3">
          {events.map((event) => (
            <LiveActivityRow
              key={event.key}
              item={event.item}
              agents={agents}
              catalog={catalog}
              simulatedWhen={simulatedLabels.get(event.key) ?? null}
              onOpenAgent={onOpenAgent}
            />
          ))}
        </ul>
      ) : null}
    </section>
  )
}

export function LiveFeedList({
  rounds,
  agents,
  ticks,
  emptyLabel,
  catalog,
  onOpenAgent,
}: {
  rounds: RunWatchRound[]
  agents: RunWatchAgent[]
  ticks: RunWatchTick[]
  emptyLabel: string
  catalog?: LiveFeedCatalog
  onOpenAgent?: (userId: number) => void
}) {
  const events = useMemo(() => collectLiveEvents(rounds), [rounds])
  const openAgent = onOpenAgent ?? (() => {})
  const tickIndexes = useMemo(
    () => [...new Set(events.map((event) => event.tickIndex))].sort((a, b) => b - a),
    [events],
  )
  const eventsByTick = useMemo(() => {
    const map = new Map<number, LiveFeedEvent[]>()
    for (const event of events) {
      const bucket = map.get(event.tickIndex) ?? []
      bucket.push(event)
      map.set(event.tickIndex, bucket)
    }
    return map
  }, [events])

  const seenTicksRef = useRef<Set<number>>(new Set())
  const [collapsedTicks, setCollapsedTicks] = useState<Set<number>>(() => new Set())

  useEffect(() => {
    const newest = tickIndexes[0]
    if (newest == null) return
    setCollapsedTicks((prev) => {
      const next = new Set(prev)
      for (const tickIndex of tickIndexes) {
        if (seenTicksRef.current.has(tickIndex)) continue
        seenTicksRef.current.add(tickIndex)
        if (tickIndex !== newest) next.add(tickIndex)
      }
      next.delete(newest)
      return next
    })
  }, [tickIndexes])

  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {tickIndexes.map((tickIndex) => {
        const tickEvents = eventsByTick.get(tickIndex) ?? []
        if (tickEvents.length === 0) return null
        const expanded = !collapsedTicks.has(tickIndex)
        return (
          <LiveTickSection
            key={tickIndex}
            tickIndex={tickIndex}
            events={tickEvents}
            ticks={ticks}
            agents={agents}
            catalog={catalog}
            expanded={expanded}
            onToggle={() =>
              setCollapsedTicks((prev) => {
                const next = new Set(prev)
                if (next.has(tickIndex)) next.delete(tickIndex)
                else next.add(tickIndex)
                return next
              })
            }
            onOpenAgent={openAgent}
          />
        )
      })}
    </div>
  )
}
