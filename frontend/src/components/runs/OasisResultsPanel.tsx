import { useEffect, useMemo, useRef, useState, useCallback, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import { createReport, listReports } from "@/api/reports"
import { PersonaProfileModal } from "@/components/personas/PersonaProfileModal"
import {
  buildTimelineItems,
  CARD_COVERED_ACTIONS,
  groupTimelineSegments,
  type TimelineActionItem,
} from "@/components/runs/activityFeed"
import {
  buildMentionAliases,
  CommentBody,
  getMentionMatcher,
} from "@/components/runs/commentMentions"
import {
  CopyAttemptButton,
  CopyFeedTextButton,
  formatCommentForClipboard,
  formatPostForClipboard,
  postBodyTextForCopy,
} from "@/components/runs/feedCopy"
import { personaInitials } from "@/data/library"
import { RUN_STATUS_LABEL } from "@/data/runs"
import { ApiError } from "@/lib/api"
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
  type RunStatus,
} from "@/data/runs-types"

type AgentRow = NonNullable<OasisVariantResult["agents"]>[number]

type ProfileTarget = {
  personaId: string | null
  name: string
}

/** Normalize legacy flat results and current attempts[] into a stable list. */
export function normalizeRunAttempts(
  results: OasisRunResults | null | undefined,
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
            label: "Huvudtidslinje",
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

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "Okänd tidpunkt"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat("sv-SE", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d)
}

function agentLabel(
  agents: NonNullable<OasisVariantResult["agents"]>,
  userId: number,
): string {
  return agents.find((a) => a.index === userId)?.member_name ?? `agent ${userId}`
}

function agentProfileTarget(
  agents: NonNullable<OasisVariantResult["agents"]>,
  userId: number,
): ProfileTarget {
  const agent = agents.find((a) => a.index === userId)
  return {
    personaId: agent?.persona_id ?? null,
    name: agent?.member_name ?? `agent ${userId}`,
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

function formatFeedWhen(iso: string | number | null | undefined): string | null {
  if (iso == null || iso === "") return null
  if (typeof iso === "number" || (/^\d+(\.\d+)?$/.test(String(iso)) && !String(iso).includes("-"))) {
    return `t=${iso}`
  }
  const d = new Date(String(iso))
  if (Number.isNaN(d.getTime())) return String(iso)
  return new Intl.DateTimeFormat("sv-SE", {
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
          <span>{engagement.posts ?? 0} inlägg</span>
          <span>{engagement.comments ?? 0} kommentarer</span>
          <span>{engagement.likes ?? 0} likes</span>
          <span>{engagement.dislikes ?? 0} dislikes</span>
          <span>{engagement.shares ?? 0} shares</span>
          <span>engagemang {engagement.engagement_score ?? 0}</span>
          {typeof follows?.edges === "number" ? (
            <span>{follows.edges} följningar</span>
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
            Sentiment
          </div>
          <div className="flex h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="bg-[var(--db-success)]"
              style={{ width: pct(sentiment.positive) }}
              title={`Positiv ${pct(sentiment.positive)}`}
            />
            <div
              className="bg-[var(--db-ink-200)]"
              style={{ width: pct(sentiment.neutral) }}
              title={`Neutral ${pct(sentiment.neutral)}`}
            />
            <div
              className="bg-[var(--db-error)]"
              style={{ width: pct(sentiment.negative) }}
              title={`Negativ ${pct(sentiment.negative)}`}
            />
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
            <span>Pos {pct(sentiment.positive)}</span>
            <span>Neu {pct(sentiment.neutral)}</span>
            <span>Neg {pct(sentiment.negative)}</span>
          </div>
        </div>
      ) : null}

      {phrases.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            Toppfraser
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
            Engagemang per distrikt
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
            Mest följda (agent-index)
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

function QualityWarningsBanner({ data }: { data: QualityWarnings }) {
  const warnings = data.warnings ?? []
  if (warnings.length === 0) return null

  const thresholdPct = Math.round(data.threshold * 100)

  return (
    <section
      className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2.5"
      aria-label="Kvalitetsvarningar"
    >
      <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-100">
        Lexikal konvergens
      </h3>
      <p className="mt-1 text-xs text-amber-900/80 dark:text-amber-100/80">
        {warnings.length} fras{warnings.length === 1 ? "" : "er"} delas av ≥
        {thresholdPct}% av populationen ({data.population_agents} agenter).
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
              {w.kind === "source_phrase_echo" ? " · eko av injektion" : " · gemensam fras"}
              {w.source ? ` (${w.source})` : ""}
            </span>
          </li>
        ))}
      </ul>
      {warnings.length > 8 ? (
        <p className="mt-1.5 text-[11px] text-amber-900/70 dark:text-amber-100/70">
          +{warnings.length - 8} till
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
      aria-label="Stimulus vs kontroll"
    >
      <h3 className="text-sm font-semibold text-sky-950 dark:text-sky-50">
        Stimulus vs kontroll
      </h3>
      <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
        Med stimulus: {sCount} konvergensvarning
        {sCount === 1 ? "" : "ar"}. Kontroll: {cCount} konvergensvarning
        {cCount === 1 ? "" : "ar"}.
      </p>
      {delta > 0 ? (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          Stimulus ökar lexikal konvergens med {delta} varning
          {delta === 1 ? "" : "ar"} — troligen kopplat till injektionstext eller
          budskapsspridning.
        </p>
      ) : delta < 0 ? (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          Kontroll har fler varningar än stimulus (oväntat — granska
          populationens spontana språkmönster).
        </p>
      ) : sCount > 0 ? (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          Samma antal varningar i båda varianterna — konvergens verkar inte
          drivas enbart av injektionen.
        </p>
      ) : (
        <p className="mt-1 text-xs text-sky-950/80 dark:text-sky-50/80">
          Inga konvergensvarningar i någon variant.
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
                — bara i stimulus ({w.agent_count} agenter)
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function MeasurementsSection({ rows }: { rows: OasisMeasurementRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="mb-4 text-sm text-muted-foreground">
        Inga mätpunkter konfigurerades på tidslinjen.
      </p>
    )
  }

  return (
    <section className="mb-5">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Mätpunkter</h3>
      <div className="flex flex-col gap-2">
        {rows.map((row) => (
          <div
            key={`${row.tick_key}-${row.tick_index}`}
            className="rounded-md border border-border/80 bg-muted/15"
          >
            <div className="border-b border-border/60 px-3 py-2 text-xs text-muted-foreground">
              Dag {row.day}
              <span className="mx-1.5 text-border">·</span>
              tick {row.tick_index + 1}
            </div>
            <ul className="divide-y divide-border/50">
              {row.points.map((point) => (
                <li key={point.id}>
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-3 py-2.5 marker:content-none [&::-webkit-details-marker]:hidden">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-foreground">
                          {point.label}
                        </div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {point.summary}
                        </div>
                      </div>
                      <span className="shrink-0 pt-0.5 text-xs text-muted-foreground group-open:hidden">
                        Detalj ▾
                      </span>
                      <span className="hidden shrink-0 pt-0.5 text-xs text-muted-foreground group-open:inline">
                        Dölj ▴
                      </span>
                    </summary>
                    <div className="border-t border-border/50 px-3 py-3">
                      <MeasurementDetail point={point} />
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
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
  if (userIds.length === 0) {
    return <p className="px-1 py-0.5 text-xs text-muted-foreground">{emptyLabel}</p>
  }
  return (
    <ul className="max-h-40 overflow-auto py-0.5">
      {userIds.map((id) => (
        <li key={id} className="rounded px-2 py-0.5 text-xs hover:bg-muted/60">
          <AgentNameButton
            name={agentLabel(agents, id)}
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
            aria-label={`Gilla, ${likes.length}`}
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
            {!compact ? <span>Gilla</span> : null}
          </button>
          {open === "like" ? (
            <div
              className="absolute bottom-full left-0 z-20 mb-1.5 min-w-[12rem] max-w-[16rem] rounded-lg border border-border bg-card p-1.5 shadow-lg"
              role="dialog"
              aria-label="Gillat av"
            >
              <div className="border-b border-border/60 px-2 py-1 text-[11px] font-semibold text-muted-foreground">
                Gillat av
              </div>
              <ActorList
                agents={agents}
                userIds={likes}
                emptyLabel="Ingen har gillat ännu"
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
            aria-label={`Ogilla, ${dislikes.length}`}
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
            {!compact ? <span>Ogilla</span> : null}
          </button>
          {open === "dislike" ? (
            <div
              className="absolute bottom-full left-0 z-20 mb-1.5 min-w-[12rem] max-w-[16rem] rounded-lg border border-border bg-card p-1.5 shadow-lg"
              role="dialog"
              aria-label="Ogillat av"
            >
              <div className="border-b border-border/60 px-2 py-1 text-[11px] font-semibold text-muted-foreground">
                Ogillat av
              </div>
              <ActorList
                agents={agents}
                userIds={dislikes}
                emptyLabel="Ingen har ogillat ännu"
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
              aria-label={`Dela, ${shares.length}`}
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
              <span>Dela</span>
            </button>
            {open === "share" ? (
              <div
                className="absolute bottom-full left-0 z-20 mb-1.5 min-w-[12rem] max-w-[16rem] rounded-lg border border-border bg-card p-1.5 shadow-lg"
                role="dialog"
                aria-label="Delat av"
              >
                <div className="border-b border-border/60 px-2 py-1 text-[11px] font-semibold text-muted-foreground">
                  Delat av
                </div>
                <ul className="max-h-40 overflow-auto py-0.5">
                  {shares.map((s) => (
                    <li
                      key={`${s.user_id}-${s.kind}-${s.share_post_id ?? ""}`}
                      className="flex items-center justify-between gap-2 rounded px-2 py-0.5 text-xs hover:bg-muted/60"
                    >
                      <AgentNameButton
                        name={agentLabel(agents, s.user_id)}
                        className="px-0 py-1 text-left text-xs"
                        showAvatar={!agentIsInjector(agents, s.user_id)}
                        onOpen={() => openAgentAndClose(s.user_id)}
                      />
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        {s.kind === "quote" ? "citat" : "delning"}
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

function NetworkActivitySection({
  variant,
  onOpenAgent,
}: {
  variant: OasisVariantResult
  onOpenAgent: (userId: number) => void
}) {
  const agents = variant.agents ?? []
  const follows = variant.follows ?? []
  const mutes = variant.mutes ?? []
  const reports = variant.reports ?? []
  const histogram = variant.action_histogram ?? []
  if (
    follows.length === 0 &&
    mutes.length === 0 &&
    reports.length === 0 &&
    histogram.length === 0
  ) {
    return null
  }

  const maxHist = Math.max(1, ...histogram.map((h) => h.count))

  return (
    <div className="mb-4 space-y-3 rounded-lg border border-border bg-card/60 px-4 py-3">
      <h3 className="text-sm font-semibold text-foreground">Nätverk & åtgärder</h3>

      {follows.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            Följningar ({follows.length})
          </div>
          <ul className="max-h-36 space-y-1 overflow-y-auto text-xs text-muted-foreground">
            {follows.slice(0, 40).map((f, i) => (
              <li key={`${f.follower_id}-${f.followee_id}-${i}`}>
                <AgentNameButton
                  name={agentLabel(agents, f.follower_id)}
                  className="text-xs text-muted-foreground"
                  showAvatar={!agentIsInjector(agents, f.follower_id)}
                  onOpen={() => onOpenAgent(f.follower_id)}
                />
                {" → "}
                <AgentNameButton
                  name={agentLabel(agents, f.followee_id)}
                  className="text-xs text-muted-foreground"
                  showAvatar={!agentIsInjector(agents, f.followee_id)}
                  onOpen={() => onOpenAgent(f.followee_id)}
                />
              </li>
            ))}
            {follows.length > 40 ? (
              <li className="text-muted-foreground/80">
                …och {follows.length - 40} till
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}

      {mutes.length > 0 || reports.length > 0 ? (
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          {mutes.length > 0 ? <span>{mutes.length} mutes</span> : null}
          {reports.length > 0 ? <span>{reports.length} rapporter</span> : null}
        </div>
      ) : null}

      {histogram.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            Åtgärder (trace)
          </div>
          <ul className="space-y-1">
            {histogram.slice(0, 12).map((row) => (
              <li
                key={row.action}
                className="grid grid-cols-[8rem_1fr_auto] items-center gap-2"
              >
                <span className="truncate font-mono text-[11px] text-foreground">
                  {row.action}
                </span>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-[var(--db-gold-500)]"
                    style={{
                      width: `${Math.round((row.count / maxHist) * 100)}%`,
                    }}
                  />
                </div>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {row.count}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
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
  const when = formatFeedWhen(item.createdAt)
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-dashed border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <AgentNameButton
        name={agentLabel(agents, item.userId)}
        className="text-xs font-medium text-foreground"
        showAvatar={!agentIsInjector(agents, item.userId)}
        onOpen={() => onOpenAgent(item.userId)}
      />
      <span>{item.label}</span>
      {item.targetUserId != null ? (
        <AgentNameButton
          name={item.detail ?? agentLabel(agents, item.targetUserId)}
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

function FeedNoiseFilter({
  hideNoise,
  onChange,
}: {
  hideNoise: boolean
  onChange: (hideNoise: boolean) => void
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
      <span className="text-muted-foreground">Händelser:</span>
      <button
        type="button"
        className={
          "rounded border px-2 py-0.5 " +
          (!hideNoise
            ? "border-[var(--db-gold-500)] bg-[var(--db-gold-500)]/15 text-foreground"
            : "border-border text-muted-foreground hover:bg-muted/40")
        }
        aria-pressed={!hideNoise}
        onClick={() => onChange(false)}
      >
        Alla
      </button>
      <button
        type="button"
        className={
          "rounded border px-2 py-0.5 " +
          (hideNoise
            ? "border-[var(--db-gold-500)] bg-[var(--db-gold-500)]/15 text-foreground"
            : "border-border text-muted-foreground hover:bg-muted/40")
        }
        aria-pressed={hideNoise}
        onClick={() => onChange(true)}
      >
        Dölj brus
      </button>
      <span className="text-[10px] text-muted-foreground/80">
        Brus = refresh, sign_up, do_nothing
      </span>
    </div>
  )
}

function TickMarkerCard({
  tick,
}: {
  tick: {
    day: number
    silent: boolean
    rounds: number
    timeStart: number
    timeEnd: number
  }
}) {
  const empty = tick.timeEnd < tick.timeStart
  return (
    <li className="list-none">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
        <span className="font-semibold text-foreground">Dag {tick.day}</span>
        {tick.silent ? (
          <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            tyst
          </span>
        ) : (
          <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            tick
          </span>
        )}
        <span className="text-muted-foreground">
          {tick.rounds} rond{tick.rounds === 1 ? "" : "er"}
        </span>
        <span className="ml-auto tabular-nums text-[10px] text-muted-foreground/80">
          {empty
            ? "inga nya händelser"
            : `t=${tick.timeStart}–${tick.timeEnd}`}
        </span>
      </div>
    </li>
  )
}

function ActionCluster({
  actions,
  agents,
  onOpenAgent,
}: {
  actions: TimelineActionItem[]
  agents: NonNullable<OasisVariantResult["agents"]>
  onOpenAgent: (userId: number) => void
}) {
  if (actions.length === 0) return null
  const labels = [...new Set(actions.map((a) => a.label))].slice(0, 3)
  const labelHint = labels.join(", ") + (labels.length < actions.length ? "…" : "")

  return (
    <li className="list-none">
      <details className="rounded-lg border border-dashed border-border/80 bg-muted/15">
        <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-foreground marker:content-none [&::-webkit-details-marker]:hidden">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>
              {actions.length} händelse{actions.length === 1 ? "" : "r"}
              <span className="ml-1.5 font-normal text-muted-foreground">
                ({labelHint})
              </span>
            </span>
            <span className="font-normal text-muted-foreground">Visa</span>
          </span>
        </summary>
        <ul
          className="flex max-h-56 flex-col gap-1.5 overflow-y-auto overscroll-y-contain border-t border-border/50 px-2 py-2"
          onWheel={(e) => e.stopPropagation()}
        >
          {actions.map((item) => (
            <CompactActionRow
              key={`action-${item.userId}-${item.action}-${item.sortKey}-${item.tie}`}
              item={item}
              agents={agents}
              onOpenAgent={onOpenAgent}
            />
          ))}
        </ul>
      </details>
    </li>
  )
}

function VariantBody({ variant }: { variant: OasisVariantResult }) {
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
  const [hideNoise, setHideNoise] = useState(false)

  const openAgent = useCallback(
    (userId: number) => {
      setProfile(agentProfileTarget(agents, userId))
    },
    [agents],
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
    (id: number) => agentLabel(agents, id),
    [agents],
  )

  const timeline = useMemo(
    () => buildTimelineItems(variant, { hideNoise, agentName }),
    [variant, hideNoise, agentName],
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
  const hasTraceActions = useMemo(
    () =>
      (variant.trace ?? []).some((t) => {
        const a = (t.action || "").trim()
        return a.length > 0 && !CARD_COVERED_ACTIONS.has(a)
      }),
    [variant.trace],
  )

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
      <p className="mb-3 text-xs text-muted-foreground">
        Plattform: {platform === "reddit" ? "Reddit" : "Twitter"}
      </p>
      {qualityWarnings ? <QualityWarningsBanner data={qualityWarnings} /> : null}
      <MeasurementsSection rows={measurements} />
      <NetworkActivitySection variant={variant} onOpenAgent={openAgent} />

      {agents.length > 0 ? (
        <div className="mb-3 space-y-1 text-sm text-muted-foreground">
          {injectors.length > 0 ? (
            <p>
              Injektorer:{" "}
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
            Population:{" "}
            {population.length === 0
              ? "—"
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

      <h3 className="mb-2 text-sm font-semibold text-foreground">Flöde</h3>
      {hasTraceActions ? (
        <FeedNoiseFilter hideNoise={hideNoise} onChange={setHideNoise} />
      ) : null}

      {posts.length === 0 && segments.every((s) => s.kind !== "actions") ? (
        <p className="text-sm text-muted-foreground">Inga inlägg sparades.</p>
      ) : null}

      <ul className="flex flex-col gap-3">
        {segments.map((segment) => {
          if (segment.kind === "tick") {
            return <TickMarkerCard key={segment.key} tick={segment.tick} />
          }
          if (segment.kind === "actions") {
            return (
              <ActionCluster
                key={segment.key}
                actions={segment.actions}
                agents={agents}
                onOpenAgent={openAgent}
              />
            )
          }

          const post = segment.post
          const agent = agents.find((a) => a.index === post.user_id)
          const author = agent?.member_name ?? `agent ${post.user_id}`
          const isInjector = agent?.role === "injector"
          const originalId = post.original_post_id ?? null
          const original =
            originalId != null ? postsById.get(originalId) : undefined
          const originalAuthor =
            original != null ? agentLabel(agents, original.user_id) : null
          const quote = (post.quote_content ?? "").trim()
          const isQuote = originalId != null && quote.length > 0
          const isRepost = originalId != null && quote.length === 0
          const postComments = commentsByPostId.get(post.post_id) ?? []
          const when = formatFeedWhen(post.created_at)

          let kindLabel: string | null = null
          if (isInjector) kindLabel = "injektion"
          else if (isQuote) kindLabel = "citat"
          else if (isRepost) kindLabel = "delning"

          const postBody = postBodyTextForCopy(post, {
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
              author: agentLabel(agents, c.user_id),
              content: c.content,
            })),
          )

          return (
            <li
              key={segment.key}
              className="rounded-lg border border-border bg-card px-4 py-3 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <FeedAuthorHeader
                  name={author}
                  showAvatar={!isInjector}
                  size="md"
                  onOpen={() => openAgentRow(agent, author)}
                  meta={
                    <>
                      {when ? <span>{when}</span> : null}
                      {kindLabel ? (
                        <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                          {kindLabel}
                        </span>
                      ) : null}
                      <span className="text-muted-foreground/80">#{post.post_id}</span>
                    </>
                  }
                />
                <CopyFeedTextButton text={postCopyText} label="Kopiera inlägg" />
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
                      Citerar{" "}
                      {original != null ? (
                        <AgentNameButton
                          name={originalAuthor ?? "okänd"}
                          className="text-xs text-muted-foreground"
                          showAvatar={!agentIsInjector(agents, original.user_id)}
                          onOpen={() => openAgent(original.user_id)}
                        />
                      ) : (
                        "okänd"
                      )}{" "}
                      #{originalId}
                    </p>
                  </div>
                ) : null}

                {isRepost ? (
                  <p className="text-sm text-muted-foreground">
                    Delade inlägg från{" "}
                    {original != null ? (
                      <AgentNameButton
                        name={originalAuthor ?? "okänd"}
                        className="text-sm text-muted-foreground"
                        showAvatar={!agentIsInjector(agents, original.user_id)}
                        onOpen={() => openAgent(original.user_id)}
                      />
                    ) : (
                      "okänd"
                    )}{" "}
                    #{originalId}
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
                    const commentName = agentLabel(agents, c.user_id)
                    const commentInjector = agentIsInjector(agents, c.user_id)
                    return (
                      <li key={c.comment_id} className="flex items-start gap-1.5">
                        {commentInjector ? null : (
                          <AgentAvatar name={commentName} size="sm" />
                        )}
                        <div className="min-w-0 flex-1 rounded-2xl bg-muted/50 px-3 py-2">
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
                        <CopyFeedTextButton
                          text={formatCommentForClipboard(commentName, c.content)}
                          label="Kopiera kommentar"
                        />
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </li>
          )
        })}
      </ul>

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
              Vem menades med {mentionPick.label}?
            </h4>
            <ul className="mt-3 space-y-2">
              {mentionPick.userIds.map((userId) => (
                <li key={userId}>
                  <AgentNameButton
                    name={agentLabel(agents, userId)}
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
              Avbryt
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function variantSummary(variant: OasisVariantResult): string {
  if (variant.error) return "misslyckades"
  const posts = variant.posts?.length ?? 0
  const meas = (variant.measurements ?? []).reduce(
    (n, row) => n + row.points.length,
    0,
  )
  const ticks =
    typeof variant.ticks_run === "number" ? `${variant.ticks_run} tickar · ` : ""
  const measPart = meas > 0 ? ` · ${meas} mätpunkter` : ""
  return `${ticks}${posts} inlägg${measPart}`
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
  defaultOpen,
  onDelete,
  deleting,
  selected,
  onToggleSelect,
  onOrderReport,
  ordering,
  branchMode,
}: {
  attempt: OasisAttemptResult
  index: number
  total: number
  defaultOpen: boolean
  onDelete?: (attemptId: string) => void
  deleting?: boolean
  selected?: boolean
  onToggleSelect?: (attemptId: string) => void
  onOrderReport?: (attemptId: string) => void
  ordering?: boolean
  branchMode?: BranchMode | null
}) {
  const variants = attempt.variants ?? []
  const stimulusVariant = variants.find((v) => v.id === "a")
  const controlVariant = variants.find((v) => v.id === "b")
  const showStimulusControl =
    stimulusVariant &&
    controlVariant &&
    isStimulusControlPair(variants, branchMode)
  const postCount = variants.reduce((n, v) => n + (v.posts?.length ?? 0), 0)
  const stamp = formatWhen(attempt.finished_at)
  const metaParts = [
    total > 1 ? `Körning ${total - index}` : null,
    attempt.engine ?? null,
    variants.length > 1 ? `${variants.length} varianter` : null,
    `${postCount} inlägg`,
  ].filter(Boolean)
  const single = variants.length === 1
  const canDelete = Boolean(onDelete && attempt.id)
  const hasData = attemptHasData(attempt)

  return (
    <details
      className="group rounded-md border border-border bg-card open:bg-card"
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-3 marker:content-none [&::-webkit-details-marker]:hidden">
        <div className="flex min-w-0 items-start gap-3">
          {onToggleSelect && hasData ? (
            <input
              type="checkbox"
              className="mt-1"
              checked={Boolean(selected)}
              aria-label={`Välj körning ${stamp}`}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              onChange={(e) => {
                e.stopPropagation()
                onToggleSelect(attempt.id)
              }}
            />
          ) : null}
          <div className="min-w-0">
            <time
              className="block font-mono text-sm font-semibold tabular-nums text-foreground"
              dateTime={attempt.finished_at ?? undefined}
            >
              {stamp}
            </time>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {metaParts.join(" · ")}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-0.5">
          {hasData && onOrderReport ? (
            <button
              type="button"
              className="rounded px-2 py-1 text-xs text-db-gold-700 hover:bg-db-gold-100 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
              disabled={ordering}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                onOrderReport(attempt.id)
              }}
            >
              {ordering ? "Genererar…" : "Beställ rapport"}
            </button>
          ) : null}
          {canDelete ? (
            <button
              type="button"
              className="rounded px-2 py-1 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
              disabled={deleting}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                onDelete?.(attempt.id)
              }}
            >
              {deleting ? "Raderar…" : "Radera"}
            </button>
          ) : null}
          {hasData ? <CopyAttemptButton attempt={attempt} disabled={deleting} /> : null}
          <span className="text-xs text-muted-foreground group-open:hidden">
            Visa ▾
          </span>
          <span className="hidden text-xs text-muted-foreground group-open:inline">
            Dölj ▴
          </span>
        </div>
      </summary>

      <div className="border-t border-border px-4 py-3">
        {attempt.error ? (
          <p className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {attempt.error}
          </p>
        ) : null}

        {showStimulusControl ? (
          <StimulusControlComparison
            stimulus={stimulusVariant}
            control={controlVariant}
          />
        ) : null}

        {single ? (
          <VariantBody variant={variants[0]} />
        ) : (
          <div className="flex flex-col gap-2">
            {variants.map((variant, vi) => (
              <details
                key={variant.id}
                className="rounded-md border border-border/80 bg-muted/20"
                open={vi === 0}
              >
                <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 px-3 py-2.5 marker:content-none [&::-webkit-details-marker]:hidden">
                  <div className="flex items-center gap-2">
                    {variant.id === "a" || variant.id === "b" ? (
                      <span
                        className={
                          "inline-grid h-5 min-w-5 place-items-center rounded px-1 text-[11px] font-semibold " +
                          (variant.id === "a"
                            ? "bg-db-gold-100 text-db-gold-700"
                            : "bg-db-ink-200 text-db-ink-950")
                        }
                      >
                        {variant.id.toUpperCase()}
                      </span>
                    ) : null}
                    <span className="text-sm font-medium text-foreground">
                      {variant.label}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {variantSummary(variant)}
                    </span>
                  </div>
                </summary>
                <div className="border-t border-border/60 px-3 py-3">
                  <VariantBody variant={variant} />
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </details>
  )
}

type Props = {
  results: OasisRunResults
  status: string
  runId?: number
  branchMode?: BranchMode | null
  onDeleteAttempt?: (attemptId: string) => void | Promise<void>
  deletingAttemptId?: string | null
}

export function OasisResultsPanel({
  results,
  status,
  runId,
  branchMode = null,
  onDeleteAttempt,
  deletingAttemptId = null,
}: Props) {
  const navigate = useNavigate()
  const attempts = normalizeRunAttempts(results)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [orderingId, setOrderingId] = useState<string | null>(null)
  const [compareBusy, setCompareBusy] = useState(false)
  const [busyAttemptIds, setBusyAttemptIds] = useState<Set<string>>(new Set())
  const [orderError, setOrderError] = useState<string | null>(null)

  useEffect(() => {
    if (runId == null) return
    let cancelled = false
    let timer: number | undefined

    async function refreshBusy() {
      try {
        const reports = await listReports({ limit: 50 })
        if (cancelled) return
        const active = reports.filter(
          (r) =>
            (r.status === "pending" || r.status === "running") &&
            r.sources.some((s) => s.run_id === runId),
        )
        const next = new Set<string>()
        for (const r of active) {
          for (const s of r.sources) {
            if (s.run_id === runId) next.add(s.attempt_id)
          }
        }
        setBusyAttemptIds(next)
        timer = window.setTimeout(refreshBusy, active.length > 0 ? 2000 : 8000)
      } catch {
        if (!cancelled) timer = window.setTimeout(refreshBusy, 8000)
      }
    }

    void refreshBusy()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [runId])

  async function orderSources(
    sources: Array<{ run_id: number; attempt_id: string }>,
    title?: string,
  ) {
    if (!runId) return
    setOrderError(null)
    setBusyAttemptIds((prev) => {
      const next = new Set(prev)
      for (const s of sources) next.add(s.attempt_id)
      return next
    })
    const report = await createReport({ sources, title })
    navigate(`/reports/${report.id}`)
  }

  async function handleOrderOne(attemptId: string) {
    if (!runId) return
    if (busyAttemptIds.has(attemptId) || orderingId != null || compareBusy) return
    setOrderingId(attemptId)
    try {
      await orderSources([{ run_id: runId, attempt_id: attemptId }])
    } catch (err) {
      setBusyAttemptIds((prev) => {
        const next = new Set(prev)
        next.delete(attemptId)
        return next
      })
      setOrderError(err instanceof ApiError ? err.message : "Kunde inte beställa rapport")
    } finally {
      setOrderingId(null)
    }
  }

  async function handleCompare() {
    if (!runId || selected.size === 0) return
    if (compareBusy || orderingId != null) return
    if ([...selected].some((id) => busyAttemptIds.has(id))) return
    setCompareBusy(true)
    const ids = [...selected]
    try {
      await orderSources(
        ids.map((attempt_id) => ({ run_id: runId, attempt_id })),
        selected.size > 1 ? `Jämförelserapport (${selected.size} körningar)` : undefined,
      )
    } catch (err) {
      setBusyAttemptIds((prev) => {
        const next = new Set(prev)
        for (const id of ids) next.delete(id)
        return next
      })
      setOrderError(err instanceof ApiError ? err.message : "Kunde inte beställa rapport")
    } finally {
      setCompareBusy(false)
    }
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
  const compareDisabled = compareBusy || orderingId != null || selectionBusy
  const statusLabel =
    status in RUN_STATUS_LABEL
      ? RUN_STATUS_LABEL[status as RunStatus]
      : status

  if (attempts.length === 0) {
    if (status === "running") return null
    return (
      <div className="mb-9 rounded-md border border-border px-5 py-6 text-sm text-muted-foreground">
        Inga sparade resultat.
      </div>
    )
  }

  return (
    <div className="mb-9 flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">Resultat</h2>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {attempts.length} {attempts.length === 1 ? "körning" : "körningar"}
            {status !== "running" ? ` · ${statusLabel}` : null}
          </span>
          {runId && selected.size > 0 ? (
            <button
              type="button"
              className="rounded-md border border-db-gold-600 bg-db-gold-100 px-3 py-1.5 text-xs font-medium text-db-gold-800 hover:bg-db-gold-200 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={compareDisabled}
              onClick={() => void handleCompare()}
            >
              {compareBusy || selectionBusy
                ? "Genererar…"
                : selected.size === 1
                  ? "Beställ rapport"
                  : `Jämför i rapport (${selected.size})`}
            </button>
          ) : null}
        </div>
      </div>
      {orderError ? (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {orderError}
        </p>
      ) : null}
      {runId ? (
        <p className="text-xs text-muted-foreground">
          Bocka i flera körningar för att jämföra, eller beställ rapport per rad.
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
            defaultOpen={index === 0}
            onDelete={
              status === "running" || !onDeleteAttempt
                ? undefined
                : onDeleteAttempt
            }
            deleting={deletingAttemptId === attempt.id}
            selected={selected.has(attempt.id)}
            onToggleSelect={runId ? toggleSelect : undefined}
            onOrderReport={runId ? (id) => void handleOrderOne(id) : undefined}
            ordering={attemptBusy}
            branchMode={branchMode}
          />
        )
      })}
    </div>
  )
}
