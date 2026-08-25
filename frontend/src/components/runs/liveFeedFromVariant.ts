import {
  HIDDEN_ACTIONS,
  tickIndexForCreatedAt,
  type PostRow,
} from "@/components/runs/activityFeed"
import type { OasisVariantResult } from "@/data/runs-types"
import type {
  RunWatchActivityItem,
  RunWatchAgent,
  RunWatchRound,
  RunWatchTick,
} from "@/data/runWatch-types"

function asInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function parseTraceInfo(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  if (typeof raw !== "string" || !raw.trim()) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    return {}
  }
  return {}
}

function asActivityItem(raw: unknown): RunWatchActivityItem | null {
  if (!raw || typeof raw !== "object") return null
  const row = raw as Record<string, unknown>
  if (typeof row.user_id !== "number") return null
  if (typeof row.action !== "string") return null
  const item: RunWatchActivityItem = {
    user_id: row.user_id,
    action: row.action,
  }
  const postId = asInt(row.post_id) ?? asInt((row.info as Record<string, unknown> | undefined)?.post_id)
  const commentId =
    asInt(row.comment_id) ??
    asInt((row.info as Record<string, unknown> | undefined)?.comment_id)
  if (postId != null) item.post_id = postId
  if (commentId != null) item.comment_id = commentId
  if (typeof row.content === "string" && row.content) item.content = row.content
  if (typeof row.post_preview === "string" && row.post_preview) {
    item.post_preview = row.post_preview
  }
  if (typeof row.comment_preview === "string" && row.comment_preview) {
    item.comment_preview = row.comment_preview
  }
  if (row.info && typeof row.info === "object" && !Array.isArray(row.info)) {
    item.info = row.info as Record<string, unknown>
  }
  if (row.created_at != null && row.created_at !== "") {
    item.created_at = row.created_at as string | number
  }
  return item
}

function storedRounds(variant: OasisVariantResult): RunWatchRound[] {
  const raw = variant.live_feed?.rounds
  if (!Array.isArray(raw) || raw.length === 0) return []
  const rounds: RunWatchRound[] = []
  for (const row of raw) {
    const tickIndex =
      typeof row.tick_index === "number"
        ? row.tick_index
        : typeof row.tickIndex === "number"
          ? row.tickIndex
          : null
    const roundIndex =
      typeof row.round_index === "number"
        ? row.round_index
        : typeof row.roundIndex === "number"
          ? row.roundIndex
          : 0
    if (tickIndex == null) continue
    const items: RunWatchActivityItem[] = []
    for (const item of row.items ?? []) {
      const parsed = asActivityItem(item)
      if (parsed) items.push(parsed)
    }
    rounds.push({ tickIndex, roundIndex, items })
  }
  return rounds
}

function reconstructRounds(variant: OasisVariantResult): RunWatchRound[] {
  const trace = variant.trace ?? []
  if (trace.length === 0) return []
  const postsById = new Map<number, PostRow>()
  for (const post of variant.posts ?? []) postsById.set(post.post_id, post)
  const commentsById = new Map<number, NonNullable<OasisVariantResult["comments"]>[number]>()
  for (const comment of variant.comments ?? []) {
    commentsById.set(comment.comment_id, comment)
  }
  const markers = variant.tick_markers ?? []
  const byTick = new Map<number, RunWatchActivityItem[]>()

  for (const row of trace) {
    const action = row.action.trim().toLowerCase()
    const info = parseTraceInfo(row.info)
    const postId = asInt(info.post_id)
    const commentId = asInt(info.comment_id)
    const tickIndex = tickIndexForCreatedAt(row.created_at, markers, 0)
    const item: RunWatchActivityItem = {
      user_id: row.user_id,
      action,
      created_at: row.created_at,
      info,
    }
    if (postId != null) item.post_id = postId
    if (commentId != null) item.comment_id = commentId
    if (action === "create_post" && postId != null) {
      const content = postsById.get(postId)?.content
      if (content) item.content = content
    }
    if (action === "create_comment" && commentId != null) {
      const comment = commentsById.get(commentId)
      if (comment?.content) item.content = comment.content
      if (comment && item.post_id == null) item.post_id = comment.post_id
    }
    if (
      (action === "like_post" ||
        action === "dislike_post" ||
        action === "unlike_post" ||
        action === "undo_dislike_post" ||
        action === "report_post" ||
        action === "repost" ||
        action === "quote_post") &&
      postId != null
    ) {
      const preview = postsById.get(postId)?.content
      if (preview) item.post_preview = preview
    }
    if (
      (action === "like_comment" ||
        action === "dislike_comment" ||
        action === "unlike_comment" ||
        action === "undo_dislike_comment") &&
      commentId != null
    ) {
      const comment = commentsById.get(commentId)
      if (comment?.content) item.comment_preview = comment.content
      if (comment && item.post_id == null) item.post_id = comment.post_id
    }
    const bucket = byTick.get(tickIndex) ?? []
    bucket.push(item)
    byTick.set(tickIndex, bucket)
  }

  return [...byTick.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([tickIndex, items]) => ({ tickIndex, roundIndex: 0, items }))
}

function followeeForItem(
  item: RunWatchActivityItem,
  follows: NonNullable<OasisVariantResult["follows"]>,
  allowLooseMatch: boolean,
): number | null {
  const info = item.info ?? {}
  const direct = asInt(info.followee_id)
  if (direct != null) return direct
  const followId = asInt(info.follow_id)
  if (followId != null) {
    const row = follows.find((follow) => follow.follow_id === followId)
    if (row) return row.followee_id
  }
  if (!allowLooseMatch) return null
  const mine = follows.filter((follow) => follow.follower_id === item.user_id)
  if (mine.length === 0) return null
  if (mine.length === 1) return mine[0].followee_id
  if (item.created_at != null) {
    const exact = mine.find((follow) => String(follow.created_at) === String(item.created_at))
    if (exact) return exact.followee_id
    const t = Number(item.created_at)
    if (Number.isFinite(t)) {
      let best = mine[0]
      let bestDist = Infinity
      for (const follow of mine) {
        const ft = Number(follow.created_at)
        if (!Number.isFinite(ft)) continue
        const dist = Math.abs(ft - t)
        if (dist < bestDist) {
          best = follow
          bestDist = dist
        }
      }
      return best.followee_id
    }
  }
  return mine[mine.length - 1].followee_id
}

function enrichItemWithCatalog(
  item: RunWatchActivityItem,
  variant: OasisVariantResult,
): RunWatchActivityItem {
  const action = item.action.trim().toLowerCase()
  const next: RunWatchActivityItem = {
    ...item,
    info: { ...(item.info ?? {}) },
  }
  const info = next.info ?? {}

  if (action === "follow" || action === "unfollow") {
    const followeeId = followeeForItem(
      item,
      variant.follows ?? [],
      action === "follow",
    )
    if (followeeId != null) info.followee_id = followeeId
  }

  if (action === "mute" || action === "unmute") {
    const muteeId = asInt(info.mutee_id)
    if (muteeId == null) {
      const muteId = asInt(info.mute_id)
      const mute =
        (muteId != null
          ? (variant.mutes ?? []).find((row) => row.mute_id === muteId)
          : undefined) ??
        (variant.mutes ?? []).find((row) => row.muter_id === item.user_id)
      if (mute) info.mutee_id = mute.mutee_id
    }
  }

  if (item.comment_id != null && !item.comment_preview) {
    const comment = (variant.comments ?? []).find((row) => row.comment_id === item.comment_id)
    if (comment?.content) next.comment_preview = comment.content
    if (comment && next.post_id == null) next.post_id = comment.post_id
  }

  if (item.post_id != null && !item.post_preview) {
    const post = (variant.posts ?? []).find((row) => row.post_id === item.post_id)
    if (post?.content) next.post_preview = post.content
  }

  next.info = info
  return next
}

function enrichRoundsWithCatalog(
  rounds: RunWatchRound[],
  variant: OasisVariantResult,
): RunWatchRound[] {
  return rounds.map((round) => ({
    ...round,
    items: round.items.map((item) => enrichItemWithCatalog(item, variant)),
  }))
}

export function collectLiveEvents(rounds: RunWatchRound[]): Array<{
  key: string
  tickIndex: number
  roundIndex: number
  item: RunWatchActivityItem
}> {
  const events: Array<{
    key: string
    tickIndex: number
    roundIndex: number
    item: RunWatchActivityItem
  }> = []
  for (const round of rounds) {
    round.items.forEach((item, index) => {
      if (HIDDEN_ACTIONS.has(item.action.trim().toLowerCase())) return
      events.push({
        key: `${round.tickIndex}-${round.roundIndex}-${index}-${item.user_id}-${item.action}-${item.created_at ?? index}`,
        tickIndex: round.tickIndex,
        roundIndex: round.roundIndex,
        item,
      })
    })
  }
  return events.reverse()
}

export function liveFeedFromVariant(variant: OasisVariantResult): {
  rounds: RunWatchRound[]
  agents: RunWatchAgent[]
  ticks: RunWatchTick[]
} {
  const stored = storedRounds(variant)
  const rounds = enrichRoundsWithCatalog(
    stored.length > 0 ? stored : reconstructRounds(variant),
    variant,
  )
  const agents: RunWatchAgent[] = (variant.agents ?? []).map((agent) => ({
    index: agent.index,
    username: agent.username,
    member_name: agent.member_name,
    persona_id: agent.persona_id,
    role: agent.role ?? "population",
  }))
  const ticks: RunWatchTick[] = (variant.tick_markers ?? []).map((marker) => ({
    tickIndex: marker.tick_index,
    day: marker.day,
    silent: marker.silent,
    key: marker.key,
    rounds: marker.rounds,
    completed: true,
  }))
  return { rounds, agents, ticks }
}

export function attemptHasLiveFeed(
  variants: OasisVariantResult[] | undefined,
): boolean {
  return (variants ?? []).some((variant) => {
    const feed = liveFeedFromVariant(variant)
    return feed.rounds.some((round) => round.items.length > 0)
  })
}
