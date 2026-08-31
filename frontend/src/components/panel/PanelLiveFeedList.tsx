import { Loader2 } from "lucide-react"
import type {
  PanelWatchPendingTurn,
  PanelWatchTurn,
  PanelWatchTurnPhase,
} from "@/data/panelWatch-types"
import { useLocale, type MessageKey } from "@/i18n"

const PHASE_LABEL_KEYS: Record<PanelWatchTurnPhase, MessageKey> = {
  opening: "dd.panel.live.phase.opening",
  sub_question: "dd.panel.live.phase.subQuestion",
  score: "dd.panel.live.phase.score",
  analysis: "dd.panel.live.phase.analysis",
  raise_hand: "dd.panel.live.phase.raiseHand",
  expert: "dd.panel.live.phase.expert",
  scratchpad: "dd.panel.live.phase.scratchpad",
  unanswered: "dd.panel.live.phase.unanswered",
}

function TurnRow({
  speaker,
  phase,
  content,
  roundIndex,
  inProgress,
}: {
  speaker: string
  phase: PanelWatchTurnPhase
  content: string | null
  roundIndex?: number | null
  inProgress?: boolean
}) {
  const { t } = useLocale()
  const phaseLabel = t(PHASE_LABEL_KEYS[phase])

  return (
    <li className="list-none rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-medium text-foreground">{speaker}</span>
        <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
          {phaseLabel}
        </span>
        {roundIndex != null ? (
          <span className="text-xs text-muted-foreground">
            {t("dd.panel.live.round", { round: roundIndex })}
          </span>
        ) : null}
        {inProgress ? (
          <span className="inline-flex items-center gap-1 text-xs text-db-gold-700">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            {t("dd.panel.live.turnInProgress")}
          </span>
        ) : null}
      </div>
      {content ? (
        <p className="mt-2 whitespace-pre-wrap text-foreground">{content}</p>
      ) : null}
    </li>
  )
}

export function PanelLiveFeedList({
  turns,
  pendingTurn,
  emptyLabel,
}: {
  turns: PanelWatchTurn[]
  pendingTurn: PanelWatchPendingTurn | null
  emptyLabel: string
}) {
  const showPending =
    pendingTurn != null && !turns.some((turn) => turn.turn_id === pendingTurn.turn_id)

  if (turns.length === 0 && !showPending) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>
  }

  return (
    <ul className="flex max-h-[28rem] flex-col gap-2 overflow-y-auto">
      {turns.map((turn) => (
        <TurnRow
          key={turn.turn_id}
          speaker={turn.speaker}
          phase={turn.phase}
          content={turn.content}
          roundIndex={turn.round_index}
        />
      ))}
      {showPending && pendingTurn ? (
        <TurnRow
          speaker={pendingTurn.speaker}
          phase={pendingTurn.phase}
          content={null}
          roundIndex={pendingTurn.round_index}
          inProgress
        />
      ) : null}
    </ul>
  )
}
