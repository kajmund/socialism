import { useMemo, useState } from "react"
import { LiveFeedList, type LiveFeedCatalog } from "@/components/runs/LiveFeedList"
import { LiveResultFeed } from "@/components/runs/LiveResultFeed"
import { buildLiveResultFeed } from "@/components/runs/buildLiveResultFeed"
import {
  ResultPaneToggle,
  paneShowsActivity,
  paneShowsFeed,
  type ResultPaneMode,
} from "@/components/runs/ResultPaneToggle"
import type { RunWatchAgent, RunWatchRound, RunWatchTick } from "@/data/runWatch-types"
import { useLocale } from "@/i18n"

export function LiveFeedSplitView({
  rounds,
  agents,
  ticks,
  seedCatalog,
  feedEmptyLabel,
  activityEmptyLabel,
  onOpenAgent,
}: {
  rounds: RunWatchRound[]
  agents: RunWatchAgent[]
  ticks: RunWatchTick[]
  seedCatalog?: LiveFeedCatalog
  feedEmptyLabel: string
  activityEmptyLabel: string
  onOpenAgent?: (userId: number) => void
}) {
  const { t } = useLocale()
  const [paneMode, setPaneMode] = useState<ResultPaneMode>("both")
  const showFeed = paneShowsFeed(paneMode)
  const showActivity = paneShowsActivity(paneMode)
  const split = showFeed && showActivity
  const built = useMemo(
    () => buildLiveResultFeed(rounds, seedCatalog),
    [rounds, seedCatalog],
  )

  return (
    <div>
      <div className="mb-3 flex justify-end">
        <ResultPaneToggle value={paneMode} onChange={setPaneMode} />
      </div>
      <div className={split ? "grid gap-4 lg:grid-cols-2" : undefined}>
        {showFeed ? (
          <section className="min-w-0">
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t("runs.live.feedColumn")}
            </h3>
            <div className="max-h-[min(70vh,42rem)] overflow-y-auto pr-1">
              <LiveResultFeed
                catalog={built.catalog}
                postTick={built.postTick}
                agents={agents}
                ticks={ticks}
                emptyLabel={feedEmptyLabel}
                onOpenAgent={onOpenAgent}
              />
            </div>
          </section>
        ) : null}
        {showActivity ? (
          <section
            className={
              split
                ? "min-w-0 lg:border-l lg:border-border/60 lg:pl-4"
                : "min-w-0"
            }
          >
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t("runs.live.activityColumn")}
            </h3>
            <div className="max-h-[min(70vh,42rem)] overflow-y-auto pr-1">
              <LiveFeedList
                rounds={rounds}
                agents={agents}
                ticks={ticks}
                emptyLabel={activityEmptyLabel}
                catalog={built.catalog}
                onOpenAgent={onOpenAgent}
              />
            </div>
          </section>
        ) : null}
      </div>
    </div>
  )
}
