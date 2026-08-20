import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import { FileText, Files, Loader2, Network, Trash2, Wrench } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { createReport } from "@/api/reports"
import type { RunTaggableTextRow, TopicStatus } from "@/api/runs"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"
import { PersonaProfileModal } from "@/components/personas/PersonaProfileModal"
import {
  AddAnchorModal,
  ShieldIcon,
  type AddAnchorTarget,
} from "@/components/runs/AddAnchorModal"
import {
  ClassificationPopover,
  flaggedKeyForRow,
} from "@/components/runs/ClassificationPopover"
import { useRunTaggableTexts } from "@/components/runs/useRunTaggableTexts"
import {
  agentToolHistogram,
  agentToolsForAuthor,
  argPreview,
  buildTimelineItems,
  describeAgentTool,
  groupTimelineSegments,
  HIDDEN_ACTIONS,
  parseTraceInfo,
  sortKeyFromCreatedAt,
  tickIndexForCreatedAt,
  type AgentToolRow,
  type PostRow,
  type TickMarker,
  type TimelineActionItem,
} from "@/components/runs/activityFeed"
import {
  buildMentionAliases,
  CommentBody,
  getMentionMatcher,
} from "@/components/runs/commentMentions"
import {
  CopyFeedTextButton,
  formatCommentForClipboard,
  formatPostForClipboard,
  postBodyTextForCopy,
} from "@/components/runs/feedCopy"
import {
  InterviewIcon,
  RunPersonaInterviewModal,
} from "@/components/runs/RunPersonaInterviewPanel"
import { personaInitials } from "@/data/library"
import { ApiError } from "@/lib/api"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import {
  CONTROL_VARIANT_LABEL,
  STIMULUS_VARIANT_LABEL,
  type BranchMode,
  type OasisAttemptResult,
  type OasisMeasurementPoint,
  type OasisMeasurementRow,
  type OasisRunResults,
  type OasisVariantResult,
  type QualityWarnings,
} from "@/data/runs-types"

type Translate = (key: MessageKey, params?: TranslateParams) => string

type AgentRow = NonNullable<OasisVariantResult["agents"]>[number]

type ProfileTarget = {
  personaId: string | null
  name: string
}

type FeedAnchors = {
  byCommentId: Map<number, RunTaggableTextRow>
  byPostId: Map<number, TopicStatus>
  toneOptions: string[]
  styleOptions: string[]
  flaggedKeys: Set<string>
  onFlagged: (key: string) => void
  onAdd: (target: AddAnchorTarget) => void
  runId: number
  attemptId: string
  variantId: string
}

function topicBorderClass(status: TopicStatus | null | undefined): string {
  if (status === "drifted") return " feed-topic-drift"
  if (status === "on_topic") return " feed-topic-on"
  return ""
}

/** Normalize legacy flat results and current attempts[] into a stable list. */
export function normalizeRunAttempts(
  results: OasisRunResults | null | undefined,
  t: Translate,
): OasisAttemptResult[] {
  if (!results) return []
  if (Array.isArray(results.attempts) && results.attempts.length > 0) {
    return results.attempts
  }
  if (Array.isArray(results.variants) && results.variants.length > 0) {
    return [
      {
        id: "legacy",
        finished_at: null,
        seed: results.seed,
        engine: results.engine,
        error: results.error,
        variants: results.variants,
      },
    ]
  }
  if (
    results.posts != null ||
    results.comments != null ||
    results.agents != null ||
    results.error
  ) {
    return [
      {
        id: "legacy",
        finished_at: null,
        seed: results.seed,
        engine: results.engine,
        error: results.error,
        variants: [
          {
            id: "main",
            label: t("runs.results.mainTimeline"),
            error: results.error,
            ticks_run: results.ticks_run,
            agents: results.agents ?? [],
            posts: results.posts ?? [],
            comments: results.comments ?? [],
            artifact_db: results.artifact_db,
          },
        ],
      },
    ]
  }
  return []
}

function formatWhen(
  iso: string | null | undefined,
  t: Translate,
  intl: string,
): string {
  if (!iso) return t("runs.results.unknownTime")
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(intl, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d)
}

function formatAttemptDay(
  iso: string | null | undefined,
  t: Translate,
  intl: string,
): string {
  if (!iso) return t("runs.results.unknownTime")
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(intl, {
    day: "numeric",
    month: "short",
  }).format(d)
}

function latestPointMetrics(variant: OasisVariantResult) {
  const rows = variant.measurements ?? []
  for (let i = rows.length - 1; i >= 0; i--) {
    const points = rows[i]?.points ?? []
    const snapshot =
      points.find((p) => p.id === "opinion_snapshot") ?? points[0]
    if (snapshot?.metrics) return snapshot.metrics
  }
  return undefined
}

function agentLabel(
  agents: NonNullable<OasisVariantResult["agents"]>,
  userId: number,
  t: Translate,
): string {
  return (
    agents.find((a) => a.index === userId)?.member_name ??
    t("runs.feed.agentFallback", { userId })
  )
}

function agentProfileTarget(
  agents: NonNullable<OasisVariantResult["agents"]>,
  userId: number,
  t: Translate,
): ProfileTarget {
  const agent = agents.find((a) => a.index === userId)
  return {
    personaId: agent?.persona_id ?? null,
    name: agent?.member_name ?? t("runs.feed.agentFallback", { userId }),
  }
}

function AgentAvatar({
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

function AgentNameButton({
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

function FeedAuthorHeader({
  name,
  showAvatar,
  meta,
  onOpen,
  size = "md",
}: {
  name: string
  showAvatar: boolean
  meta?: ReactNode
  onOpen: () => void
  size?: "xs" | "sm" | "md"
}) {
  return (
    <div className="flex items-start gap-2.5">
      {showAvatar ? <AgentAvatar name={name} size={size} /> : null}
      <div className="min-w-0 leading-tight">
        <button
          type="button"
          className="font-semibold text-foreground underline-offset-2 hover:underline"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onOpen()
          }}
        >
          {name}
        </button>
        {meta ? (
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            {meta}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function formatFeedWhen(
  iso: string | number | null | undefined,
  t: Translate,
  intl: string,
): string | null {
  if (iso == null || iso === "") return null
  if (typeof iso === "number" || (/^\d+(\.\d+)?$/.test(String(iso)) && !String(iso).includes("-"))) {
    return t("runs.feed.simTime", { value: iso })
  }
  const d = new Date(String(iso))
  if (Number.isNaN(d.getTime())) return String(iso)
  return new Intl.DateTimeFormat(intl, {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d)
}

function agentIsInjector(
  agents: NonNullable<OasisVariantResult["agents"]>,
  userId: number,
): boolean {
  return agents.find((a) => a.index === userId)?.role === "injector"
}

function pct(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`
}

function MeasurementDetail({ point }: { point: OasisMeasurementPoint }) {
  const { t } = useLocale()
  const metrics = point.metrics
  const engagement = metrics?.engagement
  const sentiment = metrics?.sentiment
  const phrases = metrics?.top_phrases ?? []
  const districts = metrics?.by_district ?? []
  const follows = metrics?.follows
  const maxDistrictEng = Math.max(
    1,
    ...districts.map((d) => d.engagement_score ?? 0),
  )

  return (
    <div className="space-y-3 text-sm">
      {engagement ? (
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>{t("runs.results.metricPosts", { count: engagement.posts ?? 0 })}</span>
          <span>
            {t("runs.results.metricComments", {
              count: engagement.comments ?? 0,
            })}
          </span>
          <span>{t("runs.results.metricLikes", { count: engagement.likes ?? 0 })}</span>
          <span>
            {t("runs.results.metricDislikes", {
              count: engagement.dislikes ?? 0,
            })}
          </span>
          <span>{t("runs.results.metricShares", { count: engagement.shares ?? 0 })}</span>
          <span>
            {t("runs.results.metricEngagement", {
              score: engagement.engagement_score ?? 0,
            })}
          </span>
          {typeof follows?.edges === "number" ? (
            <span>{t("runs.results.metricFollows", { count: follows.edges })}</span>
          ) : null}
          {typeof metrics?.engagement_delta === "number" ? (
            <span>
              Δ {metrics.engagement_delta >= 0 ? "+" : ""}
              {metrics.engagement_delta}
            </span>
          ) : null}
        </div>
      ) : null}

      {sentiment ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("runs.results.sentiment")}
          </div>
          <div className="flex h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="bg-[var(--db-success)]"
              style={{ width: pct(sentiment.positive) }}
              title={t("runs.results.sentimentPositive", {
                pct: pct(sentiment.positive),
              })}
            />
            <div
              className="bg-[var(--db-ink-200)]"
              style={{ width: pct(sentiment.neutral) }}
              title={t("runs.results.sentimentNeutral", {
                pct: pct(sentiment.neutral),
              })}
            />
            <div
              className="bg-[var(--db-error)]"
              style={{ width: pct(sentiment.negative) }}
              title={t("runs.results.sentimentNegative", {
                pct: pct(sentiment.negative),
              })}
            />
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
            <span>
              {t("runs.results.sentimentShort", {
                positive: pct(sentiment.positive),
                neutral: pct(sentiment.neutral),
                negative: pct(sentiment.negative),
              })}
            </span>
          </div>
        </div>
      ) : null}

      {phrases.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("runs.results.topPhrases")}
          </div>
          <ul className="flex flex-wrap gap-1.5">
            {phrases.map((p) => (
              <li
                key={p.phrase}
                className="rounded border border-border bg-muted/40 px-2 py-0.5 text-xs"
              >
                «{p.phrase}» <span className="text-muted-foreground">×{p.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {districts.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("runs.results.engagementByDistrict")}
          </div>
          <ul className="space-y-1.5">
            {districts.slice(0, 8).map((d) => (
              <li key={d.label} className="grid grid-cols-[7rem_1fr_auto] items-center gap-2">
                <span className="truncate text-xs text-foreground">{d.label}</span>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-[var(--db-gold-500)]"
                    style={{
                      width: `${Math.round(
                        ((d.engagement_score ?? 0) / maxDistrictEng) * 100,
                      )}%`,
                    }}
                  />
                </div>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {d.engagement_score ?? 0}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {follows?.top_followees && follows.top_followees.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("runs.results.mostFollowed")}
          </div>
          <ul className="flex flex-wrap gap-1.5">
            {follows.top_followees.map((f) => (
              <li
                key={f.user_id}
                className="rounded border border-border bg-muted/40 px-2 py-0.5 text-xs"
              >
                #{f.user_id}{" "}
                <span className="text-muted-foreground">×{f.followers}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function VariantOverview({ variant }: { variant: OasisVariantResult }) {
  const { t } = useLocale()
  const metrics = latestPointMetrics(variant)
  const sentiment = metrics?.sentiment
  const phrases = metrics?.top_phrases ?? []
  const districts = metrics?.by_district ?? []
  const maxDistrict = Math.max(
    1,
    ...districts.map((d) => d.engagement_score ?? 0),
  )
  if (!sentiment && phrases.length === 0 && districts.length === 0) return null

  return (
    <div className="results-overview">
      {sentiment ? (
        <div>
          <div className="results-overview-lbl">{t("runs.results.networkTitle")}</div>
          <div className="results-sentiment-bar">
            <div className="pos" style={{ width: pct(sentiment.positive) }} />
            <div className="neu" style={{ width: pct(sentiment.neutral) }} />
            <div className="neg" style={{ width: pct(sentiment.negative) }} />
          </div>
          <div className="results-sentiment-legend">
            <span>
              {t("runs.results.sentimentPositive", {
                pct: pct(sentiment.positive),
              })}
            </span>
            <span>
              {t("runs.results.sentimentNeutral", {
                pct: pct(sentiment.neutral),
              })}
            </span>
            <span>
              {t("runs.results.sentimentNegative", {
                pct: pct(sentiment.negative),
              })}
            </span>
          </div>
        </div>
      ) : null}
      {phrases.length > 0 || districts.length > 0 ? (
        <div className="results-overview-split">
          {phrases.length > 0 ? (
            <div>
              <div className="results-overview-lbl">
                {t("runs.results.commonPhrases")}
              </div>
              <div className="results-phrase-chips">
                {phrases.map((p) => (
                  <span key={p.phrase}>
                    «{p.phrase}» ×{p.count}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {districts.length > 0 ? (
            <div>
              <div className="results-overview-lbl">
                {t("runs.results.topicDrift")}
              </div>
              {districts.slice(0, 6).map((d) => {
                const share = Math.round(
                  ((d.engagement_score ?? 0) / maxDistrict) * 100,
                )
                return (
                  <div className="results-drift-row" key={d.label}>
                    <span className="lbl">{d.label}</span>
                    <div className="bar">
                      <div style={{ width: `${share}%` }} />
                    </div>
                    <span className="pct">{share}%</span>
                  </div>
                )
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function QualityWarningsBanner({ data }: { data: QualityWarnings }) {
  const { locale, t } = useLocale()
  const warnings = data.warnings ?? []
  if (warnings.length === 0) return null

  const thresholdPct = Math.round(data.threshold * 100)

  return (
    <section
      className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2.5"
      aria-label={t("runs.results.qualityAria")}
    >
      <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-100">
        {t("runs.results.qualityTitle")}
      </h3>
      <p className="mt-1 text-xs text-amber-900/80 dark:text-amber-100/80">
        {t("runs.results.qualitySummary", {
          count: warnings.length,
          suffix: warnings.length === 1 ? "" : locale === "sv" ? "er" : "s",
          threshold: thresholdPct,
          agents: data.population_agents,
        })}
      </p>
      <ul className="mt-2 space-y-1.5">
        {warnings.slice(0, 8).map((w) => (
          <li
            key={`${w.kind}-${w.source ?? ""}-${w.phrase}`}
            className="text-xs text-amber-950 dark:text-amber-50"
          >
            <span className="font-medium">«{w.phrase}»</span>
            <span className="text-amber-900/70 dark:text-amber-100/70">
              {" "}
              — {w.agent_count}/{data.population_agents} agenter (
              {Math.round(w.agent_share * 100)}%)
              {" · "}
              {w.kind === "source_phrase_echo"
                ? t("runs.results.qualityEcho")
                : t("runs.results.qualityCommon")}
              {w.source ? ` (${w.source})` : ""}
            </span>
          </li>
        ))}
      </ul>
      {warnings.length > 8 ? (
        <p className="mt-1.5 text-[11px] text-amber-900/70 dark:text-amber-100/70">
          {t("runs.results.qualityMore", { count: warnings.length - 8 })}
        </p>
      ) : null}
    </section>
  )
}

function warningPhraseSet(data: QualityWarnings | undefined): Set<string> {
  return new Set((data?.warnings ?? []).map((w) => w.phrase))
}

function isStimulusControlPair(
  variants: OasisVariantResult[],
  branchMode: BranchMode | null | undefined,
): boolean {
  if (branchMode === "stimulus_control") return true
  const a = variants.find((v) => v.id === "a")
  const b = variants.find((v) => v.id === "b")
  return (
    a?.label === STIMULUS_VARIANT_LABEL && b?.label === CONTROL_VARIANT_LABEL
  )
}

function StimulusControlComparison({
  stimulus,
  control,
}: {
  stimulus: OasisVariantResult
  control: OasisVariantResult
}) {
  const { t } = useLocale()
  const sw = stimulus.quality_warnings
  const cw = control.quality_warnings
  const sCount = sw?.warnings.length ?? 0
  const cCount = cw?.warnings.length ?? 0
  const delta = sCount - cCount
  const controlPhrases = warningPhraseSet(cw)
  const stimulusOnly = (sw?.warnings ?? []).filter(
    (w) => !controlPhrases.has(w.phrase),
  )

  return (
    <section
      className="mb-4 rounded-md border border-sky-500/35 bg-sky-500/10 px-3 py-2.5"
      aria-label={t("runs.results.stimulusTitle")}
    >
      <h3 className="text-sm font-semibold text-sky-950 dark:text-sky-50">
        {t("runs.results.stimulusTitle")}
      </h3>
      <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
        {t("runs.results.stimulusSummary", { sCount, cCount })}
      </p>
      {delta > 0 ? (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          {t("runs.results.stimulusIncreases", { delta })}
        </p>
      ) : delta < 0 ? (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          {t("runs.results.stimulusControlHigher")}
        </p>
      ) : sCount > 0 ? (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          {t("runs.results.stimulusEqual")}
        </p>
      ) : (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          {t("runs.results.stimulusNone")}
        </p>
      )}
      {stimulusOnly.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {stimulusOnly.slice(0, 6).map((w) => (
            <li
              key={`stimulus-only-${w.kind}-${w.phrase}`}
              className="text-xs text-sky-950 dark:text-sky-50"
            >
              <span className="font-medium">«{w.phrase}»</span>
              <span className="text-sky-900/70 dark:text-sky-100/70">
                {" "}
                — {t("runs.results.stimulusOnly", { count: w.agent_count })}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function MeasurementPointBlock({ point }: { point: OasisMeasurementPoint }) {
  return (
    <div className="rounded-md border border-border/80 bg-muted/15 px-3 py-3">
      <div className="text-sm font-medium text-foreground">{point.label}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{point.summary}</div>
      <div className="mt-3 border-t border-border/50 pt-3">
        <MeasurementDetail point={point} />
      </div>
    </div>
  )
}

function ActorList({
  agents,
  userIds,
  emptyLabel,
  onOpenAgent,
}: {
  agents: NonNullable<OasisVariantResult["agents"]>
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

function LikeShareBar({
  agents,
  likedBy,
  dislikedBy,
  sharedBy,
  compact = false,
  onOpenAgent,
}: {
  agents: NonNullable<OasisVariantResult["agents"]>
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

function OrderReportButton({
  busy,
  disabled,
  label,
  compareCount,
  onClick,
  prominent = false,
}: {
  busy?: boolean
  disabled?: boolean
  label: string
  compareCount?: number
  onClick: () => void
  prominent?: boolean
}) {
  const { t } = useLocale()
  const title = busy ? t("runs.results.reportGenerating") : label

  return (
    <button
      type="button"
      className={
        prominent
          ? "inline-grid h-8 w-8 place-items-center rounded-md border border-db-gold-600 bg-db-gold-100 text-db-gold-800 hover:bg-db-gold-200 disabled:cursor-not-allowed disabled:opacity-40"
          : "inline-grid h-7 w-7 place-items-center rounded text-db-gold-700 hover:bg-db-gold-100 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
      }
      disabled={disabled || busy}
      title={title}
      aria-label={title}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onClick()
      }}
    >
      {busy ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
      ) : compareCount != null && compareCount > 1 ? (
        <Files className="size-3.5" aria-hidden />
      ) : (
        <FileText className="size-3.5" aria-hidden />
      )}
    </button>
  )
}

function AdminModal({
  open,
  titleId,
  title,
  description,
  children,
  onClose,
  wide = false,
}: {
  open: boolean
  titleId: string
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  const overlayMouseDownRef = useRef(false)

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="theme-admin fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose()
        }
        overlayMouseDownRef.current = false
      }}
    >
      <div
        className={
          "w-full rounded-lg border border-[color:var(--border-hairline)] bg-db-ink-0 shadow-xl " +
          (wide ? "max-w-2xl" : "max-w-md")
        }
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-[color:var(--border-hairline)] px-5 py-4">
          <h2 id={titleId} className="text-base font-medium text-foreground">
            {title}
          </h2>
          {description ? (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

function variantHasNetworkActivity(variant: OasisVariantResult): boolean {
  const histogram = (variant.action_histogram ?? []).filter(
    (row) => !HIDDEN_ACTIONS.has(row.action),
  )
  return (
    (variant.follows?.length ?? 0) > 0 ||
    (variant.mutes?.length ?? 0) > 0 ||
    (variant.reports?.length ?? 0) > 0 ||
    (variant.agent_tools?.length ?? 0) > 0 ||
    histogram.length > 0
  )
}

function NetworkActivityIconButton({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="inline-grid h-7 w-7 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
      title={label}
      aria-label={label}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onClick()
      }}
    >
      <Network className="size-3.5" aria-hidden />
    </button>
  )
}

function AgentToolsIconButton({
  label,
  onClick,
}: {
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="inline-grid h-7 w-7 place-items-center rounded text-[var(--db-gold-700)] hover:bg-muted hover:text-foreground"
      title={label}
      aria-label={label}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onClick()
      }}
    >
      <Wrench className="size-3.5" aria-hidden />
    </button>
  )
}

function AgentToolsModalContent({ tools }: { tools: AgentToolRow[] }) {
  const { t } = useLocale()
  return (
    <ul className="flex max-h-[min(28rem,70vh)] flex-col gap-3 overflow-y-auto">
      {tools.map((row, i) => {
        const desc = describeAgentTool(row, t)
        const query = argPreview(row.args) ?? desc.detail
        const result = row.result_preview?.trim() || null
        return (
          <li
            key={`${row.tool_name}-${row.sequence ?? i}-${row.tick_index}`}
            className="rounded-md border border-border/70 bg-muted/20 px-3 py-2.5"
          >
            <div className="text-xs font-semibold text-foreground">
              {desc.label}
              <span className="ml-2 font-normal text-muted-foreground">
                {row.tool_name}
              </span>
            </div>
            {query ? (
              <div className="mt-2">
                <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("runs.feed.toolsQuery")}
                </div>
                <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
                  {query}
                </p>
              </div>
            ) : null}
            <div className="mt-2">
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("runs.feed.toolsResult")}
              </div>
              <p className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                {result ?? t("runs.feed.toolsEmptyResult")}
              </p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function NetworkActivityContent({
  variant,
  onOpenAgent,
}: {
  variant: OasisVariantResult
  onOpenAgent: (userId: number) => void
}) {
  const { t } = useLocale()
  const agents = variant.agents ?? []
  const follows = variant.follows ?? []
  const mutes = variant.mutes ?? []
  const reports = variant.reports ?? []
  const histogram = (variant.action_histogram ?? []).filter(
    (row) => !HIDDEN_ACTIONS.has(row.action),
  )
  const toolHistogram = agentToolHistogram(variant.agent_tools)

  return (
    <div className="space-y-3">
      {follows.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {t("runs.results.networkFollows", { count: follows.length })}
          </div>
          <ul className="max-h-48 space-y-1 overflow-y-auto text-xs text-muted-foreground">
            {follows.slice(0, 40).map((f, i) => (
              <li key={`${f.follower_id}-${f.followee_id}-${i}`}>
                <AgentNameButton
                  name={agentLabel(agents, f.follower_id, t)}
                  className="text-xs text-muted-foreground"
                  showAvatar={!agentIsInjector(agents, f.follower_id)}
                  onOpen={() => onOpenAgent(f.follower_id)}
                />
                {" → "}
                <AgentNameButton
                  name={agentLabel(agents, f.followee_id, t)}
                  className="text-xs text-muted-foreground"
                  showAvatar={!agentIsInjector(agents, f.followee_id)}
                  onOpen={() => onOpenAgent(f.followee_id)}
                />
              </li>
            ))}
            {follows.length > 40 ? (
              <li className="text-muted-foreground/80">
                {t("runs.results.networkMore", { count: follows.length - 40 })}
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}

      {mutes.length > 0 || reports.length > 0 ? (
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          {mutes.length > 0 ? (
            <span>{t("runs.results.networkMutes", { count: mutes.length })}</span>
          ) : null}
          {reports.length > 0 ? (
            <span>{t("runs.results.networkReports", { count: reports.length })}</span>
          ) : null}
        </div>
      ) : null}

      {toolHistogram.length > 0 ? (
        <div>
          <div className="mb-2 text-xs font-medium text-muted-foreground">
            {t("runs.results.networkAgentTools")}
          </div>
          <ActionHistogramChart
            rows={toolHistogram.map((row) => ({
              action: describeAgentTool(
                {
                  user_id: 0,
                  tick_index: 0,
                  tool_name: row.tool_name,
                },
                t,
              ).label,
              count: row.count,
            }))}
          />
        </div>
      ) : null}

      {histogram.length > 0 ? (
        <div>
          <div className="mb-2 text-xs font-medium text-muted-foreground">
            {t("runs.results.networkTrace")}
          </div>
          <ActionHistogramChart rows={histogram} />
        </div>
      ) : null}
    </div>
  )
}

function ActionHistogramChart({
  rows,
}: {
  rows: Array<{ action: string; count: number }>
}) {
  const { t } = useLocale()
  const top = rows.slice(0, 12)
  const max = Math.max(1, ...top.map((row) => row.count))

  return (
    <div
      className="flex h-36 items-end gap-1 border-b border-border/60 pb-1 pt-2"
      role="img"
      aria-label={t("runs.results.networkChartAria")}
    >
      {top.map((row) => {
        const heightPct = Math.round((row.count / max) * 100)
        return (
          <div
            key={row.action}
            className="flex min-w-0 flex-1 flex-col items-center gap-1"
            title={`${row.action}: ${row.count}`}
          >
            <span className="text-[10px] tabular-nums leading-none text-muted-foreground">
              {row.count}
            </span>
            <div className="flex h-24 w-full items-end">
              <div
                className="w-full rounded-t bg-[var(--db-gold-500)] transition-[height]"
                style={{
                  height: `${heightPct}%`,
                  minHeight: row.count > 0 ? "3px" : 0,
                }}
              />
            </div>
            <span
              className="w-full truncate text-center font-mono text-[9px] leading-tight text-muted-foreground"
              title={row.action}
            >
              {row.action}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function CompactActionRow({
  item,
  agents,
  onOpenAgent,
}: {
  item: TimelineActionItem
  agents: NonNullable<OasisVariantResult["agents"]>
  onOpenAgent: (userId: number) => void
}) {
  const { intl, t } = useLocale()
  const when = formatFeedWhen(item.createdAt, t, intl)
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-dashed border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <AgentNameButton
        name={agentLabel(agents, item.userId, t)}
        className="text-xs font-medium text-foreground"
        showAvatar={!agentIsInjector(agents, item.userId)}
        onOpen={() => onOpenAgent(item.userId)}
      />
      <span>{item.label}</span>
      {item.targetUserId != null ? (
        <AgentNameButton
          name={item.detail ?? agentLabel(agents, item.targetUserId, t)}
          className="text-xs text-muted-foreground"
          showAvatar={!agentIsInjector(agents, item.targetUserId)}
          onOpen={() => onOpenAgent(item.targetUserId!)}
        />
      ) : item.detail ? (
        <span className="text-foreground/80">{item.detail}</span>
      ) : null}
      {when ? (
        <span className="ml-auto tabular-nums text-[10px] text-muted-foreground/80">
          {when}
        </span>
      ) : null}
    </li>
  )
}

function DayEventsIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 6h13" />
      <path d="M8 12h13" />
      <path d="M8 18h13" />
      <path d="M3 6h.01" />
      <path d="M3 12h.01" />
      <path d="M3 18h.01" />
    </svg>
  )
}

function OpinionMeasurementIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 20V10" />
      <path d="M12 20V4" />
      <path d="M18 20v-6" />
    </svg>
  )
}

function TickMarkerCard({
  tick,
  expanded,
  onToggle,
  eventsEnabled,
  onOpenEvents,
  measurementEnabled,
  onOpenMeasurements,
  interviewEnabled,
  onInterview,
  children,
}: {
  tick: {
    day: number
    silent: boolean
    rounds: number
    timeStart: number
    timeEnd: number
    tickIndex: number
  }
  expanded: boolean
  onToggle: () => void
  eventsEnabled: boolean
  onOpenEvents: () => void
  measurementEnabled: boolean
  onOpenMeasurements: () => void
  interviewEnabled: boolean
  onInterview: () => void
  children?: ReactNode
}) {
  const { t } = useLocale()
  const empty = tick.timeEnd < tick.timeStart
  return (
    <li className="list-none">
      <div className="rounded-md border border-border bg-muted/30">
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
          <span className="font-semibold text-foreground">
            {t("runs.results.dayLabel", { day: tick.day })}
          </span>
          {tick.silent ? (
            <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              {t("runs.results.silentTick")}
            </span>
          ) : (
            <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              {t("runs.results.tickWord")}
            </span>
          )}
          <span className="text-muted-foreground">
            {t("runs.results.rounds", { count: tick.rounds })}
          </span>
          <span className="ml-auto flex items-center gap-2 tabular-nums text-[10px] text-muted-foreground/80">
            <span>
              {empty
                ? t("runs.results.noNewEvents")
                : `t=${tick.timeStart}–${tick.timeEnd}`}
            </span>
            {eventsEnabled ? (
              <button
                type="button"
                className="inline-grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                title={t("runs.results.eventsForDay", { day: tick.day })}
                aria-label={t("runs.results.eventsForDay", { day: tick.day })}
                onClick={onOpenEvents}
              >
                <DayEventsIcon />
              </button>
            ) : null}
            {measurementEnabled ? (
              <button
                type="button"
                className="inline-grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                title={t("runs.results.measurementsForDay", { day: tick.day })}
                aria-label={t("runs.results.measurementsForDay", {
                  day: tick.day,
                })}
                onClick={onOpenMeasurements}
              >
                <OpinionMeasurementIcon />
              </button>
            ) : null}
            {interviewEnabled ? (
              <button
                type="button"
                className="inline-grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                title={t("runs.results.interviewAfterDay", { day: tick.day })}
                aria-label={t("runs.results.interviewAfterDay", {
                  day: tick.day,
                })}
                onClick={onInterview}
              >
                <svg
                  aria-hidden="true"
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </button>
            ) : null}
            <button
              type="button"
              className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted/60"
              aria-expanded={expanded}
              aria-label={
                expanded
                  ? t("runs.results.closeDay", { day: tick.day })
                  : t("runs.results.expandDay", { day: tick.day })
              }
              onClick={onToggle}
            >
              {expanded ? t("runs.results.hide") : t("runs.results.show")}
            </button>
          </span>
        </div>
        {expanded && children ? (
          <div className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
            {children}
          </div>
        ) : null}
      </div>
    </li>
  )
}

function PlannedOasisInterviews({ variant }: { variant: OasisVariantResult }) {
  const { t } = useLocale()
  const agents = variant.agents ?? []
  const markers = variant.tick_markers ?? []
  const interviews = useMemo(() => {
    const rows: Array<{
      key: string
      tickIndex: number
      day: number
      agentName: string
      prompt: string
      response: string
    }> = []
    for (const row of variant.trace ?? []) {
      if ((row.action || "").toLowerCase() !== "interview") continue
      const info = parseTraceInfo(row.info)
      const prompt = typeof info.prompt === "string" ? info.prompt : ""
      const response = typeof info.response === "string" ? info.response : ""
      const sortTime = sortKeyFromCreatedAt(row.created_at)
      let tickIndex = 0
      let day = 1
      for (const m of markers) {
        if (m.time_start <= sortTime && sortTime <= m.time_end) {
          tickIndex = m.tick_index
          day = m.day
          break
        }
        if (sortTime > m.time_end) {
          tickIndex = m.tick_index
          day = m.day
        }
      }
      rows.push({
        key: `${row.user_id}-${row.created_at}-${prompt.slice(0, 12)}`,
        tickIndex,
        day,
        agentName: agentLabel(agents, row.user_id, t),
        prompt,
        response,
      })
    }
    return rows
  }, [variant.trace, agents, markers, t])

  if (interviews.length === 0) return null

  return (
    <section className="mb-4 rounded-md border border-[color:var(--border-hairline)] p-4">
      <h3 className="mb-1 text-sm font-medium text-foreground">
        {t("runs.results.plannedInterviews")}
      </h3>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("runs.results.plannedInterviewsDesc")}
      </p>
      <ul className="flex flex-col gap-3">
        {interviews.map((iv) => (
          <li
            key={iv.key}
            className="rounded border border-[color:var(--border-hairline)] px-3 py-2 text-sm"
          >
            <div className="mb-1 text-xs text-muted-foreground">
              {t("runs.results.plannedInterviewMeta", {
                agentName: iv.agentName,
                day: iv.day,
                tick: iv.tickIndex + 1,
              })}
            </div>
            <p className="text-foreground">
              <span className="text-muted-foreground">
                {t("runs.results.questionLabel")}{" "}
              </span>
              {iv.prompt || "—"}
            </p>
            <p className="mt-1 text-muted-foreground">
              <span className="text-foreground/80">
                {t("runs.results.answerLabel")}{" "}
              </span>
              {iv.response || "—"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function FeedPostCard({
  post,
  tickIndex,
  agents,
  postsById,
  commentsByPostId,
  agentTools,
  tickMarkers,
  mentionMatcher,
  openMention,
  openAgent,
  openAgentRow,
  runId,
  attemptId,
  onInterview,
  compact = false,
  anchors,
}: {
  post: PostRow
  tickIndex: number
  agents: NonNullable<OasisVariantResult["agents"]>
  postsById: Map<number, PostRow>
  commentsByPostId: Map<number, NonNullable<OasisVariantResult["comments"]>>
  agentTools: AgentToolRow[]
  tickMarkers: TickMarker[]
  mentionMatcher: ReturnType<typeof getMentionMatcher>
  openMention: (userIds: number[], label: string) => void
  openAgent: (userId: number) => void
  openAgentRow: (agent: AgentRow | undefined, fallbackName: string) => void
  runId?: number
  attemptId?: string
  onInterview: (tickIndex: number, personaId: string) => void
  compact?: boolean
  anchors?: FeedAnchors
}) {
  const { intl, t } = useLocale()
  const [toolsModal, setToolsModal] = useState<{
    kind: "post" | "comment"
    authorName: string
    tools: AgentToolRow[]
  } | null>(null)
  const agent = agents.find((a) => a.index === post.user_id)
  const author = agent?.member_name ?? t("runs.feed.agentFallback", { userId: post.user_id })
  const isInjector = agent?.role === "injector"
  const originalId = post.original_post_id ?? null
  const original = originalId != null ? postsById.get(originalId) : undefined
  const originalAuthor =
    original != null ? agentLabel(agents, original.user_id, t) : null
  const quote = (post.quote_content ?? "").trim()
  const isQuote = originalId != null && quote.length > 0
  const isRepost = originalId != null && quote.length === 0
  const postComments = commentsByPostId.get(post.post_id) ?? []
  const when = formatFeedWhen(post.created_at, t, intl)
  const postTools = agentToolsForAuthor(agentTools, post.user_id, tickIndex)

  let kindLabel: string | null = null
  if (isInjector) kindLabel = t("runs.feed.injection")
  else if (isQuote) kindLabel = t("runs.feed.quote")
  else if (isRepost) kindLabel = t("runs.feed.share")

  const postBody = postBodyTextForCopy(post, t, {
    isQuote,
    isRepost,
    quote,
    originalAuthor,
    originalId,
  })
  const postCopyText = formatPostForClipboard(
    author,
    postBody,
    postComments.map((c) => ({
        author: agentLabel(agents, c.user_id, t),
      content: c.content,
    })),
  )
  const canInterviewPost =
    runId != null &&
    Boolean(attemptId) &&
    !isInjector &&
    Boolean(agent?.persona_id)

  const postTopicStatus =
    !isInjector && anchors ? anchors.byPostId.get(post.post_id) ?? null : null

  return (
    <li
      className={
        "list-none rounded-lg border border-border bg-card shadow-sm " +
        (compact ? "px-3 py-2.5" : "px-4 py-3") +
        topicBorderClass(postTopicStatus)
      }
    >
      <div className="flex items-start justify-between gap-2">
        <FeedAuthorHeader
          name={author}
          showAvatar={!isInjector}
          size={compact ? "sm" : "md"}
          onOpen={() => openAgentRow(agent, author)}
          meta={
            <>
              {when ? <span>{when}</span> : null}
              {kindLabel ? (
                <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                  {kindLabel}
                </span>
              ) : null}
              {postTools.length > 0 ? (
                <span className="rounded border border-[color:var(--db-gold-500)]/40 bg-[color:var(--db-gold-100)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[color:var(--db-gold-700)]">
                  {t("runs.feed.toolsUsed")}
                </span>
              ) : null}
              <span className="text-muted-foreground/80">#{post.post_id}</span>
            </>
          }
        />
        <div className="flex shrink-0 items-center gap-1">
          {postTools.length > 0 ? (
            <AgentToolsIconButton
              label={t("runs.feed.toolsUsedAria")}
              onClick={() =>
                setToolsModal({
                  kind: "post",
                  authorName: author,
                  tools: postTools,
                })
              }
            />
          ) : null}
          {canInterviewPost ? (
            <button
              type="button"
              className="inline-grid h-7 w-7 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
              title={t("runs.feed.interviewAgent", { name: author })}
              aria-label={t("runs.feed.interviewAgent", { name: author })}
              onClick={() => onInterview(tickIndex, agent!.persona_id!)}
            >
              <InterviewIcon />
            </button>
          ) : null}
          <CopyFeedTextButton text={postCopyText} label={t("runs.feed.copyPost")} />
        </div>
      </div>

      <div className="mt-2.5">
        {isQuote ? (
          <div className="space-y-2">
            <CommentBody
              text={quote}
              matcher={mentionMatcher}
              onOpenMention={openMention}
              className="whitespace-pre-wrap text-sm leading-relaxed text-foreground"
            />
            <p className="text-xs text-muted-foreground">
              {t("runs.feed.quotePrefix", {
                author: originalAuthor ?? t("runs.feed.unknown"),
                postId: originalId ?? "?",
              })}
            </p>
          </div>
        ) : null}

        {isRepost ? (
          <p className="text-sm text-muted-foreground">
            {t("runs.feed.repostPrefix", {
              author: originalAuthor ?? t("runs.feed.unknown"),
              postId: originalId ?? "?",
            })}
          </p>
        ) : null}

        {!isQuote && !isRepost ? (
          <CommentBody
            text={post.content}
            matcher={mentionMatcher}
            onOpenMention={openMention}
            className="whitespace-pre-wrap text-sm leading-relaxed text-foreground"
          />
        ) : null}
      </div>

      <LikeShareBar
        agents={agents}
        likedBy={post.liked_by}
        dislikedBy={post.disliked_by}
        sharedBy={post.shared_by}
        onOpenAgent={openAgent}
      />

      {postComments.length > 0 ? (
        <ul className="mt-3 space-y-3 border-t border-border/60 pt-3">
          {postComments.map((c) => {
            const commentAgent = agents.find((a) => a.index === c.user_id)
            const commentName = agentLabel(agents, c.user_id, t)
            const commentInjector = agentIsInjector(agents, c.user_id)
            const commentTick = tickIndexForCreatedAt(
              c.created_at,
              tickMarkers,
              tickIndex,
            )
            const commentTools = agentToolsForAuthor(
              agentTools,
              c.user_id,
              commentTick,
            )
            const canInterviewComment =
              runId != null &&
              Boolean(attemptId) &&
              !commentInjector &&
              Boolean(commentAgent?.persona_id)
            const taggable = anchors?.byCommentId.get(c.comment_id)
            const hasClassification = Boolean(
              taggable?.tone_predicted ||
                taggable?.style_predicted ||
                taggable?.topic_status,
            )
            const alreadyFlagged = taggable
              ? anchors!.flaggedKeys.has(flaggedKeyForRow(taggable))
              : false
            return (
              <li key={c.comment_id} className="flex items-start gap-1.5">
                {commentInjector ? null : (
                  <AgentAvatar name={commentName} size="sm" />
                )}
                <div
                  className={
                    "min-w-0 flex-1 rounded-2xl bg-muted/50 px-3 py-2" +
                    topicBorderClass(taggable?.topic_status)
                  }
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      type="button"
                      className="text-xs font-semibold text-foreground underline-offset-2 hover:underline"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        openAgent(c.user_id)
                      }}
                    >
                      {commentName}
                    </button>
                    {commentTools.length > 0 ? (
                      <span className="rounded border border-[color:var(--db-gold-500)]/40 bg-[color:var(--db-gold-100)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[color:var(--db-gold-700)]">
                        {t("runs.feed.toolsUsed")}
                      </span>
                    ) : null}
                  </div>
                  <CommentBody
                    text={c.content}
                    matcher={mentionMatcher}
                    onOpenMention={openMention}
                    className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed text-foreground"
                  />
                  <LikeShareBar
                    agents={agents}
                    likedBy={c.liked_by}
                    dislikedBy={c.disliked_by}
                    compact
                    onOpenAgent={openAgent}
                  />
                </div>
                <div className="flex shrink-0 flex-col items-center gap-1">
                  {commentTools.length > 0 ? (
                    <AgentToolsIconButton
                      label={t("runs.feed.toolsUsedCommentAria")}
                      onClick={() =>
                        setToolsModal({
                          kind: "comment",
                          authorName: commentName,
                          tools: commentTools,
                        })
                      }
                    />
                  ) : null}
                  {taggable && hasClassification && anchors ? (
                    <ClassificationPopover
                      row={taggable}
                      runId={anchors.runId}
                      attemptId={anchors.attemptId}
                      variantId={anchors.variantId}
                      toneOptions={anchors.toneOptions}
                      styleOptions={anchors.styleOptions}
                      reported={alreadyFlagged}
                      onReported={() =>
                        anchors.onFlagged(flaggedKeyForRow(taggable))
                      }
                    />
                  ) : null}
                  {taggable && anchors ? (
                    <button
                      type="button"
                      className="results-icon-btn gold"
                      title={t("runs.results.anchorPool.addAsAnchor")}
                      aria-label={t("runs.results.anchorPool.addAsAnchor")}
                      onClick={() =>
                        anchors.onAdd({ row: taggable, author: commentName })
                      }
                    >
                      <ShieldIcon />
                    </button>
                  ) : null}
                  {canInterviewComment ? (
                    <button
                      type="button"
                      className="inline-grid h-7 w-7 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                      title={t("runs.feed.interviewAgent", { name: commentName })}
                      aria-label={t("runs.feed.interviewAgent", {
                        name: commentName,
                      })}
                      onClick={() =>
                        onInterview(commentTick, commentAgent!.persona_id!)
                      }
                    >
                      <InterviewIcon />
                    </button>
                  ) : null}
                  <CopyFeedTextButton
                    text={formatCommentForClipboard(commentName, c.content)}
                    label={t("runs.feed.copyComment")}
                  />
                </div>
              </li>
            )
          })}
        </ul>
      ) : null}

      <AdminModal
        open={toolsModal != null}
        titleId="agent-tools-modal-title"
        title={
          toolsModal?.kind === "comment"
            ? t("runs.feed.toolsModalTitleComment")
            : t("runs.feed.toolsModalTitle")
        }
        description={
          toolsModal
            ? t("runs.feed.toolsModalDescription", {
                name: toolsModal.authorName,
                count: toolsModal.tools.length,
              })
            : undefined
        }
        onClose={() => setToolsModal(null)}
        wide
      >
        {toolsModal ? <AgentToolsModalContent tools={toolsModal.tools} /> : null}
      </AdminModal>
    </li>
  )
}

function VariantBody({
  variant,
  runId,
  attemptId,
  showAnchors = false,
}: {
  variant: OasisVariantResult
  runId?: number
  attemptId?: string
  showAnchors?: boolean
}) {
  const { t } = useLocale()
  const posts = variant.posts ?? []
  const comments = variant.comments ?? []
  const agents = variant.agents ?? []
  const measurements = variant.measurements ?? []
  const qualityWarnings = variant.quality_warnings
  const postsById = useMemo(
    () => new Map(posts.map((p) => [p.post_id, p])),
    [posts],
  )
  const commentsByPostId = useMemo(() => {
    const map = new Map<number, NonNullable<OasisVariantResult["comments"]>>()
    for (const comment of comments) {
      const bucket = map.get(comment.post_id)
      if (bucket) bucket.push(comment)
      else map.set(comment.post_id, [comment])
    }
    return map
  }, [comments])
  const mentionAliases = useMemo(() => buildMentionAliases(agents), [agents])
  const mentionMatcher = useMemo(
    () => getMentionMatcher(mentionAliases),
    [mentionAliases],
  )
  const [profile, setProfile] = useState<ProfileTarget | null>(null)
  const [mentionPick, setMentionPick] = useState<{
    userIds: number[]
    label: string
  } | null>(null)
  const [expandedTickIndex, setExpandedTickIndex] = useState<number | null>(null)
  const [dayEventsModalTick, setDayEventsModalTick] = useState<number | null>(null)
  const [dayMeasurementsModalTick, setDayMeasurementsModalTick] = useState<
    number | null
  >(null)
  const [interviewTarget, setInterviewTarget] = useState<{
    tickIndex: number
    personaId: string | null
  } | null>(null)
  const taggable = useRunTaggableTexts(
    showAnchors ? runId : undefined,
    showAnchors ? attemptId : undefined,
    showAnchors ? variant.id : undefined,
  )
  const [anchorTarget, setAnchorTarget] = useState<AddAnchorTarget | null>(null)
  const [flaggedKeys, setFlaggedKeys] = useState<Set<string>>(() => new Set())
  const feedAnchors: FeedAnchors | undefined =
    showAnchors && runId != null && attemptId
      ? {
          byCommentId: taggable.byCommentId,
          byPostId: taggable.byPostId,
          toneOptions: taggable.context?.tone.labels ?? [],
          styleOptions: taggable.context?.style.labels ?? [],
          flaggedKeys,
          onFlagged: (key) =>
            setFlaggedKeys((prev) => {
              const next = new Set(prev)
              next.add(key)
              return next
            }),
          onAdd: setAnchorTarget,
          runId,
          attemptId,
          variantId: variant.id,
        }
      : undefined

  const openAgent = useCallback(
    (userId: number) => {
      setProfile(agentProfileTarget(agents, userId, t))
    },
    [agents, t],
  )

  const openMention = useCallback(
    (userIds: number[], label: string) => {
      if (userIds.length === 1) {
        openAgent(userIds[0]!)
        return
      }
      setMentionPick({ userIds, label })
    },
    [openAgent],
  )

  function openAgentRow(agent: AgentRow | undefined, fallbackName: string) {
    setProfile({
      personaId: agent?.persona_id ?? null,
      name: agent?.member_name ?? fallbackName,
    })
  }

  const agentName = useCallback(
    (id: number) => agentLabel(agents, id, t),
    [agents, t],
  )

  const timeline = useMemo(
    () => buildTimelineItems(variant, { hideNoise: true, agentName, t }),
    [variant, agentName, t],
  )
  const segments = useMemo(() => groupTimelineSegments(timeline), [timeline])
  const injectors = useMemo(
    () => agents.filter((a) => a.role === "injector"),
    [agents],
  )
  const population = useMemo(
    () => agents.filter((a) => a.role !== "injector"),
    [agents],
  )
  const hasTickMarkers = (variant.tick_markers ?? []).length > 0
  const measurementsByTick = useMemo(() => {
    const map = new Map<number, OasisMeasurementRow>()
    for (const row of measurements) {
      map.set(row.tick_index, row)
    }
    return map
  }, [measurements])
  const postsByTick = useMemo(() => {
    const map = new Map<number, PostRow[]>()
    for (const item of timeline) {
      if (item.kind !== "post") continue
      const bucket = map.get(item.tickIndex)
      if (bucket) bucket.push(item.post)
      else map.set(item.tickIndex, [item.post])
    }
    return map
  }, [timeline])

  const openPostInterview = useCallback(
    (tickIndex: number, personaId: string) => {
      setInterviewTarget({ tickIndex, personaId })
    },
    [],
  )

  const modalDayActions = useMemo(() => {
    if (dayEventsModalTick == null) return []
    return timeline.filter(
      (item): item is TimelineActionItem =>
        item.kind === "action" && item.tickIndex === dayEventsModalTick,
    )
  }, [timeline, dayEventsModalTick])

  const modalDayMeasurements = useMemo(() => {
    if (dayMeasurementsModalTick == null) return []
    return measurementsByTick.get(dayMeasurementsModalTick)?.points ?? []
  }, [dayMeasurementsModalTick, measurementsByTick])

  const tickDayLabel = useCallback(
    (tickIndex: number) => {
      const marker = (variant.tick_markers ?? []).find(
        (m) => m.tick_index === tickIndex,
      )
      return marker?.day ?? tickIndex + 1
    },
    [variant.tick_markers],
  )

  function toggleTickExpand(tickIndex: number) {
    setExpandedTickIndex((prev) => (prev === tickIndex ? null : tickIndex))
  }

  if (variant.error) {
    return (
      <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {variant.error}
      </p>
    )
  }

  const platform =
    variant.platform ??
    variant.oasis_options?.platform ??
    "twitter"

  return (
    <div>
      <VariantOverview variant={variant} />
      <p className="mb-3 text-xs text-muted-foreground">
        {t("runs.results.platform", {
          platform: platform === "reddit" ? "Reddit" : "Twitter",
        })}
      </p>
      {qualityWarnings ? <QualityWarningsBanner data={qualityWarnings} /> : null}
      <PlannedOasisInterviews variant={variant} />
      {agents.length > 0 ? (
        <div className="mb-3 space-y-1 text-sm text-muted-foreground">
          {injectors.length > 0 ? (
            <p>
              {t("runs.results.injectors")}{" "}
              {injectors.map((a, i) => (
                <span key={a.index}>
                  {i > 0 ? ", " : null}
                  <AgentNameButton
                    name={a.member_name || a.username}
                    className="text-sm text-muted-foreground"
                    showAvatar={false}
                    onOpen={() =>
                      openAgentRow(a, a.member_name || a.username)
                    }
                  />
                </span>
              ))}
            </p>
          ) : null}
          <p>
            {t("runs.results.population")}{" "}
            {population.length === 0
              ? t("common.emDash")
              : population.map((a, i) => (
                  <span key={a.index}>
                    {i > 0 ? ", " : null}
                    <AgentNameButton
                      name={a.member_name || a.username}
                      className="text-sm text-muted-foreground"
                      showAvatar={false}
                      onOpen={() =>
                        openAgentRow(a, a.member_name || a.username)
                      }
                    />
                  </span>
                ))}
          </p>
        </div>
      ) : null}
      {runId != null && attemptId && interviewTarget != null ? (
        <RunPersonaInterviewModal
          key={`${interviewTarget.tickIndex}-${interviewTarget.personaId ?? "any"}`}
          open
          onClose={() => setInterviewTarget(null)}
          runId={runId}
          attemptId={attemptId}
          variant={variant}
          tickIndex={interviewTarget.tickIndex}
          initialPersonaId={interviewTarget.personaId}
        />
      ) : null}

      <h3 className="mb-2 text-sm font-semibold text-foreground">
        {t("runs.feed.title")}
      </h3>

      {posts.length === 0 && segments.every((s) => s.kind !== "actions") ? (
        <p className="text-sm text-muted-foreground">
          {t("runs.feed.noPostsSaved")}
        </p>
      ) : null}

      <ul className="flex flex-col gap-3">
        {segments.map((segment) => {
          if (segment.kind === "tick") {
            const tickItem = segment.tick
            const expanded = expandedTickIndex === tickItem.tickIndex
            const dayPosts = postsByTick.get(tickItem.tickIndex) ?? []
            const dayComments = dayPosts.reduce(
              (n, post) => n + (commentsByPostId.get(post.post_id)?.length ?? 0),
              0,
            )
            const dayActionItems = timeline.filter(
              (item): item is TimelineActionItem =>
                item.kind === "action" && item.tickIndex === tickItem.tickIndex,
            )
            const dayInterviews = (variant.trace ?? []).filter((row) => {
              if ((row.action || "").toLowerCase() !== "interview") return false
              const t = sortKeyFromCreatedAt(row.created_at)
              return tickItem.timeStart <= t && t <= tickItem.timeEnd
            }).length
            const dayMeasurements =
              measurementsByTick.get(tickItem.tickIndex)?.points ?? []
            const hasOpinionMeasurement = dayMeasurements.some(
              (point) => point.id === "opinion_snapshot",
            )
            return (
              <TickMarkerCard
                key={segment.key}
                tick={tickItem}
                expanded={expanded}
                onToggle={() => toggleTickExpand(tickItem.tickIndex)}
                eventsEnabled={dayActionItems.length > 0}
                onOpenEvents={() => setDayEventsModalTick(tickItem.tickIndex)}
                measurementEnabled={hasOpinionMeasurement}
                onOpenMeasurements={() =>
                  setDayMeasurementsModalTick(tickItem.tickIndex)
                }
                interviewEnabled={runId != null && Boolean(attemptId)}
                onInterview={() =>
                  setInterviewTarget({
                    tickIndex: tickItem.tickIndex,
                    personaId: null,
                  })
                }
              >
                <p>
                  {t("runs.results.metricPosts", { count: dayPosts.length })}
                  {dayComments > 0
                    ? ` · ${t("runs.results.metricComments", { count: dayComments })}`
                    : ""}
                  {dayActionItems.length > 0
                    ? ` · ${dayActionItems.length} ${t("runs.results.eventsTitle").toLowerCase()}`
                    : ""}
                  {dayInterviews > 0
                    ? ` · ${dayInterviews} OASIS-intervju${dayInterviews === 1 ? "" : "er"}`
                    : ""}
                </p>
                {expanded && dayPosts.length > 0 ? (
                  <ul className="mt-3 flex flex-col gap-2">
                    {dayPosts.map((post) => (
                      <FeedPostCard
                        key={post.post_id}
                        post={post}
                        tickIndex={tickItem.tickIndex}
                        agents={agents}
                        postsById={postsById}
                        commentsByPostId={commentsByPostId}
                        agentTools={variant.agent_tools ?? []}
                        tickMarkers={variant.tick_markers ?? []}
                        mentionMatcher={mentionMatcher}
                        openMention={openMention}
                        openAgent={openAgent}
                        openAgentRow={openAgentRow}
                        runId={runId}
                        attemptId={attemptId}
                        onInterview={openPostInterview}
                        compact
                        anchors={feedAnchors}
                      />
                    ))}
                  </ul>
                ) : expanded && dayPosts.length === 0 ? (
                  <p className="mt-2 text-muted-foreground/80">
                    {t("runs.feed.noPostsToday")}
                  </p>
                ) : null}
              </TickMarkerCard>
            )
          }
          if (segment.kind === "actions") return null

          if (hasTickMarkers) return null

          return (
            <FeedPostCard
              key={segment.key}
              post={segment.post}
              tickIndex={
                timeline.find(
                  (item) =>
                    item.kind === "post" &&
                    item.post.post_id === segment.post.post_id,
                )?.tickIndex ?? 0
              }
              agents={agents}
              postsById={postsById}
              commentsByPostId={commentsByPostId}
              agentTools={variant.agent_tools ?? []}
              tickMarkers={variant.tick_markers ?? []}
              mentionMatcher={mentionMatcher}
              openMention={openMention}
              openAgent={openAgent}
              openAgentRow={openAgentRow}
              runId={runId}
              attemptId={attemptId}
              onInterview={openPostInterview}
              anchors={feedAnchors}
            />
          )
        })}
      </ul>

      <AdminModal
        open={dayEventsModalTick != null}
        titleId="day-events-modal-title"
        title={
          dayEventsModalTick != null
            ? t("runs.results.eventsTitleDay", {
                day: tickDayLabel(dayEventsModalTick),
              })
            : t("runs.results.eventsTitle")
        }
        onClose={() => setDayEventsModalTick(null)}
        wide
      >
        {modalDayActions.length > 0 ? (
          <ul className="flex max-h-[min(28rem,70vh)] flex-col gap-1.5 overflow-y-auto">
            {modalDayActions.map((item) => (
              <CompactActionRow
                key={`modal-action-${item.userId}-${item.action}-${item.sortKey}-${item.tie}`}
                item={item}
                agents={agents}
                onOpenAgent={openAgent}
              />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("runs.results.noEventsToday")}
          </p>
        )}
      </AdminModal>

      <AdminModal
        open={dayMeasurementsModalTick != null}
        titleId="day-measurements-modal-title"
        title={
          dayMeasurementsModalTick != null
            ? t("runs.results.measurementsTitleDay", {
                day: tickDayLabel(dayMeasurementsModalTick),
              })
            : t("runs.results.measurementsTitle")
        }
        onClose={() => setDayMeasurementsModalTick(null)}
        wide
      >
        {modalDayMeasurements.length > 0 ? (
          <div className="flex max-h-[min(28rem,70vh)] flex-col gap-3 overflow-y-auto">
            {modalDayMeasurements.map((point) => (
              <MeasurementPointBlock key={point.id} point={point} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("runs.results.noMeasurementToday")}
          </p>
        )}
      </AdminModal>

      <PersonaProfileModal
        open={profile != null}
        personaId={profile?.personaId ?? null}
        fallbackName={profile?.name}
        onClose={() => setProfile(null)}
      />

      {mentionPick ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
          role="presentation"
          onClick={() => setMentionPick(null)}
        >
          <div
            className="w-full max-w-sm rounded-lg border border-border bg-card p-4 shadow-lg"
            role="dialog"
            aria-labelledby="mention-pick-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h4
              id="mention-pick-title"
              className="text-sm font-semibold text-foreground"
            >
              {t("runs.feed.mentionQuestion", { label: mentionPick.label })}
            </h4>
            <ul className="mt-3 space-y-2">
              {mentionPick.userIds.map((userId) => (
                <li key={userId}>
                  <AgentNameButton
                    name={agentLabel(agents, userId, t)}
                    className="text-sm"
                    showAvatar={!agentIsInjector(agents, userId)}
                    onOpen={() => {
                      openAgent(userId)
                      setMentionPick(null)
                    }}
                  />
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="mt-3 text-xs text-muted-foreground underline-offset-2 hover:underline"
              onClick={() => setMentionPick(null)}
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {showAnchors && runId != null && attemptId ? (
        <AddAnchorModal
          key={
            anchorTarget
              ? flaggedKeyForRow(anchorTarget.row)
              : "anchor-modal-closed"
          }
          open={anchorTarget != null}
          target={anchorTarget}
          runId={runId}
          attemptId={attemptId}
          variantId={variant.id}
          toneName={taggable.context?.tone.name ?? ""}
          styleName={taggable.context?.style.name ?? ""}
          toneOptions={taggable.context?.tone.labels ?? []}
          styleOptions={taggable.context?.style.labels ?? []}
          onClose={() => setAnchorTarget(null)}
          onAdded={() => void taggable.reload()}
        />
      ) : null}
    </div>
  )
}

function attemptHasData(attempt: OasisAttemptResult): boolean {
  return (attempt.variants ?? []).some(
    (v) =>
      !v.error &&
      ((v.posts?.length ?? 0) > 0 ||
        (v.comments?.length ?? 0) > 0 ||
        (v.agents?.length ?? 0) > 0),
  )
}

function AttemptBlock({
  attempt,
  index,
  total,
  expanded,
  onToggleExpand,
  onRequestDelete,
  deleting,
  selected,
  onToggleSelect,
  onRequestOrderReport,
  ordering,
  branchMode,
  runId,
  runStatus,
}: {
  attempt: OasisAttemptResult
  index: number
  total: number
  expanded: boolean
  onToggleExpand: () => void
  onRequestDelete?: (attemptId: string) => void
  deleting?: boolean
  selected?: boolean
  onToggleSelect?: (attemptId: string) => void
  onRequestOrderReport?: (attemptId: string) => void
  ordering?: boolean
  branchMode?: BranchMode | null
  runId?: number
  runStatus?: string
}) {
  const { intl, t } = useLocale()
  const variants = attempt.variants ?? []
  const stimulusVariant = variants.find((v) => v.id === "a")
  const controlVariant = variants.find((v) => v.id === "b")
  const showStimulusControl =
    stimulusVariant &&
    controlVariant &&
    isStimulusControlPair(variants, branchMode)
  const stamp = formatWhen(attempt.finished_at, t, intl)
  const dayStamp = formatAttemptDay(attempt.finished_at, t, intl)
  const attemptNumber = total - index
  const variantIdsKey = variants.map((v) => v.id).join("|")
  const canDelete = Boolean(onRequestDelete && attempt.id)
  const hasData = attemptHasData(attempt)
  const [expandedVariantId, setExpandedVariantId] = useState<string | null>(() =>
    variants[0]?.id ?? null,
  )
  const [networkModalVariant, setNetworkModalVariant] =
    useState<OasisVariantResult | null>(null)
  const [networkProfile, setNetworkProfile] = useState<ProfileTarget | null>(null)
  const activeVariant =
    variants.find((v) => v.id === expandedVariantId) ?? variants[0]

  useEffect(() => {
    setExpandedVariantId((prev) => {
      if (prev && variants.some((v) => v.id === prev)) return prev
      return variants[0]?.id ?? null
    })
  }, [attempt.id, variantIdsKey, variants.length])

  return (
    <div className="results-attempt">
      <div
        className="results-attempt-head"
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggleExpand}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            onToggleExpand()
          }
        }}
      >
        {onToggleSelect && hasData ? (
          <input
            type="checkbox"
            checked={Boolean(selected)}
            aria-label={t("runs.results.selectAttempt", { stamp })}
            onClick={(e) => e.stopPropagation()}
            onChange={() => onToggleSelect(attempt.id)}
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="results-attempt-title">
            {t("runs.results.attemptTitle", {
              number: attemptNumber,
              when: dayStamp,
            })}
          </div>
          {attempt.engine ? (
            <div className="results-attempt-engine">
              {t("runs.results.engineLine", { engine: attempt.engine })}
            </div>
          ) : null}
        </div>
        <div
          className="results-attempt-actions"
          onClick={(e) => e.stopPropagation()}
        >
          {hasData && onRequestOrderReport ? (
            <OrderReportButton
              busy={ordering}
              label={t("runs.results.reportOrder")}
              onClick={() => onRequestOrderReport(attempt.id)}
            />
          ) : null}
          {canDelete ? (
            <button
              type="button"
              className="results-icon-btn"
              aria-label={t("runs.results.deleteResult")}
              disabled={deleting}
              onClick={() => onRequestDelete?.(attempt.id)}
            >
              <Trash2 aria-hidden="true" size={14} />
            </button>
          ) : null}
        </div>
        <span className={"results-chevron" + (expanded ? " open" : "")}>▾</span>
      </div>

      {expanded ? (
        <div className="results-attempt-body">
          {attempt.error ? (
            <p className="mb-3 text-sm text-[#b42318]">{attempt.error}</p>
          ) : null}

          {runStatus === "running" && !hasData ? (
            <p className="text-sm text-muted-foreground">
              {t("runs.results.runningWait")}
            </p>
          ) : null}

          {showStimulusControl ? (
            <StimulusControlComparison
              stimulus={stimulusVariant}
              control={controlVariant}
            />
          ) : null}

          {variants.length > 1 ? (
            <div className="results-variant-row">
              <div className="view-toggle" role="tablist">
                {variants.map((variant) => (
                  <button
                    key={variant.id}
                    type="button"
                    role="tab"
                    aria-selected={activeVariant?.id === variant.id}
                    className={activeVariant?.id === variant.id ? "on" : undefined}
                    onClick={() => setExpandedVariantId(variant.id)}
                  >
                    {variant.label}
                  </button>
                ))}
              </div>
              {activeVariant && variantHasNetworkActivity(activeVariant) ? (
                <NetworkActivityIconButton
                  label={t("runs.results.networkTitle")}
                  onClick={() => setNetworkModalVariant(activeVariant)}
                />
              ) : null}
            </div>
          ) : activeVariant && variantHasNetworkActivity(activeVariant) ? (
            <div className="results-variant-row">
              <span />
              <NetworkActivityIconButton
                label={t("runs.results.networkTitle")}
                onClick={() => setNetworkModalVariant(activeVariant)}
              />
            </div>
          ) : null}

          {activeVariant ? (
            <>
              <VariantBody
                variant={activeVariant}
                runId={runId}
                attemptId={attempt.id}
                showAnchors={runStatus === "done" && Boolean(runId)}
              />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t("runs.results.noPostsInAttempt")}
            </p>
          )}
        </div>
      ) : null}

      <AdminModal
        open={networkModalVariant != null}
        titleId="network-activity-modal-title"
        title={t("runs.results.networkTitle")}
        description={networkModalVariant?.label}
        wide
        onClose={() => setNetworkModalVariant(null)}
      >
        {networkModalVariant ? (
          <NetworkActivityContent
            variant={networkModalVariant}
            onOpenAgent={(userId) =>
              setNetworkProfile(
                agentProfileTarget(networkModalVariant.agents ?? [], userId, t),
              )
            }
          />
        ) : null}
      </AdminModal>

      <PersonaProfileModal
        open={networkProfile != null}
        personaId={networkProfile?.personaId ?? null}
        fallbackName={networkProfile?.name}
        onClose={() => setNetworkProfile(null)}
      />
    </div>
  )
}

type Props = {
  results: OasisRunResults
  status: string
  runId?: number
  pageTitle?: string
  branchMode?: BranchMode | null
  onDeleteAttempt?: (attemptId: string) => void | Promise<void>
  deletingAttemptId?: string | null
}

type ReportConfirmState = {
  sources: Array<{ run_id: number; attempt_id: string }>
  title?: string
  labels: string[]
}

type DeleteConfirmState = {
  attemptId: string
  label: string
}

export function OasisResultsPanel({
  results,
  status,
  runId,
  pageTitle,
  branchMode = null,
  onDeleteAttempt,
  deletingAttemptId = null,
}: Props) {
  const { intl, locale, t } = useLocale()
  const navigate = useNavigate()
  const { reports } = useReportsRealtime()
  const attempts = normalizeRunAttempts(results, t)
  const attemptIds = useMemo(() => attempts.map((a) => a.id), [results])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [orderingId, setOrderingId] = useState<string | null>(null)
  const [compareBusy, setCompareBusy] = useState(false)
  const [orderError, setOrderError] = useState<string | null>(null)
  const [reportConfirm, setReportConfirm] = useState<ReportConfirmState | null>(
    null,
  )
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState | null>(
    null,
  )
  const [expandedAttemptId, setExpandedAttemptId] = useState<string | null>(null)

  const busyAttemptIds = useMemo(() => {
    const next = new Set<string>()
    if (runId == null) return next
    for (const r of reports) {
      if (r.status !== "pending" && r.status !== "running") continue
      for (const s of r.sources) {
        if (s.run_id === runId) next.add(s.attempt_id)
      }
    }
    return next
  }, [reports, runId])

  useEffect(() => {
    setExpandedAttemptId((prev) => {
      if (prev && attemptIds.includes(prev)) return prev
      return attemptIds[0] ?? null
    })
  }, [attemptIds])

  function toggleAttemptExpand(attemptId: string) {
    setExpandedAttemptId((prev) => (prev === attemptId ? null : attemptId))
  }

  async function orderSources(
    sources: Array<{ run_id: number; attempt_id: string }>,
    title?: string,
  ) {
    if (!runId) return
    setOrderError(null)
    const report = await createReport({ sources, title, locale })
    navigate(`/reports/${report.id}`)
  }

  function attemptLabel(attemptId: string): string {
    const attempt = attempts.find((a) => a.id === attemptId)
    return formatWhen(attempt?.finished_at, t, intl)
  }

  function requestOrderOne(attemptId: string) {
    if (!runId) return
    setReportConfirm({
      sources: [{ run_id: runId, attempt_id: attemptId }],
      labels: [attemptLabel(attemptId)],
    })
  }

  function requestCompare() {
    if (!runId || selected.size < 2) return
    const ids = [...selected]
    setReportConfirm({
      sources: ids.map((attempt_id) => ({ run_id: runId, attempt_id })),
      title:
        selected.size > 1
          ? t("runs.results.reportCompareTitle", { count: selected.size })
          : undefined,
      labels: ids.map(attemptLabel),
    })
  }

  async function confirmReportOrder() {
    if (!reportConfirm) return
    const { sources, title } = reportConfirm
    setReportConfirm(null)
    if (sources.length === 1) {
      setOrderingId(sources[0]!.attempt_id)
    } else {
      setCompareBusy(true)
    }
    try {
      await orderSources(sources, title)
    } catch (err) {
      setOrderError(
        err instanceof ApiError ? err.message : t("runs.results.reportError"),
      )
    } finally {
      setOrderingId(null)
      setCompareBusy(false)
    }
  }

  function requestDelete(attemptId: string) {
    setDeleteConfirm({
      attemptId,
      label: attemptLabel(attemptId),
    })
  }

  async function confirmDelete() {
    if (!deleteConfirm || !onDeleteAttempt) return
    const { attemptId } = deleteConfirm
    setDeleteConfirm(null)
    await onDeleteAttempt(attemptId)
  }

  function toggleSelect(attemptId: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(attemptId)) next.delete(attemptId)
      else next.add(attemptId)
      return next
    })
  }

  const selectionBusy = [...selected].some((id) => busyAttemptIds.has(id))
  const compareDisabled =
    selected.size < 2 || compareBusy || orderingId != null || selectionBusy

  if (attempts.length === 0) {
    if (status === "running") return null
    return (
      <div className="mb-9">
        {pageTitle ? (
          <div className="results-page-head">
            <div>
              <h1>{pageTitle}</h1>
              <p>{t("runs.results.pageIntro")}</p>
            </div>
          </div>
        ) : null}
        <p className="text-sm text-muted-foreground">{t("runs.results.noSaved")}</p>
      </div>
    )
  }

  return (
    <div className="mb-9 flex flex-col gap-3.5">
      <div className="results-page-head">
        <div>
          <h1>{pageTitle || t("runs.results.title")}</h1>
          <p>{t("runs.results.pageIntro")}</p>
        </div>
        {runId ? (
          <button
            type="button"
            className="results-compare-btn"
            disabled={compareDisabled}
            onClick={requestCompare}
          >
            {t("runs.results.compareSelected", { count: selected.size })}
          </button>
        ) : null}
      </div>
      {orderError ? (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {orderError}
        </p>
      ) : null}
      {attempts.map((attempt, index) => {
        const attemptBusy =
          orderingId === attempt.id ||
          compareBusy ||
          busyAttemptIds.has(attempt.id)
        return (
          <AttemptBlock
            key={attempt.id || `attempt-${index}`}
            attempt={attempt}
            index={index}
            total={attempts.length}
            expanded={expandedAttemptId === attempt.id}
            onToggleExpand={() => toggleAttemptExpand(attempt.id)}
            onRequestDelete={
              status === "running" || !onDeleteAttempt
                ? undefined
                : requestDelete
            }
            deleting={deletingAttemptId === attempt.id}
            selected={selected.has(attempt.id)}
            onToggleSelect={runId ? toggleSelect : undefined}
            onRequestOrderReport={runId ? requestOrderOne : undefined}
            ordering={attemptBusy}
            branchMode={branchMode}
            runId={runId}
            runStatus={status}
          />
        )
      })}

      <AdminModal
        open={reportConfirm != null}
        titleId="report-confirm-title"
        title={
          reportConfirm && reportConfirm.sources.length > 1
            ? t("runs.results.reportCompare", {
                count: reportConfirm.sources.length,
              })
            : t("runs.results.reportOrder")
        }
        description={t("runs.results.reportConfirmDesc")}
        onClose={() => setReportConfirm(null)}
      >
        {reportConfirm ? (
          <div className="space-y-4">
            <p className="text-sm text-foreground">
              {reportConfirm.sources.length === 1
                ? t("runs.results.reportConfirmOne")
                : t("runs.results.reportConfirmMany", {
                    count: reportConfirm.sources.length,
                  })}
            </p>
            <ul className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
              {reportConfirm.labels.map((label, i) => (
                <li key={`${label}-${i}`} className="font-mono tabular-nums text-foreground">
                  {label}
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/40"
                onClick={() => setReportConfirm(null)}
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="rounded-md border border-db-gold-600 bg-db-gold-100 px-3 py-1.5 text-sm font-medium text-db-gold-800 hover:bg-db-gold-200"
                onClick={() => void confirmReportOrder()}
              >
                {t("runs.results.startGeneration")}
              </button>
            </div>
          </div>
        ) : null}
      </AdminModal>

      <AdminModal
        open={deleteConfirm != null}
        titleId="delete-confirm-title"
        title={t("runs.results.deleteTitle")}
        description={t("runs.results.deleteDescription")}
        onClose={() => setDeleteConfirm(null)}
      >
        {deleteConfirm ? (
          <div className="space-y-4">
            <p className="text-sm text-foreground">
              {t("runs.results.deleteBody", { label: deleteConfirm.label })}
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/40"
                onClick={() => setDeleteConfirm(null)}
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/20 disabled:opacity-50"
                disabled={deletingAttemptId != null}
                onClick={() => void confirmDelete()}
              >
                {deletingAttemptId != null
                  ? t("runs.results.deleting")
                  : t("runs.results.deletePermanent")}
              </button>
            </div>
          </div>
        ) : null}
      </AdminModal>
    </div>
  )
}
