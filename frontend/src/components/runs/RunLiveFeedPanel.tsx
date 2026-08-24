import { useMemo, useState, type ReactNode } from "react"
import { Loader2 } from "lucide-react"
import {
  describeTimelineAction,
  type PostRow,
} from "@/components/runs/activityFeed"
import { useRunWatchSocket } from "@/components/runs/useRunWatchSocket"
import { personaInitials } from "@/data/library"
import type {
  RunWatchActivityItem,
  RunWatchAgent,
  RunWatchRound,
  RunWatchTick,
  RunWatchVariantPlan,
} from "@/data/runWatch-types"
import { useLocale } from "@/i18n"

function agentLabel(
  agents: RunWatchAgent[],
  userId: number,
  t: (key: "runs.feed.agentFallback", params?: { userId: number }) => string,
): string {
  return (
    agents.find((agent) => agent.index === userId)?.member_name ??
    t("runs.feed.agentFallback", { userId })
  )
}

function tickMeta(
  tickIndex: number,
  ticks: RunWatchTick[],
): RunWatchTick | undefined {
  return ticks.find((tick) => tick.tickIndex === tickIndex)
}

function buildLivePostsById(item: RunWatchActivityItem): Map<number, PostRow> {
  if (item.post_id == null || !item.post_preview) return new Map()
  return new Map([
    [
      item.post_id,
      {
        post_id: item.post_id,
        user_id: 0,
        content: item.post_preview,
        original_post_id: null,
        quote_content: null,
        num_likes: 0,
        num_dislikes: 0,
        num_shares: 0,
        created_at: 0,
      },
    ],
  ])
}

function LiveActivityRow({
  item,
  agents,
}: {
  item: RunWatchActivityItem
  agents: RunWatchAgent[]
}) {
  const { t } = useLocale()
  const action = item.action.trim().toLowerCase()
  const author = agentLabel(agents, item.user_id, t)
  const createdAt =
    item.created_at != null && item.created_at !== ""
      ? t("runs.feed.simTime", { value: String(item.created_at) })
      : null

  if (action === "create_post" || action === "create_comment") {
    const kind =
      action === "create_post" ? t("runs.live.createPost") : t("runs.live.createComment")
    return (
      <li className="list-none rounded-lg border border-border bg-card px-3 py-2.5 shadow-sm">
        <div className="flex items-start gap-2">
          <span
            aria-hidden
            className="inline-grid h-8 w-8 shrink-0 place-items-center rounded-full bg-db-ink-950 text-[10px] font-semibold uppercase text-white"
          >
            {personaInitials(author)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{author}</span>
              <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                {kind}
              </span>
              {createdAt ? <span>{createdAt}</span> : null}
              {item.post_id != null ? <span>#{item.post_id}</span> : null}
              {item.comment_id != null ? (
                <span>{t("runs.live.commentId", { id: item.comment_id })}</span>
              ) : null}
            </div>
            {item.content ? (
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {item.content}
              </p>
            ) : null}
          </div>
        </div>
      </li>
    )
  }

  const desc = describeTimelineAction(action, item.user_id, t, {
    info: {
      ...(item.info ?? {}),
      ...(item.post_id != null ? { post_id: item.post_id } : {}),
      ...(item.comment_id != null ? { comment_id: item.comment_id } : {}),
    },
    followsById: new Map(),
    mutesById: new Map(),
    reportsById: new Map(),
    followsLoose: [],
    mutesLoose: [],
    postsById: buildLivePostsById(item),
    agentName: (userId) => agentLabel(agents, userId, t),
  })

  return (
    <li className="list-none rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-medium text-foreground">{author}</span>
        <span className="text-foreground">{desc.label}</span>
        {desc.detail ? (
          <span className="text-muted-foreground">{desc.detail}</span>
        ) : null}
        {createdAt ? <span className="text-xs text-muted-foreground">{createdAt}</span> : null}
      </div>
    </li>
  )
}

function LiveRoundBlock({
  round,
  agents,
  tick,
}: {
  round: RunWatchRound
  agents: RunWatchAgent[]
  tick?: RunWatchTick
}) {
  const { t } = useLocale()

  if (round.items.length === 0) return null

  return (
    <section className="space-y-2">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {t("runs.live.round", { round: round.roundIndex + 1 })}
        {tick?.rounds != null
          ? ` · ${t("runs.live.roundOf", { total: tick.rounds })}`
          : null}
      </h4>
      <ul className="flex flex-col gap-2">
        {round.items.map((item, index) => (
          <LiveActivityRow
            key={`${round.tickIndex}-${round.roundIndex}-${index}-${item.user_id}-${item.action}-${item.created_at ?? index}`}
            item={item}
            agents={agents}
          />
        ))}
      </ul>
    </section>
  )
}

function LiveTickSection({
  tickIndex,
  rounds,
  ticks,
  agents,
}: {
  tickIndex: number
  rounds: RunWatchRound[]
  ticks: RunWatchTick[]
  agents: RunWatchAgent[]
}) {
  const { t } = useLocale()
  const tick = tickMeta(tickIndex, ticks)
  const tickRounds = rounds.filter((round) => round.tickIndex === tickIndex)
  if (tickRounds.length === 0) return null

  const day = tick?.day ?? tickIndex + 1
  const silent = tick?.silent === true
  const inProgress = tick != null && !tick.completed

  return (
    <section className="rounded-lg border border-border bg-card/40 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
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
      </div>
      <div className="space-y-4">
        {tickRounds.map((round) => (
          <LiveRoundBlock
            key={`${round.tickIndex}-${round.roundIndex}`}
            round={round}
            agents={agents}
            tick={tick}
          />
        ))}
      </div>
    </section>
  )
}

type Props = {
  runId: number
  variantPlans: RunWatchVariantPlan[]
  enabled: boolean
}

export function RunLiveFeedPanel({ runId, variantPlans, enabled }: Props) {
  const { t } = useLocale()
  const [variantId, setVariantId] = useState(variantPlans[0]?.id ?? "main")
  const activeVariantId = variantPlans.some((plan) => plan.id === variantId)
    ? variantId
    : (variantPlans[0]?.id ?? "main")

  const live = useRunWatchSocket({
    runId,
    variantId: activeVariantId,
    enabled,
  })

  const tickIndexes = useMemo(() => {
    const fromTicks = live.ticks.map((tick) => tick.tickIndex)
    const fromRounds = live.rounds.map((round) => round.tickIndex)
    return [...new Set([...fromTicks, ...fromRounds])].sort((a, b) => a - b)
  }, [live.ticks, live.rounds])

  const statusLine = (() => {
    if (live.failedError) {
      return t("runs.live.failed", { error: live.failedError })
    }
    if (live.finished) {
      return t("runs.live.finished")
    }
    if (live.wsStatus === "connecting") {
      return t("runs.live.connecting")
    }
    if (live.wsStatus === "closed" && enabled) {
      return t("runs.live.reconnecting")
    }
    if (live.rounds.length === 0) {
      return t("runs.live.waiting")
    }
    return t("runs.live.streaming")
  })()

  return (
    <CardLikePanel
      title={t("runs.live.title")}
      statusLine={statusLine}
      variantPlans={variantPlans}
      activeVariantId={activeVariantId}
      onVariantChange={setVariantId}
    >
      {tickIndexes.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("runs.live.waiting")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {tickIndexes.map((tickIndex) => (
            <LiveTickSection
              key={tickIndex}
              tickIndex={tickIndex}
              rounds={live.rounds}
              ticks={live.ticks}
              agents={live.agents}
            />
          ))}
        </div>
      )}
    </CardLikePanel>
  )
}

function CardLikePanel({
  title,
  statusLine,
  variantPlans,
  activeVariantId,
  onVariantChange,
  children,
}: {
  title: string
  statusLine: string
  variantPlans: RunWatchVariantPlan[]
  activeVariantId: string
  onVariantChange: (variantId: string) => void
  children: ReactNode
}) {
  return (
    <div className="mb-6 rounded-lg border border-db-gold-500/30 bg-db-gold-50/20 p-4 ring-1 ring-db-gold-500/10">
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-foreground">{title}</h2>
          <p className="text-sm text-muted-foreground">{statusLine}</p>
        </div>
        {variantPlans.length > 1 ? (
          <div className="view-toggle shrink-0" role="tablist">
            {variantPlans.map((plan) => (
              <button
                key={plan.id}
                type="button"
                role="tab"
                aria-selected={activeVariantId === plan.id}
                className={activeVariantId === plan.id ? "on" : undefined}
                onClick={() => onVariantChange(plan.id)}
              >
                {plan.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {children}
    </div>
  )
}
