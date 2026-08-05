/** Build a chronological timeline: posts + compact non-engagement actions. */

import type { OasisVariantResult } from "@/data/runs-types"
import type { MessageKey, TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

export type PostRow = NonNullable<OasisVariantResult["posts"]>[number]
export type TraceRow = NonNullable<OasisVariantResult["trace"]>[number]
export type FollowRow = NonNullable<OasisVariantResult["follows"]>[number]
export type MuteRow = NonNullable<OasisVariantResult["mutes"]>[number]
export type ReportRow = NonNullable<OasisVariantResult["reports"]>[number]
export type AgentRow = NonNullable<OasisVariantResult["agents"]>[number]
export type AgentToolRow = NonNullable<OasisVariantResult["agent_tools"]>[number]

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

export const NOISE_ACTIONS = new Set(["refresh", "do_nothing"])

/** Never shown in feed or day-event modals. */
export const HIDDEN_ACTIONS = new Set(["sign_up"])

export type TimelinePostItem = {
  kind: "post"
  tickIndex: number
  sortKey: number
  tie: number
  post: PostRow
}

export type TimelineActionItem = {
  kind: "action"
  tickIndex: number
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

export type TimelineTickItem = {
  kind: "tick"
  tickIndex: number
  sortKey: number
  tie: number
  day: number
  silent: boolean
  tickKey: string
  rounds: number
  timeStart: number
  timeEnd: number
}

export type TimelineItem =
  | TimelinePostItem
  | TimelineActionItem
  | TimelineTickItem

export type TickMarker = NonNullable<OasisVariantResult["tick_markers"]>[number]

export function tickIndexForTime(t: number, markers: TickMarker[]): number {
  for (const m of markers) {
    if (m.time_start <= t && t <= m.time_end) return m.tick_index
  }
  if (markers.length === 0) return 0
  if (t < markers[0].time_start) return -1
  return markers[markers.length - 1].tick_index
}

/** Tick for a post/comment timestamp; falls back when markers or time missing. */
export function tickIndexForCreatedAt(
  createdAt: string | number | undefined,
  markers: TickMarker[],
  fallbackTick = 0,
): number {
  if (markers.length === 0) return fallbackTick
  if (createdAt == null || createdAt === "") return fallbackTick
  const tick = tickIndexForTime(sortKeyFromCreatedAt(createdAt), markers)
  return tick < 0 ? fallbackTick : tick
}

/** External tools used by an agent during the same tick as a post/comment. */
export function agentToolsForAuthor(
  tools: AgentToolRow[] | undefined,
  userId: number,
  tickIndex: number,
): AgentToolRow[] {
  return (tools ?? [])
    .filter((row) => row.user_id === userId && row.tick_index === tickIndex)
    .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
}

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

export function argPreview(args: Record<string, unknown> | undefined): string | null {
  if (!args) return null
  for (const key of ["query", "entity", "expression", "input", "text"]) {
    const value = args[key]
    if (typeof value === "string" && value.trim()) return value.trim()
  }
  const first = Object.values(args).find((v) => typeof v === "string" && v.trim())
  return typeof first === "string" ? first.trim() : null
}

export function describeAgentTool(
  row: AgentToolRow,
  t: Translate,
): {
  label: string
  detail: string | null
} {
  const argsPreview = argPreview(row.args)
  switch (row.tool_name) {
    case "search_duckduckgo":
      return { label: t("runs.feed.actionSearchWeb"), detail: argsPreview }
    case "search_wiki":
      return { label: t("runs.feed.actionSearchWiki"), detail: argsPreview }
    default:
      return {
        label: t("runs.feed.actionSympy"),
        detail: argsPreview ?? row.result_preview ?? row.tool_name,
      }
  }
}

function sortKeyForAgentTool(row: AgentToolRow, markers: TickMarker[]): number {
  const marker = markers.find((m) => m.tick_index === row.tick_index)
  if (!marker) return row.tick_index * 1_000_000
  return marker.time_start + (row.sequence ?? 0)
}

export function agentToolHistogram(
  rows: AgentToolRow[] | undefined,
): Array<{ tool_name: string; count: number }> {
  const counts = new Map<string, number>()
  for (const row of rows ?? []) {
    counts.set(row.tool_name, (counts.get(row.tool_name) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([tool_name, count]) => ({ tool_name, count }))
    .sort((a, b) => b.count - a.count)
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
  t: Translate,
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
        label: t("runs.feed.actionFollow"),
        detail: target != null ? ctx.agentName(target) : t("runs.feed.actionSomeone"),
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
        label: t("runs.feed.actionUnfollow"),
        detail: target != null ? ctx.agentName(target) : t("runs.feed.actionSomeone"),
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
        label: t("runs.feed.actionMute"),
        detail: target != null ? ctx.agentName(target) : t("runs.feed.actionSomeone"),
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
        label: t("runs.feed.actionUnmute"),
        detail: target != null ? ctx.agentName(target) : t("runs.feed.actionSomeone"),
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
        label: t("runs.feed.actionReport"),
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
        label: t("runs.feed.actionRefresh"),
        detail: n != null ? t("runs.feed.actionRefreshDetail", { count: n }) : null,
        targetUserId: null,
        postId: null,
      }
    }
    case "sign_up":
      // OASIS skapar kontot i sim-DB:n — agentnamnet syns redan som actor.
      return {
        label: t("runs.feed.actionSignUp"),
        detail: null,
        targetUserId: null,
        postId: null,
      }
    case "do_nothing":
      return {
        label: t("runs.feed.actionDoNothing"),
        detail: null,
        targetUserId: null,
        postId: null,
      }
    case "interview": {
      const prompt =
        typeof ctx.info.prompt === "string" ? ctx.info.prompt : null
      const response =
        typeof ctx.info.response === "string" ? ctx.info.response : null
      const snippet = response
        ? response.length > 80
          ? `${response.slice(0, 80)}…`
          : response
        : null
      return {
        label: t("runs.feed.actionInterview"),
        detail: prompt
          ? snippet
            ? t("runs.feed.actionInterviewDetail", { prompt, snippet })
            : t("runs.feed.actionInterviewPrompt", { prompt })
          : snippet,
        targetUserId: null,
        postId: null,
      }
    }
    case "search_user": {
      const q =
        typeof ctx.info.query === "string"
          ? ctx.info.query
          : typeof ctx.info.user_name === "string"
            ? ctx.info.user_name
            : null
      return {
        label: t("runs.feed.actionSearchUser"),
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
        label: t("runs.feed.actionSearchPosts"),
        detail: q,
        targetUserId: null,
        postId: null,
      }
    }
    case "trend":
      return {
        label: t("runs.feed.actionTrend"),
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
  if (HIDDEN_ACTIONS.has(action)) return false
  if (hideNoise && NOISE_ACTIONS.has(action)) return false
  return true
}

export function buildTimelineItems(
  variant: OasisVariantResult,
  options: {
    hideNoise: boolean
    agentName: (userId: number) => string
    t: Translate
  },
): TimelineItem[] {
  const { hideNoise, agentName, t } = options
  const posts = variant.posts ?? []
  const trace = variant.trace ?? []
  const follows = variant.follows ?? []
  const mutes = variant.mutes ?? []
  const reports = variant.reports ?? []
  const markers = variant.tick_markers ?? []

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

  for (const m of markers) {
    items.push({
      kind: "tick",
      tickIndex: m.tick_index,
      sortKey: m.time_start,
      tie: -1,
      day: m.day,
      silent: m.silent,
      tickKey: m.key,
      rounds: m.rounds ?? 1,
      timeStart: m.time_start,
      timeEnd: m.time_end,
    })
  }

  posts.forEach((post, i) => {
    const sortTime = sortKeyFromCreatedAt(post.created_at)
    items.push({
      kind: "post",
      tickIndex: markers.length ? tickIndexForTime(sortTime, markers) : 0,
      sortKey: sortTime,
      tie: i,
      post,
    })
  })

  let actionTie = 0
  for (const row of variant.agent_tools ?? []) {
    const desc = describeAgentTool(row, t)
    items.push({
      kind: "action",
      tickIndex: row.tick_index,
      sortKey: sortKeyForAgentTool(row, markers),
      tie: 20_000 + actionTie++,
      userId: row.user_id,
      action: `tool:${row.tool_name}`,
      createdAt: undefined,
      label: desc.label,
      detail: row.result_preview ?? desc.detail,
      targetUserId: null,
      postId: null,
    })
  }

  for (const row of trace) {
    const action = (row.action || "").trim()
    if (!isTimelineAction(action, hideNoise)) continue
    const info = parseTraceInfo(row.info)
    const desc = describeTimelineAction(action, row.user_id, t, {
      info,
      followsById,
      mutesById,
      reportsById,
      followsLoose: follows,
      mutesLoose: mutes,
      postsById,
      agentName,
    })
    const sortTime = sortKeyFromCreatedAt(row.created_at)
    items.push({
      kind: "action",
      tickIndex: markers.length ? tickIndexForTime(sortTime, markers) : 0,
      sortKey: sortTime,
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
    if (a.tickIndex !== b.tickIndex) return a.tickIndex - b.tickIndex
    const rank = (item: TimelineItem): number => {
      if (item.kind === "tick") return -1
      if (item.kind === "post") return 1
      return 2
    }
    const ra = rank(a)
    const rb = rank(b)
    if (ra !== rb) return ra - rb
    if (a.sortKey !== b.sortKey) return a.sortKey - b.sortKey
    return a.tie - b.tie
  })
  return items
}

export type TimelineSegment =
  | { kind: "tick"; tick: TimelineTickItem; key: string }
  | { kind: "post"; post: PostRow; key: string }
  | { kind: "actions"; actions: TimelineActionItem[]; key: string }

/** Collapse consecutive action rows; keep tick cards and posts as boundaries. */
export function groupTimelineSegments(items: TimelineItem[]): TimelineSegment[] {
  const segments: TimelineSegment[] = []
  let pending: TimelineActionItem[] = []
  let cluster = 0

  function flushActions() {
    if (pending.length === 0) return
    segments.push({
      kind: "actions",
      actions: pending,
      key: `actions-${cluster++}-${pending[0].tickIndex}-${pending[0].sortKey}-${pending.length}`,
    })
    pending = []
  }

  for (const item of items) {
    if (item.kind === "tick") {
      flushActions()
      segments.push({
        kind: "tick",
        tick: item,
        key: `tick-${item.tickKey}-${item.tickIndex}`,
      })
    } else if (item.kind === "post") {
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
