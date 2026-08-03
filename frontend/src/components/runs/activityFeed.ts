/** Build a chronological timeline: posts + compact non-engagement actions. */

import type { OasisVariantResult } from "@/data/runs-types"

export type PostRow = NonNullable<OasisVariantResult["posts"]>[number]
export type TraceRow = NonNullable<OasisVariantResult["trace"]>[number]
export type FollowRow = NonNullable<OasisVariantResult["follows"]>[number]
export type MuteRow = NonNullable<OasisVariantResult["mutes"]>[number]
export type ReportRow = NonNullable<OasisVariantResult["reports"]>[number]
export type AgentRow = NonNullable<OasisVariantResult["agents"]>[number]

/** Actions already shown on post/comment cards — skip as timeline rows. */
export const CARD_COVERED_ACTIONS = new Set([
  "create_post",
  "create_comment",
  "like_post",
  "dislike_post",
  "unlike_post",
  "undo_dislike_post",
  "like_comment",
  "dislike_comment",
  "unlike_comment",
  "undo_dislike_comment",
  "repost",
  "quote_post",
])

export const NOISE_ACTIONS = new Set(["refresh", "sign_up", "do_nothing"])

export type TimelinePostItem = {
  kind: "post"
  sortKey: number
  tie: number
  post: PostRow
}

export type TimelineActionItem = {
  kind: "action"
  sortKey: number
  tie: number
  userId: number
  action: string
  createdAt: string | number | undefined
  label: string
  detail: string | null
  targetUserId: number | null
  postId: number | null
}

export type TimelineItem = TimelinePostItem | TimelineActionItem

export function sortKeyFromCreatedAt(value: string | number | undefined): number {
  if (value == null || value === "") return Number.MAX_SAFE_INTEGER
  if (typeof value === "number" && Number.isFinite(value)) return value
  const asNum = Number(value)
  if (Number.isFinite(asNum) && String(value).trim() !== "") {
    // Numeric string from OASIS sim clock / wall-less timestamps
    if (!String(value).includes("-") && !String(value).includes("T")) {
      return asNum
    }
  }
  const ms = Date.parse(String(value))
  return Number.isNaN(ms) ? Number.MAX_SAFE_INTEGER : ms
}

export function parseTraceInfo(
  info: string | null | undefined,
): Record<string, unknown> {
  if (info == null || info === "") return {}
  try {
    const parsed: unknown = JSON.parse(info)
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    return {}
  }
  return {}
}

function asInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

export type ActionDescription = {
  label: string
  detail: string | null
  targetUserId: number | null
  postId: number | null
}

type DescribeCtx = {
  info: Record<string, unknown>
  followsById: Map<number, FollowRow>
  mutesById: Map<number, MuteRow>
  reportsById: Map<number, ReportRow>
  followsLoose: FollowRow[]
  mutesLoose: MuteRow[]
  postsById: Map<number, PostRow>
  agentName: (userId: number) => string
}

/**
 * Exhaustive handling of timeline-visible OASIS actions.
 * Unknown actions fall through to a generic label (not a TS never — action is string from DB).
 */
export function describeTimelineAction(
  action: string,
  actorUserId: number,
  ctx: DescribeCtx,
): ActionDescription {
  switch (action) {
    case "follow": {
      const followId = asInt(ctx.info.follow_id)
      const row =
        (followId != null ? ctx.followsById.get(followId) : undefined) ??
        ctx.followsLoose.find((f) => f.follower_id === actorUserId)
      const target =
        row?.followee_id ?? asInt(ctx.info.followee_id) ?? null
      return {
        label: "följde",
        detail: target != null ? ctx.agentName(target) : "någon",
        targetUserId: target,
        postId: null,
      }
    }
    case "unfollow": {
      const followId = asInt(ctx.info.follow_id)
      const row =
        (followId != null ? ctx.followsById.get(followId) : undefined) ??
        ctx.followsLoose.find((f) => f.follower_id === actorUserId)
      const target =
        row?.followee_id ?? asInt(ctx.info.followee_id) ?? null
      return {
        label: "slutade följa",
        detail: target != null ? ctx.agentName(target) : "någon",
        targetUserId: target,
        postId: null,
      }
    }
    case "mute": {
      const muteId = asInt(ctx.info.mute_id)
      const row =
        (muteId != null ? ctx.mutesById.get(muteId) : undefined) ??
        ctx.mutesLoose.find((m) => m.muter_id === actorUserId)
      const target = row?.mutee_id ?? asInt(ctx.info.mutee_id) ?? null
      return {
        label: "tystade",
        detail: target != null ? ctx.agentName(target) : "någon",
        targetUserId: target,
        postId: null,
      }
    }
    case "unmute": {
      const muteId = asInt(ctx.info.mute_id)
      const row =
        (muteId != null ? ctx.mutesById.get(muteId) : undefined) ??
        ctx.mutesLoose.find((m) => m.muter_id === actorUserId)
      const target = row?.mutee_id ?? asInt(ctx.info.mutee_id) ?? null
      return {
        label: "tog bort tystning av",
        detail: target != null ? ctx.agentName(target) : "någon",
        targetUserId: target,
        postId: null,
      }
    }
    case "report_post": {
      const postId = asInt(ctx.info.post_id)
      const reportId = asInt(ctx.info.report_id)
      const report =
        reportId != null ? ctx.reportsById.get(reportId) : undefined
      const reason =
        (typeof ctx.info.report_reason === "string" && ctx.info.report_reason) ||
        report?.report_reason ||
        null
      const preview =
        postId != null
          ? (ctx.postsById.get(postId)?.content ?? "").slice(0, 60)
          : ""
      return {
        label: "rapporterade",
        detail:
          postId != null
            ? `#${postId}${reason ? ` (${reason})` : ""}${preview ? ` — ${preview}` : ""}`
            : reason,
        targetUserId: null,
        postId,
      }
    }
    case "refresh": {
      const posts = ctx.info.posts
      const n = Array.isArray(posts) ? posts.length : null
      return {
        label: "uppdaterade flödet",
        detail: n != null ? `${n} inlägg` : null,
        targetUserId: null,
        postId: null,
      }
    }
    case "sign_up":
      // OASIS skapar kontot i sim-DB:n — agentnamnet syns redan som actor.
      return {
        label: "skapades i simuleringen",
        detail: null,
        targetUserId: null,
        postId: null,
      }
    case "do_nothing":
      return {
        label: "gjorde inget",
        detail: null,
        targetUserId: null,
        postId: null,
      }
    case "search_user": {
      const q =
        typeof ctx.info.query === "string"
          ? ctx.info.query
          : typeof ctx.info.user_name === "string"
            ? ctx.info.user_name
            : null
      return {
        label: "sökte användare",
        detail: q,
        targetUserId: null,
        postId: null,
      }
    }
    case "search_posts": {
      const q =
        typeof ctx.info.query === "string"
          ? ctx.info.query
          : typeof ctx.info.content === "string"
            ? ctx.info.content
            : null
      return {
        label: "sökte inlägg",
        detail: q,
        targetUserId: null,
        postId: null,
      }
    }
    case "trend":
      return {
        label: "såg trender",
        detail: null,
        targetUserId: null,
        postId: null,
      }
    case "create_post":
    case "create_comment":
    case "like_post":
    case "dislike_post":
    case "unlike_post":
    case "undo_dislike_post":
    case "like_comment":
    case "dislike_comment":
    case "unlike_comment":
    case "undo_dislike_comment":
    case "repost":
    case "quote_post":
      // Covered by cards — should not reach timeline, but label for safety.
      return {
        label: action,
        detail: null,
        targetUserId: null,
        postId: asInt(ctx.info.post_id),
      }
    default:
      return {
        label: action.replaceAll("_", " "),
        detail: null,
        targetUserId: null,
        postId: asInt(ctx.info.post_id),
      }
  }
}

export function isTimelineAction(
  action: string,
  hideNoise: boolean,
): boolean {
  if (CARD_COVERED_ACTIONS.has(action)) return false
  if (hideNoise && NOISE_ACTIONS.has(action)) return false
  return true
}

export function buildTimelineItems(
  variant: OasisVariantResult,
  options: {
    hideNoise: boolean
    agentName: (userId: number) => string
  },
): TimelineItem[] {
  const { hideNoise, agentName } = options
  const posts = variant.posts ?? []
  const trace = variant.trace ?? []
  const follows = variant.follows ?? []
  const mutes = variant.mutes ?? []
  const reports = variant.reports ?? []

  const followsById = new Map<number, FollowRow>()
  for (const f of follows) {
    if (f.follow_id != null) followsById.set(f.follow_id, f)
  }
  const mutesById = new Map<number, MuteRow>()
  for (const m of mutes) {
    if (m.mute_id != null) mutesById.set(m.mute_id, m)
  }
  const reportsById = new Map<number, ReportRow>()
  for (const r of reports) {
    if (r.report_id != null) reportsById.set(r.report_id, r)
  }
  const postsById = new Map(posts.map((p) => [p.post_id, p]))

  const items: TimelineItem[] = []

  posts.forEach((post, i) => {
    items.push({
      kind: "post",
      sortKey: sortKeyFromCreatedAt(post.created_at),
      tie: i,
      post,
    })
  })

  let actionTie = 0
  for (const row of trace) {
    const action = (row.action || "").trim()
    if (!isTimelineAction(action, hideNoise)) continue
    const info = parseTraceInfo(row.info)
    const desc = describeTimelineAction(action, row.user_id, {
      info,
      followsById,
      mutesById,
      reportsById,
      followsLoose: follows,
      mutesLoose: mutes,
      postsById,
      agentName,
    })
    items.push({
      kind: "action",
      sortKey: sortKeyFromCreatedAt(row.created_at),
      tie: 10_000 + actionTie++,
      userId: row.user_id,
      action,
      createdAt: row.created_at,
      label: desc.label,
      detail: desc.detail,
      targetUserId: desc.targetUserId,
      postId: desc.postId,
    })
  }

  items.sort((a, b) => {
    if (a.sortKey !== b.sortKey) return a.sortKey - b.sortKey
    const rank = (item: TimelineItem): number => {
      // Bootstrap: agents exist before they post at the same sim timestamp.
      if (item.kind === "action" && item.action === "sign_up") return 0
      if (item.kind === "post") return 1
      return 2
    }
    const ra = rank(a)
    const rb = rank(b)
    if (ra !== rb) return ra - rb
    return a.tie - b.tie
  })
  return items
}

export type TimelineSegment =
  | { kind: "post"; post: PostRow; key: string }
  | { kind: "actions"; actions: TimelineActionItem[]; key: string }

/** Collapse consecutive action rows into expandable clusters between posts. */
export function groupTimelineSegments(items: TimelineItem[]): TimelineSegment[] {
  const segments: TimelineSegment[] = []
  let pending: TimelineActionItem[] = []
  let cluster = 0

  function flushActions() {
    if (pending.length === 0) return
    segments.push({
      kind: "actions",
      actions: pending,
      key: `actions-${cluster++}-${pending[0].sortKey}-${pending.length}`,
    })
    pending = []
  }

  for (const item of items) {
    if (item.kind === "post") {
      flushActions()
      segments.push({
        kind: "post",
        post: item.post,
        key: `post-${item.post.post_id}`,
      })
    } else {
      pending.push(item)
    }
  }
  flushActions()
  return segments
}
