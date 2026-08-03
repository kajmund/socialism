import { useState } from "react"
import type {
  OasisAttemptResult,
  OasisMeasurementPoint,
  OasisMeasurementRow,
  OasisRunResults,
  OasisVariantResult,
} from "@/data/runs-types"

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

function pct(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`
}

function MeasurementDetail({ point }: { point: OasisMeasurementPoint }) {
  const metrics = point.metrics
  const engagement = metrics?.engagement
  const sentiment = metrics?.sentiment
  const phrases = metrics?.top_phrases ?? []
  const districts = metrics?.by_district ?? []
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
          <span>{engagement.shares ?? 0} shares</span>
          <span>engagemang {engagement.engagement_score ?? 0}</span>
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
    </div>
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
}: {
  agents: NonNullable<OasisVariantResult["agents"]>
  userIds: number[]
  emptyLabel: string
}) {
  if (userIds.length === 0) {
    return <p className="px-1 py-0.5 text-xs text-muted-foreground">{emptyLabel}</p>
  }
  return (
    <ul className="max-h-40 overflow-auto py-0.5">
      {userIds.map((id) => (
        <li
          key={id}
          className="rounded px-2 py-1 text-xs text-foreground hover:bg-muted/60"
        >
          {agentLabel(agents, id)}
        </li>
      ))}
    </ul>
  )
}

function LikeShareBar({
  agents,
  likedBy,
  sharedBy,
  compact = false,
}: {
  agents: NonNullable<OasisVariantResult["agents"]>
  likedBy?: number[]
  sharedBy?: Array<{
    user_id: number
    kind: "repost" | "quote"
    share_post_id?: number
  }>
  compact?: boolean
}) {
  const likes = likedBy ?? []
  const shares = sharedBy ?? []
  const [open, setOpen] = useState<"like" | "share" | null>(null)

  function toggle(kind: "like" | "share") {
    setOpen((prev) => (prev === kind ? null : kind))
  }

  return (
    <div
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
                      className="flex items-center justify-between gap-2 rounded px-2 py-1 text-xs text-foreground hover:bg-muted/60"
                    >
                      <span>{agentLabel(agents, s.user_id)}</span>
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

function VariantBody({ variant }: { variant: OasisVariantResult }) {
  const posts = variant.posts ?? []
  const comments = variant.comments ?? []
  const agents = variant.agents ?? []
  const measurements = variant.measurements ?? []
  const postsById = new Map(posts.map((p) => [p.post_id, p]))

  if (variant.error) {
    return (
      <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {variant.error}
      </p>
    )
  }

  return (
    <div>
      <MeasurementsSection rows={measurements} />

      {agents.length > 0 ? (
        <div className="mb-3 space-y-1 text-sm text-muted-foreground">
          {agents.some((a) => a.role === "injector") ? (
            <p>
              Injektorer:{" "}
              {agents
                .filter((a) => a.role === "injector")
                .map((a) => a.member_name || a.username)
                .join(", ")}
            </p>
          ) : null}
          <p>
            Population:{" "}
            {agents
              .filter((a) => a.role !== "injector")
              .map((a) => a.member_name || a.username)
              .join(", ") || "—"}
          </p>
        </div>
      ) : null}

      <h3 className="mb-2 text-sm font-semibold text-foreground">Inlägg</h3>

      {posts.length === 0 ? (
        <p className="text-sm text-muted-foreground">Inga inlägg sparades.</p>
      ) : null}

      <ul className="flex flex-col gap-3">
        {posts.map((post) => {
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
          const postComments = comments.filter((c) => c.post_id === post.post_id)

          let kindLabel: string | null = null
          if (isInjector) kindLabel = "injektion"
          else if (isQuote) kindLabel = "citat"
          else if (isRepost) kindLabel = "delning"

          return (
            <li
              key={post.post_id}
              className="rounded-md border border-border bg-muted/30 px-3 py-2"
            >
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{author}</span>
                {kindLabel ? (
                  <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                    {kindLabel}
                  </span>
                ) : null}
                <span>#{post.post_id}</span>
              </div>

              {isQuote ? (
                <div className="space-y-2">
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {quote}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Citerar {originalAuthor ?? "okänd"} #{originalId}
                  </p>
                </div>
              ) : null}

              {isRepost ? (
                <p className="text-sm text-muted-foreground">
                  Delade inlägg från {originalAuthor ?? "okänd"} #{originalId}
                </p>
              ) : null}

              {!isQuote && !isRepost ? (
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {post.content}
                </p>
              ) : null}

              <LikeShareBar
                agents={agents}
                likedBy={post.liked_by}
                sharedBy={post.shared_by}
              />

              {postComments.length > 0 ? (
                <ul className="mt-2 space-y-2 border-t border-border/60 pt-2">
                  {postComments.map((c) => (
                    <li key={c.comment_id} className="text-xs text-muted-foreground">
                      <div>
                        <span className="font-medium text-foreground">
                          {agentLabel(agents, c.user_id)}:
                        </span>{" "}
                        {c.content}
                      </div>
                      <LikeShareBar
                        agents={agents}
                        likedBy={c.liked_by}
                        compact
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          )
        })}
      </ul>
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

function AttemptBlock({
  attempt,
  index,
  total,
  defaultOpen,
  onDelete,
  deleting,
}: {
  attempt: OasisAttemptResult
  index: number
  total: number
  defaultOpen: boolean
  onDelete?: (attemptId: string) => void
  deleting?: boolean
}) {
  const variants = attempt.variants ?? []
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

  return (
    <details
      className="group rounded-md border border-border bg-card open:bg-card"
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-3 marker:content-none [&::-webkit-details-marker]:hidden">
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
        <div className="flex shrink-0 items-center gap-2 pt-0.5">
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
  onDeleteAttempt?: (attemptId: string) => void | Promise<void>
  deletingAttemptId?: string | null
}

export function OasisResultsPanel({
  results,
  status,
  onDeleteAttempt,
  deletingAttemptId = null,
}: Props) {
  const attempts = normalizeRunAttempts(results)

  if (attempts.length === 0) {
    return (
      <div className="mb-9 rounded-md border border-border px-5 py-6 text-sm text-muted-foreground">
        Inga sparade resultat.
        {status === "running" ? " Simulering pågår…" : null}
      </div>
    )
  }

  return (
    <div className="mb-9 flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">Resultat</h2>
        <span className="text-xs text-muted-foreground">
          {attempts.length} {attempts.length === 1 ? "körning" : "körningar"} ·{" "}
          {status}
        </span>
      </div>
      {attempts.map((attempt, index) => (
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
        />
      ))}
    </div>
  )
}
