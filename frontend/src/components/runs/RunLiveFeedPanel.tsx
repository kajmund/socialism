import { useEffect, useMemo, useState, type ReactNode } from "react"
import { getPopulation } from "@/api/populations"
import { LiveFeedList } from "@/components/runs/LiveFeedList"
import { useRunWatchSocket } from "@/components/runs/useRunWatchSocket"
import {
  mergeWatchAgents,
  ticksForVariant,
  watchAgentsFromPopulation,
} from "@/components/runs/watchAgents"
import type { PopulationMember } from "@/data/library-types"
import type { BranchState, Tick } from "@/data/runs-types"
import type { RunWatchVariantPlan } from "@/data/runWatch-types"
import { useLocale } from "@/i18n"

type Props = {
  runId: number
  variantPlans: RunWatchVariantPlan[]
  enabled: boolean
  populationId: number | null
  mainTicks: Tick[]
  branch: BranchState | null
}

export function RunLiveFeedPanel({
  runId,
  variantPlans,
  enabled,
  populationId,
  mainTicks,
  branch,
}: Props) {
  const { t } = useLocale()
  const [variantId, setVariantId] = useState(variantPlans[0]?.id ?? "main")
  const [members, setMembers] = useState<PopulationMember[]>([])
  const activeVariantId = variantPlans.some((plan) => plan.id === variantId)
    ? variantId
    : (variantPlans[0]?.id ?? "main")

  const live = useRunWatchSocket({
    runId,
    variantId: activeVariantId,
    enabled,
  })

  useEffect(() => {
    if (populationId == null) {
      setMembers([])
      return
    }
    let cancelled = false
    void getPopulation(populationId)
      .then((detail) => {
        if (!cancelled) setMembers(detail.members)
      })
      .catch(() => {
        if (!cancelled) setMembers([])
      })
    return () => {
      cancelled = true
    }
  }, [populationId])

  const populationAgents = useMemo(
    () =>
      watchAgentsFromPopulation(
        members,
        ticksForVariant(activeVariantId, mainTicks, branch),
      ),
    [members, activeVariantId, mainTicks, branch],
  )
  const agents = useMemo(
    () => mergeWatchAgents(populationAgents, live.agents),
    [populationAgents, live.agents],
  )

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
      <LiveFeedList
        rounds={live.rounds}
        agents={agents}
        ticks={live.ticks}
        emptyLabel={t("runs.live.waiting")}
      />
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
