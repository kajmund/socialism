import { useEffect, useRef, useState } from "react"
import { Activity } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useLocale } from "@/i18n"
import type { MessageKey } from "@/i18n"
import type { ModelTraceEntry, ModelTraceKind } from "./modelTrace"

function kindLabel(kind: ModelTraceKind, t: (key: MessageKey) => string): string {
  switch (kind) {
    case "context":
      return t("voiceWorkspaceChat.modelTraceContext")
    case "message":
      return t("voiceWorkspaceChat.modelTraceMessage")
    case "tools":
      return t("voiceWorkspaceChat.modelTraceTools")
    case "tool_call":
      return t("voiceWorkspaceChat.modelTraceToolCall")
    case "tool_result":
      return t("voiceWorkspaceChat.modelTraceToolResult")
    default: {
      const _exhaustive: never = kind
      return _exhaustive
    }
  }
}

export function ModelTraceButton({ entries }: { entries: ModelTraceEntry[] }) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (open) end.current?.scrollIntoView({ block: "end" })
  }, [open, entries])
  return (
    <>
      <button
        type="button"
        className="ml-auto mb-1 grid size-9 shrink-0 place-items-center rounded-lg text-muted-foreground hover:bg-db-ink-50 hover:text-db-ink-950"
        aria-label={t("voiceWorkspaceChat.modelTrace")}
        onClick={() => setOpen(true)}
      >
        <Activity size={16} />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="theme-admin flex max-h-[80vh] max-w-2xl flex-col gap-3">
          <DialogHeader>
            <DialogTitle>{t("voiceWorkspaceChat.modelTrace")}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-2 overflow-auto pr-1">
            {entries.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("voiceWorkspaceChat.modelTraceEmpty")}</p>
            ) : entries.map((entry) => <TraceRow key={entry.id} entry={entry} label={kindLabel(entry.kind, t)} />)}
            <div ref={end} />
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

function TraceRow({ entry, label }: { entry: ModelTraceEntry; label: string }) {
  const border = entry.kind === "tool_call" || entry.kind === "tools" ? "border-db-gold-500" : "border-db-ink-200"
  const argumentsText = entry.arguments ? JSON.stringify(entry.arguments, null, 2) : ""
  const heading = [label, entry.model, entry.name].filter(Boolean).join(" · ")
  return (
    <article className={`rounded-lg border border-l-4 bg-white p-3 ${border}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {heading}
      </p>
      {entry.text ? <p className="mt-1 whitespace-pre-wrap text-sm">{entry.text}</p> : null}
      {argumentsText ? <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-db-ink-700">{argumentsText}</pre> : null}
    </article>
  )
}
