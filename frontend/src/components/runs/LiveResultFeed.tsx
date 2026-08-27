import { useMemo, useState } from "react"
import { commentsByPostId } from "@/components/runs/buildLiveResultFeed"
import {
  FeedCommentCard,
  FeedPostSnippet,
  agentIsInjector,
  type FeedAgent,
  type FeedComment,
  type FeedPost,
} from "@/components/runs/feedChrome"
import type { LiveFeedCatalog } from "@/components/runs/LiveFeedList"
import type { RunWatchTick } from "@/data/runWatch-types"
import { useLocale } from "@/i18n"

function ResultPostCard({
  post,
  comments,
  agents,
  onOpenAgent,
  injection,
}: {
  post: FeedPost
  comments: FeedComment[]
  agents: FeedAgent[]
  onOpenAgent: (userId: number) => void
  injection: boolean
}) {
  const { t } = useLocale()
  return (
    <li className="list-none rounded-lg border border-border bg-card px-3 py-2.5 shadow-sm">
      {injection ? (
        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {t("runs.feed.injection")}
        </p>
      ) : null}
      <FeedPostSnippet post={post} agents={agents} onOpenAgent={onOpenAgent} />
      {comments.length > 0 ? (
        <ul className="mt-3 space-y-2 border-t border-border/60 pt-3">
          {comments.map((comment) => (
            <li key={comment.comment_id}>
              <FeedCommentCard
                comment={comment}
                agents={agents}
                onOpenAgent={onOpenAgent}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  )
}

export function LiveResultFeed({
  catalog,
  postTick,
  agents,
  ticks,
  emptyLabel,
  onOpenAgent,
}: {
  catalog: LiveFeedCatalog
  postTick: Map<number, number>
  agents: FeedAgent[]
  ticks: RunWatchTick[]
  emptyLabel: string
  onOpenAgent?: (userId: number) => void
}) {
  const { t } = useLocale()
  const [injectorsOpen, setInjectorsOpen] = useState(true)
  const openAgent = onOpenAgent ?? (() => {})
  const commentsMap = useMemo(
    () => commentsByPostId(catalog.comments),
    [catalog.comments],
  )
  const { injectorPosts, populationGroups } = useMemo(() => {
    const injector: FeedPost[] = []
    const byTick = new Map<number, FeedPost[]>()
    for (const post of catalog.posts ?? []) {
      if (agentIsInjector(agents, post.user_id)) {
        injector.push(post)
        continue
      }
      const tickIndex = postTick.get(post.post_id) ?? 0
      const bucket = byTick.get(tickIndex) ?? []
      bucket.push(post)
      byTick.set(tickIndex, bucket)
    }
    const groups = [...byTick.keys()]
      .sort((a, b) => b - a)
      .map((tickIndex) => {
        const tick = ticks.find((row) => row.tickIndex === tickIndex)
        return {
          tickIndex,
          day: tick?.day ?? tickIndex + 1,
          posts: byTick.get(tickIndex) ?? [],
        }
      })
    return { injectorPosts: injector, populationGroups: groups }
  }, [agents, catalog.posts, postTick, ticks])

  const hasPosts =
    injectorPosts.length > 0 ||
    populationGroups.some((group) => group.posts.length > 0)
  if (!hasPosts) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>
  }

  const injectorSectionId = "live-result-injectors"

  return (
    <div className="flex flex-col gap-3">
      {injectorPosts.length > 0 ? (
        <section className="rounded-lg border border-border bg-card/40">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-3 text-left"
            aria-expanded={injectorsOpen}
            aria-controls={injectorSectionId}
            onClick={() => setInjectorsOpen((open) => !open)}
          >
            <h4 className="text-sm font-semibold text-foreground">
              {t("runs.live.injectorsTitle", { count: injectorPosts.length })}
            </h4>
            <span className="ml-auto text-xs text-muted-foreground">
              {injectorsOpen
                ? t("runs.live.collapseInjectors")
                : t("runs.live.expandInjectors")}
            </span>
          </button>
          {injectorsOpen ? (
            <ul
              id={injectorSectionId}
              className="flex flex-col gap-2 border-t border-border/60 px-4 py-3"
            >
              {injectorPosts.map((post) => (
                <ResultPostCard
                  key={post.post_id}
                  post={post}
                  comments={commentsMap.get(post.post_id) ?? []}
                  agents={agents}
                  onOpenAgent={openAgent}
                  injection
                />
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {populationGroups.map((group) => (
        <section key={group.tickIndex} className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("runs.results.dayLabel", { day: group.day })}
          </h4>
          {group.posts.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("runs.feed.noPostsToday")}
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {group.posts.map((post) => (
                <ResultPostCard
                  key={post.post_id}
                  post={post}
                  comments={commentsMap.get(post.post_id) ?? []}
                  agents={agents}
                  onOpenAgent={openAgent}
                  injection={false}
                />
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  )
}
