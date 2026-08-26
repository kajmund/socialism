import { useEffect, useMemo, useState } from "react"
import { LiveFeedList } from "@/components/runs/LiveFeedList"
import { liveFeedFromVariant } from "@/components/runs/liveFeedFromVariant"
import type { OasisAttemptResult, OasisVariantResult } from "@/data/runs-types"
import { useLocale } from "@/i18n"

export function AttemptLiveFeedView({ attempt }: { attempt: OasisAttemptResult }) {
  const { t } = useLocale()
  const withFeed = useMemo(
    () =>
      (attempt.variants ?? []).filter((variant) => {
        const feed = liveFeedFromVariant(variant)
        return feed.rounds.some((round) => round.items.length > 0)
      }),
    [attempt],
  )
  const [variantId, setVariantId] = useState(withFeed[0]?.id ?? "")

  useEffect(() => {
    setVariantId((prev) =>
      withFeed.some((variant) => variant.id === prev)
        ? prev
        : (withFeed[0]?.id ?? ""),
    )
  }, [withFeed])

  const active: OasisVariantResult | undefined =
    withFeed.find((variant) => variant.id === variantId) ?? withFeed[0]
  const feed = active ? liveFeedFromVariant(active) : null

  if (!feed) {
    return (
      <p className="text-sm text-muted-foreground">{t("runs.results.liveFeedEmpty")}</p>
    )
  }

  return (
    <div className="space-y-3">
      {withFeed.length > 1 ? (
        <div className="view-toggle" role="tablist">
          {withFeed.map((variant) => (
            <button
              key={variant.id}
              type="button"
              role="tab"
              aria-selected={active?.id === variant.id}
              className={active?.id === variant.id ? "on" : undefined}
              onClick={() => setVariantId(variant.id)}
            >
              {variant.label}
            </button>
          ))}
        </div>
      ) : null}
      <div className="max-h-[min(70vh,36rem)] overflow-y-auto pr-1">
        <LiveFeedList
          key={active?.id ?? "none"}
          rounds={feed.rounds}
          agents={feed.agents}
          ticks={feed.ticks}
          emptyLabel={t("runs.results.liveFeedEmpty")}
          catalog={{
            posts: active?.posts,
            comments: active?.comments,
            follows: active?.follows,
            mutes: active?.mutes,
            reports: active?.reports,
          }}
        />
      </div>
    </div>
  )
}
