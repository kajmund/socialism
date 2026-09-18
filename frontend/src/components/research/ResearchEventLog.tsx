import type { ResearchProgressEvent } from "@/api/execution"
import { useLocale, type MessageKey } from "@/i18n"

export function ResearchEventLog({ events }: { events: ResearchProgressEvent[] }) {
  const { t, intl } = useLocale()
  return (
    <details className="rounded-xl border border-white/10 bg-black/10">
      <summary className="cursor-pointer list-none p-4"><h2 className="text-sm font-semibold">{t("execution.researchMonitor.debugTitle")}</h2><p className="mt-1 text-xs text-muted-foreground">{t("execution.researchMonitor.debugIntro")}</p></summary>
      <div className="max-h-96 space-y-2 overflow-auto border-t border-white/10 p-4">
        {events.length === 0 ? <p className="text-sm text-muted-foreground">{t("execution.researchMonitor.noEvents")}</p> : [...events].reverse().map((event) => {
          const key = `execution.researchMonitor.eventTypes.${event.event_type}` as MessageKey
          return (
            <div key={event.id} className="grid gap-1 rounded-lg border border-white/5 bg-white/[0.02] p-3 md:grid-cols-[9rem_1fr]">
              <div className="text-xs text-muted-foreground"><div>{t("execution.researchMonitor.eventSequence", { sequence: event.sequence })}</div><div>{new Intl.DateTimeFormat(intl, { timeStyle: "medium" }).format(new Date(event.occurred_at))}</div></div>
              <div className="min-w-0"><p className="text-sm font-medium">{t(key)}</p><pre className="mt-1 overflow-auto whitespace-pre-wrap break-all text-[11px] text-muted-foreground">{JSON.stringify(event.payload, null, 2)}</pre></div>
            </div>
          )
        })}
      </div>
    </details>
  )
}
