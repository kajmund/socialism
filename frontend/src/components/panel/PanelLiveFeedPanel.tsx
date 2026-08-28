import { PanelLiveFeedList } from "@/components/panel/PanelLiveFeedList"
import { usePanelWatchSocket } from "@/components/panel/usePanelWatchSocket"
import { useLocale } from "@/i18n"

type Props = {
  sessionId: string
  enabled: boolean
}

export function PanelLiveFeedPanel({ sessionId, enabled }: Props) {
  const { t } = useLocale()
  const live = usePanelWatchSocket({ sessionId, enabled })

  const statusLine = (() => {
    if (live.failedError) {
      return t("dd.panel.live.failed", { error: live.failedError })
    }
    if (live.finished) {
      return t("dd.panel.live.finished")
    }
    if (live.wsStatus === "connecting") {
      return t("dd.panel.live.connecting")
    }
    if (live.wsStatus === "closed" && enabled) {
      return t("dd.panel.live.reconnecting")
    }
    if (live.turns.length === 0 && live.pendingTurn == null) {
      return t("dd.panel.live.waiting")
    }
    return t("dd.panel.live.streaming")
  })()

  return (
    <div className="mt-4 rounded-lg border border-db-gold-500/30 bg-db-gold-50/20 p-4 ring-1 ring-db-gold-500/10">
      <div className="mb-3">
        <h3 className="text-base font-semibold text-foreground">{t("dd.panel.live.title")}</h3>
        <p className="text-sm text-muted-foreground">{statusLine}</p>
      </div>
      <PanelLiveFeedList
        turns={live.turns}
        pendingTurn={live.pendingTurn}
        emptyLabel={t("dd.panel.live.feedWaiting")}
      />
    </div>
  )
}
